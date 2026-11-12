"""Production routes on the agency router: content, assets, approvals, publication packages,
analytics, reports. Same loopback guard, validation and safe errors as the planning routes."""
from datetime import date as Date
from typing import Annotated, Literal
from fastapi import HTTPException, Query, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field
from .api import router, guard
from .schemas import Strict, Id, Locale, Short, Text
from .production import channel_specs
from .production_schemas import GenerationNote
from . import content, assets, analytics

Options = Annotated[list[Short], Field(max_length=12)]


@router.get('/channel-specs')
def specs():
    return guard(channel_specs)


class Matrix(Strict):
    brief_id: Id | None = None
    audience_id: Id | None = None
    axes: dict[Literal['hook_type', 'benefit', 'pain_point', 'awareness_stage', 'appeal', 'visual_territory', 'offer', 'cta', 'channel'], Options]


@router.post('/clients/{client_id}/campaigns/{campaign_id}/concept-matrix', status_code=201)
def concept_matrix(client_id: Id, campaign_id: Id, body: Matrix):
    return guard(content.concept_matrix, client_id, campaign_id, body.axes, body.brief_id, body.audience_id)


class CopyCheck(Strict):
    format: Short
    text: str = Field(max_length=30000)
    headline: Short = ''
    cta: Short = ''
    hashtags: list[Short] = Field(default=[], max_length=50)
    language: Locale = 'en'
    claim_ids: list[Id] = Field(default=[], max_length=50)
    exclude_id: Id | None = None


@router.post('/clients/{client_id}/campaigns/{campaign_id}/copy-checks')
def copy_checks(client_id: Id, campaign_id: Id, body: CopyCheck):
    return guard(content.copy_checks, client_id, campaign_id, body.format, body.text, body.headline, body.cta,
                 body.hashtags, body.language, body.claim_ids, body.exclude_id)


@router.post('/clients/{client_id}/scripts/{script_id}/storyboard', status_code=201)
def script_storyboard(client_id: Id, script_id: Id):
    return guard(content.storyboard_from_script, client_id, script_id)


@router.get('/clients/{client_id}/storyboards/{storyboard_id}/shots')
def shots(client_id: Id, storyboard_id: Id):
    board, items = guard(content.storyboard_shots, client_id, storyboard_id)
    return dict(storyboard=board, shots=items, total_seconds=round(sum(s['data']['duration_seconds'] for s in items), 2))


@router.post('/clients/{client_id}/storyboards/{storyboard_id}/video-project', status_code=201)
def storyboard_video(client_id: Id, storyboard_id: Id):
    return guard(content.video_project_from_storyboard, client_id, storyboard_id)


@router.get('/clients/{client_id}/storyboards/{storyboard_id}/export')
def storyboard_export(client_id: Id, storyboard_id: Id):
    return FileResponse(guard(content.storyboard_export, client_id, storyboard_id), filename='storyboard.zip', media_type='application/zip')


@router.get('/clients/{client_id}/storyboards/{storyboard_id}/captions')
def storyboard_captions(client_id: Id, storyboard_id: Id, format: Literal['srt', 'vtt'] = 'srt'):
    from fastapi.responses import Response
    body, cues, seconds = guard(content.storyboard_captions, client_id, storyboard_id, format)
    return Response(body.encode('utf-8'), media_type='text/vtt' if format == 'vtt' else 'application/x-subrip',
                    headers={'Content-Disposition': f'attachment; filename="captions-planned-timing.{format}"',
                             'X-Caption-Cues': str(cues), 'X-Planned-Seconds': str(seconds)})


class AssetMeta(Strict):
    asset_type: Literal['image', 'gif', 'video', 'audio', 'logo', 'product-reference', 'document', 'subtitle', 'template'] | None = None
    origin: Literal['generated', 'owned', 'client-provided', 'stock', 'creative-commons', 'unknown'] = 'unknown'
    language: Literal['', 'en', 'ar', 'ar-BH'] = ''
    tags: list[Short] = Field(default=[], max_length=50)
    concept_id: Id | None = None
    parent_asset_id: Id | None = None
    license_id: Id | None = None
    generation_note: GenerationNote | None = None
    notes: Text = ''


class Register(AssetMeta):
    name: str = Field('', max_length=160)
    media_url: str = Field('', max_length=500)
    video_asset_id: str = Field('', pattern=r'^(?:[a-f0-9]{32})?$')
    project_id: Id | None = None
    campaign_id: Id | None = None


@router.post('/clients/{client_id}/assets/register', status_code=201)
def register_asset(client_id: Id, body: Register):
    if bool(body.media_url) == bool(body.video_asset_id):
        raise HTTPException(400, 'Give either an application media URL or a Video Studio asset ID')
    meta = body.model_dump(mode='json', exclude={'name', 'media_url', 'video_asset_id', 'project_id', 'campaign_id'})
    if meta['asset_type'] is None:
        meta.pop('asset_type')
    return guard(assets.register, client_id, body.name, body.media_url, body.video_asset_id, body.project_id, body.campaign_id, meta)


