"""Every client's creative must come from that client's campaign: no house lines from another
brand, no invented figures or working patterns, and channel copy adapted from the written post.

Offline: the text model and external network are disabled, so these run in seconds.
"""
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import campaign_generator as campaign
import visual_engine as visual
import agency_suite
import server

HOUSE_LINES = ("8ms", "99.4", "99.9", "TensorRT", "Edge AI", "Flagship Innovation", "Core Lab", "Global HQ",
               "NEXT ERA OF AI", "PROVEN AT SCALE", "Visual Inspection", "NEURAL CORE", "PERCEPTION",
               "الذكاء الاصطناعي", "ميلي ثانية")
NOOR = {"brand_name": "Noor Solar", "brand_colors": {"primary": "#102B35", "accent": "#F5A623"}}


def card_text(card):
    return " ".join(" ".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v) for v in card.values())


class MissionHookTests(unittest.TestCase):
    def test_substrings_do_not_trigger_ai_hooks(self):
        # "ai" inside "Bahrain" / "Maintenance" and "edge" inside "knowledge" used to match.
        for is_ar in (False, True):
            hook = campaign.generate_hiring_mission_hook("Senior Sales Engineer", "We are hiring in Bahrain", is_ar)
            self.assertNotIn("AI", hook)
            self.assertNotIn("الذكاء الاصطناعي", hook)
            self.assertEqual(len(hook.split("\n")), 2)
        self.assertNotIn("AI", campaign.generate_hiring_mission_hook("Maintenance Technician", "hiring"))
        launch = campaign.generate_launch_mission_hook("HomeCell", "a knowledge hub for villa owners")
        self.assertNotIn("EDGE", launch)
        self.assertFalse(any(ch.isdigit() for ch in launch))

    def test_real_ai_roles_keep_their_hooks(self):
        self.assertIn("VISION", campaign.generate_hiring_mission_hook("Computer Vision Engineer", ""))
        self.assertIn("AI", campaign.generate_hiring_mission_hook("ML Engineer", "AI team"))

    def test_no_invented_product_or_team(self):
        self.assertEqual(campaign.detect_featured_person("Launch post for our new battery", "product_launch"), (None, None))
        role, team = campaign.detect_featured_person("We are hiring a Sales Engineer", "hiring")
        self.assertEqual((role, team), ("Sales Engineer", ""))
        self.assertEqual(campaign.request_location("We are hiring a Sales Engineer in Manama"), "Manama")
        self.assertEqual(campaign.request_location("we are hiring a sales engineer"), "")


class ClaimsTests(unittest.TestCase):
    EVIDENCE = "Solar for small businesses in the Gulf. Panels carry a 25-year warranty."

    def test_unsupported_figures_are_removed_and_reported(self):
        text = ("Your costs should not swing with the weather. Cut overhead by up to 45% within 90 days.\n\n"
                "Covered by a 25-year warranty. Support is available 24/7.")
        clean, removed = campaign.strip_unsupported_figures(text, self.EVIDENCE)
        self.assertNotIn("45%", clean)
        self.assertIn("25-year warranty", clean)
        self.assertIn("24/7", clean)
        self.assertEqual(removed, ["Cut overhead by up to 45% within 90 days."])
        self.assertEqual(campaign.unsupported_figures("خفض التكاليف بنسبة ٤٥٪", self.EVIDENCE), ["45"])

    def test_card_labels_need_evidence(self):
        pack = {"card_headline": "Power your villa / own your energy",
                "card_chips": ["Manama, Bahrain", "Full-Time", "Saves 40% yearly"],
                "focus_areas": ["Enterprise Accounts", "Solar Integration", "Deal Closing"],
                "card_overline": "Noor Solar HomeCell", "card_subtitle": "Pays back in 3 years"}
        creative = campaign.build_card_creative(pack, "hiring", "en", "Noor Solar",
                                                evidence="We are hiring a Sales Engineer in Manama", title="HomeCell")
        self.assertEqual(creative["headline"], "POWER YOUR VILLA\nOWN YOUR ENERGY")
        self.assertEqual(creative["chips"], ["Manama, Bahrain", "Enterprise Accounts", "Solar Integration"])
        self.assertEqual(creative["subtitle"], "")       # unsupported figure
        self.assertEqual(creative["overline"], "")       # only repeated brand + title
        stated = campaign.build_card_creative(pack, "hiring", "en", "Noor Solar",
                                              evidence="Full-time Sales Engineer in Manama; saves 40% yearly")
        self.assertEqual(stated["chips"], ["Manama, Bahrain", "Full-Time", "Saves 40% yearly"])

    def test_neutral_defaults_replace_house_lines_for_other_brands(self):
        legacy = {"hero_hook": "ARCHITECT THE\nNEXT ERA OF AI.", "chips": ["Global HQ", "Full-Time / Hybrid", "X Core Lab"],
                  "card_overline": "OPEN POSITION  //  AI & VISION ENGINEERING", "subcopy": ""}
        empty = campaign.build_card_creative({}, "hiring", "en", "Noor Solar")
        for lang in ("en", "ar"):
            card = campaign.apply_card_creative(legacy, empty, "hiring", lang, keep_house_lines=False)
            self.assertFalse([w for w in HOUSE_LINES if w in card_text(card)], card)
            self.assertEqual(card["focus_areas"], [])
        kept = campaign.apply_card_creative(legacy, empty, "hiring", "en", keep_house_lines=True)
        self.assertEqual(kept["hero_hook"], legacy["hero_hook"])


