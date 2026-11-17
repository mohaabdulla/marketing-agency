"""Isolated video API with persistent revision control, media analysis, captions, compliance, and AI editing."""
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import Field, model_validator

from video_storage import DATA, MAX_UPLOAD, read, listing, identifier
from video_projects import Strict, Project, save, migrate_project
from video_assets import ingest, path_for, existing, EXTENSIONS
from video_jobs import jobs
from video_ffmpeg import binary
from video_models import hardware, statuses
from video_engine import Generate, check_generate, generate, extract_audio
from video_editor import render, validate_sources
from video_revisions import get_revisions, get_revision, restore_revision, undo, redo
from video_operations import OperationExecutor
from video_analysis import analyze_asset, get_cached_analysis
from video_captions import DEFAULT_CAPTION_STYLES
from video_brand_context import compile_video_edit_context
from video_compliance import VideoComplianceEngine
from video_ai_editor import VideoAIEditor
from video_variants import create_platform_variant
from video_review import ReviewRequest, review_record, set_review,RubricRequest,set_rubric,RUBRIC_CATEGORIES
from video_director import VideoBriefRequest,RenderSequenceRequest,generate_video_brief
from video_engine import prepare_sequence,render_sequence
from video_brief_assistant import MessageRequest,suggest_message
import video_company_intro as company_intro


def trusted_origin(request: Request):
    origin = request.headers.get('origin')
    if origin:
        parsed = urlsplit(origin)
        same = parsed.scheme == request.url.scheme and parsed.netloc == request.url.netloc
        allowed = {x.strip() for x in os.getenv('VIDEO_ALLOWED_ORIGINS', '').split(',') if x.strip()}
        if not same and origin not in allowed:
            raise HTTPException(403, 'Video requests must originate from this application')


router = APIRouter(prefix='/api/video', tags=['video'], dependencies=[Depends(trusted_origin)])


