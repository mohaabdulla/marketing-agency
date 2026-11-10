"""Offline dual-slide rendering, API, layout and download regressions.

Run: python scripts/test_dual_social_images.py
Writes the six bilingual pairs requested by the companion-image brief.
"""
import io
import json
import socket
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import campaign_generator as campaign
import visual_engine as visual
from server import app, render_path

ASSETS = ROOT / "static" / "assets"


class DualSocialImagesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ASSETS.mkdir(parents=True, exist_ok=True)
        cls.pairs = []
        # Reuse the bundled portrait fixture, without inventing an uploaded person.
        subject = Image.open(ROOT / "test_assets" / "raw_subject.jpg").convert("RGB")
        w = int(subject.height * .75)
        left = (subject.width - w) // 2
        buf = io.BytesIO()
        subject.crop((left, 0, left+w, subject.height)).save(buf, "JPEG", quality=95)
        cls.subject = buf.getvalue()
        for kind in ("hiring", "launch", "welcome"):
            theme = visual.resolve_brand_theme(brand_name="Lexnis Technologies", post_type=kind)
            if kind == "welcome":
                theme.hashtag_ar = "#فريق_لكسنس"
            for lang in ("en", "ar"):
                ar = lang == "ar"
                if kind == "hiring":
                    title = "مهندس أول تعلم الآلة وأنظمة الرؤية الحاسوبية" if ar else "Senior Machine Learning & Vision Systems Engineer"
                    primary = visual.render_lexnis_hiring_card(role_title=title, language=lang)
                    filename = f"lexnis_hiring_{lang}.jpg"
                elif kind == "launch":
                    title = "Lexnis VisionOS 2.0"
                    primary = visual.render_lexnis_launch_card(product_name=title, language=lang)
                    filename = f"lexnis_launch_{lang}.jpg"
                else:
                    title = "مهندس ذكاء اصطناعي" if ar else "AI Engineer"
                    primary = visual.render_welcome_template_swap(cls.subject, name="Mohamed Redha", role=title, lang=lang, brand_name="Lexnis Technologies")
                    filename = f"api_swap_{lang}.jpg"
                req = dict(topic=title, post_type=kind, role_title=title, person_name="Mohamed Redha" if kind == "welcome" else "",
                           language=lang, use_local_sdxl=False, seed=7)
                pair = campaign.generate_campaign_post(primary, req, theme, output_path=ASSETS / filename)
                cls.pairs.append((kind, lang, pair))

    def test_six_pairs_exist_at_portrait_dimensions(self):
        for kind, lang, pair in self.pairs:
            with self.subTest(kind=kind, lang=lang):
                self.assertEqual(len(pair["carousel_paths"]), 2)
                for path in pair["carousel_paths"]:
                    self.assertTrue(Path(path).is_file())
                    with Image.open(path) as image:
                        self.assertEqual(image.size, (1080, 1350))
                self.assertNotEqual(Path(pair["primary_card"]).read_bytes(), Path(pair["companion_image"]).read_bytes())

    def test_companion_text_bounds_do_not_overlap(self):
        for kind, lang, pair in self.pairs:
            meta = json.loads(Path(pair["companion_image"]).with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(meta["source"], "editorial_showcase")
            boxes = meta["layout"]["text_boxes"]
            self.assertGreater(len(boxes), 12)
            for i, (x1, y1, x2, y2) in enumerate(boxes):
                self.assertTrue(0 <= x1 <= x2 <= 1080 and 0 <= y1 <= y2 <= 1350)
                for j, (a1, b1, a2, b2) in enumerate(boxes[:i]):
                    self.assertFalse(min(x2, a2) > max(x1, a1) and min(y2, b2) > max(y1, b1),
                                     f"{kind}/{lang}: overlapping text {i} and {j}")

    def test_both_slides_share_header_geometry(self):
        # Opaque glyph interiors must occupy the same positions on both backgrounds.
        asset = ASSETS / "brand_logo.png"
        if asset.exists():
            logo = visual.load_logo_pil(asset)
            aspect = logo.width / logo.height
            height = min(46, round(240 / aspect))
            logo = logo.resize((round(height * aspect), height), Image.Resampling.LANCZOS)
            left, top = 80, 68 + (46 - height) // 2
        else:
            logo = visual.render_lexnis_logo(height=32)
            left, top = 80, 91 - logo.height // 2
        mask = np.array(logo.getchannel("A")) > 250
        for kind, lang, pair in self.pairs:
            with Image.open(pair["primary_card"]) as image:
                a = np.array(image)
            with Image.open(pair["companion_image"]) as image:
                b = np.array(image)
            ca = a[top:top+logo.height, left:left+logo.width]
            cb = b[top:top+logo.height, left:left+logo.width]
            self.assertLess(np.abs(ca[mask].astype(float)-cb[mask]).mean(), 15, (kind, lang))
            expected = np.array(logo.convert("RGB"))[mask].astype(float)
            self.assertLess(np.abs(ca[mask].astype(float)-expected).mean(), 20, (kind, lang, "logo asset"))
            self.assertGreater(a[1307:1334, 896:1008].std(), 10)  # slide 01 micro-badge

    def test_prompt_aliases_and_brand_isolation(self):
        for alias, expected in [("team_welcome", "welcome"), ("product_launch", "launch"), ("hiring", "hiring"), ("case_study", "general")]:
            scene = campaign.build_companion_scene_prompt("Robotics inspection", alias, "Acme", "Robotics Engineer")
            self.assertEqual(scene["post_type"], expected)
            self.assertIn("Robotics", scene["scene_prompt"])
            self.assertNotIn("lexnis", json.dumps(scene).lower())
        self.assertIn("VISIONOS 2.0", campaign.build_companion_scene_prompt("VisionOS 2.0", "launch", "Lexnis")["overlay_pill"])

    def test_cpu_mode_never_calls_local_model(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "output") as td, \
             mock.patch.object(visual, "local_image", side_effect=AssertionError("GPU called")), \
             mock.patch.object(visual, "preferred_local_model", side_effect=AssertionError("GPU queried")):
            campaign.generate_companion_image(dict(topic="Solar analytics", post_type="general", use_local_sdxl=False),
                                              visual.resolve_brand_theme(brand_name="Acme"), str(Path(td) / "cpu.jpg"))

    def test_local_renderer_and_failure_fallback(self):
        buf = io.BytesIO()
        Image.new("RGB", (1080, 1350), "#334455").save(buf, "JPEG")
        with tempfile.TemporaryDirectory(dir=ROOT / "output") as td, \
             mock.patch.object(visual, "preferred_local_model", return_value=visual.REALISM_MODEL), \
             mock.patch.object(visual, "local_image", return_value=(buf.getvalue(), True)) as render:
            out = Path(td) / "local.jpg"
            campaign.generate_companion_image(dict(topic="Vision camera", post_type="launch", use_local_sdxl=True), {}, str(out))
            render.assert_called_once()
            self.assertEqual(json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["source"], "local_sdxl")
            render.side_effect = RuntimeError("GPU offline")
            campaign.generate_companion_image(dict(topic="Vision camera", post_type="launch", use_local_sdxl=True), {}, str(out))
            meta = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(meta["source"], "editorial_showcase")
            self.assertIn("GPU offline", meta["warning"])

    def test_off_switch_keeps_single_image_and_source_cache(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "output") as td:
            source = Path(td) / "original.jpg"
            Image.new("RGB", (1080, 1350), "white").save(source)
            original = source.read_bytes()
            pair = campaign.generate_campaign_post(source, {}, output_path=Path(td) / "single.jpg", generate_companion=False)
            self.assertEqual(pair["companion_image"], "")
            self.assertEqual(len(pair["carousel_paths"]), 1)
            self.assertEqual(source.read_bytes(), original)
            with Image.open(pair["primary_card"]) as image:
                self.assertEqual(image.getpixel((950, 1320)), (255, 255, 255))

    def test_template_api_alias_language_pair_and_logo_upload(self):
        client = TestClient(app)
        logo_buf = io.BytesIO()
        Image.new("RGBA", (200, 46), (255, 32, 64, 255)).save(logo_buf, "PNG")
        with mock.patch.object(visual, "draw_brand_header", wraps=visual.draw_brand_header) as header:
            response = client.post("/api/template/swap", files={
                "subject_file": ("subject.jpg", self.subject, "image/jpeg"),
                "template_file": ("template.jpg", (ROOT / "test_assets/template_reference.jpg").read_bytes(), "image/jpeg"),
                "logo_file": ("logo.png", logo_buf.getvalue(), "image/png")},
                data=dict(person_name="Mohamed Redha", person_title="AI Engineer", brand_name="Lexnis", language="both", use_local_sdxl="false"))
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["carousel_urls"], [data["image_url"], data["companion_image_url"]])
        self.assertEqual(data["arabic_carousel_urls"], [data["arabic_image_url"], data["arabic_companion_image_url"]])
        self.assertGreaterEqual(header.call_count, 4)
        for call in header.call_args_list:
            self.assertEqual(call.kwargs.get("custom_logo"), logo_buf.getvalue())
        download = client.post("/api/carousel/download", json={"urls": data["carousel_urls"]})
        self.assertEqual(download.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            self.assertEqual(archive.namelist(), ["slide_01.jpg", "slide_02.jpg"])
        self.assertEqual(client.post("/api/carousel/download", json={"urls": ["/etc/passwd"]}).status_code, 400)

    def test_campaign_endpoint_and_single_slide_opt_out(self):
        client = TestClient(app)
        real_connect = socket.socket.connect
        def no_external(sock, address):
            if address[0] not in ("127.0.0.1", "localhost", "::1"):
                raise OSError("offline test")
            return real_connect(sock, address)
        with mock.patch.object(campaign.LexnisCampaignStudio, "_chat", side_effect=RuntimeError("offline test")), \
             mock.patch.object(socket.socket, "connect", no_external):
            for enabled in (True, False):
                data = dict(prompt="Hiring a Computer Vision Engineer for Lexnis", brand="Lexnis", post_type="hiring",
                            person_name="Computer Vision Engineer", use_search=False, generate_companion=enabled, use_local_sdxl=False)
                response = client.post("/api/campaign/generate", json=data)
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(len(result["carousel_urls"]), 2 if enabled else 1)
                self.assertEqual(bool(result["companion_image_url"]), enabled)
                if enabled:
                    with Image.open(render_path(result["companion_image_url"])) as image:
                        self.assertEqual(image.size, (1080, 1350))

    def test_arabic_template_selection_and_opt_out(self):
        client = TestClient(app)
        for enabled in (True, False):
            response = client.post("/api/template-swap", files={
                "subject_file": ("subject.jpg", self.subject, "image/jpeg"),
                "template_file": ("template.jpg", (ROOT / "test_assets/template_reference.jpg").read_bytes(), "image/jpeg")},
                data=dict(person_name="Mohamed Redha", person_title="AI Engineer", brand_name="Lexnis",
                          language="ar", generate_companion=str(enabled).lower(), use_local_sdxl="false"))
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data["image_url"], data["arabic_image_url"])
            self.assertEqual(data["companion_image_url"], data["arabic_companion_image_url"])
            self.assertEqual(len(data["carousel_urls"]), 2 if enabled else 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
