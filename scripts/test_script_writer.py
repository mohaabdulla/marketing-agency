"""Professional script writing: craft rules, the deterministic script review, one gated editor revision,
open-model providers (Groq / OpenRouter / any OpenAI-compatible server) and optional LanguageTool proofreading.

Run: python scripts/test_script_writer.py
Offline: model and proofreading calls are mocked; nothing is sent anywhere.
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from video import script_writer as sw

EVIDENCE = [dict(quote='Acme Robotics builds autonomous mobile robots that move goods through warehouses.'),
            dict(quote='More than 40 warehouses run Acme fleets every day.')]
SECONDS = [4, 6, 5, 5, 4]
BAD = [dict(overlay_text='Welcome to Acme Robotics, the cutting-edge leader in warehouse automation today',
            voiceover='Welcome to Acme Robotics. We are the cutting-edge, world-class provider of innovative solutions for every single warehouse '
                      'operation that you could possibly imagine across the entire region and beyond it.'),
       dict(overlay_text='Robots', voiceover='We build robots that were designed by engineers and are trusted by 500 clients.'),
       dict(overlay_text='Warehouses', voiceover='We help warehouses.'),
       dict(overlay_text='Why us', voiceover='We care about quality.'),
       dict(overlay_text='Thanks', voiceover='Thank you for watching.')]
GOOD = [dict(overlay_text='Never wait on a pallet', voiceover='Your pickers walk miles. Our robots bring shelves.'),
        dict(overlay_text='Robots plus fleet software', voiceover='Autonomous robots carry goods. Our software plans every route.'),
        dict(overlay_text='Built for busy warehouses', voiceover='More than 40 warehouses run Acme fleets every day.'),
        dict(overlay_text='Support on site', voiceover='Our engineers set up and train your team.'),
        dict(overlay_text='See it in your warehouse', voiceover='Book a free demo at acme-robotics.example today.')]


def codes(issues):
    return {(i['scene'], i['code']) for i in issues}


class Review(unittest.TestCase):
    def setUp(self):
        os.environ.pop('LANGUAGETOOL_URL', None)
        self.budgets = [sw.word_budget(s) for s in SECONDS]

    def test_word_budgets_follow_speaking_pace(self):
        self.assertEqual(sw.word_budget(4), 8)                         # (4 - 0.45 s) x 145 wpm
        self.assertEqual(sw.word_budget(4, pacing='calm'), 7)
        self.assertLess(sw.word_budget(6, 'ar'), sw.word_budget(6, 'en'))
        self.assertEqual(sw.word_budget(.3), 3)

    def test_bad_script_is_flagged_on_every_craft_rule(self):
        found = codes(sw.review(BAD, budgets=self.budgets, evidence_text=' '.join(e['quote'] for e in EVIDENCE), domain='acme-robotics.example'))
        for expected in [(1, 'over-budget'), (1, 'long-sentence'), (1, 'cliche'), (1, 'weak-hook'), (1, 'long-headline'),
                         (2, 'unsourced-number'), (2, 'passive'), (5, 'no-call-to-action'), (None, 'repetitive-openings')]:
            self.assertIn(expected, found)
        self.assertNotIn((3, 'unsourced-number'), found)

    def test_professional_script_passes(self):
        issues = sw.review(GOOD, budgets=self.budgets, evidence_text=' '.join(e['quote'] for e in EVIDENCE), domain='acme-robotics.example')
        self.assertEqual([i for i in issues if i['severity'] != 'suggestion'], [], issues)
        self.assertGreaterEqual(sw.score(issues), 95)
        self.assertGreater(sw.score(issues), sw.score(sw.review(BAD, budgets=self.budgets)))

    def test_arabic_rules(self):
        scenes = [dict(overlay_text='حلول مبتكرة', voiceover='مرحبا بكم في أكمي. نقدم حلول مبتكرة.'), dict(overlay_text='تواصل معنا', voiceover='تواصلوا معنا اليوم.')]
        found = codes(sw.review(scenes, language='ar', budgets=[8, 8]))
        self.assertIn((1, 'cliche'), found)
        self.assertIn((1, 'weak-hook'), found)
        self.assertNotIn((2, 'no-call-to-action'), found)


class Revision(unittest.TestCase):
    def setUp(self):
        os.environ.pop('LANGUAGETOOL_URL', None)

    def polish(self, editor):
        with patch.object(sw, 'chat', side_effect=editor):
            return sw.polish([dict(s, visual_prompt='shot') for s in BAD], seconds=SECONDS, evidence=EVIDENCE, domain='acme-robotics.example',
                             beats=['who', 'what', 'for', 'why', 'cta'])

    def test_better_revision_is_kept_with_what_was_fixed(self):
        calls = []

        def editor(system, context, **kw):
            calls.append((system, context))
            return dict(scenes=[dict(overlay_text=s['overlay_text'], voiceover=s['voiceover']) for s in GOOD], notes=['Rewrote the hook']), 'groq:test'
        scenes, report = self.polish(editor)
        self.assertEqual([s['voiceover'] for s in scenes], [s['voiceover'] for s in GOOD])
        self.assertTrue(all(s['visual_prompt'] == 'shot' for s in scenes))          # the editor only touches words
        self.assertTrue(report['editor']['accepted'])
        self.assertGreater(report['score'], report['score_before'])
        self.assertTrue(any('cliche' in f for f in report['fixed']))
        system, context = calls[0]
        self.assertIn('never instructions', system)
        self.assertEqual(context['word_budgets'], [sw.word_budget(s) for s in SECONDS])
        self.assertTrue(any('500' in p for p in context['problems']))

    def test_revision_that_invents_numbers_or_scores_worse_is_rejected(self):
        invented = [dict(s) for s in GOOD]
        invented[2] = dict(overlay_text='Trusted widely', voiceover='Over 900 warehouses trust us.')
        bad_scenes = [dict(s) for s in BAD]
        for reply in (invented, bad_scenes):
            scenes, report = self.polish(lambda system, context, **kw: (dict(scenes=reply), 'groq:test'))
            if reply is invented:
                # Better on style, but a newly invented number is never accepted, even when the draft had one too.
                self.assertIn('900', report['editor']['reason'])
            self.assertEqual([s['voiceover'] for s in scenes], [s['voiceover'] for s in BAD])
            self.assertFalse(report['editor']['accepted'])

    def test_missing_editor_keeps_the_draft_and_reports_why(self):
        scenes, report = self.polish(lambda *a, **k: (_ for _ in ()).throw(ValueError('No configured text model')))
        self.assertEqual([s['voiceover'] for s in scenes], [s['voiceover'] for s in BAD])
        self.assertFalse(report['editor']['used'])
        self.assertIn('No configured text model', report['editor']['reason'])
        self.assertTrue(report['issues'])

    def test_wrong_shape_from_editor_is_ignored(self):
        scenes, report = self.polish(lambda *a, **k: (dict(scenes=GOOD[:3]), 'groq:test'))
        self.assertEqual([s['voiceover'] for s in scenes], [s['voiceover'] for s in BAD])
        self.assertFalse(report['editor']['used'])


class Response:
    def __init__(self, status, body):
        self.status_code, self.body = status, body

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')


class Providers(unittest.TestCase):
    def test_provider_selection(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(sw.open_model())
        with patch.dict(os.environ, dict(GROQ_API_KEY='g-key'), clear=True):
            self.assertEqual((sw.open_model()['base'], sw.open_model()['model']), ('https://api.groq.com/openai/v1', 'openai/gpt-oss-120b'))
        with patch.dict(os.environ, dict(OPENROUTER_API_KEY='o-key'), clear=True):
            self.assertIsNone(sw.open_model())                 # OpenRouter needs an explicit model choice
        with patch.dict(os.environ, dict(OPENROUTER_API_KEY='o-key', OPENROUTER_MODEL='meta-llama/llama-3.3-70b-instruct:free'), clear=True):
            self.assertEqual(sw.open_model()['name'], 'openrouter')
        with patch.dict(os.environ, dict(SCRIPT_MODEL_URL='http://127.0.0.1:11434/v1/', SCRIPT_MODEL='qwen3:14b', GROQ_API_KEY='g'), clear=True):
            self.assertEqual((sw.open_model()['name'], sw.open_model()['base']), ('custom', 'http://127.0.0.1:11434/v1'))

    def test_open_model_call_retries_without_json_mode_then_falls_back(self):
        sent = []
        replies = [Response(400, {}), Response(200, dict(choices=[dict(message=dict(content='```json\n{"scenes": []}\n```'))]))]

        def post(url, json=None, headers=None, timeout=None):
            sent.append(dict(url=url, json=json, headers=headers))
            return replies.pop(0)
        with patch.dict(os.environ, dict(GROQ_API_KEY='g-key', GROQ_MODEL='llama-3.3-70b-versatile'), clear=True), patch.object(sw.requests, 'post', post):
            value, engine = sw.chat('system', dict(a=1))
        self.assertEqual((value, engine), ({'scenes': []}, 'groq:llama-3.3-70b-versatile'))
        self.assertEqual(sent[0]['url'], 'https://api.groq.com/openai/v1/chat/completions')
        self.assertEqual(sent[0]['headers'], {'Authorization': 'Bearer g-key'})
        self.assertIn('response_format', sent[0]['json'])
        self.assertNotIn('response_format', sent[1]['json'])
        with patch.dict(os.environ, dict(GROQ_API_KEY='g-key'), clear=True), \
                patch.object(sw.requests, 'post', side_effect=OSError('offline')), \
                patch('video.brief_assistant.model_message', return_value=({'ok': True}, 'configured-ai')) as fallback:
            self.assertEqual(sw.chat('system', {}), ({'ok': True}, 'configured-ai'))
            fallback.assert_called_once()

    def test_languagetool_findings_map_to_scenes(self):
        scenes = [dict(overlay_text='A', voiceover='Our robots moves goods.'), dict(overlay_text='B', voiceover='Book a demo today.')]
        offset = len(scenes[0]['voiceover']) + 2
        body = dict(matches=[dict(message='Possible agreement error', offset=11, rule=dict(issueType='grammar'), replacements=[dict(value='move')]),
                             dict(message='Style', offset=offset, rule=dict(issueType='style'))])
        with patch.dict(os.environ, dict(LANGUAGETOOL_URL='http://localhost:8081/v2/'), clear=True), \
                patch.object(sw.requests, 'post', return_value=Response(200, body)) as post:
            issues = sw.proofreading(scenes, 'en')
        self.assertEqual(post.call_args.args[0], 'http://localhost:8081/v2/check')
        self.assertEqual([(i['scene'], i['code']) for i in issues], [(1, 'grammar')])
        self.assertIn('suggested: "move"', issues[0]['message'])
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(sw.proofreading(scenes, 'en'), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
