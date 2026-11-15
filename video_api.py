"""Isolated video API with persistent revision control, media analysis, captions, compliance, and AI editing."""
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse, Response
from starlette.concurrency import run_in_threadpool
from pydantic import Field, model_validator

from video_storage import DATA, MAX_UPLOAD, read, listing, space, identifier, atomic
from video_projects import Strict, Project, save, migrate_project
from video_assets import ingest, path_for, existing, EXTENSIONS
from video_jobs import jobs
from video_ffmpeg import binary
from video_models import hardware, statuses
from video_engine import Generate, check_generate, generate, extract_audio
from video_editor import render, validate_sources
from video_revisions import record_revision, get_revisions, get_revision, restore_revision, undo, redo
from video_operations import EditOperation, EditPlan, OperationExecutor
from video_analysis import analyze_asset, get_cached_analysis
from video_captions import DEFAULT_CAPTION_STYLES, CaptionTrack, parse_srt, to_srt, to_vtt
from video_brand_context import compile_video_edit_context
from video_compliance import VideoComplianceEngine
from video_ai_editor import VideoAIEditor
from video_variants import create_platform_variant
from video_review import ReviewRequest, review_record, set_review


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
    from brand_guidelines import Rules
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
    return dict(
        matting=guard(video_segmentation.status), speech=speech(), platforms=guard(video_platforms.public),
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
