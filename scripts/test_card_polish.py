"""Pixel and asset regressions for the hiring/welcome card polish (offline)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import campaign_generator as campaign
import visual_engine as visual


class CardPolishTests(unittest.TestCase):
    def test_bundled_font_roles(self):
        for lang, role, filename in [
            ("en", "headline", "Montserrat-ExtraBold.ttf"),
            ("en", "chip", "Inter-SemiBold.ttf"),
            ("ar", "headline", "Cairo-ExtraBold.ttf"),
            ("ar", "name", "Cairo-Bold.ttf"),
            ("ar", "chip", "Cairo-SemiBold.ttf"),
        ]:
            font = campaign._load_font(24, lang=lang, role=role)
            self.assertEqual(Path(font.path).name, filename)

    def test_hair_matte_has_no_added_rim_colour(self):
        cutout = np.zeros((80, 80, 4), dtype=np.uint8)
        cutout[:, :, :3] = 35
        cutout[10:70, 10:70, 3] = 255
        result = visual.enhance_studio_portrait(
            cutout, {"bg_dark": (0, 0, 0), "primary_accent": (0, 255, 0)})
        np.testing.assert_array_equal(result[:, :, 0], result[:, :, 1])
        expected = Image.fromarray(cutout[:, :, 3]).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1))
        np.testing.assert_array_equal(result[:, :, 3], np.minimum(np.array(expected), cutout[:, :, 3]))

    def test_watermark_is_blended_above_pills_and_focus_strip_is_present(self):
        composite = Image.Image.alpha_composite
        text = ImageDraw.ImageDraw.text
        marks, labels = [], []

        def capture_composite(canvas, overlay, *args, **kwargs):
            if canvas.width == 936 and overlay.size == canvas.size:
                marks.append(overlay.copy())
            return composite(canvas, overlay, *args, **kwargs)

        def capture_text(draw, xy, value, *args, **kwargs):
            labels.append((value, xy))
            return text(draw, xy, value, *args, **kwargs)

        with mock.patch.object(Image.Image, "alpha_composite", capture_composite), \
             mock.patch.object(ImageDraw.ImageDraw, "text", capture_text):
            card = visual.render_lexnis_hiring_card()
        self.assertEqual(card.size, (1080, 1350))
        self.assertEqual(len(marks), 1)
        alpha = marks[0].getchannel("A")
        self.assertEqual(alpha.getextrema()[1], 18)
        bounds = alpha.getbbox()
        self.assertGreaterEqual(bounds[1], 20)
        self.assertLessEqual(bounds[3], marks[0].height - 114)
        label = next(xy for value, xy in labels if value == "KEY FOCUS AREAS")
        self.assertGreaterEqual(label[1], 1025)
        self.assertLess(label[1], 1065)
        self.assertIn("Tax-Free BHD Package", [value for value, _ in labels])

    def test_header_prefers_bundled_logo(self):
        theme = visual.resolve_brand_theme(brand_name="Lexnis", post_type="hiring")
        logo = Image.new("RGBA", (200, 46), (255, 0, 0, 255))
        canvas = Image.new("RGBA", (1080, 180), (0, 0, 0, 255))
        with mock.patch.object(Path, "is_file", return_value=True), \
             mock.patch.object(visual, "load_logo_pil", return_value=logo) as load, \
             mock.patch.object(visual, "render_lexnis_logo") as synthetic:
            visual.draw_brand_header(canvas, theme)
        self.assertEqual(Path(load.call_args.args[0]).name, "brand_logo.png")
        synthetic.assert_not_called()
        self.assertEqual(canvas.getpixel((80, 68)), (255, 0, 0, 255))


if __name__ == "__main__":
    unittest.main(verbosity=2)
