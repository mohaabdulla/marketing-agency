"""Assisted editing on a project: quick edit, captions, AI and rule-based edit plans, compliance repair,
platform variants, voiceover, music, pacing, and what the editor can do on this machine."""
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import Field

from video import brand_editing as branded
from video.ai_editor import VideoAIEditor
from video.analysis import get_cached_analysis
from video.assets import ingest
from video.brand_context import compile_video_edit_context
from video.captions import DEFAULT_CAPTION_STYLES, parse_srt
from video.compliance import VideoComplianceEngine
from video.editor import primary_layout
from video.jobs import jobs
from video.operations import OperationExecutor
from video.projects import Clip, Strict, save
from video.quick_edit import QuickEdit, run as run_quick_edit
from video.routes.common import as_project, guard, load_project, save_plan, stored_project
from video.storage import DATA, read, uid
from video.variants import create_platform_variant

router = APIRouter()


class AIEditRequest(Strict):
    instruction: str = Field(..., min_length=1, max_length=1000)
    brand_profile: Optional[Dict[str, Any]] = None
    brief_data: Optional[Dict[str, Any]] = None


class AIFirstCutRequest(Strict):
    media_asset_ids: List[str] = Field(..., min_length=1)
    brand_profile: Optional[Dict[str, Any]] = None
    brief_data: Optional[Dict[str, Any]] = None
    target_duration: float = Field(15.0, ge=3.0, le=300.0)
    language: str = 'en'
    user_instruction: str = ''


class AutoPolishRequest(Strict):
    brand_profile: Optional[Dict[str, Any]] = None
    brief_data: Optional[Dict[str, Any]] = None


class VariantRequest(Strict):
    target_aspect: Literal['9:16', '1:1', '4:5', '16:9'] = '9:16'
    focal_x: float = Field(0.5, ge=0.0, le=1.0)
    focal_y: float = Field(0.5, ge=0.0, le=1.0)


class VoiceoverRequest(Strict):
    text: str = Field(min_length=1, max_length=1000)
    voice_id: str = Field('af_sarah', max_length=50)
    speed: float = Field(1.0, ge=0.5, le=2.0)
    start: float = Field(0.0, ge=0.0, le=300.0)
    ducking_priority: int = Field(1, ge=0, le=5)
    add_to_timeline: bool = True
    create_captions: bool = True


class BackgroundMusicRequest(Strict):
    prompt: str = Field('Corporate ambient inspiring track', max_length=300)
    genre: str = Field('Corporate Ambient', max_length=100)
    duration_seconds: Optional[float] = Field(None, ge=1.0, le=300.0)
    volume: float = Field(0.25, ge=0.0, le=2.0)
    ducking_priority: int = Field(1, ge=0, le=5)


class OptimizePacingRequest(Strict):
    pacing_mode: Literal['rollercoaster', 'even', 'dynamic'] = 'rollercoaster'
    default_transition: float = Field(0.5, ge=0.1, le=2.0)
    transition_type: Literal['fade', 'dissolve', 'fadeblack', 'fadewhite', 'wipeleft', 'wiperight', 'slideup', 'slidedown', 'smooth'] = 'dissolve'


# ------------------------------------------------------------------ quick edit and captions

@router.post('/projects/{project_id}/quick-edit', status_code=202)
def quick_edit(project_id: str, body: QuickEdit):
    original = guard(branded.model, guard(read, 'projects', project_id))
    asset = guard(read, 'assets', body.asset_id)
    if asset['kind'] != 'video':
        raise HTTPException(400, 'Choose a video source; upload logos separately')
    if not 0 < asset['duration'] <= 300:
        raise HTTPException(400, 'Quick edit supports videos up to five minutes')
    for key, kinds in [('reference_asset_id', {'video'}), ('background_asset_id', {'image', 'video'}), ('parent_asset_id', {'video'})]:
        value = getattr(body, key)
        if value:
            item = guard(read, 'assets', value)
            if item['kind'] not in kinds:
                raise HTTPException(400, 'The selected reference, background or parent asset has an incompatible media type.')
            if key == 'parent_asset_id' and item.get('source_asset_id') != body.asset_id:
                raise HTTPException(400, 'The previous render must belong to this source video.')
    original.master_project_id = project_id
    return guard(jobs.submit, 'quick-edit', lambda job: run_quick_edit(original, body, job))


