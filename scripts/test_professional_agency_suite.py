"""Offline agency integration tests; no paid API or GPU inference required."""
import io
import json
import socket
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image, ImageSequence
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import campaign_generator as campaign
import visual_engine as visual
import server
import brand_kits


class AgencySuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = __import__('contextlib').ExitStack()
        cls.stack.enter_context(mock.patch.object(server, "AGENCY_BUNDLES_DIR", server.RENDERS_DIR))
        cls.stack.enter_context(mock.patch.object(visual, "preferred_local_model", return_value=None))
        cls.stack.enter_context(mock.patch.object(campaign.LexnisCampaignStudio, "_chat", side_effect=RuntimeError("offline test")))
        cls.stack.enter_context(mock.patch.object(campaign.LexnisCampaignStudio, "analyze_company_website", return_value={}))
        cls.client = TestClient(server.app)
        cls.results = []
        for language in ("en", "ar"):
            result = cls.client.post("/api/campaign/generate", json=dict(prompt="Hiring an AI Engineer for Lexnis Technologies", brand="Lexnis Technologies",
                         post_type="hiring", person_name="AI Engineer", language=language, use_search=False, use_local_sdxl=False))
            if result.status_code != 200:
                raise AssertionError(result.text)
            cls.results.append(("campaign", language, result.json()))
            result = cls.client.post("/api/template/swap", files={
                "subject_file": ("employee.jpg", (ROOT/"test_assets/raw_subject.jpg").read_bytes(), "image/jpeg"),
                "template_file": ("template.jpg", (ROOT/"test_assets/template_reference.jpg").read_bytes(), "image/jpeg")},
                data=dict(brand_name="Lexnis Technologies", person_name="Mohamed Redha", person_title="AI Engineer", language=language, use_local_sdxl="false"))
            if result.status_code != 200:
                raise AssertionError(result.text)
            cls.results.append(("welcome", language, result.json()))
        (ROOT/"output/professional_agency_results.json").write_text(json.dumps(cls.results, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def test_both_endpoints_both_languages(self):
        for kind, lang, data in self.results:
            with self.subTest(kind=kind, language=lang):
                for key in ("image_url", "companion_image_url", "animation_url", "story_url", "landscape_url", "bundle_zip_url", "copywriting"):
                    self.assertTrue(data.get(key), (key, data))
                self.assertEqual(data["copywriting"]["language"], lang)
                self.assertLess(len(data["copywriting"]["x_post"]), 280)
                self.assertTrue(8 <= len(data["copywriting"]["hashtags"]) <= 10)
                for key in ("linkedin_post", "instagram_caption", "posting_recommendation"):
                    self.assertTrue(data["copywriting"][key])
                if lang == "ar":
                    self.assertRegex(data["copywriting"]["linkedin_post"], r"[\u0600-\u06ff]")

    def test_format_dimensions_and_readable_story(self):
        for _, _, data in self.results:
            for key, size in (("image_url", (1080,1350)), ("companion_image_url", (1080,1350)), ("story_url", (1080,1920)), ("landscape_url", (1200,628))):
                response = self.client.get(data[key])
                self.assertEqual(response.status_code, 200, data[key])
                with Image.open(io.BytesIO(response.content)) as image:
                    self.assertEqual(image.size, size)

    def test_gif_loop_and_optional_mp4(self):
        import cv2
        for _, _, data in self.results:
            with Image.open(server.render_path(data["animation_url"])) as gif:
                self.assertGreaterEqual(gif.n_frames, 16)
                self.assertEqual(gif.info["loop"], 0)
                duration = sum(frame.info["duration"] for frame in ImageSequence.Iterator(gif))
                self.assertEqual(duration, 4320)
            if data.get("animation_mp4_url"):
                video = cv2.VideoCapture(server.render_path(data["animation_mp4_url"]))
                self.assertTrue(video.isOpened())
                self.assertAlmostEqual(video.get(cv2.CAP_PROP_FPS), 24, delta=.1)
                self.assertEqual(int(video.get(cv2.CAP_PROP_FRAME_WIDTH)), 1080)
                self.assertEqual(int(video.get(cv2.CAP_PROP_FRAME_HEIGHT)), 1350)
                video.release()

    def test_complete_zip_contents_and_rebundle(self):
        for _, _, data in self.results:
            response = self.client.get(data["bundle_zip_url"])
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                self.assertIsNone(archive.testzip())
                for name in ("01_primary_feed_1080x1350.jpg", "02_companion_feed_1080x1350.jpg", "03_animated_companion.gif",
                             "04_story_9x16_1080x1920.jpg", "05_landscape_1200x628.jpg", "campaign_copy_and_strategy.txt"):
                    self.assertIn(name, archive.namelist())
                self.assertIn(data["copywriting"]["x_post"], archive.read("campaign_copy_and_strategy.txt").decode("utf-8"))
        data = self.results[0][2]
        response = self.client.post("/api/campaign/bundle", json=dict(deliverables={key:data.get(key, "") for key in
             ("image_url","companion_image_url","animation_url","animation_mp4_url","story_url","landscape_url")}, copywriting=data["copywriting"]))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(response.json()["bundle_zip_url"]).status_code, 200)
        self.assertEqual(self.client.post("/api/campaign/bundle", json={"deliverables":{"image_url":"C:/Windows/win.ini"}, "copywriting":{}}).status_code, 400)

    def test_brand_crud_persists_and_validates(self):
        with tempfile.TemporaryDirectory(dir=ROOT/"output") as td, mock.patch.object(brand_kits, "STORE", Path(td)/"brands.json"):
            brand_kits.STORE.write_text("[]", encoding="utf-8")
            brand = dict(brand_name="Example Client", primary_hex="#102030", accent_hex="#ECA234", logo_path="", tagline="Build together", hashtag="#ExampleClient")
            response = self.client.post("/api/brands", json=brand)
            self.assertEqual(response.status_code, 201)
            saved = response.json()["brand"]
            self.assertEqual(self.client.get("/api/brands/"+saved["id"]).json()["brand"]["brand_name"], brand["brand_name"])
            theme = visual.resolve_brand_theme(brand_profile=brand_kits.profile_for(saved), brand_name=saved["brand_name"], post_type="hiring")
            self.assertEqual(theme.primary_accent, (236,162,52))
            self.assertEqual(theme.hashtag_en, "#ExampleClient")
            self.assertEqual(self.client.get("/api/brands").json()["brands"][0]["id"], saved["id"])
            brand["tagline"] = "Updated tagline"
            self.assertEqual(self.client.put("/api/brands/"+saved["id"], json=brand).status_code, 200)
            self.assertEqual(json.loads(brand_kits.STORE.read_text())[0]["tagline"], brand["tagline"])
            self.assertEqual(self.client.post("/api/brands", json=brand).status_code, 409)
            self.assertEqual(self.client.post("/api/brands", json={**brand, "accent_hex":"bad"}).status_code, 422)
            self.assertEqual(self.client.delete("/api/brands/"+saved["id"]).status_code, 200)
            self.assertEqual(self.client.get("/api/brands").json()["brands"], [])

    def test_copy_key_points_and_topic_types(self):
        for kind in ("hiring", "launch", "welcome", "general"):
            for language in ("en", "ar"):
                copy = campaign.generate_campaign_copy(dict(topic="AI Engineer", post_type=kind, language=language,
                         person_name="Mohamed Redha", key_points=["Custom engineering focus"], key_points_ar=["تركيز هندسي مخصص"]), {"brand_name":"Lexnis Technologies"})
                self.assertIn("تركيز هندسي مخصص" if language == "ar" else "Custom engineering focus", copy["linkedin_post"])
                self.assertLess(len(copy["x_post"]), 280)

    def test_reroll_retains_the_agency_kit(self):
        data = self.results[0][2]
        pairs = []
        for prefix in ("", "arabic_"):
            pairs.append(dict(primary_card=server.render_path(data[prefix+"image_url"]),
                              companion_image=server.render_path(data[prefix+"companion_image_url"]),
                              animation=server.render_path(data[prefix+"animation_url"])))
        result = campaign.RenderResult(pairs[0]["primary_card"], pairs[0]["primary_card"], True, pairs[1]["primary_card"])
        with mock.patch.object(campaign.LexnisCampaignStudio, "render_image", return_value=result), \
             mock.patch.object(server, "generate_campaign_post", side_effect=pairs):
            response = self.client.post("/api/render", json=dict(visual_prompt="An AI research lab", seed=7,
                         brand="Lexnis Technologies", post_type="hiring", headline="AI Engineer", use_local_sdxl=False))
        self.assertEqual(response.status_code, 200, response.text)
        for key in ("copywriting", "story_url", "landscape_url", "bundle_zip_url"):
            self.assertTrue(response.json().get(key), key)
        self.assertEqual(bool(response.json().get("animation_mp4_url")), bool(data.get("animation_mp4_url")))

    def test_brand_colour_edits_invalidate_cached_primary(self):
        with mock.patch.object(campaign.LexnisCampaignStudio, "_chat", side_effect=RuntimeError("offline test")):
            studio = campaign.LexnisCampaignStudio()
            for brand in ("Noor Solar", "Lexnis Technologies"):
                profiles = [dict(source="client_brand_kit", brand_name=brand, brand_colors={"primary":"#102B35", "accent":colour})
                            for colour in ("#F5A623", "#48D7B4")]
                outputs = [studio.generate_campaign(prompt=f"Hiring an AI Engineer for {brand}", brand=brand,
                              post_type="hiring", person_name="AI Engineer", brand_profile=profile,
                              use_search=False, generate_companion=False, seed=7) for profile in profiles]
                self.assertNotEqual(outputs[0].image_path, outputs[1].image_path)
                self.assertNotEqual(Path(outputs[0].image_path).read_bytes(), Path(outputs[1].image_path).read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
