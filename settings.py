"""User settings (JSON in %APPDATA%) and the scene's look-and-feel tables."""
import json
import os

# name -> (day top color, day bottom color), linear-ish 0..1
WATER = {
    "tropical": ((0.10, 0.58, 0.78), (0.01, 0.12, 0.26)),
    "deep": ((0.04, 0.30, 0.55), (0.0, 0.04, 0.14)),
    "lagoon": ((0.12, 0.62, 0.55), (0.01, 0.16, 0.20)),
    "aegean": ((0.08, 0.50, 0.82), (0.01, 0.10, 0.32)),
}
# AMD FSR 1.0 upscaling: name -> how many times fewer pixels per axis are rendered
UPSCALE_RATIO = {"off": 1.0, "quality": 1.5, "balanced": 1.7, "performance": 2.0}
QUALITY = {   # name -> (MSAA samples, render scale)
    "low": (0, 0.75),
    "medium": (2, 1.0),
    "high": (4, 1.0),
}

DEFAULTS = {
    "water": "tropical",
    "quality": "medium",
    "light": "auto",          # auto (follows the clock) | day | dusk | night
    "fish": 60,               # 5..200 total fish
    "fish_scale": 1.5,        # 0.6..3.0 fish size multiplier
    "jellyfish": 3,           # 0..8
    "shark": True,            # an occasional shark patrols the far water
    "bubbles": True,
    "bloom": 0.35,            # 0..1
    "vignette": 0.30,         # 0..1
    "camera_drift": True,     # slow, subtle camera sway
    "raytracing": True,       # traced shadows, caustics, light shafts, water mirror
    "upscaling": "off",       # off | quality (1.5x) | balanced (1.7x) | performance (2x), AMD FSR 1.0
    "sharpness": 0.2,         # 0..2 FSR sharpening in stops (0 = sharpest, AMD default 0.2)
}
RANGES = {
    "fish": (5, 200), "fish_scale": (0.6, 3.0), "jellyfish": (0, 8),
    "bloom": (0.0, 1.0), "vignette": (0.0, 1.0), "sharpness": (0.0, 2.0),
}
CHOICES = {
    "water": list(WATER), "quality": list(QUALITY),
    "light": ["auto", "day", "dusk", "night"],
    "upscaling": list(UPSCALE_RATIO),
}


def settings_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "AquariumScreensaver", "settings.json")


def load():
    """Defaults overlaid with whatever valid values the JSON file contains."""
    cfg = dict(DEFAULTS)
    try:
        with open(settings_path(), encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return cfg
    if not isinstance(raw, dict):
        return cfg
    for key, default in DEFAULTS.items():
        val = raw.get(key)
        if val is None:
            continue
        if isinstance(default, bool):
            if isinstance(val, bool):
                cfg[key] = val
        elif key in CHOICES:
            if val in CHOICES[key]:
                cfg[key] = val
        elif isinstance(val, (int, float)) and not isinstance(val, bool):
            lo, hi = RANGES[key]
            val = min(hi, max(lo, val))
            cfg[key] = int(round(val)) if isinstance(default, int) else float(val)
    return cfg


def save(cfg):
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
