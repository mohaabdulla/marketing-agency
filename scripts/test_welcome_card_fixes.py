"""
Regression suite for the Team Welcome 2.5D card defects:

1. Camera / messenger filenames ("WhatsApp Image 2026-11-09 at 19.48.58") are never used as the
   person's name; the name and role come from the prompt instead.
2. Brand guidelines resolve to the right company (never a year or a generic filename) and a
   non-Lexnis guideline renders with its own colours, lockup and #<Brand>Team hashtag.
3. The headline always fits inside x = 72..1008 and sits fully above the pop-out head.
4. The subject is scaled uniformly (portrait photos are never squashed) and fills the frame.

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
from server import app

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
            self.assertLessEqual(len(team_welcome_headline(brand)), 24)
        self.assertEqual(team_welcome_headline("Tab"), "WELCOME TO TAB")


class HeadlineFitTests(unittest.TestCase):
    def test_long_headlines_fit_safe_margins(self):
        draw = ImageDraw.Draw(Image.new("RGB", (1080, 400)))
        for text in ("WELCOME", "WELCOME TO THE TEAM", "LEXNIS TECHNOLOGIES WELCOMING NEW TEAM MEMBER!",
                     "A VERY LONG HEADLINE THAT SOMEONE TYPED INTO THE OVERRIDE FIELD FOR NO GOOD REASON"):
            fit = fit_popout_headline(draw, text, FONTS_DIR / "Poppins-Bold.ttf", max_w=936, preferred_h=128,
                                      max_h=172, start_size=120, min_single=56, min_double=36)
            self.assertLessEqual(fit["block_w"], 936, text)
            self.assertLessEqual(fit["block_h"], 172, text)


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
        for (x0, y0, x1, y1) in layout["headline_boxes"]:
            self.assertGreaterEqual(x0, lo - 1)
            self.assertLessEqual(x1, hi + 1)
            self.assertLess(y1, layout["head_top"], "headline overlaps the pop-out head")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
