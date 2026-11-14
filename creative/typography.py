"""Professional deterministic typography engine with Arabic/RTL support and auto-fit layout."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple, Union
from PIL import Image, ImageDraw, ImageFont

from .schemas import TextLayerData, TextDirection, TextRole
from .colors import parse_color, to_hex

# Leverage visual_engine's tested font loading and bidirectional text shaping
try:
    from visual_engine import get_font, prepare_bidi_text
except ImportError:
    def prepare_bidi_text(t: str) -> str:
        try:
            import arabic_reshaper
            from bidi.algorithm import get_display
            return get_display(arabic_reshaper.reshape(t))
        except Exception:
            return t

    def get_font(name: str = "Inter", size: int = 36, weight: str = "regular"):
        try:
            return ImageFont.truetype("arial.ttf", size)
        except Exception:
            return ImageFont.load_default()


def is_arabic_text(text: str) -> bool:
    """Check if string contains Arabic characters."""
    return bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]", text))


class TypographyEngine:
    """Renders high-fidelity typographic layers with font scaling, wrapping, and RTL shaping."""

    @staticmethod
    def is_arabic(text: str) -> bool:
        return is_arabic_text(text)

    @staticmethod
    def wrap_text(
        text: str,
        font: Optional[Any] = None,
        max_width: float = 400.0,
        is_ar: Optional[bool] = None,
        font_size: int = 36
    ) -> List[str]:
        """Wrap text into lines fitting max_width."""
        if font is None or isinstance(font, (int, float)):
            f_size = int(font) if isinstance(font, (int, float)) else font_size
            font = get_font("Inter", f_size, "bold")
        if is_ar is None:
            is_ar = is_arabic_text(text)

        words = text.split()
        if not words:
            return []

        lines = []
        current_line = []
        temp_img = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(temp_img)

        for w in words:
            test_line = " ".join(current_line + [w])
            shaped = prepare_bidi_text(test_line) if is_ar else test_line
            bbox = draw.textbbox((0, 0), shaped, font=font)
            line_w = bbox[2] - bbox[0]

            if line_w <= max_width or not current_line:
                current_line.append(w)
            else:
                lines.append(" ".join(current_line))
                current_line = [w]

        if current_line:
            lines.append(" ".join(current_line))

        return lines

    @classmethod
    def layout_text(
        cls,
        text_data: TextLayerData,
        target_width: float,
        target_height: float,
    ) -> Dict[str, Any]:
        """Compute fitted font size, wrapped lines, and bounding boxes."""
        raw_text = text_data.raw_text.strip()
        if not raw_text:
            return {"lines": [], "font": None, "width": 0, "height": 0, "font_size": text_data.font_size}

        is_ar = (
            text_data.direction == TextDirection.RTL
            or (text_data.direction == TextDirection.AUTO and is_arabic_text(raw_text))
        )

        font_family = text_data.font_family or ("Cairo" if is_ar else "Inter")
        current_size = text_data.font_size
        min_size = 14

        temp_img = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(temp_img)

        # Auto-fit loop if fit_mode == 'shrink' or lines exceed max_lines
        while current_size >= min_size:
            font = get_font(font_family, current_size, text_data.font_weight)
            wrapped_lines = cls.wrap_text(raw_text, font, target_width, is_ar=is_ar)

            if len(wrapped_lines) <= text_data.max_lines or text_data.fit_mode != "shrink":
                # Check height
                line_height_px = current_size * text_data.line_height
                total_h = len(wrapped_lines) * line_height_px
                if total_h <= target_height or current_size <= min_size:
                    break

            current_size -= 2

        # Truncate if exceeds max_lines
        if len(wrapped_lines) > text_data.max_lines and text_data.fit_mode == "truncate":
            wrapped_lines = wrapped_lines[:text_data.max_lines]
            wrapped_lines[-1] = wrapped_lines[-1].rstrip(". ") + "..."

        # Shape final lines for display
        shaped_lines = [
            prepare_bidi_text(l) if is_ar else l
            for l in wrapped_lines
        ]

        # Calculate exact bounding dimensions
        max_line_w = 0
        for l in shaped_lines:
            bbox = draw.textbbox((0, 0), l, font=font)
            max_line_w = max(max_line_w, bbox[2] - bbox[0])

        total_height = max(1, int(len(shaped_lines) * current_size * text_data.line_height))

        return {
            "lines": shaped_lines,
            "raw_lines": wrapped_lines,
            "font": font,
            "font_size": current_size,
            "line_height_px": current_size * text_data.line_height,
            "width": max_line_w,
            "height": total_height,
            "is_arabic": is_ar,
        }

    @classmethod
    def render_layer(
        cls,
        text_data: TextLayerData,
        width: int,
        height: int,
    ) -> Image.Image:
        """Render typography into an RGBA Pillow Image."""
        layout = cls.layout_text(text_data, float(width), float(height))
        img = Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        lines = layout["lines"]
        font = layout["font"]
        if not lines or not font:
            return img

        line_h = layout["line_height_px"]
        text_fill = parse_color(text_data.fill)
        align = text_data.alignment.lower()

        # Padding resolution
        if isinstance(text_data.padding, (tuple, list)):
            pad_x = int(text_data.padding[0])
            pad_y = int(text_data.padding[1])
        else:
            pad_x = pad_y = int(text_data.padding or 0)

        # Render optional background pill/box
        if text_data.background:
            bg_color = parse_color(text_data.background)
            bg_w = min(width, int(layout["width"] + pad_x * 2))
            bg_h = min(height, int(layout["height"] + pad_y * 2))
            radius = getattr(text_data, "bg_radius", 6) or 6
            draw.rounded_rectangle([0, 0, bg_w, bg_h], radius=radius, fill=bg_color)

        # Draw lines
        y = pad_y
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            lw = bbox[2] - bbox[0]

            if align == "center":
                x = (width - lw) // 2
            elif align == "right":
                x = width - lw - pad_x
            else:
                x = pad_x

            # Shadow
            if text_data.shadow:
                sh = text_data.shadow
                sh_col = parse_color(sh.get("color", "#00000080"))
                sh_x = x + sh.get("offset_x", 2)
                sh_y = y + sh.get("offset_y", 2)
                draw.text((sh_x, sh_y), line, font=font, fill=sh_col)

            # Stroke
            if text_data.stroke and text_data.stroke_width > 0:
                st_col = parse_color(text_data.stroke)
                sw = text_data.stroke_width
                draw.text((x, y), line, font=font, fill=text_fill, stroke_width=sw, stroke_fill=st_col)
            else:
                draw.text((x, y), line, font=font, fill=text_fill)

            y += line_h

        return img


typography_engine = TypographyEngine()
