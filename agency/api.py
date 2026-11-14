"""Local agency API; existing image/video endpoint formats are unchanged."""
import json
import logging
import sqlite3
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError, Field
from .database import repository, NotFound, Conflict, packed
from .schemas import Client, ClientUpdate, MODELS, RecordInput, RecordUpdate, Strict, Id, Locale
from .services import service
from .security import local_operator
from .compliance import scan
from .jobs import queue
from .research import import_file, capture
from .exports import brief_from_strategy, campaign_plan, backup_bundle
from .local_text import status as text_status,draft_brief,DraftRequest
from .production_schemas import SERVER_MANAGED

router=APIRouter(prefix='/api/agency',tags=['agency'],dependencies=[Depends(local_operator)])
log=logging.getLogger('lexnis.agency')


@router.on_event('startup')
def startup():
    repository.initialize()
    queue.recover()


def guard(fn,*args,**kwargs):
    try:
        return fn(*args,**kwargs)
    except NotFound as exc:
        raise HTTPException(404,str(exc))
    except Conflict as exc:
        raise HTTPException(409,str(exc))
    except ValidationError as exc:
        raise HTTPException(422,exc.errors(include_input=False,include_context=False))
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    except sqlite3.OperationalError:
        raise HTTPException(503,'Agency storage is busy or unavailable; retry shortly')
    except Exception:
        trace=uuid.uuid4().hex
        log.exception('Agency operation failed; trace=%s',trace)
        raise HTTPException(500,dict(message='Agency operation failed',trace_id=trace))


@router.get('/health')
def health():
    guard(repository.initialize)
    return dict(schema_version=1,mode='local-operator',network='loopback-only',paid_provider_required=False)


@router.get('/schemas')
def schemas():
    return dict(client=Client.model_json_schema(),records={key:model.model_json_schema() for key,model in MODELS.items()})


@router.get('/dashboard')
def dashboard(client_id: Id | None=None):
    return guard(service.dashboard,client_id)


@router.get('/clients')
def clients(limit:int=Query(25,ge=1,le=100),offset:int=Query(0,ge=0,le=100000),q:str=Query('',max_length=200),archived:bool=False):
    return guard(repository.clients,limit,offset,q,archived)


@router.post('/clients',status_code=201)
def create_client(body:Client):
    return guard(repository.save_client,body.model_dump(mode='json'))


@router.get('/clients/{client_id}')
def get_client(client_id:Id):
    def get():
        with repository.connection() as db:
            return repository.client(db,client_id)
    return guard(get)


@router.put('/clients/{client_id}')
def update_client(client_id:Id,body:ClientUpdate):
    return guard(repository.save_client,body.model_dump(mode='json',exclude={'expected_version'}),client_id,body.expected_version)


@router.get('/clients/{client_id}/records')
def records(client_id:Id,kind:str|None=None,project_id:Id|None=None,campaign_id:Id|None=None,
            limit:int=Query(25,ge=1,le=100),offset:int=Query(0,ge=0,le=100000),
            q:str=Query('',max_length=200),archived:bool=False,summary:bool=False):
    return guard(service.list,client_id,kind,project_id=project_id,campaign_id=campaign_id,
                 limit=limit,offset=offset,query=q,include_archived=archived,summary=summary)


@router.post('/clients/{client_id}/records/{kind}',status_code=201)
def create_record(client_id:Id,kind:str,body:RecordInput):
    if kind in SERVER_MANAGED:
        raise HTTPException(400,'This record type is created by its own workflow (register an asset, or request an approval)')
    if kind=='briefs' and body.data.get('generation') is not None:
        raise HTTPException(400,'Generation provenance is created by the local model worker, not by manual record creation')
    return guard(service.save,client_id,kind,body)


@router.get('/clients/{client_id}/record/{record_id}')
def get_record(client_id:Id,record_id:Id):
    return guard(service.get,client_id,record_id)


@router.put('/clients/{client_id}/records/{kind}/{record_id}')
def update_record(client_id:Id,kind:str,record_id:Id,body:RecordUpdate):
    if kind=='approvals':
        raise HTTPException(400,'Approvals change only through review comments and decisions')
    if kind=='briefs':
        old=guard(service.get,client_id,record_id,'briefs')
        if body.data.get('generation')!=old['data'].get('generation'):
            raise HTTPException(400,'Recorded generation provenance is immutable; edit the draft content instead')
    return guard(service.save,client_id,kind,body,record_id,body.expected_version)


class Archive(Strict):
    expected_version:int=Field(ge=1)
    archived:bool=True


@router.post('/clients/{client_id}/record/{record_id}/archive')
def archive(client_id:Id,record_id:Id,body:Archive):
    return guard(service.archive,client_id,record_id,body.expected_version,body.archived)


@router.get('/clients/{client_id}/history/{record_id}')
def history(client_id:Id,record_id:Id,limit:int=Query(25,ge=1,le=100),offset:int=Query(0,ge=0,le=100000)):
    return guard(repository.revisions,client_id,record_id,limit,offset)


