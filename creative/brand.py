"""Brand Kit bindings, brand lock enforcement, and typography role resolution."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from .schemas import Layer, LayerType, TextRole, TextLayerData
from .colors import contrast_ratio, is_wcag_aa, parse_color


DEFAULT_BRAND_KIT = {
    "brand_name": "Lexnis Technologies",
    "primary_color": "#10b981",
    "secondary_color": "#0ea5e9",
    "accent_color": "#a3e635",
    "background_color": "#0b0f19",
    "text_color": "#f8fafc",
    "fonts": {
        "headline_en": "Montserrat",
        "body_en": "Inter",
        "headline_ar": "Cairo",
        "body_ar": "Cairo",
    },
    "brand_lock": True,
}


class BrandKitBinder:
    """Binds corporate brand guidelines to scene layers and enforces brand safety constraints."""

    @staticmethod
    def apply_brand_to_text(text_data: TextLayerData, brand_kit: Dict[str, Any]) -> TextLayerData:
        bk = brand_kit or DEFAULT_BRAND_KIT
        fonts = bk.get("fonts", DEFAULT_BRAND_KIT["fonts"])
        is_ar = text_data.language == "ar"

        # Apply fonts based on role
        if text_data.text_role in {TextRole.HEADLINE, TextRole.METRIC}:
            text_data.font_family = fonts.get("headline_ar" if is_ar else "headline_en", "Montserrat")
            text_data.font_weight = "extrabold" if not is_ar else "bold"
        elif text_data.text_role == TextRole.EYEBROW:
            text_data.font_family = fonts.get("body_ar" if is_ar else "body_en", "Inter")
            text_data.font_weight = "bold"
            text_data.fill = bk.get("accent_color", "#10b981")
        elif text_data.text_role == TextRole.CTA:
            text_data.font_family = fonts.get("body_ar" if is_ar else "body_en", "Inter")
            text_data.font_weight = "bold"
            text_data.fill = "#000000" if bk.get("brand_lock") else text_data.fill
            text_data.background = bk.get("primary_color", "#10b981")
        else:
            text_data.font_family = fonts.get("body_ar" if is_ar else "body_en", "Inter")
            text_data.font_weight = "regular"

        return text_data

    @staticmethod
    def validate_brand_safety(
        layers: List[Layer],
        brand_kit: Dict[str, Any],
        canvas_w: int,
        canvas_h: int
    ) -> List[Dict[str, Any]]:
        """Audit brand fidelity: logo aspect ratio, minimum clear space, and text contrast."""
        issues: List[Dict[str, Any]] = []
        bk = brand_kit or DEFAULT_BRAND_KIT
        bg_col = bk.get("background_color", "#0b0f19")

        for layer in layers:
            # 1. Logo checks
            if layer.type == LayerType.LOGO:
                # Check scale aspect distortion
                if abs(layer.scale_x - layer.scale_y) > 0.05:
                    issues.append({
                        "severity": "ERROR",
                        "layer_id": layer.id,
                        "code": "LOGO_ASPECT_DISTORTION",
                        "message": f"Logo '{layer.name}' aspect ratio is distorted (scale_x={layer.scale_x}, scale_y={layer.scale_y}).",
                    })

                # Check edge margin (minimum 5% clear space)
                min_clear = min(canvas_w, canvas_h) * 0.04
                if layer.x < min_clear or layer.y < min_clear:
                    issues.append({
                        "severity": "WARNING",
                        "layer_id": layer.id,
                        "code": "LOGO_CLEAR_SPACE",
                        "message": f"Logo '{layer.name}' violates minimum recommended edge margin ({int(min_clear)}px).",
                    })

            # 2. Text contrast checks
            elif layer.type == LayerType.TEXT and layer.text_data:
                td = layer.text_data
                txt_col = td.fill
                ratio = contrast_ratio(txt_col, bg_col)
                if ratio < 3.0:
                    issues.append({
                        "severity": "WARNING",
                        "layer_id": layer.id,
                        "code": "LOW_TEXT_CONTRAST",
                        "message": f"Text layer '{layer.name}' contrast ratio ({ratio}:1) fails WCAG minimums against background.",
                    })

        return issues

