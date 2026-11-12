"""Validated agency records. Unknown fields and non-finite numbers are rejected."""
from datetime import date as Date
import hashlib
import json
from typing import Annotated, Literal
from urllib.parse import urlsplit, parse_qs
from pydantic import Field, model_validator
from .schema_types import Strict, Id, Short, Text, Tags, Ids, Locale, EvidenceState


def public_url(value):
    if not value:
        return value
    p = urlsplit(value)
    if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password:
        raise ValueError('Use a public HTTP/HTTPS URL without credentials')
    if any(any(word in key.lower() for word in ('token', 'secret', 'password', 'api_key')) for key in parse_qs(p.query)):
        raise ValueError('URLs must not contain credentials or secret query parameters')
    return value


class Client(Strict):
    name: str = Field(min_length=1, max_length=120)
    legal_name: Short = ''
    industry: Short = ''
    website: str = Field('', max_length=2000)
    description: Text = ''
    markets: Tags = []
    languages: list[Locale] = Field(default=['en', 'ar'], max_length=3)
    timezone: Short = 'Asia/Bahrain'
    status: Literal['prospect', 'active', 'paused', 'archived'] = 'active'
    owner: Short = 'Local operator'
    notes: Text = ''

    @model_validator(mode='after')
    def urls(self):
        public_url(self.website)
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError('Use an installed IANA timezone, for example Asia/Bahrain')
        return self


class Project(Strict):
    objective: Text = ''
    scope: Text = ''
    owner: Short = ''
    start_date: Date | None = None
    end_date: Date | None = None
    notes: Text = ''


class Brand(Strict):
    legacy_brand_id: Short = ''
    brand_name_ar: Short = ''
    primary_color: str = Field('#131724', pattern=r'^#[0-9a-fA-F]{6}$')
    accent_color: str = Field('#53B849', pattern=r'^#[0-9a-fA-F]{6}$')
    secondary_colors: list[Annotated[str, Field(pattern=r'^#[0-9a-fA-F]{6}$')]] = Field(default=[], max_length=8)
    typography: Tags = []
    logo_url: str = Field('', max_length=500)
    logo_variations: Tags = []
    logo_clear_space: Text = ''
    voice: Text = ''
    personality: Text = ''
    desired_language: Tags = []
    prohibited_language: Tags = []
    product_vocabulary: Tags = []
    messaging_pillars: Tags = []
    visual_style: Text = ''
    photography_style: Text = ''
    icon_style: Text = ''
    cta_style: Text = ''
    legal_disclosures: Tags = []
    arabic_rules: Text = ''
    english_rules: Text = ''
    mixed_direction_rules: Text = ''
    approved_claim_ids: Ids = []
    forbidden_claims: Tags = []
    product_references: Tags = []
    platform_notes: Text = ''
    tagline: Short = ''
    hashtag: Short = ''

    @model_validator(mode='after')
    def logo(self):
        if self.logo_url and not self.logo_url.startswith(('/static/assets/', '/uploads/', '/renders/')):
            raise ValueError('Logo must use a managed application media URL')
        if '..' in self.logo_url or '\\' in self.logo_url or '?' in self.logo_url:
            raise ValueError('Invalid logo URL')
        return self


class Glossary(Strict):
    source_term: Short = Field(min_length=1)
    approved_english: Short = ''
    approved_arabic: Short = ''
    transliteration: Short = ''
    do_not_translate: bool = False
    prohibited_forms: Tags = []
    notes: Text = ''


class Stakeholder(Strict):
    role: Short = ''
    contact: Short = ''
    approval_role: Short = ''
    decision_authority: Short = ''
    preferred_communication: Short = ''
    notes: Text = ''


class AccessRequirement(Strict):
    service: Short
    owner: Short = ''
    state: Literal['missing', 'requested', 'granted', 'not-needed', 'revoked'] = 'missing'
    instructions: Text = ''
    credential_reference: str = Field('', pattern=r'^(?:(?:env|keychain):[A-Za-z0-9_.-]{1,100})?$')


class Onboarding(Strict):
    objectives: Text = ''
    products_services: Text = ''
    target_markets: Tags = []
    known_competitors: Tags = []
    prior_marketing: Text = ''
    current_challenges: Text = ''
    existing_channels: Tags = []
    brand_assets: Text = ''
    access_checklist: Text = ''
    legal_approvals: Text = ''
    deadline: Date | None = None
    budget_range: Short = ''
    reporting_cadence: Short = ''


class Source(Strict):
    source_type: Literal['manual', 'url', 'document', 'csv'] = 'manual'
    url: str = Field('', max_length=2000)
    content: str = Field('', max_length=120000)
    date: Date = Field(default_factory=Date.today)
    evidence_state: EvidenceState = 'unverified_hypothesis'
    credibility: Literal['unreviewed', 'low', 'medium', 'high'] = 'unreviewed'
    tags: Tags = []
    annotation: Text = ''
    document_id: Id | None = None
    snapshot_id: Id | None = None
    captured_at: Short = ''

    @model_validator(mode='after')
    def urls(self):
        public_url(self.url)
        if self.source_type == 'url' and not self.url:
            raise ValueError('A URL source needs a public URL')
        return self


