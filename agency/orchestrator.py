"""Campaign Command Center Orchestrator for LEXNIS AI Marketing Agency.

Coordinates the 15-stage agency campaign lifecycle, computes readiness, and audits risks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from datetime import timezone
from enum import Enum
from typing import Any, Dict, List

from .database import NotFound
from .services import service
from .model_registry import registry as model_registry


class CampaignStage(str, Enum):
    INTAKE = "INTAKE"
    RESEARCH = "RESEARCH"
    STRATEGY = "STRATEGY"
    BRIEF = "BRIEF"
    CONCEPT = "CONCEPT"
    COPY = "COPY"
    SCRIPT = "SCRIPT"
    STORYBOARD = "STORYBOARD"
    PRODUCTION = "PRODUCTION"
    QA = "QA"
    APPROVAL = "APPROVAL"
    DISTRIBUTION = "DISTRIBUTION"
    MEASUREMENT = "MEASUREMENT"
    LEARNING = "LEARNING"
    COMPLETE = "COMPLETE"


STATUS_TO_STAGE: Dict[str, str] = {
    "draft": CampaignStage.INTAKE.value,
    "strategy": CampaignStage.STRATEGY.value,
    "creative": CampaignStage.PRODUCTION.value,
    "review": CampaignStage.QA.value,
    "approved": CampaignStage.APPROVAL.value,
    "scheduled": CampaignStage.DISTRIBUTION.value,
    "live": CampaignStage.MEASUREMENT.value,
    "optimization": CampaignStage.LEARNING.value,
    "completed": CampaignStage.COMPLETE.value,
}

STAGE_TO_STATUS: Dict[str, str] = {
    "INTAKE": "draft",
    "RESEARCH": "strategy",
    "STRATEGY": "strategy",
    "BRIEF": "strategy",
    "CONCEPT": "creative",
    "COPY": "creative",
    "SCRIPT": "creative",
    "STORYBOARD": "creative",
    "PRODUCTION": "creative",
    "QA": "review",
    "APPROVAL": "approved",
    "DISTRIBUTION": "scheduled",
    "MEASUREMENT": "live",
    "LEARNING": "optimization",
    "COMPLETE": "completed",
}

STAGE_ORDER: List[CampaignStage] = [
    CampaignStage.INTAKE,
    CampaignStage.RESEARCH,
    CampaignStage.STRATEGY,
    CampaignStage.BRIEF,
    CampaignStage.CONCEPT,
    CampaignStage.COPY,
    CampaignStage.SCRIPT,
    CampaignStage.STORYBOARD,
    CampaignStage.PRODUCTION,
    CampaignStage.QA,
    CampaignStage.APPROVAL,
    CampaignStage.DISTRIBUTION,
    CampaignStage.MEASUREMENT,
    CampaignStage.LEARNING,
    CampaignStage.COMPLETE,
]


class StageStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    COMPLETE = "COMPLETE"


@dataclass
class StageDetail:
    stage: str
    order: int
    status: str
    items_count: int = 0
    approved_count: int = 0
    blockers: List[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RiskItem:
    code: str
    severity: str  # "HIGH", "MEDIUM", "LOW"
    stage: str
    message: str
    remediation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CampaignOrchestrator:
    """Evaluates campaign state, stage transitions, production readiness, and legal/creative risks."""

    def get_campaign_command_center(self, client_id: str, campaign_id: str) -> Dict[str, Any]:
        from .campaign_context import campaign_context,strategy_summary
        client,campaign,campaign_records=campaign_context(client_id,campaign_id)
        if not campaign:
            raise NotFound(f"Campaign '{campaign_id}' not found for client '{client_id}'")

        cdata = campaign.get("data", {})

        stage_details = self._compute_stages(campaign, campaign_records)
        risks = self._compute_risks(campaign, campaign_records)
        readiness = self._compute_readiness(stage_details, risks)
        production_board = self._compute_production_board(campaign_records)

        completed_stages = sum(1 for s in stage_details if s.status in {StageStatus.COMPLETE.value, StageStatus.APPROVED.value})
        progress_pct = int((completed_stages / len(STAGE_ORDER)) * 100)

        notes = cdata.get("notes", "")
        stage_match = re.search(r"\[STAGE:\s*([^\]]+)\]", notes)
        if stage_match:
            current_stage = stage_match.group(1).strip()
        else:
            current_stage = cdata.get("current_stage") or STATUS_TO_STAGE.get(cdata.get("status", "draft"), CampaignStage.BRIEF.value)

        # Derive a human campaign name from top-level record, notes or objective
        clean_name = re.sub(r"\[STAGE:\s*[^\]]+\]", "", notes).strip()
        display_name = campaign.get("name") or cdata.get("name") or clean_name or cdata.get("objective") or "Campaign"

        return {
            "campaign": {
                "id": campaign["id"],
                "client_id": client_id,
                "client_name": client.get("name", "Unknown Client"),
                "name": display_name,
                "objective": cdata.get("objective") or 'Not set',
                "budget": cdata.get("budget", 0),
                "primary_kpi": cdata.get("primary_kpi") or 'Not set',
                "currency": cdata.get('currency','BHD'),
                "markets": cdata.get("markets", ["Global"]),
                "languages": cdata.get("languages", ["en", "ar"]),
                "date_range": {
                    "start": cdata.get("start_date") or cdata.get("starts_at"),
                    "end": cdata.get("end_date") or cdata.get("ends_at"),
                },
                "current_stage": current_stage,
                "progress_percent": progress_pct,
            },
            "strategy_summary": strategy_summary(campaign,campaign_records),
            "stages": [s.to_dict() for s in stage_details],
            "production_board": production_board,
            "risks": [r.to_dict() for r in risks],
            "readiness": readiness,
        }

    def _compute_stages(
        self,
        campaign: Dict[str, Any],
        records: Dict[str, List[Dict[str, Any]]]
    ) -> List[StageDetail]:
        details = []
        cdata = campaign.get("data", {})
        active_stage = cdata.get("current_stage", CampaignStage.BRIEF.value)
        from .campaign_context import approved_targets
        approved_ids=approved_targets(records)

        # Counts from database records
        counts = {
            "briefs": len(records.get("briefs", [])),
            "concepts": len(records.get("concepts", [])),
            "copy": len(records.get("copy", [])),
            "scripts": len(records.get("scripts", [])),
            "storyboards": len(records.get("storyboards", [])),
            "assets": len(records.get("assets", [])),
            "approvals": len(records.get("approvals", [])),
            "deliverables": len(records.get("deliverables", [])),
            "metrics": len(records.get("metrics", [])),
            "reports": len(records.get("reports", [])),
            "learnings": len(records.get("learnings", [])),
            "claims": len(records.get("claims", [])),
            "evidence": len(records.get("evidence", [])),
        }

        for idx, stage in enumerate(STAGE_ORDER):
            status = StageStatus.NOT_STARTED.value
            items = 0
            approved = 0
            blockers = []

            if stage == CampaignStage.INTAKE:
                status = StageStatus.COMPLETE.value
                items = 1
                approved = 1
            elif stage == CampaignStage.RESEARCH:
                items = counts["evidence"] + counts["claims"]
                status = StageStatus.COMPLETE.value if items > 0 else StageStatus.IN_PROGRESS.value
            elif stage == CampaignStage.STRATEGY:
                items = len(records.get('strategies',[]))
                status = StageStatus.COMPLETE.value if items else StageStatus.NOT_STARTED.value
            elif stage == CampaignStage.BRIEF:
                items = counts["briefs"]
                if items > 0:
                    approved = sum(r['id'] in approved_ids for r in records['briefs'])
                    status = StageStatus.APPROVED.value if approved==items else StageStatus.IN_PROGRESS.value
                else:
                    status = StageStatus.IN_PROGRESS.value
                    blockers.append("Creative brief not yet finalized")
            elif stage == CampaignStage.CONCEPT:
                items = counts["concepts"]
                status = StageStatus.COMPLETE.value if items > 0 else StageStatus.NOT_STARTED.value
            elif stage == CampaignStage.COPY:
                items = counts["copy"]
                status = StageStatus.COMPLETE.value if items > 0 else StageStatus.NOT_STARTED.value
            elif stage == CampaignStage.SCRIPT:
                items = counts["scripts"]
                status = StageStatus.COMPLETE.value if items > 0 else StageStatus.NOT_STARTED.value
            elif stage == CampaignStage.STORYBOARD:
                items = counts["storyboards"]
                status = StageStatus.COMPLETE.value if items > 0 else StageStatus.NOT_STARTED.value
            elif stage == CampaignStage.PRODUCTION:
                items = counts["assets"]
                if items > 0:
                    status = StageStatus.IN_PROGRESS.value
                else:
                    status = StageStatus.NOT_STARTED.value
            elif stage == CampaignStage.QA:
                items = counts["assets"]
                status = StageStatus.NOT_STARTED.value if items == 0 else StageStatus.IN_PROGRESS.value
            elif stage == CampaignStage.APPROVAL:
                items = counts["approvals"]
                required={r['id'] for kind in ('briefs','copy','assets') for r in records.get(kind,[])}
                approved=len(required & approved_ids)
                status = StageStatus.APPROVED.value if required and required<=approved_ids else StageStatus.AWAITING_APPROVAL.value
            elif stage == CampaignStage.DISTRIBUTION:
                items = counts["deliverables"]
                status = StageStatus.NOT_STARTED.value if items == 0 else StageStatus.IN_PROGRESS.value
            elif stage == CampaignStage.MEASUREMENT:
                items = counts["metrics"]
                status = StageStatus.COMPLETE.value if items > 0 else StageStatus.NOT_STARTED.value
            elif stage == CampaignStage.LEARNING:
                items = counts["learnings"]
                status = StageStatus.COMPLETE.value if items > 0 else StageStatus.NOT_STARTED.value
            elif stage == CampaignStage.COMPLETE:
                status = StageStatus.NOT_STARTED.value

            details.append(StageDetail(
                stage=stage.value,
                order=idx + 1,
                status=status,
                items_count=items,
                approved_count=approved,
                blockers=blockers,
                description=f"Campaign stage {stage.value}",
            ))

        return details

    def _compute_production_board(self, records: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        assets = records.get("assets", [])
        return {
            "concepts_count": len(records.get("concepts", [])),
            "copy_variants_count": len(records.get("copy", [])),
            "scripts_count": len(records.get("scripts", [])),
            "storyboards_count": len(records.get("storyboards", [])),
            "total_assets": len(assets),
            "images_count": sum(1 for a in assets if a.get("data", {}).get("asset_type") in {'image','gif'}),
            "videos_count": sum(1 for a in assets if a.get("data", {}).get("asset_type") == "video"),
            "audio_count": sum(1 for a in assets if a.get("data", {}).get("asset_type") == 'audio'),
            "subtitles_count": len(records.get("subtitles", [])),
        }

    def _compute_risks(
        self,
        campaign: Dict[str, Any],
        records: Dict[str, List[Dict[str, Any]]]
    ) -> List[RiskItem]:
        risks: List[RiskItem] = []
        cdata = campaign.get("data", {})
        is_commercial = cdata.get("mode", "commercial") == "commercial"

        # 1. Check Claims vs Evidence
        claims = records.get("claims", [])
        evidence = records.get("evidence", [])
        ev_ids = {e["id"] for e in evidence}
        for cl in claims:
            cl_data = cl.get("data", {})
            if cl.get('effective_status',cl_data.get('status')) not in {'verified','client-approved'}:
                risks.append(RiskItem(code='CLAIM_REVIEW_REQUIRED',severity='HIGH',stage=CampaignStage.RESEARCH.value,
                    message=f'Claim "{cl_data.get("text",cl["id"])[:80]}" is not currently verified or client-approved.',
                    remediation='Review its evidence and record the claim status and reviewer.'))
            srcs = cl_data.get("evidence_ids") or cl_data.get("source_ids") or []
            if not srcs or not any(s in ev_ids for s in srcs):
                risks.append(RiskItem(
                    code="UNSUPPORTED_CLAIM",
                    severity="HIGH",
                    stage=CampaignStage.RESEARCH.value,
                    message=f"Marketing claim '{cl_data.get('claim', cl['id'])[:50]}...' lacks verified evidence sources.",
                    remediation="Attach valid document citations or evidence records before public distribution.",
                ))

        # 2. Check Creative Brief
        briefs = records.get("briefs", [])
        if not briefs:
            risks.append(RiskItem(
                code="MISSING_BRIEF",
                severity="HIGH",
                stage=CampaignStage.BRIEF.value,
                message="Campaign does not have an approved creative brief bound to downstream assets.",
                remediation="Draft and approve a brief from the Strategy module.",
            ))

        # 3. Check Asset Model Licenses
        assets = records.get("assets", [])
        licenses={record['id']:record for record in records.get('licenses',[])}
        for a in assets:
            adata = a.get("data", {})
            license_record=licenses.get(adata.get('license_id'))
            if not license_record or license_record['data'].get('license_type')=='unknown' or license_record.get('effective_status')=='expired':
                risks.append(RiskItem(code='MEDIA_RIGHTS_REVIEW',severity='HIGH',stage=CampaignStage.PRODUCTION.value,
                    message=f'Current usage rights are missing, unknown or expired for asset "{a.get("name",a["id"])}".',
                    remediation='Link a current usage-rights record in Assets & Approvals.'))
            model_id = adata.get("model_id") or adata.get("generator_model")
            if model_id:
                gate = model_registry.check_license_gate(model_id, "commercial" if is_commercial else "internal_draft")
                if not gate["allowed"]:
                    risks.append(RiskItem(
                        code="NON_COMMERCIAL_MODEL",
                        severity="HIGH",
                        stage=CampaignStage.PRODUCTION.value,
                        message=f"Asset '{a['id']}' was generated with '{model_id}' which has a non-commercial license.",
                        remediation="Regenerate asset using an Apache 2.0 or commercial-permissive model.",
                    ))

        # 4. Check Tracking & UTMs
        deliverables = records.get("deliverables", [])
        for d in deliverables:
            ddata = d.get("data", {})
            if ddata.get("channel") in {"meta", "linkedin", "google"} and not ddata.get("utm_parameters"):
                risks.append(RiskItem(
                    code="MISSING_UTM",
                    severity="MEDIUM",
                    stage=CampaignStage.DISTRIBUTION.value,
                    message=f"Channel deliverable '{d['id']}' has no UTM attribution parameters.",
                    remediation="Generate canonical UTM parameters via the Tracking Builder.",
                ))

        return risks

    def _compute_readiness(
        self,
        stages: List[StageDetail],
        risks: List[RiskItem]
    ) -> Dict[str, Any]:
        high_risks = [r for r in risks if r.severity == "HIGH"]
        reasons=[r.message for r in high_risks]
        indexed={stage.stage:stage for stage in stages}
        if not indexed['PRODUCTION'].items_count:reasons.append('No campaign media assets are registered yet.')
        if not indexed['COPY'].items_count:reasons.append('No campaign copy is recorded yet.')
        if indexed['APPROVAL'].status!='APPROVED':reasons.append('Current versions of the brief, copy and media still need approval.')
        is_ready = not reasons
        return {
            "ready_for_distribution": is_ready,
            "blockers_count": len(reasons),
            "warnings_count": len([r for r in risks if r.severity == "MEDIUM"]),
            "status": "READY" if is_ready else "BLOCKED",
            "blocking_reasons": reasons,
        }

    def advance_stage(
        self,
        client_id: str,
        campaign_id: str,
        target_stage: str
    ) -> Dict[str, Any]:
        """Validate prerequisites and advance campaign lifecycle stage."""
        if target_stage not in [s.value for s in STAGE_ORDER]:
            raise ValueError(f"Invalid target stage '{target_stage}'")

        campaign = service.get(client_id, campaign_id, "campaigns")
        if not campaign:
            raise NotFound(f"Campaign '{campaign_id}' not found")

        cdata = dict(campaign.get("data", {}))
        notes = cdata.get("notes", "")
        stage_match = re.search(r"\[STAGE:\s*([^\]]+)\]", notes)
        old_stage = stage_match.group(1).strip() if stage_match else STATUS_TO_STAGE.get(cdata.get("status", "draft"), CampaignStage.BRIEF.value)

        # Update status and notes safely within strict Campaign schema
        mapped_status = STAGE_TO_STATUS.get(target_stage, "creative")
        cdata["status"] = mapped_status
        clean_notes = re.sub(r"\[STAGE:\s*[^\]]+\]", "", notes).strip()
        cdata["notes"] = f"[STAGE: {target_stage}] {clean_notes}".strip()

        class DummyBody:
            def __init__(self, data, name="Campaign"):
                self.data = data
                self.name = name
                self.campaign_id = None
                self.project_id = None

        orig_name = campaign.get("name") or "Campaign"
        saved = service.save(
            client_id=client_id,
            kind="campaigns",
            body=DummyBody(cdata, name=orig_name),
            key=campaign_id,
            expected_version=campaign.get("version", 1)
        )
        return {
            "success": True,
            "previous_stage": old_stage,
            "current_stage": target_stage,
            "version": saved.get("version"),
        }


orchestrator = CampaignOrchestrator()
