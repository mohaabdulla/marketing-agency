"""Mask creation, feathering, inversion, and subject isolation operations."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Optional, Tuple, Union
import numpy as np
from PIL import Image, ImageFilter, ImageOps


class Mask:
    """Represents a single-channel alpha mask with non-destructive operations."""

    def __init__(self, image: Image.Image):
        # Always convert to 'L' (8-bit grayscale)
        self.image = image.convert("L")

    @classmethod
    def blank(cls, width: int, height: int, fill: int = 0) -> Mask:
        return cls(Image.new("L", (max(1, width), max(1, height)), fill))

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    def invert(self) -> Mask:
        return Mask(ImageOps.invert(self.image))

    def feather(self, radius: float = 4.0) -> Mask:
        if radius <= 0:
            return Mask(self.image.copy())
        return Mask(self.image.filter(ImageFilter.GaussianBlur(radius=radius)))

    def dilate(self, iterations: int = 1) -> Mask:
        return Mask(self.image.filter(ImageFilter.MaxFilter(size=1 + 2 * iterations)))

    def erode(self, iterations: int = 1) -> Mask:
        return Mask(self.image.filter(ImageFilter.MinFilter(size=1 + 2 * iterations)))

    def apply_to_rgba(self, image: Image.Image) -> Image.Image:
        """Apply this mask as the alpha channel of an image."""
        rgba = image.convert("RGBA")
        if (rgba.width, rgba.height) != (self.width, self.height):
            mask_resized = self.image.resize((rgba.width, rgba.height), Image.Resampling.BILINEAR)
        else:
            mask_resized = self.image

        r, g, b, _ = rgba.split()
        return Image.merge("RGBA", (r, g, b, mask_resized))

    def to_bytes(self, format: str = "PNG") -> bytes:
        buf = io.BytesIO()
        self.image.save(buf, format=format)
        return buf.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> Mask:
        img = Image.open(io.BytesIO(data))
        return cls(img)

