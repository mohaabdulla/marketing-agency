"""Storyboard videos: planning a brief, narrator voices, company introductions and rendered sequences."""
import threading
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field, model_validator

from video import company_intro
from video.brief_assistant import MessageRequest, suggest_message
from video.director import RenderSequenceRequest, VideoBriefRequest, generate_video_brief
from video.jobs import jobs
from video.projects import Strict
from video.routes.common import guard, require_ffmpeg
from video.sequence import prepare_sequence, render_sequence
from video.storage import DATA, identifier, read
from video.voice import fit_timings, preview, public_voices

router = APIRouter()


def queue_render(body, kind='storyboard-sequence', action='rendering a storyboard'):
    """Check the tools, validate the reviewed storyboard and its media, then queue the render.
    Shared by the storyboard, company-introduction and agency campaign routes."""
    require_ffmpeg(action)
    brief = guard(prepare_sequence, body)
    return guard(jobs.submit, kind, lambda job: render_sequence(brief, body, job))


@router.post('/generate-brief')
def video_generate_brief(body: VideoBriefRequest):
    return guard(generate_video_brief, body)


@router.post('/suggest-message')
def video_suggest_message(body: MessageRequest):
    return guard(suggest_message, body)


@router.get('/briefs/{brief_id}')
def video_get_brief(brief_id: str):
    return guard(read, 'briefs', brief_id)


@router.post('/render-sequence', status_code=202)
def video_render_sequence(body: RenderSequenceRequest):
    return queue_render(body)


@router.get('/sequences/{sequence_id}/bundle')
def video_sequence_bundle(sequence_id: str):
    guard(read, 'sequences', sequence_id)
    path = DATA / 'sequences' / (identifier(sequence_id) + '.zip')
    if not path.is_file():
        raise HTTPException(404, 'Bundle not found')
    return FileResponse(path, media_type='application/zip', filename='video-client-kit.zip')


# ------------------------------------------------------------------ narrator voices

@router.get('/voices')
def video_voices(language: str | None = None):
    """Offline narrator voices installed on this computer (no network, no paid service)."""
    return dict(voices=public_voices(language if language in ('en', 'ar') else None))


class VoicePreviewRequest(Strict):
    voice_id: str = Field(pattern=r'^[a-z0-9-]{1,80}$')
    text: str = Field(min_length=1, max_length=450)
    language: Literal['en', 'ar'] = 'en'
    duration: float | None = Field(None, ge=1, le=60)


_PREVIEWS = threading.BoundedSemaphore(2)


@router.post('/voices/preview')
def video_voice_preview(body: VoicePreviewRequest):
    """Let the person hear one narration line, and whether it fits its scene, before approving a render."""
    if not body.text.strip():
        raise HTTPException(400, 'Write the narration first')
    if not _PREVIEWS.acquire(blocking=False):
        raise HTTPException(429, 'Another narration preview is still recording; try again in a moment')
    try:
        return guard(preview, body.text, body.voice_id, body.language, body.duration)
    finally:
        _PREVIEWS.release()


class VoiceFitRequest(Strict):
    voice_id: str = Field(pattern=r'^[a-z0-9-]{1,80}$')
    language: Literal['en', 'ar'] = 'en'
    lines: list[Annotated[str, Field(min_length=1, max_length=450)]] = Field(min_length=1, max_length=6)
    durations: list[Annotated[float, Field(ge=1, le=60)]] = Field(min_length=1, max_length=6)

    @model_validator(mode='after')
    def one_duration_per_line(self):
        if len(self.lines) != len(self.durations):
            raise ValueError('Give one duration per narration line')
        if any(not line.strip() for line in self.lines):
            raise ValueError('Every scene needs narration to time it')
        return self


@router.post('/voices/fit')
def video_voice_fit(body: VoiceFitRequest):
    """Scene lengths that follow how long each narration line takes to say, keeping the total length.
    Returned for review; nothing is changed until the person applies and renders."""
    if not _PREVIEWS.acquire(blocking=False):
        raise HTTPException(429, 'The narrator is busy with another recording; try again in a moment')
    try:
        return guard(fit_timings, body.lines, body.durations, body.language, body.voice_id)
    finally:
        _PREVIEWS.release()


# ------------------------------------------------------------------ company introduction

@router.post('/company-intro/research', status_code=202)
def video_company_research(body: company_intro.CompanyResearchRequest):
    """Research the company website (and optionally the web) in the background; the job result is the proposal."""
    return guard(jobs.submit, 'company-research', lambda job: company_intro.research_company(body, job))


@router.get('/company-intro/{proposal_id}')
def video_company_proposal(proposal_id: str):
    return guard(company_intro.get_proposal, proposal_id)


@router.get('/company-intro/{proposal_id}/images/{index}')
def video_company_image(proposal_id: str, index: int):
    return FileResponse(guard(company_intro.image_path, proposal_id, index), media_type='image/jpeg')


@router.get('/company-intro/{proposal_id}/videos/{index}')
def video_company_video(proposal_id: str, index: int):
    return FileResponse(guard(company_intro.video_path, proposal_id, index), media_type='video/mp4')


@router.get('/company-intro/{proposal_id}/videos/{index}/poster')
def video_company_video_poster(proposal_id: str, index: int):
    return FileResponse(guard(company_intro.video_path, proposal_id, index, True), media_type='image/jpeg')


@router.post('/company-intro/{proposal_id}/approve', status_code=202)
def video_company_approve(proposal_id: str, body: company_intro.CompanyIntroApproval):
    """The person approved the proposal: store the storyboard and render the finished video."""
    require_ffmpeg('rendering a video')
    brief = guard(company_intro.approve, proposal_id, body)
    render_body = RenderSequenceRequest(brief_id=brief['brief_id'], burn_subtitles=body.burn_subtitles,
                                        music_asset_id=body.music_asset_id, voiceover_asset_id=body.voiceover_asset_id,
                                        voiceover_volume=body.voiceover_volume, music_volume=body.music_volume,
                                        narrator_voice=body.narrator_voice)
    job = queue_render(render_body, 'company-intro-video', 'rendering a video')
    guard(company_intro.record_render, proposal_id, job['id'])
    return dict(brief=brief, job=job)
