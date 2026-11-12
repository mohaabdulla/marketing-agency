"""Record types for content production, assets, approvals, publishing export, analytics,
reporting and operations. Registered into schemas.MODELS; same strict validation rules."""
from datetime import date as Date
from typing import Annotated, Literal
from pydantic import Field, model_validator
from .schema_types import Strict, Id, Short, Text, Tags, Ids, Locale

LongText = Annotated[str, Field(max_length=30000)]
Money = Annotated[float, Field(ge=0, le=1e9)]
Percent = Annotated[float, Field(ge=0, le=100)]
Sha = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]


# ---------------------------------------------------------------- content
class Concept(Strict):
    status: Literal['proposed', 'approved', 'rejected'] = 'proposed'
    brief_id: Id | None = None
    audience_id: Id | None = None
    strategic_rationale: Text = ''
    insight: Text = ''
    hook_type: Literal['', 'authority', 'curiosity', 'problem', 'benefit', 'story', 'social-proof', 'offer', 'question'] = ''
    appeal: Literal['', 'emotional', 'rational'] = ''
    awareness_stage: Literal['', 'unaware', 'problem-aware', 'solution-aware', 'product-aware', 'most-aware'] = ''
    emotion: Short = ''
    benefit: Short = ''
    pain_point: Short = ''
    visual_territory: Text = ''
    headline_concept: Short = ''
    offer: Short = ''
    cta: Short = ''
    channels: Tags = []
    risk: Text = ''
    references: Tags = []


class CopyVariant(Strict):
    format: Short = 'linkedin_post'
    language: Locale = 'en'
    concept_id: Id | None = None
    brief_id: Id | None = None
    headline: Short = ''
    text: LongText = Field(min_length=1)
    cta: Short = ''
    hashtags: Tags = []
    claim_ids: Ids = []
    origin: Literal['operator', 'operator-edited-model-draft'] = 'operator'
    notes: Text = ''


class Scene(Strict):
    heading: Short = ''
    narration: Text = ''
    dialogue: Text = ''
    on_screen_text: Annotated[str, Field(max_length=500)] = ''
    visual: Text = ''
    broll: Short = ''
    music_sfx: Short = ''
    duration_seconds: float | None = Field(None, ge=0.5, le=600)


class Script(Strict):
    script_type: Literal['short-form-social', 'paid-social', 'product-demo', 'explainer', 'testimonial',
                         'ugc-brief', 'voiceover-commercial', 'youtube', 'brand-video'] = 'short-form-social'
    language: Locale = 'en'
    goal: Text = ''
    target_duration_seconds: int = Field(30, ge=3, le=3600)
    concept_id: Id | None = None
    brief_id: Id | None = None
    audience_id: Id | None = None
    hooks: Annotated[list[Annotated[str, Field(max_length=500)]], Field(max_length=10)] = []
    scenes: Annotated[list[Scene], Field(max_length=40)] = []
    cta: Short = ''
    disclosure: Short = ''


class Storyboard(Strict):
    script_id: Id | None = None
    aspect: Literal['portrait-9x16', 'square-1x1', 'landscape-16x9', 'feed-4x5'] = 'portrait-9x16'
    notes: Text = ''


class Shot(Strict):
    storyboard_id: Id
    sequence: int = Field(1, ge=1, le=200)
    duration_seconds: float = Field(4, ge=0.5, le=300)
    description: Text = ''
    framing: Short = ''
    camera_angle: Short = ''
    camera_motion: Short = ''
    subject: Short = ''
    background: Short = ''
    action: Text = ''
    lighting: Short = ''
    visual_style: Short = ''
    continuity: Text = ''
    voiceover: Text = ''
    dialogue: Text = ''
    on_screen_text: Annotated[str, Field(max_length=500)] = ''
    transition: Short = ''
    image_prompt: Text = ''
    video_prompt: Text = ''
    image_asset_id: Id | None = None
    video_asset_id: Id | None = None


# ---------------------------------------------------------------- assets, rights, approvals
class GenerationNote(Strict):
    """Provenance as recorded by the operator for a generated file; not inferred by the server."""
    model: Short = ''
    revision: Short = ''
    model_license: Short = ''
    prompt: Text = ''
    negative_prompt: Text = ''
    seed: Short = ''
    parameters: Text = ''


