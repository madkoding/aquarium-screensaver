"""Thin-film iridescence for the fish skin.

Pure CPU reference of the colour term the fish shader adds. It has no
dependencies so it can be unit tested with the standard library. The shader
uses the same formula, so the numbers here are what the test checks.
"""
import math

TWO_PI = 6.2831853
# Phase offset per RGB channel: the spread that produces the rainbow sheen.
CHANNEL_OFFSETS = (0.0, 0.33, 0.67)
# Time scale: the sheen drifts slowly, it must not look like neon.
TIME_RATE = 0.05


def _clamp01(x):
    return min(max(x, 0.0), 1.0)


def iridescence_rgb(ndv, t):
    """Thin-film colour for a view angle (ndv in [0, 1]) and a time t.

    Each channel is in [0, 1].
    """
    ndv = _clamp01(ndv)
    phase = TWO_PI * (ndv * 1.2 + t * TIME_RATE)
    return tuple(0.5 + 0.5 * math.cos(phase + TWO_PI * off) for off in CHANNEL_OFFSETS)


def add_iridescence(base, ndv, t, strength=0.14, enabled=True):
    """Return base plus a faint thin-film sheen, scaled by the base colour.

    The term is additive and only shows at grazing angles. When disabled or
    when strength is 0, the base colour is returned unchanged.
    Every channel stays in [0, 1].
    """
    r, g, b = base
    if not enabled or strength <= 0.0:
        return (r, g, b)
    ndv = _clamp01(ndv)
    k = strength * (1.0 - ndv) ** 1.5
    irid = iridescence_rgb(ndv, t)
    return tuple(_clamp01(c + c * i * k) for c, i in zip((r, g, b), irid))
