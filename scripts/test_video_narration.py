"""Offline AI narration and post-render quality checks for storyboard videos.

Run: python scripts/test_video_narration.py
Uses the speech voices installed on this computer (Windows speech or a configured Piper voice) and
real FFmpeg renders. Narration tests are skipped, not faked, when no English voice is installed.
"""
import io
import json
import os
import re
import sys
import tempfile
import time
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='video-narration-suite-')
os.environ.update(PUBLIC_TEST_MODE='true', PUBLIC_TEST_DATA_DIR=str(Path(TEMP.name) / 'guests'),
                  VIDEO_DATA_DIR=str(Path(TEMP.name) / 'video'), AGENCY_DATA_DIR=str(Path(TEMP.name) / 'agency'))
from fastapi.testclient import TestClient
from PIL import Image
import server
from image import campaign_generator
from video import voice as video_voice
from video.sequence import sequence_qa
from video.ffmpeg import ffmpeg, probe, run

ENGLISH = video_voice.voices('en')
LINES = ['Northwind helps small clinics run on time.', 'Booking, billing and reminders in one place.',
         'Book a free demo at northwind dot health.']


def silences(path):
    log = run(['-hide_banner', '-nostdin', '-i', str(path), '-af', 'silencedetect=n=-45dB:d=0.3', '-f', 'null', '-'], timeout=60)
    starts = [float(x) for x in re.findall(r'silence_start: (-?[\d.]+)', log)]
    ends = [float(x) for x in re.findall(r'silence_end: ([\d.]+)', log)]
    return list(zip(starts, ends + [probe(path)['duration']] * (len(starts) - len(ends))))


