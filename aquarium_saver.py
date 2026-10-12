"""Aquarium screensaver for Windows (3D, multi-monitor).

Windows screensaver contract (the .scr is just a renamed .exe):
    /s       run the screensaver full screen
    /c       show the settings dialog
    /p HWND  render inside the tiny preview window of the settings picker

Dev flags:  --seconds N     auto-exit after N seconds (ignores input)
            --shot FILE     save a screenshot just before exiting
            --at SECONDS    advance the simulation by this much before the first frame
"""
import os
import sys
import time

import winapi

MONITOR_CHECK_SECS = 3.0
POWER_CHECK_SECS = 5.0
FPS_BATTERY = 30
MOUSE_THRESHOLD_PX = 25


class FrameLimiter:
    """Precise frame pacing: sleep for most of the gap, spin for the last ms."""

    def __init__(self):
        self.next = time.perf_counter()

    def wait(self, fps):
        step = 1.0 / fps
        self.next += step
        now = time.perf_counter()
        if self.next < now - step:  # fell far behind (e.g. a stall): resync
            self.next = now
        while True:
            left = self.next - time.perf_counter()
            if left <= 0:
                break
            if left > 0.002:
                time.sleep(left - 0.0015)


def make_renderer(pygame, cfg, mons, origin, size):
    from renderer import AquariumRenderer
    for attr, val in ((pygame.GL_CONTEXT_MAJOR_VERSION, 3),
                      (pygame.GL_CONTEXT_MINOR_VERSION, 3),
                      (pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)):
        pygame.display.gl_set_attribute(attr, val)
    pygame.display.set_mode(size, pygame.OPENGL | pygame.DOUBLEBUF | pygame.NOFRAME, vsync=1)
    return AquariumRenderer(mons, cfg, origin, size)


def run_session(cfg, preview_hwnd=None, seconds=None, shot=None, warmup=0.0):
    """Run until the user quits. Returns "quit" or "restart" (monitors changed)."""
    mons = winapi.list_monitors()
    if preview_hwnd:
        pw, ph = winapi.client_size(preview_hwnd)
        mons = [dict(x=0, y=0, w=pw, h=ph, dpi=1.0)]
    sig = winapi.monitor_signature(mons)
    vx, vy, vw, vh = winapi.virtual_bounds(mons)

    os.environ["SDL_VIDEO_WINDOW_POS"] = f"{vx},{vy}"
    os.environ["SDL_VIDEO_ALLOW_SCREENSAVER"] = "1"
    import pygame
    pygame.display.init()
    try:
        renderer = make_renderer(pygame, cfg, mons, (vx, vy), (vw, vh))
    except Exception as exc:
        if seconds is not None:
            raise                      # dev run: show the real traceback
        winapi.message_box("The Aquarium screensaver needs OpenGL 3.3 or newer.\n\n"
                           f"{exc}", "Aquarium Screensaver")
        pygame.display.quit()
        return "quit"
    pygame.display.set_caption("Aquarium Screensaver")
    hwnd = pygame.display.get_wm_info()["window"]
    if preview_hwnd:
        winapi.embed_in_parent(hwnd, preview_hwnd, vw, vh)
    else:
        pygame.mouse.set_visible(False)
        winapi.set_topmost(hwnd, vx, vy, vw, vh)

    ac_fps = winapi.max_refresh_rate()
    limiter = FrameLimiter()
    start = last_mon = last_pow = last = time.perf_counter()
    fps_cap = FPS_BATTERY if winapi.on_battery() else ac_fps
    moved, last_pos, frame = 0, None, 0
    result, running = "quit", True
    clock_offset = warmup
    while running:
        limiter.wait(fps_cap)
        now = time.perf_counter()
        t, dt, last = now - start + clock_offset, min(now - last, 0.1), now

        for e in pygame.event.get():
            if seconds is not None or preview_hwnd:
                continue  # dev/test and preview: input never closes it
            if e.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.QUIT):
                running = False
            elif e.type == pygame.MOUSEMOTION:
                if t > 0.6 and last_pos is not None:  # ignore the first jump
                    moved += abs(e.pos[0] - last_pos[0]) + abs(e.pos[1] - last_pos[1])
                    if moved > MOUSE_THRESHOLD_PX:
                        running = False
                last_pos = e.pos

        if frame == 0 and warmup > 0:      # let the school spread out for dev shots
            for _ in range(int(warmup * 30)):
                renderer.sim.update(1 / 30)
        renderer.render(t, dt, frame)
        pygame.display.flip()
        frame += 1

        if preview_hwnd and not winapi.is_window(preview_hwnd):
            running = False
        if now - last_pow > POWER_CHECK_SECS:
            last_pow = now
            fps_cap = FPS_BATTERY if winapi.on_battery() else ac_fps
        if not preview_hwnd and now - last_mon > MONITOR_CHECK_SECS:
            last_mon = now
            if winapi.monitor_signature(winapi.list_monitors()) != sig:
                result, running = "restart", False  # a display was plugged/unplugged
        if seconds is not None and now - start >= seconds:
            if shot:
                renderer.screenshot(shot)
            running = False

    if seconds is not None:
        el = max(time.perf_counter() - start, 1e-6)
        print(f"cap: {fps_cap} Hz, avg fps at exit: {frame / el:.1f}")
    renderer.close()
    pygame.display.quit()
    return result


def parse_args(argv):
    """-> (mode, preview_hwnd, dev_options)."""
    mode, hwnd = "c", None
    dev = {"seconds": None, "shot": None, "at": 0.0}
    i = 0
    while i < len(argv):
        low = argv[i].lower()
        if low in ("--seconds", "--shot", "--at") and i + 1 < len(argv):
            key = low[2:]
            dev[key] = argv[i + 1] if key == "shot" else float(argv[i + 1])
            mode = "s" if mode == "c" else mode
            i += 2
            continue
        if low[:1] in "/-" and not low.startswith("--") \
                and low.lstrip("/-")[:1] in ("s", "c", "p"):
            body = low.lstrip("/-")
            mode = body[0]
            rest = body[1:].lstrip(":")
            if rest.isdigit():
                hwnd = int(rest)
            elif i + 1 < len(argv) and argv[i + 1].isdigit():
                hwnd = int(argv[i + 1])
                i += 1
        i += 1
    return mode, hwnd, dev


def main():
    mode, hwnd, dev = parse_args(sys.argv[1:])
    if mode == "c":
        import config_dialog
        config_dialog.show()
        return
    if mode == "p" and hwnd is None:
        return  # preview requested without a window to draw into
    winapi.make_dpi_aware()
    if dev["seconds"] is None:
        name = "Local\\AquariumScreensaver_" + ("Preview" if mode == "p" else "Run")
        if not winapi.acquire_single_instance(name):
            return  # already running
    import settings
    cfg = settings.load()
    while True:
        res = run_session(cfg, hwnd if mode == "p" else None,
                          dev["seconds"], dev["shot"], dev["at"])
        if res != "restart":
            break


if __name__ == "__main__":
    main()