@router.get('/captions/styles')
def caption_styles():
    return {k: v.model_dump(mode='json') for k, v in DEFAULT_CAPTION_STYLES.items()}


@router.post('/projects/{project_id}/captions/import')
async def import_captions(project_id: str, file: UploadFile = File(...)):
    try:
        raw = await file.read(256 * 1024 + 1)
        if not (file.filename or '').lower().endswith('.srt') or len(raw) > 256 * 1024:
            raise HTTPException(400, 'Import a UTF-8 SRT subtitle file up to 256 KB')
        try:
            text = raw.decode('utf-8-sig')
            if any(ord(c) < 32 and c not in '\r\n\t' for c in text):
                raise ValueError('Invalid control characters')
            blocks = [b for b in text.replace('\r\n', '\n').strip().split('\n\n') if b.strip()]
            for block in blocks:
                lines = block.strip().splitlines()
                if len(lines) < 3 or not re.fullmatch(r'\d{1,8}', lines[0]) or len(lines[1]) > 60 or len('\n'.join(lines[2:])) > 500:
                    raise ValueError('Invalid SRT block')
            segments = parse_srt(text)
            if not segments or len(segments) != text.count('-->'):
                raise ValueError('Malformed caption timing')
        except Exception:
            raise HTTPException(400, 'Invalid UTF-8 SRT captions')
        project = branded.model(guard(read, 'projects', project_id))
        total = primary_layout(project)[1]
        remaining = [c for c in project.clips if c.caption_style_id != 'imported-srt']
        if len(remaining) + len(segments) > 60:
            raise HTTPException(400, 'Caption import exceeds the 60-clip rendering budget; combine cues or shorten the edit')
        previous = 0
        for cue in segments:
            if cue.start < previous or cue.end <= cue.start or cue.end > total + .01 or len(cue.text) > 500:
                raise HTTPException(400, 'Captions must be ordered, non-overlapping, within the timeline, and at most 500 characters each')
            previous = cue.end
            remaining.append(Clip(kind='title', text=cue.text, start=cue.start, duration=cue.end - cue.start,
                                  text_role='caption', caption_style_id='imported-srt',
                                  font='arabic' if re.search(r'[؀-ۿ]', cue.text) else 'sans',
                                  font_size=40, color='#ffffff', x=.5, y=.72))
        original = DATA / 'caption-originals'
        original.mkdir(exist_ok=True)
        key = uid()
        (original / (key + '.srt')).write_bytes(raw)
        project.clips = remaining
        project.caption_tracks = [dict(id=key, source='imported', sha256=hashlib.sha256(raw).hexdigest(), burn_in=True,
                                       segments=[s.model_dump() for s in segments])]
        return guard(save, project, project_id, 'user', 'Imported reviewed SRT captions')
    finally:
        await file.close()


# ------------------------------------------------------------------ edit plans

@router.post('/projects/{project_id}/ai/first-cut')
def ai_first_cut(project_id: str, body: AIFirstCutRequest):
    project = load_project(project_id)
    media_assets = [guard(read, 'assets', aid) for aid in body.media_asset_ids]
    analyses = [get_cached_analysis(aid).model_dump(mode='json') for aid in body.media_asset_ids if get_cached_analysis(aid)]
    context = compile_video_edit_context(project=project, user_instruction=body.user_instruction,
                                         brand_profile=body.brand_profile, brief_data=body.brief_data,
                                         media_analyses=analyses, target_duration=body.target_duration,
                                         language=body.language)
    plan = VideoAIEditor.first_cut(project, context, media_assets)
    updated, warnings = OperationExecutor.apply_plan(project, plan)
    saved = save_plan(updated, project_id, plan, 'rule_engine', f"Deterministic First Cut: {plan.intent}", 'Deterministic First Cut')
    return {'project': saved, 'plan': plan.model_dump(mode='json'), 'warnings': warnings, 'engine': 'rule_engine', 'ai_used': False}


