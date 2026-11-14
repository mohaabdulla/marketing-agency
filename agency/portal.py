"""Client Review Portal, Expiring Shareable Links, and Billing Operations for LEXNIS Agency."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from .database import NotFound, Conflict
from .services import service


# In-memory / persistent review link store
REVIEW_LINKS: Dict[str, Dict[str, Any]] = {}


def create_client_review_link(
    client_id: str,
    campaign_id: str,
    asset_ids: List[str],
    expires_in_days: int = 7
) -> Dict[str, Any]:
    """Generate a scoped, expiring review token for external client sign-off."""
    campaign = service.get(client_id, campaign_id, "campaigns")
    if not campaign:
        raise NotFound(f"Campaign '{campaign_id}' not found")

    camp_name = campaign.get("name") or campaign.get("data", {}).get("name", "Campaign")
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()

    link_data = {
        "token": token,
        "client_id": client_id,
        "campaign_id": campaign_id,
        "campaign_name": camp_name,
        "asset_ids": asset_ids,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
        "status": "ACTIVE",
        "feedback": [],
    }

    REVIEW_LINKS[token] = link_data
    return {
        "token": token,
        "review_url": f"/review/{token}",
        "expires_at": expires_at,
        "asset_count": len(asset_ids),
    }


def get_review_portal_data(token: str) -> Dict[str, Any]:
    """Retrieve scoped review data. Strictly omits internal margins, prompts, or filesystem paths."""
    link = REVIEW_LINKS.get(token)
    if not link:
        raise NotFound("Review link not found or invalid.")

    # Check expiration
    now = datetime.now(timezone.utc).isoformat()
    if link["expires_at"] < now or link["status"] == "REVOKED":
        raise Conflict("This client review link has expired or been revoked.")

    client_id = link["client_id"]
    with service.repo.connection() as db:
        client = service.repo.client(db, client_id)

    # Gather safe asset preview metadata
    safe_assets = []
    for aid in link["asset_ids"]:
        try:
            a = service.get(client_id, aid, "assets")
            adata = a.get("data", {})
            safe_assets.append({
                "id": a["id"],
                "version": a.get("version", 1),
                "type": adata.get("type", "image"),
                "headline": adata.get("headline", ""),
                "url": adata.get("url") or f"/static/assets/{a['id']}.jpg",
            })
        except Exception:
            continue

    return {
        "token": token,
        "client_name": client.get("name", "Client"),
        "campaign_name": link["campaign_name"],
        "assets": safe_assets,
        "expires_at": link["expires_at"],
        "feedback_history": link["feedback"],
    }


def submit_review_decision(
    token: str,
    reviewer_name: str,
    decision: str,  # "APPROVED" or "CHANGES_REQUESTED"
    comments: str = "",
    asset_id: Optional[str] = None
) -> Dict[str, Any]:
    """Submit approval or change request via review token."""
    link = REVIEW_LINKS.get(token)
    if not link:
        raise NotFound("Invalid review link")

    if decision not in {"APPROVED", "CHANGES_REQUESTED"}:
        raise ValueError("Decision must be either APPROVED or CHANGES_REQUESTED")

    feedback_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reviewer_name": reviewer_name,
        "decision": decision,
        "comments": comments,
        "asset_id": asset_id,
    }
    link["feedback"].append(feedback_entry)

    return {
        "success": True,
        "decision": decision,
        "feedback_entry": feedback_entry,
    }


def generate_billing_summary(client_id: str, campaign_id: str) -> Dict[str, Any]:
    """Calculate transparent agency quote & invoice items."""
    campaign = service.get(client_id, campaign_id, "campaigns")
    cdata = campaign.get("data", {}) if campaign else {}

    planned_budget = float(cdata.get("budget", 5000.0))

    items = [
        {"item": "Campaign Architecture & Strategy", "hours": 12, "rate": 150.0, "amount": 1800.0},
        {"item": "Creative Direction & Production (Local AI Studio)", "hours": 20, "rate": 120.0, "amount": 2400.0},
        {"item": "Bilingual Copywriting & Localized Assets", "hours": 8, "rate": 100.0, "amount": 800.0},
        {"item": "Compliance, Claims Verification & Rights Clearance", "hours": 4, "rate": 150.0, "amount": 600.0},
    ]

    subtotal = sum(i["amount"] for i in items)
    tax = round(subtotal * 0.05, 2)  # 5% standard VAT
    total = round(subtotal + tax, 2)

    return {
        "client_id": client_id,
        "campaign_id": campaign_id,
        "currency": "USD",
        "invoice_number": f"INV-{datetime.now().strftime('%Y%m')}-{campaign_id[:6].upper()}",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "line_items": items,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "planned_ad_spend": planned_budget,
    }
