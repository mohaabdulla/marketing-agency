"""Tracking, UTM Builder, KPI Calculations, and Analytics Import for LEXNIS Agency.

UTM handling follows Google Analytics campaign-URL conventions: values are case-sensitive in
reports, so they are lower-cased and use hyphens instead of spaces; utm_source, utm_medium and
utm_campaign are required; utm_id and utm_source_platform are supported; utm_creative_format
and utm_marketing_tactic are written but are not reported in GA4 at the time of review.
Ratios are only computed when their denominator exists: an undefined ratio is None, not 0.
"""
from __future__ import annotations

import csv
import io
import re
import urllib.parse
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

UTM_FIELDS = (('source', 'utm_source'), ('medium', 'utm_medium'), ('campaign', 'utm_campaign'), ('id', 'utm_id'),
              ('term', 'utm_term'), ('content', 'utm_content'), ('source_platform', 'utm_source_platform'),
              ('creative_format', 'utm_creative_format'), ('marketing_tactic', 'utm_marketing_tactic'))
NOT_REPORTED_IN_GA4 = {'utm_creative_format', 'utm_marketing_tactic'}
EMAIL = re.compile(r'[^@\s]+@[^@\s]+\.[a-z]{2,}', re.IGNORECASE)


def normalize_utm_value(value: str) -> str:
    """Lower case, trimmed, words joined by hyphens; only letters, digits and . _ - + survive."""
    text = re.sub(r'\s+', '-', str(value).strip().casefold())
    text = re.sub(r'[^\w.\-+]', '', text)
    return re.sub(r'-{2,}', '-', text).strip('-')


@dataclass
class UTMParameters:
    source: str
    medium: str
    campaign: str
    content: Optional[str] = None
    term: Optional[str] = None
    id: Optional[str] = None
    source_platform: Optional[str] = None
    creative_format: Optional[str] = None
    marketing_tactic: Optional[str] = None

    def normalized(self) -> Dict[str, str]:
        values = {}
        for attribute, key in UTM_FIELDS:
            raw = getattr(self, attribute)
            if raw is None or not str(raw).strip():
                continue
            if EMAIL.search(str(raw)):
                raise ValueError(f'{key} contains an email address. Personal data must not be sent to analytics in a URL.')
            value = normalize_utm_value(raw)
            if value:
                values[key] = value
        missing = [key for key in ('utm_source', 'utm_medium', 'utm_campaign') if key not in values]
        if missing:
            raise ValueError('Required campaign parameters are empty after normalisation: ' + ', '.join(missing))
        return values

    def warnings(self) -> List[str]:
        notes = []
        for attribute, key in UTM_FIELDS:
            raw = getattr(self, attribute)
            if raw is None:
                continue
            if str(raw).strip() and normalize_utm_value(raw) != str(raw).strip():
                notes.append(f'{key} was normalised from "{str(raw).strip()[:60]}" to "{normalize_utm_value(raw)}"')
        for key in NOT_REPORTED_IN_GA4 & set(self.normalized()):
            notes.append(f'{key} is written to the URL but is not shown in Google Analytics 4 reports')
        return notes

    def build_url(self, base_url: str) -> str:
        parsed = urllib.parse.urlparse(str(base_url).strip())
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            raise ValueError('The landing page must be an absolute http(s) URL')
        # Existing non-UTM parameters and their order are kept; earlier UTM values are replaced.
        kept = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith('utm_')]
        query = urllib.parse.urlencode(kept + list(self.normalized().items()))
        return urllib.parse.urlunparse(parsed._replace(query=query))


def _ratio(numerator: float, denominator: float, scale: float = 1.0) -> Optional[float]:
    return round(numerator / denominator * scale, 2) if denominator > 0 else None


