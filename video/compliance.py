"""Brand compliance and technical pre-flight QA engine for video projects."""
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, ConfigDict
from video.operations import EditOperation, EditPlan


class ComplianceFinding(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    code: str
    severity: Literal['error', 'warning', 'info']
    message: str
    clip_id: Optional[str] = None
    suggested_fix: Optional[str] = None
    time_range: Optional[Tuple[float, float]] = None


class VideoComplianceReport(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    passed: bool
    findings_count: int
    errors_count: int
    warnings_count: int
    findings: List[ComplianceFinding]
    summary: str


SAFE_ZONE_PROFILES = {
    'generic': {'top': 0.05, 'bottom': 0.05, 'left': 0.05, 'right': 0.05},
    'vertical-social': {'top': 0.14, 'bottom': 0.20, 'left': 0.06, 'right': 0.06},
    'square-social': {'top': 0.08, 'bottom': 0.08, 'left': 0.08, 'right': 0.08},
    'landscape-social': {'top': 0.05, 'bottom': 0.05, 'left': 0.05, 'right': 0.05},
}


class VideoComplianceEngine:
    """Verifies brand governance, safe zone margins, CTA timing, and audiovisual integrity."""

    @staticmethod
    def audit_project(
        project: Any,
        brand_profile: Optional[Dict[str, Any]] = None,
        context: Optional[Any] = None
    ) -> VideoComplianceReport:
        findings: List[ComplianceFinding] = []
        clips = getattr(project, 'clips', [])

        # Timeline duration
        primary_clips = [c for c in clips if c.kind == 'video']
        total_duration = sum(c.duration for c in primary_clips) if primary_clips else 0.0

        # Safe zone profile
        sz_name = getattr(project, 'safe_zone_profile', 'generic')
        sz = SAFE_ZONE_PROFILES.get(sz_name, SAFE_ZONE_PROFILES['generic'])

        # 1. Primary video check
        if not primary_clips:
            findings.append(ComplianceFinding(
                code='NO_PRIMARY_FOOTAGE',
                severity='error',
                message='Project has no primary video clips on the timeline.'
            ))

        # 2. Safe zone audits for titles and overlays
        for c in clips:
            if c.kind in {'title', 'overlay'}:
                # Check vertical bounds
                if c.y < sz['top']:
                    findings.append(ComplianceFinding(
                        code='SAFE_ZONE_TOP_BREACH',
                        severity='warning',
                        message=f"Element '{c.kind}' (y={c.y:.2f}) breaches top safe zone margin ({sz['top']*100:.0f}%).",
                        clip_id=c.id,
                        suggested_fix=f"Adjust y position to at least {sz['top']:.2f}",
                        time_range=(c.start, c.start + c.duration)
                    ))
                elif c.y > (1.0 - sz['bottom']):
                    findings.append(ComplianceFinding(
                        code='SAFE_ZONE_BOTTOM_BREACH',
                        severity='warning',
                        message=f"Element '{c.kind}' (y={c.y:.2f}) breaches bottom safe zone margin ({(1.0-sz['bottom'])*100:.0f}%).",
                        clip_id=c.id,
                        suggested_fix=f"Adjust y position to at most {1.0 - sz['bottom']:.2f}",
                        time_range=(c.start, c.start + c.duration)
                    ))

                # Check horizontal bounds
                if c.x < sz['left'] or c.x > (1.0 - sz['right']):
                    findings.append(ComplianceFinding(
                        code='SAFE_ZONE_SIDE_BREACH',
                        severity='warning',
                        message=f"Element '{c.kind}' (x={c.x:.2f}) extends beyond horizontal safe margin.",
                        clip_id=c.id,
                        suggested_fix="Center x position to 0.5",
                        time_range=(c.start, c.start + c.duration)
                    ))

        # 3. Logo compliance
        logo_asset_id = (brand_profile or {}).get('logo_asset_id')
        if logo_asset_id:
            logo_overlays = [c for c in clips if c.kind == 'overlay' and c.asset_id == logo_asset_id]
            if not logo_overlays:
                findings.append(ComplianceFinding(
                    code='BRAND_LOGO_MISSING',
                    severity='warning',
                    message=f"Brand '{brand_profile.get('brand_name', 'Client')}' logo is not present on the timeline.",
                    suggested_fix="Add official brand logo overlay in the corner"
                ))

        # 4. CTA presence and timing
        cta_clips = [c for c in clips if c.kind == 'title' and getattr(c, 'text_role', '') == 'cta']
        cta_required = bool((brand_profile or {}).get('cta') or (context and getattr(context, 'cta', '')))
        if cta_required and total_duration > 3.0:
            if not cta_clips:
                findings.append(ComplianceFinding(
                    code='CTA_MISSING',
                    severity='warning',
                    message='Campaign requires a call-to-action (CTA), but no CTA title or end card is present.',
                    suggested_fix='Add end card or CTA title in final 3 seconds'
                ))
            else:
                for cta_c in cta_clips:
                    # CTA should appear in final 30% of timeline
                    if cta_c.start < (total_duration * 0.6):
                        findings.append(ComplianceFinding(
                            code='CTA_TIMING_PREMATURE',
                            severity='info',
                            message=f"CTA appears at {cta_c.start:.1f}s; standard practice places the CTA in the final third of the video.",
                            clip_id=cta_c.id,
                            suggested_fix=f"Shift CTA start to {total_duration * 0.7:.1f}s",
                            time_range=(cta_c.start, cta_c.start + cta_c.duration)
                        ))

        # 5. Prohibited wording check
        prohibited_words = (brand_profile or {}).get('prohibited_language') or []
        if context and getattr(context, 'prohibited_language', None):
            prohibited_words.extend(context.prohibited_language)

        for c in clips:
            if c.kind == 'title' and c.text:
                t_lower = c.text.lower()
                for pw in prohibited_words:
                    if pw.lower() in t_lower:
                        findings.append(ComplianceFinding(
                            code='PROHIBITED_WORDING',
                            severity='error',
                            message=f"Title contains prohibited marketing wording '{pw}'.",
                            clip_id=c.id,
                            suggested_fix="Replace with approved claim wording",
                            time_range=(c.start, c.start + c.duration)
                        ))

        # 6. Audio presence check
        has_audio_track = any(c.kind == 'audio' for c in clips)
        if not has_audio_track:
            findings.append(ComplianceFinding(
                code='AUDIO_EMPTY_WARNING',
                severity='info',
                message='Timeline contains no dedicated background music or voiceover audio track.',
                suggested_fix='Add licensed background track or voiceover'
            ))

        # 7. Arabic RTL font alignment check
        for c in clips:
            if c.kind == 'title' and c.text:
                if any('\u0600' <= char <= '\u06ff' for char in c.text):
                    if c.font != 'arabic':
                        findings.append(ComplianceFinding(
                            code='ARABIC_FONT_MISMATCH',
                            severity='warning',
                            message="Arabic text detected in title, but font is not set to 'arabic'.",
                            clip_id=c.id,
                            suggested_fix="Set font='arabic' for correct HarfBuzz shaping"
                        ))

        errors = [f for f in findings if f.severity == 'error']
        warnings = [f for f in findings if f.severity == 'warning']

        passed = len(errors) == 0
        summary = f"Audit {'PASSED' if passed else 'FAILED'}: {len(errors)} error(s), {len(warnings)} warning(s)."

        return VideoComplianceReport(
            passed=passed,
            findings_count=len(findings),
            errors_count=len(errors),
            warnings_count=len(warnings),
            findings=findings,
            summary=summary
        )

    @classmethod
    def generate_compliance_repairs(cls, report: VideoComplianceReport, project: Any) -> EditPlan:
        """Construct automated repair operations to resolve non-destructive compliance warnings."""
        ops: List[EditOperation] = []
        sz_name = getattr(project, 'safe_zone_profile', 'generic')
        sz = SAFE_ZONE_PROFILES.get(sz_name, SAFE_ZONE_PROFILES['generic'])

        for f in report.findings:
            if f.code == 'SAFE_ZONE_BOTTOM_BREACH' and f.clip_id:
                ops.append(EditOperation(
                    operation_type='SET_POSITION',
                    target_id=f.clip_id,
                    parameters={'y': round(1.0 - sz['bottom'] - 0.04, 2)},
                    reason='Push element upwards into compliant safe zone',
                    source='rule_engine'
                ))
            elif f.code == 'SAFE_ZONE_TOP_BREACH' and f.clip_id:
                ops.append(EditOperation(
                    operation_type='SET_POSITION',
                    target_id=f.clip_id,
                    parameters={'y': round(sz['top'] + 0.04, 2)},
                    reason='Push element downwards into compliant safe zone',
                    source='rule_engine'
                ))
            elif f.code == 'ARABIC_FONT_MISMATCH' and f.clip_id:
                ops.append(EditOperation(
                    operation_type='UPDATE_TITLE',
                    target_id=f.clip_id,
                    parameters={'font': 'arabic'},
                    reason='Apply Cairo/Arabic font family for RTL text',
                    source='rule_engine'
                ))
            elif f.code == 'CTA_MISSING':
                ops.append(EditOperation(
                    operation_type='ADD_END_CARD',
                    parameters={'cta_text': 'Learn More', 'duration': 3.0},
                    reason='Add compliant final Call-To-Action end card',
                    source='rule_engine'
                ))

        return EditPlan(
            plan_version='1.0',
            intent='Compliance Pre-Flight Repair',
            operations=ops,
            assumptions=['Auto-repairs applied safe-zone position adjustments and default end card.'],
            requires_approval=True
        )

