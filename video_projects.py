"""Strict, non-destructive timeline schema, schema versioning, and atomic project persistence."""
import time
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, model_validator
from video_storage import DATA, atomic, read, uid


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class FrameAnchor(Strict):
    time: float = Field(ge=0,le=300)
    x: float = Field(ge=0,le=1)
    y: float = Field(ge=0,le=1)


class Clip(Strict):
    reframe_keyframes: list[FrameAnchor] = Field(default_factory=list,max_length=24)
    zoom_ease: float = Field(0,ge=0,le=1)
    layout_box: list[float] | None = Field(None,min_length=4,max_length=4)
    graphic_style: dict | None = None
    logo_backplate: bool = False
    # How a still fills the canvas: 'cover' crops it; 'blur-fill' shows it whole over a blurred copy.
    fit: Literal['cover', 'blur-fill'] = 'cover'
    id: str = Field(default_factory=uid, pattern=r'^[a-f0-9]{32}$')
    asset_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
    kind: Literal['video', 'overlay', 'title', 'audio'] = 'video'
    start: float = Field(0, ge=0, le=300)
    trim: float = Field(0, ge=0, le=3600)
    duration: float = Field(4, ge=.1, le=300)
    speed: float = Field(1, ge=.25, le=4)
    volume: float = Field(1, ge=0, le=2)
    opacity: float = Field(1, ge=0, le=1)
    x: float = Field(.5, ge=0, le=1)
    y: float = Field(.5, ge=0, le=1)
    scale: float = Field(1, ge=.1, le=3)
    rotation: float = Field(0, ge=-180, le=180)
    zoom: float = Field(1, ge=1, le=1.5)
    zoom_start: float = Field(1, ge=1, le=1.5)
    pan: float = Field(0, ge=-1, le=1)
    crop: float = Field(0, ge=0, le=.4)
    brightness: float = Field(0, ge=-.5, le=.5)
    contrast: float = Field(1, ge=.1, le=2)
    saturation: float = Field(1, ge=0, le=3)
    fade_in: float = Field(0, ge=0, le=5)
    fade_out: float = Field(0, ge=0, le=5)
    motion: Literal['none','fade','slide-up','masked-reveal','soft-scale','word-emphasis'] = 'none'
    transition: float = Field(0, ge=0, le=2)
    # Lighting correction actually rendered by video_grade.filters (neutral values change nothing).
    exposure: float = Field(0, ge=-1, le=1)
    gamma: float = Field(1, ge=.6, le=1.6)
    shadows: float = Field(0, ge=0, le=1)
    highlights: float = Field(0, ge=0, le=1)
    temperature: float = Field(0, ge=-1, le=1)
    vignette: float = Field(0, ge=0, le=1)
    sharpen: float = Field(0, ge=0, le=1)
    denoise: float = Field(0, ge=0, le=1)
    # Where a punch-in is anchored (fraction of the frame); 0.5/0.5 is the centre.
    zoom_x: float = Field(.5, ge=0, le=1)
    zoom_y: float = Field(.5, ge=0, le=1)
    text: str = Field('', max_length=500)
    color: str = Field('#ffffff', pattern=r'^#[0-9a-fA-F]{6}$')
    font: Literal['sans', 'arabic', 'serif'] = 'sans'
    font_family: str = Field('', max_length=80, pattern=r'^[A-Za-z0-9 -]*$')
    font_size: int = Field(48, ge=16, le=160)

    # Professional multi-track & semantic properties
    track: int = Field(1, ge=1, le=10)
    audio_role: Literal['dialogue', 'voiceover', 'music', 'sfx', 'ambient', 'master'] = 'dialogue'
    ducking_priority: int = Field(0, ge=0, le=5)
    z_index: int = Field(0, ge=-100, le=100)
    locked: bool = False
    muted: bool = False
    blend_mode: Literal['normal', 'multiply', 'screen', 'overlay'] = 'normal'
    text_role: Literal['hook', 'headline', 'subheadline', 'lower_third', 'speaker_name', 'speaker_role', 'metric', 'disclosure', 'cta', 'end_card', 'caption', 'title'] = 'title'
    caption_style_id: str | None = None
    ai_operation_id: str | None = None

    @model_validator(mode='after')
    def source(self):
        if self.kind == 'title':
            if not self.text.strip():
                raise ValueError('Title text is required')
        elif not self.asset_id:
            raise ValueError('A server asset ID is required')
        if self.graphic_style:
            if self.layout_box is None:raise ValueError('Designed graphics require a measured layout rectangle')
            from video_captions import CaptionStyle
            style=dict(self.graphic_style)
            for key in ('canvas_width','canvas_height'):
                value=style.get(key)
                if not isinstance(value,int) or not 128<=value<=1920:raise ValueError('Graphic canvas dimensions must be between 128 and 1920')
            CaptionStyle.model_validate({k:v for k,v in style.items() if k not in {'canvas_width','canvas_height'}})
        times=[p.time for p in self.reframe_keyframes]
        if times!=sorted(set(times)):raise ValueError('Framing keyframe times must be unique and increasing')
        if times and times[-1]>self.duration+.01:raise ValueError('Framing keyframes extend beyond the clip')
        return self


