"""Export and animation motion presets for still images, GIFs, and video scenes."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
from .schemas import Keyframe


@dataclass
class ExportPreset:
    id: str
    name: str
    category: str  # image, motion, video
    width: int
    height: int
    fps: int = 0
    format: str = "png"
    codec: Optional[str] = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


EXPORT_PRESETS: Dict[str, ExportPreset] = {
    # Still Images
    "instagram_portrait": ExportPreset("instagram_portrait", "Instagram Portrait (4:5)", "image", 1080, 1350, 0, "jpg"),
    "instagram_square": ExportPreset("instagram_square", "Instagram Square (1:1)", "image", 1080, 1080, 0, "jpg"),
    "linkedin_feed": ExportPreset("linkedin_feed", "LinkedIn Feed Landscape (1.91:1)", "image", 1200, 627, 0, "png"),
    "story_reel_cover": ExportPreset("story_reel_cover", "Story / Reel Cover (9:16)", "image", 1080, 1920, 0, "jpg"),
    "youtube_thumbnail": ExportPreset("youtube_thumbnail", "YouTube Thumbnail (16:9)", "image", 1280, 720, 0, "jpg"),

    # Motion / GIF
    "gif_social": ExportPreset("gif_social", "GIF Social (Looping)", "motion", 1080, 1080, 15, "gif", note="Optimized palette"),
    "mp4_social": ExportPreset("mp4_social", "MP4 Motion Short (Direct Render)", "motion", 1080, 1080, 30, "mp4", codec="h264"),
    "webm_web": ExportPreset("webm_web", "WebM Transparent Animation", "motion", 1080, 1080, 30, "webm", codec="vp9"),

    # Video
    "vertical_9_16": ExportPreset("vertical_9_16", "Vertical HD (9:16)", "video", 1080, 1920, 30, "mp4", codec="h264"),
    "landscape_16_9": ExportPreset("landscape_16_9", "Landscape Full HD (16:9)", "video", 1920, 1080, 30, "mp4", codec="h264"),
    "square_1_1": ExportPreset("square_1_1", "Square HD (1:1)", "video", 1080, 1080, 30, "mp4", codec="h264"),
    "portrait_4_5": ExportPreset("portrait_4_5", "Portrait Social (4:5)", "video", 1080, 1350, 30, "mp4", codec="h264"),
    "draft_720p": ExportPreset("draft_720p", "Draft Fast Preview (720p)", "video", 1280, 720, 24, "mp4", codec="h264"),
}

FORMAT_PRESETS = EXPORT_PRESETS


CAMERA_DIRECTION_PRESETS: Dict[str, Dict[str, str]] = {
    "static": {
        "label": "Static Tripod",
        "description": "Stationary framing, locked camera on subject.",
        "prompt_clause": "locked tripod shot, perfectly static stable commercial framing",
    },
    "slow_push_in": {
        "label": "Slow Push In",
        "description": "Subtle dolly forward into the subject.",
        "prompt_clause": "slow cinematic push-in towards the hero subject, smooth dolly in",
    },
    "slow_pull_out": {
        "label": "Slow Pull Out",
        "description": "Camera gradually pulls back to reveal the full environment.",
        "prompt_clause": "gradual cinematic pull-out revealing the surrounding architectural environment",
    },
    "pan_left": {
        "label": "Pan Left",
        "description": "Smooth horizontal scan to the left.",
        "prompt_clause": "smooth cinematic pan from right to left across the workspace",
    },
    "pan_right": {
        "label": "Pan Right",
        "description": "Smooth horizontal scan to the right.",
        "prompt_clause": "smooth cinematic horizontal pan from left to right",
    },
    "orbit": {
        "label": "Subtle Orbit",
        "description": "Gentle circular parallax around the product/person.",
        "prompt_clause": "subtle circular orbital parallax movement around the central product",
    },
    "macro_product": {
        "label": "Macro Detail",
        "description": "Extreme close-up focusing on textures and craft.",
        "prompt_clause": "macro lens close-up photography, shallow depth of field, sharp surface detail",
    },
}


class MotionPresetBuilder:
    """Generates animated keyframe tracks from professional motion presets."""

    @staticmethod
    def apply_preset(
        preset_name: str,
        start_time: float = 0.0,
        duration: float = 1.0,
        base_x: float = 0.0,
        base_y: float = 0.0,
        base_scale: float = 1.0
    ) -> Dict[str, List[Keyframe]]:
        p = preset_name.lower().replace("-", "_")
        end_time = start_time + duration

        if p == "fade_in":
            return {
                "opacity": [
                    Keyframe(time=start_time, value=0.0, easing="ease_out"),
                    Keyframe(time=end_time, value=1.0, easing="ease_out"),
                ]
            }
        elif p == "slide_up":
            return {
                "y": [
                    Keyframe(time=start_time, value=base_y + 80.0, easing="ease_out"),
                    Keyframe(time=end_time, value=base_y, easing="ease_out"),
                ],
                "opacity": [
                    Keyframe(time=start_time, value=0.0, easing="ease_out"),
                    Keyframe(time=start_time + duration * 0.6, value=1.0, easing="ease_out"),
                ],
            }
        elif p == "slide_down":
            return {
                "y": [
                    Keyframe(time=start_time, value=base_y - 80.0, easing="ease_out"),
                    Keyframe(time=end_time, value=base_y, easing="ease_out"),
                ],
                "opacity": [
                    Keyframe(time=start_time, value=0.0, easing="ease_out"),
                    Keyframe(time=start_time + duration * 0.6, value=1.0, easing="ease_out"),
                ],
            }
        elif p == "scale_in":
            return {
                "scale_x": [
                    Keyframe(time=start_time, value=base_scale * 0.8, easing="overshoot"),
                    Keyframe(time=end_time, value=base_scale, easing="overshoot"),
                ],
                "scale_y": [
                    Keyframe(time=start_time, value=base_scale * 0.8, easing="overshoot"),
                    Keyframe(time=end_time, value=base_scale, easing="overshoot"),
                ],
                "opacity": [
                    Keyframe(time=start_time, value=0.0, easing="ease_out"),
                    Keyframe(time=start_time + duration * 0.5, value=1.0, easing="ease_out"),
                ],
            }
        elif p == "ken_burns":
            return {
                "scale_x": [
                    Keyframe(time=start_time, value=base_scale, easing="linear"),
                    Keyframe(time=end_time, value=base_scale * 1.15, easing="linear"),
                ],
                "scale_y": [
                    Keyframe(time=start_time, value=base_scale, easing="linear"),
                    Keyframe(time=end_time, value=base_scale * 1.15, easing="linear"),
                ],
                "x": [
                    Keyframe(time=start_time, value=base_x, easing="linear"),
                    Keyframe(time=end_time, value=base_x - 30.0, easing="linear"),
                ],
            }
        elif p == "cta_pop":
            mid_time = start_time + duration * 0.6
            return {
                "scale_x": [
                    Keyframe(time=start_time, value=base_scale * 0.85, easing="ease_out"),
                    Keyframe(time=mid_time, value=base_scale * 1.08, easing="ease_in_out"),
                    Keyframe(time=end_time, value=base_scale, easing="ease_out"),
                ],
                "scale_y": [
                    Keyframe(time=start_time, value=base_scale * 0.85, easing="ease_out"),
                    Keyframe(time=mid_time, value=base_scale * 1.08, easing="ease_in_out"),
                    Keyframe(time=end_time, value=base_scale, easing="ease_out"),
                ],
                "opacity": [
                    Keyframe(time=start_time, value=0.0, easing="ease_out"),
                    Keyframe(time=start_time + duration * 0.4, value=1.0, easing="ease_out"),
                ],
            }
        else:
            return {
                "opacity": [
                    Keyframe(time=start_time, value=1.0, easing="linear"),
                    Keyframe(time=end_time, value=1.0, easing="linear"),
                ]
            }

    @classmethod
    def ken_burns(
        cls,
        image_path: Optional[str] = None,
        canvas: Optional[Any] = None,
        duration: float = 3.0,
        zoom_start: float = 1.0,
        zoom_end: float = 1.15,
        scene_id: str = "scene_ken_burns"
    ):
        from .schemas import Scene, CanvasConfig, Layer, LayerType
        c = canvas or CanvasConfig(width=1080, height=1080)
        kf = cls.apply_preset("ken_burns", start_time=0.0, duration=duration, base_scale=zoom_start)
        layer = Layer(
            layer_id="bg_image",
            name="Hero Image",
            layer_type=LayerType.IMAGE if image_path else LayerType.SHAPE,
            properties={"image_path": image_path} if image_path else {"shape_type": "rectangle", "fill_color": "#182234"},
            keyframes=kf,
        )
        return Scene(scene_id=scene_id, duration=duration, canvas=c, layers=[layer])

    @classmethod
    def cta_pop(
        cls,
        text: str = "APPLY NOW",
        canvas: Optional[Any] = None,
        duration: float = 1.5,
        scene_id: str = "scene_cta_pop"
    ):
        from .schemas import Scene, CanvasConfig, Layer, LayerType, TextLayerData, TextRole
        c = canvas or CanvasConfig(width=1080, height=1080)
        kf = cls.apply_preset("cta_pop", start_time=0.0, duration=duration, base_scale=1.0)
        layer = Layer(
            layer_id="cta_badge",
            name="CTA Badge",
            layer_type=LayerType.TEXT,
            text_data=TextLayerData(
                text=text,
                font_size=26,
                text_role=TextRole.CTA,
                color="#041B15",
                bg_color="#00FFA3",
                bg_radius=16,
                padding=(24, 12),
            ),
            transform={"x": int(c.width * 0.1), "y": int(c.height * 0.85)},
            keyframes=kf,
        )
        return Scene(scene_id=scene_id, duration=duration, canvas=c, layers=[layer])


MOTION_PRESETS: Dict[str, str] = {
    "fade_in": "Fade In smoothly",
    "slide_up": "Slide Up from bottom",
    "slide_down": "Slide Down from top",
    "scale_in": "Scale In with overshoot",
    "ken_burns": "Cinematic slow zoom & pan",
    "cta_pop": "Pulsing Call-To-Action bounce",
}


def build_preset_scene(preset_name: str, **kwargs):
    builder = MotionPresetBuilder()
    if preset_name == "ken_burns":
        return builder.ken_burns(**kwargs)
    elif preset_name == "cta_pop":
        return builder.cta_pop(**kwargs)
    return builder.ken_burns(**kwargs)

