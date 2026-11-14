"""Tracking, UTM Builder, KPI Calculations, and Analytics Import for LEXNIS Agency."""
from __future__ import annotations

import csv
import io
import urllib.parse
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class UTMParameters:
    source: str
    medium: str
    campaign: str
    content: Optional[str] = None
    term: Optional[str] = None

    def build_url(self, base_url: str) -> str:
        parsed = urllib.parse.urlparse(base_url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        params["utm_source"] = self.source.lower().strip()
        params["utm_medium"] = self.medium.lower().strip()
        params["utm_campaign"] = self.campaign.lower().strip()
        if self.content:
            params["utm_content"] = self.content.lower().strip()
        if self.term:
            params["utm_term"] = self.term.lower().strip()

        new_query = urllib.parse.urlencode(params)
        return urllib.parse.urlunparse(parsed._replace(query=new_query))


def calculate_canonical_kpis(
    impressions: int,
    clicks: int,
    spend: float,
    conversions: int = 0,
    revenue: float = 0.0
) -> Dict[str, float]:
    """Calculate standard marketing metrics deterministically."""
    impr = max(0, impressions)
    clk = max(0, clicks)
    sp = max(0.0, float(spend))
    conv = max(0, conversions)
    rev = max(0.0, float(revenue))

    ctr = round((clk / impr * 100.0), 2) if impr > 0 else 0.0
    cpm = round((sp / impr * 1000.0), 2) if impr > 0 else 0.0
    cpc = round((sp / clk), 2) if clk > 0 else 0.0
    cpa = round((sp / conv), 2) if conv > 0 else 0.0
    cvr = round((conv / clk * 100.0), 2) if clk > 0 else 0.0
    roas = round((rev / sp), 2) if sp > 0 else 0.0

    return {
        "impressions": impr,
        "clicks": clk,
        "spend": sp,
        "conversions": conv,
        "revenue": rev,
        "ctr_percent": ctr,
        "cpm": cpm,
        "cpc": cpc,
        "cpa": cpa,
        "cvr_percent": cvr,
        "roas": roas,
    }


def parse_analytics_csv(csv_text: str) -> Dict[str, Any]:
    """Parse and validate CSV performance metrics."""
    f = io.StringIO(csv_text.strip())
    reader = csv.DictReader(f)
    required_fields = {"date", "channel", "impressions", "clicks", "spend"}
    if not required_fields.issubset(set(reader.fieldnames or [])):
        missing = required_fields - set(reader.fieldnames or [])
        raise ValueError(f"CSV missing mandatory columns: {', '.join(missing)}")

    rows = []
    tot_impr = 0
    tot_clicks = 0
    tot_spend = 0.0
    tot_conv = 0
    tot_rev = 0.0

    for r in reader:
        try:
            impr = int(r.get("impressions", 0))
            clk = int(r.get("clicks", 0))
            sp = float(r.get("spend", 0.0))
            conv = int(r.get("conversions", 0))
            rev = float(r.get("revenue", 0.0))
        except ValueError as ex:
            raise ValueError(f"Invalid numeric value in row: {ex}")

        tot_impr += impr
        tot_clicks += clk
        tot_spend += sp
        tot_conv += conv
        tot_rev += rev

        kpis = calculate_canonical_kpis(impr, clk, sp, conv, rev)
        rows.append({
            "date": r.get("date"),
            "channel": r.get("channel"),
            "campaign": r.get("campaign", ""),
            **kpis,
        })

    summary = calculate_canonical_kpis(tot_impr, tot_clicks, tot_spend, tot_conv, tot_rev)
    return {
        "rows_count": len(rows),
        "summary": summary,
        "rows": rows,
    }