def calculate_canonical_kpis(
    impressions: int,
    clicks: int,
    spend: float,
    conversions: int = 0,
    revenue: float = 0.0
) -> Dict[str, Any]:
    """Standard paid-media ratios. A ratio whose denominator is zero is None (undefined), never 0."""
    impr = max(0, int(impressions))
    clk = max(0, int(clicks))
    sp = max(0.0, float(spend))
    conv = max(0, int(conversions))
    rev = max(0.0, float(revenue))
    return {
        "impressions": impr,
        "clicks": clk,
        "spend": round(sp, 2),
        "conversions": conv,
        "revenue": round(rev, 2),
        "ctr_percent": _ratio(clk, impr, 100.0),      # clicks / impressions
        "cpm": _ratio(sp, impr, 1000.0),              # cost per 1,000 impressions
        "cpc": _ratio(sp, clk),                       # cost per click
        "cpa": _ratio(sp, conv),                      # cost per conversion
        "cvr_percent": _ratio(conv, clk, 100.0),      # conversions / clicks
        "roas": _ratio(rev, sp),                      # revenue / spend
    }


def _number(value: Any, column: str, line: int, integer: bool) -> float:
    """Accepts exports such as "1,234", "$1,234.50", "BHD 12.5" or a blank optional cell."""
    text = str(value if value is not None else '').strip()
    if not text:
        return 0
    cleaned = re.sub(r'[^\d.\-]', '', text.replace(',', ''))
    try:
        number = float(cleaned)
    except ValueError:
        raise ValueError(f'Line {line}: {column} "{text[:30]}" is not a number')
    if number < 0:
        raise ValueError(f'Line {line}: {column} cannot be negative')
    if integer:
        if number != int(number):
            raise ValueError(f'Line {line}: {column} must be a whole number')
        return int(number)
    return number


def parse_analytics_csv(csv_text: str) -> Dict[str, Any]:
    """Parse and validate a performance export. Headers are matched case-insensitively."""
    reader = csv.DictReader(io.StringIO(csv_text.lstrip('﻿').strip()))
    headers = {(name or '').strip().casefold(): name for name in (reader.fieldnames or [])}
    required_fields = {"date", "channel", "impressions", "clicks", "spend"}
    missing = required_fields - set(headers)
    if missing:
        raise ValueError(f"CSV missing mandatory columns: {', '.join(sorted(missing))}")

    rows, warnings = [], []
    totals = dict(impressions=0, clicks=0, spend=0.0, conversions=0, revenue=0.0)
    for line, raw in enumerate(reader, start=2):
        r = {key: raw.get(original) for key, original in headers.items()}
        if not any(str(v or '').strip() for v in r.values()):
            continue
        for column in ('date', 'channel', 'impressions', 'clicks', 'spend'):
            if not str(r.get(column) or '').strip():
                raise ValueError(f'Line {line}: {column} is empty')
        values = dict(impressions=_number(r['impressions'], 'impressions', line, True),
                      clicks=_number(r['clicks'], 'clicks', line, True),
                      spend=_number(r['spend'], 'spend', line, False),
                      conversions=_number(r.get('conversions'), 'conversions', line, True),
                      revenue=_number(r.get('revenue'), 'revenue', line, False))
        when = str(r['date']).strip()
        try:
            date.fromisoformat(when)
        except ValueError:
            warnings.append(f'Line {line}: date "{when[:20]}" is not YYYY-MM-DD; it is kept as text and cannot be sorted reliably')
        if values['clicks'] > values['impressions']:
            warnings.append(f'Line {line}: more clicks than impressions; check the export')
        if values['conversions'] > values['clicks'] and values['clicks']:
            warnings.append(f'Line {line}: more conversions than clicks; view-through or offline conversions may be included')
        for key in totals:
            totals[key] += values[key]
        rows.append({"date": when, "channel": str(r['channel']).strip(), "campaign": str(r.get("campaign") or '').strip(),
                     **calculate_canonical_kpis(**values)})
    if not rows:
        raise ValueError('The CSV has a header but no data rows')
    return {
        "rows_count": len(rows),
        "summary": calculate_canonical_kpis(**totals),
        "rows": rows,
        "warnings": warnings,
        "method": 'Summary ratios are recomputed from summed totals, never averaged across rows. Undefined ratios are null.',
    }