def guard(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except FileNotFoundError:
        raise HTTPException(404, 'Item not found')
    except (ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'Media operation failed'
        if '\\' in message or '/' in message:
            message = 'Invalid media operation; see local diagnostics'
        raise HTTPException(400, message)


@router.post('/generate-brief')
def video_generate_brief(body: VideoBriefRequest):
    return guard(generate_video_brief,body)


@router.post('/suggest-message')
def video_suggest_message(body: MessageRequest):
    return guard(suggest_message,body)


@router.get('/briefs/{brief_id}')
def video_get_brief(brief_id: str):
    return guard(read,'briefs',brief_id)


@router.post('/render-sequence',status_code=202)
def video_render_sequence(body: RenderSequenceRequest):
    if not binary('ffmpeg') or not binary('ffprobe'):
        raise HTTPException(503,'Install FFmpeg and FFprobe before rendering a storyboard')
    brief=guard(prepare_sequence,body)
    return guard(jobs.submit,'storyboard-sequence',lambda job:render_sequence(brief,body,job))


@router.post('/company-intro/research',status_code=202)
def video_company_research(body: company_intro.CompanyResearchRequest):
    """Research the company website (and optionally the web) in the background; the job result is the proposal."""
    return guard(jobs.submit,'company-research',lambda job:company_intro.research_company(body,job))


@router.get('/company-intro/{proposal_id}')
def video_company_proposal(proposal_id: str):
    return guard(company_intro.get_proposal,proposal_id)


@router.get('/company-intro/{proposal_id}/images/{index}')
def video_company_image(proposal_id: str, index: int):
    return FileResponse(guard(company_intro.image_path,proposal_id,index),media_type='image/jpeg')


@router.post('/company-intro/{proposal_id}/approve',status_code=202)
def video_company_approve(proposal_id: str, body: company_intro.CompanyIntroApproval):
    """The person approved the proposal: store the storyboard and render the finished video."""
    if not binary('ffmpeg') or not binary('ffprobe'):
        raise HTTPException(503,'Install FFmpeg and FFprobe before rendering a video')
    brief=guard(company_intro.approve,proposal_id,body)
    render_body=RenderSequenceRequest(brief_id=brief['brief_id'],burn_subtitles=body.burn_subtitles,music_asset_id=body.music_asset_id,
        voiceover_asset_id=body.voiceover_asset_id,voiceover_volume=body.voiceover_volume,music_volume=body.music_volume)
    prepared=guard(prepare_sequence,render_body)
    job=guard(jobs.submit,'company-intro-video',lambda job:render_sequence(prepared,render_body,job))
    guard(company_intro.record_render,proposal_id,job['id'])
    return dict(brief=brief,job=job)


@router.get('/sequences/{sequence_id}/bundle')
def video_sequence_bundle(sequence_id: str):
    guard(read,'sequences',sequence_id)
    path=DATA/'sequences'/(identifier(sequence_id)+'.zip')
    if not path.is_file():raise HTTPException(404,'Bundle not found')
    return FileResponse(path,media_type='application/zip',filename='video-client-kit.zip')


# Request schemas for AI editing, auto-polish, variants, and transcription
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


class TranscribeRequest(Strict):
    language: str = Field('en', pattern=r'^(en|ar|auto)$')


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


@router.get('/health')
def health():
    return dict(ffmpeg=bool(binary('ffmpeg')), ffprobe=bool(binary('ffprobe')), hardware=hardware(),
                storage='Application-managed video assets and JSON projects', max_upload_mb=MAX_UPLOAD // 1024**2)


@router.get('/capabilities')
def capabilities():
    models = statuses()
    ai_ready, ai_reason = VideoAIEditor.is_ai_available()
    return dict(
        editor=bool(binary('ffmpeg') and binary('ffprobe')),
        models=models,
        max_duration=300,
        max_clips=60,
        exports=['mp4', 'webm'],
        ai_inference_verified=any(m['verified'] for m in models),
        image_animation='CPU deterministic motion; no diffusion or paid service',
        ai_editor=dict(available=ai_ready, reason=ai_reason),
        caption_styles=list(DEFAULT_CAPTION_STYLES.keys()),
        safe_zones=['generic', 'vertical-social', 'square-social', 'landscape-social']
    )


@router.get('/models')
def models():
    return statuses()


@router.get('/assets')
def assets():
    return listing('assets')


@router.post('/upload')
async def upload(file: UploadFile = File(...)):
    name = file.filename or ''
    if Path(name).suffix.lower() not in EXTENSIONS:
        raise HTTPException(400, 'Unsupported media extension')
    temp = None
    try:
        total = 0
        with tempfile.NamedTemporaryFile(dir=DATA / 'work', suffix=Path(name).suffix.lower(), delete=False) as out:
            temp = Path(out.name)
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise HTTPException(413, 'File exceeds upload limit')
                out.write(chunk)
        return guard(ingest, temp, name, move=True)
    finally:
        if temp and temp.is_file():
            temp.unlink(missing_ok=True)


class ImportMedia(Strict):
    url: str = Field(..., max_length=1000)

    @model_validator(mode='before')
    @classmethod
    def legacy_alias(cls, value):
        if isinstance(value,dict) and 'source_url' in value and 'url' not in value:
            value = dict(value)
            value['url'] = value.pop('source_url')
        return value


@router.post('/import')
def import_asset(body: ImportMedia):
    return guard(existing, body.url)


@router.get('/media/{asset_id}')
async def media_stream(asset_id: str, request: Request):
    path = guard(path_for, asset_id)
    size = path.stat().st_size
    range_header = request.headers.get('range')
    if range_header:
        parts = range_header.replace('bytes=', '').split('-')
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else size - 1
        end = min(end, size - 1)
        length = end - start + 1
        if start >= size:
            raise HTTPException(416, 'Requested range not satisfiable')

        def chunker():
            with path.open('rb') as f:
                f.seek(start)
                left = length
                while left > 0:
                    read_bytes = f.read(min(left, 64 * 1024))
                    if not read_bytes:
                        break
                    left -= len(read_bytes)
                    yield read_bytes

        headers = {
            'Content-Range': f'bytes {start}-{end}/{size}',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(length),
        }
        return StreamingResponse(chunker(), status_code=206, headers=headers, media_type='video/mp4')
    return FileResponse(path)


@router.get('/download/{asset_id}')
def download(asset_id: str):
    asset = guard(read, 'assets', asset_id)
    return FileResponse(guard(path_for, asset_id), filename=asset['name'])


@router.get('/thumbnails/{asset_id}')
def thumbnail(asset_id: str):
    # Support both asset thumbnail and shot analysis thumbnail names
    clean_id = asset_id.replace('.jpg', '').replace('.thumb', '')
    p1 = guard(path_for, clean_id).with_suffix('.thumb.jpg')
    p2 = DATA / 'assets' / 'thumbs' / f"{clean_id}.jpg"
    p3 = DATA / 'assets' / 'thumbs' / asset_id

    for cand in (p1, p2, p3):
        if cand.is_file():
            return FileResponse(cand)
    raise HTTPException(404, 'Thumbnail not available')


# ==========================================
# Projects & Revision Control
# ==========================================

@router.post('/projects')
def create_project(body: Project):
    if body.clips:
        guard(validate_sources, body)
    return guard(save, body, actor='user', instruction='Initial project creation')


@router.get('/projects')
def projects():
    return [migrate_project(p) for p in listing('projects')]


@router.get('/projects/{project_id}')
def get_project(project_id: str):
    raw = guard(read, 'projects', project_id)
    return migrate_project(raw)


@router.put('/projects/{project_id}')
def save_project_endpoint(project_id: str, body: Project):
    if body.clips:
        guard(validate_sources, body)
    return guard(save, body, project_id, actor='user', instruction='Manual timeline edits')


@router.post('/projects/{project_id}/duplicate')
def duplicate_project(project_id: str):
    old = guard(read, 'projects', project_id)
    migrated = migrate_project(old)
    body = Project(**{k: v for k, v in migrated.items() if k not in ('id', 'created', 'updated')})
    body.name = (body.name[:110] + ' copy')
    return guard(save, body, actor='user', instruction=f"Duplicated from {project_id}")


@router.delete('/projects/{project_id}')
def delete_project(project_id: str):
    guard(read, 'projects', project_id)
    (DATA / 'projects' / (identifier(project_id) + '.json')).unlink()
    return dict(deleted=True)


@router.get('/projects/{project_id}/revisions')
def list_revisions(project_id: str):
    guard(read, 'projects', project_id)
    return {'revisions': get_revisions(project_id)}


@router.get('/assets/{asset_id}/review')
def get_asset_review(asset_id: str):
    return guard(review_record, asset_id)


@router.post('/assets/{asset_id}/review')
def update_asset_review(asset_id: str, body: ReviewRequest):
    return guard(set_review, asset_id, body)


@router.post('/assets/{asset_id}/rubric')
def save_creative_rubric(asset_id: str,body: RubricRequest):
    return guard(set_rubric,asset_id,body)


@router.get('/creative-review/rubric')
def creative_rubric():
    return dict(categories=RUBRIC_CATEGORIES,scale=[1,2,3,4,5],basis='HUMAN_REVIEW_ONLY',notice='Ratings describe a person\'s judgment, not an automated professional quality score.')


@router.get('/projects/{project_id}/revisions/{revision_id}')
def get_revision_snapshot(project_id: str, revision_id: str):
    guard(read, 'projects', project_id)
    rev = get_revision(project_id, revision_id)
    if not rev:
        raise HTTPException(404, f"Revision {revision_id} not found")
    return rev


@router.post('/projects/{project_id}/revisions/{revision_id}/restore')
def restore_revision_endpoint(project_id: str, revision_id: str):
    guard(read, 'projects', project_id)
    return guard(restore_revision, project_id, revision_id)


@router.post('/projects/{project_id}/undo')
def undo_endpoint(project_id: str):
    guard(read, 'projects', project_id)
    res = undo(project_id)
    if not res:
        raise HTTPException(400, 'Cannot undo: already at the earliest revision')
    return res


@router.post('/projects/{project_id}/redo')
def redo_endpoint(project_id: str):
    guard(read, 'projects', project_id)
    res = redo(project_id)
    if not res:
        raise HTTPException(400, 'Cannot redo: already at the latest revision')
    return res


# ==========================================
# Media Analysis & Transcription
# ==========================================

@router.post('/assets/{asset_id}/analyze', status_code=202)
def start_analyze_asset(asset_id: str):
    guard(read, 'assets', asset_id)
    return guard(
        jobs.submit, 'analyze',
        lambda job: analyze_asset(asset_id, force=True, job=job).model_dump(mode='json')
    )


@router.get('/assets/{asset_id}/analysis')
def get_asset_analysis(asset_id: str):
    guard(read, 'assets', asset_id)
    analysis = get_cached_analysis(asset_id)
    if not analysis:
        # Run synchronous analysis if not yet cached
        analysis = guard(analyze_asset, asset_id, False)
    return analysis.model_dump(mode='json')


@router.post('/assets/{asset_id}/transcribe', status_code=202)
def start_transcribe_asset(asset_id: str, body: TranscribeRequest):
    item = guard(read, 'assets', asset_id)
    if not item.get('has_audio'):
        raise HTTPException(400, 'Asset has no audio track for transcription')

    def run_transcription(job):
        from video_transcription import transcribe
        return transcribe(asset_id,body.language,job)

    return guard(jobs.submit, 'transcribe', run_transcription)


from video_quick_edit import QuickEdit


@router.post('/projects/{project_id}/quick-edit',status_code=202)
def quick_edit(project_id: str,body: QuickEdit):
    from video_quick_edit import run
    from video_brand_editing import model
    original=guard(model,guard(read,'projects',project_id))
    asset=guard(read,'assets',body.asset_id)
    if asset['kind']!='video':raise HTTPException(400,'Choose a video source; upload logos separately')
    if not 0<asset['duration']<=300:raise HTTPException(400,'Quick edit supports videos up to five minutes')
    for key,kinds in [('reference_asset_id',{'video'}),('background_asset_id',{'image','video'}),('parent_asset_id',{'video'})]:
        value=getattr(body,key)
        if value:
            item=guard(read,'assets',value)
            if item['kind'] not in kinds:raise HTTPException(400,'The selected reference, background or parent asset has an incompatible media type.')
            if key=='parent_asset_id' and item.get('source_asset_id')!=body.asset_id:raise HTTPException(400,'The previous render must belong to this source video.')
    original.master_project_id=project_id
    return guard(jobs.submit,'quick-edit',lambda job:run(original,body,job))


@router.get('/captions/styles')
def caption_styles():
    return {k: v.model_dump(mode='json') for k, v in DEFAULT_CAPTION_STYLES.items()}


# ==========================================
# AI Editor, Auto-Polish & Compliance
# ==========================================

@router.post('/projects/{project_id}/ai/first-cut')
def ai_first_cut(project_id: str, body: AIFirstCutRequest):
    proj_data = migrate_project(guard(read, 'projects', project_id))
    project = Project.model_validate({k:v for k,v in proj_data.items() if k in Project.model_fields})

    media_assets = [guard(read, 'assets', aid) for aid in body.media_asset_ids]
    # Collect cached analyses
    analyses = [get_cached_analysis(aid).model_dump(mode='json') for aid in body.media_asset_ids if get_cached_analysis(aid)]

    context = compile_video_edit_context(
        project=project,
        user_instruction=body.user_instruction,
        brand_profile=body.brand_profile,
        brief_data=body.brief_data,
        media_analyses=analyses,
        target_duration=body.target_duration,
        language=body.language
    )

    plan = VideoAIEditor.first_cut(project, context, media_assets)
    updated_project, warnings = OperationExecutor.apply_plan(project, plan)

    # Commit as AI revision
    saved = save(
        updated_project, project_id, actor='rule_engine',
        instruction=f"Deterministic First Cut: {plan.intent}",
        reason='; '.join(op.reason for op in plan.operations if op.reason),
        operation_ids=[op.operation_id for op in plan.operations],
        label='Deterministic First Cut'
    )
    return {'project': saved, 'plan': plan.model_dump(mode='json'), 'warnings': warnings, 'engine':'rule_engine', 'ai_used':False}


@router.post('/projects/{project_id}/ai/edit')
def ai_edit_timeline(project_id: str, body: AIEditRequest):
    proj_data = migrate_project(guard(read, 'projects', project_id))
    project = Project.model_validate({k:v for k,v in proj_data.items() if k in Project.model_fields})

    context = compile_video_edit_context(
        project=project,
        user_instruction=body.instruction,
        brand_profile=body.brand_profile,
        brief_data=body.brief_data
    )

    import video_brand_editing as branded
    if not branded.ai_status()['available']:
        raise HTTPException(409,branded.ai_status()['reason'])
    plan = guard(branded.local_plan,project,body.instruction,branded.effective_rules(project,body.brand_profile))
    updated_project = guard(branded.checked,project,plan)
    warnings = plan.warnings
    result=branded.compliance(updated_project)
    if not result['passed']:
        raise HTTPException(409,dict(message='Brand checks need review; use the preview/apply workflow',findings=result['findings']))

    # Commit as AI patch revision
    saved = save(
        updated_project, project_id, actor='ai',
        instruction=body.instruction,
        reason='; '.join(op.reason for op in plan.operations if op.reason),
        operation_ids=[op.operation_id for op in plan.operations],
        label='AI Edit'
    )
    return {'project': saved, 'plan': plan.model_dump(mode='json'), 'warnings': warnings}


@router.post('/projects/{project_id}/auto-polish')
def auto_polish_endpoint(project_id: str, body: AutoPolishRequest):
    proj_data = migrate_project(guard(read, 'projects', project_id))
    project = Project.model_validate({k:v for k,v in proj_data.items() if k in Project.model_fields})

    context = compile_video_edit_context(
        project=project,
        brand_profile=body.brand_profile,
        brief_data=body.brief_data
    )

    import video_brand_editing as branded
    plan = guard(branded.polish,project,'Apply the reviewed brand styling.',branded.effective_rules(project,body.brand_profile))
    updated_project = guard(branded.checked,project,plan)
    warnings = plan.warnings

    saved = save(
        updated_project, project_id, actor='rule_engine',
        instruction='Deterministic Auto Polish',
        reason='; '.join(op.reason for op in plan.operations if op.reason),
        operation_ids=[op.operation_id for op in plan.operations],
        label='Auto Polish'
    )
    return {'project': saved, 'plan': plan.model_dump(mode='json'), 'warnings': warnings}


@router.get('/projects/{project_id}/compliance')
def get_compliance_report(project_id: str):
    proj_data = migrate_project(guard(read, 'projects', project_id))
    project = Project.model_validate({k:v for k,v in proj_data.items() if k in Project.model_fields})
    report = VideoComplianceEngine.audit_project(project)
    return report.model_dump(mode='json')


@router.post('/projects/{project_id}/compliance/fix')
def fix_compliance_endpoint(project_id: str):
    proj_data = migrate_project(guard(read, 'projects', project_id))
    project = Project.model_validate({k:v for k,v in proj_data.items() if k in Project.model_fields})
    report = VideoComplianceEngine.audit_project(project)

    plan = VideoComplianceEngine.generate_compliance_repairs(report, project)
    if not plan.operations:
        return {'status': 'noop', 'message': 'No auto-fixable compliance issues found', 'project': proj_data}

    updated_project, warnings = OperationExecutor.apply_plan(project, plan)
    saved = save(
        updated_project, project_id, actor='rule_engine',
        instruction='Compliance Auto-Repair',
        reason='; '.join(op.reason for op in plan.operations if op.reason),
        operation_ids=[op.operation_id for op in plan.operations],
        label='Compliance Repair'
    )
    return {'status': 'repaired', 'project': saved, 'plan': plan.model_dump(mode='json')}


@router.post('/projects/{project_id}/variants')
def create_variant_endpoint(project_id: str, body: VariantRequest):
    proj_data = migrate_project(guard(read, 'projects', project_id))
    project = Project.model_validate({k:v for k,v in proj_data.items() if k in Project.model_fields})

    variant_proj = create_platform_variant(
        master_project=project,
        master_project_id=project_id,
        target_aspect=body.target_aspect,
        focal_x=body.focal_x,
        focal_y=body.focal_y
    )
    # Save as new independent project
    new_proj = save(variant_proj, actor='user', instruction=f"Created {body.target_aspect} variant from {project_id}")
    return new_proj


@router.post('/projects/{project_id}/generate-voiceover')
def generate_voiceover_endpoint(project_id: str, body: VoiceoverRequest):
    proj_data = migrate_project(guard(read, 'projects', project_id))
    project = Project.model_validate({k: v for k, v in proj_data.items() if k in Project.model_fields})

    from agency.tts import tts_engine
    tts_result = guard(tts_engine.generate_voiceover, text=body.text, voice_id=body.voice_id, speed=body.speed)

    wav_path = Path(tts_result['file_path'])
    asset = guard(ingest, wav_path, tts_result['filename'])

    if body.add_to_timeline:
        from video_projects import Clip
        dur = float(tts_result['duration_seconds'])
        audio_clip = Clip(
            asset_id=asset['id'],
            kind='audio',
            start=body.start,
            duration=dur,
            volume=1.0,
            track=4,
            audio_role='voiceover',
            ducking_priority=body.ducking_priority,
            fade_in=0.1,
            fade_out=0.1
        )
        project.clips.append(audio_clip)

        if body.create_captions:
            title_clip = Clip(
                kind='title',
                text=body.text,
                start=body.start,
                duration=dur,
                x=0.5,
                y=0.82,
                track=2,
                text_role='caption',
                font='arabic' if any('\u0600' <= c <= '\u06ff' for c in body.text) else 'sans',
                fade_in=0.2,
                fade_out=0.2
            )
            project.clips.append(title_clip)

    saved = save(
        project, project_id, actor='user',
        instruction=f"Generated voiceover with {body.voice_id}",
        reason="Local broadcast-grade speech synthesis"
    )
    return {'project': saved, 'asset': asset, 'voiceover': tts_result}


@router.post('/projects/{project_id}/add-music')
def add_music_endpoint(project_id: str, body: BackgroundMusicRequest):
    proj_data = migrate_project(guard(read, 'projects', project_id))
    project = Project.model_validate({k: v for k, v in proj_data.items() if k in Project.model_fields})

    from video_editor import primary_layout
    _, total_dur = primary_layout(project)
    track_dur = body.duration_seconds or max(5.0, total_dur)

    from agency.music import music_engine
    music_res = guard(music_engine.generate_soundtrack, prompt=body.prompt, genre=body.genre, duration_seconds=track_dur)

    track_meta = music_res.get('track', music_res)
    wav_path = Path(track_meta['file_path'])
    asset = guard(ingest, wav_path, track_meta['filename'])

    from video_projects import Clip
    music_clip = Clip(
        asset_id=asset['id'],
        kind='audio',
        start=0.0,
        duration=track_dur,
        volume=body.volume,
        track=5,
        audio_role='music',
        ducking_priority=body.ducking_priority,
        fade_in=0.5,
        fade_out=0.8
    )
    project.clips.append(music_clip)

    saved = save(
        project, project_id, actor='user',
        instruction=f"Added background music track: {body.genre}",
        reason="Offline ambient background music"
    )
    return {'project': saved, 'asset': asset, 'soundtrack': music_res}


@router.post('/projects/{project_id}/optimize-pacing')
def optimize_pacing_endpoint(project_id: str, body: OptimizePacingRequest):
    proj_data = migrate_project(guard(read, 'projects', project_id))
    project = Project.model_validate({k: v for k, v in proj_data.items() if k in Project.model_fields})

    import video_brand_editing as branded
    plan = guard(
        branded.optimize_pacing_and_transitions,
        project=project,
        pacing_mode=body.pacing_mode,
        default_transition=body.default_transition,
        transition_type=body.transition_type
    )

    updated_project, warnings = OperationExecutor.apply_plan(project, plan)
    saved = save(
        updated_project, project_id, actor='rule_engine',
        instruction=f"Optimized pacing ({body.pacing_mode}) and transitions ({body.transition_type})",
        reason='; '.join(op.reason for op in plan.operations if op.reason),
        operation_ids=[op.operation_id for op in plan.operations],
        label='Pacing & Transitions'
    )
    return {'project': saved, 'plan': plan.model_dump(mode='json'), 'warnings': warnings}


# ==========================================
# Rendering & Export
# ==========================================

class Export(Strict):
    project: Project
    container: str = Field('mp4', pattern=r'^(mp4|webm)$')
    audio: bool = True
    preview: bool = False


@router.post('/export', status_code=202)
def export(body: Export):
    guard(validate_sources, body.project)
    if body.preview or body.container != 'mp4':
        return guard(jobs.submit, 'preview' if body.preview else 'export',
                     lambda job: render(body.project, job, body.container, body.audio, body.preview))
    # Final MP4 exports are measured after rendering; the report travels with the result.
    from video_qa import master
    return guard(jobs.submit, 'export', lambda job: master(body.project, job, audio=body.audio))


@router.get('/export-presets')
def export_presets():
    from video_presets import public, DEFAULT
    return dict(presets=public(), default=DEFAULT,
                note='Loudness and true peak are measured per ITU-R BS.1770 for every preset. Only the broadcast preset uses the EBU R128 target; '
                     'web and social targets are product delivery choices.')


@router.get('/editing-capabilities')
def editing_capabilities():
    """What the guided editor can do on this machine: optional models, platform profiles, styles."""
    import video_platforms
    import video_segmentation
    from video_transcription import status as speech
    from video_brand_editing import ai_status
    semantic = ai_status()
    from video_provider_registry import providers
    return dict(
        matting=guard(video_segmentation.status), speech=speech(), platforms=guard(video_platforms.public),
        creative_director=dict(schema_version=1,semantic_provider_available=semantic['available'],cut_policies=['safe','balanced','aggressive']),
        composition=dict(scene_aware=True,hand_object_detection=False,caption_timing_optimizer=True),
        optional_providers=providers(),performance_tiers=['basic-cpu','enhanced-cpu','gpu-professional'],
        styles=[dict(id=key, label=value['label'], summary=value['summary']) for key, value in video_platforms.STYLES.items()],
        semantic_planner=dict(available=semantic['available'], reason='Semantic AI planner available in the Advanced editor; proposed operations require review.' if semantic['available'] else
                             'Semantic AI planner unavailable. Deterministic editing remains available.'),
        generative_background=dict(available=False, reason='Generative background replacement is not implemented. Blur/dim and replacement with your own approved image use a local subject mask.'),
        ai_upscale=dict(available=False, reason='No restoration or upscaling model is installed. "Platform canvas" only rescales.'))


@router.post('/assets/{asset_id}/qa', status_code=202)
def asset_technical_qa(asset_id: str):
    """Measure any managed video (loudness, true peak, colour tags, black/frozen intervals)."""
    return guard(jobs.submit, 'analyze', lambda job: analyze_asset(asset_id, force=True, job=job).model_dump(mode='json'))


@router.post('/generate', status_code=202)
def start_generate(body: Generate):
    guard(check_generate, body)
    return guard(jobs.submit, body.mode, lambda job: generate(body, job))


@router.post('/assets/{asset_id}/extract-audio', status_code=202)
def audio_extract(asset_id: str):
    item = guard(read, 'assets', asset_id)
    if not item.get('has_audio'):
        raise HTTPException(400, 'This asset has no audio stream')
    return guard(jobs.submit, 'extract-audio', lambda job: extract_audio(asset_id, job))


@router.get('/jobs/{job_id}')
def job_status(job_id: str):
    return guard(jobs.status, job_id)


@router.get('/jobs')
def job_list():
    return listing('jobs')[:100]


@router.post('/jobs/{job_id}/cancel')
def cancel(job_id: str):
    return guard(jobs.cancel, job_id)
