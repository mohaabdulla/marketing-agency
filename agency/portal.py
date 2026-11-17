"""Client Review Portal, Expiring Shareable Links, and Billing Estimates for LEXNIS Agency.

Review links follow common bearer-link practice: a 256-bit random token is shown once, only its
SHA-256 digest is stored (in the workspace's own agency folder, so links survive a restart),
every use re-checks expiry and revocation, and each decision is bound to the asset version the
client saw. A link is not an identity check: anyone holding it can review, so keep links short-lived.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from .database import NotFound, Conflict
from .services import service

MAX_DAYS = 30
MAX_ASSETS = 50
MAX_FEEDBACK = 200
LOCK = threading.Lock()

# Standard VAT rates in force (GCC, reviewed 2026-11-16). Qatar and Kuwait have not introduced VAT.
VAT_RATES = {'BH': .10, 'AE': .05, 'SA': .15, 'OM': .05, 'QA': 0., 'KW': 0.}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _store_path():
    return service.repo.home / 'review-links.json'


def _load() -> Dict[str, Any]:
    path = _store_path()
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def _save(links: Dict[str, Any]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + secrets.token_hex(4) + '.tmp')
    temp.write_text(json.dumps(links, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(temp, path)


def _active(link: Dict[str, Any]) -> None:
    if link['status'] == 'REVOKED':
        raise Conflict('This client review link has been revoked.')
    if datetime.fromisoformat(link['expires_at']) <= _now():
        raise Conflict('This client review link has expired.')


def _link(token: str) -> Dict[str, Any]:
    if not isinstance(token, str) or not 20 <= len(token) <= 100:
        raise NotFound('Review link not found or invalid.')
    links = _load()
    key = _digest(token)
    # Constant-time comparison of the digests, so lookup timing does not reveal partial matches.
    match = next((k for k in links if secrets.compare_digest(k, key)), None)
    if match is None:
        raise NotFound('Review link not found or invalid.')
    return links[match]


def create_client_review_link(
    client_id: str,
    campaign_id: str,
    asset_ids: List[str],
    expires_in_days: int = 7
) -> Dict[str, Any]:
    """Create a scoped, expiring review link. The token is returned once and never stored."""
    if not 1 <= int(expires_in_days) <= MAX_DAYS:
        raise ValueError(f'Review links last between 1 and {MAX_DAYS} days')
    unique = list(dict.fromkeys(asset_ids))
    if len(unique) > MAX_ASSETS:
        raise ValueError(f'A review link can include at most {MAX_ASSETS} assets')
    campaign = service.get(client_id, campaign_id, 'campaigns')
    versions = {aid: service.get(client_id, aid, 'assets').get('version', 1) for aid in unique}
    token = secrets.token_urlsafe(32)
    created = _now()
    link = dict(client_id=client_id, campaign_id=campaign_id,
                campaign_name=campaign.get('name') or campaign.get('data', {}).get('name', 'Campaign'),
                asset_versions=versions, created_at=created.isoformat(),
                expires_at=(created + timedelta(days=int(expires_in_days))).isoformat(), status='ACTIVE', feedback=[])
    with LOCK:
        links = _load()
        links[_digest(token)] = link
        _save(links)
    return {'token': token, 'review_url': f'/review/{token}', 'expires_at': link['expires_at'], 'asset_count': len(unique),
            'notice': 'Anyone with this link can review until it expires. Share it only with the approver.'}


def revoke_review_link(client_id: str, token: str) -> Dict[str, Any]:
    with LOCK:
        links = _load()
        key = _digest(token)
        link = links.get(key)
        if not link or link['client_id'] != client_id:
            raise NotFound('Review link not found or invalid.')
        link['status'] = 'REVOKED'
        link['revoked_at'] = _now().isoformat()
        _save(links)
    return {'status': 'REVOKED'}


def get_review_portal_data(token: str) -> Dict[str, Any]:
    """Scoped review data. Omits internal margins, prompts and filesystem paths."""
    link = _link(token)
    _active(link)
    client_id = link['client_id']
    with service.repo.connection() as db:
        client = service.repo.client(db, client_id)
    safe_assets = []
    for aid, version in link['asset_versions'].items():
        try:
            asset = service.get(client_id, aid, 'assets')
        except NotFound:
            continue
        data = asset.get('data', {})
        safe_assets.append({'id': asset['id'], 'version': version, 'current_version': asset.get('version', 1),
                            'changed_since_shared': asset.get('version', 1) != version,
                            'type': data.get('type', 'image'), 'headline': data.get('headline', ''), 'url': data.get('url')})
    return {
        'client_name': client.get('name', 'Client'),
        'campaign_name': link['campaign_name'],
        'assets': safe_assets,
        'expires_at': link['expires_at'],
        'feedback_history': link['feedback'],
    }


def submit_review_decision(
    token: str,
    reviewer_name: str,
    decision: str,
    comments: str = '',
    asset_id: Optional[str] = None
) -> Dict[str, Any]:
    """Record APPROVED or CHANGES_REQUESTED for the asset version that was shared."""
    if decision not in {'APPROVED', 'CHANGES_REQUESTED'}:
        raise ValueError('Decision must be either APPROVED or CHANGES_REQUESTED')
    name = ' '.join(str(reviewer_name or '').split())
    if not 1 <= len(name) <= 120:
        raise ValueError('Enter the reviewer name (up to 120 characters)')
    if len(comments or '') > 2000:
        raise ValueError('Comments are limited to 2,000 characters')
    if decision == 'CHANGES_REQUESTED' and not (comments or '').strip():
        raise ValueError('Describe the changes you need')
    with LOCK:
        links = _load()
        key = _digest(token) if isinstance(token, str) else ''
        link = links.get(key)
        if not link:
            raise NotFound('Invalid review link')
        _active(link)                          # an expired or revoked link cannot approve anything
        if len(link['feedback']) >= MAX_FEEDBACK:
            raise Conflict('This review link has reached its feedback limit; ask for a new link.')
        version = None
        if asset_id is not None:
            if asset_id not in link['asset_versions']:
                raise ValueError('This asset is not part of the review link')
            version = link['asset_versions'][asset_id]
            current = service.get(link['client_id'], asset_id, 'assets').get('version', 1)
            if current != version:
                raise Conflict('This asset changed after the link was shared; ask for a new review link.')
        entry = {'timestamp': _now().isoformat(), 'reviewer_name': name, 'decision': decision,
                 'comments': (comments or '').strip(), 'asset_id': asset_id, 'asset_version': version,
                 'scope': 'asset' if asset_id else 'all shared assets'}
        link['feedback'].append(entry)
        _save(links)
    return {'success': True, 'decision': decision, 'feedback_entry': entry}


def generate_billing_summary(client_id: str, campaign_id: str) -> Dict[str, Any]:
    """Editable fee ESTIMATE in the campaign's currency. Not an invoice.

    Hours and rates are a starting template for the operator to edit. VAT is charged at the
    standard rate of the agency's own country (AGENCY_VAT_COUNTRY, default Bahrain); tax treatment
    of cross-border services must be checked by the operator.
    """
    campaign = service.get(client_id, campaign_id, 'campaigns')
    data = campaign.get('data', {})
    currency = data.get('currency') or 'BHD'
    country = os.getenv('AGENCY_VAT_COUNTRY', 'BH').strip().upper()
    if country not in VAT_RATES:
        raise ValueError(f'No VAT rate is configured for {country}; set AGENCY_VAT_COUNTRY to one of {", ".join(sorted(VAT_RATES))}')
    rate = VAT_RATES[country]
    items = [
        {'item': 'Campaign strategy and planning', 'hours': 12, 'rate': 60.0},
        {'item': 'Creative direction and production', 'hours': 20, 'rate': 45.0},
        {'item': 'Bilingual copywriting and localisation', 'hours': 8, 'rate': 40.0},
        {'item': 'Claims review and rights clearance', 'hours': 4, 'rate': 60.0},
    ]
    for item in items:
        item['amount'] = round(item['hours'] * item['rate'], 3)
    subtotal = round(sum(i['amount'] for i in items), 3)
    tax = round(subtotal * rate, 3)
    return {
        'document_type': 'ESTIMATE',
        'client_id': client_id,
        'campaign_id': campaign_id,
        'currency': currency,
        'reference': f'EST-{_now().strftime("%Y%m")}-{campaign_id[:6].upper()}',
        'date': _now().strftime('%Y-%m-%d'),
        'line_items': items,
        'subtotal': subtotal,
        'vat_country': country,
        'vat_rate': rate,
        'tax': tax,
        'total': round(subtotal + tax, 3),
        'planned_ad_spend': data.get('budget', 0),
        'notice': 'Template hours and rates: edit them before sending. This is not a tax invoice; invoices need your '
                  'VAT registration number and the client details required in your country.',
    }
