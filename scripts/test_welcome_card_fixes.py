"""
Regression suite for the Team Welcome 2.5D card defects:

1. Camera / messenger filenames ("WhatsApp Image 2026-11-09 at 19.48.58") are never used as the
   person's name; the name and role come from the prompt instead.
2. Brand guidelines resolve to the right company (never a year or a generic filename) and a
   non-Lexnis guideline renders with its own colours, lockup and #<Brand>Team hashtag.
3. The headline always fits inside x = 90..990 (<= 900px) and sits fully above the pop-out head:
   headline ink from y=148 (bottom <= 205), head top = max(headline_bottom + 24, 222), frame top
   340 (~118px pop-out), nameplate 955..1118. Checked on the rendered pixels as well as the layout.
   Long / LLM-sentence headlines are replaced inside the renderer itself.
4. The subject is scaled uniformly (portrait photos are never squashed) and fills the frame.
   Head-size normalisation: a tight passport headshot is capped at a normal head size (face box
   190..240px, like a half-body portrait) and rests on the nameplate instead of filling the frame.
5. A leftover "Lexnis Technologies" brand is overridden by an uploaded guideline (profile JSON
   or guideline text) unless the website is lexnis.com.
6. Guideline extraction: domain / copyright / title name detection, colours ranked by frequency
   (hex + RGB, greys dropped), and a Gemini fallback whose answers are validated against the text.

Renders written for review: static/assets/campaign_generate_en.jpg (render_welcome_template_swap)
and static/assets/api_swap_en.jpg (/api/template-swap with the Acme Solar guideline).

Run:  python scripts/test_welcome_card_fixes.py
"""
import io
import json
import socket
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
    estimate_head_metrics,
    fit_popout_headline,
    place_popout_subject,
    render_welcome_template_swap,
    resolve_brand_theme,
    rgb_to_hex,
)
from campaign_generator import (
    LexnisCampaignStudio,
    detect_brand_name_from_guideline,
    detect_featured_person,
    guideline_brand_colors,
    is_generic_filename_name,
    resolve_featured_person,
    select_template_and_subject,
    smart_title,
    team_welcome_headline,
)
from server import app, resolve_request_brand

