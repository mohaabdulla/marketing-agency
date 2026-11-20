"""Producer workflow inputs. Server-owned candidates, approvals and governance are never editable."""
from typing import Annotated,Literal
from pydantic import Field,StringConstraints
from video.projects import Strict
from video.director import VideoBriefRequest

Id=Annotated[str,Field(pattern=r'^[a-f0-9]{32}$')]
Method=Literal['auto','motion-graphics','real-footage','image-animation','text-to-video','image-to-video']
Pass=Literal['concept','continuity','final']
Reviewer=Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=100)]


class ProductionCreate(Strict):
    name: str = Field('New video production',min_length=1,max_length=100)
    brief: VideoBriefRequest
    script_text: str = Field('',max_length=6000)
    continuity_notes: str = Field('',max_length=1500)
    use_local_ai: bool = True


class ShotInput(Strict):
    overlay_text: str = Field(min_length=1,max_length=180)
    voiceover: str = Field(min_length=1,max_length=450)
    visual_prompt: str = Field(min_length=1,max_length=1000)
    duration: float = Field(4,ge=1,le=30)
    method: Method = 'auto'
    model: str = Field('cogvideox-2b',max_length=100)
    seed: int = Field(42,ge=0,le=2**31-1)
    reference_asset_id: Id | None = None
    source_asset_id: Id | None = None
    accuracy_critical: bool = False
    composite_critical_text: Literal[True] = True
    subject: str = Field('',max_length=250)
    framing: Literal['wide','medium','close-up','detail'] = 'medium'
    camera_angle: str = Field('eye-level',max_length=120)
    camera_motion: str = Field('gentle push-in',max_length=120)
    action: str = Field('',max_length=400)
    location: str = Field('',max_length=250)
    wardrobe: str = Field('',max_length=250)
    props: str = Field('',max_length=250)
    continuity_notes: str = Field('',max_length=600)
    screen_direction: Literal['neutral','left-to-right','right-to-left','toward-camera'] = 'neutral'
    motion: Literal['zoom-in','zoom-out','pan','still'] = 'zoom-in'
    background_style: Literal['brand-gradient','minimal','geometric'] = 'brand-gradient'
    transition: Literal['fade','cut'] = 'fade'
    transition_seconds: float = Field(.3,ge=0,le=1)


class ShotUpdate(Strict):
    expected_version: int = Field(ge=1)
    shot: ShotInput


class Versioned(Strict):
    expected_version: int = Field(ge=1)


class CandidateRequest(Versioned):
    pass_name: Pass = 'concept'


class GateRequest(Versioned):
    gate: Pass
    candidate_id: Id
    reviewer: Reviewer
    note: str = Field('',max_length=1200)
    approved: bool = True
    issue: Literal['intent','continuity','readability','motion','brand','other'] | None = None
    intent_checked: bool = False
    continuity_checked: bool = False
    readability_checked: bool = False


class ScriptApproval(Versioned):
    reviewer: Reviewer
    note: str = Field('',max_length=1200)


class ProductionRender(Versioned):
    narrator_voice: str | None = Field(None,pattern=r'^[a-z0-9-]{1,80}$')
    music_asset_id: Id | None = None
    voiceover_asset_id: Id | None = None
    burn_subtitles: bool = True
    music_volume: float = Field(.2,ge=0,le=1)
    variants: list[Literal['9:16','1:1','16:9']] = Field(default_factory=list,max_length=3)


class ReleaseRequest(Versioned):
    reviewer: Reviewer
    note: str = Field('',max_length=1500)
    story_checked: bool
    continuity_checked: bool
    text_checked: bool
    audio_checked: bool
    rights_checked: bool

