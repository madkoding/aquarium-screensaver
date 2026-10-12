# Aquarium Screensaver

A real-time 3D aquarium screensaver for Windows, written in Python with OpenGL. Every fish is generated from code (no model files), schools swim as one continuous world across all your monitors, the lighting follows your clock, and shadows, caustics, light shafts, reflections and refractions are ray traced.

![Three monitors](docs/screenshot.png)

*Real capture from a 3-monitor setup (a central ultrawide plus two portrait displays).*

| Traced caustics and shadows | The water surface, seen from below |
|---|---|
| ![Detail](docs/detail.png) | ![Mirror](docs/mirror.png) |

![Night](docs/night.png)

*Night: moonlit water, and the neon tetras glow.*

## Features

- **Fully procedural 3D fish:** one parametric mesh (lofted body, forked tail, dorsal, anal and pectoral fins) is animated in the vertex shader with a wave that travels from head to tail. Species differ only by parameters: proportions, fin sizes, colors and skin pattern.
- **Six species:** neon tetras, clownfish, blue tangs, angelfish, tuna, and an occasional shark patrolling the far water.
- **Schooling behavior:** every school follows a roaming waypoint and its members apply boid rules (cohesion, alignment, separation) with soft tank bounds, so groups turn and cross the screen together.
- **One continuous world:** a single perspective camera covers the whole virtual desktop, so fish swim from one monitor to the next. Mixed sizes and orientations work.
- **Ray-traced lighting (hybrid):** the scene is rasterized, and these effects are traced per pixel in shaders (no RT cores needed, so it runs on any OpenGL 3.3 GPU):
  - **Soft shadows** from fish, jellyfish, rocks and coral, using shadow rays against ellipsoid occluders and a sun-space grid as the acceleration structure.
  - **Physical caustics:** sun rays are refracted (Snell's law) through an animated water surface and focused onto the sand; the brightness is the energy density of those rays.
  - **Volumetric light shafts:** each camera ray is marched through the water, picking up the focused light and the shadows of fish and rocks.
  - **A real water surface seen from below:** total internal reflection mirrors the sea floor, rocks and fish on the underside of the waves, with Snell's window showing the sky when you look steeply up.
  - **Refraction:** jellyfish bend and tint what is behind them like a gel lens, and every bubble is a tiny diverging lens with chromatic dispersion.
- **Underwater look:** depth fog that absorbs red first, bubble streams, drifting marine snow, swaying seaweed, rocks, coral heads, and translucent pulsing jellyfish.
- **Day, dusk and night:** lighting follows your clock (or pick one). At night the neon tetras glow.
- **Bloom, vignette, MSAA and de-banding dither** for a clean image, with three quality levels.
- **AMD FSR 1.0 upscaling (optional):** render at 67%, 59% or 50% of the resolution per axis and upscale with a GLSL port of AMD's EASU + RCAS. On a RTX 3060 across three monitors it takes the uncapped frame rate from about 81 FPS to 128 (quality), 148 (balanced) or 177 FPS (performance).
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
| `upscaling` | AMD FSR 1.0: `off`, `quality` (1.5x), `balanced` (1.7x) or `performance` (2x). |
| `sharpness` | FSR sharpening in stops: 0 is sharpest, 2 softest (AMD's default is 0.2). |
| `raytracing` | Ray-traced shadows, caustics, light shafts, water mirror and refraction. Turn it off for the cheaper procedural look. |

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
| `renderer.py` | OpenGL pipeline: caustics, mirror, scene (MSAA), refraction copy, volume, bloom, final composite. |
| `fsr.py` | Standalone, reusable AMD FSR 1.0 (EASU + RCAS) for moderngl: `FSR(ctx).upscale(src_tex, src_size, dst_fbo, dst_size, sharpness)`. |
| `rt.py` | Ray-tracing data: ellipsoid occluder texture, sun-space acceleration grid, caustic map layout, surface grid. |
| `shaders.py` | All GLSL: fish animation and skin patterns, shadow rays, caustic tracing, mirror and volume passes, refraction, fog, seaweed, jellyfish, bubbles. |
| `meshes.py` | Procedural geometry: fish, seaweed ribbons, rocks, coral, seabed, jellyfish. |
| `sim.py` | Species table, boid schooling, shark patrol and jellyfish motion. |
| `world.py` | Camera, projection and the seabed height function shared by the CPU and the shaders. |
| `settings.py` / `config_dialog.py` | Defaults, JSON persistence and the Tk settings window. |
| `winapi.py` | Monitors with per-monitor DPI, refresh rate, power status, single instance, preview embedding. |

- A `.scr` is just a renamed `.exe`; Windows launches it with `/s` (run), `/c` (configure) or `/p HWND` (preview). [PyInstaller](https://pyinstaller.org) packages the script.
- Fish are drawn with one instanced draw call. The vertex shader scales fins about their base, flaps the pectorals, and bends the spine with a head-to-tail traveling wave plus a turn-dependent curve.
- Skin patterns (neon stripe, clownfish bands, tang palette, angelfish bars, shark counter-shading) are evaluated per pixel from the mesh's `(length, around)` coordinates, and the eyes are drawn procedurally.
- The scene renders into a 16-bit float target, so bloom and fog gradients stay smooth; a tiny dither in the final pass removes banding.
- **Shadow rays:** occluders live in a float texture. Projecting every point along the light direction onto a plane makes all points of one sun ray land in the same grid cell, so each shadow ray only tests the few ellipsoids of its own cell.
- **Caustics:** a dense grid on the water surface refracts one sun ray per vertex down to the sea floor. The vertex shader computes the Jacobian of that surface-to-floor mapping; its inverse is the energy per area, accumulated additively into a texture that the floor, seaweed, fish and light shafts all sample.
- **Distance for free:** the scene's alpha channel stores the distance to the camera, which is all the volumetric pass needs, so there is no extra depth pass.
- **Sharpness:** the caustic map is 2560x1200 (about 2.5 cm per texel) fed by a 0.09 mesh, lookups use a slight mip blur so thin focus lines stay smooth up close, and the water-surface mirror is traced at 2/3 resolution with distance-filtered waves so it doesn't alias.
- The simulation costs about 2 ms per frame for 60 fish; everything else runs on the GPU. On an RTX 3060 across three monitors it renders about 280 FPS without ray tracing and about 85 FPS with it (medium quality), against a 75 Hz cap.

## Requirements

- Windows 10/11 with an OpenGL 3.3 capable GPU
- Python 3.10+, `pygame-ce`, `numpy`, `moderngl` (only to run from source)

## Credits

- Upscaling is based on AMD FidelityFX Super Resolution 1.0 (MIT license); see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