class NewVersion(Strict):
    expected_version: int = Field(ge=1)
    media_url: str = Field('', max_length=500)
    video_asset_id: str = Field('', pattern=r'^(?:[a-f0-9]{32})?$')


@router.post('/clients/{client_id}/assets/{asset_id}/version')
def asset_version(client_id: Id, asset_id: Id, body: NewVersion):
    if bool(body.media_url) == bool(body.video_asset_id):
        raise HTTPException(400, 'Give either an application media URL or a Video Studio asset ID')
    return guard(assets.new_version, client_id, asset_id, body.expected_version, body.media_url, body.video_asset_id)


@router.get('/clients/{client_id}/assets/{asset_id}/file')
def asset_file(client_id: Id, asset_id: Id, version: int | None = Query(None, ge=1), download: bool = False):
    path, name, mime = guard(assets.version_file, client_id, asset_id, version)
    return FileResponse(path, media_type=mime, filename=name if download else None,
                        headers={'Content-Security-Policy': "default-src 'none'; sandbox"})


class ApprovalRequest(Strict):
    target_id: Id
    reviewer: Short = Field(min_length=1)
    due_date: Date | None = None
    note: Text = ''


@router.post('/clients/{client_id}/approvals', status_code=201)
def request_approval(client_id: Id, body: ApprovalRequest):
    return guard(assets.request_approval, client_id, body.target_id, body.reviewer,
                 body.due_date.isoformat() if body.due_date else None, body.note)


@router.get('/clients/{client_id}/approvals')
def approvals(client_id: Id, state: Literal['review-requested', 'changes-requested', 'approved', 'rejected', 'superseded'] | None = None,
              limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000)):
    return guard(assets.review_queue, client_id, state, limit, offset)


class Comment(Strict):
    expected_version: int = Field(ge=1)
    author: Short = Field(min_length=1)
    text: Text = Field(min_length=1)
    timecode_seconds: float | None = Field(None, ge=0, le=86400)


@router.post('/clients/{client_id}/approvals/{approval_id}/comments')
def approval_comment(client_id: Id, approval_id: Id, body: Comment):
    return guard(assets.comment, client_id, approval_id, body.expected_version, body.author, body.text, body.timecode_seconds)


class Decision(Strict):
    expected_version: int = Field(ge=1)
    decision: Literal['approved', 'changes-requested', 'rejected']
    reviewer: Short = Field(min_length=1)
    text: Text = ''


@router.post('/clients/{client_id}/approvals/{approval_id}/decision')
def approval_decision(client_id: Id, approval_id: Id, body: Decision):
    return guard(assets.decide, client_id, approval_id, body.expected_version, body.decision, body.reviewer, body.text)


@router.get('/clients/{client_id}/record/{record_id}/approval-state')
def approval_state(client_id: Id, record_id: Id):
    def read():
        from .database import repository
        with repository.connection() as db:
            record = repository.record(db, client_id, record_id, include_archived=True)
            return dict(record_id=record_id, version=record['version'], state=assets.approval_state(db, repository, client_id, record))
    return guard(read)


@router.get('/clients/{client_id}/calendar/{entry_id}/package')
def publication_package(client_id: Id, entry_id: Id, draft: bool = True):
    path, cleared = guard(assets.publication_package, client_id, entry_id, draft)
    name = 'publication-package.zip' if cleared and not draft else 'publication-package-DRAFT.zip'
    return FileResponse(path, filename=name, media_type='application/zip')


@router.get('/clients/{client_id}/schedule')
def schedule(client_id: Id, campaign_id: Id | None = None, start: Date | None = None, end: Date | None = None):
    def read():
        from .services import service
        items = service.list(client_id, 'calendar', campaign_id=campaign_id, limit=500)['items']
        low, high = (start.isoformat() if start else ''), (end.isoformat() if end else '9999')
        items = [i for i in items if low <= i['data']['scheduled_date'] <= high]
        items.sort(key=lambda i: (i['data']['scheduled_date'], i['data']['scheduled_time']))
        return dict(items=items, total=len(items),
                    note='Planning dates only. Nothing is scheduled or posted on an external platform.')
    return guard(read)


@router.post('/clients/{client_id}/analytics/import', status_code=201)
def analytics_import(client_id: Id, campaign_id: Id | None = None, file: UploadFile = File(...)):
    try:
        return guard(analytics.import_csv, client_id, file, campaign_id)
    finally:
        file.file.close()


@router.get('/clients/{client_id}/analytics/summary')
def analytics_summary(client_id: Id, campaign_id: Id | None = None, start: Date | None = None, end: Date | None = None):
    return guard(analytics.summary, client_id, campaign_id, None,
                 start.isoformat() if start else None, end.isoformat() if end else None)


@router.get('/clients/{client_id}/reports/{report_id}/render')
def render_report(client_id: Id, report_id: Id):
    return FileResponse(guard(analytics.render_report, client_id, report_id), filename='report.zip', media_type='application/zip')


@router.get('/clients/{client_id}/overview')
def overview(client_id: Id):
    return guard(analytics.overview, client_id)