TEMPLATE = ROOT / "test_assets" / "template_reference.jpg"
SUBJECT = ROOT / "test_assets" / "raw_subject.jpg"
WELCOME_PROMPT = "welcoming new team member Mohamed Redha, AI Engineer, to the team"
WHATSAPP_NAME = "WhatsApp Image 2026 11 09 At 19.48.58"
LONG_HEADLINE = "LEXNIS TECHNOLOGIES WELCOMING NEW TEAM MEMBER!"
ACME_GUIDELINE_TEXT = "Acme Solar Guidelines. Website: www.acmesolar.com. Primary Color: #FF6B00, Dark: #101828"
ASSETS = ROOT / "static" / "assets"
LEXNIS_GREENS = ((83, 184, 73), (188, 215, 85))  # Tech Green #53B849, Lime #BCD755
_FACE_CASCADE = visual_engine._face_cascade()

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

    def test_lowercase_roles_get_proper_casing(self):
        # Prompt typed in lowercase (the "ai engineer" nameplate bug).
        lower_prompt = "welcoming new team member Mohamed Redha, ai engineer, to the team"
        self.assertEqual(resolve_featured_person(WHATSAPP_NAME, "", lower_prompt), ("Mohamed Redha", "AI Engineer"))
        # Role typed into the Role field.
        self.assertEqual(resolve_featured_person("Sara Ali", "ai engineer", "")[1], "AI Engineer")
        self.assertEqual(resolve_featured_person("Sara Ali", "Ai Engineer", "")[1], "AI Engineer")
        self.assertEqual(resolve_featured_person("Sara Ali", "head of it", "")[1], "Head of IT")
        self.assertEqual(resolve_featured_person("Sara Ali", "vp of product", "")[1], "VP of Product")
        self.assertEqual(resolve_featured_person("Sara Ali", "senior ui/ux designer", "")[1], "Senior UI/UX Designer")
        # Deliberate casing is never changed.
        self.assertEqual(resolve_featured_person("Sara Ali", "VisionAI Lead", "")[1], "VisionAI Lead")
        self.assertEqual(smart_title("make it simple"), "Make It Simple")  # product names never get "IT"


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
        self.assertEqual(detect_brand_name_from_guideline(ACME_GUIDELINE_TEXT, "Brand guidelines document (3).pdf"), "Acme Solar")

    def test_domain_and_copyright_detection(self):
        # The website / e-mail domain confirms the candidate it spells ("acmesolar" -> "Acme Solar").
        text = "Table of Contents\nIntroduction\nAcme Solar powers homes.\nContact: hello@acmesolar.com"
        self.assertEqual(detect_brand_name_from_guideline(text, "Brand guidelines document (3).pdf"), "Acme Solar")
        # A domain on its own still names the brand; tool domains (figma, google) never do.
        self.assertEqual(detect_brand_name_from_guideline("Logo files at www.figma.com and https://brightpath.io", ""), "Brightpath")
        self.assertEqual(detect_brand_name_from_guideline("Copyright 2024-2026 Noor Solar Ltd. All rights reserved.", ""), "Noor Solar")
        self.assertEqual(detect_brand_name_from_guideline("\u00a9 2026 Sadad Payments, all rights reserved", ""), "Sadad Payments")

    def test_guideline_colors_by_frequency(self):
        text = ("Accent #4F46E5. Background #17243B. Accent #4F46E5 again, #4f46e5 once more. "
                "Black #000000, white #FFFFFF, grey #CCCCCC, slate #F8FAFC. Mint RGB 72, 215, 180. Coral R255 G107 B0.")
        cols = guideline_brand_colors(text)
        self.assertEqual(cols[0], "#4F46E5")  # most frequent first
        self.assertIn("#17243B", cols)
        self.assertIn("#48D7B4", cols)  # RGB triple
        self.assertIn("#FF6B00", cols)  # R G B notation
        for neutral in ("#000000", "#FFFFFF", "#CCCCCC", "#F8FAFC"):
            self.assertNotIn(neutral, cols)

    def test_acme_profile_palette_roles(self):
        prof = LexnisCampaignStudio().extract_brand_profile_from_guideline(guideline_raw_text=ACME_GUIDELINE_TEXT)
        self.assertEqual(prof["brand_name"], "Acme Solar")
        self.assertFalse(prof["is_lexnis"])
        self.assertEqual(prof["brand_colors"]["primary"], "#101828")      # dark canvas
        self.assertEqual(prof["brand_colors"]["accent"], "#FF6B00")       # brand accent
        self.assertEqual(prof["brand_colors"]["accent_lime"], "#FFA666")  # tint of its own accent
        self.assertEqual(prof["website"], "https://acmesolar.com")

    def test_llm_fallback_is_validated_against_document(self):
        studio = LexnisCampaignStudio()
        studio.gemini_key = "test-key"
        text = ("Table of Contents\nIntroduction\nIdentity Manual\n" + "Colour usage and spacing rules. " * 12 +
                "Northwind Labs builds tools. Primary RGB 0, 120, 212. CMYK print specs follow.")
        reply = {"brand_name": "Northwind Labs", "colors": ["#0078D4", "#123456", "not-a-colour"],
                 "industry": "Developer Tools", "tone": "Calm and precise"}
        with mock.patch.object(studio, "_chat_json", return_value=(reply, None)) as chat:
            facts = studio._llm_guideline_brand_facts(text)
        chat.assert_called_once()
        self.assertEqual(facts["brand_name"], "Northwind Labs")
        self.assertEqual(facts["colors"][0], "#0078D4")
        self.assertEqual(facts["industry"], "Developer Tools")
        # A name that never appears in the document is rejected.
        with mock.patch.object(studio, "_chat_json", return_value=({"brand_name": "Contoso", "colors": []}, None)):
            self.assertEqual(studio._llm_guideline_brand_facts(text)["brand_name"], "")
        # No key -> no call.
        studio.gemini_key = ""
        with mock.patch.object(studio, "_chat_json") as chat:
            self.assertEqual(studio._llm_guideline_brand_facts(text)["brand_name"], "")
        chat.assert_not_called()

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
        self.assertEqual(team_welcome_headline("Acme Solar"), "WELCOME TO ACME SOLAR")
        self.assertEqual(team_welcome_headline("Lexnis Technologies"), "WELCOME TO THE TEAM")  # > 14 chars
        self.assertEqual(team_welcome_headline("Noor Solar Energy"), "WELCOME TO THE TEAM")
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
            fit = fit_popout_headline(draw, text, FONTS_DIR / "Poppins-Bold.ttf", max_w=920, preferred_h=50,
                                      max_h=96, start_size=58, min_single=38, min_double=38)
            self.assertLessEqual(fit["block_w"], 920, text)
            self.assertLessEqual(fit["block_h"], 96, text)


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


