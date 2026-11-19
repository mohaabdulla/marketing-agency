"""Motion smoothness of rendered video, measured on real renders (no mocks):
steady sub-pixel camera moves on stills, no move-then-freeze, and footage without repeated frames."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='video-smoothness-')
os.environ['VIDEO_DATA_DIR'] = TEMP.name
import cv2
import numpy as np
from video.assets import ingest, path_for
from video.editor import render
from video.ffmpeg import ffmpeg
from video.jobs import Job
from video.projects import Canvas, Clip, Project
from video.sequence import camera_move, needs_interpolation, rate_family, sequence_fps


def frames(path):
    capture = cv2.VideoCapture(str(path))
    while True:
        ok, frame = capture.read()
        if not ok:
            return
        yield cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float64)


def repeated(path):
    """Frames that repeat the one before (a stall in the motion). A repeat differs only by encoding
    noise, a small fraction of the usual frame-to-frame change."""
    previous, changes = None, []
    for frame in frames(path):
        if previous is not None:
            changes.append(np.mean(np.abs(frame - previous)))
        previous = frame
    changes = np.array(changes)
    return int((changes < .1 * np.median(changes)).sum())


class SmoothnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job = Job('smoothness-test')

    @classmethod
    def tearDownClass(cls):
        TEMP.cleanup()

    def clip_asset(self, rate, seconds=2, size='320x180'):
        path = Path(TEMP.name) / f'moving-{rate}.mp4'
        ffmpeg(['-f', 'lavfi', '-i', f'testsrc2=s={size}:r={rate}:d={seconds}', '-c:v', 'libx264', '-crf', '12', '-pix_fmt', 'yuv420p', str(path)])
        return ingest(path, path.name, self.job)

    def test_rate_families_and_sequence_rate_follow_the_footage(self):
        for source, family in [(23.976, 24), (24, 24), (48, 24), (25, 25), (50, 25), (29.97, 30), (30, 30), (59.94, 30), (60, 30), (12, 30)]:
            self.assertEqual(rate_family(source), family, source)
        pal, ntsc = self.clip_asset(25), self.clip_asset(30)
        self.assertEqual(sequence_fps([dict(duration=4)]), 30)                      # stills only
        self.assertEqual(sequence_fps([dict(asset_id=pal['id'], duration=5), dict(asset_id=ntsc['id'], duration=3)]), 25)
        self.assertTrue(needs_interpolation(dict(fps=25), 1, 30))
        self.assertTrue(needs_interpolation(dict(fps=30), .8, 30))                   # slowed footage
        self.assertFalse(needs_interpolation(dict(fps=60), 1, 30))

    def test_camera_moves_span_the_whole_scene(self):
        self.assertEqual(camera_move('zoom-in', 'balanced'), dict(zoom_start=1, zoom=1.07))
        self.assertEqual(camera_move('zoom-out', 'calm'), dict(zoom_start=1.04, zoom=1))
        self.assertGreater(camera_move('still', 'balanced')['zoom'], 1)              # a held card still drifts

    def test_still_zoom_moves_every_frame_at_a_steady_speed(self):
        image = np.full((540, 960, 3), 30, np.uint8)
        cv2.circle(image, (192, 108), 5, (255, 255, 255), -1, lineType=cv2.LINE_AA)
        source = Path(TEMP.name) / 'dot.png'; cv2.imwrite(str(source), image)
        asset = ingest(source, source.name, self.job)
        project = Project(canvas=Canvas(width=960, height=540, fps=30),
                          clips=[Clip(asset_id=asset['id'], duration=3, zoom_start=1, zoom=1.07, zoom_ease=0)])
        output = path_for(render(project, self.job, audio=False)['id'])
        points = []
        for frame in frames(output):
            frame[frame < 80] = 0
            ys, xs = np.nonzero(frame); weight = frame[ys, xs]
            points.append((np.sum(xs * weight) / weight.sum(), np.sum(ys * weight) / weight.sum()))
        steps = np.hypot(*np.diff(np.array(points), axis=0).T)
        self.assertEqual(len(points), 90)
        # A 7% zoom about the centre moves the dot 7% of its distance from the centre (330 px), no more.
        self.assertAlmostEqual(steps.sum(), .07 * np.hypot(288, 162), delta=3)
        # zoompan's whole-pixel window measured a variation of about 0.47 here; sub-pixel sampling about 0.15.
        self.assertLess(steps.std() / steps.mean(), .3)
        self.assertLessEqual(int((steps < .02).sum()), 1)

    def test_brand_backdrop_moves_on_every_frame(self):
        from video import backdrop
        path = Path(TEMP.name) / 'backdrop.mp4'
        backdrop.render(path, Canvas(width=320, height=180, fps=30), dict(primary_hex='#0d1b2a', secondary_hex='#3fbf6f'), 1, seconds=2)
        self.assertEqual(sum(1 for _ in frames(path)), 60)
        self.assertEqual(repeated(path), 0)

    def test_logos_and_cutouts_are_not_scene_pictures(self):
        from PIL import Image
        from video.company_intro import is_logo_url, transparent_share
        self.assertTrue(is_logo_url('https://example.bh/brand/lexnis.webp'))
        self.assertTrue(is_logo_url('https://example.bh/_next/image?url=%2Fimages%2Flogo-dark.png&w=3840'))
        self.assertFalse(is_logo_url('https://example.bh/_next/image?url=%2Fimages%2F2026%2F05%2Fteam-photo.webp&w=3840'))
        cutout = Image.new('RGBA', (100, 100), (0, 0, 0, 0)); cutout.paste((20, 200, 90, 255), (30, 30, 70, 70))
        self.assertGreater(transparent_share(cutout), .5)
        self.assertEqual(transparent_share(Image.new('RGB', (10, 10))), 0)

    def test_framed_card_fits_its_share_of_the_frame(self):
        from PIL import Image
        from video.editor import card_layers
        for size in [(1200, 1199), (300, 400)]:                             # large and small pictures
            source = Path(TEMP.name) / f'card-{size[0]}.png'; Image.new('RGB', size, (90, 120, 200)).save(source)
            backdrop, card = Path(TEMP.name) / 'b.png', Path(TEMP.name) / 'c.png'
            card_layers(source, 0, 2074, 1166, .78, backdrop, card)
            pad = round(1166 * .05)
            with Image.open(backdrop) as b, Image.open(card) as c:
                self.assertEqual(b.size, (2074, 1166))
                self.assertLessEqual(c.height - 2 * pad, round(1166 * .78) + 2)
                self.assertGreaterEqual(c.height - 2 * pad, round(1166 * .78) - 2)

    def test_split_layout_and_end_card_logo(self):
        from PIL import Image
        from video.sequence import end_card_logo, low_contrast, split_card
        canvas = Canvas(width=1920, height=1080, fps=30)
        def image(name, size, colour=(200, 60, 40)):
            path = Path(TEMP.name) / name; Image.new('RGB', size, colour).save(path)
            return ingest(path, name, self.job)['id']
        portrait, wide = image('portrait.png', (650, 820)), image('wide.png', (1200, 800))
        self.assertTrue(split_card(dict(asset_id=portrait), canvas))       # framed card beside the headline
        self.assertFalse(split_card(dict(asset_id=wide), canvas))          # too wide for half the frame
        self.assertFalse(split_card(dict(), canvas))
        logo = Path(TEMP.name) / 'logo.png'
        mark = Image.new('RGBA', (600, 200), (0, 0, 0, 0)); mark.paste((240, 240, 240, 255), (20, 20, 580, 180)); mark.save(logo)
        logo_id = ingest(logo, 'logo.png', self.job)['id']
        self.assertFalse(low_contrast(path_for(logo_id), '#0d1b2a'))         # light logo on a dark brand colour
        self.assertTrue(low_contrast(path_for(logo_id), '#f0f0f0'))
        from video.captions import CaptionStyle
        style = CaptionStyle(id='cta', name='cta', y_pct=.56)
        scenes = [dict(start=0, duration=4, asset_id=portrait), dict(start=4, duration=3)]
        hero = end_card_logo(dict(logo_asset_id=logo_id, primary_hex='#0d1b2a'), scenes, canvas, '16:9', ('cta', style, .6 * 1080), 60, 32)
        self.assertEqual((hero.start, hero.duration, hero.x), (4, 3, .5))
        logo_bottom = hero.y * (1080 - 1920 * hero.scale / 3) + 1920 * hero.scale / 3
        self.assertLess(logo_bottom, 2 * .56 * 1080 - .6 * 1080)            # clear of the call-to-action headline
        self.assertIsNone(end_card_logo(dict(logo_asset_id=logo_id, primary_hex='#000'), scenes[:1], canvas, '16:9', ('cta', style, 600), 60, 32))

    def test_pal_footage_in_a_30_fps_video_has_no_repeated_frames_when_interpolated(self):
        asset = self.clip_asset(25)

        def export(smooth):
            project = Project(canvas=Canvas(width=320, height=180, fps=30),
                              clips=[Clip(asset_id=asset['id'], duration=1.6, smooth_motion=smooth)])
            return path_for(render(project, self.job, audio=False)['id'])
        self.assertGreaterEqual(repeated(export(False)), 6)    # 25 -> 30 repeats every fifth frame
        self.assertEqual(repeated(export(True)), 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
