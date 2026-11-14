"""Scene graph management and temporal layer compositing engine."""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional
from PIL import Image, ImageDraw

from .schemas import Scene, Layer, LayerType, TextLayerData
from .keyframes import KeyframeTrack
from .transforms import compute_layer_bounds
from .colors import parse_color
from .typography import typography_engine


class SceneGraph:
    """Manages scene layers, temporal keyframe resolution, and deterministic rasterization."""

    def __init__(self, scene: Scene, canvas_w: int = 1080, canvas_h: int = 1080):
        self.scene = scene
        self.canvas_w = canvas_w
        self.canvas_h = canvas_h

    def add_layer(self, layer: Layer) -> None:
        self.scene.layers.append(layer)

    def remove_layer(self, layer_id: str) -> bool:
        initial_len = len(self.scene.layers)
        self.scene.layers = [l for l in self.scene.layers if l.id != layer_id]
        return len(self.scene.layers) < initial_len

    def get_layer(self, layer_id: str) -> Optional[Layer]:
        return next((l for l in self.scene.layers if l.id == layer_id), None)

    def reorder_layer(self, layer_id: str, new_z_index: int) -> bool:
        layer = self.get_layer(layer_id)
        if not layer:
            return False
        layer.z_index = new_z_index
        return True

    def resolve_layer_at_time(self, layer: Layer, t: float) -> Optional[Dict[str, Any]]:
        """Compute layer's animated properties at time t."""
        if not layer.visible:
            return None
        if t < layer.start or t > layer.end:
            return None

        kfs = layer.keyframes or {}

        x = KeyframeTrack.evaluate(kfs.get("x", []), t, layer.x)
        y = KeyframeTrack.evaluate(kfs.get("y", []), t, layer.y)
        scale_x = KeyframeTrack.evaluate(kfs.get("scale_x", []), t, layer.scale_x)
        scale_y = KeyframeTrack.evaluate(kfs.get("scale_y", []), t, layer.scale_y)
        rotation = KeyframeTrack.evaluate(kfs.get("rotation", []), t, layer.rotation)
        opacity = KeyframeTrack.evaluate(kfs.get("opacity", []), t, layer.opacity)

        if opacity <= 0.001:
            return None

        return {
            "layer": layer,
            "x": x,
            "y": y,
            "scale_x": scale_x,
            "scale_y": scale_y,
            "rotation": rotation,
            "opacity": max(0.0, min(1.0, opacity)),
            "width": layer.width,
            "height": layer.height,
        }

    def render_frame(
        self,
        t: float,
        asset_loader: Optional[callable] = None
    ) -> Image.Image:
        """Render the complete scene at time t into an RGBA Pillow Image."""
        # 1. Base background
        bg_config = self.scene.background or {"type": "color", "value": "#0b0f19"}
        frame = Image.new("RGBA", (self.canvas_w, self.canvas_h), parse_color(bg_config.get("value", "#0b0f19")))

        # 2. Sort visible layers by z-index
        sorted_layers = sorted(self.scene.layers, key=lambda l: l.z_index)

        for layer in sorted_layers:
            resolved = self.resolve_layer_at_time(layer, t)
            if not resolved:
                continue

            # Render layer content
            layer_img: Optional[Image.Image] = None

            if layer.type == LayerType.TEXT and layer.text_data:
                layer_img = typography_engine.render_layer(
                    layer.text_data,
                    int(layer.width),
                    int(layer.height),
                )
            elif layer.type in {LayerType.IMAGE, LayerType.LOGO, LayerType.GENERATED_IMAGE}:
                if asset_loader and layer.asset_id:
                    layer_img = asset_loader(layer.asset_id)
                if not layer_img:
                    # Colored placeholder rectangle for tests / missing assets
                    layer_img = Image.new("RGBA", (int(layer.width), int(layer.height)), (50, 100, 180, 200))

            if not layer_img:
                continue

            # Apply scale & transform
            target_w = max(1, int(layer_img.width * resolved["scale_x"]))
            target_h = max(1, int(layer_img.height * resolved["scale_y"]))
            if (target_w, target_h) != (layer_img.width, layer_img.height):
                layer_img = layer_img.resize((target_w, target_h), Image.Resampling.BILINEAR)

            # Apply rotation
            if resolved["rotation"] != 0:
                layer_img = layer_img.rotate(resolved["rotation"], expand=True, resample=Image.Resampling.BILINEAR)

            # Apply layer opacity
            if resolved["opacity"] < 0.999:
                r, g, b, a = layer_img.split()
                a_arr = (a.point(lambda p: int(p * resolved["opacity"])))
                layer_img = Image.merge("RGBA", (r, g, b, a_arr))

            # Composite onto frame
            pos_x = int(resolved["x"])
            pos_y = int(resolved["y"])
            frame.alpha_composite(layer_img, dest=(pos_x, pos_y))

        return frame

