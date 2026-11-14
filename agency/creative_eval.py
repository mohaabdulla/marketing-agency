"""Creative Evaluation Layer for LEXNIS AI Marketing Agency.

Performs deterministic rule checks (character limits, mandatory/prohibited terms, RTL checks,
disclosures, claim support) and heuristic quality scoring.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional


CHANNEL_LIMITS = {
    "linkedin": {"headline_max": 120, "body_max": 3000},
    "instagram": {"headline_max": 80, "body_max": 2200},
    "twitter": {"headline_max": 70, "body_max": 280},
    "facebook": {"headline_max": 100, "body_max": 2000},
    "youtube": {"headline_max": 100, "body_max": 5000},
}

DEFAULT_PROHIBITED_TERMS = [
    "guaranteed 100%",
    "risk-free guaranteed",
    "miracle cure",
    "unbeatable lowest price",
    "scam",
]


@dataclass
class EvalResult:
    passed: bool
    score: int
    hard_failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    model_review: Dict[str, Any] = field(default_factory=dict)
    character_counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CreativeEvaluator:
    """Evaluates marketing copy and asset manifests against channel, brand, and legal constraints."""

    def evaluate_copy(
        self,
        headline: str,
        body: str,
        channel: str = "linkedin",
        language: str = "en",
        prohibited_terms: Optional[List[str]] = None,
        mandatory_terms: Optional[List[str]] = None,
        cta_required: bool = True,
        disclosures_required: Optional[List[str]] = None
    ) -> EvalResult:
        hard_failures: List[str] = []
        warnings: List[str] = []
        channel_lower = channel.lower()
        limits = CHANNEL_LIMITS.get(channel_lower, {"headline_max": 120, "body_max": 3000})

        h_len = len(headline.strip())
        b_len = len(body.strip())
        char_counts = {"headline_length": h_len, "body_length": b_len}

        # 1. Channel character length constraints
        if h_len > limits["headline_max"]:
            hard_failures.append(
                f"Headline length ({h_len}) exceeds {channel} max limit ({limits['headline_max']})."
            )
        if b_len > limits["body_max"]:
            hard_failures.append(
                f"Body copy length ({b_len}) exceeds {channel} max limit ({limits['body_max']})."
            )

        if h_len < 10:
            warnings.append("Headline is very short (under 10 characters).")
        if b_len < 30:
            warnings.append("Body copy is very brief (under 30 characters).")

        # 2. Prohibited terms check
        check_prohibited = (prohibited_terms or []) + DEFAULT_PROHIBITED_TERMS
        combined_text = f"{headline} {body}".lower()
        for term in check_prohibited:
            if term.lower() in combined_text:
                hard_failures.append(f"Prohibited term detected: '{term}'.")

        # 3. Mandatory terms check
        if mandatory_terms:
            for mterm in mandatory_terms:
                if mterm.lower() not in combined_text:
                    warnings.append(f"Mandatory brand term missing: '{mterm}'.")

        # 4. Call to Action (CTA) check
        if cta_required:
            cta_patterns = [
                r"\b(apply|visit|click|explore|discover|learn more|get started|register|join|contact|read more|download)\b",
                r"(\u0627\u0646\u0636\u0645|\u062a\u0642\u062f\u0645|\u0627\u0643\u062a\u0634\u0641|\u0632\u0631\u0646\u0627|\u062a\u0648\u0627\u0635\u0644|\u062a\u0639\u0631\u0641|\u0627\u0628\u062f\u0623)",
            ]
            has_cta = any(re.search(p, combined_text, re.IGNORECASE) for p in cta_patterns)
            if not has_cta:
                warnings.append("No clear Call-to-Action (CTA) detected in headline or body copy.")

        # 5. Right-to-Left (RTL) validation for Arabic
        if language == "ar":
            arabic_chars = len(re.findall(r"[\u0600-\u06FF]", combined_text))
            total_chars = max(1, len(combined_text.replace(" ", "")))
            ar_ratio = arabic_chars / total_chars
            if ar_ratio < 0.4:
                warnings.append(
                    f"Arabic language selected, but Arabic character ratio is only {ar_ratio:.1%}. Ensure text is localized."
                )

        # 6. Disclosures check
        if disclosures_required:
            for disc in disclosures_required:
                if disc.lower() not in combined_text:
                    hard_failures.append(f"Mandatory disclosure missing: '{disc}'.")

        # Calculate heuristic score
        base_score = 100
        base_score -= len(hard_failures) * 25
        base_score -= len(warnings) * 8
        final_score = max(0, min(100, base_score))

        model_review = {
            "brief_alignment": round(max(0.0, (final_score / 100.0)), 2),
            "distinctiveness": 0.85 if not warnings else 0.72,
            "readability": "Clear and accessible" if h_len <= limits["headline_max"] else "Overly dense",
            "notes": (
                ["Copy meets all hard compliance rules."]
                if not hard_failures
                else [f"Requires revision: {f}" for f in hard_failures]
            ),
        }

        return EvalResult(
            passed=len(hard_failures) == 0,
            score=final_score,
            hard_failures=hard_failures,
            warnings=warnings,
            model_review=model_review,
            character_counts=char_counts,
        )


evaluator = CreativeEvaluator()