class Canvas(Strict):
    width: int = Field(1280, ge=128, le=1920, multiple_of=2)
    height: int = Field(720, ge=128, le=1920, multiple_of=2)
    fps: Literal[24, 30] = 24
    fps_mode: Literal['fixed', 'original'] = 'fixed'


class CreativeContext(Strict):
    objective: str = Field('',max_length=1000)
    audience: str = Field('',max_length=500)
    key_message: str = Field('',max_length=1000)
    style: str = Field('',max_length=500)
    platform: str = Field('',max_length=100)
    cta: str = Field('',max_length=500)
    language: Literal['en','ar','ar-BH'] = 'en'


class EditingBrief(Strict):
    purpose: Literal['','team_welcome','product_launch','event_announcement','milestone_achievement',
                     'thought_leadership','case_study','hiring','brand_awareness'] = ''
    person_name: str = Field('',max_length=150)
    person_position: str = Field('',max_length=200)
    logo_asset_id: str | None = Field(None,pattern=r'^[a-f0-9]{32}$')
    instruction: str = Field('',max_length=1000)


class BackgroundTreatment(Strict):
    """Subject-mask background treatment. Needs the optional matting model (video_segmentation)."""
    mode: Literal['blur-dim', 'replace'] = 'blur-dim'
    blur: float = Field(.12, ge=0, le=1)
    dim: float = Field(.02, ge=0, le=.5)
    desaturate: float = Field(0, ge=0, le=1)
    replacement_asset_id: str | None = Field(None, pattern=r'^[a-f0-9]{32}$')
    mask_fps: Literal[6, 12, 24] = 12

    @model_validator(mode='after')
    def replacement(self):
        if self.mode == 'replace' and not self.replacement_asset_id:
            raise ValueError('Choose an approved background image to replace the background')
        return self


class RegionalGrade(Strict):
    exposure: float = Field(0,ge=-1,le=1)
    gamma: float = Field(1,ge=.6,le=1.6)
    shadows: float = Field(0,ge=0,le=1)
    highlights: float = Field(0,ge=0,le=1)
    temperature: float = Field(0,ge=-1,le=1)
    saturation: float = Field(1,ge=.5,le=1.5)
    contrast: float = Field(1,ge=.75,le=1.3)


class ColorPipeline(Strict):
    mask_fps: Literal[6,12,24] = 12
    input_space: Literal['rec709-sdr'] = 'rec709-sdr'
    output_space: Literal['rec709-sdr'] = 'rec709-sdr'
    look: Literal['organic','polished-organic','corporate-clean','warm-lifestyle','high-energy','cinematic-brand'] = 'polished-organic'
    subject: RegionalGrade = Field(default_factory=RegionalGrade)
    background: RegionalGrade = Field(default_factory=RegionalGrade)
    source_asset_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    regional: bool = False


