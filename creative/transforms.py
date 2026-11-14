"""2D geometric transformations and layout geometry calculations."""
from __future__ import annotations

import math
from typing import Dict, Tuple


def transform_point(
    px: float,
    py: float,
    cx: float,
    cy: float,
    rotation_deg: float,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> Tuple[float, float]:
    """Rotate and scale a point (px, py) around center (cx, cy)."""
    # Scale relative to center
    dx = (px - cx) * scale_x
    dy = (py - cy) * scale_y

    # Rotate
    rad = math.radians(rotation_deg)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)

    rx = cx + (dx * cos_r - dy * sin_r)
    ry = cy + (dx * sin_r + dy * cos_r)
    return rx, ry


def compute_layer_bounds(
    x: float,
    y: float,
    width: float,
    height: float,
    anchor_x: float = 0.5,
    anchor_y: float = 0.5,
    rotation: float = 0.0,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> Dict[str, float]:
    """Compute axis-aligned bounding box for transformed layer."""
    cx = x + width * anchor_x
    cy = y + height * anchor_y

    corners = [
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
    ]

    transformed_corners = [
        transform_point(px, py, cx, cy, rotation, scale_x, scale_y)
        for px, py in corners
    ]

    xs = [pt[0] for pt in transformed_corners]
    ys = [pt[1] for pt in transformed_corners]

    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    return {
        "min_x": round(min_x, 2),
        "min_y": round(min_y, 2),
        "max_x": round(max_x, 2),
        "max_y": round(max_y, 2),
        "width": round(max_x - min_x, 2),
        "height": round(max_y - min_y, 2),
    }


def is_within_safe_area(
    bounds: Dict[str, float],
    canvas_w: int,
    canvas_h: int,
    margin_pct: float = 0.05,
) -> Tuple[bool, str]:
    """Check if bounds are completely inside canvas safe margins."""
    margin_x = canvas_w * margin_pct
    margin_y = canvas_h * margin_pct

    safe_min_x = margin_x
    safe_max_x = canvas_w - margin_x
    safe_min_y = margin_y
    safe_max_y = canvas_h - margin_y

    if bounds["min_x"] < safe_min_x:
        return False, f"Left edge ({bounds['min_x']}px) encroaches into {margin_pct*100}% safe margin."
    if bounds["max_x"] > safe_max_x:
        return False, f"Right edge ({bounds['max_x']}px) encroaches into {margin_pct*100}% safe margin."
    if bounds["min_y"] < safe_min_y:
        return False, f"Top edge ({bounds['min_y']}px) encroaches into {margin_pct*100}% safe margin."
    if bounds["max_y"] > safe_max_y:
        return False, f"Bottom edge ({bounds['max_y']}px) encroaches into {margin_pct*100}% safe margin."

    return True, "Within safe area"

