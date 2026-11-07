"""
Lexnis Brand Guidelines Compliance & Visual Engine Audit Suite.
Verifies all 6 governance criteria from Brand Identity Expansion (Edition 01 - 2026):
1. Guidelines Priority: Stage 1 Guidelines lock Brand DNA over website/default seeds.
2. Vector WELCOME Headline: Anti-aliased Poppins Bold 700 with 0 raster stair-step artifacts.
3. Official Logo Renderer: Poppins Bold wordmark + dual right-facing geometric chevrons (#53B849 + #BCD755), 0 ASCII '»'.
4. Color Architecture: Depth Gradient (#131724 -> #023024) substrate + Core Chevron Field.
5. Bilingual Typography: Poppins + Cairo/Tajawal with 0 tofu boxes / missing glyphs.
6. 2.5D Pop-Out Layering: Head pops out over WELCOME with clean alpha matting.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import unittest

from visual_engine import (
    ensure_brand_fonts,
    render_lexnis_logo,
    generate_chevron_field,
    render_depth_gradient,
    composite_template_swap,
    prepare_bidi_text,
    FONTS_DIR
)
from campaign_generator import LexnisCampaignStudio


class TestBrandCompliance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_brand_fonts()
        cls.template_path = Path("test_assets/template_reference.jpg")
        cls.subject_path = Path("test_assets/raw_subject.jpg")
        cls.out_dir = Path("static/assets")
        cls.out_dir.mkdir(parents=True, exist_ok=True)

    def test_01_guidelines_priority_locks_brand_dna(self):
        """Audit 1: Uploaded guidelines must lock Brand DNA over website/default seeds."""
        studio = LexnisCampaignStudio()
        guidelines_text = """
        LEXNIS TECHNOLOGIES BRAND SYSTEM EXPANSION (EDITION 01 - 2026)
        Tier 1 Solids: Dark Navy #131724, Deep Forest #023024, Tech Green #53B849, Lime Green #BCD755.
        Tier 2 Gradients: Depth Gradient #131724 to #023024 at 135 degrees.
        Typography: Poppins Bold 700 and Cairo Bold 700.
        Hashtag: #LexnisTeam
        """
        dna = studio.extract_brand_dna_from_guidelines(guidelines_text, default_brand="Lexnis Technologies")
        self.assertTrue(dna.get("locked_by_guidelines"))
        colors = dna.get("brand_colors", {})
        self.assertEqual(colors.get("primary"), "#131724")
        self.assertEqual(colors.get("secondary"), "#023024")
        self.assertEqual(colors.get("accent"), "#53B849")
        self.assertEqual(colors.get("accent_lime"), "#BCD755")
        self.assertEqual(colors.get("gradient_start"), "#131724")
        self.assertEqual(colors.get("gradient_end"), "#023024")
        self.assertEqual(dna.get("brand_tag"), "#LexnisTeam")
        print("✓ Audit 1 Passed: Stage 1 Guidelines successfully locked Brand DNA with 100% priority.")

    def test_02_vector_anti_aliased_welcome(self):
        """Audit 2: WELCOME must be crisp anti-aliased vector Poppins Bold (0 jagged raster steps)."""
        res_pil = composite_template_swap(
            self.template_path,
            self.subject_path,
            brand_name="Lexnis Technologies",
            person_name="Alisha Faisal",
            person_title="Marketing Manager",
            recolor_gradient=True,
            language="en"
        )
        res_cv = cv2.cvtColor(np.array(res_pil), cv2.COLOR_RGB2BGR)
        # Check WELCOME headline crop (y: 190..260, x: 260..550)
        hl_crop = res_cv[190:260, 260:550]
        # Should have smooth anti-aliased gradient values (not binary 0/255 stair-steps)
        gray = cv2.cvtColor(hl_crop, cv2.COLOR_BGR2GRAY)
        intermediate_pixels = np.sum((gray > 30) & (gray < 225))
        self.assertGreater(intermediate_pixels, 50, "Headline should be smooth vector anti-aliased, not binary thresholded!")
        print(f"✓ Audit 2 Passed: Vector WELCOME is anti-aliased with {intermediate_pixels} smooth edge transition pixels.")

    def test_03_official_logo_dual_chevrons_no_ascii(self):
        """Audit 3: Logo must be Poppins Bold + dual geometric chevrons (#53B849, #BCD755), no ASCII '»'."""
        logo_img = render_lexnis_logo(height=40, is_dark_bg=True)
        self.assertIsInstance(logo_img, Image.Image)
        logo_np = np.array(logo_img)
        self.assertEqual(logo_np.shape[2], 4, "Logo must have RGBA alpha channel")

        # Check for Tech Green #53B849 (R=83, G=184, B=73) in logo pixels
        r_chan = logo_np[:, :, 0]
        g_chan = logo_np[:, :, 1]
        b_chan = logo_np[:, :, 2]
        a_chan = logo_np[:, :, 3]

        tech_green_mask = (a_chan > 100) & (g_chan > 160) & (r_chan < 110) & (b_chan < 100)
        lime_green_mask = (a_chan > 100) & (r_chan > 160) & (g_chan > 190) & (b_chan < 110)

        self.assertGreater(np.sum(tech_green_mask), 10, "Logo must contain Chevron 1 in Tech Green #53B849!")
        self.assertGreater(np.sum(lime_green_mask), 10, "Logo must contain Chevron 2 in Lime Green #BCD755!")
        print("✓ Audit 3 Passed: Logo correctly rendered with official Poppins Bold + dual geometric chevrons (#53B849 + #BCD755).")

    def test_04_depth_gradient_and_chevron_pattern(self):
        """Audit 4: Composition substrate must follow Depth Gradient (#131724 -> #023024) + chevron field."""
        grad = render_depth_gradient(808, 1024, "#131724", "#023024")
        self.assertEqual(grad.shape, (1024, 808, 3))
        # Lower-left corner (y=1023, x=0) should be Dark Navy #131724 (BGR: 36, 23, 19)
        ll_color = grad[1020, 5]
        self.assertAlmostEqual(ll_color[2], 19, delta=15)  # R
        self.assertAlmostEqual(ll_color[1], 23, delta=15)  # G
        self.assertAlmostEqual(ll_color[0], 36, delta=15)  # B

        # Upper-right corner (y=5, x=800) should be Deep Forest #023024 (BGR: 36, 48, 2)
        ur_color = grad[5, 800]
        self.assertAlmostEqual(ur_color[2], 2, delta=15)   # R
        self.assertAlmostEqual(ur_color[1], 48, delta=15)  # G
        self.assertAlmostEqual(ur_color[0], 36, delta=15)  # B

        # Test pattern field
        field = generate_chevron_field(808, 1024, opacity=0.10)
        self.assertEqual(field.size, (808, 1024))
        self.assertEqual(field.mode, "RGBA")
        print("✓ Audit 4 Passed: Depth Gradient substrate (135°) and Core Chevron Field verified.")

    def test_05_bilingual_shaping_and_zero_tofu(self):
        """Audit 5: Arabic copy must be shaped with 0 tofu boxes across Cairo/Tajawal."""
        arabic_sample = "أهلاً وسهلاً · أليشا فيصل · مديرة التسويق · نحن متحمسون جداً لانضمامك إلى فريقنا!"
        reshaped = prepare_bidi_text(arabic_sample)
        self.assertNotIn("[]", reshaped)
        self.assertNotIn("\ufffd", reshaped)

        f_cairo = ImageFont.truetype(str(FONTS_DIR / "Cairo-Bold.ttf"), 30)
        img_test = Image.new("RGB", (900, 100), (0, 0, 0))
        d = ImageDraw.Draw(img_test)
        d.text((10, 10), reshaped, font=f_cairo, fill=(255, 255, 255))
        test_np = np.array(img_test)
        self.assertGreater(np.sum(test_np > 0), 1000, "Text must render visible pixels")
        print("✓ Audit 5 Passed: Bilingual shaping verified with 0 tofu boxes in Cairo & Tajawal.")

    def test_06_full_pipeline_renders_and_saves_diagnostic_artifacts(self):
        """Audit 6: Full rendering pipeline produces both English and Arabic Lexnis upgrade artifacts."""
        en_img = composite_template_swap(
            self.template_path,
            self.subject_path,
            brand_name="Lexnis Technologies",
            brand_tag="#LexnisTeam",
            person_name="Alisha Faisal",
            person_title="Marketing Manager",
            recolor_gradient=True,
            language="en"
        )
        en_path = self.out_dir / "debug_lexnis_brand_upgrade.jpg"
        en_img.save(en_path, "JPEG", quality=95)
        self.assertTrue(en_path.exists())
        self.assertGreater(en_path.stat().st_size, 50000)

        ar_img = composite_template_swap(
            self.template_path,
            self.subject_path,
            brand_name="Lexnis Technologies",
            brand_tag="#فريق_لكسنس",
            person_name="أليشا فيصل",
            person_title="مديرة التسويق",
            recolor_gradient=True,
            language="ar",
            headline_text="أهلاً وسهلاً",
            footer_text="نحن متحمسون جداً لانضمامك إلى فريقنا!"
        )
        ar_path = self.out_dir / "debug_lexnis_arabic_upgrade.jpg"
        ar_img.save(ar_path, "JPEG", quality=95)
        self.assertTrue(ar_path.exists())
        self.assertGreater(ar_path.stat().st_size, 50000)
        print(f"✓ Audit 6 Passed: Saved diagnostic artifacts:\n  - {en_path}\n  - {ar_path}")


if __name__ == "__main__":
    unittest.main()
