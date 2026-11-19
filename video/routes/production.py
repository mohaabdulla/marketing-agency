"""Separate, local-only producer workflow. Existing generation/editing routes retain their contracts."""
from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse
from video import production as service
from video.production_schemas import (ProductionCreate,ShotUpdate,ScriptApproval,CandidateRequest,GateRequest,
    ProductionRender,Versioned,ReleaseRequest)
from video.routes.common import guard as ordinary_guard

router=APIRouter()


def guard(function,*args):
    def run():
        try:return function(*args)
        except service.ProductionConflict as exc:raise HTTPException(409,str(exc)) from exc
    return ordinary_guard(run)


@router.get('/productions')
def productions():return guard(service.listings)


@router.post('/productions',status_code=201)
def create(body:ProductionCreate):return guard(service.create,body)


@router.get('/productions/{key}')
def get(key:str):return guard(service.get,key)


@router.put('/productions/{key}/shots/{shot_id}')
def update_shot(key:str,shot_id:str,body:ShotUpdate):return guard(service.update_shot,key,shot_id,body)


@router.post('/productions/{key}/approve-script')
def approve_script(key:str,body:ScriptApproval):return guard(service.approve_script,key,body)


@router.post('/productions/{key}/shots/{shot_id}/generate',status_code=202)
def candidate(key:str,shot_id:str,body:CandidateRequest):return guard(service.generate_candidate,key,shot_id,body)


@router.post('/productions/{key}/shots/{shot_id}/review')
def review(key:str,shot_id:str,body:GateRequest):return guard(service.approve_candidate,key,shot_id,body)


@router.post('/productions/{key}/check')
def check(key:str):return guard(service.check,key)


@router.post('/productions/{key}/reset-timeline')
def reset(key:str,body:Versioned):return guard(service.reset_timeline,key,body)


@router.post('/productions/{key}/render',status_code=202)
def render(key:str,body:ProductionRender):return guard(service.render_master,key,body)


@router.post('/productions/{key}/release',status_code=202)
def release(key:str,body:ReleaseRequest):return guard(service.release,key,body)


@router.get('/productions/{key}/delivery/{kind}')
def delivery(key:str,kind:str):
    path=guard(service.delivery_file,key,kind)
    return FileResponse(path,filename=f'VIDEO_{key}_{kind}'+path.suffix,media_type='application/zip' if kind=='zip' else 'video/mp4')