class Project(Strict):
    motion_preset: Literal['fade','slide-up','masked-reveal','soft-scale'] = 'fade'
    dialogue_noise_reduction: bool = False
    dialogue_hum_hz: Literal[0,50,60] = 0
    dialogue_deess: bool = False
    color_pipeline: ColorPipeline | None = None
    motion_intensity: Literal['minimal', 'balanced', 'expressive'] = 'minimal'
    background: BackgroundTreatment | None = None
    dialogue_polish: bool = False
    normalize_audio: bool = False
    export_quality: Literal['standard','high'] = 'standard'
    # Named delivery preset (video_presets.PRESETS). None keeps the web defaults.
    delivery_preset: Literal['source-master','web-youtube','vertical-social','square-social','portrait-feed','broadcast-ebu'] | None = None
    editing_brief: EditingBrief = Field(default_factory=EditingBrief)
    creative_context: CreativeContext = Field(default_factory=CreativeContext)
    schema_version: int = Field(2, ge=1)
    name: str = Field('Untitled video', min_length=1, max_length=120)
    canvas: Canvas = Field(default_factory=Canvas)
    brand_id: str | None = Field(None, max_length=100)
    guideline_id: str | None = Field(None, pattern=r'^[a-f0-9]{32}$')
    guideline_version: int | None = Field(None, ge=1)
    brand_rules: dict | None = None
    clips: list[Clip] = Field(default_factory=list, max_length=60)

    # Master/variant & compliance tracking
    master_project_id: str | None = Field(default=None, max_length=100)
    variant_target: Literal['original', '9:16', '1:1', '4:5', '16:9'] | None = None
    safe_zone_profile: Literal['generic', 'vertical-social', 'square-social', 'landscape-social', 'custom'] = 'generic'
    status: Literal['draft', 'review', 'approved', 'rejected'] = 'draft'
    caption_tracks: list[Dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_clips(self):
        if len({c.id for c in self.clips}) != len(self.clips):
            raise ValueError('Clip IDs must be unique within a project')
        return self


def migrate_project(data: Dict[str, Any]) -> Dict[str, Any]:
    """Non-destructive migration of legacy (version 1 or unversioned) project dictionaries."""
    data = dict(data)
    if 'schema_version' not in data or data['schema_version'] < 2:
        data['schema_version'] = 2
        data.setdefault('master_project_id', None)
        data.setdefault('variant_target', None)
        data.setdefault('safe_zone_profile', 'generic')
        data.setdefault('status', 'draft')
        data.setdefault('caption_tracks', [])

        migrated_clips = []
        for c in data.get('clips', []):
            cd = dict(c)
            cd.setdefault('track', 1)
            cd.setdefault('audio_role', 'dialogue' if cd.get('kind') != 'audio' else 'music')
            cd.setdefault('ducking_priority', 0)
            cd.setdefault('z_index', 0)
            cd.setdefault('locked', False)
            cd.setdefault('muted', False)
            cd.setdefault('blend_mode', 'normal')
            cd.setdefault('text_role', 'title')
            cd.setdefault('caption_style_id', None)
            cd.setdefault('ai_operation_id', None)
            migrated_clips.append(cd)
        data['clips'] = migrated_clips
    return data


def save(
    project: Project,
    project_id: Optional[str] = None,
    actor: str = 'user',
    instruction: str = '',
    reason: str = '',
    operation_ids: Optional[List[str]] = None,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Atomic project save that automatically commits a persistent revision snapshot."""
    now = time.time()
    old = read('projects', project_id) if project_id else {}
    key = project_id or uid()
    value = dict(project.model_dump(), id=key, created=old.get('created', now), updated=now)
    atomic(DATA / 'projects' / (key + '.json'), value)

    # Persist immutable revision snapshot
    try:
        from video_revisions import record_revision
        record_revision(
            project_id=key,
            project_state=value,
            actor=actor,  # type: ignore
            instruction=instruction,
            reason=reason,
            operation_ids=operation_ids,
            label=label,
        )
    except Exception:
        pass  # Never fail project save if revision logging hits a transient issue

    return value
