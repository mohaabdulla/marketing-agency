"""
Regression suite for the Team Welcome 2.5D card defects:

1. Camera / messenger filenames ("WhatsApp Image 2026-11-09 at 19.48.58") are never used as the
   person's name; the name and role come from the prompt instead.
2. Brand guidelines resolve to the right company (never a year or a generic filename) and a
   non-Lexnis guideline renders with its own colours, lockup and #<Brand>Team hashtag.
3. The headline always fits inside x = 80..1000 and sits fully above the pop-out head:
   headline ink y ~168..200, >= 15px clear gap, head top at 218, frame top at 335 (117px pop-out).
   Long / LLM-sentence headlines are replaced inside the renderer itself.
4. The subject is scaled uniformly (portrait photos are never squashed) and fills the frame.
5. A leftover "Lexnis Technologies" brand is overridden by an uploaded guideline (profile JSON
   or guideline text) unless the website is lexnis.com.

Run:  python scripts/test_welcome_card_fixes.py
"""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient

import visual_engine
from visual_engine import (
    FONTS_DIR,
    composite_template_swap,
    fit_popout_headline,
    place_popout_subject,
    resolve_brand_theme,
)
from campaign_generator import (
    LexnisCampaignStudio,
    detect_brand_name_from_guideline,
    detect_featured_person,
    is_generic_filename_name,
    resolve_featured_person,
    team_welcome_headline,
)
from server import app, resolve_request_brand

TEMPLATE = ROOT / "test_assets" / "template_reference.jpg"
SUBJECT = ROOT / "test_assets" / "raw_subject.jpg"
WELCOME_PROMPT = "welcoming new team member Mohamed Redha, AI Engineer, to the team"
WHATSAPP_NAME = "WhatsApp Image 2026 11 09 At 19.48.58"

TAB_GUIDELINE_TEXT = (
    "Tab · Version 3.0 · Final edition · 9 November 2026\n"
    "TAB / A CLEARER WAY TO WORK\n"
    "Visual brand guideline\n"
    "Tab keeps teams in flow. Tab primary indigo #4F46E5, Tab mint #48D7B4, Tab night #17243B.\n"
    "Tab product system, Tab social templates, Tab bilingual typography.\n"
)


def _portrait_subject_bytes() -> bytes:
    """A portrait-orientation (3:4) crop of the sample studio photo, like a phone/WhatsApp portrait."""
    im = Image.open(SUBJECT).convert("RGB")
    w, h = im.size
    crop_w = int(h * 0.75)
    left = (w - crop_w) // 2
    buf = io.BytesIO()
    im.crop((left, 0, left + crop_w, h)).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _tab_profile() -> dict:
    return LexnisCampaignStudio().extract_brand_profile_from_guideline(
        guideline_raw_text=TAB_GUIDELINE_TEXT, filename="Tab_Full_Visual_Brand_Guideline (1).pdf"
    )


class PersonNameTests(unittest.TestCase):
    def test_filename_names_are_detected(self):
        for junk in (WHATSAPP_NAME, "IMG_2034", "Screenshot 2026-11-09", "DSC 0012", "photo", "subject"):
            self.assertTrue(is_generic_filename_name(junk), junk)
        for real in ("Mohamed Redha", "Alisha Faisal", "Anyta Putri", "Sara Al-Khalifa"):
            self.assertFalse(is_generic_filename_name(real), real)

    def test_name_and_role_come_from_prompt(self):
        self.assertEqual(resolve_featured_person(WHATSAPP_NAME, "", WELCOME_PROMPT), ("Mohamed Redha", "AI Engineer"))
        self.assertEqual(resolve_featured_person("", None, WELCOME_PROMPT), ("Mohamed Redha", "AI Engineer"))
        # An explicitly typed name always wins.
        self.assertEqual(resolve_featured_person("Sara Ali", "CFO", WELCOME_PROMPT), ("Sara Ali", "CFO"))

    def test_acronyms_survive_title_casing(self):
        _, title = detect_featured_person(WELCOME_PROMPT, post_type="team_welcome")
        self.assertEqual(title, "AI Engineer")


