"""Pearlescent (nacre) iridescence for the fish skin.

Pure CPU reference of the colour term the fish shader adds. It has no
dependencies so it can be unit tested with the standard library. The shader gets
its constants from GLSL_CONSTS below, so the numbers here are the numbers it runs.

Real fish skin does not run through the whole rainbow: guanine crystals in the
scales reflect a narrow range of hues that shifts a little with the viewing angle,
and every scale catches the light slightly differently. So the look here is:
- two tones only, a cool cyan and a warm pink-lavender, blended by the view angle;
- still in time (nothing drifts, which is what makes it look like a hologram);
- strongest toward the silhouette and on the belly, present but weaker face-on;
- modulated per scale in the shader, so it reads as metal made of many small mirrors.
"""
import math

TWO_PI = 6.2831853
COOL = (0.30, 0.85, 1.00)     # nacre tone 1: cyan
WARM = (0.95, 0.55, 0.95)     # nacre tone 2: pink-lavender
STRENGTH = 0.62               # additive, albedo-tinted sheen
FACE_ON_FLOOR = 0.30          # share of the sheen that is still present looking straight at the skin
FLUOR = 0.12                  # faint self-lit glow, independent of the light and the base colour
METAL_BASE = 0.30             # sheen between the highlights
METAL_PEAK = 1.60             # extra sheen at the highlights
FLIP_RATE = 6.0               # highlight bands per unit of (n.v)
FLIP_NORMAL = 2.0             # how much the body's vertical normal shifts the bands
MIRROR = 0.60                 # coloured reflection of the surroundings (shader only: needs the probe grid)


def _vec3(name, v):
    return "const vec3 %s = vec3(%.3f, %.3f, %.3f);" % (name, *v)


GLSL_CONSTS = "\n".join([
    "const float IRID_STRENGTH = %.3f;" % STRENGTH,
    "const float IRID_FACE_FLOOR = %.3f;" % FACE_ON_FLOOR,
    "const float IRID_FLUOR = %.3f;" % FLUOR,
    "const float IRID_METAL_BASE = %.3f;" % METAL_BASE,
    "const float IRID_METAL_PEAK = %.3f;" % METAL_PEAK,
    "const float IRID_FLIP_RATE = %.3f;" % FLIP_RATE,
    "const float IRID_FLIP_NORMAL = %.3f;" % FLIP_NORMAL,
    "const float IRID_MIRROR = %.3f;" % MIRROR,
    _vec3("IRID_COOL", COOL),
    _vec3("IRID_WARM", WARM),
    "",
])


def _clamp01(x):
    return min(max(x, 0.0), 1.0)


def _smoothstep(a, b, x):
    t = _clamp01((x - a) / (b - a))
    return t * t * (3.0 - 2.0 * t)


def flip(ndv, ny=0.0):
    """Highlight band weight in [0, 1]: where the sheen sits across the body."""
    return 0.5 + 0.5 * math.sin(ndv * FLIP_RATE + ny * FLIP_NORMAL)


def iridescence_rgb(ndv, ny=0.0):
    """Nacre colour for a view angle (ndv in [0, 1]): a blend of two tones only.

    Each channel is in [0, 1]. It does not depend on time.
    """
    w = _smoothstep(0.15, 0.85, flip(_clamp01(ndv), ny))
    return tuple(c + (wm - c) * w for c, wm in zip(COOL, WARM))


def metal_weight(ndv, ny=0.0):
    """Sheen multiplier: a floor plus broad bright bands (the square of the band weight)."""
    f = flip(_clamp01(ndv), ny)
    return METAL_BASE + METAL_PEAK * f * f


def add_iridescence(base, ndv, strength=STRENGTH, enabled=True, ny=0.0):
    """Return base plus the pearlescent sheen and a faint glow.

    The sheen is additive and tinted by the base colour; the glow does not depend
    on it. Both are strongest at grazing angles but still present face-on, and every
    channel stays in [0, 1]. When disabled or when strength is 0, the base colour is
    returned unchanged.
    """
    r, g, b = base
    if not enabled or strength <= 0.0:
        return (r, g, b)
    ndv = _clamp01(ndv)
    face = FACE_ON_FLOOR + (1.0 - FACE_ON_FLOOR) * (1.0 - ndv)
    irid = iridescence_rgb(ndv, ny)
    metal = strength * face * metal_weight(ndv, ny)
    glow = FLUOR * face * (strength / STRENGTH) * (0.35 + 0.65 * flip(ndv, ny))
    return tuple(_clamp01(c + c * i * metal + i * glow) for c, i in zip((r, g, b), irid))