class CompanionAndKitTests(unittest.TestCase):
    def test_companion_uses_plain_labels_and_campaign_text(self):
        scene = campaign.build_companion_scene_prompt("battery launch", "product_launch", "Noor Solar", "HomeCell")
        self.assertFalse(scene["technical"])
        self.assertEqual(scene["core_label"], "NOOR SOLAR")
        creative = {"en": {"card_title": "HomeCell", "hero_hook": "POWER YOUR VILLA\nOWN YOUR ENERGY",
                           "card_subtitle": "Rooftop battery storage for villas.", "chips": ["Bahrain", "Villas", "Storage"]}}
        scene = campaign.build_companion_scene_prompt("battery launch", "product_launch", "Noor Solar", "HomeCell", creative=creative)
        self.assertEqual(scene["panel_title"], "HomeCell")
        self.assertEqual(scene["hook"], "Power your villa own your energy")
        self.assertEqual(scene["caption"], "Rooftop battery storage for villas.")
        self.assertEqual([m[0] for m in scene["metrics"]], ["Bahrain", "Villas", "Storage"])
        theme = visual.resolve_brand_theme(brand_profile=NOOR, brand_name="Noor Solar", post_type="product_launch")
        for lang in ("en", "ar"):
            image = visual.render_companion_showcase(scene, theme, lang)
            self.assertEqual(image.size, (1080, 1350))
        lexnis = campaign.build_companion_scene_prompt("edge AI launch", "product_launch", "Lexnis Technologies", "VisionAI")
        self.assertTrue(lexnis["technical"])

    def test_card_renders_without_focus_row_and_with_campaign_focus(self):
        theme = visual.resolve_brand_theme(brand_profile=NOOR, brand_name="Noor Solar", post_type="hiring")
        base = {"card_title": "Sales Engineer", "hero_hook": "JOIN THE TEAM\nSHAPING WHAT'S NEXT.",
                "chips": ["Manama", "Now Hiring", "Join Our Team"], "subcopy": "Bring your experience.", "cta_text": "APPLY NOW", "cta_url": ""}
        for focus in ([], ["Enterprise Accounts", "Solar Integration"]):
            for kind in ("hiring", "general"):
                image = visual.render_agency_card({**base, "focus_areas": focus}, theme, post_type=kind, language="en")
                self.assertEqual(image.size, (1080, 1350))

    def test_channel_copy_comes_from_the_written_campaign(self):
        pack = {"hook": "Keep your villa powered through every summer peak.",
                "caption": "HomeCell stores rooftop solar for the hours you need it most.\n\nDesigned for villas in Bahrain.",
                "highlights": ["Power through outages", "Use more of your own solar"], "cta": "Book a home energy consultation.",
                "hashtags": "#HomeCell #SolarBahrain"}
        copy = agency_suite.generate_campaign_copy({"post_type": "product_launch", "topic": "raw prompt text", "copy_pack": pack}, NOOR)
        self.assertEqual(copy["copy_source"], "campaign")
        for field in ("linkedin_post", "instagram_caption", "x_post"):
            self.assertIn(pack["hook"], copy[field])
        self.assertIn("• Power through outages", copy["linkedin_post"])
        self.assertIn("#HomeCell", copy["hashtags"])
        self.assertLessEqual(len(copy["x_post"]), 280)
        self.assertNotIn("raw prompt text", copy["linkedin_post"])
        long_copy = agency_suite.generate_campaign_copy({"copy_pack": {**pack, "hook": "word " * 70}}, NOOR)
        self.assertLessEqual(len(long_copy["x_post"]), 280)
        template = agency_suite.generate_campaign_copy({"post_type": "hiring", "role_title": "Sales Engineer"}, NOOR)
        self.assertEqual(template["copy_source"], "template")

    def test_client_paths_stay_inside_the_project(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as outside:
            outside.write(b"x")
        try:
            self.assertEqual(server.render_path(outside.name), "")
            self.assertFalse(server._inside_project(outside.name))
        finally:
            Path(outside.name).unlink()
        self.assertTrue(server._inside_project(str(ROOT / "static/assets/brand_logo.png")))
        self.assertEqual(server.render_path("/renders/../../server.py"), "")


class OfflineCampaignTests(unittest.TestCase):
    """Whole pipeline for a non-Lexnis client with the text model unreachable."""

    def test_other_brands_never_receive_house_lines(self):
        real_connect = socket.socket.connect

        def local_only(sock, address):
            if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "localhost", "::1"):
                raise OSError("offline test")
            return real_connect(sock, address)

        prompts = {"product_launch": "Launch post for Noor Solar's new rooftop battery system HomeCell for villas in Bahrain",
                   "hiring": "We are hiring a Senior Sales Engineer in Manama",
                   "general": "Why small businesses in the Gulf should invest in solar now"}
        with mock.patch.object(campaign.LexnisCampaignStudio, "_chat", side_effect=RuntimeError("offline test")), \
                mock.patch.object(socket.socket, "connect", local_only), \
                mock.patch.object(visual, "preferred_local_model", return_value=None):
            for post_type, prompt in prompts.items():
                with self.subTest(post_type=post_type):
                    asset = campaign.LexnisCampaignStudio().generate_campaign(
                        prompt=prompt, brand="Noor Solar", use_search=False, post_type=post_type,
                        brand_profile=dict(NOOR), generate_companion=True, use_local_sdxl=False)
                    for lang in ("en", "ar"):
                        text = card_text(asset.card_copy[lang])
                        self.assertFalse([w for w in HOUSE_LINES if w in text], text)
                        self.assertFalse(campaign.unsupported_figures(text, prompt), text)
                    companion = Path(asset.companion_image_path).with_suffix(".json").read_text(encoding="utf-8")
                    self.assertFalse([w for w in HOUSE_LINES if w in companion])
                    if post_type == "hiring":
                        self.assertEqual(asset.card_copy["en"]["city"], "MANAMA")


if __name__ == "__main__":
    unittest.main(verbosity=2)