class Narration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.stack.enter_context(patch.object(campaign_generator.LexnisCampaignStudio, '_chat', side_effect=RuntimeError('Offline test provider')))
        cls.client = TestClient(server.app, base_url='http://localhost')
        cls.client.get('/')
        brand = cls.client.post('/api/brands', json=dict(brand_name='Northwind Health', primary_hex='#0f2a3d', secondary_hex='#3fb8af',
                                                          font_preferences=['Arial'], tagline='Clinics that run on time.'))
        assert brand.status_code == 201, brand.text
        cls.brand = brand.json()['brand']
        cls.briefs = {}
        for language in ('English', 'Arabic'):
            response = cls.client.post('/api/video/generate-brief', json=dict(
                brand_id=cls.brand['id'], core_message='Northwind runs clinic scheduling and billing. Book a free demo.' if language == 'English'
                else 'Ù†ÙˆØ±Ø«ÙˆÙŠÙ†Ø¯ ØªØ¯ÙŠØ± Ù…ÙˆØ§Ø¹ÙŠØ¯ Ø§Ù„Ø¹ÙŠØ§Ø¯Ø§Øª ÙˆØ§Ù„ÙÙˆØ§ØªÙŠØ±. Ø§Ø­Ø¬Ø² Ø¹Ø±Ø¶Ø§ Ù…Ø¬Ø§Ù†ÙŠØ§.', campaign_type='Brand Announcement',
                platform_target='Feed (1:1)', tone='Professional', language=language, duration=12, resolution=720,
                pacing='balanced', transition='cut'))
            assert response.status_code == 200, response.text
            cls.briefs[language] = response.json()

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()
        cls.client.close()
        TEMP.cleanup()

    def wait(self, job):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            value = self.client.get('/api/video/jobs/' + job['id']).json()
            if value['state'] == 'completed':
                return value['result']
            if value['state'] in {'failed', 'cancelled'}:
                raise AssertionError(value)
            time.sleep(.1)
        raise AssertionError('Render did not finish within 180 seconds')

    def scenes(self, lines=LINES):
        brief = self.briefs['English']
        scenes = [dict(scene) for scene in brief['scenes']][:len(lines)]
        cursor, length = 0.0, brief['request']['duration'] / len(lines)
        for scene, line in zip(scenes, lines):
            scene.update(voiceover=line, start=round(cursor, 3), duration=round(length, 3), asset_id=None)
            cursor += length
        return scenes

    def test_voice_list_is_local_and_language_filtered(self):
        body = self.client.get('/api/video/voices?language=en').json()
        self.assertEqual([v['id'] for v in body['voices']], [v['id'] for v in ENGLISH])
        for voice in body['voices']:
            self.assertEqual(voice['language'], 'en')
            self.assertNotIn('engine_voice', voice)  # local model paths are not exposed
        self.assertTrue(all(v['language'] == 'ar' for v in self.client.get('/api/video/voices?language=ar').json()['voices']))

    @unittest.skipUnless(ENGLISH, 'No English narrator voice installed on this computer')
    def test_narrated_render_is_timed_to_scenes_and_checked(self):
        voice = ENGLISH[0]['id']
        response = self.client.post('/api/video/render-sequence', json=dict(brief_id=self.briefs['English']['brief_id'],
                                                                            scenes=self.scenes(), narrator_voice=voice))
        self.assertEqual(response.status_code, 202, response.text)
        result = self.wait(response.json())
        self.assertTrue(result['has_voiceover'])
        self.assertEqual(result['narration']['engine'], ENGLISH[0]['engine'])
        quality = result['quality']
        self.assertTrue(quality['checks']['has_audio'])
        self.assertIsNotNone(quality['checks']['loudness']['integrated_lufs'])
        self.assertEqual(quality['checks']['black_segments'], [])
        self.assertTrue(quality['passed'], quality['warnings'])
        # Mastered: loudness lands on the -14 LUFS web/social target under the true-peak ceiling.
        delivery = {c['id']: c for c in json.loads(zipfile.ZipFile(io.BytesIO(self.client.get(result['bundle_zip_url']).content))
                                                   .read('quality-check.json'))['delivery']['checks']}
        self.assertEqual(delivery['loudness']['status'], 'PASS', delivery['loudness'])
        self.assertEqual(delivery['true_peak']['status'], 'PASS', delivery['true_peak'])
        self.assertEqual(delivery['caption_readability']['status'], 'PASS', delivery['caption_readability'])
        self.assertEqual(delivery['captions_visible']['status'], 'PASS', delivery['captions_visible'])
        kit =Path(TEMP.name) / 'kit.zip'
        kit.write_bytes(self.client.get(result['bundle_zip_url']).content)
        with zipfile.ZipFile(kit) as bundle:
            names = set(bundle.namelist())
            self.assertTrue({'audio/narration.wav', 'quality-check.json', 'video/campaign.mp4', 'cover.jpg', 'copy/subtitles.vtt'} <= names)
            self.assertTrue(bundle.read('copy/subtitles.vtt').decode('utf-8').startswith('WEBVTT'))
            narration = Path(TEMP.name) / 'narration.wav'
            narration.write_bytes(bundle.read('audio/narration.wav'))
            video = Path(TEMP.name) / 'campaign.mp4'
            video.write_bytes(bundle.read('video/campaign.mp4'))
            project = json.loads(bundle.read('project.json'))
            with Image.open(io.BytesIO(bundle.read('cover.jpg'))) as cover:
                self.assertEqual(cover.size, (720, 720))
        self.assertTrue(result['cover_url'] and self.client.get(result['cover_download_url']).status_code == 200)
        meta = probe(video)
        self.assertTrue(meta['has_audio'])
        self.assertAlmostEqual(meta['duration'], 12, delta=.12)
        # Speech sits inside each scene window, with quiet at every cut.
        spoken = result['narration']['scenes']
        for scene, part in zip(self.scenes(), spoken):
            self.assertGreaterEqual(part['start'], scene['start'])
            self.assertLessEqual(part['end'], scene['start'] + scene['duration'] - video_voice.TAIL + .01)
        quiet = silences(narration)
        for scene in self.scenes()[1:]:
            self.assertTrue(any(a - .05 <= scene['start'] <= b + .05 for a, b in quiet), (scene['start'], quiet))
        voiced = sum(part['end'] - part['start'] for part in spoken)
        self.assertGreater(voiced, 6)  # real speech, not a short beep
        # Subtitles are short cues timed to the narrator's words: every word kept once and in order,
        # no cue across a scene cut, none shown before its words are spoken (beyond a short lead-in).
        cues = project['caption_tracks'][0]['segments']
        self.assertGreaterEqual(len(cues), len(LINES))
        self.assertEqual(' '.join(c['text'] for c in cues).split(), ' '.join(LINES).split())
        cuts = [scene['start'] for scene in self.scenes()[1:]]
        for previous, cue in zip([None] + cues, cues):
            self.assertLess(cue['start'], cue['end'])
            self.assertFalse(any(cue['start'] + .05 < cut < cue['end'] - .05 for cut in cuts), (cue, cuts))
            if previous:
                self.assertLessEqual(previous['end'], cue['start'] + .001)
        words = result['narration']['scenes']
        self.assertGreaterEqual(cues[0]['start'], words[0]['start'] - .2)
        self.assertEqual(result['captions']['timing'], 'narrator word timings')
        self.assertEqual(result['captions']['cues'], len(cues))
        self.assertEqual(result['narration']['word_timing'], 'engine word events' if ENGLISH[0]['engine'] == 'windows' else 'estimated from the voiced audio')

    @unittest.skipUnless(ENGLISH, 'No English narrator voice installed on this computer')
    def test_word_timings_follow_the_voice_for_numbers_and_addresses(self):
        with tempfile.TemporaryDirectory() as work:
            lines = video_voice.record(['Over 120 clinics run on time.', 'Visit northwind.health today.'], ENGLISH[0],
                                       [Path(work) / 'a.wav', Path(work) / 'b.wav'])
        first, second = lines
        # The words on screen are the words written, even where the voice says them differently.
        self.assertEqual([w['word'] for w in first['words']], 'Over 120 clinics run on time.'.split())
        self.assertEqual([w['word'] for w in second['words']], ['Visit', 'northwind.health', 'today.'])
        self.assertEqual(second['spoken_text'], 'Visit northwind dot health today.')
        for line in lines:
            starts = [w['start'] for w in line['words']]
            self.assertEqual(starts, sorted(starts))
            self.assertTrue(all(w['end'] > w['start'] for w in line['words']))
            begin, finish = line['speech']
            self.assertLess(abs(line['words'][0]['start'] - begin), .25)
            self.assertLessEqual(line['words'][-1]['end'], finish + .01)
        # "northwind dot health" is three spoken words, so the address is on air longer than "Visit".
        visit, address = second['words'][:2]
        self.assertGreater(address['end'] - address['start'], visit['end'] - visit['start'])

    @unittest.skipUnless(ENGLISH, 'No English narrator voice installed on this computer')
    def test_fit_timings_follow_the_narration_and_keep_the_total(self):
        lines = ['Hello.', 'Northwind brings booking, billing and reminders into one simple place for every clinic team.', 'Book a demo.']
        body = dict(voice_id=ENGLISH[0]['id'], lines=lines, durations=[4, 4, 4])
        response = self.client.post('/api/video/voices/fit', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        fitted = response.json()
        self.assertAlmostEqual(sum(fitted['durations']), 12, delta=.001)
        self.assertGreater(fitted['durations'][1], fitted['durations'][0])
        self.assertTrue(all(d >= 2 for d in fitted['durations']))
        self.assertTrue(video_voice.fit(fitted['spoken_seconds'][1], fitted['durations'][1])[1])
        self.assertEqual(self.client.post('/api/video/voices/fit', json=dict(body, durations=[1, 1.5, 1])).status_code, 400)
        self.assertEqual(self.client.post('/api/video/voices/fit', json=dict(body, durations=[4, 4])).status_code, 422)

    def test_subtitles_only_captions_are_paced_inside_each_scene(self):
        from video.sequence import caption_track, platform_profile
        brief = self.briefs['English']
        lines = ['A short opener for the clinic team.',
                 'Northwind brings booking, billing and reminders together so your team can focus on patients every single day.',
                 'Book a free demo today.']
        scenes, report = self.scenes(lines), {}
        track, caption_top = caption_track(scenes, brief['request'], brief['brand'], True, None, (720, 720),
                                           platform_profile('1:1', 'en'), '#ffffff', report)
        cues = track['segments']
        self.assertEqual(' '.join(c['text'] for c in cues).split(), ' '.join(lines).split())
        self.assertGreater(len(cues), len(lines))           # the long scene is split into readable cues
        for cue in cues:
            self.assertTrue(any(s['start'] - .001 <= cue['start'] and cue['end'] <= s['start'] + s['duration'] + .001 for s in scenes), cue)
        self.assertEqual(report['timing'], 'scene text paced across each scene')
        self.assertEqual(track['brand_style']['max_lines'], 2)
        self.assertTrue(caption_top and caption_top < 720 * (1 - .08))

    def test_storyboard_advice_follows_short_form_guidance(self):
        from video.sequence import storyboard_advice
        scenes = [dict(overlay_text='One two three four five six seven eight nine ten', duration=3, start=0),
                  dict(overlay_text='Short', duration=9, start=3), dict(overlay_text='Call now', duration=1.5, start=12)]
        advice = ' '.join(storyboard_advice(scenes, dict(platform_target='9:16', duration=31)))
        for expected in ('10 words', 'Scene 2 keeps one picture', '15-30 seconds', 'at least 2 seconds'):
            self.assertIn(expected, advice)
        calm = [dict(overlay_text='Meet Northwind', duration=4, start=i * 4) for i in range(3)]
        self.assertEqual(storyboard_advice(calm, dict(platform_target='16:9', duration=12)), [])

    @unittest.skipUnless(ENGLISH, 'No English narrator voice installed on this computer')
    def test_too_long_line_names_the_scene(self):
        long = ['Short opener.', 'This second line is far too long to be spoken comfortably inside a scene that only lasts four seconds '
                'because it keeps going with more and more detail about every single feature.', 'Book a demo.']
        with tempfile.TemporaryDirectory() as work, self.assertRaisesRegex(ValueError, r'^Scene 2 narration takes about'):
            video_voice.narrate(self.scenes(long), 'en', ENGLISH[0]['id'], 12, work)

    def test_invalid_narrator_requests_are_rejected_before_rendering(self):
        english = self.briefs['English']['brief_id']
        cases = [dict(brief_id=english, narrator_voice='not-installed-voice'),
                 dict(brief_id=english, narrator_voice='Bad Voice!')]
        if ENGLISH:
            cases.append(dict(brief_id=self.briefs['Arabic']['brief_id'], narrator_voice=ENGLISH[0]['id']))
        for body in cases:
            response = self.client.post('/api/video/render-sequence', json=body)
            self.assertIn(response.status_code, (400, 422), response.text)
        if ENGLISH:
            self.assertIn('does not speak Arabic', response.json()['detail'])

    def test_spoken_text_reads_addresses_and_symbols_naturally(self):
        cases = {'Visit https://www.lexnis.com/contact-us today.': 'Visit lexnis dot com slash contact us today.',
                 'Email hello@northwind.health & book now.': 'Email hello at northwind dot health and book now.',
                 'Support 24/7 with 99% uptime and AI tools.': 'Support twenty four seven with 99 percent uptime and A.I. tools.',
                 'Version 3.5 ships soon. Acme Inc. grows.': 'Version 3.5 ships soon. Acme Inc. grows.'}
        for text, heard in cases.items():
            self.assertEqual(video_voice.spoken_text(text, 'en'), heard)
        self.assertEqual(video_voice.spoken_text('خصم 50% & شحن', 'ar'), 'خصم 50 بالمئة و شحن')

    @unittest.skipUnless(ENGLISH, 'No English narrator voice installed on this computer')
    def test_preview_reports_fit_before_rendering(self):
        voice = ENGLISH[0]['id']
        short = self.client.post('/api/video/voices/preview', json=dict(voice_id=voice, text='Book a demo at northwind.health.', duration=4))
        self.assertEqual(short.status_code, 200, short.text)
        body = short.json()
        self.assertTrue(body['audio'].startswith('data:audio/wav;base64,'))
        self.assertTrue(body['fits'])
        self.assertIn('northwind dot health', body['heard_as'])
        long = self.client.post('/api/video/voices/preview', json=dict(voice_id=voice, duration=2,
                                text='This line keeps going with far more detail than anyone could say in two seconds.')).json()
        self.assertFalse(long['fits'])
        self.assertIn('Too long', long['message'])
        for bad in (dict(voice_id='nope', text='Hello'), dict(voice_id=voice, text='x' * 451), dict(voice_id=voice, text='Hi', language='fr')):
            self.assertIn(self.client.post('/api/video/voices/preview', json=bad).status_code, (400, 422))

    @unittest.skipUnless(ENGLISH, 'No English narrator voice installed on this computer')
    def test_agency_voiceover_is_real_speech_with_honest_metadata(self):
        from agency.tts import tts_engine
        result = tts_engine.generate_voiceover('Northwind keeps clinics on time.', voice_id='af_sarah', speed=1.0)
        try:
            self.assertIn(result['engine_used'], ('windows', 'piper'))
            self.assertTrue(result['voice_used'])
            self.assertEqual(result['substituted'], result['engine_used'] != 'kokoro')
            path = Path(result['file_path'])
            self.assertAlmostEqual(video_voice.wav_seconds(path), result['duration_seconds'], delta=.05)
            # Speech has pauses between words; the old placeholder was one continuous tone.
            self.assertTrue(silences(path) or result['duration_seconds'] < 1.5)
        finally:
            Path(result['file_path']).unlink(missing_ok=True)

    def test_quality_check_flags_black_frames_and_silence(self):
        clip = Path(TEMP.name) / 'black.mp4'
        ffmpeg(['-f', 'lavfi', '-i', 'color=c=black:s=320x240:d=1:r=30', '-f', 'lavfi', '-i', 'color=c=red:s=320x240:d=2:r=30',
                '-filter_complex', '[0:v][1:v]concat=n=2:v=1[v]', '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(clip)])
        qa = sequence_qa(clip, probe(clip), dict(request=dict(duration=3)), expect_audio=False)
        self.assertFalse(qa['passed'])
        self.assertEqual(len(qa['checks']['black_segments']), 1)
        self.assertTrue(any('Black frames' in text for text in qa['warnings']))
        self.assertTrue(any('silent' in text for text in qa['warnings']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