@router.get('/clients/{client_id}/audit')
def audit(client_id:Id,limit:int=Query(25,ge=1,le=100),offset:int=Query(0,ge=0,le=100000)):
    def read():
        with repository.connection() as db:
            repository.client(db,client_id)
            total=db.execute('SELECT count(*) FROM audit WHERE client_id=?',(client_id,)).fetchone()[0]
            items=[dict(row,details=json.loads(row['details'])) for row in db.execute(
                'SELECT * FROM audit WHERE client_id=? ORDER BY id DESC LIMIT ? OFFSET ?',(client_id,limit,offset))]
            return dict(items=items,total=total,limit=limit,offset=offset)
    return guard(read)


@router.get('/clients/{client_id}/calendar')
def calendar(client_id:Id,campaign_id:Id|None=None,limit:int=Query(25,ge=1,le=100),offset:int=Query(0,ge=0,le=100000)):
    return guard(service.calendar,client_id,campaign_id,limit,offset)


class Scan(Strict):
    text:str=Field(max_length=30000)
    claim_ids:list[Id]=Field(default=[],max_length=50)
    brand_id:Id|None=None
    cta:str=Field('',max_length=250)
    language:Locale='en'


@router.post('/clients/{client_id}/checks')
def checks(client_id:Id,body:Scan):
    return guard(scan,client_id,**body.model_dump())


@router.get('/legacy-brands')
def legacy_brands():
    from brand_kits import list_brands
    return dict(items=guard(list_brands),migration='Copy a selected legacy brand into an explicitly chosen client; originals remain unchanged.')


@router.post('/backups',status_code=201)
def backup():
    return guard(backup_bundle)


@router.get('/backups/{backup_id}/download')
def download_backup(backup_id:Id):
    repository.initialize()
    path=repository.home/'backups'/(backup_id+'.zip')
    if not path.is_file():
        raise HTTPException(404,'Backup not found')
    return FileResponse(path,filename='lexnis-agency-backup.zip',media_type='application/zip')


@router.post('/clients/{client_id}/research/import',status_code=201)
def research_import(client_id:Id,file:UploadFile=File(...)):
    try:
        return guard(import_file,client_id,file)
    finally:
        file.file.close()


@router.get('/clients/{client_id}/documents/{document_id}')
def research_document(client_id:Id,document_id:Id):
    def lookup():
        with repository.connection() as db:
            repository.client(db,client_id)
            row=db.execute('SELECT * FROM documents WHERE id=? AND client_id=?',(document_id,client_id)).fetchone()
            if not row:
                raise NotFound('Document not found in this client')
            path=repository.home/'documents'/row['filename']
            if path.parent!=repository.home/'documents' or not path.is_file():
                raise NotFound('Document file not found')
            return FileResponse(path,filename=row['original_name'],media_type='application/octet-stream')
    return guard(lookup)


class Capture(Strict):
    expected_version:int=Field(ge=1)
    terms_reviewed:bool


@router.post('/clients/{client_id}/sources/{source_id}/capture',status_code=202)
def capture_source(client_id:Id,source_id:Id,body:Capture):
    if not body.terms_reviewed:
        raise HTTPException(400,'Review the site terms and your configured research policy before capture')
    source=guard(service.get,client_id,source_id,'sources')
    from .research import target
    guard(target,source['data']['url'])
    return guard(queue.submit,client_id,'research-capture',
                 lambda task:capture(client_id,source_id,body.expected_version,task),target_id=source_id)


@router.get('/clients/{client_id}/jobs/{job_id}')
def job(client_id:Id,job_id:Id):
    return guard(queue.get,client_id,job_id)


@router.post('/clients/{client_id}/jobs/{job_id}/cancel')
def cancel_job(client_id:Id,job_id:Id):
    return guard(queue.cancel,client_id,job_id)


@router.post('/clients/{client_id}/campaigns/{campaign_id}/brief',status_code=201)
def build_brief(client_id:Id,campaign_id:Id):
    return guard(brief_from_strategy,client_id,campaign_id)


@router.get('/clients/{client_id}/campaigns/{campaign_id}/package')
def export_plan(client_id:Id,campaign_id:Id,draft_only:bool=True):
    path=guard(campaign_plan,client_id,campaign_id,draft_only)
    return FileResponse(path,filename='campaign-review-plan.zip' if draft_only else 'campaign-plan.zip',media_type='application/zip')


@router.get('/local-text/status')
def local_text_status():
    return guard(text_status)


@router.post('/clients/{client_id}/local-text/draft',status_code=202)
def local_draft(client_id:Id,body:DraftRequest):
    guard(service.get,client_id,body.brief_id,'briefs')
    model=guard(text_status)
    if not model['available']:
        raise HTTPException(409,model['reason'])
    return guard(queue.submit,client_id,'local-text-draft',lambda task:draft_brief(client_id,body,task),target_id=body.brief_id)


# Content, asset, approval, publication-package, analytics and report routes share this router.
from . import api_production, api_acquisition, api_audio, api_privacy, api_planning, api_orchestrator  # noqa: E402,F401
