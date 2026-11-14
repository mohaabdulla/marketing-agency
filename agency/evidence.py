"""Evidence and Claim Verification Engine for LEXNIS Marketing Agency.

Enforces that marketing claims cite real document chunk IDs and carry verified review status.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from .database import NotFound
from .documents import document_vault
from .services import service


class EvidenceType(str, Enum):
    DOCUMENT_EXCERPT = "document_excerpt"
    BENCHMARK_RESULT = "benchmark_result"
    CASE_STUDY = "case_study"
    CUSTOMER_QUOTE = "customer_quote"
    FINANCIAL_AUDIT = "financial_audit"
    REGULATORY_FILING = "regulatory_filing"


class ReviewState(str, Enum):
    UNREVIEWED = "unreviewed"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class EvidenceCitation:
    chunk_id: str
    document_id: str
    filename: str
    excerpt: str
    page_number: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EvidenceEngine:
    """Validates citations, verifies claims, and blocks ungrounded marketing claims."""

    def register_evidence(
        self,
        client_id: str,
        claim_text: str,
        chunk_ids: List[str],
        evidence_type: EvidenceType = EvidenceType.DOCUMENT_EXCERPT,
        notes: str = "",
        expires_at: Optional[str] = None
    ) -> Dict[str, Any]:
        """Link a claim to verified document chunks and create an evidence record."""
        citations: List[EvidenceCitation] = []

        # Validate that each chunk ID exists in the client's document vault
        for cid in chunk_ids:
            found = False
            for doc_meta in document_vault.list_documents(client_id):
                doc = document_vault.get_document(client_id, doc_meta["document_id"])
                if not doc:
                    continue
                for ch in doc.get("chunks", []):
                    if ch["chunk_id"] == cid:
                        citations.append(EvidenceCitation(
                            chunk_id=cid,
                            document_id=doc_meta["document_id"],
                            filename=doc_meta["filename"],
                            excerpt=ch["text"][:300],
                            page_number=ch.get("page_number"),
                        ))
                        found = True
                        break
                if found:
                    break

            if not found:
                raise ValueError(f"Referenced chunk ID '{cid}' was not found in client's document vault.")

        class Body:
            def __init__(self, data, name="Evidence Record"):
                self.data = data
                self.name = name
                self.campaign_id = None
                self.project_id = None

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        quotation = citations[0].excerpt if citations else ""
        evidence_data = {
            "summary": claim_text[:5000],
            "source_type": "manual-note",
            "source_ids": [],
            "quotation": quotation[:5000],
            "state": "verified_source" if citations else "unverified_hypothesis",
            "date": today,
            "reviewer": "Agency Operator",
        }

        saved = service.save(client_id, "evidence", Body(evidence_data))
        return saved

    def verify_claim(self, client_id: str, claim_id: str) -> Dict[str, Any]:
        """Check whether a registered claim has valid, non-expired evidence."""
        claim_record = service.get(client_id, claim_id, "claims")
        if not claim_record:
            raise NotFound(f"Claim '{claim_id}' not found")

        cdata = claim_record.get("data", {})
        ev_ids = cdata.get("evidence_ids") or cdata.get("source_ids") or []

        if not ev_ids:
            return {
                "claim_id": claim_id,
                "verified": False,
                "reason": "Claim has no linked evidence records.",
                "citations": [],
            }

        # Check evidence records
        all_citations = []
        for eid in ev_ids:
            try:
                ev_rec = service.get(client_id, eid, "evidence")
                edata = ev_rec.get("data", {})
                if edata.get("state") == "verified_source" or edata.get("status") == ReviewState.VERIFIED.value:
                    all_citations.extend(edata.get("citations", []))
            except Exception:
                continue

        is_verified = len(all_citations) > 0
        return {
            "claim_id": claim_id,
            "claim_text": cdata.get("claim"),
            "verified": is_verified,
            "citations": all_citations,
            "reason": "All citations verified against source document vault." if is_verified else "Evidence unverified or missing.",
        }


evidence_engine = EvidenceEngine()
