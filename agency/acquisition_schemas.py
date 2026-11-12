"""Local acquisition workflows: no network fetching, sending or site deployment."""
import re
import json
import math
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from pydantic import Field, field_validator, model_validator
from .schema_types import Strict, Id, Short, Text, Tags, Ids, Locale


def safe_url(value, empty=True):
    if not value and empty:
        return value
    parsed = urlsplit(value)
    if (parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password
            or any(ord(c) < 33 or ord(c) == 127 for c in value)):
        raise ValueError('Use an absolute HTTP(S) URL without credentials or whitespace')
    return value


def strict_json(value):
    def constant(token):
        raise ValueError('JSON-LD cannot contain non-finite numbers')
    def number(token):
        parsed = float(token)
        if not math.isfinite(parsed):
            constant(token)
        return parsed
    try:
        parsed = json.loads(value, parse_constant=constant, parse_float=number)
    except RecursionError:
        raise ValueError('JSON-LD nesting exceeds supported limits')
    pending = [(parsed, 0)]
    visited = 0
    while pending:
        node, depth = pending.pop()
        visited += 1
        if depth > 32 or visited > 10000:
            raise ValueError('JSON-LD exceeds the depth or node budget')
        if isinstance(node, dict):
            pending.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            pending.extend((child, depth + 1) for child in node)
    return parsed


class SEOAudit(Strict):
    page_url: str = Field(max_length=2000)
    html: str = Field(min_length=1, max_length=300000)
    source_note: Text = ''
    observed_status: int | None = Field(None, ge=100, le=599)
    source_ids: Ids = []
    _url = field_validator('page_url')(safe_url)


class SEOBrief(Strict):
    topic: Short = Field(min_length=1)
    intent_hypothesis: Text = ''
    audience_id: Id | None = None
    primary_question: Short = ''
    related_questions: Tags = []
    keywords: Tags = []
    content_gap: Text = ''
    page_type: Literal['article', 'service', 'product', 'landing', 'faq', 'other'] = 'article'
    sections: Tags = []
    internal_links: Tags = []
    evidence_ids: Annotated[list[Id], Field(max_length=50)] = []
    cta: Short = ''


class PageBlock(Strict):
    kind: Literal['nav', 'hero', 'proof', 'benefits', 'features', 'comparison', 'process', 'testimonials', 'stats', 'faq', 'cta', 'footer', 'form'] = 'hero'
    heading: Short = ''
    text: Text = ''
    cta_label: Short = ''
    cta_url: str = Field('', max_length=2000)
    _url = field_validator('cta_url')(safe_url)


class LandingPage(Strict):
    language: Locale = 'en'
    title: Short = Field(min_length=1)
    description: str = Field('', max_length=500)
    canonical_url: str = Field('', max_length=2000)
    brand_id: Id | None = None
    primary_color: str = Field('#14b8a6', pattern=r'^#[0-9A-Fa-f]{6}$')
    background_color: str = Field('#ffffff', pattern=r'^#[0-9A-Fa-f]{6}$')
    text_color: str = Field('#142124', pattern=r'^#[0-9A-Fa-f]{6}$')
    blocks: Annotated[list[PageBlock], Field(max_length=40)] = []
    privacy_copy: Text = ''
    form_endpoint: str = Field('', max_length=2000)
    structured_data: str = Field('', max_length=20000)
    _urls = field_validator('canonical_url', 'form_endpoint')(safe_url)

    @field_validator('structured_data')
    @classmethod
    def jsonld(cls, value):
        if value:
            data = strict_json(value)
            if not isinstance(data, (dict, list)):
                raise ValueError('JSON-LD must be an object or array')
        return value


class Contact(Strict):
    email: str = Field(max_length=254)
    language: Locale = 'en'
    source: Short = ''
    consent_status: Literal['unknown', 'granted', 'withdrawn'] = 'unknown'
    consent_purpose: Short = ''
    consent_evidence: Text = ''
    consent_recorded_at: datetime | None = None
    suppressed: bool = False
    unsubscribed: bool = False
    tags: Tags = []
    notes: Text = ''

    @field_validator('email')
    @classmethod
    def email_format(cls, value):
        value = value.strip().casefold()
        if not re.fullmatch(r'[a-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}', value) or '..' in value:
            raise ValueError('Enter a valid email address')
        return value

    @model_validator(mode='after')
    def consent_proof(self):
        if self.consent_status == 'granted' and not (self.source.strip() and self.consent_purpose.strip() and self.consent_evidence.strip()):
            raise ValueError('Granted consent needs a source, purpose and evidence note')
        return self


class Segment(Strict):
    purpose: Short = Field(min_length=1)
    language: Literal['', 'en', 'ar', 'ar-BH'] = ''
    required_tags: Tags = []
    excluded_tags: Tags = []


class EmailTemplate(Strict):
    subject: Short = Field(min_length=1)
    preheader: Short = ''
    language: Locale = 'en'
    body: Text = Field(min_length=1)
    cta_label: Short = ''
    cta_url: str = Field('', max_length=2000)
    physical_address: Short = ''
    unsubscribe_url: str = Field('', max_length=2000)
    footer: Text = ''
    _urls = field_validator('cta_url', 'unsubscribe_url')(safe_url)


class Retention(Strict):
    review_after_days: int = Field(365, ge=1, le=3650)
    purpose: Text = ''
    legal_hold: bool = False
    auto_delete: Literal[False] = False
    notes: Text = ''


ACQUISITION_MODELS = {'seo-audits': SEOAudit, 'seo-briefs': SEOBrief, 'landing-pages': LandingPage,
                      'contacts': Contact, 'segments': Segment, 'email-templates': EmailTemplate, 'retention': Retention}
