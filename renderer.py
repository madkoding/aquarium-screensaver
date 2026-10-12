"""OpenGL 3.3 renderer for the aquarium (moderngl).

Pass order each frame
    caustics  forward-trace sun rays through the animated water surface
    mirror    trace the underside of the surface (total internal reflection)
    scene     (MSAA, RGBA16F) background, seabed+rocks, seaweed, fish; then
              blended: jellyfish, bubbles, marine snow (+ god rays when not
              ray tracing). Alpha carries the distance to the camera.
    resolve   MSAA -> texture
    volume    ray-march light shafts through the water (shadow rays + caustics)
    bloom     1/4 and 1/16 resolution blurs of the bright parts
    final     scene + bloom, vignette, tone roll-off, dithering
One perspective camera covers the whole virtual desktop, so the water is a
single continuous world across every monitor.
"""
import datetime

import moderngl
import numpy as np
import pygame

import meshes
import rt
import shaders as S
import world
from settings import QUALITY, WATER
from sim import INST_FLOATS, Sim

MAX_JELLY = 8
BUBBLE_SOURCES = 14
RT_QUALITY = {   # volume downscale, ray-march steps, mirror downscale
    "low": dict(vol_div=3, steps=14, mirror_div=6),
    "medium": dict(vol_div=2, steps=22, mirror_div=4),
    "high": dict(vol_div=2, steps=32, mirror_div=3),
}
U_GRID, U_OCC, U_CAUS, U_MIRROR, U_SCENE, U_REFR = 3, 4, 5, 6, 7, 8   # texture units


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
        self.rt_on = bool(cfg["raytracing"])
        self.rtq = RT_QUALITY[cfg["quality"]]

        rng = np.random.default_rng()
        self.sim = Sim(cfg, self.aspect, rng)
        self._build_programs()
        self._build_geometry(rng)
        self._build_targets()
        self.proj = world.perspective(self.aspect)
        self._rt_n = 0
        self._refr = np.array([0.0, -1.0, 0.0])

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
            caustic=prog(S.CAUSTIC_VS, S.CAUSTIC_FS),
            mirror=prog(S.FULLSCREEN_VS, S.MIRROR_FS),
            vol=prog(S.FULLSCREEN_VS, S.VOL_FS),
            blit=prog(S.FULLSCREEN_VS, S.BLIT_FS),
        )

    def _build_geometry(self, rng):
        c, p = self.ctx, self.p
        buf = lambda a: c.buffer(np.ascontiguousarray(a).tobytes())

        v, i, static_occ = meshes.build_seabed(rng)
        self.occ = rt.OccluderSet(static_occ)
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

        v, i = rt.surface_grid()
        self.vao_caustic = c.vertex_array(
            p["caustic"], [(buf(v), "2f", "in_xz")], index_buffer=buf(i))

        self.vao_empty = {k: c.vertex_array(p[k], []) for k in
                          ("bg", "rays", "down", "blur", "final", "bubble", "snow",
                           "mirror", "vol", "blit")}
        quality = self.cfg["quality"]
        self.n_bubbles = BUBBLE_SOURCES * {"low": 14, "medium": 22, "high": 30}[quality]
        self.n_snow = {"low": 250, "medium": 500, "high": 800}[quality]

    def _build_targets(self):
        c = self.ctx
        sw, sh = self.scene_size

        def tex(w, h, comps=4, dtype="f2", linear=True):
            t = c.texture((max(1, w), max(1, h)), comps, dtype=dtype)
            f = moderngl.LINEAR if linear else moderngl.NEAREST
            t.filter = (f, f)
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
        self.refr_tex, self.refr_fbo = tex(sw, sh)       # opaque scene, for refraction
        self.q = [tex(sw // 4, sh // 4), tex(sw // 4, sh // 4),
                  tex(sw // 16, sh // 16), tex(sw // 16, sh // 16)]

        # ray-tracing resources
        nearest = moderngl.NEAREST
        self.occ_tex = c.texture((rt.MAX_OCC, 4), 4, dtype="f4")
        self.grid_tex = c.texture((rt.GRID_W * rt.K, rt.GRID_H), 1, dtype="f4")
        for t in (self.occ_tex, self.grid_tex):
            t.filter = (nearest, nearest)
            t.repeat_x = t.repeat_y = False
        self.caus_tex = c.texture(rt.MAP_RES, 1, dtype="f2")
        self.caus_tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        self.caus_tex.repeat_x = self.caus_tex.repeat_y = False
        self.caus_fbo = c.framebuffer(color_attachments=[self.caus_tex])
        md, vd = self.rtq["mirror_div"], self.rtq["vol_div"]
        self.mir_tex, self.mir_fbo = tex(sw // md, sh // md)
        self.vol_tex, self.vol_fbo = tex(sw // vd, sh // vd)

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
        night_top, night_bot = np.array([0.025, 0.05, 0.12]), np.array([0.006, 0.014, 0.045])
        k = day ** 1.3
        w_top = night_top + (top - night_top) * k
        w_bot = night_bot + (bot - night_bot) * k
        warm = _smooth(0.3, 0.9, day)
        sun = np.array([1.0, 0.75 + 0.25 * warm, 0.55 + 0.45 * warm]) * (0.85 + 0.15 * warm)
        moon = np.array([0.28, 0.36, 0.60]) * 0.62
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
        inv_vp = np.linalg.inv(self.proj @ view)
        tup = lambda a: tuple(float(v) for v in a)
        for prog in self.p.values():
            s = self._set
            s(prog, "u_time", float(t))
            s(prog, "u_res", (float(sw), float(sh)))
            s(prog, "u_resy", float(sh))
            s(prog, "u_camPos", tup(eye))
            s(prog, "u_sunDir", tup(env["sun_dir"]))
            s(prog, "u_sunCol", tup(env["sun_col"]))
            s(prog, "u_day", float(env["day"]))
            s(prog, "u_waterTop", tup(env["top"]))
            s(prog, "u_waterBot", tup(env["bot"]))
            s(prog, "u_fog", 0.055)
            s(prog, "u_floor", float(world.FLOOR_Y))
            s(prog, "u_surf", float(world.SURFACE_Y))
            s(prog, "u_rays", float(0.20 * env["day"] + 0.03))
            s(prog, "u_vol", float(0.9 * (0.15 + 0.85 * env["day"])))
            # ray tracing
            s(prog, "u_rt", 1.0 if self.rt_on else 0.0)
            s(prog, "u_gridOrigin", rt.GRID_ORIGIN)
            s(prog, "u_cell", rt.CELL)
            s(prog, "u_gridDim", (rt.GRID_W, rt.GRID_H))
            s(prog, "u_nocc", int(self._rt_n))
            s(prog, "u_nstatic", int(self.occ.n_static))
            s(prog, "u_mapOrigin", rt.MAP_ORIGIN)
            s(prog, "u_mapSize", rt.MAP_SIZE)
            s(prog, "u_refr", tup(self._refr))
            s(prog, "u_cgain", 0.8)
            for name, unit in (("u_grid", U_GRID), ("u_occ", U_OCC), ("u_caus", U_CAUS),
                               ("u_mirror", U_MIRROR), ("u_scene", U_SCENE),
                               ("u_refrTex", U_REFR)):
                s(prog, name, unit)
            self._mat(prog, "u_view", view)
            self._mat(prog, "u_proj", self.proj)
            self._mat(prog, "u_invVP", inv_vp)

    def _bind_rt(self):
        self.grid_tex.use(U_GRID)
        self.occ_tex.use(U_OCC)
        self.caus_tex.use(U_CAUS)

    def render(self, t, dt, frame):
        ctx = self.ctx
        sw, sh = self.scene_size
        sim = self.sim
        sim.update(dt)
        env = self._environment(t)
        eye, view = self._camera(t)

        if self.rt_on:
            occ_data, grid_data, n = self.occ.build(sim.occluders(), env["sun_dir"])
            self.occ_tex.write(occ_data.tobytes())
            self.grid_tex.write(grid_data.tobytes())
            self._rt_n = n
            self._refr = rt.refracted_down(env["sun_dir"])
        self._uniforms(t, env, eye, view)

        self.fish_inst.write(sim.fish_instances().tobytes())
        if sim.J:
            self.jelly_inst.write(sim.jelly_instances().tobytes())

        ctx.disable(moderngl.CULL_FACE)
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.BLEND)
        if self.rt_on:
            self._caustic_pass()
            self._mirror_pass()

        fbo = self.render_fbo
        fbo.use()
        ctx.viewport = (0, 0, sw, sh)
        fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        self._bind_rt()
        self.mir_tex.use(U_MIRROR)

        self.vao_empty["bg"].render(moderngl.TRIANGLES, vertices=3)
        ctx.enable(moderngl.DEPTH_TEST)
        self.vao_floor.render(moderngl.TRIANGLES)
        self.vao_kelp.render(moderngl.TRIANGLES, instances=self.n_kelp)
        self.vao_fish.render(moderngl.TRIANGLES, instances=sim.N)

        # transparent objects refract what was drawn so far
        ctx.copy_framebuffer(self.refr_fbo, self.render_fbo)
        self.refr_tex.use(U_REFR)
        ctx.enable(moderngl.BLEND)
        # premultiplied alpha for colour; keep the alpha channel (distance) intact
        ctx.blend_func = (moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA, moderngl.ZERO, moderngl.ONE)
        fbo.depth_mask = False
        if sim.J:
            self.vao_bell.render(moderngl.TRIANGLES, instances=sim.J)
            self.vao_tent.render(moderngl.TRIANGLES, instances=sim.J)
        if self.cfg["bubbles"]:
            self.vao_empty["bubble"].render(moderngl.POINTS, vertices=self.n_bubbles)
        self.vao_empty["snow"].render(moderngl.POINTS, vertices=self.n_snow)
        if not self.rt_on:
            ctx.disable(moderngl.DEPTH_TEST)
            ctx.blend_func = (moderngl.ONE, moderngl.ONE, moderngl.ZERO, moderngl.ONE)
            self.vao_empty["rays"].render(moderngl.TRIANGLES, vertices=3)
        fbo.depth_mask = True
        ctx.disable(moderngl.BLEND)
        ctx.disable(moderngl.DEPTH_TEST)

        if self.samples:
            ctx.copy_framebuffer(self.scene_fbo, self.render_fbo)
        if self.rt_on:
            self._volume_pass()

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

    # --------------------------------------------------------- ray-tracing passes
    def _caustic_pass(self):
        ctx = self.ctx
        self.caus_fbo.use()
        ctx.viewport = (0, 0, *rt.MAP_RES)
        self.caus_fbo.clear(0.0, 0.0, 0.0, 0.0)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE
        self.vao_caustic.render(moderngl.TRIANGLES)
        ctx.disable(moderngl.BLEND)
        self.caus_tex.build_mipmaps()

    def _mirror_pass(self):
        ctx = self.ctx
        w, h = self.mir_tex.size
        self._bind_rt()
        self.mir_fbo.use()
        ctx.viewport = (0, 0, w, h)
        self._set(self.p["mirror"], "u_res", (float(w), float(h)))
        self.vao_empty["mirror"].render(moderngl.TRIANGLES, vertices=3)

    def _volume_pass(self):
        ctx = self.ctx
        w, h = self.vol_tex.size
        self._bind_rt()
        self.scene_tex.use(U_SCENE)
        self.vol_fbo.use()
        ctx.viewport = (0, 0, w, h)
        v = self.p["vol"]
        self._set(v, "u_scale", self.scene_size[0] / w)
        self._set(v, "u_steps", int(self.rtq["steps"]))
        self.vao_empty["vol"].render(moderngl.TRIANGLES, vertices=3)

        sw, sh = self.scene_size
        self.scene_fbo.use()
        ctx.viewport = (0, 0, sw, sh)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE
        self.vol_tex.use(0)
        self._set(self.p["blit"], "u_tex", 0)
        self.vao_empty["blit"].render(moderngl.TRIANGLES, vertices=3)
        ctx.disable(moderngl.BLEND)

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