class Asset(Strict):
    asset_type: Literal['image', 'gif', 'video', 'audio', 'logo', 'product-reference', 'document', 'subtitle', 'template']
    origin: Literal['generated', 'owned', 'client-provided', 'stock', 'creative-commons', 'unknown'] = 'unknown'
    language: Literal['', 'en', 'ar', 'ar-BH'] = ''
    tags: Tags = []
    concept_id: Id | None = None
    parent_asset_id: Id | None = None
    parent_asset_version: int | None = Field(None, ge=1)
    license_id: Id | None = None
    generation_note: GenerationNote | None = None
    notes: Text = ''
    # Set by the server when a file is registered; immutable through ordinary edits.
    sha256: Sha
    size: int = Field(ge=1, le=512 * 1024 ** 2)
    mime: Short
    stored_name: Annotated[str, Field(pattern=r'^[a-f0-9]{64}\.[a-z0-9]{2,5}$')]
    original_url: Short = ''
    width: int | None = Field(None, ge=1, le=16384)
    height: int | None = Field(None, ge=1, le=16384)
    duration_seconds: float | None = Field(None, ge=0, le=86400)


class License(Strict):
    license_type: Literal['generated', 'owned', 'client-provided', 'cc0', 'creative-commons', 'stock', 'custom-agreement', 'unknown'] = 'unknown'
    owner: Short = ''
    license_name: Short = ''
    source: Short = ''
    attribution: Text = ''
    restrictions: Text = ''
    allowed_markets: Tags = []
    allowed_channels: Tags = []
    expires: Date | None = None
    evidence_ids: Ids = []


class ReviewComment(Strict):
    author: Short
    at: Short
    text: Text
    timecode_seconds: float | None = Field(None, ge=0, le=86400)
    decision: Literal['', 'approved', 'changes-requested', 'rejected'] = ''


class Approval(Strict):
    target_id: Id
    target_kind: Short
    target_name: Short
    target_version: int = Field(ge=1)
    target_sha256: Sha | None = None
    reviewer: Short = Field(min_length=1)
    due_date: Date | None = None
    state: Literal['review-requested', 'changes-requested', 'approved', 'rejected', 'superseded'] = 'review-requested'
    request_note: Text = ''
    comments: Annotated[list[ReviewComment], Field(max_length=200)] = []
    decided_at: Short = ''