class GuidelineBrandTests(unittest.TestCase):
    def test_brand_name_detection(self):
        lexnis_text = (
            "BRAND SYSTEM EXPANSION\nEDITION 01 · 2026\nBrand Identity Expansion,\n"
            "A working extension of the Lexnis Technologies Bahrain brand guidelines."
        )
        self.assertEqual(detect_brand_name_from_guideline(lexnis_text, "Brand guidelines document (3).pdf"), "Lexnis Technologies")
        self.assertEqual(detect_brand_name_from_guideline(TAB_GUIDELINE_TEXT, "Tab_Full_Visual_Brand_Guideline (1).pdf"), "Tab")
        self.assertEqual(detect_brand_name_from_guideline("", "Brand guidelines document (3).pdf"), "")
        self.assertEqual(detect_brand_name_from_guideline("Noor Solar Energy Brand Guidelines\nNoor Solar Energy", "x.pdf"), "Noor Solar Energy")
        prepared = ("Table of Contents\nIntroduction\nIdentity Manual\nPrepared for Noor Solar Energy\n"
                    "Noor Solar Energy powers homes across the Gulf.")
        self.assertEqual(detect_brand_name_from_guideline(prepared, "Brand guidelines document (3).pdf"), "Noor Solar Energy")
        self.assertEqual(detect_brand_name_from_guideline("Welcome to Sadad\nSadad payments", ""), "Sadad")

    def test_tab_profile_palette_roles(self):
        prof = _tab_profile()
        self.assertEqual(prof["brand_name"], "Tab")
        self.assertFalse(prof["is_lexnis"])
        self.assertEqual(prof["brand_colors"]["accent"], "#4F46E5")
        self.assertEqual(prof["brand_colors"]["primary"], "#17243B")  # dark canvas, not the accent
        theme = resolve_brand_theme(prof, None, "Tab", "team_welcome")
        self.assertFalse(theme.is_lexnis)
        self.assertEqual(theme.primary_hex.upper(), "#4F46E5")

    def test_welcome_headlines_are_short(self):
        for brand in ("Lexnis Technologies", "Tab", "Noor Solar Energy", "", "Brand"):
            self.assertLessEqual(len(team_welcome_headline(brand)), 26)
        self.assertEqual(team_welcome_headline("Tab"), "WELCOME TO TAB")
        self.assertEqual(team_welcome_headline("Lexnis Technologies"), "WELCOME TO THE TEAM")  # > 12 chars
        self.assertEqual(team_welcome_headline("Tab", "ar"), "أهلاً بك في فريقنا")


class BrandResolutionTests(unittest.TestCase):
    """A leftover 'Lexnis Technologies' is a stale default whenever a guideline is loaded."""

    def test_guideline_profile_overrides_stale_lexnis(self):
        brand, bp = resolve_request_brand("Lexnis Technologies", _tab_profile(), None, WELCOME_PROMPT, "")
        self.assertEqual(brand, "Tab")
        self.assertEqual(bp["brand_name"], "Tab")

    def test_guideline_text_overrides_stale_lexnis(self):
        brand, bp = resolve_request_brand("Lexnis Technologies", None, TAB_GUIDELINE_TEXT, WELCOME_PROMPT, "")
        self.assertEqual(brand, "Tab")
        self.assertFalse(bp.get("is_lexnis"))

    def test_lexnis_website_keeps_lexnis(self):
        brand, _ = resolve_request_brand("Lexnis Technologies", {"brand_name": "Brand", "locked_by_guidelines": True},
                                         None, WELCOME_PROMPT, "https://lexnis.com")
        self.assertEqual(brand, "Lexnis Technologies")

    def test_unnamed_guideline_never_falls_back_to_lexnis(self):
        brand, _ = resolve_request_brand("Lexnis Technologies", {"brand_name": "Brand", "locked_by_guidelines": True},
                                         None, WELCOME_PROMPT, "")
        self.assertEqual(brand, "")

    def test_no_guideline_keeps_typed_brand_and_drops_lexnis_profile(self):
        self.assertEqual(resolve_request_brand("Lexnis Technologies", None, None, "", "")[0], "Lexnis Technologies")
        brand, bp = resolve_request_brand("Acme Robotics", {"company_name": "Lexnis Technologies"}, None, "", "")
        self.assertEqual(brand, "Acme Robotics")
        self.assertEqual(bp, {})  # Lexnis DNA never styles another brand


