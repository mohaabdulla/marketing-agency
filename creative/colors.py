"""Color management, WCAG contrast calculations, and brand color validation."""
from __future__ import annotations

import math
import re
from typing import Tuple, Union

ColorRGBA = Tuple[int, int, int, int]
ColorRGB = Tuple[int, int, int]


def parse_color(c: Union[str, Tuple[int, ...]]) -> ColorRGBA:
    """Parse color from hex string (#fff, #ffffff, #ffffff80) or tuple into RGBA."""
    if isinstance(c, (tuple, list)):
        if len(c) == 3:
            return (int(c[0]), int(c[1]), int(c[2]), 255)
        elif len(c) >= 4:
            return (int(c[0]), int(c[1]), int(c[2]), int(c[3]))
        return (0, 0, 0, 255)

    s = str(c).strip().lstrip("#")
    if len(s) == 3:
        r = int(s[0] * 2, 16)
        g = int(s[1] * 2, 16)
        b = int(s[2] * 2, 16)
        return (r, g, b, 255)
    elif len(s) == 6:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        return (r, g, b, 255)
    elif len(s) == 8:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
        a = int(s[6:8], 16)
        return (r, g, b, a)

    # rgb/rgba string support
    rgb_m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)", str(c).lower())
    if rgb_m:
        r = int(rgb_m.group(1))
        g = int(rgb_m.group(2))
        b = int(rgb_m.group(3))
        a = int(float(rgb_m.group(4) or 1.0) * 255)
        return (r, g, b, a)

    return (0, 0, 0, 255)


hex_to_rgba = parse_color


def to_hex(color: Union[str, Tuple[int, ...]]) -> str:
    rgba = parse_color(color)
    return f"#{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}"


def relative_luminance(color: Union[str, Tuple[int, ...]]) -> float:
    """Compute relative luminance according to WCAG 2.1 specs."""
    r, g, b, _ = parse_color(color)

    def srgb_channel(val: int) -> float:
        c = val / 255.0
        return c / 12.92 if c <= 0.03928 else math.pow((c + 0.055) / 1.055, 2.4)

    return 0.2126 * srgb_channel(r) + 0.7152 * srgb_channel(g) + 0.0722 * srgb_channel(b)


def contrast_ratio(c1: Union[str, Tuple[int, ...]], c2: Union[str, Tuple[int, ...]]) -> float:
    """Calculate WCAG contrast ratio between two colors (range 1.0 to 21.0)."""
    l1 = relative_luminance(c1)
    l2 = relative_luminance(c2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


def is_wcag_aa(c1: Union[str, Tuple[int, ...]], c2: Union[str, Tuple[int, ...]], large_text: bool = False) -> bool:
    ratio = contrast_ratio(c1, c2)
    threshold = 3.0 if large_text else 4.5
    return ratio >= threshold


def color_distance(c1: Union[str, Tuple[int, ...]], c2: Union[str, Tuple[int, ...]]) -> float:
    """Calculate Euclidean distance in sRGB space (0.0 to ~441.7)."""
    r1, g1, b1, _ = parse_color(c1)
    r2, g2, b2, _ = parse_color(c2)
    return math.sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2)
