from typing import Literal
from fastapi import HTTPException
from fastapi.responses import Response
from .api import router, guard
from .schemas import Id, Strict, Locale
from .services import service
from .jobs import queue
from . import audio


@router.get('/audio/capabilities')
def capabilities():
    return guard(audio.capabilities)


@router.post('/clients/{client_id}/audio-projects/{project_id}/render', status_code=202)
def render_audio(client_id: Id, project_id: Id):
    project = guard(service.get, client_id, project_id, 'audio-projects')
    guard(audio.source, client_id, project['data']['asset_id'])
    caps = guard(audio.capabilities)
    if not caps['ffmpeg'] or not caps['ffprobe']:
        raise HTTPException(409, 'Install FFmpeg and FFprobe before rendering audio')
    return guard(queue.submit, client_id, 'audio-render', lambda task: audio.render(client_id, project_id, task), target_id=project_id)


@router.get('/clients/{client_id}/subtitles/{subtitle_id}/export')
def export_subtitles(client_id: Id, subtitle_id: Id, format: Literal['srt', 'vtt'] = 'srt'):
    item = guard(service.get, client_id, subtitle_id, 'subtitles')
    return Response(guard(audio.captions, item['data'], format),
                    media_type='application/x-subrip' if format == 'srt' else 'text/vtt',
                    headers={'Content-Disposition': f'attachment; filename="captions.{format}"'})


class Transcribe(Strict):
    language: Locale = 'en'


@router.post('/clients/{client_id}/assets/{asset_id}/transcribe', status_code=202)
def transcribe(client_id: Id, asset_id: Id, body: Transcribe):
    guard(audio.source, client_id, asset_id)
    if not guard(audio.capabilities)['asr']['available']:
        raise HTTPException(409, 'Local Whisper is not installed. Configure AGENCY_ASR_MODEL_DIR and the optional faster-whisper runtime; no model is downloaded automatically.')
    return guard(queue.submit, client_id, 'audio-transcription',
                 lambda task: audio.transcribe(client_id, asset_id, body.language, task), target_id=asset_id)
