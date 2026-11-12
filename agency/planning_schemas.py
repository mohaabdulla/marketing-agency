"""Organic, creator and paid-media planning. No account access or spend authorization."""
from datetime import date as Date
from typing import Literal
from pydantic import Field, field_validator
from .schema_types import Strict, Id, Short, Text, Tags, Ids
from .acquisition_schemas import safe_url


class Pillar(Strict):
    purpose: Text = ''
    audience_id: Id | None = None
    topics: Tags = []
    formats: Tags = []
    cadence: Short = ''
    evidence_ids: Ids = []


class Series(Strict):
    pillar_id: Id | None = None
    recurring_concept: Text = ''
    platform: Short = ''
    template_note: Text = ''
    cadence: Short = ''
    source_copy_id: Id | None = None
    source_script_id: Id | None = None
    brief_id: Id | None = None


class PaidPlan(Strict):
    platform: Literal['meta', 'google', 'linkedin', 'tiktok', 'youtube', 'other'] = 'meta'
    objective: Short = Field(min_length=1)
    audience_id: Id | None = None
    audience_notes: Text = ''
    ad_group: Short = ''
    placements: Tags = []
    copy_id: Id | None = None
    asset_ids: Ids = []
    landing_page_id: Id | None = None
    destination_url: str = Field('', max_length=2000)
    currency: str = Field('BHD', pattern=r'^[A-Z]{3}$')
    daily_budget: float = Field(0, ge=0, le=1e7)
    days: int = Field(1, ge=1, le=366)
    assumed_cpc: float | None = Field(None, gt=0, le=1e7)
    assumed_conversion_percent: float | None = Field(None, ge=0, le=100)
    assumption_source: Text = ''
    kpi: Short = ''
    utm_source: Short = ''
    utm_medium: Short = 'paid'
    utm_campaign: Short = ''
    utm_content: Short = ''
    notes: Text = ''
    _url = field_validator('destination_url')(safe_url)


class Creator(Strict):
    handle: Short = ''
    platform: Short = ''
    market: Short = ''
    niche: Short = ''
    public_contact: Short = ''
    source: Short = ''
    status: Literal['prospect', 'contacted-manually', 'interested', 'contracted', 'inactive'] = 'prospect'
    notes: Text = ''


class CreatorBrief(Strict):
    creator_id: Id
    deliverables: Tags = []
    talking_points: Tags = []
    prohibited_claims: Tags = []
    disclosure_required: bool = True
    disclosure_text: Text = ''
    due_date: Date | None = None
    compensation: float = Field(0, ge=0, le=1e9)
    currency: str = Field('BHD', pattern=r'^[A-Z]{3}$')
    product_provided: Short = ''
    license_id: Id | None = None
    organic_use: bool = False
    paid_use: bool = False
    edit_rights: bool = False
    geography: Tags = []
    rights_end: Date | None = None
    approval_process: Text = ''
    notes: Text = ''


PLANNING_MODELS = {'content-pillars': Pillar, 'content-series': Series, 'paid-plans': PaidPlan,
                   'creators': Creator, 'creator-briefs': CreatorBrief}
PLANNING_REFERENCES = {'pillar_id': 'content-pillars', 'source_copy_id': 'copy', 'source_script_id': 'scripts',
                       'landing_page_id': 'landing-pages', 'creator_id': 'creators'}
