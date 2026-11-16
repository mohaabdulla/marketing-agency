"""Strict, versioned schemas and atomic execution engine for video edit operations."""
import time
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field, ConfigDict
from video_storage import uid


OperationType = Literal[
    'ADD_CLIP', 'REMOVE_CLIP', 'MOVE_CLIP', 'SPLIT_CLIP', 'TRIM_CLIP',
    'SET_DURATION', 'SET_SPEED', 'SET_VOLUME', 'SET_START', 'SET_OPACITY',
    'SET_POSITION', 'SET_SCALE', 'SET_ROTATION', 'SET_CROP', 'SET_COLOR',
    'SET_FADE', 'SET_TRANSITION',
    'ADD_TITLE', 'UPDATE_TITLE', 'REMOVE_TITLE',
    'ADD_OVERLAY', 'UPDATE_OVERLAY', 'REMOVE_OVERLAY',
    'ADD_AUDIO', 'UPDATE_AUDIO', 'REMOVE_AUDIO',
    'SET_AUDIO_ROLE', 'SET_DUCKING', 'SET_AUDIO_NORMALIZATION',
    'SET_CANVAS', 'SET_FPS', 'SET_SAFE_ZONE_PROFILE',
    'ADD_END_CARD', 'UPDATE_END_CARD', 'APPLY_BRAND_PRESET',
    'ADD_CAPTION_TRACK', 'UPDATE_CAPTION_SEGMENT', 'REMOVE_CAPTION_TRACK'
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class EditOperation(StrictModel):
    operation_id: str = Field(default_factory=uid)
    operation_type: OperationType
    target_id: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    reason: str = Field('', max_length=500)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    source: Literal['user', 'ai', 'rule_engine', 'system'] = 'user'
    created_at: float = Field(default_factory=time.time)


class EditPlan(StrictModel):
    plan_version: str = '1.0'
    intent: str = Field('General Edit', max_length=500)
    target_duration: Optional[float] = Field(None, ge=0.1, le=300.0)
    operations: List[EditOperation] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    unfulfilled_requests: List[str] = Field(default_factory=list)
    brand_checks: List[str] = Field(default_factory=list)
    requires_approval: bool = True


class OperationExecutor:
    """Validates and executes edit operations atomically on a Project model."""

    @staticmethod
    def validate_operation(project: Any, op: EditOperation) -> List[str]:
        errors: List[str] = []
        op_t = op.operation_type
        params = op.parameters
        clip_ids = {c.id for c in project.clips}

        # 1. Target ID checks
        if op_t in {
            'REMOVE_CLIP', 'MOVE_CLIP', 'SPLIT_CLIP', 'TRIM_CLIP',
            'SET_DURATION', 'SET_SPEED', 'SET_VOLUME', 'SET_START',
            'SET_OPACITY', 'SET_POSITION', 'SET_SCALE', 'SET_ROTATION',
            'SET_CROP', 'SET_COLOR', 'SET_FADE', 'SET_TRANSITION',
            'UPDATE_TITLE', 'REMOVE_TITLE', 'UPDATE_OVERLAY',
            'REMOVE_OVERLAY', 'UPDATE_AUDIO', 'REMOVE_AUDIO',
            'SET_AUDIO_ROLE'
        }:
            target = op.target_id or params.get('clip_id')
            if not target or target not in clip_ids:
                errors.append(f"Operation {op_t} references nonexistent clip '{target}'")

        # 2. Parameter sanity checks
        if op_t in {'SET_DURATION', 'TRIM_CLIP'}:
            dur = params.get('duration')
            if dur is not None and (dur < 0.1 or dur > 300):
                errors.append(f"Duration {dur}s must be between 0.1 and 300 seconds")

        if op_t == 'SET_SPEED':
            speed = params.get('speed')
            if speed is not None and (speed < 0.25 or speed > 4.0):
                errors.append(f"Speed {speed} must be between 0.25 and 4.0")

        if op_t == 'SET_VOLUME':
            vol = params.get('volume')
            if vol is not None and (vol < 0.0 or vol > 2.0):
                errors.append(f"Volume {vol} must be between 0.0 and 2.0")

        if op_t == 'SET_OPACITY':
            opac = params.get('opacity')
            if opac is not None and (opac < 0.0 or opac > 1.0):
                errors.append(f"Opacity {opac} must be between 0.0 and 1.0")

        if op_t == 'SET_CANVAS':
            w = params.get('width')
            h = params.get('height')
            if w is not None and (w < 128 or w > 1920 or w % 2 != 0):
                errors.append("Canvas width must be even and between 128 and 1920")
            if h is not None and (h < 128 or h > 1920 or h % 2 != 0):
                errors.append("Canvas height must be even and between 128 and 1920")

        if op_t in {'ADD_TITLE', 'UPDATE_TITLE'}:
            text = params.get('text', '')
            if op_t == 'ADD_TITLE' and not text.strip():
                errors.append("Title text cannot be empty")

        return errors

    @classmethod
    def apply_operation(cls, project: Any, op: EditOperation):
        from video_projects import Clip
        op_t = op.operation_type
        params = op.parameters
        target_id = op.target_id or params.get('clip_id')

        # Find target clip if applicable
        clip = next((c for c in project.clips if c.id == target_id), None)

        if op_t == 'ADD_CLIP':
            new_clip = Clip(
                asset_id=params.get('asset_id'),
                kind=params.get('kind', 'video'),
                start=params.get('start', 0.0),
                trim=params.get('trim', 0.0),
                duration=params.get('duration', 4.0),
                speed=params.get('speed', 1.0),
                volume=params.get('volume', 1.0),
                opacity=params.get('opacity', 1.0),
                x=params.get('x', 0.5),
                y=params.get('y', 0.5),
                scale=params.get('scale', 1.0),
                rotation=params.get('rotation', 0.0),
                fade_in=params.get('fade_in', 0.0),
                fade_out=params.get('fade_out', 0.0),
                transition=params.get('transition', 0.0),
                track=params.get('track', 1),
                audio_role=params.get('audio_role', 'dialogue'),
                text_role=params.get('text_role', 'title'),
                ai_operation_id=op.operation_id
            )
            insert_pos = params.get('position')
            if insert_pos is not None and 0 <= insert_pos <= len(project.clips):
                project.clips.insert(insert_pos, new_clip)
            else:
                project.clips.append(new_clip)

        elif op_t in {'REMOVE_CLIP', 'REMOVE_TITLE', 'REMOVE_OVERLAY', 'REMOVE_AUDIO'}:
            if clip:
                project.clips = [c for c in project.clips if c.id != target_id]

        elif op_t == 'MOVE_CLIP':
            if clip:
                old_idx = project.clips.index(clip)
                new_idx = max(0, min(params.get('to_index', old_idx), len(project.clips) - 1))
                project.clips.pop(old_idx)
                project.clips.insert(new_idx, clip)
                if 'start' in params:
                    clip.start = float(params['start'])

        elif op_t == 'SPLIT_CLIP':
            if clip and clip.kind == 'video':
                split_t = float(params.get('split_time', clip.duration / 2))
                if 0.1 <= split_t <= clip.duration - 0.1:
                    orig_dur = clip.duration
                    clip.duration = split_t
                    new_clip = Clip(
                        **{**clip.model_dump(), 'id': uid(), 'trim': clip.trim + split_t * clip.speed, 'duration': orig_dur - split_t}
                    )
                    idx = project.clips.index(clip)
                    project.clips.insert(idx + 1, new_clip)

        elif op_t == 'TRIM_CLIP':
            if clip:
                if 'trim' in params: clip.trim = max(0.0, float(params['trim']))
                if 'duration' in params: clip.duration = max(0.1, float(params['duration']))

        elif op_t == 'SET_DURATION':
            if clip and 'duration' in params:
                clip.duration = max(0.1, float(params['duration']))

        elif op_t == 'SET_SPEED':
            if clip and 'speed' in params:
                clip.speed = max(0.25, min(4.0, float(params['speed'])))

        elif op_t == 'SET_VOLUME':
            if clip and 'volume' in params:
                clip.volume = max(0.0, min(2.0, float(params['volume'])))

        elif op_t == 'SET_START':
            if clip and 'start' in params:
                clip.start = max(0.0, float(params['start']))

        elif op_t == 'SET_OPACITY':
            if clip and 'opacity' in params:
                clip.opacity = max(0.0, min(1.0, float(params['opacity'])))

        elif op_t == 'SET_POSITION':
            if clip:
                if 'x' in params: clip.x = max(0.0, min(1.0, float(params['x'])))
                if 'y' in params: clip.y = max(0.0, min(1.0, float(params['y'])))

        elif op_t == 'SET_SCALE':
            if clip and 'scale' in params:
                clip.scale = max(0.1, min(3.0, float(params['scale'])))

        elif op_t == 'SET_ROTATION':
            if clip and 'rotation' in params:
                clip.rotation = max(-180.0, min(180.0, float(params['rotation'])))

        elif op_t == 'SET_CROP':
            if clip and 'crop' in params:
                clip.crop = max(0.0, min(0.4, float(params['crop'])))

        elif op_t == 'SET_COLOR':
            if clip:
                if 'brightness' in params: clip.brightness = max(-0.5, min(0.5, float(params['brightness'])))
                if 'contrast' in params: clip.contrast = max(0.1, min(2.0, float(params['contrast'])))
                if 'saturation' in params: clip.saturation = max(0.0, min(3.0, float(params['saturation'])))

        elif op_t == 'SET_FADE':
            if clip:
                if 'fade_in' in params: clip.fade_in = max(0.0, min(5.0, float(params['fade_in'])))
                if 'fade_out' in params: clip.fade_out = max(0.0, min(5.0, float(params['fade_out'])))

        elif op_t == 'SET_TRANSITION':
            if clip and 'transition' in params:
                clip.transition = max(0.0, min(2.0, float(params['transition'])))

        elif op_t == 'ADD_TITLE':
            new_title = Clip(
                kind='title',
                text=params.get('text', 'Title'),
                start=params.get('start', 0.0),
                duration=params.get('duration', 3.0),
                color=params.get('color', '#ffffff'),
                font=params.get('font', 'sans'),
                font_family=params.get('font_family', ''),
                font_size=params.get('font_size', 48),
                x=params.get('x', 0.5),
                y=params.get('y', 0.5),
                scale=params.get('scale', 1.0),
                fade_in=params.get('fade_in', 0.3),
                fade_out=params.get('fade_out', 0.3),
                track=params.get('track', 2),
                text_role=params.get('text_role', 'title'),
                ai_operation_id=op.operation_id
            )
            project.clips.append(new_title)

        elif op_t == 'UPDATE_TITLE':
            if clip and clip.kind == 'title':
                if 'text' in params: clip.text = str(params['text'])
                if 'color' in params: clip.color = str(params['color'])
                if 'font' in params: clip.font = str(params['font'])
                if 'font_size' in params: clip.font_size = int(params['font_size'])
                if 'font_family' in params: clip.font_family = str(params['font_family'])
                for key in ('x','y','start','duration'):
                    if key in params:
                        setattr(clip,key,float(params[key]))
                if 'text_role' in params: clip.text_role = str(params['text_role'])

        elif op_t == 'ADD_OVERLAY':
            new_ov = Clip(
                asset_id=params.get('asset_id'),
                kind='overlay',
                start=params.get('start', 0.0),
                duration=params.get('duration', 5.0),
                x=params.get('x', 0.85),
                y=params.get('y', 0.15),
                scale=params.get('scale', 0.4),
                opacity=params.get('opacity', 1.0),
                fade_in=params.get('fade_in', 0.0),
                fade_out=params.get('fade_out', 0.0),
                track=params.get('track', 3),
                ai_operation_id=op.operation_id
            )
            project.clips.append(new_ov)

        elif op_t == 'UPDATE_OVERLAY':
            if clip and clip.kind == 'overlay':
                if 'x' in params: clip.x = float(params['x'])
                if 'y' in params: clip.y = float(params['y'])
                if 'scale' in params: clip.scale = float(params['scale'])
                if 'opacity' in params: clip.opacity = float(params['opacity'])

        elif op_t == 'ADD_AUDIO':
            new_au = Clip(
                asset_id=params.get('asset_id'),
                kind='audio',
                start=params.get('start', 0.0),
                trim=params.get('trim', 0.0),
                duration=params.get('duration', 5.0),
                volume=params.get('volume', 1.0),
                fade_in=params.get('fade_in', 0.2),
                fade_out=params.get('fade_out', 0.2),
                audio_role=params.get('audio_role', 'music'),
                track=params.get('track', 4),
                ai_operation_id=op.operation_id
            )
            project.clips.append(new_au)

        elif op_t == 'UPDATE_AUDIO':
            if clip and clip.kind == 'audio':
                if 'volume' in params: clip.volume = float(params['volume'])
                if 'audio_role' in params: clip.audio_role = str(params['audio_role'])

        elif op_t == 'SET_AUDIO_ROLE':
            if clip:
                clip.audio_role = str(params.get('audio_role', clip.audio_role))

        elif op_t == 'SET_CANVAS':
            if 'width' in params: project.canvas.width = int(params['width'])
            if 'height' in params: project.canvas.height = int(params['height'])
            if 'fps' in params: project.canvas.fps = int(params['fps'])
            if 'fps_mode' in params: project.canvas.fps_mode = str(params['fps_mode'])

        elif op_t == 'SET_SAFE_ZONE_PROFILE':
            project.safe_zone_profile = str(params.get('profile', 'generic'))

        elif op_t == 'ADD_END_CARD':
            cta_text = params.get('cta_text', 'Learn More')
            card_dur = float(params.get('duration', 3.0))
            # Primary timeline duration
            primary_clips = [c for c in project.clips if c.kind == 'video']
            total_dur = sum(c.duration for c in primary_clips) if primary_clips else 0.0
            start_t = max(0.0, total_dur - card_dur)

            # Add end card CTA title
            cta_title = Clip(
                kind='title',
                text=cta_text,
                start=start_t,
                duration=card_dur,
                color=params.get('color', '#00FFA3'),
                font=params.get('font', 'sans'),
                font_size=params.get('font_size', 52),
                x=0.5,
                y=0.75,
                fade_in=0.4,
                fade_out=0.0,
                track=2,
                text_role='cta',
                ai_operation_id=op.operation_id
            )
            project.clips.append(cta_title)

            # Add logo overlay if provided
            if params.get('logo_asset_id'):
                logo_ov = Clip(
                    asset_id=params['logo_asset_id'],
                    kind='overlay',
                    start=start_t,
                    duration=card_dur,
                    x=0.5,
                    y=0.35,
                    scale=params.get('scale', 0.6),
                    fade_in=0.4,
                    fade_out=0.0,
                    track=3,
                    ai_operation_id=op.operation_id
                )
                project.clips.append(logo_ov)

        elif op_t == 'APPLY_BRAND_PRESET':
            project.brand_id = params.get('brand_id', project.brand_id)
            color = params.get('primary_color')
            font = params.get('font')
            if color or font:
                for c in project.clips:
                    if c.kind == 'title':
                        if color: c.color = color
                        if font: c.font = font

        elif op_t == 'ADD_CAPTION_TRACK':
            track_data = params.get('track', {})
            if track_data:
                project.caption_tracks.append(track_data)

        elif op_t == 'REMOVE_CAPTION_TRACK':
            track_id = params.get('track_id')
            project.caption_tracks = [t for t in project.caption_tracks if t.get('id') != track_id]

    @classmethod
    def apply_plan(cls, project: Any, plan: EditPlan) -> Tuple[Any, List[str]]:
        """Validate all operations in plan, then execute atomically. Reverts on any error."""
        import copy
        all_errors = []
        for op in plan.operations:
            errs = cls.validate_operation(project, op)
            all_errors.extend(errs)

        if all_errors:
            raise ValueError(f"Plan validation failed: {'; '.join(all_errors)}")

        # Clone project to execute atomically
        cloned = copy.deepcopy(project)
        for op in plan.operations:
            cls.apply_operation(cloned, op)

        from video_projects import Project
        return Project.model_validate(cloned.model_dump()), plan.warnings