class Finding(Strict):
    statement: Text = Field(min_length=1)
    source_ids: Ids = []
    classification: Literal['fact', 'hypothesis', 'interpretation', 'recommendation'] = 'hypothesis'
    evidence_state: EvidenceState = 'unverified_hypothesis'
    origin: Literal['analyst', 'local-model'] = 'analyst'
    confidence: Literal['low', 'medium', 'high'] = 'low'
    tags: Tags = []
    implications: Text = ''
    date: Date = Field(default_factory=Date.today)

    @model_validator(mode='after')
    def facts(self):
        if self.classification == 'fact' and not self.source_ids:
            raise ValueError('A finding marked fact requires a source')
        return self


class Evidence(Strict):
    summary: Text = Field(min_length=1)
    source_type: Literal['research-source', 'client-statement', 'manual-note'] = 'manual-note'
    source_ids: Ids = []
    quotation: Text = ''
    state: EvidenceState = 'unverified_hypothesis'
    date: Date = Field(default_factory=Date.today)
    reviewer: Short = ''


class Claim(Strict):
    text: Text = Field(min_length=1)
    language: Locale = 'en'
    category: Short = ''
    status: Literal['draft', 'verified', 'client-approved', 'expired', 'prohibited', 'needs-evidence'] = 'draft'
    substantiation_requirement: Text = ''
    restrictions: Text = ''
    valid_from: Date | None = None
    valid_until: Date | None = None
    owner: Short = ''
    reviewer: Short = ''
    evidence_ids: Ids = []

    @model_validator(mode='after')
    def approval(self):
        if self.status in {'verified', 'client-approved'} and (not self.evidence_ids or not self.reviewer):
            raise ValueError('Approved claims require evidence and a named reviewer')
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError('Claim expiry must follow its valid-from date')
        return self


class Competitor(Strict):
    website: str = Field('', max_length=2000)
    products_services: Text = ''
    positioning: Text = ''
    observed_messages: Tags = []
    apparent_audience: Text = ''
    offers: Text = ''
    channels: Tags = []
    themes: Tags = []
    creative_observations: Text = ''
    strengths: Text = ''
    weaknesses: Text = ''
    source_ids: Ids = []
    snapshot_date: Date | None = None

    @model_validator(mode='after')
    def urls(self):
        public_url(self.website)
        return self


class Objective(Strict):
    objective: Text = Field(min_length=1)
    objective_type: Literal['business', 'marketing', 'communication'] = 'marketing'
    baseline: Short = ''
    target: Short = ''
    deadline: Date | None = None
    kpi: Short = ''
    source_ids: Ids = []


class Audience(Strict):
    source_ids: Ids = []
    evidence_state: EvidenceState = 'unverified_hypothesis'
    behavior: Text = ''
    needs: Tags = []
    motivations: Tags = []
    barriers: Tags = []
    decision_criteria: Tags = []
    awareness: Short = ''
    language: Locale = 'en'
    market: Short = ''


class Persona(Strict):
    audience_id: Id | None = None
    job_to_be_done: Text = ''
    context: Text = ''
    trigger: Text = ''
    desired_outcome: Text = ''
    barriers: Tags = []
    alternatives: Tags = []
    source_ids: Ids = []
    evidence_state: EvidenceState = 'unverified_hypothesis'


class Journey(Strict):
    audience_id: Id | None = None
    questions: Tags = []
    pain_points: Tags = []
    desired_action: Text = ''
    content_need: Text = ''
    measurement: Text = ''


class Positioning(Strict):
    audience_id: Id | None = None
    category: Text = ''
    problem: Text = ''
    primary_benefit: Text = ''
    differentiation: Text = ''
    reason_to_believe: Text = ''
    evidence_ids: Ids = []
    alternatives: Tags = []


class MessagePillar(Strict):
    proposition: Text = ''
    supporting_messages: Tags = []
    evidence_ids: Ids = []
    objections: Tags = []
    cta: Short = ''
    prohibited_language: Tags = []


class Offer(Strict):
    description: Text = ''
    incentive: Text = ''
    eligibility: Text = ''
    valid_until: Date | None = None
    restrictions: Text = ''
    evidence_ids: Ids = []
    cta: Short = ''


class Strategy(Strict):
    business_context: Text = ''
    current_state: Text = ''
    desired_state: Text = ''
    constraints: Tags = []
    objective_ids: Ids = []
    audience_ids: Ids = []
    positioning_id: Id | None = None
    message_ids: Ids = []
    offer_id: Id | None = None
    communication_task: Text = ''
    strategic_idea: Text = ''
    channels: Tags = []
    channel_roles: Text = ''
    exclusions: Tags = []
    risks: Tags = []
    assumptions: Tags = []


