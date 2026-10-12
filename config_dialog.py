"""Settings window shown by Windows for the screensaver's "Settings" button."""
import tkinter as tk
from tkinter import ttk

import settings

CHOICES = [  # (key, label)
    ("water", "Water color"),
    ("light", "Lighting (auto follows your clock)"),
    ("quality", "Quality"),
    ("upscaling", "Upscaling (AMD FSR 1.0)"),
]
SLIDERS = [  # (key, label, from, to, decimals)
    ("fish", "Number of fish", 5, 200, 0),
    ("fish_scale", "Fish size", 0.6, 3.0, 2),
    ("jellyfish", "Jellyfish", 0, 8, 0),
    ("bloom", "Bloom (glow)", 0.0, 1.0, 2),
    ("vignette", "Vignette", 0.0, 1.0, 2),
    ("dof", "Depth of field", 0.0, 1.0, 2),
    ("lens", "Lens fringing and film grain", 0.0, 1.0, 2),
    ("sharpness", "FSR sharpening (0 = sharpest)", 0.0, 2.0, 2),
]
CHECKS = [
    ("shark", "An occasional shark patrols the far water"),
    ("bubbles", "Bubble streams"),
    ("camera_drift", "Slow camera drift"),
    ("raytracing", "Ray-traced shadows, caustics, AO, light shafts and water mirror"),
    ("taa", "Temporal anti-aliasing"),
]


def show():
    cfg = settings.load()
    root = tk.Tk()
    root.title("Aquarium Screensaver Settings")
    root.resizable(False, False)
    frm = ttk.Frame(root, padding=14)
    frm.grid()

    vars_ = {}
    row = 0
    for key, label in CHOICES:
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=3)
        vars_[key] = tk.StringVar(value=cfg[key])
        ttk.Combobox(frm, textvariable=vars_[key], values=settings.CHOICES[key],
                     state="readonly", width=14).grid(row=row, column=1, sticky="w", padx=8)
        row += 1

    for key, label, lo, hi, dec in SLIDERS:
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=3)
        var = tk.DoubleVar(value=cfg[key])
        vars_[key] = var
        ttk.Scale(frm, from_=lo, to=hi, variable=var, length=220).grid(row=row, column=1, padx=8)
        val = ttk.Label(frm, width=5)
        val.grid(row=row, column=2, sticky="e")

        def refresh(*_a, var=var, val=val, dec=dec):
            val.config(text=f"{var.get():.{dec}f}")
        var.trace_add("write", refresh)
        refresh()
        row += 1

    for key, label in CHECKS:
        vars_[key] = tk.BooleanVar(value=cfg[key])
        ttk.Checkbutton(frm, text=label, variable=vars_[key]).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=2)
        row += 1

    def reset():
        for k, v in settings.DEFAULTS.items():
            vars_[k].set(v)

    def ok():
        settings.save({k: v.get() for k, v in vars_.items()})
        settings.save(settings.load())   # round-trip so values are clamped and typed
        root.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=row, column=0, columnspan=3, sticky="e", pady=(12, 0))
    ttk.Button(btns, text="Reset to defaults", command=reset).pack(side="left", padx=4)
    ttk.Button(btns, text="OK", command=ok).pack(side="left", padx=4)
    ttk.Button(btns, text="Cancel", command=root.destroy).pack(side="left", padx=4)
    root.mainloop()
