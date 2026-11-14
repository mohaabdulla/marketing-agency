"""Sanitized and bounded compilation of brand guidelines, briefs, claims, and timeline context."""
import hashlib
import json
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class VideoEditContext(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    brand_id: Optional[str] = None
    brand_name: str = 'General'
    brand_colors: Dict[str, str] = Field(default_factory=dict)
    fonts: Dict[str, str] = Field(default_factory=dict)
    logo_asset_id: Optional[str] = None

    creative_brief_id: Optional[str] = None
    campaign_objective: str = ''
    target_audience: str = ''
    primary_message: str = ''
    supporting_messages: List[str] = Field(default_factory=list)
    cta: str = ''

    approved_claims: List[Dict[str, Any]] = Field(default_factory=list)
    prohibited_language: List[str] = Field(default_factory=list)
    legal_disclosures: List[str] = Field(default_factory=list)

    language: str = 'en'
    platform_target: str = 'general'
    target_duration: float = 15.0
    aspect_ratio: str = '16:9'

    user_instruction: str = ''
    media_analysis_summaries: List[Dict[str, Any]] = Field(default_factory=list)
    current_timeline_summary: Dict[str, Any] = Field(default_factory=dict)
    context_hash: str = ''


def compile_video_edit_context(
    project: Any,
    user_instruction: str = '',
    brand_profile: Optional[Dict[str, Any]] = None,
    brief_data: Optional[Dict[str, Any]] = None,
    media_analyses: Optional[List[Dict[str, Any]]] = None,
    platform_target: str = 'general',
    target_duration: Optional[float] = None,
    language: str = 'en'
) -> VideoEditContext:
    """Compile structured, bounded edit context from disparate agency inputs without prompt injection vulnerability."""
    brand_id = project.brand_id if hasattr(project, 'brand_id') else None
    b_name = 'Enterprise'
    colors = {'primary': '#131724', 'accent': '#53B849'}
    logo_id = None

    if brand_profile:
        b_name = brand_profile.get('brand_name') or brand_profile.get('name') or b_name
        if 'brand_colors' in brand_profile and isinstance(brand_profile['brand_colors'], dict):
            colors.update(brand_profile['brand_colors'])
        logo_id = brand_profile.get('logo_asset_id') or brand_profile.get('logo_id')

    # Extract brief fields
    brief_data = brief_data or {}
    objective = str(brief_data.get('campaign_objective', brief_data.get('objective', ''))).strip()[:300]
    audience = str(brief_data.get('target_audience', brief_data.get('audience', ''))).strip()[:200]
    p_msg = str(brief_data.get('primary_message', '')).strip()[:500]
    s_msgs = [str(m).strip()[:200] for m in brief_data.get('supporting_messages', [])][:5]
    cta_text = str(brief_data.get('cta', 'Learn More')).strip()[:100]

    approved_claims = brief_data.get('approved_claims', [])
    prohibited = brief_data.get('prohibited_language', ['unverified', 'guaranteed 100%'])
    disclosures = brief_data.get('legal_disclosures', [])

    # Summarize current timeline
    clips_summary = []
    total_dur = 0.0
    for c in getattr(project, 'clips', []):
        clips_summary.append({
            'id': c.id,
            'kind': c.kind,
            'duration': c.duration,
            'start': c.start,
            'text': c.text if c.kind == 'title' else None,
            'audio_role': getattr(c, 'audio_role', 'dialogue'),
        })
        if c.kind == 'video':
            total_dur += c.duration

    current_summary = {
        'total_duration': round(total_dur, 2),
        'clips_count': len(project.clips) if hasattr(project, 'clips') else 0,
        'clips': clips_summary[:20],
        'canvas': {
            'width': project.canvas.width,
            'height': project.canvas.height,
            'fps': project.canvas.fps
        } if hasattr(project, 'canvas') else {}
    }

    # Bounded summaries of media analysis
    analysis_summaries = []
    if media_analyses:
        for ma in media_analyses[:6]:
            shots_brief = []
            for s in ma.get('shots', [])[:8]:
                shots_brief.append({
                    'shot_id': s.get('shot_id'),
                    'duration': s.get('duration'),
                    'brightness': s.get('brightness'),
                    'contrast': s.get('contrast'),
                })
            analysis_summaries.append({
                'asset_id': ma.get('asset_id'),
                'duration': ma.get('duration'),
                'shots_count': len(ma.get('shots', [])),
                'shots': shots_brief,
                'silence_percentage': ma.get('audio_metrics', {}).get('silence_percentage', 0.0)
            })

    # Duration calculation
    computed_duration = target_duration or (total_dur if total_dur > 0 else 15.0)

    # Sanitize user instruction (untrusted text)
    safe_instruction = str(user_instruction or '').strip()[:800]

    ctx_payload = {
        'brand_name': b_name,
        'objective': objective,
        'instruction': safe_instruction,
        'duration': computed_duration,
        'timeline': current_summary
    }
    raw_hash = json.dumps(ctx_payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
    ctx_hash = hashlib.sha256(raw_hash).hexdigest()[:16]

    return VideoEditContext(
        brand_id=brand_id,
        brand_name=b_name,
        brand_colors=colors,
        fonts={'heading': 'Montserrat-Bold', 'body': 'Inter'},
        logo_asset_id=logo_id,
        creative_brief_id=brief_data.get('id'),
        campaign_objective=objective,
        target_audience=audience,
        primary_message=p_msg,
        supporting_messages=s_msgs,
        cta=cta_text,
        approved_claims=approved_claims,
        prohibited_language=prohibited,
        legal_disclosures=disclosures,
        language=language,
        platform_target=platform_target,
        target_duration=round(computed_duration, 2),
        aspect_ratio='16:9' if project.canvas.width >= project.canvas.height else '9:16',
        user_instruction=safe_instruction,
        media_analysis_summaries=analysis_summaries,
        current_timeline_summary=current_summary,
        context_hash=ctx_hash,
    )

