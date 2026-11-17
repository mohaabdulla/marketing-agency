"""FastAPI router endpoints for Campaign Command Center, Model Registry, Document Vault,
Creative Evaluation, Audio Studio, Connectors, and Client Review Portal.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import HTTPException, Query, File, UploadFile, Body, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .api import router, guard
from .schemas import Id
from .model_registry import registry as model_registry
from .orchestrator import orchestrator
from .documents import document_vault
from .creative_eval import evaluator
from .tts import tts_engine
from .music import music_engine
from .connectors import connector_registry, package_builder
from .tracking import UTMParameters, parse_analytics_csv
from .portal import (
    create_client_review_link,
    get_review_portal_data,
    submit_review_decision,
    revoke_review_link,
    generate_billing_summary,
)


# Pydantic Schemas for Request Payloads
class AdvanceStageRequest(BaseModel):
    target_stage: str


class CreativeEvalRequest(BaseModel):
    headline: str
    body: str
    channel: str = "linkedin"
    language: str = "en"
    prohibited_terms: Optional[List[str]] = None
    mandatory_terms: Optional[List[str]] = None
    cta_required: bool = True
    disclosures_required: Optional[List[str]] = None


class TTSGenerateRequest(BaseModel):
    text: str
    voice_id: str = "af_sarah"
    speed: float = 1.0
    commercial_mode: bool = True


class MusicGenerateRequest(BaseModel):
    prompt: str = "Inspiring corporate background"
    genre: str = "Corporate Ambient"
    mood: str = "Inspiring / Authoritative"
    duration_seconds: float = 15.0
    bpm: int = 120
    model_id: str = "ace-step-v1"
    commercial_mode: bool = True


class ConnectorTestRequest(BaseModel):
    credentials: Dict[str, Any]


class UTMBuildRequest(BaseModel):
    base_url: str = Field(max_length=2000)
    source: str = Field(max_length=200)
    medium: str = Field(max_length=200)
    campaign: str = Field(max_length=200)
    content: Optional[str] = Field(None, max_length=200)
    term: Optional[str] = Field(None, max_length=200)
    id: Optional[str] = Field(None, max_length=100)
    source_platform: Optional[str] = Field(None, max_length=100)
    creative_format: Optional[str] = Field(None, max_length=100)
    marketing_tactic: Optional[str] = Field(None, max_length=100)


class ReviewLinkCreateRequest(BaseModel):
    campaign_id: str
    asset_ids: List[str]
    expires_in_days: int = 7


class ReviewLinkRevokeRequest(BaseModel):
    token: str = Field(min_length=20, max_length=100)


class ReviewDecisionRequest(BaseModel):
    reviewer_name: str
    decision: str
    comments: str = ""
    asset_id: Optional[str] = None


# 1. SYSTEM CAPABILITIES & MODEL REGISTRY
@router.get("/system/capabilities")
def get_system_capabilities():
    return guard(model_registry.probe_system_capabilities)


@router.get("/models")
def list_models(task: Optional[str] = None, commercial_only: bool = False):
    return guard(lambda: model_registry.list_models(task=task, commercial_only=commercial_only))


@router.post("/models/{model_id}/gate-check")
def check_model_gate(model_id: str, mode: str = Query("commercial")):
    return guard(lambda: model_registry.check_license_gate(model_id, mode))


# 2. CAMPAIGN COMMAND CENTER
@router.get("/clients/{client_id}/campaigns/{campaign_id}/command-center")
def get_campaign_command_center(client_id: Id, campaign_id: Id):
    def run():
        from server import RENDERS_DIR
        from .enterprise_pipeline import completed_runs
        data=orchestrator.get_campaign_command_center(client_id,campaign_id)
        data['generated_campaigns']=completed_runs(RENDERS_DIR.published(),client_id,campaign_id)
        return data
    return guard(run)


@router.post('/clients/{client_id}/campaigns/{campaign_id}/generate')
async def generate_campaign_kit(client_id: Id, campaign_id: Id, request: Request, payload: dict=Body(...)):
    from starlette.concurrency import run_in_threadpool
    from pydantic import ValidationError
    from .services import service
    from server import GenerateRequest,run_enterprise_campaign
    # Resolve ownership before starting any production work.
    await run_in_threadpool(lambda:guard(lambda:service.get(client_id,campaign_id,'campaigns')))
    try:
        req=GenerateRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422,exc.errors(include_context=False)) from exc
    return await run_enterprise_campaign(req,request,dict(client_id=client_id,campaign_id=campaign_id))


@router.get("/clients/{client_id}/campaigns/{campaign_id}/readiness")
def get_campaign_readiness(client_id: Id, campaign_id: Id):
    def run():
        data = orchestrator.get_campaign_command_center(client_id, campaign_id)
        return data.get("readiness")
    return guard(run)


@router.get("/clients/{client_id}/campaigns/{campaign_id}/risks")
def get_campaign_risks(client_id: Id, campaign_id: Id):
    def run():
        data = orchestrator.get_campaign_command_center(client_id, campaign_id)
        return {"risks": data.get("risks", [])}
    return guard(run)


@router.post("/clients/{client_id}/campaigns/{campaign_id}/advance")
def advance_campaign_stage(client_id: Id, campaign_id: Id, req: AdvanceStageRequest):
    return guard(lambda: orchestrator.advance_stage(client_id, campaign_id, req.target_stage))


# 3. RESEARCH DOCUMENT VAULT & EVIDENCE
@router.post("/clients/{client_id}/documents/upload", status_code=201)
def upload_research_document(client_id: Id, file: UploadFile = File(...)):
    def run():
        data = file.file.read()
        return document_vault.ingest_bytes(
            client_id=client_id,
            filename=file.filename or "uploaded_doc",
            data=data,
            mime_type=file.content_type,
        )
    return guard(run)


@router.get("/clients/{client_id}/documents")
def list_research_documents(client_id: Id):
    return guard(lambda: document_vault.list_documents(client_id))


@router.get("/clients/{client_id}/documents/{document_id}/chunks")
def get_document_chunks(client_id: Id, document_id: str):
    def run():
        doc = document_vault.get_document(client_id, document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"document_id": document_id, "chunks": doc.get("chunks", [])}
    return guard(run)


# 4. CREATIVE EVALUATION LAYER
@router.post("/creative-eval/check")
def check_creative_evaluation(req: CreativeEvalRequest):
    return guard(lambda: evaluator.evaluate_copy(
        headline=req.headline,
        body=req.body,
        channel=req.channel,
        language=req.language,
        prohibited_terms=req.prohibited_terms,
        mandatory_terms=req.mandatory_terms,
        cta_required=req.cta_required,
        disclosures_required=req.disclosures_required,
    ).to_dict())


# 5. AUDIO STUDIO (TTS & MUSIC)
@router.get("/audio/tts/voices")
def list_tts_voices(language: Optional[str] = None, commercial_only: bool = True):
    return guard(lambda: tts_engine.list_voices(language=language, commercial_only=commercial_only))


@router.post("/audio/tts/generate")
def generate_tts_voiceover(req: TTSGenerateRequest):
    return guard(lambda: tts_engine.generate_voiceover(
        text=req.text,
        voice_id=req.voice_id,
        speed=req.speed,
        commercial_mode=req.commercial_mode,
    ))


@router.post("/audio/music/generate")
def generate_soundtrack(req: MusicGenerateRequest):
    return guard(lambda: music_engine.generate_soundtrack(
        prompt=req.prompt,
        genre=req.genre,
        mood=req.mood,
        duration_seconds=req.duration_seconds,
        bpm=req.bpm,
        model_id=req.model_id,
        commercial_mode=req.commercial_mode,
    ))


# 6. CONNECTORS & PUBLICATION PACKAGE
@router.get("/connectors")
def list_connectors():
    return guard(connector_registry.list_connectors)


@router.post("/connectors/{connector_id}/test")
def test_connector(connector_id: str, req: ConnectorTestRequest):
    return guard(lambda: connector_registry.test_connection(connector_id, req.credentials))


@router.post("/clients/{client_id}/campaigns/{campaign_id}/export-package")
def export_publication_package(client_id: Id, campaign_id: Id):
    def run():
        zip_bytes, filename = package_builder.build_package(client_id, campaign_id)
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    return guard(run)


# 7. TRACKING & ANALYTICS
@router.post("/tracking/build-utm")
def build_utm_url(req: UTMBuildRequest):
    def run():
        utm = UTMParameters(**req.model_dump(exclude={'base_url'}))
        url = utm.build_url(req.base_url)
        return {"url": url, "parameters": utm.normalized(), "warnings": utm.warnings()}
    return guard(run)


@router.post("/analytics/import-csv")
def import_analytics_csv(csv_text: str = Body(..., media_type="text/plain")):
    return guard(lambda: parse_analytics_csv(csv_text))


# 8. CLIENT REVIEW PORTAL & BILLING
@router.post("/clients/{client_id}/review-links")
def create_review_link(client_id: Id, req: ReviewLinkCreateRequest):
    return guard(lambda: create_client_review_link(
        client_id=client_id,
        campaign_id=req.campaign_id,
        asset_ids=req.asset_ids,
        expires_in_days=req.expires_in_days,
    ))


@router.get("/review-links/{token}")
def get_review_portal(token: str):
    return guard(lambda: get_review_portal_data(token))


@router.post("/review-links/{token}/review")
def submit_portal_review(token: str, req: ReviewDecisionRequest):
    return guard(lambda: submit_review_decision(
        token=token,
        reviewer_name=req.reviewer_name,
        decision=req.decision,
        comments=req.comments,
        asset_id=req.asset_id,
    ))


@router.post("/clients/{client_id}/review-links/revoke")
def revoke_review(client_id: Id, req: ReviewLinkRevokeRequest):
    return guard(lambda: revoke_review_link(client_id, req.token))


@router.get("/clients/{client_id}/campaigns/{campaign_id}/billing")
def get_billing_summary(client_id: Id, campaign_id: Id):
    return guard(lambda: generate_billing_summary(client_id, campaign_id))

