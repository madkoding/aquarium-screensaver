# Aquarium Screensaver

A real-time 3D aquarium screensaver for Windows, written in Python with OpenGL. Every fish is generated from code (no model files), schools swim as one continuous world across all your monitors, and the lighting follows your clock.

![Three monitors](docs/screenshot.png)

*Real capture from a 3-monitor setup (a central ultrawide plus two portrait displays).*

| Fish up close | At night |
|---|---|
| ![Detail](docs/detail.png) | ![Night](docs/night.png) |

## Features

- **Fully procedural 3D fish:** one parametric mesh (lofted body, forked tail, dorsal, anal and pectoral fins) is animated in the vertex shader with a wave that travels from head to tail. Species differ only by parameters: proportions, fin sizes, colors and skin pattern.
- **Six species:** neon tetras, clownfish, blue tangs, angelfish, tuna, and an occasional shark patrolling the far water.
- **Schooling behavior:** every school follows a roaming waypoint and its members apply boid rules (cohesion, alignment, separation) with soft tank bounds, so groups turn and cross the screen together.
- **One continuous world:** a single perspective camera covers the whole virtual desktop, so fish swim from one monitor to the next. Mixed sizes and orientations work.
- **Underwater look:** animated caustics on the sand, god rays, depth fog that absorbs red first, bubble streams, drifting marine snow, swaying seaweed, rocks, coral heads, and translucent pulsing jellyfish.
- **Day, dusk and night:** lighting follows your clock (or pick one). At night the neon tetras glow.
- **Bloom, vignette, MSAA and de-banding dither** for a clean image, with three quality levels.
- **Settings dialog** and a live **preview** in the Windows screensaver picker.
- **Paced to your displays:** frames are capped at the fastest monitor's refresh rate (60, 75, 144 Hz...) and drop to 30 FPS on battery. Display hot-plugging is detected automatically.
- Exits on any key press, click, or mouse movement.

## Download

Grab `Aquarium.scr` from the [latest release](../../releases/latest), then right-click it and choose **Install**. Windows opens the screensaver picker with it already selected; use **Settings...** there to tweak the scene.

> The file is not code-signed (that needs a paid certificate), so Windows SmartScreen or an antivirus may warn about it, as is common with PyInstaller executables. You can inspect the source here and build it yourself.

Requires a GPU with **OpenGL 3.3** or newer.

## Settings

Open **Settings...** in the screensaver picker. Values are stored in `%APPDATA%\AquariumScreensaver\settings.json`.

| Setting | What it does |
|---|---|
| `water` | Water color: tropical, deep, lagoon, aegean. |
| `light` | `auto` (follows your clock), `day`, `dusk` or `night`. |
| `quality` | `low` (no MSAA, 75% resolution), `medium` (2x MSAA), `high` (4x MSAA). |
| `fish` | Total number of fish (5 to 200). |
| `fish_scale` | Fish size multiplier. |
| `jellyfish` | Number of jellyfish (0 to 8). |
| `shark` | Let an occasional shark patrol the far water. |
| `bubbles` | Bubble streams. |
| `bloom` / `vignette` | Glow strength and corner darkening. |
| `camera_drift` | Slow, subtle camera sway. |

## Build from source

Requires Windows and Python 3.10+.

```powershell
python -m pip install -r requirements.txt pyinstaller
.\build.ps1
```

This produces `Aquarium.scr`. Pushing a `v*` tag runs the GitHub Actions workflow in `.github/workflows/release.yml`, which builds it and attaches it to the release.

### Run directly from Python

```powershell
python aquarium_saver.py /s
```

Dev flags:

| Flag | Effect |
|---|---|
| `--seconds N` | Exit after N seconds and ignore input. |
| `--shot FILE` | Save a screenshot right before exiting. |
| `--at SECONDS` | Pre-simulate this long so the schools have spread out (for screenshots). |

Example: `python aquarium_saver.py /s --seconds 6 --at 25 --shot capture.png`

> Notes: launching a `.scr` through `Start-Process` or double-click makes Windows append `/S` and drop your arguments, so run it directly from a shell. Git Bash rewrites `/p` into a drive path; set `MSYS_NO_PATHCONV=1` there.

## How it works

| File | Role |
|---|---|
| `aquarium_saver.py` | Entry point: argument parsing (`/s`, `/c`, `/p`), main loop, frame pacing, hot-plug and battery handling. |
| `renderer.py` | OpenGL pipeline: scene pass (MSAA), bloom chain, final composite. |
| `shaders.py` | All GLSL: fish animation and skin patterns, caustics, fog, seaweed, jellyfish, bubbles, god rays. |
| `meshes.py` | Procedural geometry: fish, seaweed ribbons, rocks, coral, seabed, jellyfish. |
| `sim.py` | Species table, boid schooling, shark patrol and jellyfish motion. |
| `world.py` | Camera, projection and the seabed height function shared by the CPU and the shaders. |
| `settings.py` / `config_dialog.py` | Defaults, JSON persistence and the Tk settings window. |
| `winapi.py` | Monitors with per-monitor DPI, refresh rate, power status, single instance, preview embedding. |

- A `.scr` is just a renamed `.exe`; Windows launches it with `/s` (run), `/c` (configure) or `/p HWND` (preview). [PyInstaller](https://pyinstaller.org) packages the script.
- Fish are drawn with one instanced draw call. The vertex shader scales fins about their base, flaps the pectorals, and bends the spine with a head-to-tail traveling wave plus a turn-dependent curve.
- Skin patterns (neon stripe, clownfish bands, tang palette, angelfish bars, shark counter-shading) are evaluated per pixel from the mesh's `(length, around)` coordinates, and the eyes are drawn procedurally.
- The scene renders into a 16-bit float target, so bloom and fog gradients stay smooth; a tiny dither in the final pass removes banding.
- The simulation costs about 2 ms per frame for 60 fish; everything else runs on the GPU.

## Requirements

- Windows 10/11 with an OpenGL 3.3 capable GPU
- Python 3.10+, `pygame-ce`, `numpy`, `moderngl` (only to run from source)
