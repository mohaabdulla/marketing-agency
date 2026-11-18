"""Media library, AI generation, analysis, export and background jobs."""
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import Field, model_validator

from video.ai_editor import VideoAIEditor
from video.analysis import analyze_asset, get_cached_analysis
from video.assets import EXTENSIONS, existing, ingest, path_for
from video.captions import DEFAULT_CAPTION_STYLES
from video.editor import render, validate_sources
from video.engine import Generate, check_generate, extract_audio, generate
from video.ffmpeg import binary
from video.jobs import jobs
from video.models import hardware, statuses
from video.projects import Project, Strict
from video.routes.common import guard
from video.storage import DATA, MAX_UPLOAD, listing, read

router = APIRouter()


# ------------------------------------------------------------------ this machine

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


# ------------------------------------------------------------------ media library

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
        if isinstance(value, dict) and 'source_url' in value and 'url' not in value:
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


# ------------------------------------------------------------------ analysis and transcription

class TranscribeRequest(Strict):
    language: str = Field('en', pattern=r'^(en|ar|auto)$')


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
        from video.transcription import transcribe
        return transcribe(asset_id, body.language, job)

    return guard(jobs.submit, 'transcribe', run_transcription)


@router.post('/assets/{asset_id}/qa', status_code=202)
def asset_technical_qa(asset_id: str):
    """Measure any managed video (loudness, true peak, colour tags, black/frozen intervals)."""
    return guard(jobs.submit, 'analyze', lambda job: analyze_asset(asset_id, force=True, job=job).model_dump(mode='json'))


# ------------------------------------------------------------------ generation and export

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
    from video.qa import master
    return guard(jobs.submit, 'export', lambda job: master(body.project, job, audio=body.audio))


@router.get('/export-presets')
def export_presets():
    from video.presets import public, DEFAULT
    return dict(presets=public(), default=DEFAULT,
                note='Loudness and true peak are measured per ITU-R BS.1770 for every preset. Only the broadcast preset uses the EBU R128 target; '
                     'web and social targets are product delivery choices.')


# ------------------------------------------------------------------ background jobs

@router.get('/jobs/{job_id}')
def job_status(job_id: str):
    return guard(jobs.status, job_id)


@router.get('/jobs')
def job_list():
    return listing('jobs')[:100]


@router.post('/jobs/{job_id}/cancel')
def cancel(job_id: str):
    return guard(jobs.cancel, job_id)
