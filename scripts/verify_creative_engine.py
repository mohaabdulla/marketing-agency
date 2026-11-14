"""Comprehensive verification suite for the Layered Creative Engine, Direct MP4, Adapters, and Local-Only Enforcement."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from creative.schemas import (
    CreativeProject, Scene, CanvasConfig, Layer, LayerType, TextLayerData,
    TextRole, TextDirection, Keyframe, GenerationManifest
)
from creative.easing import evaluate_easing, EASING_FUNCTIONS
from creative.colors import hex_to_rgba, contrast_ratio, relative_luminance
from creative.keyframes import KeyframeTrack
from creative.typography import TypographyEngine
from creative.scene import SceneGraph
from creative.presets import FORMAT_PRESETS, MOTION_PRESETS, MotionPresetBuilder
from creative.qa import CreativeQAEngine
from creative.exports import CreativeExporter
from creative.storage import creative_storage
from video_models import (
    ModelState, VideoModelAdapter, CogVideoXAdapter, Wan21I2VAdapter,
    Wan21T2VAdapter, Wan22TI2VAdapter, get_adapter, statuses, MODELS
)
from video_ffmpeg import probe


class TestCreativeEngine(unittest.TestCase):

    def test_01_easing_curves(self):
        """Verify all 7 easing functions produce continuous monotonic or expected bounds."""
        for name in EASING_FUNCTIONS:
            v0 = evaluate_easing(name, 0.0)
            v1 = evaluate_easing(name, 1.0)
            self.assertAlmostEqual(v0, 0.0, places=3, msg=f"Easing {name} at 0 should be 0")
            if name != "hold":
                self.assertAlmostEqual(v1, 1.0, places=3, msg=f"Easing {name} at 1 should be 1")

        # Test overshoot exceeds 1.0 at peak
        overshoot_mid = evaluate_easing("overshoot", 0.8)
        self.assertGreater(overshoot_mid, 1.0)

    def test_02_wcag_contrast_and_color_math(self):
        """Verify WCAG relative luminance and contrast calculations."""
        # White vs Black should be 21:1
        ratio = contrast_ratio("#FFFFFF", "#000000")
        self.assertAlmostEqual(ratio, 21.0, places=1)

        # Identical colors should have contrast ratio 1.0
        ratio_same = contrast_ratio("#131724", "#131724")
        self.assertAlmostEqual(ratio_same, 1.0, places=1)

    def test_03_keyframe_track_evaluation(self):
        """Verify numerical and color interpolation between keyframes."""
        track = KeyframeTrack("opacity", [
            Keyframe(time=0.0, value=0.0, easing="linear"),
            Keyframe(time=1.0, value=1.0, easing="linear"),
        ])
        self.assertAlmostEqual(track.evaluate(0.0), 0.0)
        self.assertAlmostEqual(track.evaluate(0.5), 0.5)
        self.assertAlmostEqual(track.evaluate(1.0), 1.0)

    def test_04_bilingual_typography_and_rtl(self):
        """Verify typography engine correctly classifies Arabic text as RTL and renders."""
        typo = TypographyEngine()
        is_ar = typo.is_arabic("مرحبا بكم في لكسنس")
        is_en = typo.is_arabic("Welcome to Lexnis")
        self.assertTrue(is_ar)
        self.assertFalse(is_en)

        # Test text measurement and wrapping
        lines = typo.wrap_text("Welcome to the next generation of industrial intelligence", max_width=400, font_size=28)
        self.assertGreater(len(lines), 1)

    def test_05_scene_graph_still_render_and_manifest(self):
        """Verify scene graph rasterization and still image export."""
        scene = Scene(
            scene_id="test_still_01",
            duration=2.0,
            canvas=CanvasConfig(width=640, height=640),
            layers=[
                Layer(
                    layer_id="bg",
                    name="Background",
                    layer_type=LayerType.SHAPE,
                    properties={"shape_type": "rectangle", "fill_color": "#131724"},
                ),
                Layer(
                    layer_id="headline",
                    name="Headline",
                    layer_type=LayerType.TEXT,
                    text_data=TextLayerData(
                        text="AUTONOMOUS SYSTEMS",
                        font_size=32,
                        text_role=TextRole.HEADLINE,
                        color="#00FFA3",
                    ),
                    transform={"x": 50, "y": 80},
                )
            ]
        )
        exporter = CreativeExporter()
        out_dir = ROOT / "output/test_creative"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "still_test.png"

        result = exporter.render_still(scene, t=0.0, output_path=out_file)
        self.assertTrue(out_file.exists())
        self.assertGreater(out_file.stat().st_size, 1000)
        self.assertEqual(result.manifest.generation_type, "creative-layered-still")

    def test_06_direct_mp4_export_without_intermediate_gif(self):
        """Verify direct MP4 rendering via FFmpeg rawvideo pipe with valid probe."""
        builder = MotionPresetBuilder()
        scene = builder.ken_burns(
            image_path=None,  # will render solid fallback
            canvas=CanvasConfig(width=480, height=480),
            duration=1.5,
            zoom_start=1.0,
            zoom_end=1.1,
            scene_id="test_mp4_direct"
        )
        # Add animated text layer with CTA pop
        cta_scene = builder.cta_pop(
            text="APPLY NOW",
            canvas=CanvasConfig(width=480, height=480),
            scene_id="test_cta_direct"
        )
        # Combine into one scene
        scene.layers.extend(cta_scene.layers)

        exporter = CreativeExporter()
        out_dir = ROOT / "output/test_creative"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_mp4 = out_dir / "direct_render.mp4"

        result = exporter.render_mp4_direct(scene, output_path=out_mp4, fps=24, bitrate="2M")
        self.assertTrue(out_mp4.exists())
        self.assertGreater(out_mp4.stat().st_size, 5000)
        self.assertEqual(result.manifest.generation_type, "creative-motion-mp4")

        # Probe the resulting video to verify libx264 encoding and dimensions
        info = probe(out_mp4)
        self.assertEqual(info["width"], 480)
        self.assertEqual(info["height"], 480)
        self.assertAlmostEqual(info["duration"], 1.5, delta=0.2)

    def test_07_creative_qa_engine(self):
        """Verify QA engine detects safe margin violations and low contrast."""
        qa = CreativeQAEngine()
        scene = Scene(
            scene_id="test_qa",
            duration=1.0,
            canvas=CanvasConfig(width=500, height=500, safe_margins=50),
            layers=[
                # Layer outside safe margin (x=10 is < safe_margin 50)
                Layer(
                    layer_id="bad_margin",
                    name="Bad Margin Text",
                    layer_type=LayerType.TEXT,
                    text_data=TextLayerData(text="Edge text", font_size=20, color="#FFFFFF"),
                    transform={"x": 10, "y": 10},
                ),
                # Low contrast layer (dark text on dark background)
                Layer(
                    layer_id="low_contrast",
                    name="Low Contrast Text",
                    layer_type=LayerType.TEXT,
                    text_data=TextLayerData(text="Hidden text", font_size=20, color="#151928", bg_color="#131724"),
                    transform={"x": 100, "y": 100},
                )
            ]
        )
        report = qa.audit_scene(scene)
        self.assertFalse(report.passed)
        self.assertGreater(len(report.findings), 0)
        codes = [f.check_name for f in report.findings]
        self.assertTrue("safe_margin_audit" in codes or "contrast_audit" in codes)

    def test_08_video_model_adapter_architecture(self):
        """Verify VideoModelAdapter subclasses, explicit states, and get_adapter registry."""
        self.assertIn("cogvideox-2b", MODELS)
        self.assertIn("wan21-i2v-480p", MODELS)
        self.assertIn("wan21-t2v-480p", MODELS)
        self.assertIn("wan22-ti2v-5b", MODELS)

        cog_adapter = get_adapter("cogvideox-2b")
        self.assertIsInstance(cog_adapter, CogVideoXAdapter)
        self.assertEqual(cog_adapter.metadata()["modes"], ["text-to-video"])

        wan_adapter = get_adapter("wan21-i2v-480p")
        self.assertIsInstance(wan_adapter, Wan21I2VAdapter)
        self.assertEqual(wan_adapter.metadata()["modes"], ["image-to-video"])

        # Check explicit states in statuses()
        current_statuses = statuses()
        self.assertGreater(len(current_statuses), 0)
        for s in current_statuses:
            self.assertIn("state", s)
            self.assertIn(s["state"], [e.value for e in ModelState])

    def test_09_strict_local_only_enforcement(self):
        """Verify LEXNIS_LOCAL_ONLY=1 blocks silent cloud fallbacks."""
        from campaign_generator import LexnisCampaignStudio
        from visual_engine import cloudflare_image

        studio = LexnisCampaignStudio()
        with patch.dict(os.environ, {"LEXNIS_LOCAL_ONLY": "1"}):
            # 1. Cloudflare image must raise
            with self.assertRaises(RuntimeError) as ctx1:
                cloudflare_image("robot", 42)
            self.assertIn("strict local-only mode", str(ctx1.exception))

            # 2. _fetch_image_bytes with cloud provider must raise
            with self.assertRaises(RuntimeError) as ctx2:
                studio._fetch_image_bytes("industrial robot", 42, model="flux")
            self.assertIn("strict local-only mode", str(ctx2.exception))

            # 3. _fetch_image_bytes with local model should not silently fallback to flux on error
            with patch("campaign_generator.local_image", side_effect=RuntimeError("CUDA out of memory")):
                with self.assertRaises(RuntimeError) as ctx3:
                    studio._fetch_image_bytes("industrial robot", 42, model="local:segmind-vega")
                self.assertIn("Strict local-only mode is active", str(ctx3.exception))

    def test_10_creative_fastapi_endpoints(self):
        """Verify /api/creative endpoints via FastAPI TestClient."""
        from fastapi.testclient import TestClient
        from server import app

        client = TestClient(app)

        # GET /api/creative/presets
        res_presets = client.get("/api/creative/presets")
        self.assertEqual(res_presets.status_code, 200)
        data = res_presets.json()
        self.assertIn("formats", data)
        self.assertIn("motion_presets", data)

        # POST /api/creative/projects (save project)
        test_proj = {
            "project_id": "test_api_proj_01",
            "name": "Test Agency Project",
            "scenes": [
                {
                    "scene_id": "scene_01",
                    "duration": 2.0,
                    "canvas": {"width": 720, "height": 720},
                    "layers": [
                        {
                            "layer_id": "l1",
                            "name": "Text",
                            "layer_type": "text",
                            "text_data": {"text": "API Test", "font_size": 28, "color": "#FFFFFF"},
                            "transform": {"x": 80, "y": 80}
                        }
                    ]
                }
            ]
        }
        res_save = client.post("/api/creative/projects", json={"project": test_proj})
        self.assertEqual(res_save.status_code, 200)
        self.assertEqual(res_save.json()["status"], "ok")

        # GET /api/creative/projects/{id}
        res_load = client.get("/api/creative/projects/test_api_proj_01")
        self.assertEqual(res_load.status_code, 200)
        self.assertEqual(res_load.json()["name"], "Test Agency Project")

        # POST /api/creative/qa/audit
        res_audit = client.post("/api/creative/qa/audit", json={"project_id": "test_api_proj_01"})
        self.assertEqual(res_audit.status_code, 200)
        self.assertIn("passed", res_audit.json())

        # POST /api/creative/render/still
        res_still = client.post("/api/creative/render/still", json={"project_id": "test_api_proj_01", "t": 0.0})
        self.assertEqual(res_still.status_code, 200)
        self.assertEqual(res_still.json()["status"], "ok")
        self.assertTrue(Path(res_still.json()["output_path"]).exists())

        # POST /api/creative/render/mp4
        res_mp4 = client.post("/api/creative/render/mp4", json={"project_id": "test_api_proj_01", "fps": 20})
        self.assertEqual(res_mp4.status_code, 200)
        self.assertEqual(res_mp4.json()["status"], "ok")
        out_mp4_path = Path(res_mp4.json()["output_path"])
        self.assertTrue(out_mp4_path.exists())

        # POST /api/creative/bridge-to-video (send rendered MP4 to Video Studio asset library)
        res_bridge = client.post("/api/creative/bridge-to-video", json={
            "output_path": str(out_mp4_path),
            "name": "Creative Scene Direct MP4"
        })
        self.assertEqual(res_bridge.status_code, 200)
        self.assertEqual(res_bridge.json()["status"], "ok")
        self.assertEqual(res_bridge.json()["kind"], "video")


if __name__ == "__main__":
    unittest.main()