class Campaign(Strict):
    status: Literal['draft','strategy','creative','review','approved','scheduled','live','optimization','completed','archived'] = 'draft'
    brand_id: Id | None = None
    strategy_id: Id | None = None
    objective: Text = ''
    primary_kpi: Short = ''
    secondary_kpis: Tags = []
    audience_ids: Ids = []
    positioning_id: Id | None = None
    message_ids: Ids = []
    offer_id: Id | None = None
    start_date: Date | None = None
    end_date: Date | None = None
    owner: Short = ''
    budget: float = Field(0, ge=0, le=1e9)
    currency: str = Field('BHD', pattern=r'^[A-Z]{3}$')
    markets: Tags = []
    languages: list[Locale] = Field(default=['en'], max_length=3)
    notes: Text = ''


class Generation(Strict):
    provider:Literal['local-llama.cpp']
    model_id:Short
    revision:Short
    license:Short
    source_brief_id:Id
    source_brief_version:int=Field(ge=1)
    prompt_template:Short
    instruction:str=Field('',max_length=1500)
    input_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    input_snapshot:dict=Field(default_factory=dict)
    seed:int
    temperature:float
    max_tokens:int
    generated_at:Short

    @model_validator(mode='after')
    def inputs(self):
        if self.input_snapshot:
            encoded=json.dumps(self.input_snapshot,sort_keys=True,ensure_ascii=False,allow_nan=False).encode('utf-8')
            if len(encoded)>12000 or hashlib.sha256(encoded).hexdigest()!=self.input_sha256:
                raise ValueError('Generation input snapshot exceeds its budget or does not match its hash')
        return self


class Brief(Strict):
    business_context: Text = ''
    campaign_objective: Text = ''
    measurable_success: Text = ''
    audience: Text = ''
    desired_behavior: Text = ''
    insight: Text = ''
    positioning: Text = ''
    primary_message: Text = ''
    supporting_messages: Tags = []
    reasons_to_believe: Tags = []
    claim_ids: Ids = []
    offer: Text = ''
    cta: Short = ''
    tone: Text = ''
    visual_direction: Text = ''
    mandatory_elements: Tags = []
    prohibited_elements: Tags = []
    channels: Tags = []
    deliverables: Tags = []
    localization: Text = ''
    timing: Text = ''
    budget: Short = ''
    reviewers: Tags = []
    approval_checkpoints: Tags = []
    assumptions: Tags = []
    generation:Generation|None=None


class ChannelPlan(Strict):
    channel: Short
    role: Text = ''
    audience_id: Id | None = None
    objective: Text = ''
    content_types: Tags = []
    cadence: Short = ''
    kpi: Short = ''
    budget: float = Field(0, ge=0, le=1e9)


class Deliverable(Strict):
    platform: Short = ''
    format: Short = ''
    width: int | None = Field(None, ge=1, le=8192)
    height: int | None = Field(None, ge=1, le=8192)
    language: Locale = 'en'
    due_date: Date | None = None
    owner: Short = ''
    state: Literal['planned','in-progress','review','done','cancelled'] = 'planned'
    notes: Text = ''


MODELS = {
    'projects': Project, 'brands': Brand, 'glossary': Glossary, 'stakeholders': Stakeholder,
    'access': AccessRequirement, 'onboarding': Onboarding, 'sources': Source, 'findings': Finding,
    'evidence': Evidence, 'claims': Claim, 'competitors': Competitor, 'objectives': Objective,
    'audiences': Audience, 'personas': Persona, 'journey': Journey, 'positionings': Positioning,
    'messages': MessagePillar, 'offers': Offer, 'strategies': Strategy, 'campaigns': Campaign,
    'briefs': Brief, 'channels': ChannelPlan, 'deliverables': Deliverable,
}

# All links are checked in the same transaction as the record write.
REFERENCES = {
    'source_ids':'sources', 'evidence_ids':'evidence', 'approved_claim_ids':'claims', 'claim_ids':'claims',
    'audience_id':'audiences', 'audience_ids':'audiences', 'objective_ids':'objectives',
    'positioning_id':'positionings', 'message_ids':'messages', 'offer_id':'offers',
    'brand_id':'brands', 'strategy_id':'strategies',
}


# Content, asset, approval, publishing-export, analytics, reporting and operations records.
from .production_schemas import PRODUCTION_MODELS, PRODUCTION_REFERENCES  # noqa: E402
MODELS.update(PRODUCTION_MODELS)
REFERENCES.update(PRODUCTION_REFERENCES)
from .acquisition_schemas import ACQUISITION_MODELS  # noqa: E402
MODELS.update(ACQUISITION_MODELS)
from .audio_schemas import AUDIO_MODELS  # noqa: E402
MODELS.update(AUDIO_MODELS)
from .planning_schemas import PLANNING_MODELS, PLANNING_REFERENCES  # noqa: E402
MODELS.update(PLANNING_MODELS)
REFERENCES.update(PLANNING_REFERENCES)


class RecordInput(Strict):
    name: str = Field(min_length=1, max_length=160)
    project_id: Id | None = None
    campaign_id: Id | None = None
    data: dict


class RecordUpdate(RecordInput):
    expected_version: int = Field(ge=1)


class ClientUpdate(Client):
    expected_version: int = Field(ge=1)
