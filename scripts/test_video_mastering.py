"""Measured analysis, explainable edit decisions, delivery presets and post-render QA.

Every export assertion here is made on a file that FFmpeg actually rendered; nothing is mocked
except the speech model's words (the real model is exercised by the optional source review).
Optional: set LEXNIS_VIDEO_REGRESSION_SOURCE to a local talking-head video to run the same
checks on real footage. Such footage is not committed to the repository.
"""
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='lexnis-video-mastering-')
os.environ['VIDEO_DATA_DIR'] = TEMP.name
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from video_api import router
from video_security import VideoRequestLimits
from video_ffmpeg import ffmpeg, probe
from video_assets import ingest, path_for
from video_projects import Project, Clip, Canvas
import video_measure
import video_presets
import video_qa
from video_analysis import analyze_asset
from video_quick_edit import keep_ranges, punch_in_plan, caption_cues
from video_captions import caption_qa, DEFAULT_CAPTION_STYLES

app = FastAPI()
app.include_router(router)
app.add_middleware(VideoRequestLimits)
WORK = Path(TEMP.name) / 'fixtures'
WORK.mkdir()


def make(name, video, audio=None, seconds=4, extra=()):
    path = WORK / name
    args = ['-f', 'lavfi', '-i', video]
    if audio:
        args += ['-f', 'lavfi', '-i', audio]
    args += ['-t', str(seconds), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', *extra]
    if audio:
        args += ['-c:a', 'aac']
    ffmpeg(args + [str(path)])
    return path


def word(start, end, text, probability=.95):
    return dict(start=start, end=end, word=text, probability=probability)


def wait(client, job, seconds=240):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        state = client.get('/api/video/jobs/' + job['id']).json()
        if state['state'] in ('completed', 'failed', 'cancelled'):
            return state
        time.sleep(.2)
    raise AssertionError('job did not finish')


class MeasurementTests(unittest.TestCase):
    def test_loudness_and_interval_parsing(self):
        log = '''[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -17.3 LUFS
    Threshold: -29.1 LUFS

  Loudness range:
    LRA:        12.4 LU

  True peak:
    Peak:        0.5 dBFS
'''
        self.assertEqual({k: v for k, v in video_measure.parse_loudness(log).items() if k != 'method'},
                         dict(integrated_lufs=-17.3, loudness_range_lu=12.4, true_peak_dbtp=0.5))
        silent = video_measure.parse_loudness('Summary:\n I: -70.0 LUFS\n LRA: 0.0 LU\n Peak: -inf dBFS')
        self.assertIsNone(silent['true_peak_dbtp'])                    # unmeasurable stays None, never a default
        self.assertEqual(video_measure.parse_loudness('no summary here')['integrated_lufs'], None)
        log = 'black_start:0 black_end:1.5 black_duration:1.5\n lavfi.freezedetect.freeze_start: 2.0\n lavfi.freezedetect.freeze_end: 4.25'
        self.assertEqual(video_measure.parse_intervals(log, 'black_start', 'black_end'), [dict(start=0.0, end=1.5, duration=1.5)])
        self.assertEqual(video_measure.parse_intervals(log, 'freeze_start', 'freeze_end'), [dict(start=2.0, end=4.25, duration=2.25)])
        self.assertEqual(video_measure.parse_intervals('freeze_start: 1.0', 'freeze_start', 'freeze_end', until=5.0), [dict(start=1.0, end=5.0, duration=4.0)])
        self.assertEqual(video_measure.contrast_ratio((255, 255, 255), (0, 0, 0)), 21.0)
        self.assertLess(video_measure.contrast_ratio((120, 120, 120), (128, 128, 128)), 1.2)
        self.assertEqual(video_measure.audio_activity(0, 4, [dict(start=1, end=3)]), 0.5)

    def test_analysis_reports_measurements_not_constants(self):
        moving = ingest(make('moving.mp4', 'testsrc2=s=320x240:r=30000/1001', 'sine=frequency=440:sample_rate=44100', extra=['-af', 'volume=17dB']), 'moving.mp4')
        still = ingest(make('still.mp4', 'color=c=0x334455:s=320x240:r=25'), 'still.mp4')
        a, b = analyze_asset(moving['id']), analyze_asset(still['id'])
        self.assertGreaterEqual(a.analysis_version, 2)
        self.assertEqual((a.technical.fps_rational, a.technical.video_profile, a.technical.pix_fmt), ('30000/1001', 'High', 'yuv420p'))
        self.assertEqual(a.audio_metrics.sample_rate, 44100)           # read from the file, not assumed 48000
        self.assertGreater(a.audio_metrics.true_peak_dbtp, -3)         # a boosted sine is hot
        self.assertLess(a.audio_metrics.integrated_lufs, 0)
        self.assertIn('ITU-R BS.1770', a.audio_metrics.measurement_method)
        self.assertGreater(a.shots[0].motion_score, 0.2)
        self.assertEqual(b.shots[0].motion_score, 0.0)                 # a flat colour does not move
        self.assertNotEqual(a.shots[0].motion_score, b.shots[0].motion_score)
        self.assertIsNotNone(a.shots[0].sharpness_laplacian_var)
        self.assertEqual(a.shots[0].audio_activity_ratio, 1.0)
        self.assertIsNone(a.shots[0].speech_present)                   # no transcript: unknown, not False
        self.assertTrue(any('speech presence' in item for item in a.not_measured))
        self.assertFalse(b.has_audio)
        self.assertEqual((b.audio_metrics.true_peak_dbtp, b.audio_metrics.integrated_lufs, b.audio_metrics.sample_rate), (None, None, None))
        self.assertTrue(b.frozen_intervals)                            # the still clip is detected as frozen
        self.assertEqual(a.black_intervals, [])
        self.assertEqual(analyze_asset(moving['id']).created_at, a.created_at)   # cached by content hash
        self.assertEqual(probe(path_for(moving['id']))['variable_frame_rate'], False)


class EditorialTests(unittest.TestCase):
    def test_pauses_are_cut_by_meaning_with_evidence(self):
        words = [word(.2, .6, 'Hello'), word(1.6, 2.0, 'there.'), word(2.9, 3.3, 'Next'), word(3.4, 3.8, 'um', .9), word(4.0, 4.4, 'point.'),
                 word(5.9, 6.3, 'Bye.')]
        ranges, cuts = keep_ranges(6.5, words, silences=None)
        reasons = [c['reason'] for c in cuts]
        self.assertEqual(reasons.count('Long speech pause'), 2)        # 1.0s inside a sentence, and the 1.5s pause after "point."
        mid = next(c for c in cuts if c['start'] < 1)
        self.assertEqual((mid['start'], mid['end']), (.76, 1.44))      # 0.16s of air kept on each side
        self.assertFalse(any(2.0 < c['start'] < 2.9 for c in cuts))    # a 0.9s beat after a finished sentence is left alone
        long = next(c for c in cuts if c['start'] > 4.4)
        self.assertEqual((long['start'], long['end']), (4.65, 5.65))   # sentence-end pause keeps 0.25s each side
        self.assertIn('Recognized filler', reasons)
        for item in cuts:
            self.assertTrue(item['evidence'] and 0 < item['confidence'] <= 1 and item['removed_seconds'] > 0)
        self.assertAlmostEqual(sum(b - a for a, b in ranges) + sum(c['removed_seconds'] for c in cuts), 6.5, places=2)
        # Measured: the gap is not silent (laughter, a gesture) -> the pause is kept.
        _, audible = keep_ranges(6.5, words, silences=[])
        self.assertFalse(any(c['kind'] == 'pause' for c in audible))
        _, confirmed = keep_ranges(6.5, words, silences=[dict(start=.6, end=1.6), dict(start=4.4, end=5.9)])
        self.assertTrue(all(c['confidence'] > .85 for c in confirmed if c['kind'] == 'pause'))
        unsure = [word(.2, .6, 'Hello'), word(.7, 1.0, 'um', .4), word(1.1, 1.5, 'there.')]
        self.assertEqual(keep_ranges(1.7, unsure)[1], [])              # a doubtful "um" is not cut

    def test_punch_ins_follow_cuts_not_a_timer(self):
        self.assertEqual([s['scale'] for s in punch_in_plan([(0, 12)], True)], [1.0])           # one take, nothing measured: no zoom
        cut = punch_in_plan([(0, 3), (4, 7)], True, 1.08)
        self.assertEqual([s['scale'] for s in cut], [1.0, 1.08])        # a cut changes framing so the jump reads as intended
        self.assertIn('cut', cut[1]['reason'])
        self.assertEqual([s['scale'] for s in punch_in_plan([(0, 3), (4, 7)], False)], [1.0, 1.0])
        tight = punch_in_plan([(0, 3), (4, 7)], True, 1.1, face=dict(headroom=.03))
        self.assertEqual(tight[1]['scale'], 1.03)                      # little headroom: smaller punch-in keeps the head in frame

    def test_caption_cues_and_readability_review(self):
        words = [word(0, .3, 'Yes.'), word(.35, .7, 'It'), word(.7, 1.0, 'was'), word(1.0, 1.5, 'amazing.'), word(4, 4.2, 'Bye.')]
        cues = caption_cues(words, [(0, 5)])
        self.assertEqual([c['text'] for c in cues], ['Yes. It was amazing.', 'Bye.'])     # the flash-by "Yes." is joined
        self.assertGreaterEqual(round(cues[1]['end'] - cues[1]['start'], 3), .8)
        style = DEFAULT_CAPTION_STYLES['quick-social']
        bad = [dict(start=0, end=.3, text='Too fast to read this line at all'), dict(start=.2, end=3, text='word ' * 40),
               dict(start=4, end=6, text='Fine', words=[dict(word='Khawar', probability=.3)])]
        issues, stats = caption_qa(bad, style, 464, 832)
        codes = {i['code'] for i in issues}
        self.assertTrue({'too_short', 'reading_speed', 'overlap', 'truncated', 'low_confidence'} <= codes, codes)
        self.assertGreater(stats['max_characters_per_second'], 20)
        self.assertEqual(caption_qa([dict(start=0, end=2, text='Hello, how are you?')], style, 464, 832)[0], [])

    def test_transitions_are_not_added_by_default(self):
        from video_ai_editor import VideoAIEditor
        clips = [SimpleNamespace(kind='video', id=str(i), duration=3.0, transition=0.0) for i in range(3)]
        plan = VideoAIEditor.auto_polish(SimpleNamespace(clips=clips), None)
        self.assertFalse([op for op in plan.operations if op.operation_type == 'SET_TRANSITION'])
        self.assertTrue(any('left clean' in a for a in plan.assumptions))
        asked = VideoAIEditor.auto_polish(SimpleNamespace(clips=clips), SimpleNamespace(transition_preferences=['soft dissolve'], animation_style='', logo_asset_id=None))
        self.assertEqual(len([op for op in asked.operations if op.operation_type == 'SET_TRANSITION']), 2)

    def test_presets_are_labelled_and_never_upscale(self):
        self.assertEqual(video_presets.canvas_for(464, 832), (464, 832))
        self.assertEqual(video_presets.canvas_for(464, 832, '9:16'), (464, 824))        # cropped, not enlarged to 1080x1920
        self.assertEqual(video_presets.canvas_for(3840, 2160, None, 1920), (1920, 1080))
        self.assertEqual(video_presets.canvas_for(1920, 1080, '1:1', 1080), (1080, 1080))
        ebu, web, master = (video_presets.preset(x) for x in ('broadcast-ebu', 'web-youtube', 'source-master'))
        self.assertEqual(ebu['loudness']['integrated'], -23.0)
        self.assertEqual(web['loudness']['integrated'], -14.0)
        self.assertNotIn('EBU', web['label'])
        self.assertIsNone(video_presets.loudnorm_filter(master))
        self.assertEqual(video_presets.loudnorm_filter(web), 'loudnorm=I=-14.0:TP=-1.5:LRA=11.0')
        args = video_presets.video_encode_args(web)
        for pair in (('-profile:v', 'high'), ('-pix_fmt', 'yuv420p'), ('-color_primaries', 'bt709'), ('-color_trc', 'bt709'), ('-colorspace', 'bt709'), ('-movflags', '+faststart')):
            self.assertEqual(args[args.index(pair[0]) + 1], pair[1])
        self.assertEqual(video_presets.preset('unknown')['id'], 'web-youtube')
        self.assertEqual(len(video_presets.public()), 6)


class RenderedOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = TestClient(app)
        # 29.97 fps, 44.1 kHz and very hot audio: three things an export must handle deliberately.
        source = make('talk.mp4', 'testsrc2=s=480x640:r=30000/1001', 'sine=frequency=330:sample_rate=44100', seconds=6, extra=['-af', 'volume=19dB'])
        cls.source_bytes = source.read_bytes()
        cls.asset = cls.http.post('/api/video/upload', files={'file': ('talk.mp4', cls.source_bytes)}).json()
        logo = Image.new('RGBA', (240, 80), (0, 0, 0, 0))
        draw = ImageDraw.Draw(logo)
        draw.rectangle((0, 0, 239, 79), fill=(20, 120, 90, 255))
        draw.rectangle((30, 20, 110, 60), fill=(255, 255, 255, 255))
        draw.ellipse((150, 15, 210, 65), fill=(240, 200, 40, 255))
        buffer = io.BytesIO()
        logo.save(buffer, 'PNG')
        cls.logo = cls.http.post('/api/video/upload', files={'file': ('logo.png', buffer.getvalue())}).json()
        cls.transcript = dict(language='en', segments=[dict(words=[word(.2, .6, 'Hello,'), word(.6, 1.0, 'welcome.'), word(2.4, 2.8, 'This'),
                                                               word(2.8, 3.2, 'is'), word(3.2, 3.9, 'LEXNIS.'), word(4.9, 5.2, 'Okay'), word(5.2, 5.5, 'stop')])])

    def project(self, **brief):
        return self.http.post('/api/video/projects', json=dict(name='Talk', clips=[dict(asset_id=self.asset['id'], duration=6)],
                                                               editing_brief=dict(brief))).json()

    def edit(self, project, speech=True, **body):
        with patch('video_quick_edit.speech_status', return_value={'available': speech, 'reason': 'Install the optional local speech runtime and model to generate captions.'}), \
                patch('video_quick_edit.transcribe', return_value=self.transcript):
            response = self.http.post(f'/api/video/projects/{project["id"]}/quick-edit', json=dict(asset_id=self.asset['id'], language='en', **body))
            self.assertEqual(response.status_code, 202, response.text)
            state = wait(self.http, response.json())
        self.assertEqual(state['state'], 'completed', state)
        return state['result']

    def checks(self, result):
        return {c['id']: c for c in result['qa_report']['checks']}

    def test_direct_export_is_measured_and_explained(self):
        result = self.edit(self.project(logo_asset_id=self.logo['id']))
        report, qa, checks = result['edit_report'], result['qa_report'], self.checks(result)
        self.assertEqual(qa['counts']['FAIL'], 0, [c for c in qa['checks'] if c['status'] == 'FAIL'])
        for key in ('readable', 'duration', 'dimensions', 'frame_rate', 'video_codec', 'color_metadata', 'faststart', 'audio_format',
                    'true_peak', 'logo_visible', 'logo_aspect', 'captions_visible', 'caption_contrast', 'duration_explained', 'source_unchanged'):
            self.assertEqual(checks[key]['status'], 'PASS', checks[key])
        meta = probe(path_for(result['id']))                            # read the real file again, independently of the report
        self.assertEqual(meta['fps_rational'], '30000/1001')            # 29.97 is not rounded to 30
        self.assertEqual((meta['video_profile'], meta['pix_fmt'], meta['audio_sample_rate']), ('High', 'yuv420p', 48000))
        self.assertEqual([meta[k] for k in ('color_primaries', 'color_transfer', 'color_space', 'color_range')], ['bt709', 'bt709', 'bt709', 'tv'])
        loud = video_measure.loudness(path_for(result['id']))
        self.assertLessEqual(loud['true_peak_dbtp'], -1.4)             # the hot source is under the -1.5 dBTP web ceiling
        self.assertGreater(float(checks['caption_contrast']['measured']['minimum_ratio']), 4.5)
        self.assertAlmostEqual(report['source_duration'] - report['duration_removed'], meta['duration'], delta=.2)
        self.assertTrue(all(d['reason'] and d['evidence'] for d in report['decisions']))
        types = [d['type'] for d in report['decisions']]
        for kind in ('CUT', 'TRANSITION', 'CAPTIONS', 'LOGO', 'AUDIO'):
            self.assertIn(kind, types)
        self.assertEqual(report['delivery_preset']['id'], 'web-youtube')
        self.assertIn('true peak', ' '.join(report['warnings']).lower())    # the hot source is called out
        self.assertEqual(self.http.get('/api/video/media/' + self.asset['id']).content, self.source_bytes)
        saved = self.http.get('/api/video/projects/' + result['project_id']).json()
        videos = [c for c in saved['clips'] if c['kind'] == 'video']
        self.assertTrue(all(c['transition'] == 0 for c in videos))      # clean cuts
        self.assertTrue(all(c['zoom'] == c['zoom_start'] for c in videos))   # held framing, no continuous zoom
        self.assertTrue(all(c['fade_in'] == 0 for c in videos[1:]) and all(c['fade_out'] == 0 for c in videos[:-1]))

    def test_broadcast_preset_targets_r128_and_missing_captions_are_diagnosed(self):
        result = self.edit(self.project(), speech=False, delivery='broadcast-ebu', captions=True)
        report, qa, checks = result['edit_report'], result['qa_report'], self.checks(result)
        self.assertEqual(checks['captions_present']['status'], 'FAIL')
        self.assertIn('Install the optional local speech runtime', report['caption_diagnostic'])
        self.assertEqual(report['caption_count'], 0)
        self.assertEqual(qa['overall'], 'FAIL')                         # a requested deliverable is missing: not "finished"
        self.assertEqual(checks['logo_visible']['status'], 'NOT_CHECKED')   # no logo on the timeline: unknown, not PASS
        self.assertEqual(qa['preset']['loudness_target_lufs'], -23.0)
        loud = video_measure.loudness(path_for(result['id']))
        self.assertAlmostEqual(loud['integrated_lufs'], -23.0, delta=1.5)
        self.assertLessEqual(loud['true_peak_dbtp'], -1.9)
        self.assertEqual(report['zoom_segments'], 0)                    # no words: no framing change is invented
        self.assertEqual(report['cuts'], [])
        self.assertAlmostEqual(result['duration'], 6.0, delta=.2)       # nothing is removed without evidence

    def test_validator_fails_a_non_conforming_file_and_export_endpoint_reports(self):
        bad = ingest(make('bad.mp4', 'testsrc2=s=320x240:r=25', 'sine=frequency=500:sample_rate=22050', seconds=3,
                          extra=['-profile:v', 'baseline', '-ar', '22050', '-ac', '1', '-af', 'volume=20dB']), 'bad.mp4')
        project = Project(name='Check', canvas=Canvas(width=480, height=640, fps=30, fps_mode='original'),
                          clips=[Clip(asset_id=self.asset['id'], duration=6)], delivery_preset='web-youtube')
        report = video_qa.validate(bad, project, captions_requested=False)
        failed = {c['id'] for c in report['checks'] if c['status'] == 'FAIL'}
        self.assertTrue({'duration', 'dimensions', 'frame_rate', 'video_codec', 'color_metadata', 'audio_format', 'true_peak'} <= failed, failed)
        self.assertEqual(report['overall'], 'FAIL')
        body = dict(project=dict(name='Plain export', canvas=dict(width=320, height=240, fps=24), clips=[dict(asset_id=self.asset['id'], duration=2, volume=2)]))
        state = wait(self.http, self.http.post('/api/video/export', json=body).json())
        self.assertEqual(state['state'], 'completed', state)
        qa = state['result']['qa_report']
        self.assertEqual(qa['counts']['FAIL'], 0, [c for c in qa['checks'] if c['status'] == 'FAIL'])
        self.assertLessEqual(video_measure.loudness(path_for(state['result']['id']))['true_peak_dbtp'], -1.4)   # safety pass on a non-normalised export
        self.assertTrue(qa['true_peak_safety_pass']['applied'])
        presets = self.http.get('/api/video/export-presets').json()
        self.assertEqual({p['id'] for p in presets['presets']}, set(video_presets.PRESETS))
        self.assertIn('BS.1770', presets['note'])

    @unittest.skipUnless(os.environ.get('LEXNIS_VIDEO_REGRESSION_SOURCE') and Path(os.environ.get('LEXNIS_VIDEO_REGRESSION_SOURCE', '')).is_file(),
                         'Set LEXNIS_VIDEO_REGRESSION_SOURCE to a local talking-head video to run the real-footage review')
    def test_real_footage_review(self):
        source = Path(os.environ['LEXNIS_VIDEO_REGRESSION_SOURCE'])
        before = source.read_bytes()
        asset = self.http.post('/api/video/upload', files={'file': ('source.mp4', before)}).json()
        project = self.http.post('/api/video/projects', json=dict(name='Review', clips=[dict(asset_id=asset['id'], duration=asset['duration'])],
                                                                  editing_brief=dict(logo_asset_id=self.logo['id']))).json()
        state = wait(self.http, self.http.post(f'/api/video/projects/{project["id"]}/quick-edit', json=dict(asset_id=asset['id'], language='en')).json(), 900)
        self.assertEqual(state['state'], 'completed', state)
        result = state['result']
        qa, report = result['qa_report'], result['edit_report']
        self.assertEqual(qa['counts']['FAIL'], 0 if report['caption_count'] else 1, [c for c in qa['checks'] if c['status'] == 'FAIL'])
        meta = probe(path_for(result['id']))
        self.assertAlmostEqual(meta['fps'], asset['fps'], delta=.02)
        self.assertLessEqual(meta['duration'], asset['duration'] + .1)   # an edit never adds duration
        self.assertAlmostEqual(asset['duration'] - report['duration_removed'], meta['duration'], delta=.2)
        self.assertLessEqual(video_measure.loudness(path_for(result['id']))['true_peak_dbtp'], -1.4)
        self.assertEqual(source.read_bytes(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
