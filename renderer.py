"""OpenGL 3.3 renderer for the aquarium (moderngl).

Pass order each frame
    scene (MSAA, RGBA16F): background, seabed+rocks, seaweed, fish,
                           then blended: jellyfish, bubbles, marine snow, god rays
    resolve -> bloom (1/4 and 1/16 res blurs of the bright parts)
    final   -> scene + bloom, vignette, tone roll-off, dithering
One perspective camera covers the whole virtual desktop, so the water is a
single continuous world across every monitor.
"""
import datetime

import moderngl
import numpy as np
import pygame

import meshes
import shaders as S
import world
from settings import QUALITY, WATER
from sim import INST_FLOATS, Sim

MAX_JELLY = 8
BUBBLE_SOURCES = 14


def _smooth(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


class AquariumRenderer:
    name = "gpu"

    def __init__(self, mons, cfg, origin, size):
        self.cfg = cfg
        self.size = size
        vw, vh = size
        self.aspect = vw / vh
        c = self.ctx = moderngl.create_context()
        c.enable(moderngl.PROGRAM_POINT_SIZE)

        samples, scale = QUALITY[cfg["quality"]]
        self.samples = samples
        sw, sh = max(2, int(vw * scale)), max(2, int(vh * scale))
        self.scene_size = (sw, sh)

        rng = np.random.default_rng()
        self.sim = Sim(cfg, self.aspect, rng)
        self._build_programs()
        self._build_geometry(rng)
        self._build_targets()
        self.proj = world.perspective(self.aspect)

    # ------------------------------------------------------------------ setup
    def _build_programs(self):
        c = self.ctx

        def prog(vs, fs):
            return c.program(vertex_shader=vs, fragment_shader=fs)

        self.p = dict(
            bg=prog(S.FULLSCREEN_VS, S.BG_FS),
            floor=prog(S.FLOOR_VS, S.FLOOR_FS),
            fish=prog(S.FISH_VS, S.FISH_FS),
            kelp=prog(S.KELP_VS, S.KELP_FS),
            bell=prog(S.JELLY_BELL_VS, S.JELLY_BELL_FS),
            tent=prog(S.JELLY_TENT_VS, S.JELLY_TENT_FS),
            bubble=prog(S.BUBBLE_VS, S.BUBBLE_FS),
            snow=prog(S.SNOW_VS, S.SNOW_FS),
            rays=prog(S.FULLSCREEN_VS, S.RAYS_FS),
            down=prog(S.FULLSCREEN_VS, S.DOWN_FS),
            blur=prog(S.FULLSCREEN_VS, S.BLUR_FS),
            final=prog(S.FULLSCREEN_VS, S.FINAL_FS),
        )

    def _build_geometry(self, rng):
        c, p = self.ctx, self.p
        buf = lambda a: c.buffer(np.ascontiguousarray(a).tobytes())

        v, i = meshes.build_seabed(rng)
        self.vao_floor = c.vertex_array(
            p["floor"], [(buf(v), "3f 3f 3f", "in_pos", "in_nrm", "in_col")],
            index_buffer=buf(i))

        v, i = meshes.build_fish()
        self.fish_inst = c.buffer(reserve=max(1, self.sim.N) * INST_FLOATS * 4, dynamic=True)
        self.vao_fish = c.vertex_array(
            p["fish"],
            [(buf(v), "3f 3f 2f 1f 3f", "in_pos", "in_nrm", "in_uv", "in_part", "in_pivot"),
             (self.fish_inst, "3f 3f 4f 4f 4f 3f 3f 3f/i", "i_pos", "i_fwd", "i_size",
              "i_fin", "i_anim", "i_c1", "i_c2", "i_c3")],
            index_buffer=buf(i))

        v, i = meshes.build_ribbon()
        kelp = meshes.build_kelp_instances(rng)
        self.n_kelp = len(kelp)
        self.vao_kelp = c.vertex_array(
            p["kelp"],
            [(buf(v), "2f", "in_uv"),
             (buf(kelp), "3f 4f 3f/i", "i_base", "i_dim", "i_col")],
            index_buffer=buf(i))

        self.jelly_inst = c.buffer(reserve=MAX_JELLY * 8 * 4, dynamic=True)
        jinst = (self.jelly_inst, "3f 1f 1f 3f/i", "i_pos", "i_size", "i_phase", "i_col")
        v, i = meshes.build_jelly_bell()
        self.vao_bell = c.vertex_array(
            p["bell"], [(buf(v), "3f 3f", "in_pos", "in_nrm"), jinst], index_buffer=buf(i))
        v, i = meshes.build_jelly_tentacles()
        self.vao_tent = c.vertex_array(
            p["tent"], [(buf(v), "3f", "in_t"), jinst], index_buffer=buf(i))

        self.vao_empty = {k: c.vertex_array(p[k], []) for k in
                          ("bg", "rays", "down", "blur", "final", "bubble", "snow")}
        quality = self.cfg["quality"]
        self.n_bubbles = BUBBLE_SOURCES * {"low": 14, "medium": 22, "high": 30}[quality]
        self.n_snow = {"low": 250, "medium": 500, "high": 800}[quality]

    def _build_targets(self):
        c = self.ctx
        sw, sh = self.scene_size

        def tex(w, h):
            t = c.texture((max(1, w), max(1, h)), 4, dtype="f2")
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.repeat_x = t.repeat_y = False
            return t, c.framebuffer(color_attachments=[t])

        self.scene_tex = c.texture((sw, sh), 4, dtype="f2")
        self.scene_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.scene_tex.repeat_x = self.scene_tex.repeat_y = False
        if self.samples:
            self.scene_fbo = c.framebuffer(color_attachments=[self.scene_tex])
            self.render_fbo = c.framebuffer(
                color_attachments=[c.renderbuffer((sw, sh), 4, samples=self.samples, dtype="f2")],
                depth_attachment=c.depth_renderbuffer((sw, sh), samples=self.samples))
        else:
            self.scene_fbo = self.render_fbo = c.framebuffer(
                color_attachments=[self.scene_tex],
                depth_attachment=c.depth_renderbuffer((sw, sh)))
        self.q = [tex(sw // 4, sh // 4), tex(sw // 4, sh // 4),
                  tex(sw // 16, sh // 16), tex(sw // 16, sh // 16)]

    # -------------------------------------------------------------- per frame
    def _environment(self, t):
        mode = self.cfg["light"]
        if mode == "auto":
            now = datetime.datetime.now()
            h = now.hour + now.minute / 60.0
            day = _smooth(6.0, 8.5, h) * (1.0 - _smooth(17.5, 20.0, h))
        else:
            day = {"day": 1.0, "dusk": 0.45, "night": 0.0}[mode]
        top, bot = (np.array(v) for v in WATER[self.cfg["water"]])
        night_top, night_bot = np.array([0.012, 0.025, 0.06]), np.array([0.0, 0.005, 0.02])
        k = day ** 1.3
        w_top = night_top + (top - night_top) * k
        w_bot = night_bot + (bot - night_bot) * k
        warm = _smooth(0.3, 0.9, day)
        sun = np.array([1.0, 0.75 + 0.25 * warm, 0.55 + 0.45 * warm]) * (0.85 + 0.15 * warm)
        moon = np.array([0.28, 0.36, 0.60]) * 0.30
        sun_col = moon + (sun - moon) * day
        ang = 0.35 - 0.5 * (1 - day)
        sun_dir = np.array([np.sin(ang), 0.9, 0.3])
        return dict(day=day, top=w_top, bot=w_bot, sun_col=sun_col,
                    sun_dir=sun_dir / np.linalg.norm(sun_dir))

    def _camera(self, t):
        if self.cfg["camera_drift"]:
            sx, sy = 0.40 * np.sin(t * 0.07), 0.12 * np.sin(t * 0.05 + 1.0)
        else:
            sx = sy = 0.0
        eye = np.array([sx, world.CAM_Y + sy, world.CAM_Z])
        target = world.LOOK_AT + np.array([sx * 0.6, sy * 0.6, 0.0])
        return eye, world.look_at(eye, target)

    @staticmethod
    def _set(prog, name, value):
        try:
            prog[name].value = value
        except KeyError:
            pass

    @staticmethod
    def _mat(prog, name, m):
        try:
            prog[name].write(np.ascontiguousarray(m.T, dtype="f4").tobytes())
        except KeyError:
            pass

    def _uniforms(self, t, env, eye, view):
        sw, sh = self.scene_size
        for key, prog in self.p.items():
            s = self._set
            s(prog, "u_time", float(t))
            s(prog, "u_res", (float(sw), float(sh)))
            s(prog, "u_resy", float(sh))
            s(prog, "u_camPos", tuple(float(v) for v in eye))
            s(prog, "u_sunDir", tuple(float(v) for v in env["sun_dir"]))
            s(prog, "u_sunCol", tuple(float(v) for v in env["sun_col"]))
            s(prog, "u_day", float(env["day"]))
            s(prog, "u_waterTop", tuple(float(v) for v in env["top"]))
            s(prog, "u_waterBot", tuple(float(v) for v in env["bot"]))
            s(prog, "u_fog", 0.055)
            s(prog, "u_floor", float(world.FLOOR_Y))
            s(prog, "u_rays", float(0.20 * env["day"] + 0.03))
            self._mat(prog, "u_view", view)
            self._mat(prog, "u_proj", self.proj)

    def render(self, t, dt, frame):
        ctx = self.ctx
        sw, sh = self.scene_size
        sim = self.sim
        sim.update(dt)
        env = self._environment(t)
        eye, view = self._camera(t)
        self._uniforms(t, env, eye, view)

        self.fish_inst.write(sim.fish_instances().tobytes())
        if sim.J:
            self.jelly_inst.write(sim.jelly_instances().tobytes())

        fbo = self.render_fbo
        fbo.use()
        ctx.viewport = (0, 0, sw, sh)
        fbo.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
        ctx.disable(moderngl.BLEND)
        ctx.disable(moderngl.CULL_FACE)

        ctx.disable(moderngl.DEPTH_TEST)
        self.vao_empty["bg"].render(moderngl.TRIANGLES, vertices=3)
        ctx.enable(moderngl.DEPTH_TEST)
        self.vao_floor.render(moderngl.TRIANGLES)
        self.vao_kelp.render(moderngl.TRIANGLES, instances=self.n_kelp)
        self.vao_fish.render(moderngl.TRIANGLES, instances=sim.N)

        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        fbo.depth_mask = False
        if sim.J:
            self.vao_bell.render(moderngl.TRIANGLES, instances=sim.J)
            self.vao_tent.render(moderngl.TRIANGLES, instances=sim.J)
        if self.cfg["bubbles"]:
            self.vao_empty["bubble"].render(moderngl.POINTS, vertices=self.n_bubbles)
        self.vao_empty["snow"].render(moderngl.POINTS, vertices=self.n_snow)
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.blend_func = moderngl.ONE, moderngl.ONE
        self.vao_empty["rays"].render(moderngl.TRIANGLES, vertices=3)
        fbo.depth_mask = True
        ctx.disable(moderngl.BLEND)

        if self.samples:
            ctx.copy_framebuffer(self.scene_fbo, self.render_fbo)

        bloom = float(self.cfg["bloom"])
        if bloom > 0:
            self._blur_chain(self.scene_tex, self.q[0], self.q[1])
            self._blur_chain(self.q[0][0], self.q[2], self.q[3])

        vw, vh = self.size
        ctx.screen.use()
        ctx.viewport = (0, 0, vw, vh)
        self.scene_tex.use(0)
        self.q[0][0].use(1)
        self.q[2][0].use(2)
        f = self.p["final"]
        for name, unit in (("u_scene", 0), ("u_bloom1", 1), ("u_bloom2", 2)):
            self._set(f, name, unit)
        self._set(f, "u_g1", bloom * 0.9)
        self._set(f, "u_g2", bloom * 1.3)
        self._set(f, "u_vig", float(self.cfg["vignette"]))
        self.vao_empty["final"].render(moderngl.TRIANGLES, vertices=3)

    def _blur_chain(self, src_tex, a, b):
        ctx = self.ctx
        (a_tex, a_fbo), (b_tex, b_fbo) = a, b
        w, h = a_tex.size
        a_fbo.use()
        ctx.viewport = (0, 0, w, h)
        src_tex.use(0)
        self._set(self.p["down"], "u_tex", 0)
        self._set(self.p["down"], "u_texel", (1.0 / src_tex.size[0], 1.0 / src_tex.size[1]))
        self.vao_empty["down"].render(moderngl.TRIANGLES, vertices=3)
        for src, dst, dx, dy in ((a_tex, b_fbo, 1.0 / w, 0.0), (b_tex, a_fbo, 0.0, 1.0 / h)):
            dst.use()
            src.use(0)
            self._set(self.p["blur"], "u_tex", 0)
            self._set(self.p["blur"], "u_dir", (dx, dy))
            self.vao_empty["blur"].render(moderngl.TRIANGLES, vertices=3)

    # ------------------------------------------------------------- utilities
    def screenshot(self, path):
        vw, vh = self.size
        data = self.ctx.screen.read(components=3)
        surf = pygame.image.frombuffer(data, (vw, vh), "RGB")
        pygame.image.save(pygame.transform.flip(surf, False, True), path)

    def close(self):
        pass