@router.post('/projects/{project_id}/ai/edit')
def ai_edit_timeline(project_id: str, body: AIEditRequest):
    project = load_project(project_id)
    if not branded.ai_status()['available']:
        raise HTTPException(409, branded.ai_status()['reason'])
    plan = guard(branded.local_plan, project, body.instruction, branded.effective_rules(project, body.brand_profile))
    updated = guard(branded.checked, project, plan)
    result = branded.compliance(updated)
    if not result['passed']:
        raise HTTPException(409, dict(message='Brand checks need review; use the preview/apply workflow', findings=result['findings']))
    saved = save_plan(updated, project_id, plan, 'ai', body.instruction, 'AI Edit')
    return {'project': saved, 'plan': plan.model_dump(mode='json'), 'warnings': plan.warnings}


@router.post('/projects/{project_id}/auto-polish')
def auto_polish_endpoint(project_id: str, body: AutoPolishRequest):
    project = load_project(project_id)
    plan = guard(branded.polish, project, 'Apply the reviewed brand styling.', branded.effective_rules(project, body.brand_profile))
    updated = guard(branded.checked, project, plan)
    saved = save_plan(updated, project_id, plan, 'rule_engine', 'Deterministic Auto Polish', 'Auto Polish')
    return {'project': saved, 'plan': plan.model_dump(mode='json'), 'warnings': plan.warnings}


@router.post('/projects/{project_id}/optimize-pacing')
def optimize_pacing_endpoint(project_id: str, body: OptimizePacingRequest):
    project = load_project(project_id)
    plan = guard(branded.optimize_pacing_and_transitions, project=project, pacing_mode=body.pacing_mode,
                 default_transition=body.default_transition, transition_type=body.transition_type)
    updated, warnings = OperationExecutor.apply_plan(project, plan)
    saved = save_plan(updated, project_id, plan, 'rule_engine',
                      f"Optimized pacing ({body.pacing_mode}) and transitions ({body.transition_type})", 'Pacing & Transitions')
    return {'project': saved, 'plan': plan.model_dump(mode='json'), 'warnings': warnings}


# ------------------------------------------------------------------ compliance and variants

@router.get('/projects/{project_id}/compliance')
def get_compliance_report(project_id: str):
    return VideoComplianceEngine.audit_project(load_project(project_id)).model_dump(mode='json')


@router.post('/projects/{project_id}/compliance/fix')
def fix_compliance_endpoint(project_id: str):
    stored = stored_project(project_id)
    project = as_project(stored)
    report = VideoComplianceEngine.audit_project(project)
    plan = VideoComplianceEngine.generate_compliance_repairs(report, project)
    if not plan.operations:
        return {'status': 'noop', 'message': 'No auto-fixable compliance issues found', 'project': stored}
    updated, warnings = OperationExecutor.apply_plan(project, plan)
    saved = save_plan(updated, project_id, plan, 'rule_engine', 'Compliance Auto-Repair', 'Compliance Repair')
    return {'status': 'repaired', 'project': saved, 'plan': plan.model_dump(mode='json')}


@router.post('/projects/{project_id}/variants')
def create_variant_endpoint(project_id: str, body: VariantRequest):
    variant = create_platform_variant(master_project=load_project(project_id), master_project_id=project_id,
                                      target_aspect=body.target_aspect, focal_x=body.focal_x, focal_y=body.focal_y)
    # Saved as a new, independent project.
    return save(variant, actor='user', instruction=f"Created {body.target_aspect} variant from {project_id}")


# ------------------------------------------------------------------ voiceover and music

