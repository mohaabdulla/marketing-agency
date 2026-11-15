"""Editorial gates of the guided video edit: request fulfilment, approval policy for weak cuts,
caption name review, purpose-driven framing, measured lighting correction, subject-mask
background treatment, platform safe zones and the separate editorial QA report.

Renders are real FFmpeg output and pixel checks read the rendered frames. The speech model's
words are supplied by the test; the matting model is replaced by a fixed elliptical matte so
the compositing itself is tested on every machine (the installed model is exercised by the
optional real-footage review in test_video_mastering.py).
"""
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='lexnis-video-editorial-')
os.environ['VIDEO_DATA_DIR'] = TEMP.name
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from video_api import router
from video_security import VideoRequestLimits
from video_ffmpeg import ffmpeg
from video_assets import path_for
from video_projects import Project
import video_editorial_qa
import video_grade
import video_measure
import video_platforms
import video_segmentation
from video_captions import DEFAULT_CAPTION_STYLES, caption_qa, render_caption_image, track_style, brand_caption_style
from video_quick_edit import (plan_cuts, punch_in_plan, likely_names, apply_corrections, requested, caption_cues,
                              AUTO_CUT_CONFIDENCE)

app = FastAPI()
app.include_router(router)
app.add_middleware(VideoRequestLimits)
WORK = Path(TEMP.name) / 'fixtures'
WORK.mkdir()
USER_REQUEST = 'change the background to make it more pro and add some words on the screen and edit the lighting and add some effect'


def word(start, end, text, probability=.95):
    return dict(start=start, end=end, word=text, probability=probability)


def wait(client, job, seconds=300):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        state = client.get('/api/video/jobs/' + job['id']).json()
        if state['state'] in ('completed', 'failed', 'cancelled'):
            return state
        time.sleep(.2)
    raise AssertionError('job did not finish')


class FixedMatte:
    """Stand-in matting engine: an ellipse in the middle of the frame is 'the subject'."""
    model = 'u2netp'

    def mask(self, rgb):
        height, width = rgb.shape[:2]
        yy, xx = np.mgrid[0:height, 0:width]
        inside = ((xx - width / 2) / (width * .22)) ** 2 + ((yy - height / 2) / (height * .3)) ** 2 <= 1
        return (inside * 255).astype('uint8')


