"""Easing functions and interpolation curves for creative animations."""
from __future__ import annotations

import math
from typing import Callable, Dict


def linear(t: float) -> float:
    return t


def ease_in_quad(t: float) -> float:
    return t * t


def ease_out_quad(t: float) -> float:
    return t * (2.0 - t)


def ease_in_out_quad(t: float) -> float:
    return 2.0 * t * t if t < 0.5 else -1.0 + (4.0 - 2.0 * t) * t


def ease_in_cubic(t: float) -> float:
    return t * t * t


def ease_out_cubic(t: float) -> float:
    t -= 1.0
    return t * t * t + 1.0


def ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4.0 * t * t * t
    t -= 1.0
    return (t) * (2.0 * t) * (2.0 * t) + 1.0


def overshoot(t: float, s: float = 1.70158) -> float:
    """Back ease-out with slight overshoot."""
    t -= 1.0
    return t * t * ((s + 1.0) * t + s) + 1.0


def spring(t: float) -> float:
    """Soft damped spring-like bounce."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return math.pow(2.0, -10.0 * t) * math.sin((t - 0.075) * (2.0 * math.pi) / 0.3) + 1.0


def hold(t: float) -> float:
    return 0.0 if t < 1.0 else 1.0


EASING_MAP: Dict[str, Callable[[float], float]] = {
    "linear": linear,
    "ease_in": ease_in_cubic,
    "ease_out": ease_out_cubic,
    "ease_in_out": ease_in_out_cubic,
    "cubic": ease_in_out_cubic,
    "overshoot": overshoot,
    "spring": spring,
    "hold": hold,
}

EASING_FUNCTIONS = list(EASING_MAP.keys())


def evaluate_easing(name: str, t: float) -> float:
    """Evaluate easing progress (0.0 to 1.0) given curve name."""
    t_clamped = max(0.0, min(1.0, float(t)))
    func = EASING_MAP.get(name.lower().replace("-", "_"), ease_out_cubic)
    return func(t_clamped)
