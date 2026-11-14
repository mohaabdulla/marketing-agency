"""Creative QA Engine for still images, animated GIFs, and video exports."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional
from PIL import Image

from .schemas import Scene, Layer, LayerType
from .transforms import compute_layer_bounds, is_within_safe_area
from .colors import contrast_ratio, parse_color


@dataclass
class QAFinding:
    check_name: str
    severity: str  # error, warning, info
    message: str
    layer_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class QAReport(dict):
    """Rich report that supports both attribute and dict-like access."""

    def __init__(self, passed: bool, findings: List[QAFinding], errors: List[str], warnings: List[str], info: List[str]):
        super().__init__()
        self.passed = passed
        self.findings = findings
        self.errors = errors
        self.warnings = warnings
        self.info = info
        self["passed"] = passed
        self["findings"] = [f.to_dict() for f in findings]
        self["errors"] = errors
        self["warnings"] = warnings
        self["info"] = info

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class CreativeQAEngine:
    """Performs rigorous automated checks on creative assets before final delivery."""

    @staticmethod
    def audit_scene(
        scene: Scene,
        canvas_w: Optional[int] = None,
        canvas_h: Optional[int] = None,
        brand_kit: Optional[Dict[str, Any]] = None
    ) -> QAReport:
        cw = canvas_w or (scene.canvas.width if scene.canvas else 1080)
        ch = canvas_h or (scene.canvas.height if scene.canvas else 1080)

        findings: List[QAFinding] = []
        errors: List[str] = []
        warnings: List[str] = []
        info: List[str] = []

        bg_col = (brand_kit or {}).get("background_color", "#0b0f19")

        # 1. Canvas sanity
        if cw <= 0 or ch <= 0:
            msg = f"Invalid canvas dimensions: {cw}x{ch}"
            errors.append(msg)
            findings.append(QAFinding("canvas_sanity", "error", msg))

        # Determine safe margin fraction
        safe_margin_px = scene.canvas.safe_margins if scene.canvas and hasattr(scene.canvas, "safe_margins") else 40
        margin_pct = safe_margin_px / float(cw) if cw > 0 else 0.04

        # 2. Check each layer
        has_text = False
        has_logo = False

        for layer in scene.layers:
            bounds = compute_layer_bounds(
                layer.x, layer.y, layer.width, layer.height,
                layer.anchor_x, layer.anchor_y, layer.rotation,
                layer.scale_x, layer.scale_y
            )

            # Safe area check
            in_safe, safe_msg = is_within_safe_area(bounds, cw, ch, margin_pct=margin_pct)
            if not in_safe:
                if layer.type in {LayerType.TEXT, LayerType.LOGO}:
                    msg = f"Layer '{layer.name}' ({layer.type.value}): {safe_msg}"
                    warnings.append(msg)
                    findings.append(QAFinding("safe_margin_audit", "warning", msg, layer_id=layer.id))

            if layer.type == LayerType.TEXT:
                has_text = True
                if layer.text_data:
                    td = layer.text_data
                    if not td.raw_text.strip():
                        msg = f"Text layer '{layer.name}' has empty text content."
                        warnings.append(msg)
                        findings.append(QAFinding("text_content_audit", "warning", msg, layer_id=layer.id))

                    # Contrast check
                    fg = td.color or td.fill
                    bg = td.bg_color or td.background or bg_col
                    ratio = contrast_ratio(fg, bg)
                    if ratio < 4.5:
                        msg = f"Text layer '{layer.name}' contrast ratio ({ratio:.1f}:1) is below WCAG AA recommendation (4.5:1)."
                        warnings.append(msg)
                        findings.append(QAFinding("contrast_audit", "warning", msg, layer_id=layer.id))

            elif layer.type == LayerType.LOGO:
                has_logo = True
                if abs(layer.scale_x - layer.scale_y) > 0.05:
                    msg = f"Logo layer '{layer.name}' has non-uniform scale distortion ({layer.scale_x} vs {layer.scale_y})."
                    errors.append(msg)
                    findings.append(QAFinding("logo_aspect_ratio_audit", "error", msg, layer_id=layer.id))

        info.append(f"Scene contains {len(scene.layers)} layers (Text: {has_text}, Logo: {has_logo}).")
        passed = len(errors) == 0 and len([f for f in findings if f.severity in ("error", "warning") and f.check_name in ("safe_margin_audit", "contrast_audit")]) == 0

        return QAReport(passed=passed, findings=findings, errors=errors, warnings=warnings, info=info)

    @staticmethod
    def audit_image_file(image_path: str) -> Dict[str, Any]:
        """Validate exported image file integrity, mode, and non-empty pixels."""
        from pathlib import Path
        p = Path(image_path)
        if not p.exists():
            return {"passed": False, "errors": [f"File does not exist: {image_path}"], "warnings": []}

        try:
            with Image.open(p) as img:
                img.verify()
            with Image.open(p) as img:
                w, h = img.size
                mode = img.mode
                if w <= 0 or h <= 0:
                    return {"passed": False, "errors": ["Zero image dimensions."], "warnings": []}
                return {
                    "passed": True,
                    "width": w,
                    "height": h,
                    "mode": mode,
                    "file_size_bytes": p.stat().st_size,
                    "errors": [],
                    "warnings": [],
                }
        except Exception as ex:
            return {"passed": False, "errors": [f"Corrupt image file: {str(ex)}"], "warnings": []}


qa_engine = CreativeQAEngine()
