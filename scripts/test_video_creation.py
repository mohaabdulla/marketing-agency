"""Video creation from stills: real renders, measured motion, composition and delivery QA."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='lexnis-video-creation-')
os.environ['VIDEO_DATA_DIR'] = TEMP.name
import cv2
import numpy as np
from PIL import Image, ImageDraw
from video.assets import ingest, path_for
from video.engine import Generate, generate, check_generate, promo_timeline, canvas_for
from video.ffmpeg import ffmpeg
from video.jobs import Job
from video.layout import intersection
from video.measure import frame_at, loudness
from video.platforms import profile, safe_area


def still(name='still.png', seed=3, size=(1920, 1080)):
    rng = np.random.default_rng(seed)
    image = Image.fromarray((rng.random((size[1], size[0], 3)) * 60 + 60 + seed * 12).astype('uint8'))
    draw = ImageDraw.Draw(image)
    for _ in range(60):
        x, y = int(rng.integers(100, size[0] - 100)), int(rng.integers(100, size[1] - 100))
        draw.ellipse([x - 14, y - 14, x + 14, y + 14], fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    path = Path(TEMP.name) / name
    image.save(path)
    return ingest(path, name)


def frame_steps(path):
    """Per-frame translation of an off-centre patch (a zoom shows there as steady drift)."""
    capture, previous, steps = cv2.VideoCapture(str(path)), None, []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)[60:300, 80:500].astype('float32')
            if previous is not None:
                steps.append(cv2.phaseCorrelate(previous, gray)[0])
            previous = gray
    finally:
        capture.release()
    return np.array(steps)


class CreationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = still()
        cls.scenes = [still(f'scene-{n}.png', seed=n + 4) for n in range(2)]
        logo = Path(TEMP.name) / 'logo.png'
        Image.new('RGBA', (300, 90), '#e4572e').save(logo)
        cls.logo = ingest(logo, 'logo.png')
        music = Path(TEMP.name) / 'music.wav'
        ffmpeg(['-f', 'lavfi', '-i', 'sine=frequency=220:sample_rate=48000:duration=12', '-af', 'volume=0.2', '-c:a', 'pcm_s16le', str(music)])
        cls.music = ingest(music, 'music.wav')

    def test_zoom_and_pan_move_smoothly(self):
        for motion in ('zoom-in', 'pan'):
            result = generate(Generate(mode='image-animation', asset_id=self.image['id'], duration=4, motion=motion), Job('generate'))
            steps = frame_steps(path_for(result['id']))[18:-18]      # skip the fade in and out: no texture to track
            size = np.hypot(steps[:, 0], steps[:, 1])
            self.assertGreater(size.mean(), .3, motion)                    # it does move
            # Whole-pixel window rounding alternated 0 and 2 px steps (std above 0.7 px).
            self.assertLess(size.std(), .5, (motion, size.std()))
            self.assertLess(np.percentile(np.abs(np.diff(steps, axis=0)).max(axis=1), 95), 1.6, motion)

    def test_generated_clip_is_mastered_and_measured(self):
        result = generate(Generate(mode='image-animation', asset_id=self.image['id'], aspect='9:16', duration=3, cta='Book a demo'), Job('generate'))
        self.assertEqual((result['width'], result['height']), (720, 1280))
        self.assertEqual(result['video_profile'], 'High')
        self.assertEqual((result['color_primaries'], result['color_transfer']), ('bt709', 'bt709'))
        report = result['qa_report']
        self.assertEqual(report['counts']['FAIL'], 0, [c for c in report['checks'] if c['status'] == 'FAIL'])
        self.assertGreater(report['counts']['PASS'], 5)
        self.assertEqual(result['generation_type'], 'deterministic-image-animation')

    def test_brand_promo_has_scenes_story_timing_logo_and_music(self):
        request = Generate(mode='image-animation', asset_id=self.image['id'], asset_ids=[s['id'] for s in self.scenes], logo_asset_id=self.logo['id'],
                           music_asset_id=self.music['id'], aspect='9:16', duration=9, motion='auto', platform='instagram reels',
                           key_message='Meet the team behind the product', cta='Book a demo today')
        result = generate(request, Job('generate'))
        self.assertAlmostEqual(result['duration'], 9, delta=.1)                 # the length that was asked for
        self.assertTrue(result['has_audio'])
        report = result['qa_report']
        self.assertEqual(report['counts']['FAIL'], 0, [c for c in report['checks'] if c['status'] == 'FAIL'])
        composition = result['composition']
        self.assertEqual((composition['scenes'], composition['platform']['id']), (3, 'instagram-reels'))
        elements = {e['role']: e for e in composition['elements']}
        self.assertEqual(set(elements), {'HOOK', 'CTA', 'LOGO'})
        # Story order: the headline opens, the call to action closes, and they never share the screen.
        self.assertLess(elements['HOOK']['end'], elements['CTA']['start'])
        self.assertAlmostEqual(elements['CTA']['end'], 9, delta=.1)
        self.assertGreaterEqual(elements['CTA']['font_size_px'], 24)
        bounds = safe_area(profile('instagram-reels'), 720, 1280)
        for role, element in elements.items():
            box = element['box']
            self.assertAlmostEqual(intersection(box, bounds), (box[2] - box[0]) * (box[3] - box[1]), delta=2, msg=role)   # inside the platform safe area
            self.assertFalse(element['requires_review'], role)
        self.assertEqual(intersection(elements['LOGO']['box'], elements['HOOK']['box']), 0)
        # The three stills really appear: the picture at the middle of each scene differs from the others.
        frames = [cv2.resize(frame_at(path_for(result['id']), t), (90, 160)).astype(float) for t in (1.6, 4.5, 7.4)]
        self.assertGreater(np.abs(frames[0] - frames[1]).mean(), 4)
        self.assertGreater(np.abs(frames[1] - frames[2]).mean(), 4)
        # Text is burned in where the plan says: the headline region changes once the headline has left.
        x0, y0, x1, y1 = [int(v) for v in elements['HOOK']['box']]
        with_text, without = frame_at(path_for(result['id']), 2.0), frame_at(path_for(result['id']), 4.9)
        plate = with_text[y0:y1, x0:x1].astype(float)
        self.assertLess(np.median(plate), 90)                                   # dark plate behind the headline
        self.assertGreater((plate > 200).mean(), .04)                           # light glyphs on it
        # Music is delivered at the preset level, under the true-peak ceiling.
        measured = loudness(path_for(result['id']))
        self.assertLessEqual(measured['true_peak_dbtp'], -1.0)
        self.assertAlmostEqual(measured['integrated_lufs'], -14, delta=2.5)

    def test_portrait_still_in_a_landscape_frame_is_shown_whole(self):
        portrait = still('portrait.png', seed=9, size=(720, 1280))
        request = Generate(mode='image-animation', asset_id=portrait['id'], aspect='16:9', duration=3, motion='still',
                           key_message='Meet the team behind the product', cta='Book a demo today')
        timeline = promo_timeline(request, canvas_for('16:9', 720))
        self.assertEqual(timeline.clips[0].fit, 'blur-fill')
        self.assertEqual(promo_timeline(request.model_copy(update={'asset_id': self.image['id']}), canvas_for('16:9', 720)).clips[0].fit, 'cover')
        result = generate(request, Job('generate'))
        frame = cv2.cvtColor(frame_at(path_for(result['id']), 1.5), cv2.COLOR_BGR2GRAY)
        sharp = lambda region: cv2.Laplacian(region, cv2.CV_64F).var()
        # The centre column holds the whole, sharp still; the sides are its blurred fill.
        self.assertGreater(sharp(frame[100:400, 520:760]), 20 * sharp(frame[100:400, 40:280]))
        sizes = {e['role']: e['font_size_px'] for e in result['composition']['elements'] if e['font_size_px']}
        # Type follows the shorter reading dimension: 16:9 at 720p no longer gets 80 px titles.
        self.assertTrue(30 <= sizes['CTA'] <= 46 and 34 <= sizes['HOOK'] <= 50, sizes)
        self.assertEqual(result['qa_report']['counts']['FAIL'], 0)

    def test_letter_spaced_text_sits_on_one_baseline(self):
        from video.captions import CaptionStyle, render_caption_image
        image = render_caption_image('Book a demo today', 720, 1280, CaptionStyle(id='cta', name='CTA', tracking=.2, background=None, stroke=None, stroke_width=0))
        alpha = (np.array(image.getchannel('A')) > 128).astype('uint8')
        count, _, stats, _ = cv2.connectedComponentsWithStats(alpha, 8)
        bottoms = np.array([stats[i, cv2.CC_STAT_TOP] + stats[i, cv2.CC_STAT_HEIGHT] for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] > 20])
        self.assertGreaterEqual(len(bottoms), 12)
        # Letters without a descender end on one baseline (round letters overshoot by a pixel or two).
        # Per-glyph top anchoring lifted the short letters by the difference to the capital height.
        on_baseline = np.abs(bottoms - np.median(bottoms)) <= 2
        self.assertGreaterEqual(on_baseline.mean(), .85, bottoms.tolist())

    def test_requests_that_cannot_work_are_refused_with_a_reason(self):
        with self.assertRaisesRegex(ValueError, '120 characters'):
            check_generate(Generate(mode='image-animation', asset_id=self.image['id'], key_message='x' * 121))
        with self.assertRaisesRegex(ValueError, 'key message can be read'):
            check_generate(Generate(mode='image-animation', asset_id=self.image['id'], duration=1, key_message='Our company', cta='Contact us'))
        with self.assertRaisesRegex(ValueError, 'music track at least as long'):
            check_generate(Generate(mode='image-animation', asset_id=self.image['id'], duration=20, music_asset_id=self.music['id']))
        many = Generate(mode='image-animation', asset_id=self.image['id'], asset_ids=[s['id'] for s in self.scenes], duration=3)
        with self.assertRaisesRegex(ValueError, 'scenes need at least'):
            check_generate(many)
        with self.assertRaisesRegex(ValueError, 'still image'):
            check_generate(Generate(mode='image-animation', asset_id=self.image['id'], asset_ids=[self.music['id']], duration=8))
        with self.assertRaisesRegex(ValueError, 'audio file'):
            check_generate(Generate(mode='image-animation', asset_id=self.image['id'], music_asset_id=self.logo['id']))
        with self.assertRaisesRegex(ValueError, 'Image Animation only'):
            check_generate(Generate(mode='text-to-video', prompt='A factory', music_asset_id=self.music['id']))
        # One image keeps the single-shot behaviour; several get varied moves and crossfades.
        single = promo_timeline(Generate(mode='image-animation', asset_id=self.image['id'], motion='pan', duration=4), canvas_for('16:9', 720))
        self.assertEqual((len(single.clips), single.clips[0].pan, single.clips[0].transition), (1, .8, 0))
        several = promo_timeline(many.model_copy(update={'duration': 9}), canvas_for('16:9', 720))
        self.assertEqual([c.transition for c in several.clips], [0, .4, .4])
        self.assertEqual(len({(c.zoom_start, c.zoom, c.pan) for c in several.clips}), 3)

    def test_short_promos_keep_titles_inside_the_requested_duration(self):
        from video.engine import branded_project, compose_promo
        from video.editor import primary_layout
        for duration, message in [(1, ''), (3, 'Our company')]:
            request = Generate(mode='image-animation', asset_id=self.image['id'], duration=duration, key_message=message, cta='Contact us')
            check_generate(request)
            project, _, _ = branded_project(promo_timeline(request, canvas_for('16:9', 720)), request)
            project, composition = compose_promo(project, request)
            self.assertAlmostEqual(primary_layout(project)[1], duration, delta=.01)
            for element in composition['elements']:
                self.assertGreaterEqual(element['start'], 0)
                self.assertLessEqual(element['end'], duration + .01)
            if message:
                elements = {e['role']: e for e in composition['elements']}
                self.assertLess(elements['HOOK']['end'], elements['CTA']['start'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