class HeadlineFitTests(unittest.TestCase):
    def test_long_headlines_fit_safe_margins(self):
        draw = ImageDraw.Draw(Image.new("RGB", (1080, 400)))
        for text in ("WELCOME", "WELCOME TO THE TEAM", "LEXNIS TECHNOLOGIES WELCOMING NEW TEAM MEMBER!",
                     "A VERY LONG HEADLINE THAT SOMEONE TYPED INTO THE OVERRIDE FIELD FOR NO GOOD REASON"):
            fit = fit_popout_headline(draw, text, FONTS_DIR / "Poppins-Bold.ttf", max_w=920, preferred_h=64,
                                      max_h=109, start_size=46, min_single=32, min_double=28)
            self.assertLessEqual(fit["block_w"], 920, text)
            self.assertLessEqual(fit["block_h"], 109, text)


class SubjectPlacementTests(unittest.TestCase):
    def test_uniform_scale_preserves_aspect(self):
        # Synthetic 3:4 portrait silhouette: head ellipse + shoulders touching the bottom edge.
        h, w = 1200, 900
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        yy, xx = np.mgrid[0:h, 0:w]
        head = ((xx - 450) / 170.0) ** 2 + ((yy - 380) / 230.0) ** 2 <= 1.0
        shoulders = (yy >= 640) & (np.abs(xx - 450) <= 120 + (yy - 640) * 0.9)
        rgba[head | shoulders, 3] = 255
        rgba[head | shoulders, :3] = 128
        bgr, alpha, info = place_popout_subject(rgba, (1080, 1350), head_top_y=280, center_x=540,
                                                target_w=696 * 1.04, min_bottom_y=1032, window_w=696)
        rows = np.where((alpha > 0.5).any(axis=1))[0]
        cols = np.where((alpha > 0.5).any(axis=0))[0]
        self.assertAlmostEqual(int(rows[0]), 280, delta=2)
        # Head ellipse aspect (340 x 460) must survive placement unchanged.
        head_rows = alpha[rows[0]:rows[0] + int(460 * info["scale"]) - 4] > 0.5
        head_w = head_rows.any(axis=0).sum()
        self.assertAlmostEqual(head_w / (460 * info["scale"]), 340 / 460.0, delta=0.03)
        self.assertGreaterEqual(info["silhouette_bottom"], 1032 - 2)
        self.assertAlmostEqual((cols[0] + cols[-1]) / 2.0, 540, delta=6)


class BrandedCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.subject_bytes = _portrait_subject_bytes()

    def _assert_headline_clear(self, img):
        layout = img.info["popout_layout"]
        lo, hi = layout["safe_x"]
        self.assertEqual((lo, hi), (80, 1000))
        frame_top = layout["frame"][1]
        for (x0, y0, x1, y1) in layout["headline_boxes"]:
            self.assertGreaterEqual(x0, lo - 1)
            self.assertLessEqual(x1, hi + 1)
            self.assertLessEqual(x1 - x0, 920)
            self.assertGreaterEqual(layout["head_top"] - y1, 15, "headline must clear the head by >= 15px")
        # 2.5D pop-out preserved: the head rises well above the white frame's top border.
        self.assertLess(layout["head_top"], frame_top)
        self.assertGreaterEqual(layout["pop_out"], 100)
        self.assertEqual((layout["head_top"], frame_top, layout["pop_out"]), (218, 335, 117))
        # Pixel check: white headline ink in the headline band never leaves x = 72..1008.
        arr = np.asarray(img.convert("RGB")).astype(int)
        band = arr[136:layout["head_top"] - 4]
        white = (band > 235).all(axis=2)
        xs = np.where(white.any(axis=0))[0]
        self.assertTrue(xs.size > 0, "headline not drawn")
        self.assertGreaterEqual(int(xs.min()), lo - 1)
        self.assertLessEqual(int(xs.max()), hi + 1)

    def test_lexnis_long_headline_fits_and_clears_head(self):
        img = composite_template_swap(
            TEMPLATE, self.subject_bytes, target_size=(1080, 1350), person_name="Mohamed Redha",
            person_title="AI Engineer", brand_name="Lexnis Technologies", recolor_gradient=True,
            headline_text="LEXNIS TECHNOLOGIES WELCOMING NEW TEAM MEMBER!", post_type="team_welcome",
        )
        self.assertEqual(img.size, (1080, 1350))
        self.assertTrue(img.info["popout_layout"]["is_lexnis"])
        # The renderer never trusts a long LLM sentence as the welcome headline.
        self.assertEqual(img.info["popout_layout"]["headline_text"], "WELCOME TO THE TEAM")
        self._assert_headline_clear(img)

    def test_tab_guideline_card_has_no_lexnis_elements(self):
        prof = _tab_profile()
        theme = resolve_brand_theme(prof, None, "Tab", "team_welcome")
        with mock.patch.object(visual_engine, "render_lexnis_logo", wraps=visual_engine.render_lexnis_logo) as lexnis_logo, \
             mock.patch.object(visual_engine, "generate_chevron_field", wraps=visual_engine.generate_chevron_field) as chevrons, \
             mock.patch.object(visual_engine, "draw_brand_header", wraps=visual_engine.draw_brand_header) as header:
            img = composite_template_swap(
                TEMPLATE, self.subject_bytes, target_size=(1080, 1350), person_name="Mohamed Redha",
                person_title="AI Engineer", brand_name="Tab", brand_tag=prof["brand_tag"],
                brand_colors=prof["brand_colors"], recolor_gradient=True, headline_text=team_welcome_headline("Tab"),
                post_type="team_welcome", brand_theme=theme, brand_profile=prof,
            )
        lexnis_logo.assert_not_called()
        chevrons.assert_not_called()
        header.assert_called_once()
        header_theme = header.call_args[0][1]
        self.assertEqual(header_theme.brand_name, "Tab")
        self.assertEqual(header_theme.hashtag_en, "#TabTeam")
        self.assertFalse(img.info["popout_layout"]["is_lexnis"])
        self._assert_headline_clear(img)
        # No Lexnis Tech Green (#53B849) / Lime (#BCD755) pixels anywhere on the card.
        arr = np.asarray(img.convert("RGB")).astype(int)
        for rgb in ((83, 184, 73), (188, 215, 85)):
            near = (np.abs(arr - np.array(rgb)).sum(axis=2) < 40).sum()
            self.assertLess(int(near), 20, f"found Lexnis colour {rgb}")

    def test_template_swap_endpoint_end_to_end(self):
        """Upload a WhatsApp-named photo with a stale Lexnis brand + Tab guideline profile."""
        client = TestClient(app)
        prof = _tab_profile()
        resp = client.post(
            "/api/template-swap",
            files={
                "template_file": ("template_reference.jpg", TEMPLATE.read_bytes(), "image/jpeg"),
                "subject_file": ("WhatsApp Image 2026-11-09 at 19.48.58.jpeg", self.subject_bytes, "image/jpeg"),
            },
            data={
                "person_name": WHATSAPP_NAME,
                "brand_name": "Lexnis Technologies",
                "brand_tag": "#LexnisTeam",
                "prompt": WELCOME_PROMPT,
                "brand_profile_json": json.dumps(prof),
                "language": "en",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["person_name"], "Mohamed Redha")
        self.assertEqual(data["person_title"], "AI Engineer")
        self.assertEqual(data["brand_name"], "Tab")
        self.assertEqual(data["headline_text"], "WELCOME TO TAB")
        self.assertFalse(data["is_lexnis"])
        self.assertEqual(data["brand_primary"].upper(), "#4F46E5")

    def test_template_swap_guideline_text_overrides_stale_lexnis(self):
        """Guideline TEXT only (no profile JSON) + leftover Lexnis brand + long LLM headline."""
        client = TestClient(app)
        with mock.patch.object(visual_engine, "draw_brand_header", wraps=visual_engine.draw_brand_header) as header, \
             mock.patch.object(visual_engine, "render_lexnis_logo", wraps=visual_engine.render_lexnis_logo) as lexnis_logo:
            resp = client.post(
                "/api/template-swap",
                files={
                    "template_file": ("template_reference.jpg", TEMPLATE.read_bytes(), "image/jpeg"),
                    "subject_file": ("WhatsApp Image 2026-11-09 at 19.48.58.jpeg", self.subject_bytes, "image/jpeg"),
                },
                data={
                    "brand_name": "Lexnis Technologies",
                    "prompt": WELCOME_PROMPT,
                    "guidelines": TAB_GUIDELINE_TEXT,
                    "headline_text": "LEXNIS TECHNOLOGIES WELCOMING NEW TEAM MEMBER!",
                    "language": "en",
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["brand_name"], "Tab")
        self.assertFalse(data["is_lexnis"])
        self.assertEqual(data["brand_primary"].upper(), "#4F46E5")
        self.assertEqual(data["headline_text"], "WELCOME TO TAB")
        self.assertEqual(data["person_name"], "Mohamed Redha")
        lexnis_logo.assert_not_called()
        header.assert_called_once()
        self.assertEqual(header.call_args[0][1].hashtag_en, "#TabTeam")


if __name__ == "__main__":
    unittest.main(verbosity=2)
