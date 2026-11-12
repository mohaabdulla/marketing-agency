"""Isolated video API. Heavy work never runs on the ASGI event loop."""
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse, Response
from starlette.concurrency import run_in_threadpool
from pydantic import Field
from video_storage import DATA, MAX_UPLOAD, read, listing, space, identifier
from video_projects import Strict, Project, save
from video_assets import ingest, path_for, existing, EXTENSIONS
from video_jobs import jobs
from video_ffmpeg import binary
from video_models import hardware, statuses
from video_engine import Generate, check_generate, generate, extract_audio
from video_editor import render, validate_sources


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


@router.get('/health')
def health():
    return dict(ffmpeg=bool(binary('ffmpeg')), ffprobe=bool(binary('ffprobe')), hardware=hardware(),
                storage='Application-managed video assets and JSON projects', max_upload_mb=MAX_UPLOAD//1024**2)


@router.get('/capabilities')
def capabilities():
    models = statuses()
    return dict(editor=bool(binary('ffmpeg') and binary('ffprobe')), models=models,
                max_duration=300, max_clips=60, exports=['mp4', 'webm'], ai_inference_verified=any(m['verified'] for m in models),
                image_animation='CPU deterministic motion; no diffusion or paid service')


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
        with tempfile.NamedTemporaryFile(dir=DATA/'work', suffix=Path(name).suffix.lower(), delete=False) as out:
            temp = Path(out.name)
            while chunk := await file.read(1024*1024):
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise HTTPException(413, 'File exceeds upload limit')
                await run_in_threadpool(guard, space, len(chunk))
                out.write(chunk)
        return await run_in_threadpool(guard, ingest, temp, name, move=True)
    finally:
        await file.close()
        if temp:
            temp.unlink(missing_ok=True)


class Import(Strict):
    source_url: str = Field(max_length=500)


@router.post('/import')
def import_asset(body: Import):
    return guard(existing, body.source_url)


@router.get('/media/{asset_id}')
def media(asset_id: str, request: Request):
    import mimetypes
    import re
    path = guard(path_for, asset_id)
    size = path.stat().st_size
    header = request.headers.get('range')
    start, end, status = 0, size-1, 200
    if header:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
        if not match or not any(match.groups()):
            return Response(status_code=416, headers={'Content-Range':f'bytes */{size}'})
        a, b = match.groups()
        if a:
            start, end = int(a), min(int(b) if b else size-1, size-1)
        else:
            start = max(0, size-int(b))
        if start > end or start >= size:
            return Response(status_code=416, headers={'Content-Range':f'bytes */{size}'})
        status = 206
    def chunks():
        remaining = end-start+1
        with path.open('rb') as handle:
            handle.seek(start)
            while remaining:
                data = handle.read(min(256*1024,remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data
    headers = {'Accept-Ranges':'bytes', 'Content-Length':str(end-start+1)}
    if status == 206:
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    return StreamingResponse(chunks(), status_code=status, headers=headers,
                             media_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream')


@router.get('/download/{asset_id}')
def download(asset_id: str):
    asset = guard(read, 'assets', asset_id)
    return FileResponse(guard(path_for, asset_id), filename=asset['name'])


@router.get('/thumbnails/{asset_id}')
def thumbnail(asset_id: str):
    path = guard(path_for, asset_id).with_suffix('.thumb.jpg')
    if not path.is_file():
        raise HTTPException(404, 'Thumbnail not available')
    return FileResponse(path)


@router.post('/projects')
def create_project(body: Project):
    if body.clips:
        guard(validate_sources, body)
    return guard(save, body)


@router.get('/projects')
def projects():
    return listing('projects')


@router.get('/projects/{project_id}')
def get_project(project_id: str):
    return guard(read, 'projects', project_id)


@router.put('/projects/{project_id}')
def save_project(project_id: str, body: Project):
    if body.clips:
        guard(validate_sources, body)
    return guard(save, body, project_id)


@router.post('/projects/{project_id}/duplicate')
def duplicate_project(project_id: str):
    old = guard(read, 'projects', project_id)
    body = Project(**{k:v for k,v in old.items() if k not in ('id','created','updated')})
    body.name = (body.name[:110] + ' copy')
    return guard(save, body)


@router.delete('/projects/{project_id}')
def delete_project(project_id: str):
    guard(read, 'projects', project_id)
    (DATA/'projects'/(identifier(project_id)+'.json')).unlink()
    return dict(deleted=True)


class Export(Strict):
    project: Project
    container: str = Field('mp4', pattern=r'^(mp4|webm)$')
    audio: bool = True
    preview: bool = False


@router.post('/export', status_code=202)
def export(body: Export):
    guard(validate_sources, body.project)
    return guard(jobs.submit, 'preview' if body.preview else 'export',
                 lambda job: render(body.project, job, body.container, body.audio, body.preview))


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
    return guard(read, 'jobs', job_id)


@router.get('/jobs')
def job_list():
    return listing('jobs')[:100]


@router.post('/jobs/{job_id}/cancel')
def cancel(job_id: str):
    return guard(jobs.cancel, job_id)
