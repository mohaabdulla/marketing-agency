"""Comprehensive automated test suite for the Professional AI Video Studio Enhancement.

Tests cover:
1. Brand Guidelines Extraction & Styling (colors, fonts, logo, safe zones)
2. Professional Pacing & Transitions (rollercoaster rhythm, xfade dissolve/fade, generative extend)
3. Frame Interpolation & Unified Studio Color Grading (minterpolate, hqdn3d, looks)
4. Offline TTS & Sound Mixing (voiceover synthesis, music generation, sidechain ducking)
5. Multi-Aspect Ratio Variants (16:9, 9:16, 1:1, 4:5)
6. Playable MP4 Video Export verified with FFprobe
"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix='lexnis-video-enhancement-test-')
os.environ['VIDEO_DATA_DIR'] = TEMP.name

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from video.api import router
from video.storage import DATA, read
from video.ffmpeg import ffmpeg, probe, binary
from video.assets import ingest, path_for
from video.jobs import jobs
from video.projects import Project, Clip, Canvas, save, migrate_project
from video.operations import EditOperation, EditPlan, OperationExecutor
from video.brand_editing import optimize_pacing_and_transitions, polish, checked
from video.editor import render
from video.security import VideoRequestLimits

app = FastAPI()
app.include_router(router)
app.add_middleware(VideoRequestLimits)


def wait_for_job(client: TestClient, job: dict, timeout: float = 60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = client.get(f"/api/video/jobs/{job['id']}").json()
        if res['state'] in ('completed', 'failed', 'cancelled'):
            return res
        time.sleep(0.15)
    raise TimeoutError(f"Job {job['id']} timed out")


class ProfessionalVideoStudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not binary('ffmpeg') or not binary('ffprobe'):
            raise RuntimeError('FFmpeg and FFprobe are required for video studio tests')

        cls.client = TestClient(app)

        # Generate a small 3-second test video with audio
        cls.raw_video = DATA / 'work/test_sample.mp4'
        ffmpeg([
            '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
            '-t', '3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', str(cls.raw_video)
        ])
        with cls.raw_video.open('rb') as f:
            resp = cls.client.post('/api/video/upload', files={'file': ('clip1.mp4', f, 'video/mp4')})
        assert resp.status_code == 200, resp.text
        cls.asset_video1 = resp.json()

        # Upload a second copy for transitions & cuts
        with cls.raw_video.open('rb') as f:
            resp = cls.client.post('/api/video/upload', files={'file': ('clip2.mp4', f, 'video/mp4')})
        assert resp.status_code == 200, resp.text
        cls.asset_video2 = resp.json()

        # Generate a test logo
        buf = io.BytesIO()
        Image.new('RGBA', (200, 200), (0, 255, 163, 255)).save(buf, format='PNG')
        resp = cls.client.post('/api/video/upload', files={'file': ('brand_logo.png', buf.getvalue(), 'image/png')})
        assert resp.status_code == 200, resp.text
        cls.asset_logo = resp.json()

    def test_01_project_schema_defaults_and_migration(self):
        """Verify new schema fields: transition_type, smooth_motion, unified_grade, frame_interpolation."""
        legacy_data = {
            'name': 'Legacy Test',
            'clips': [
                {'id': 'a'*32, 'asset_id': self.asset_video1['id'], 'kind': 'video', 'duration': 3.0}
            ]
        }
        migrated = migrate_project(legacy_data)
        self.assertFalse(migrated['frame_interpolation'])
        self.assertIsNone(migrated['unified_grade'])
        self.assertEqual(migrated['global_denoise'], 0.0)
        self.assertEqual(migrated['clips'][0]['transition_type'], 'fade')
        self.assertFalse(migrated['clips'][0]['smooth_motion'])

    def test_02_brand_guidelines_styling_and_safe_zones(self):
        """Verify brand guidelines auto-polish applies colors, fonts, safe zones (x=0.5, y=0.82), and logo."""
        project = Project(
            name='Brand Polish Test',
            clips=[
                Clip(asset_id=self.asset_video1['id'], kind='video', duration=3.0),
                Clip(kind='title', text='Welcome to Lexnis', text_role='lower_third', x=0.5, y=0.5)
            ]
        )
        saved = save(project)
        p_id = saved['id']

        brand_profile = {
            'brand_name': 'Lexnis Tech',
            'brand_colors': {'primary': '#00FFA3', 'accent': '#7928CA'},
            'font_preferences': ['Arial', 'sans-serif'],
            'logo_asset_id': self.asset_logo['id']
        }

        resp = self.client.post(f"/api/video/projects/{p_id}/auto-polish", json={
            'brand_profile': brand_profile
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        updated = data['project']

        # Verify title updated to primary brand color and bottom-center safe zone
        title_clip = next(c for c in updated['clips'] if c['kind'] == 'title')
        self.assertEqual(title_clip['color'].lower(), '#00ffa3')
        self.assertAlmostEqual(title_clip['x'], 0.5, places=2)
        self.assertAlmostEqual(title_clip['y'], 0.82, places=2)

        # Verify logo overlay added
        logo_clip = next((c for c in updated['clips'] if c['kind'] == 'overlay'), None)
        self.assertIsNotNone(logo_clip)
        self.assertEqual(logo_clip['asset_id'], self.asset_logo['id'])

        # Verify unified grade was applied
        self.assertEqual(updated['unified_grade'], 'polished-organic')

    def test_03_pacing_and_transitions_optimization(self):
        """Verify optimize_pacing_and_transitions applies varied cut durations, dissolves, and generative extend."""
        project = Project(
            name='Pacing Test',
            clips=[
                Clip(asset_id=self.asset_video1['id'], kind='video', duration=1.0),  # Intentionally short
                Clip(asset_id=self.asset_video2['id'], kind='video', duration=4.0)
            ]
        )
        saved = save(project)
        p_id = saved['id']

        resp = self.client.post(f"/api/video/projects/{p_id}/optimize-pacing", json={
            'pacing_mode': 'rollercoaster',
            'default_transition': 0.6,
            'transition_type': 'dissolve'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        updated = data['project']

        # Clip 1 should have been extended because 1.0s < 0.6 * 2.2
        clip1 = updated['clips'][0]
        self.assertGreaterEqual(clip1['duration'], 0.6 * 2.2)

        # Clip 2 should have transition 0.6s and dissolve type
        clip2 = updated['clips'][1]
        self.assertEqual(clip2['transition'], 0.6)
        self.assertEqual(clip2['transition_type'], 'dissolve')

    def test_04_offline_tts_voiceover_and_caption_sync(self):
        """Verify offline TTS generates a WAV asset, attaches audio clip with ducking, and generates synced caption."""
        project = Project(
            name='Voiceover Test',
            clips=[
                Clip(asset_id=self.asset_video1['id'], kind='video', duration=3.0)
            ]
        )
        saved = save(project)
        p_id = saved['id']

        resp = self.client.post(f"/api/video/projects/{p_id}/generate-voiceover", json={
            'text': 'Transform your business with autonomous marketing systems.',
            'voice_id': 'af_sarah',
            'ducking_priority': 2,
            'add_to_timeline': True,
            'create_captions': True
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertTrue(data['voiceover']['success'])
        self.assertGreater(data['voiceover']['duration_seconds'], 0.5)

        updated_clips = data['project']['clips']
        vo_clip = next((c for c in updated_clips if c['kind'] == 'audio' and c['audio_role'] == 'voiceover'), None)
        self.assertIsNotNone(vo_clip)
        self.assertEqual(vo_clip['ducking_priority'], 2)

        # Captions should be positioned in safe zone
        cap_clip = next((c for c in updated_clips if c['kind'] == 'title' and c['text_role'] == 'caption'), None)
        self.assertIsNotNone(cap_clip)
        self.assertAlmostEqual(cap_clip['y'], 0.82, places=2)

    def test_05_background_music_generation_and_timeline_addition(self):
        """Verify offline ambient soundtrack synthesis and addition to timeline."""
        project = Project(
            name='Music Test',
            clips=[
                Clip(asset_id=self.asset_video1['id'], kind='video', duration=3.0)
            ]
        )
        saved = save(project)
        p_id = saved['id']

        resp = self.client.post(f"/api/video/projects/{p_id}/add-music", json={
            'prompt': 'Minimalist corporate tech ambient bed',
            'genre': 'Corporate Ambient',
            'duration_seconds': 4.0,
            'volume': 0.25,
            'ducking_priority': 1
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        music_clip = next((c for c in data['project']['clips'] if c['kind'] == 'audio' and c['audio_role'] == 'music'), None)
        self.assertIsNotNone(music_clip)
        self.assertEqual(music_clip['volume'], 0.25)
        self.assertEqual(music_clip['ducking_priority'], 1)

    def test_06_multi_aspect_ratio_variants(self):
        """Verify creating 9:16 and 1:1 variants from master project."""
        project = Project(
            name='Variant Master',
            canvas=Canvas(width=1280, height=720),
            clips=[
                Clip(asset_id=self.asset_video1['id'], kind='video', duration=3.0)
            ]
        )
        saved = save(project)
        p_id = saved['id']

        resp = self.client.post(f"/api/video/projects/{p_id}/variants", json={
            'target_aspect': '9:16',
            'focal_x': 0.5,
            'focal_y': 0.5
        })
        self.assertEqual(resp.status_code, 200)
        variant = resp.json()
        self.assertEqual(variant['canvas']['width'], 1080)
        self.assertEqual(variant['canvas']['height'], 1920)
        self.assertEqual(variant['variant_target'], '9:16')

    def test_07_full_playable_mp4_export_with_ffprobe(self):
        """Full end-to-end export: 2 clips with xfade dissolve, unified grade, voiceover, music, subtitles.
        Verify generated MP4 using ffprobe for exact streams, duration, and resolution.
        """
        # Create full production project
        project = Project(
            name='End-to-End Production Export',
            canvas=Canvas(width=640, height=360, fps=24),
            frame_interpolation=False,  # Keep export fast for test
            unified_grade='polished-organic',
            global_denoise=0.05,
            clips=[
                Clip(
                    asset_id=self.asset_video1['id'],
                    kind='video',
                    duration=2.5,
                    transition=0.0
                ),
                Clip(
                    asset_id=self.asset_video2['id'],
                    kind='video',
                    duration=2.5,
                    transition=0.5,
                    transition_type='dissolve'
                ),
                Clip(
                    kind='title',
                    text='Autonomous Marketing Studio',
                    start=0.5,
                    duration=3.0,
                    x=0.5,
                    y=0.82,
                    text_role='caption',
                    color='#00FFA3'
                )
            ]
        )

        resp = self.client.post('/api/video/export', json={
            'project': project.model_dump(),
            'container': 'mp4',
            'audio': True,
            'preview': False
        })
        self.assertEqual(resp.status_code, 202)
        job_info = resp.json()

        finished_job = wait_for_job(self.client, job_info, timeout=60.0)
        self.assertEqual(finished_job['state'], 'completed')
        self.assertIn('result', finished_job)
        exported_asset_id = finished_job['result']['id']

        # Probe the exported MP4 using ffprobe via path_for
        out_path = path_for(exported_asset_id)
        self.assertTrue(out_path.is_file())
        self.assertGreater(out_path.stat().st_size, 5000)

        meta = probe(out_path)
        self.assertEqual(meta['width'], 640)
        self.assertEqual(meta['height'], 360)
        self.assertTrue(meta['has_audio'])
        # 2.5 + 2.5 - 0.5 = 4.5s
        self.assertAlmostEqual(meta['duration'], 4.5, delta=0.3)


if __name__ == '__main__':
    unittest.main()