@router.post('/projects/{project_id}/generate-voiceover')
def generate_voiceover_endpoint(project_id: str, body: VoiceoverRequest):
    project = load_project(project_id)
    from agency.tts import tts_engine
    tts_result = guard(tts_engine.generate_voiceover, text=body.text, voice_id=body.voice_id, speed=body.speed)
    asset = guard(ingest, Path(tts_result['file_path']), tts_result['filename'])
    if body.add_to_timeline:
        duration = float(tts_result['duration_seconds'])
        project.clips.append(Clip(asset_id=asset['id'], kind='audio', start=body.start, duration=duration, volume=1.0, track=4,
                                  audio_role='voiceover', ducking_priority=body.ducking_priority, fade_in=0.1, fade_out=0.1))
        if body.create_captions:
            project.clips.append(Clip(kind='title', text=body.text, start=body.start, duration=duration, x=0.5, y=0.82, track=2,
                                      text_role='caption', font='arabic' if any('؀' <= c <= 'ۿ' for c in body.text) else 'sans',
                                      fade_in=0.2, fade_out=0.2))
    saved = save(project, project_id, actor='user', instruction=f"Generated voiceover with {body.voice_id}",
                 reason="Local broadcast-grade speech synthesis")
    return {'project': saved, 'asset': asset, 'voiceover': tts_result}


@router.post('/projects/{project_id}/add-music')
def add_music_endpoint(project_id: str, body: BackgroundMusicRequest):
    project = load_project(project_id)
    _, total_duration = primary_layout(project)
    track_duration = body.duration_seconds or max(5.0, total_duration)
    from agency.music import music_engine
    music = guard(music_engine.generate_soundtrack, prompt=body.prompt, genre=body.genre, duration_seconds=track_duration)
    track = music.get('track', music)
    asset = guard(ingest, Path(track['file_path']), track['filename'])
    project.clips.append(Clip(asset_id=asset['id'], kind='audio', start=0.0, duration=track_duration, volume=body.volume, track=5,
                              audio_role='music', ducking_priority=body.ducking_priority, fade_in=0.5, fade_out=0.8))
    saved = save(project, project_id, actor='user', instruction=f"Added background music track: {body.genre}",
                 reason="Offline ambient background music")
    return {'project': saved, 'asset': asset, 'soundtrack': music}


# ------------------------------------------------------------------ what the editor can do here

@router.get('/editing-capabilities')
def editing_capabilities():
    """What the guided editor can do on this machine: optional models, platform profiles, styles."""
    from video import platforms as video_platforms
    from video import segmentation as video_segmentation
    from video.provider_registry import providers
    from video.transcription import status as speech
    semantic = branded.ai_status()
    return dict(
        matting=guard(video_segmentation.status), speech=speech(), platforms=guard(video_platforms.public),
        creative_director=dict(schema_version=1, semantic_provider_available=semantic['available'], cut_policies=['safe', 'balanced', 'aggressive']),
        composition=dict(scene_aware=True, hand_object_detection=False, caption_timing_optimizer=True),
        optional_providers=providers(), performance_tiers=['basic-cpu', 'enhanced-cpu', 'gpu-professional'],
        styles=[dict(id=key, label=value['label'], summary=value['summary']) for key, value in video_platforms.STYLES.items()],
        semantic_planner=dict(available=semantic['available'], reason='Semantic AI planner available in the Advanced editor; proposed operations require review.' if semantic['available'] else
                              'Semantic AI planner unavailable. Deterministic editing remains available.'),
        generative_background=dict(available=False, reason='Generative background replacement is not implemented. Blur/dim and replacement with your own approved image use a local subject mask.'),
        ai_upscale=dict(available=False, reason='No restoration or upscaling model is installed. "Platform canvas" only rescales.'))


@router.get('/editor/capabilities')
def editor_status():
    from video.fonts import FONTS
    from video.transcription import status
    return dict(ai=branded.ai_status(), speech=status(), quick_edit=True, deterministic=True,
                supported_operations=list(branded.SUPPORTED), fonts=list(FONTS))