class PolicyTests(unittest.TestCase):
    def test_changed_checkpoint_invalidates_the_loaded_provider(self):
        checkpoint=WORK/'operator-model.onnx';checkpoint.write_bytes(b'first model')
        video_segmentation._sessions.clear()
        with patch.object(video_segmentation,'installed_model',return_value='u2netp'), \
             patch.object(video_segmentation,'model_file',return_value=checkpoint), \
             patch.object(video_segmentation,'status',return_value={'available':True}), \
             patch.object(video_segmentation,'RembgProvider',side_effect=[object(),object()]) as create:
            first=video_segmentation.provider()
            self.assertIs(video_segmentation.provider(),first)
            checkpoint.write_bytes(b'replacement model version')
            self.assertIsNot(video_segmentation.provider(),first)
            self.assertEqual(create.call_count,2)
        video_segmentation._sessions.clear()

    def test_mask_propagation_follows_small_motion_and_rejects_scene_changes(self):
        import cv2
        rng=np.random.default_rng(42)
        before=cv2.GaussianBlur(rng.integers(30,220,(160,160),dtype='uint8'),(5,5),0)
        matte=np.zeros((160,160),'uint8');cv2.circle(matte,(75,80),38,255,-1)
        matrix=np.float32([[1,0,2],[0,1,0]])
        after=cv2.warpAffine(before,matrix,(160,160),borderMode=cv2.BORDER_REPLICATE)
        expected=cv2.warpAffine(matte,matrix,(160,160))>127
        actual,trusted=video_segmentation.propagate_mask(before,after,matte)
        self.assertTrue(trusted)
        binary=actual>127
        self.assertGreater(np.logical_and(binary,expected).sum()/np.logical_or(binary,expected).sum(),.96)
        _,trusted=video_segmentation.propagate_mask(before,np.full((160,160),255,'uint8'),matte)
        self.assertFalse(trusted)

    def test_brand_caption_snapshot_and_arabic_logical_line_order(self):
        from brand_guidelines import Rules
        snapshot, warnings = brand_caption_style(Rules(caption_color='#eecc22',caption_size=58,font_preferences=['Arial']))
        style=track_style(dict(brand_style=snapshot))
        self.assertEqual((style.fill,style.font_size,style.font_name),('#eecc22',58,'Arial'))
        text='مرحبا بكم في مكتبنا اليوم كان يوما رائعا لأن المطر كان يهطل'
        image=render_caption_image(text,720,1280,DEFAULT_CAPTION_STYLES['arabic-corporate'])
        self.assertEqual(' '.join(image.info['caption_layout']['logical_lines']),text)

    def test_weak_cuts_are_proposed_not_applied(self):
        words = [word(.2, .6, 'Hello'), word(.6, 1.0, 'there.'), word(6.0, 6.3, 'Okay,', .4), word(6.3, 6.6, "that's", .5), word(6.6, 6.9, 'it.', .45)]
        ranges, applied, proposed = plan_cuts(8, words)
        tail = next(c for c in proposed if c['kind'] == 'recording-direction')
        self.assertLess(tail['confidence'], AUTO_CUT_CONFIDENCE)
        self.assertTrue(tail['requires_approval'])
        self.assertFalse(any(c['kind'] == 'recording-direction' for c in applied))
        self.assertGreater(ranges[-1][1], 6.9)                                 # the doubtful phrase is still in the edit
        ranges, applied, proposed = plan_cuts(8, words, approved={tail['id']})
        self.assertEqual(proposed, [])
        approved = next(c for c in applied if 'recording instruction' in c['reason'])
        self.assertEqual(approved['approval'], 'approved by you')
        self.assertLess(ranges[-1][1], 6.1)
        sure = [word(.2, .6, 'Hello'), word(.6, 1.0, 'there.'), word(6.0, 6.3, 'Okay,', .7), word(6.3, 6.6, 'stop', .7)]
        _, applied, proposed = plan_cuts(8, sure)
        self.assertEqual(next(c for c in applied if 'recording instruction' in c['reason'])['approval'], 'review recommended')   # 0.6-0.8
        self.assertEqual(proposed, [])

    def test_framing_changes_need_a_purpose(self):
        one_take = [(0, 12)]
        self.assertEqual([s['scale'] for s in punch_in_plan(one_take, True, 1.06)], [1.0])       # no cut, no measured moment: nothing
        emphasis = [(5.2, 7.4, 'Emphasise the most animated sentence (gesture and expression)', 'Measured movement 1.4× the clip median')]
        plan = punch_in_plan(one_take, True, 1.06, None, emphasis)
        self.assertEqual([(s['start'], s['end'], s['scale']) for s in plan], [(0, 5.2, 1.0), (5.2, 7.4, 1.06), (7.4, 12, 1.0)])
        self.assertIn('Measured movement', plan[1]['evidence'])
        self.assertTrue(all(s['reason'] and s['evidence'] for s in plan))
        self.assertEqual([s['scale'] for s in punch_in_plan(one_take, False, 1.06, None, emphasis)], [1.0])
        across = punch_in_plan([(0, 3), (4, 7)], True, 1.08)
        self.assertEqual([s['scale'] for s in across], [1.0, 1.08])
        self.assertIn('jump', across[1]['reason'])
        self.assertEqual(punch_in_plan([(0, 3), (4, 7)], True, 1.1, dict(headroom=.03))[1]['scale'], 1.03)

    def test_names_requests_styles_and_platforms(self):
        words = [word(0, .3, 'We'), word(.3, .6, 'met'), word(.6, .9, 'Mr.'), word(.9, 1.2, 'Mee', .5), word(1.2, 1.5, 'and'), word(1.5, 1.9, 'Ahmad.', .2),
                 word(2.0, 2.3, 'It'), word(2.3, 2.6, 'was'), word(2.6, 3.0, 'great.')]
        names = {n['heard']: n['confidence'] for n in likely_names(words)}
        self.assertEqual(names, {'Mr': .95, 'Mee': .5, 'Ahmad': .2})           # sentence-initial "We"/"It" are not names
        fixed, applied = apply_corrections(words, {'mee': 'Khawar', 'Ahmad': 'Ahmed', 'unused': 'x'})
        self.assertEqual(applied, ['Mee', 'Ahmad'])
        self.assertEqual([w['word'] for w in fixed][3:6], ['Khawar', 'and', 'Ahmed.'])   # punctuation kept, confidence now certain
        self.assertEqual(fixed[5]['probability'], 1.0)
        self.assertEqual([k for k, _ in requested(USER_REQUEST)], ['background', 'lighting', 'text', 'effects'])
        self.assertEqual(requested('make it nice'), [])
        self.assertEqual(video_platforms.interpret_style('keep it professional but organic')[0], 'polished-organic')
        self.assertEqual(video_platforms.interpret_style('casual and authentic')[0], 'organic')
        self.assertEqual(video_platforms.interpret_style('fast, punchy, high energy')[0], 'high-energy')
        self.assertEqual(video_platforms.choose('for tiktok and instagram', 464, 832, 'ar'), 'tiktok-rtl')
        self.assertEqual(video_platforms.choose('for tiktok and instagram', 464, 832, 'en'), 'tiktok-ltr')
        self.assertEqual(video_platforms.choose('youtube', 1920, 1080), 'youtube-standard')
        self.assertEqual(video_platforms.choose('', 464, 832), 'generic-vertical')
        tiktok = video_platforms.profile('tiktok-ltr')
        self.assertEqual(tiktok['basis'], 'PRODUCT DEFAULT')
        # 4% from the physical bottom edge passes a generic margin, yet sits fully under the app interface.
        low_caption = [80, 720, 380, 790]
        self.assertGreater(790 / 832, 0.05)
        self.assertEqual(video_platforms.outside_share(low_caption, tiktok, 464, 832), 1.0)
        self.assertEqual(video_platforms.outside_share([60, 300, 380, 360], tiktok, 464, 832), 0.0)
        rtl = video_platforms.profile('tiktok-rtl')
        self.assertGreater(rtl['left'], rtl['right'])                         # buttons are mirrored for Arabic

    def test_lighting_proposal_is_measured_and_checked(self):
        frame = np.full((400, 300, 3), 215, 'uint8')                           # bright window
        frame[150:260, 110:190] = (70, 85, 120)                                # darker face region (BGR skin-like)
        face = dict(x=110 / 300, y=150 / 400, width=80 / 300, height=110 / 400)
        stats = video_grade.light_stats(frame, face)
        self.assertGreater(stats['backlight_difference'], .3)
        self.assertIn('backlit_subject', {f['code'] for f in video_grade.diagnose(stats)})
        grade = video_grade.propose(stats)
        self.assertGreater(grade['gamma'], 1.1)
        self.assertGreater(grade['highlights'], .3)
        self.assertFalse(video_grade.is_neutral(grade))
        self.assertEqual(video_grade.filters(video_grade.NEUTRAL), [])
        self.assertTrue(any(f.startswith('curves=') for f in video_grade.filters(grade)))
        ok, reasons, _ = video_grade.verify(stats, dict(stats, face_hue=(stats['face_hue'] + 30) % 360))
        self.assertFalse(ok)
        self.assertIn('skin hue', reasons[0])
        ok, reasons, _ = video_grade.verify(stats, dict(stats, clipped_highlights=stats['clipped_highlights'] + .05))
        self.assertFalse(ok)
        even = np.full((400, 300, 3), 120, 'uint8')
        even[::2] = 150
        self.assertEqual(video_grade.propose(video_grade.light_stats(even)), video_grade.NEUTRAL)

    def test_arabic_captions_render_inside_the_safe_area(self):
        text = 'مرحبا بكم في مكتبنا اليوم كان يوما رائعا لأن المطر كان يهطل'
        platform = video_platforms.profile('tiktok-rtl')
        left, top, right, bottom = video_platforms.safe_area(platform, 720, 1280)
        track = dict(style_id='arabic-corporate', y_pct=.66, max_width_pct=round((right - left) / 720 - .07, 4), x_center_pct=round((left + right) / 2 / 720, 4))
        style = track_style(track)
        image = render_caption_image(text, 720, 1280, style)
        layout = image.info['caption_layout']
        self.assertFalse(layout['truncated'])
        self.assertLessEqual(layout['lines'], 2)
        self.assertEqual(video_platforms.outside_share(layout['box'], platform, 720, 1280), 0.0)
        alpha = np.array(image)[:, :, 3]
        self.assertGreater((alpha > 200).sum(), 2000)                          # real pixels were drawn
        ys, xs = np.nonzero(alpha)
        self.assertGreaterEqual(xs.min(), left)
        self.assertLessEqual(xs.max(), right)
        # Shaped right-to-left text is not the same picture as the raw logical-order string drawn left to right.
        from PIL import ImageFont
        issues, _ = caption_qa([dict(start=0, end=4, text=text)], style, 720, 1280)
        self.assertFalse([i for i in issues if i['code'] in ('truncated', 'safe_zone')], issues)
        long = render_caption_image(text + ' ' + text + ' ' + text, 720, 1280, style).info['caption_layout']
        self.assertTrue(long['truncated'])                                     # over two lines is reported, never silently cut


class GuidedEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = TestClient(app)
        source = WORK / 'talk.mp4'
        # A dim, crushed scene with movement: left third near black, the rest a moving mid-grey pattern.
        ffmpeg(['-f', 'lavfi', '-i', "nullsrc=s=360x640:r=30,geq=lum='if(lt(X,W*0.3),2,95+55*sin((X+N*5)/37)*sin(Y/29)+18*sin(X*1.1)*sin(Y*.9))':cb=128:cr=128",
                '-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=48000', '-t', '8', '-af', 'volume=10dB', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], timeout=120)
        cls.source_bytes = source.read_bytes()
        cls.asset = cls.http.post('/api/video/upload', files={'file': ('talk.mp4', cls.source_bytes)}).json()
        logo = Image.new('RGBA', (240, 80), (20, 120, 90, 255))
        ImageDraw.Draw(logo).rectangle((30, 20, 110, 60), fill=(255, 255, 255, 255))
        buffer = io.BytesIO()
        logo.save(buffer, 'PNG')
        cls.logo = cls.http.post('/api/video/upload', files={'file': ('logo.png', buffer.getvalue())}).json()
        backdrop = Image.new('RGB', (360, 640), (10, 60, 140))
        buffer = io.BytesIO()
        backdrop.save(buffer, 'PNG')
        cls.backdrop = cls.http.post('/api/video/upload', files={'file': ('backdrop.png', buffer.getvalue())}).json()
        cls.words = [word(.2, .6, 'Hello,'), word(.6, 1.0, 'welcome.'), word(1.3, 1.6, 'We'), word(1.6, 1.9, 'met'), word(1.9, 2.3, 'Ahmad', .3),
                     word(2.3, 2.6, 'today.'), word(3.0, 3.4, 'It'), word(3.4, 3.7, 'was'), word(3.7, 4.3, 'productive.'),
                     word(6.6, 6.9, 'Okay,', .4), word(6.9, 7.2, "that's", .45), word(7.2, 7.5, 'it.', .4)]

    def project(self, creative_context=None, **brief):
        return self.http.post('/api/video/projects', json=dict(name='Talk', clips=[dict(asset_id=self.asset['id'], duration=8)],
                                                               creative_context=creative_context or {},
                                                               editing_brief=dict(logo_asset_id=self.logo['id'], **brief))).json()

    def edit(self, matting=False, creative_context=None, **body):
        transcript = dict(language='en', segments=[dict(words=self.words)])
        status = dict(available=matting, model='u2netp' if matting else None, privacy='local',
                      reason='Subject-aware background editing is available.' if matting else
                      'Subject-aware background editing requires the optional segmentation model. Run: python scripts/setup_video_matting.py')
        with patch('video_quick_edit.speech_status', return_value={'available': True, 'reason': ''}), patch('video_quick_edit.transcribe', return_value=transcript), \
                patch.object(video_segmentation, 'status', return_value=status), patch.object(video_segmentation, 'installed_model', return_value='u2netp' if matting else None), \
                patch.object(video_segmentation, 'provider', return_value=FixedMatte()):
            response = self.http.post(f'/api/video/projects/{self.project(creative_context=creative_context, person_name="Sara Ali", person_position="Engineer")["id"]}/quick-edit',
                                      json=dict(asset_id=self.asset['id'], language='en', instruction=USER_REQUEST + '. Platform: TikTok.', **body))
            self.assertEqual(response.status_code, 202, response.text)
            state = wait(self.http, response.json())
        self.assertEqual(state['state'], 'completed', state)
        return state['result']

    def fulfilment(self, result):
        return {r['request']: r for r in result['edit_report']['request_fulfilment']}

    def editorial(self, result):
        return {c['id']: c for c in result['editorial_report']['checks']}

    def test_request_is_answered_and_weak_evidence_blocks_ready(self):
        result = self.edit(matting=False)
        report, editorial = result['edit_report'], result['editorial_report']
        requests = self.fulfilment(result)
        self.assertEqual(set(requests), {'background', 'lighting', 'text', 'effects'})
        self.assertEqual(requests['background']['status'], 'UNSUPPORTED')        # never claimed, never silently dropped
        self.assertIn('setup_video_matting.py', requests['background']['detail'])
        self.assertFalse(any(d['type'] == 'BACKGROUND' for d in report['decisions']))
        self.assertEqual(requests['lighting']['status'], 'FULFILLED')
        self.assertEqual(requests['text']['status'], 'FULFILLED')
        self.assertIn('lower third', requests['text']['detail'])
        self.assertEqual(requests['effects']['status'], 'FULFILLED')
        # The 40% "Okay, that's it." is proposed, not cut.
        self.assertEqual(len(report['proposed_cuts']), 1)
        self.assertAlmostEqual(result['duration'], 8.0, delta=.6)
        self.assertEqual(report['caption_state'], 'needs-review')
        self.assertEqual([n['heard'] for n in report['caption_review']['unresolved']], ['Ahmad'])
        self.assertEqual(editorial['caption_review'], 'REQUIRED')
        self.assertEqual(editorial['publish_readiness'], 'DRAFT')
        self.assertEqual(editorial['editorial_status'], 'NEEDS REVIEW')
        self.assertEqual(result['qa_report']['counts']['FAIL'], 0)              # the file itself is technically fine: gates are separate
        self.assertEqual(editorial['technical_status'], result['qa_report']['overall'])
        checks = self.editorial(result)
        self.assertEqual(checks['review']['status'], 'FAIL')
        self.assertEqual(checks['pending_cuts']['status'], 'WARNING')
        self.assertEqual(checks['hook_strength']['status'], 'NOT_CHECKED')      # not judged, and not faked
        self.assertEqual(checks['key_message']['status'], 'NOT_CHECKED')
        self.assertEqual(checks['request']['measured'], 'UNSUPPORTED')
        self.assertFalse(report['ai_text_planner_used'])
        self.assertIn('Semantic AI planner unavailable', report['semantic_planner'])
        self.assertEqual(report['platform_profile']['id'], 'tiktok-ltr')
        self.assertEqual(report['platform_profile']['basis'], 'PRODUCT DEFAULT')
        self.assertTrue(all(d['purpose'] and d['evidence'] and 'confidence' in d for d in report['decisions']))
        self.assertIn('LOWER_THIRD', [d['type'] for d in report['decisions']])
        self.assertEqual(self.http.get('/api/video/media/' + self.asset['id']).content, self.source_bytes)

    def test_lighting_correction_changes_real_pixels(self):
        result = self.edit(matting=False, captions=False, subtle_zooms=False)
        lighting = result['edit_report']['lighting']
        self.assertEqual(lighting['status'], 'CORRECTED')
        self.assertIn('crushed_shadows', {f['code'] for f in lighting['findings']})
        saved = self.http.get('/api/video/projects/' + result['project_id']).json()
        clip = next(c for c in saved['clips'] if c['kind'] == 'video')
        self.assertGreater(clip['shadows'], 0)                                  # a real timeline operation
        before = video_measure.frame_at(path_for(self.asset['id']), 4.5)
        after = video_measure.frame_at(path_for(result['id']), 4.5)
        region = (slice(250, 520), slice(150, 340))                             # mid-grey area, clear of captions/logo/lower third
        gain = float(after[region].mean()) - float(before[region].mean())
        self.assertGreater(gain, 2.0, 'shadows were lifted in the rendered frame')
        self.assertLess(float((after[region] > 250).mean()), .01)               # without blowing out
        off = self.edit(matting=False, captions=False, lighting='off', subtle_zooms=False)
        self.assertEqual(self.fulfilment(off)['lighting']['status'], 'NOT_APPLIED')
        untouched = video_measure.frame_at(path_for(off['id']), 4.5)
        self.assertLess(abs(float(untouched[region].mean()) - float(before[region].mean())), 2.0)

    def test_background_treatment_keeps_the_subject_and_softens_the_rest(self):
        result = self.edit(matting=True, captions=False, lighting='off', subtle_zooms=False)
        report = result['edit_report']
        self.assertEqual(self.fulfilment(result)['background']['status'], 'PARTIALLY_FULFILLED')   # blurred, not replaced: said so
        mask = report['background']['mask']
        self.assertTrue(mask['stable'] and mask['subject_found'])
        self.assertGreaterEqual(mask['temporal_iou'], .99)
        self.assertIn('BACKGROUND', [d['type'] for d in report['decisions']])
        # Inspect after the speaker lower third has left: this measures the compositing,
        # not the intentionally added nameplate over the subject's torso.
        before = video_measure.frame_at(path_for(self.asset['id']), 4.5).astype('float32')
        after = video_measure.frame_at(path_for(result['id']), 4.5).astype('float32')
        subject, outside = (slice(250, 390), slice(150, 210)), (slice(430, 550), slice(270, 350))
        self.assertLess(np.abs(after[subject] - before[subject]).mean(), 6)     # subject substantially unchanged
        # Sharpness measures detail; whole-region variance mostly measures the fixture's
        # broad lighting gradients. Keep clear of the intentionally added top-right logo.
        import cv2
        def detail(frame):
            return cv2.Laplacian(cv2.cvtColor(frame[outside].astype('uint8'), cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        self.assertLess(detail(after), detail(before) * .8)
        self.assertLess(after[outside].mean(), before[outside].mean())          # and slightly dimmed
        self.assertEqual(self.editorial(result)['mask_stability']['status'], 'PASS')
        replaced = self.edit(matting=True, captions=False, lighting='off', subtle_zooms=False, background='replace', background_asset_id=self.backdrop['id'])
        self.assertEqual(self.fulfilment(replaced)['background']['status'], 'FULFILLED')
        frame = video_measure.frame_at(path_for(replaced['id']), 4.5).astype('float32')
        corner = frame[430:550, 270:350].mean(axis=(0, 1))                     # BGR of the approved blue backdrop (10, 60, 140 RGB)
        self.assertGreater(corner[0], corner[2] + 60)
        self.assertLess(np.abs(frame[subject] - before[subject]).mean(), 8)

    def test_approvals_and_corrections_lead_to_ready(self):
        first = self.edit(matting=False)
        proposed = first['edit_report']['proposed_cuts'][0]
        self.assertEqual(self.http.get(f'/api/video/assets/{first["id"]}/review').json()['state'], 'DRAFT')
        for state in ('INTERNAL_REVIEW', 'CLIENT_REVIEW'):
            self.assertEqual(self.http.post(f'/api/video/assets/{first["id"]}/review', json=dict(state=state)).status_code, 200)
        self.assertEqual(self.http.post(f'/api/video/assets/{first["id"]}/review', json=dict(state='APPROVED')).status_code, 400)
        result = self.edit(matting=False, approved_cuts=[proposed['id']], caption_corrections={'Ahmad': 'Ahmed'}, captions_reviewed=True,
                           parent_asset_id=first['id'])
        report, editorial = result['edit_report'], result['editorial_report']
        self.assertEqual(report['proposed_cuts'], [])
        self.assertLess(result['duration'], first['duration'] - 1.0)            # the approved cut is now applied
        self.assertEqual(report['caption_state'], 'reviewed')
        self.assertEqual(report['caption_review']['corrected'], ['Ahmad'])
        self.assertIn('Ahmed', ' '.join(c['text'] for c in report['caption_review']['cues']))
        self.assertEqual(editorial['caption_review'], 'DONE')
        self.assertEqual(editorial['publish_readiness'], 'READY', editorial['blockers'])
        self.assertEqual(self.editorial(result)['review']['status'], 'PASS')
        self.assertEqual(self.editorial(result)['cut_confidence']['status'], 'WARNING')   # still flagged: the cut rests on weak recognition
        self.assertEqual(result['parent_asset_id'], first['id'])
        revision = self.http.get(f'/api/video/projects/{result["project_id"]}/revisions/{result["render_revision_id"]}').json()
        self.assertEqual(revision['parent_render_revision_id'], first['render_revision_id'])
        self.assertEqual(revision['render_asset_id'], result['id'])
        self.assertEqual(revision['qa_report'], result['qa_report'])
        self.assertEqual(revision['edit_plan'], report)
        for state in ('INTERNAL_REVIEW', 'CLIENT_REVIEW', 'APPROVED', 'FINAL'):
            response = self.http.post(f'/api/video/assets/{result["id"]}/review', json=dict(state=state, note='Reviewed locally'))
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()['events']), 4)
        self.assertEqual(self.http.post(f'/api/video/assets/{result["id"]}/review', json=dict(state='CLIENT_REVIEW')).status_code, 400)

    def test_platform_zone_catches_what_a_generic_margin_misses(self):
        result = self.edit(matting=False)
        checks = self.editorial(result)
        self.assertEqual(checks['captions_safe_zone']['status'], 'PASS')
        self.assertEqual(checks['logo_safe_zone']['status'], 'PASS')
        self.assertEqual(checks['resolution']['status'], 'WARNING')             # 360 px short side: said, not hidden by upscaling
        saved = self.http.get('/api/video/projects/' + result['project_id']).json()
        project = Project(**{k: v for k, v in saved.items() if k in Project.model_fields})
        for track in project.caption_tracks:
            if track.get('kind') == 'captions':
                track['y_pct'] = .9                                             # about 5% above the physical edge
        style = track_style(next(t for t in project.caption_tracks if t.get('kind') == 'captions'))
        box = render_caption_image('Hello, welcome.', project.canvas.width, project.canvas.height, style).info['caption_layout']['box']
        self.assertLess(box[3], project.canvas.height * .96)                    # inside a generic edge margin
        moved = video_editorial_qa.review(result, project, self.asset, result['edit_report'], None)
        zone = next(c for c in moved['checks'] if c['id'] == 'captions_safe_zone')
        self.assertEqual(zone['status'], 'FAIL')
        self.assertEqual(zone['basis'], 'PRODUCT_DEFAULT')

    def test_plan_preview_renders_nothing_and_capabilities_are_honest(self):
        before = len(self.http.get('/api/video/assets').json())
        plan = self.edit(matting=False, dry_run=True)
        self.assertTrue(plan['dry_run'])
        self.assertNotIn('qa_report', plan)
        self.assertEqual(len(self.http.get('/api/video/assets').json()), before)
        self.assertTrue(plan['edit_report']['decisions'] and plan['edit_report']['request_fulfilment'])
        variants = self.edit(matting=False, plan_variants=True)
        self.assertEqual({v['style'] for v in variants['variants']}, set(video_platforms.STYLES))
        self.assertEqual(len(self.http.get('/api/video/assets').json()), before)
        contextual=self.edit(matting=False,dry_run=True,creative_context=dict(style='authentic and casual',platform='YouTube',cta='Follow our team'))
        contextual=contextual['edit_report']
        self.assertEqual(contextual['style_profile']['id'],'organic')
        self.assertEqual(contextual['platform_profile']['id'],'tiktok-ltr') # explicit instruction overrides the brief's YouTube preference
        self.assertTrue(any(d['type']=='TITLE' and 'Follow our team' in d['reason'] for d in contextual['decisions']))
        with patch.object(video_segmentation, 'installed_model', return_value=None):
            capabilities = self.http.get('/api/video/editing-capabilities').json()
        self.assertFalse(capabilities['matting']['available'])
        self.assertIn('optional segmentation model', capabilities['matting']['reason'])
        self.assertFalse(capabilities['semantic_planner']['available'])
        self.assertFalse(capabilities['generative_background']['available'])
        self.assertEqual(capabilities['platforms']['basis'], 'PRODUCT DEFAULT')
        self.assertEqual({p['id'] for p in capabilities['platforms']['profiles']},
                         {'tiktok-ltr', 'tiktok-rtl', 'instagram-reels', 'instagram-stories', 'youtube-shorts', 'youtube-standard', 'generic-vertical', 'generic-horizontal'})
        self.assertEqual(len(capabilities['styles']), 4)


if __name__ == '__main__':
    unittest.main(verbosity=2)
