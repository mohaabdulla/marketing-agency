"""Creative Scene Graph, Layer, and Manifest Data Models for LEXNIS Studio."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union


class LayerType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    GENERATED_IMAGE = "generated-image"
    GENERATED_VIDEO = "generated-video"
    TEXT = "text"
    LOGO = "logo"
    SHAPE = "shape"
    GRADIENT = "gradient"
    AUDIO = "audio"
    GROUP = "group"


class TextRole(str, Enum):
    EYEBROW = "eyebrow"
    HEADLINE = "headline"
    SUBHEADLINE = "subheadline"
    BODY = "body"
    CTA = "cta"
    CAPTION = "caption"
    LEGAL = "legal"
    NAME = "name"
    ROLE = "role"
    METRIC = "metric"


class TextDirection(str, Enum):
    LTR = "ltr"
    RTL = "rtl"
    AUTO = "auto"


@dataclass
class Keyframe:
    time: float
    value: Any
    easing: str = "ease_in_out"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Keyframe:
        return cls(
            time=float(data.get("time", 0.0)),
            value=data.get("value", 0.0),
            easing=str(data.get("easing", "ease_in_out"))
        )


@dataclass
class TextLayerData:
    raw_text: str = ""
    language: str = "en"
    direction: TextDirection = TextDirection.AUTO
    font_family: str = "Inter"
    font_asset_id: Optional[str] = None
    font_weight: str = "bold"
    font_size: int = 36
    line_height: float = 1.25
    letter_spacing: float = 0.0
    alignment: str = "left"
    vertical_alignment: str = "top"
    max_lines: int = 4
    fit_mode: str = "wrap"
    fill: str = "#ffffff"
    stroke: Optional[str] = None
    stroke_width: int = 0
    shadow: Optional[Dict[str, Any]] = None
    background: Optional[str] = None
    bg_radius: int = 0
    padding: Union[int, Tuple[int, int]] = 0
    safe_area: bool = True
    text_role: TextRole = TextRole.BODY

    def __init__(
        self,
        raw_text: str = "",
        text: Optional[str] = None,
        language: str = "en",
        direction: Union[str, TextDirection] = TextDirection.AUTO,
        font_family: str = "Inter",
        font_asset_id: Optional[str] = None,
        font_weight: str = "bold",
        font_size: int = 36,
        line_height: float = 1.25,
        letter_spacing: float = 0.0,
        alignment: str = "left",
        vertical_alignment: str = "top",
        max_lines: int = 4,
        fit_mode: str = "wrap",
        fill: str = "#ffffff",
        color: Optional[str] = None,
        stroke: Optional[str] = None,
        stroke_width: int = 0,
        shadow: Optional[Dict[str, Any]] = None,
        background: Optional[str] = None,
        bg_color: Optional[str] = None,
        bg_radius: int = 0,
        padding: Union[int, Tuple[int, int]] = 0,
        safe_area: bool = True,
        text_role: Union[str, TextRole] = TextRole.BODY,
    ):
        self.raw_text = text if text is not None else raw_text
        self.language = language
        self.direction = TextDirection(direction) if isinstance(direction, str) else direction
        self.font_family = font_family
        self.font_asset_id = font_asset_id
        self.font_weight = font_weight
        self.font_size = font_size
        self.line_height = line_height
        self.letter_spacing = letter_spacing
        self.alignment = alignment
        self.vertical_alignment = vertical_alignment
        self.max_lines = max_lines
        self.fit_mode = fit_mode
        self.fill = color if color is not None else fill
        self.stroke = stroke
        self.stroke_width = stroke_width
        self.shadow = shadow
        self.background = bg_color if bg_color is not None else background
        self.bg_radius = bg_radius
        self.padding = padding
        self.safe_area = safe_area
        self.text_role = TextRole(text_role) if isinstance(text_role, str) else text_role

    @property
    def text(self) -> str:
        return self.raw_text

    @text.setter
    def text(self, val: str):
        self.raw_text = val

    @property
    def color(self) -> str:
        return self.fill

    @color.setter
    def color(self, val: str):
        self.fill = val

    @property
    def bg_color(self) -> Optional[str]:
        return self.background

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["direction"] = self.direction.value
        d["text_role"] = self.text_role.value
        d["text"] = self.raw_text
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TextLayerData:
        return cls(**data)


@dataclass
class Layer:
    id: str = "layer"
    name: str = "Layer"
    type: LayerType = LayerType.SHAPE
    asset_id: Optional[str] = None
    x: float = 0.0
    y: float = 0.0
    width: float = 100.0
    height: float = 100.0
    anchor_x: float = 0.5
    anchor_y: float = 0.5
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    opacity: float = 1.0
    visible: bool = True
    locked: bool = False
    z_index: int = 0
    blend_mode: str = "normal"
    crop: Optional[Dict[str, float]] = None
    mask_id: Optional[str] = None
    effects: Dict[str, Any] = field(default_factory=dict)
    properties: Dict[str, Any] = field(default_factory=dict)
    start: float = 0.0
    end: float = 5.0
    keyframes: Dict[str, List[Keyframe]] = field(default_factory=dict)
    text_data: Optional[TextLayerData] = None

    def __init__(
        self,
        id: Optional[str] = None,
        layer_id: Optional[str] = None,
        name: str = "Layer",
        type: Union[str, LayerType] = LayerType.SHAPE,
        layer_type: Optional[Union[str, LayerType]] = None,
        asset_id: Optional[str] = None,
        x: float = 0.0,
        y: float = 0.0,
        width: float = 100.0,
        height: float = 100.0,
        anchor_x: float = 0.5,
        anchor_y: float = 0.5,
        rotation: float = 0.0,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        opacity: float = 1.0,
        visible: bool = True,
        locked: bool = False,
        z_index: int = 0,
        blend_mode: str = "normal",
        crop: Optional[Dict[str, float]] = None,
        mask_id: Optional[str] = None,
        effects: Optional[Dict[str, Any]] = None,
        properties: Optional[Dict[str, Any]] = None,
        transform: Optional[Dict[str, Any]] = None,
        start: float = 0.0,
        end: float = 5.0,
        keyframes: Optional[Dict[str, List[Any]]] = None,
        text_data: Optional[Union[Dict[str, Any], TextLayerData]] = None,
    ):
        self.id = layer_id or id or "layer"
        self.name = name
        t = layer_type or type
        self.type = LayerType(t) if isinstance(t, str) else t
        self.asset_id = asset_id
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.anchor_x = anchor_x
        self.anchor_y = anchor_y
        self.rotation = rotation
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.opacity = opacity
        self.visible = visible
        self.locked = locked
        self.z_index = z_index
        self.blend_mode = blend_mode
        self.crop = crop
        self.mask_id = mask_id
        self.effects = effects or {}
        self.properties = properties or {}
        self.start = start
        self.end = end

        if transform:
            self.x = float(transform.get("x", self.x))
            self.y = float(transform.get("y", self.y))
            self.scale_x = float(transform.get("scale_x", self.scale_x))
            self.scale_y = float(transform.get("scale_y", self.scale_y))
            self.rotation = float(transform.get("rotation", self.rotation))

        self.keyframes = {}
        if keyframes:
            for prop, kf_list in keyframes.items():
                parsed = []
                for k in kf_list:
                    if isinstance(k, Keyframe):
                        parsed.append(k)
                    elif isinstance(k, dict):
                        parsed.append(Keyframe.from_dict(k))
                self.keyframes[prop] = parsed

        if isinstance(text_data, dict):
            self.text_data = TextLayerData.from_dict(text_data)
        else:
            self.text_data = text_data

    @property
    def layer_id(self) -> str:
        return self.id

    @property
    def layer_type(self) -> LayerType:
        return self.type

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        d["layer_id"] = self.id
        if self.text_data:
            d["text_data"] = self.text_data.to_dict()
        d["keyframes"] = {
            prop: [k.to_dict() for k in kfs]
            for prop, kfs in self.keyframes.items()
        }
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Layer:
        return cls(**data)


@dataclass
class CanvasConfig:
    width: int = 1080
    height: int = 1080
    fps: int = 30
    duration: float = 5.0
    color_space: str = "sRGB"
    safe_margins: int = 40

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CanvasConfig:
        return cls(
            width=int(data.get("width", 1080)),
            height=int(data.get("height", 1080)),
            fps=int(data.get("fps", 30)),
            duration=float(data.get("duration", 5.0)),
            color_space=str(data.get("color_space", "sRGB")),
            safe_margins=int(data.get("safe_margins", 40)),
        )


@dataclass
class Scene:
    id: str = "scene"
    name: str = "Scene 1"
    duration: float = 5.0
    canvas: Optional[CanvasConfig] = None
    background: Dict[str, Any] = field(default_factory=lambda: {"type": "color", "value": "#0d1117"})
    layers: List[Layer] = field(default_factory=list)
    audio: List[Dict[str, Any]] = field(default_factory=list)
    transitions: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        id: Optional[str] = None,
        scene_id: Optional[str] = None,
        name: str = "Scene 1",
        duration: float = 5.0,
        canvas: Optional[Union[Dict[str, Any], CanvasConfig]] = None,
        background: Optional[Dict[str, Any]] = None,
        layers: Optional[List[Union[Dict[str, Any], Layer]]] = None,
        audio: Optional[List[Dict[str, Any]]] = None,
        transitions: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.id = scene_id or id or "scene"
        self.name = name
        self.duration = duration
        if isinstance(canvas, dict):
            self.canvas = CanvasConfig.from_dict(canvas)
        else:
            self.canvas = canvas or CanvasConfig()
        self.background = background or {"type": "color", "value": "#0d1117"}
        self.layers = []
        if layers:
            for l in layers:
                if isinstance(l, Layer):
                    self.layers.append(l)
                elif isinstance(l, dict):
                    self.layers.append(Layer.from_dict(l))
        self.audio = audio or []
        self.transitions = transitions or {}
        self.metadata = metadata or {}

    @property
    def scene_id(self) -> str:
        return self.id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "scene_id": self.id,
            "name": self.name,
            "duration": self.duration,
            "canvas": self.canvas.to_dict() if self.canvas else None,
            "background": self.background,
            "layers": [layer.to_dict() for layer in sorted(self.layers, key=lambda l: l.z_index)],
            "audio": self.audio,
            "transitions": self.transitions,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Scene:
        return cls(**data)


@dataclass
class GenerationManifest:
    generator_type: str = "deterministic-motion"
    model_id: str = "lexnis-engine"
    model_repo: str = ""
    model_revision: str = "main"
    model_license: str = "Apache-2.0"
    commercial_status: str = "COMMERCIAL_ALLOWED"
    seed: int = 42
    prompt: str = ""
    negative_prompt: str = ""
    prompt_compiler_version: str = "1.0"
    input_assets: List[str] = field(default_factory=list)
    reference_images: List[Dict[str, Any]] = field(default_factory=list)
    masks: List[str] = field(default_factory=list)
    control_images: List[Dict[str, Any]] = field(default_factory=list)
    adapter_settings: Dict[str, Any] = field(default_factory=dict)
    steps: int = 25
    guidance: float = 7.5
    scheduler: str = "EulerDiscrete"
    precision: str = "fp16"
    device: str = "cuda"
    native_width: int = 1024
    native_height: int = 1024
    native_fps: int = 0
    native_frames: int = 1
    generation_duration_seconds: float = 0.0
    post_processing: List[str] = field(default_factory=list)
    upscale_method: Optional[str] = None
    crop_method: Optional[str] = None
    export_resolution: str = "1080x1080"
    timestamp: str = ""

    @property
    def generation_type(self) -> str:
        return self.generator_type

    @generation_type.setter
    def generation_type(self, val: str):
        self.generator_type = val

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GenerationManifest:
        return cls(**data)


@dataclass
class CreativeProject:
    project_id: str
    name: str
    version: int = 1
    created: str = ""
    updated: str = ""
    canvas: CanvasConfig = field(default_factory=CanvasConfig)
    fps: int = 30
    duration: float = 5.0
    color_space: str = "sRGB"
    brand_kit: Dict[str, Any] = field(default_factory=dict)
    language: str = "en"
    scenes: List[Scene] = field(default_factory=list)
    assets: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    generation_manifests: List[GenerationManifest] = field(default_factory=list)
    export_history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "version": self.version,
            "created": self.created,
            "updated": self.updated,
            "canvas": self.canvas.to_dict(),
            "fps": self.fps,
            "duration": self.duration,
            "color_space": self.color_space,
            "brand_kit": self.brand_kit,
            "language": self.language,
            "scenes": [s.to_dict() for s in self.scenes],
            "assets": self.assets,
            "generation_manifests": [m.to_dict() for m in self.generation_manifests],
            "export_history": self.export_history,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CreativeProject:
        scenes = [Scene.from_dict(s) for s in data.get("scenes", [])]
        canvas_data = data.get("canvas", {})
        canvas = CanvasConfig.from_dict(canvas_data) if isinstance(canvas_data, dict) else canvas_data
        manifests = [GenerationManifest.from_dict(m) for m in data.get("generation_manifests", [])]
        return cls(
            project_id=str(data.get("project_id", "project")),
            name=str(data.get("name", "Untitled Project")),
            version=int(data.get("version", 1)),
            created=str(data.get("created", "")),
            updated=str(data.get("updated", "")),
            canvas=canvas or CanvasConfig(),
            fps=int(data.get("fps", 30)),
            duration=float(data.get("duration", 5.0)),
            color_space=str(data.get("color_space", "sRGB")),
            brand_kit=data.get("brand_kit", {}),
            language=str(data.get("language", "en")),
            scenes=scenes,
            assets=data.get("assets", {}),
            generation_manifests=manifests,
            export_history=data.get("export_history", []),
        )
