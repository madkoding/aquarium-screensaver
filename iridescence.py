"""Metallic, fluorescent thin-film iridescence for the fish skin.

Pure CPU reference of the colour term the fish shader adds. It has no
dependencies so it can be unit tested with the standard library. The shader gets
its constants from GLSL_CONSTS below, so the numbers here are the numbers it runs.

The look has two parts:
- metallic: a hue that shifts with the view angle and a flip-flop that sweeps
  bright, coloured highlights across the body, like a mirror tinted by the film;
- fluorescent: the hue is fully saturated and part of it glows on its own, so it
  stays vivid in shade and at night and feeds the bloom.
"""
import math

TWO_PI = 6.2831853
# Phase offset per RGB channel: the spread that produces the rainbow sheen.
CHANNEL_OFFSETS = (0.0, 0.33, 0.67)
TIME_RATE = 0.05          # hue drift per second
STRENGTH = 0.55           # additive, albedo-tinted metallic sheen
FACE_ON_FLOOR = 0.50      # share of the sheen that is still present looking straight at the skin
SATURATION_POWER = 1.7    # >1 pushes the pastel cosine palette toward pure, fluorescent hues
FLUOR = 0.40              # self-lit glow, independent of the light and of the base colour
METAL_BASE = 0.25         # sheen between the flip-flop highlights
METAL_PEAK = 2.20         # extra sheen at the flip-flop highlights
FLIP_RATE = 8.0           # flip-flop bands per unit of (n.v)
FLIP_NORMAL = 2.5         # how much the body's vertical normal shifts the bands
FLIP_TIME = 0.4           # flip-flop drift per second
MIRROR = 1.30             # coloured reflection of the surroundings (shader only: needs the probe grid)

GLSL_CONSTS = "\n".join([
    "const float IRID_STRENGTH = %.3f;" % STRENGTH,
    "const float IRID_FACE_FLOOR = %.3f;" % FACE_ON_FLOOR,
    "const float IRID_SAT_POWER = %.3f;" % SATURATION_POWER,
    "const float IRID_FLUOR = %.3f;" % FLUOR,
    "const float IRID_METAL_BASE = %.3f;" % METAL_BASE,
    "const float IRID_METAL_PEAK = %.3f;" % METAL_PEAK,
    "const float IRID_FLIP_RATE = %.3f;" % FLIP_RATE,
    "const float IRID_FLIP_NORMAL = %.3f;" % FLIP_NORMAL,
    "const float IRID_FLIP_TIME = %.3f;" % FLIP_TIME,
    "const float IRID_MIRROR = %.3f;" % MIRROR,
    "const float IRID_TIME_RATE = %.3f;" % TIME_RATE,
    "",
])


def _clamp01(x):
    return min(max(x, 0.0), 1.0)


def iridescence_rgb(ndv, t):
    """Fully saturated thin-film colour for a view angle (ndv in [0, 1]) and a time t.

    Each channel is in [0, 1] and the brightest one is exactly 1.
    """
    ndv = _clamp01(ndv)
    phase = TWO_PI * (ndv * 1.2 + t * TIME_RATE)
    rgb = [(0.5 + 0.5 * math.cos(phase + TWO_PI * off)) ** SATURATION_POWER for off in CHANNEL_OFFSETS]
    peak = max(rgb) + 1e-4
    return tuple(c / peak for c in rgb)


def flip(ndv, t, ny=0.0):
    """Metallic flip-flop weight in [0, 1]: where the coloured highlights sit."""
    return 0.5 + 0.5 * math.sin(ndv * FLIP_RATE + ny * FLIP_NORMAL + t * FLIP_TIME)


def metal_weight(ndv, t, ny=0.0):
    """Sheen multiplier: a low floor plus sharp bright bands (the cube of the flip-flop)."""
    f = flip(ndv, t, ny)
    return METAL_BASE + METAL_PEAK * f * f * f


def add_iridescence(base, ndv, t, strength=STRENGTH, enabled=True, ny=0.0):
    """Return base plus the metallic sheen and the fluorescent glow.

    The metallic term is additive and tinted by the base colour; the fluorescent
    term does not depend on it. Both are strongest at grazing angles but still
    visible face-on, and every channel stays in [0, 1]. When disabled or when
    strength is 0, the base colour is returned unchanged.
    """
    r, g, b = base
    if not enabled or strength <= 0.0:
        return (r, g, b)
    ndv = _clamp01(ndv)
    face = FACE_ON_FLOOR + (1.0 - FACE_ON_FLOOR) * (1.0 - ndv)
    irid = iridescence_rgb(ndv, t)
    metal = strength * face * metal_weight(ndv, t, ny)
    glow = FLUOR * face * (strength / STRENGTH) * (0.35 + 0.65 * flip(ndv, t, ny))
    return tuple(_clamp01(c + c * i * metal + i * glow) for c, i in zip((r, g, b), irid))