# ---------------------------------------------------------------- calendar / publishing export
class CalendarEntry(Strict):
    channel: Short = Field(min_length=1)
    target_account: Short = ''
    scheduled_date: Date
    scheduled_time: Annotated[str, Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')] = '10:00'
    timezone: Short = 'Asia/Bahrain'
    owner: Short = ''
    publish_status: Literal['planned', 'package-exported', 'published-manually', 'cancelled'] = 'planned'
    title: Short = ''
    copy_id: Id | None = None
    asset_ids: Ids = []
    alt_text: Text = ''
    disclosure: Short = ''
    platform_post_reference: Short = ''
    notes: Text = ''

    @model_validator(mode='after')
    def zone(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Use an installed IANA timezone, for example Asia/Bahrain')
        return self


# ---------------------------------------------------------------- analytics / experiments / reports
class Metric(Strict):
    unit: Short = ''
    direction: Literal['higher-is-better', 'lower-is-better', 'neutral'] = 'higher-is-better'
    aggregation: Literal['sum', 'mean', 'last'] = 'sum'
    source: Short = 'manual'
    formula: Text = ''
    scope: Short = ''


class Snapshot(Strict):
    metric_id: Id
    date: Date
    value: float = Field(ge=-1e12, le=1e12)
    channel: Short = ''
    variant: Short = ''
    copy_id: Id | None = None
    asset_id: Id | None = None
    source: Literal['manual', 'csv-import'] = 'manual'
    note: Short = ''


class Variant(Strict):
    label: Short = Field(min_length=1)
    is_control: bool = False
    sample_size: int | None = Field(None, ge=0, le=10 ** 10)
    conversions: int | None = Field(None, ge=0, le=10 ** 10)
    copy_id_note: Short = ''

    @model_validator(mode='after')
    def counts(self):
        if self.sample_size is not None and self.conversions is not None and self.conversions > self.sample_size:
            raise ValueError('Conversions cannot exceed the sample size')
        return self


class Experiment(Strict):
    hypothesis: Text = Field(min_length=1)
    variable: Literal['hook', 'image', 'cta', 'headline', 'offer', 'audience', 'landing-page', 'send-time', 'subject', 'other'] = 'hook'
    primary_metric_id: Id | None = None
    guardrail_metric_ids: Ids = []
    start_date: Date | None = None
    end_date: Date | None = None
    status: Literal['planned', 'running', 'completed', 'stopped'] = 'planned'
    decision_rule: Text = ''
    variants: Annotated[list[Variant], Field(max_length=8)] = []
    conclusion: Text = ''
    notes: Text = ''

    @model_validator(mode='after')
    def one_control(self):
        if self.variants and sum(v.is_control for v in self.variants) != 1:
            raise ValueError('Mark exactly one variant as the control')
        if len({v.label.casefold() for v in self.variants}) != len(self.variants):
            raise ValueError('Variant labels must be unique')
        return self


class Report(Strict):
    period_start: Date
    period_end: Date
    metric_ids: Ids = []
    experiment_ids: Ids = []
    executive_summary: Text = ''
    interpretation: Text = ''
    recommendations: Tags = []
    next_actions: Tags = []

    @model_validator(mode='after')
    def period(self):
        if self.period_end < self.period_start:
            raise ValueError('Report period end must follow its start')
        return self


class Learning(Strict):
    category: Literal['winning-hook', 'weak-cta', 'strong-visual', 'seasonality', 'objection', 'offer', 'audience-preference', 'channel', 'other'] = 'other'
    finding: Text = Field(min_length=1)
    status: Literal['draft', 'validated', 'retired'] = 'draft'
    confidence: Literal['low', 'medium', 'high'] = 'low'
    experiment_ids: Ids = []
    report_id: Id | None = None
    source_ids: Ids = []
    audience: Short = ''
    channel: Short = ''
    tags: Tags = []
    date: Date = Field(default_factory=Date.today)

    @model_validator(mode='after')
    def validated_needs_evidence(self):
        if self.status == 'validated' and not (self.experiment_ids or self.report_id or self.source_ids):
            raise ValueError('A validated learning needs an experiment, report or source as evidence')
        return self


# ---------------------------------------------------------------- operations
class Task(Strict):
    status: Literal['todo', 'in-progress', 'blocked', 'done', 'cancelled'] = 'todo'
    owner: Short = ''
    due_date: Date | None = None
    depends_on_ids: Ids = []
    origin: Literal['operator', 'workflow-rule'] = 'operator'
    notes: Text = ''


class ScopeItem(Strict):
    deliverable: Short = Field(min_length=1)
    quantity: int = Field(1, ge=1, le=100000)
    revision_rounds: int = Field(2, ge=0, le=50)
    due_date: Date | None = None
    included: bool = True
    notes: Text = ''


class Cost(Strict):
    category: Literal['labor', 'media', 'creator', 'printing', 'infrastructure', 'external-expense'] = 'external-expense'
    amount: Money = 0
    currency: str = Field('BHD', pattern=r'^[A-Z]{3}$')
    date: Date = Field(default_factory=Date.today)
    pass_through: bool = False
    notes: Text = ''


class Pricing(Strict):
    """An internal scenario. Every rate is the operator's own input; nothing is an industry default."""
    fee_model: Literal['hourly', 'fixed-project', 'retainer', 'deliverable-package', 'media-percentage',
                       'performance', 'value-based', 'hybrid'] = 'fixed-project'
    currency: str = Field('BHD', pattern=r'^[A-Z]{3}$')
    internal_hourly_cost: Money = 0
    expected_hours: Money = 0
    billable_rate: Money = 0
    fixed_fee: Money = 0
    monthly_retainer: Money = 0
    retainer_months: Money = 0
    package_price: Money = 0
    package_quantity: Money = 0
    media_spend: Money = 0
    media_fee_percent: Percent = 0
    performance_fee: Money = 0
    other_internal_costs: Money = 0
    pass_through_costs: Money = 0
    pass_through_markup_percent: Percent = 0
    discount_percent: Percent = 0
    target_margin_percent: Annotated[float, Field(ge=0, lt=100)] = 0
    notes: Text = ''


PRODUCTION_MODELS = {
    'concepts': Concept, 'copy': CopyVariant, 'scripts': Script, 'storyboards': Storyboard, 'shots': Shot,
    'assets': Asset, 'licenses': License, 'approvals': Approval, 'calendar': CalendarEntry,
    'metrics': Metric, 'snapshots': Snapshot, 'experiments': Experiment, 'reports': Report, 'learnings': Learning,
    'tasks': Task, 'scope': ScopeItem, 'costs': Cost, 'pricing': Pricing,
}

PRODUCTION_REFERENCES = {
    'brief_id': 'briefs', 'concept_id': 'concepts', 'script_id': 'scripts', 'storyboard_id': 'storyboards',
    'image_asset_id': 'assets', 'video_asset_id': 'assets', 'asset_id': 'assets', 'asset_ids': 'assets',
    'parent_asset_id': 'assets', 'license_id': 'licenses', 'copy_id': 'copy',
    'metric_id': 'metrics', 'primary_metric_id': 'metrics', 'guardrail_metric_ids': 'metrics', 'metric_ids': 'metrics',
    'experiment_ids': 'experiments', 'report_id': 'reports', 'depends_on_ids': 'tasks',
}

# Records created only by their own workflow endpoints, never by the generic record API.
SERVER_MANAGED = {'approvals', 'assets'}
# Work that must sit inside a campaign.
CAMPAIGN_SCOPED = {'concepts', 'copy', 'scripts', 'storyboards', 'calendar', 'paid-plans', 'creator-briefs'}
# Record kinds an approval request may target.
APPROVABLE = {'strategies', 'briefs', 'concepts', 'copy', 'scripts', 'storyboards', 'shots', 'assets', 'reports'}