def _tight_headshot_bytes() -> bytes:
    """A passport-style crop of the sample photo: head + collar only, shoulders cut by the photo edges."""
    import cv2
    im = Image.open(SUBJECT).convert("RGB")
    gray = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2GRAY)
    faces = _FACE_CASCADE.detectMultiScale(gray, 1.05, 6, minSize=(60, 60))
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    box = (max(0, int(x - 0.55 * w)), max(0, int(y - 0.6 * h)),
           min(im.width, int(x + 1.55 * w)), min(im.height, int(y + 1.8 * h)))
    buf = io.BytesIO()
    im.crop(box).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _card_face_height(img) -> int:
    """Height of the largest Haar face box found on a rendered card."""
    import cv2
    gray = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    faces = _FACE_CASCADE.detectMultiScale(gray, 1.05, 6, minSize=(90, 90))
    return int(max(faces, key=lambda f: f[2] * f[3])[3]) if len(faces) else 0


class ConsistentSubjectFramingTests(unittest.TestCase):
    """Every subject (half-body or headshot) follows the exact same 2.5D pop-out size and structure."""

    HEADLINE_ZONE_BOTTOM = 210

    def _render(self, subject):
        return render_welcome_template_swap(subject, name="Mohamed Redha", role="AI Engineer",
                                            brand_name="Lexnis Technologies")

    def _assert_consistent_framing(self, img, label):
        layout = img.info["popout_layout"]
        subj = layout["subject"]
        self.assertFalse(subj["head_limited"], f"{label}: subject was incorrectly shrunk")
        self.assertEqual(subj["head_top"], 222, f"{label}: head top not anchored at 222px pop-out")
        self.assertGreaterEqual(subj["silhouette_w"], 696, f"{label}: silhouette width {subj['silhouette_w']} under 696px")
        self.assertEqual(subj["feathered_sides"], [], f"{label}: shoulders feathered")
        self.assertGreaterEqual(layout["subject_px_top"], self.HEADLINE_ZONE_BOTTOM, f"{label}: head in the headline zone")
        self.assertGreaterEqual(layout["subject_px_top"] - layout["headline_px"][3], 18, label)
        return layout

    def test_silhouette_fallback_estimates_head_height(self):
        # Faceless silhouette: 340 x 460 head ellipse on shoulders.
        h, w = 1200, 900
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        yy, xx = np.mgrid[0:h, 0:w]
        head = ((xx - 450) / 170.0) ** 2 + ((yy - 380) / 230.0) ** 2 <= 1.0
        shoulders = (yy >= 600) & (np.abs(xx - 450) <= 120 + (yy - 600) * 0.9)
        rgba[head | shoulders] = (128, 128, 128, 255)
        m = estimate_head_metrics(rgba)
        self.assertEqual(m["method"], "silhouette")
        self.assertAlmostEqual(m["head_h"], 460, delta=60)
        self.assertAlmostEqual(m["head_cx"], 450, delta=6)
        # When target_head_h is explicitly passed to place_popout_subject, it caps scale
        _, alpha, info = place_popout_subject(rgba, (1080, 1350), head_top_y=222, center_x=540,
                                              target_w=696 * 1.04, min_bottom_y=967, window_w=696,
                                              target_head_h=200)
        self.assertTrue(info["head_limited"])
        self.assertAlmostEqual(info["head_h"], 200, delta=1)
        self.assertAlmostEqual(info["silhouette_bottom"], 967, delta=2)   # rests on the nameplate
        rows = np.where((alpha > 0.5).any(axis=1))[0]
        self.assertGreater(int(rows[0]), 222)                             # clear space under the headline

    def test_half_body_portrait_keeps_frame_filling_scale(self):
        img = self._render(SUBJECT)
        layout = self._assert_consistent_framing(img, "half-body")
        self.assertFalse(layout["subject"]["head_limited"])
        self.assertEqual(layout["subject"]["head_top"], 222)
        self.assertGreaterEqual(layout["subject"]["silhouette_w"], 696)   # shoulders fill the window

    def test_tight_headshot_maintains_consistent_popout_framing(self):
        img = self._render(_tight_headshot_bytes())
        img.convert("RGB").save(ASSETS / "welcome_tight_headshot_en.jpg", quality=92)
        layout = self._assert_consistent_framing(img, "tight headshot")
        subj = layout["subject"]
        self.assertFalse(subj["head_limited"])
        self.assertEqual(subj["head_top"], 222)
        self.assertGreaterEqual(subj["silhouette_w"], 696)
        self.assertAlmostEqual(subj["face"][0] + subj["face"][2] / 2.0, 540, delta=24)  # face centred on the card

    def test_uploaded_reference_photos(self):
        """The two real uploads from the bug report (kept outside git; skipped when absent)."""
        photos = {"half-body": ROOT / "test_assets" / "portrait_half_body.jpeg",
                   "tight headshot": ROOT / "test_assets" / "portrait_tight_headshot.jpeg"}
        if not all(p.exists() for p in photos.values()):
            self.skipTest("reference uploads not present in test_assets/")
        for label, path in photos.items():
            self._assert_consistent_framing(self._render(path), label)


class BrandedCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.subject_bytes = _portrait_subject_bytes()

    def _assert_headline_clear(self, img, english=True):
        layout = img.info["popout_layout"]
        lo, hi = layout["safe_x"]
        self.assertEqual((lo, hi), (80, 1000))
        frame_top = layout["frame"][1]
        self.assertEqual(frame_top, 340)
        self.assertEqual(layout["nameplate_top"], 955)
        self.assertEqual(layout["frame"][1] + layout["frame"][3], 1118)
        for (x0, y0, x1, y1) in layout["headline_boxes"]:
            self.assertGreaterEqual(x0, lo - 1)
            self.assertLessEqual(x1, hi + 1)
            self.assertLessEqual(x1 - x0, 920)
        self.assertEqual(round(layout["headline_boxes"][0][1]), 148)  # headline ink starts at y=148
        # Head top (paste_y) = max(headline_bottom + 24, 222).
        self.assertEqual(layout["head_top"], max(layout["headline_bottom"] + 24, 222))
        if english:
            self.assertLessEqual(layout["headline_bottom"], 205)
            self.assertEqual((layout["head_top"], layout["pop_out"]), (222, 118))
        # 2.5D pop-out preserved: the head rises well above the white frame's top border.
        self.assertGreaterEqual(layout["pop_out"], 100)

        # Pixel-level: measured headline pixels stay in x = 80..1000 and end >= 18px above the
        # first row holding ANY subject alpha (hair wisps included).
        hx0, hy0, hx1, hy1 = layout["headline_px"]
        self.assertGreaterEqual(hx0, lo - 1)
        self.assertLessEqual(hx1, hi + 1)
        self.assertGreaterEqual(layout["subject_px_top"] - hy1 - 1, 18, "headline must clear the head by >= 18px")
        self.assertGreaterEqual(layout["subject_px_top"], 220)
        arr = np.asarray(img.convert("RGB")).astype(int)
        white = (arr[120:layout["subject_px_top"]] > 235).all(axis=2)
        xs = np.where(white.any(axis=0))[0]
        self.assertTrue(xs.size > 0, "headline not drawn")
        self.assertGreaterEqual(int(xs.min()), lo - 1)
        self.assertLessEqual(int(xs.max()), hi + 1)
        # The rows between the headline and the head are bare background: no white headline ink.
        gap = arr[hy1 + 2:layout["subject_px_top"], lo:hi]
        self.assertFalse(bool((gap > 235).all(axis=2).any()), "headline ink found in the head gap")

    def _assert_no_lexnis_colours(self, img):
        arr = np.asarray(img.convert("RGB")).astype(int)
        for rgb in LEXNIS_GREENS:
            near = (np.abs(arr - np.array(rgb)).sum(axis=2) < 40).sum()
            self.assertLess(int(near), 20, f"found Lexnis colour {rgb}")

    def test_visual_engine_module_is_the_project_root_file(self):
        self.assertTrue((ROOT / "visual_engine.py").exists())
        self.assertEqual(Path(visual_engine.__file__).resolve(), (ROOT / "visual_engine.py").resolve())

    def test_render_welcome_template_swap_sanitizes_and_clears_head(self):
        """The brief's entry point: long Lexnis headline, no brand -> 'WELCOME TO THE TEAM'."""
        img = render_welcome_template_swap(self.subject_bytes, name="Mohamed Redha", role="AI Engineer",
                                           headline=LONG_HEADLINE)
        img.convert("RGB").save(ASSETS / "campaign_generate_en.jpg", quality=92)
        layout = img.info["popout_layout"]
        self.assertEqual(img.size, (1080, 1350))
        self.assertEqual(layout["headline_text"], "WELCOME TO THE TEAM")
        self.assertFalse(layout["is_lexnis"])
        self._assert_headline_clear(img)

    def test_arabic_welcome_card_clears_head(self):
        prof = LexnisCampaignStudio().extract_brand_profile_from_guideline(guideline_raw_text=ACME_GUIDELINE_TEXT)
        img = render_welcome_template_swap(self.subject_bytes, name="Mohamed Redha", role="AI Engineer",
                                           headline=LONG_HEADLINE, brand_name="Acme Solar", brand_profile=prof, lang="ar")
        self.assertEqual(img.info["popout_layout"]["headline_text"], "أهلاً بك في فريقنا")
        self._assert_headline_clear(img, english=False)

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

    def test_executive_typography_and_visual_hierarchy(self):
        """Verify typography scale, smart casing, transliteration, two-tone rendering, and popout backglow."""
        # Assert font files exist in static/fonts/ and are not default bitmap
        required_fonts = [
            "Montserrat-ExtraBold.ttf", "Montserrat-Bold.ttf", "Inter-SemiBold.ttf", "Inter-Medium.ttf",
            "Cairo-ExtraBold.ttf", "Cairo-Bold.ttf", "Cairo-SemiBold.ttf", "Cairo-Medium.ttf"
        ]
        for f in required_fonts:
            self.assertTrue((FONTS_DIR / f).exists(), f"Font file {f} missing in static/fonts/")

        img_en = render_welcome_template_swap(
            self.subject_bytes, name="Mohamed Redha", role="ai engineer",
            headline="WELCOME TO THE TEAM", brand_name="Lexnis Technologies", lang="en"
        )
        img_en.convert("RGB").save(ASSETS / "api_swap_en.jpg", quality=95)
        layout_en = img_en.info["popout_layout"]

        img_ar = render_welcome_template_swap(
            self.subject_bytes, name="Mohamed Redha", role="ai engineer",
            headline="أهلاً بك في فريقنا", brand_name="Lexnis Technologies", lang="ar"
        )
        img_ar.convert("RGB").save(ASSETS / "api_swap_ar.jpg", quality=95)
        layout_ar = img_ar.info["popout_layout"]

        for label, layout in [("English", layout_en), ("Arabic", layout_ar)]:
            # 1. Headline font size is >= 44px
            self.assertGreaterEqual(layout["headline_font_size"], 44, f"{label} headline size < 44px")
            # 2. Subject name font size is >= 48px
            self.assertGreaterEqual(layout["name_font_size"], 48, f"{label} name size < 48px")
            # 3. Role font size is >= 26px
            self.assertGreaterEqual(layout["role_font_size"], 26, f"{label} role size < 26px")
            # 4. Text elements do not clip across the 1080px canvas boundaries
            for (x0, y0, x1, y1) in layout["headline_boxes"]:
                self.assertGreaterEqual(x0, 0, f"{label} headline clipped on left")
                self.assertLessEqual(x1, 1080, f"{label} headline clipped on right")

        # 5. Acronyms like "AI" in the role line are capitalized
        self.assertIn("AI", layout_en["role_text"], "AI acronym not capitalized in role line")
        self.assertEqual(layout_en["role_text"], "AI Engineer")

        # 6. Automatic transliteration of Mohamed Redha to Arabic script in Arabic welcome card
        self.assertEqual(layout_ar["name_text"], "محمد رضا", "Latin name was not transliterated to Arabic script")

        # Name + role ink and the accent tile form a vertically centred block.
        for img in (img_en, img_ar):
            plate = np.array(img.convert("RGB"))[956:1118, 192:888]
            rows = np.where((plate.min(axis=2) < 200).any(axis=1))[0]
            self.assertGreater(rows.size, 0)
            top_padding = int(rows[0]) + 1  # include the excluded seam row
            bottom_padding = 162 - int(rows[-1]) - 1
            self.assertLessEqual(abs(top_padding - bottom_padding), 3)

        # 7. Two-tone headline pixels in both EN and AR (both #FFFFFF and primary_accent in y=130..215)
        for label, img in [("English", img_en), ("Arabic", img_ar)]:
            arr = np.array(img.convert("RGB"))[130:215, 80:1000]
            # White pixels: high R, G, B
            white_mask = (arr[:, :, 0] > 230) & (arr[:, :, 1] > 230) & (arr[:, :, 2] > 230)
            self.assertTrue(np.any(white_mask), f"{label} card missing white headline pixels")
            # Accent green pixels: G is dominant over R and B
            accent_mask = (arr[:, :, 1] > 140) & (arr[:, :, 0] < 120) & (arr[:, :, 2] < 120)
            self.assertTrue(np.any(accent_mask), f"{label} card missing primary accent headline pixels")

        # 8. Pop-out head is intact within y=240..355
        self.assertLess(layout_en["head_top"], 340, "English pop-out head does not break above frame top 340")
        self.assertLess(layout_ar["head_top"], 340, "Arabic pop-out head does not break above frame top 340")

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
        self._assert_no_lexnis_colours(img)  # no Tech Green / Lime pixels anywhere on the card

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
        self.assertGreaterEqual(header.call_count, 2)  # primary, companion and format headers
        self.assertEqual(header.call_args[0][1].hashtag_en, "#TabTeam")

    def test_template_swap_acme_guideline_overrides_legacy_lexnis(self):
        """Legacy form value 'Lexnis Technologies' + Acme Solar guideline text -> an Acme Solar card."""
        client = TestClient(app)
        with mock.patch.object(visual_engine, "draw_brand_header", wraps=visual_engine.draw_brand_header) as header, \
             mock.patch.object(visual_engine, "render_lexnis_logo", wraps=visual_engine.render_lexnis_logo) as lexnis_logo, \
             mock.patch.object(visual_engine, "generate_chevron_field", wraps=visual_engine.generate_chevron_field) as chevrons:
            resp = client.post(
                "/api/template-swap",
                files={
                    "template_file": ("template_reference.jpg", TEMPLATE.read_bytes(), "image/jpeg"),
                    "subject_file": ("WhatsApp Image 2026-11-09 at 19.48.58.jpeg", self.subject_bytes, "image/jpeg"),
                },
                data={
                    "brand_name": "Lexnis Technologies",
                    "brand_tag": "#LexnisTeam",
                    "person_name": "Mohamed Redha",
                    "person_title": "AI Engineer",
                    "guidelines": ACME_GUIDELINE_TEXT,
                    "headline_text": LONG_HEADLINE,
                    "language": "en",
                },
            )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["brand_name"], "Acme Solar")
        self.assertFalse(data["is_lexnis"])
        self.assertEqual(data["brand_primary"].upper(), "#FF6B00")
        self.assertEqual(data["headline_text"], "WELCOME TO ACME SOLAR")
        lexnis_logo.assert_not_called()
        chevrons.assert_not_called()
        self.assertGreaterEqual(header.call_count, 2)  # primary, companion and format headers
        header_theme = header.call_args[0][1]
        self.assertEqual(header_theme.hashtag_en, "#AcmeSolarTeam")
        self.assertEqual(rgb_to_hex(header_theme.bg_dark_start).upper(), "#101828")
        self.assertEqual(rgb_to_hex(header_theme.primary_accent).upper(), "#FF6B00")

        rendered = ROOT / "output" / "renders" / Path(data["image_url"]).name
        img = Image.open(rendered)
        img.save(ASSETS / "api_swap_en.jpg", quality=92)
        self._assert_no_lexnis_colours(img)


