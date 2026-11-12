"""Strict, non-destructive timeline schema and atomic project persistence."""
import time
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator
from video_storage import DATA, atomic, read, uid


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Clip(Strict):
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
    transition: float = Field(0, ge=0, le=2)
    text: str = Field('', max_length=500)
    color: str = Field('#ffffff', pattern=r'^#[0-9a-fA-F]{6}$')
    font: Literal['sans', 'arabic', 'serif'] = 'sans'
    font_size: int = Field(48, ge=16, le=160)

    @model_validator(mode='after')
    def source(self):
        if self.kind == 'title':
            if not self.text.strip():
                raise ValueError('Title text is required')
        elif not self.asset_id:
            raise ValueError('A server asset ID is required')
        return self


class Canvas(Strict):
    width: int = Field(1280, ge=128, le=1920, multiple_of=2)
    height: int = Field(720, ge=128, le=1920, multiple_of=2)
    fps: Literal[24, 30] = 24
    fps_mode: Literal['fixed', 'original'] = 'fixed'


class Project(Strict):
    name: str = Field('Untitled video', min_length=1, max_length=120)
    canvas: Canvas = Field(default_factory=Canvas)
    brand_id: str | None = Field(None, max_length=100)
    clips: list[Clip] = Field(default_factory=list, max_length=60)

    @model_validator(mode='after')
    def unique_clips(self):
        if len({c.id for c in self.clips}) != len(self.clips):
            raise ValueError('Clip IDs must be unique within a project')
        return self


def save(project, project_id=None):
    now = time.time()
    old = read('projects', project_id) if project_id else {}
    key = project_id or uid()
    value = dict(project.model_dump(), id=key, created=old.get('created', now), updated=now)
    atomic(DATA / 'projects' / (key + '.json'), value)
    return value
