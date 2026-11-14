"""Keyframe track evaluation and interpolation engine."""
from __future__ import annotations

from typing import Any, List, Optional
from .easing import evaluate_easing
from .schemas import Keyframe
from .colors import parse_color, to_hex


class KeyframeTrack:
    """Evaluates an animated property across a sequence of timed keyframes."""

    def __init__(
        self,
        property_name: str = "",
        keyframes: Optional[List[Keyframe]] = None,
        default_value: Any = 0.0
    ):
        self.property_name = property_name
        self.keyframes = keyframes or []
        self.default_value = default_value

    def evaluate(self, *args, **kwargs) -> Any:
        if isinstance(self, list):
            keyframes = self
            t = args[0] if len(args) > 0 else kwargs.get("t", 0.0)
            def_val = args[1] if len(args) > 1 else kwargs.get("default_value", 0.0)
            return KeyframeTrack._evaluate_list(keyframes, t, def_val)

        t = args[0] if len(args) > 0 else kwargs.get("t", 0.0)
        def_val = args[1] if len(args) > 1 else kwargs.get("default_value", self.default_value)
        return KeyframeTrack._evaluate_list(self.keyframes, t, def_val)

    @staticmethod
    def _evaluate_list(keyframes: List[Keyframe], t: float, default_value: Any) -> Any:
        if not keyframes:
            return default_value
        if len(keyframes) == 1:
            return keyframes[0].value

        # Sort keyframes by time
        sorted_kfs = sorted(keyframes, key=lambda k: k.time)

        # Before first keyframe
        if t <= sorted_kfs[0].time:
            return sorted_kfs[0].value
        # After last keyframe
        if t >= sorted_kfs[-1].time:
            return sorted_kfs[-1].value

        # Find enclosing pair
        for i in range(len(sorted_kfs) - 1):
            k1 = sorted_kfs[i]
            k2 = sorted_kfs[i + 1]
            if k1.time <= t <= k2.time:
                span = k2.time - k1.time
                if span <= 0:
                    return k2.value
                alpha = (t - k1.time) / span
                eased_alpha = evaluate_easing(k2.easing, alpha)

                # Numeric interpolation
                if isinstance(k1.value, (int, float)) and isinstance(k2.value, (int, float)):
                    return k1.value + (k2.value - k1.value) * eased_alpha

                # Color interpolation
                if isinstance(k1.value, str) and (k1.value.startswith("#") or "rgb" in k1.value):
                    c1 = parse_color(k1.value)
                    c2 = parse_color(k2.value)
                    r = int(c1[0] + (c2[0] - c1[0]) * eased_alpha)
                    g = int(c1[1] + (c2[1] - c1[1]) * eased_alpha)
                    b = int(c1[2] + (c2[2] - c1[2]) * eased_alpha)
                    a = int(c1[3] + (c2[3] - c1[3]) * eased_alpha)
                    return to_hex((r, g, b, a))

                return k1.value if alpha < 0.5 else k2.value

        return default_value