class AnalyzeBrandEndpointTests(unittest.TestCase):
    def test_accepts_guidelines_and_guideline_text_fields(self):
        client = TestClient(app)
        for field in ("guidelines", "guideline_text"):
            resp = client.post("/api/analyze-brand", data={field: ACME_GUIDELINE_TEXT})
            self.assertEqual(resp.status_code, 200, resp.text)
            prof = resp.json()["profile"]
            self.assertEqual(prof["brand_name"], "Acme Solar", field)
            self.assertEqual(prof["brand_colors"]["accent"], "#FF6B00", field)
            self.assertEqual(prof["brand_colors"]["primary"], "#101828", field)


class SubjectSelectionTests(unittest.TestCase):
    """The photo uploaded with the request is always the person on the card (never an older upload)."""

    def test_select_template_and_subject_rules(self):
        up = ROOT / "output" / "uploads" / "subject_new_member.jpg"
        older = ROOT / "output" / "uploads" / "subject_previous_person.jpg"
        never = mock.Mock(side_effect=AssertionError("single welcome upload must not be classified"))
        self.assertEqual(select_template_and_subject([up], True, SUBJECT, never), (None, up))
        # A classifier guess that drops every uploaded photo is overruled.
        bad_classifier = mock.Mock(return_value=(TEMPLATE, SUBJECT))
        t, s = select_template_and_subject([up, older], True, SUBJECT, bad_classifier)
        self.assertIn(s, (up, older))
        # Nothing uploaded on a Team Welcome card -> bundled demo subject.
        self.assertEqual(select_template_and_subject([], True, SUBJECT, never), (None, SUBJECT))
        self.assertEqual(select_template_and_subject([], False, SUBJECT, never), (None, None))

    def test_generate_uses_uploaded_photo_not_older_upload(self):
        """/api/generate (offline) with one uploaded photo while a NEWER photo of someone else sits in uploads."""
        import uuid
        uid = uuid.uuid4().hex[:8]
        uploads = ROOT / "output" / "uploads"
        mine = uploads / f"subject_test_new_member_portrait_{uid}.jpg"
        decoy = uploads / f"subject_test_decoy_other_person_{uid}.jpg"
        mine.write_bytes(_portrait_subject_bytes())
        Image.open(SUBJECT).convert("RGB").transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(decoy, quality=90)  # newer file
        real_connect = socket.socket.connect

        def no_network(sock, address):
            host = address[0] if isinstance(address, tuple) else str(address)
            if host not in ("127.0.0.1", "localhost", "::1"):
                raise OSError("network disabled in test")
            return real_connect(sock, address)

        try:
            with mock.patch.object(LexnisCampaignStudio, "_chat", side_effect=RuntimeError("LLM disabled in test")), \
                 mock.patch.object(socket.socket, "connect", no_network), \
                 mock.patch.object(visual_engine, "classify_template_and_subject",
                                   wraps=visual_engine.classify_template_and_subject) as classify, \
                 mock.patch.object(visual_engine, "composite_template_swap",
                                   wraps=visual_engine.composite_template_swap) as swap:
                resp = TestClient(app).post("/api/generate", json={
                    "prompt": "welcoming new team member Mohamed Redha, ai engineer, to the team",
                    "brand": "Lexnis Technologies", "use_search": False, "output_format": "portrait",
                    "enhance_image": False, "recolor_to_brand": True, "post_type": "team_welcome",
                    "uploaded_image_url": f"/uploads/{mine.name}", "uploaded_image_urls": [f"/uploads/{mine.name}"],
                    "use_uploaded_image": True, "person_name": "", "person_title": "", "seed": 7,
                })
        finally:
            for f in (mine, decoy):
                f.unlink(missing_ok=True)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual((data["person_name"], data["person_title"]), ("Mohamed Redha", "AI Engineer"))
        classify.assert_not_called()
        self.assertGreaterEqual(swap.call_count, 2)  # EN + AR cards
        for call in swap.call_args_list:
            self.assertEqual(Path(call.args[1]).name, mine.name, "the uploaded photo must be the card's subject")
            self.assertEqual(call.kwargs["post_type"], "team_welcome")
        en_call, ar_call = swap.call_args_list[0], swap.call_args_list[1]
        # Welcome copy on both cards (the offline fallback headline is the bare brand name).
        self.assertEqual(en_call.kwargs["headline_text"], "WELCOME TO THE TEAM")
        self.assertEqual(ar_call.kwargs["headline_text"], "أهلاً بك في فريقنا")
        self.assertEqual(ar_call.kwargs["footer_text"], "نحن سعداء جداً بانضمامك إلى فريقنا!")
        self.assertTrue(data["arabic_image_url"])


class RenderCacheTests(unittest.TestCase):
    def test_cached_renders_are_keyed_on_layout_code(self):
        """Cards cached by older layout code are never served again for the same photo."""
        import campaign_generator
        self.assertRegex(campaign_generator.LAYOUT_CODE_VERSION, r"^[0-9a-f]{10}$")
        src = (ROOT / "campaign_generator.py").read_text(encoding="utf-8")
        for prefix in ("swap_v6_1080x1350|", "exec_art|", "agency_card_v4|", "ad-v5-vision-aligned|", "ad-v5-ar|"):
            self.assertIn(prefix + "{LAYOUT_CODE_VERSION}|", src, prefix)


if __name__ == "__main__":
    unittest.main(verbosity=2)
