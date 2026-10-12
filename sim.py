"""Fish and jellyfish behaviour (numpy, vectorised).

Each school follows a roaming waypoint and its members apply the classic boid
rules (cohesion, alignment, separation) plus soft tank bounds. The simulation
only produces per-instance arrays; all drawing happens in renderer.py.
"""
import numpy as np

import world

PATTERN = dict(neon=0, clown=1, tang=2, shark=3, angel=4, tuna=5)

# colors: (back, belly, accent) variants; accent meaning depends on the pattern
SPECIES = {
    "tetra": dict(
        len=(0.26, 0.34), sy=1.0, sz=1.0, tail=1.0, dorsal=0.9, pect=0.9, amp=1.0,
        pattern="neon", speed=(0.9, 1.3), group=(12, 18), band=(0.25, 0.95), z=(-6, 1.5),
        colors=[((0.04, 0.12, 0.42), (0.85, 0.90, 0.95), (0.10, 0.85, 1.0)),
                ((0.30, 0.04, 0.08), (0.95, 0.80, 0.75), (1.0, 0.25, 0.12))]),
    "clown": dict(
        len=(0.30, 0.38), sy=1.3, sz=1.2, tail=1.1, dorsal=1.2, pect=1.3, amp=0.9,
        pattern="clown", speed=(0.35, 0.6), group=(2, 4), band=(0.0, 0.3), z=(-5, 0.5),
        colors=[((1.0, 0.36, 0.04), (1.0, 0.50, 0.14), (0.04, 0.03, 0.03))]),
    "tang": dict(
        len=(0.50, 0.62), sy=1.6, sz=0.8, tail=1.2, dorsal=1.1, pect=1.0, amp=0.8,
        pattern="tang", speed=(0.5, 0.8), group=(4, 7), band=(0.2, 0.85), z=(-8, 1.0),
        colors=[((0.08, 0.28, 0.95), (0.06, 0.18, 0.70), (0.02, 0.03, 0.10))]),
    "angel": dict(
        len=(0.60, 0.75), sy=1.9, sz=0.55, tail=1.1, dorsal=1.6, pect=0.9, amp=0.6,
        pattern="angel", speed=(0.3, 0.5), group=(3, 4), band=(0.2, 0.8), z=(-7, 0.5),
        colors=[((0.92, 0.86, 0.55), (0.95, 0.95, 0.90), (0.04, 0.04, 0.05)),
                ((0.85, 0.88, 0.95), (0.95, 0.95, 1.0), (0.10, 0.10, 0.12))]),
    "tuna": dict(
        len=(1.25, 1.55), sy=0.95, sz=1.0, tail=1.5, dorsal=0.6, pect=0.8, amp=1.2,
        pattern="tuna", speed=(1.4, 1.9), group=(1, 2), band=(0.3, 0.9), z=(-12, -3),
        colors=[((0.05, 0.16, 0.38), (0.85, 0.88, 0.92), (0.95, 0.80, 0.10))]),
    "shark": dict(
        len=(3.2, 3.8), sy=0.9, sz=1.0, tail=1.6, dorsal=1.0, pect=1.1, amp=1.1,
        pattern="shark", speed=(0.9, 1.1), group=(1, 1), band=(0.4, 0.8), z=(-13, -9),
        colors=[((0.36, 0.40, 0.46), (0.88, 0.90, 0.92), (0.2, 0.2, 0.22))]),
}
RECIPE = ["tetra", "angel", "clown", "tang", "tetra", "tuna", "clown", "tang"]
INST_FLOATS = 27   # pos3 fwd3 size4 fin4 anim4 c1(3) c2(3) c3(3)


class Sim:
    def __init__(self, cfg, aspect, rng=None):
        self.rng = rng or np.random.default_rng()
        self.aspect = aspect
        self.scale = cfg["fish_scale"]
        self._build_fish(cfg)
        self._build_jellies(cfg["jellyfish"])
        self.time = 0.0

    # ---------------------------------------------------------------- setup
    def _build_fish(self, cfg):
        rng = self.rng
        groups, i = [], 0
        while sum(g["n"] for g in groups) < cfg["fish"]:
            name = RECIPE[i % len(RECIPE)]
            sp = SPECIES[name]
            groups.append(dict(name=name, n=int(rng.integers(sp["group"][0], sp["group"][1] + 1)),
                               palette=sp["colors"][rng.integers(0, len(sp["colors"]))]))
            i += 1
        if cfg["shark"]:
            groups.append(dict(name="shark", n=1, palette=SPECIES["shark"]["colors"][0]))
        self.groups = groups
        self.G = len(groups)

        gid, rows = [], []
        for g, grp in enumerate(groups):
            sp = SPECIES[grp["name"]]
            base_len = rng.uniform(*sp["len"])
            base_speed = rng.uniform(*sp["speed"])
            for _ in range(grp["n"]):
                ln = base_len * rng.uniform(0.9, 1.1) * self.scale
                jit = rng.uniform(0.9, 1.1)
                back, belly, acc = (np.array(c) * jit for c in grp["palette"])
                rows.append(dict(
                    len=ln, speed=base_speed * rng.uniform(0.9, 1.1) * np.sqrt(self.scale),
                    sy=sp["sy"], sz=sp["sz"], tail=sp["tail"], dorsal=sp["dorsal"],
                    pect=sp["pect"], amp=sp["amp"], pattern=PATTERN[sp["pattern"]],
                    c1=back, c2=belly, c3=np.clip(acc, 0, 1.5)))
                gid.append(g)
        n = len(rows)
        self.N = n
        self.gid = np.array(gid)
        self.fish = rows
        self.len = np.array([r["len"] for r in rows])
        self.spd = np.array([r["speed"] for r in rows])
        self.is_shark = np.array([groups[g]["name"] == "shark" for g in gid])
        self.static = self._pack_static()

        self.wp = np.zeros((self.G, 3))
        self.wp_timer = np.zeros(self.G)
        for g in range(self.G):
            self._new_waypoint(g, first=True)
        self.pos = self.wp[self.gid] + rng.normal(0, 0.8, (n, 3))
        for k in range(n):  # spawn inside the water volume
            self.pos[k] = self._clamp_to_bounds(self.pos[k])
        ang = rng.uniform(0, 2 * np.pi, n)
        self.vel = np.stack([np.cos(ang), 0 * ang, np.sin(ang) * 0.3], -1) * self.spd[:, None]
        self.fwd = self.vel / np.linalg.norm(self.vel, axis=1, keepdims=True)
        self.phase = rng.uniform(0, 2 * np.pi, n)
        self.bend = np.zeros(n)
        self.wander = rng.normal(0, 1, (n, 3))

    def _pack_static(self):
        """Per-fish constants as a full instance block, reused every frame."""
        out = np.zeros((self.N, INST_FLOATS), np.float32)
        for k, r in enumerate(self.fish):
            out[k, 6:10] = [r["len"], r["sy"], r["sz"], 0.0]
            out[k, 10:14] = [r["tail"], r["dorsal"], r["pect"], r["amp"]]
            out[k, 16] = r["pattern"]
            out[k, 18:21], out[k, 21:24], out[k, 24:27] = r["c1"], r["c2"], r["c3"]
        return out

    def _build_jellies(self, count):
        rng = self.rng
        self.J = count
        self.jpos = np.zeros((count, 3))
        for k in range(count):
            z = rng.uniform(-8.0, -1.0)
            hw, hh, cy = world.view_extent(z, self.aspect)
            self.jpos[k] = [rng.uniform(-hw, hw) * 0.9, cy + rng.uniform(-hh, hh) * 0.6, z]
        self.jphase = rng.uniform(0, 6.28, count)
        self.jsize = rng.uniform(0.35, 0.7, count)
        self.jdir = rng.uniform(0, 6.28, count)
        pal = np.array([(1.0, 0.45, 0.75), (0.55, 0.65, 1.0), (0.45, 1.0, 0.85), (1.0, 0.65, 0.35)])
        self.jcol = pal[rng.integers(0, len(pal), count)]

    # --------------------------------------------------------------- bounds
    def _limits(self, z):
        hw, hh, cy = world.view_extent(z, self.aspect)
        floor = world.floor_y(0.0, z)
        return hw * 0.97, max(floor + 0.35, cy - hh * 0.9), cy + hh * 0.9

    def _clamp_to_bounds(self, p):
        xm, ylo, yhi = self._limits(p[2])
        return np.array([np.clip(p[0], -xm, xm), np.clip(p[1], ylo, yhi),
                         np.clip(p[2], world.Z_FAR_LIMIT, world.Z_NEAR_LIMIT)])

    def _new_waypoint(self, g, first=False):
        rng = self.rng
        sp = SPECIES[self.groups[g]["name"]]
        z = rng.uniform(*sp["z"])
        xm, ylo, yhi = self._limits(z)
        if sp["pattern"] == "shark":           # patrol across and past the edges
            side = -np.sign(self.wp[g, 0]) if self.wp[g, 0] != 0 else rng.choice([-1, 1])
            x = side * (xm + 5.0)
        else:
            x = rng.uniform(-xm, xm)
        y = ylo + (yhi - ylo) * rng.uniform(*sp["band"])
        self.wp[g] = (x, y, z)
        self.wp_timer[g] = rng.uniform(6.0, 14.0) if not first else rng.uniform(0.0, 4.0)

    # --------------------------------------------------------------- update
    def update(self, dt):
        dt = min(dt, 0.05)
        self.time += dt
        self._update_fish(dt)
        self._update_jellies(dt)

    def _update_fish(self, dt):
        rng = self.rng
        gid, n = self.gid, self.N
        pos, vel = self.pos, self.vel

        self.wp_timer -= dt
        arrived = np.linalg.norm(self.wp - self._centroids(pos), axis=1) < 1.2
        for g in np.nonzero((self.wp_timer <= 0) | arrived)[0]:
            self._new_waypoint(g)

        cent = self._centroids(pos)
        meanv = self._centroids(vel)
        to_wp = self.wp[gid] - pos
        dist = np.linalg.norm(to_wp, axis=1, keepdims=True) + 1e-6
        seek = to_wp / dist * self.spd[:, None]

        acc = (seek - vel) * 1.6
        acc += (cent[gid] - pos) * 0.55 + (meanv[gid] - vel) * 0.9

        diff = pos[:, None, :] - pos[None, :, :]
        d2 = (diff ** 2).sum(-1) + np.eye(n) * 1e9
        rs = (self.len * 1.9)[:, None]
        close = d2 < rs ** 2
        d = np.sqrt(d2)[..., None]
        acc += ((diff / np.maximum(d, 1e-3)) * np.maximum(rs[..., None] - d, 0)
                * close[..., None]).sum(1) * 6.0

        acc += self._boundary(pos) * 4.0

        self.wander += rng.normal(0, 1.0, (n, 3)) * dt * 2.0
        self.wander *= 1.0 - 0.8 * dt
        acc += self.wander * 0.35 * self.spd[:, None]

        vel += acc * dt
        sp = np.linalg.norm(vel, axis=1, keepdims=True) + 1e-9
        target = np.clip(sp, 0.55 * self.spd[:, None], 1.25 * self.spd[:, None])
        vel *= target / sp
        pos += vel * dt

        want = vel / (np.linalg.norm(vel, axis=1, keepdims=True) + 1e-9)
        want[:, 1] *= 0.55                          # fish prefer level swimming
        want /= np.linalg.norm(want, axis=1, keepdims=True)
        new = self.fwd + (want - self.fwd) * (1.0 - np.exp(-dt * 5.0))
        new /= np.linalg.norm(new, axis=1, keepdims=True)
        yaw_rate = (self.fwd[:, 2] * new[:, 0] - self.fwd[:, 0] * new[:, 2]) / max(dt, 1e-4)
        self.bend += (np.clip(yaw_rate * 0.25, -1, 1) - self.bend) * (1 - np.exp(-dt * 4.0))
        self.fwd = new

        speed = np.linalg.norm(vel, axis=1)
        self.phase += dt * 2 * np.pi * (1.0 + 0.9 * speed / self.len)

    def _centroids(self, arr):
        out = np.zeros((self.G, 3))
        np.add.at(out, self.gid, arr)
        return out / np.bincount(self.gid, minlength=self.G)[:, None]

    def _boundary(self, pos):
        out = np.zeros_like(pos)
        for k in range(self.N):
            xm, ylo, yhi = self._limits(pos[k, 2])
            if self.is_shark[k]:
                xm += 12.0
            mx, my, mz = 1.0, 0.7, 1.5
            out[k, 0] = np.clip((-xm + mx - pos[k, 0]) / mx, 0, 1) - np.clip((pos[k, 0] - (xm - mx)) / mx, 0, 1)
            out[k, 1] = np.clip((ylo + my - pos[k, 1]) / my, 0, 1) - np.clip((pos[k, 1] - (yhi - my)) / my, 0, 1)
            out[k, 2] = (np.clip((world.Z_FAR_LIMIT + mz - pos[k, 2]) / mz, 0, 1)
                         - np.clip((pos[k, 2] - (world.Z_NEAR_LIMIT - mz)) / mz, 0, 1))
        return out

    def _update_jellies(self, dt):
        if not self.J:
            return
        self.jphase += dt * 2.2
        thrust = np.maximum(np.sin(self.jphase), 0.0)
        self.jdir += self.rng.normal(0, 0.4, self.J) * dt
        self.jpos[:, 0] += np.cos(self.jdir) * 0.10 * dt
        self.jpos[:, 2] += np.sin(self.jdir) * 0.05 * dt
        self.jpos[:, 1] += (0.55 * thrust - 0.14) * dt
        for k in range(self.J):
            xm, ylo, yhi = self._limits(self.jpos[k, 2])
            if self.jpos[k, 1] > yhi:
                self.jpos[k, 1] = ylo + 0.2
            self.jpos[k, 0] = np.clip(self.jpos[k, 0], -xm, xm)
            self.jpos[k, 2] = np.clip(self.jpos[k, 2], -9.0, -0.5)

    # -------------------------------------------------------------- packing
    def fish_instances(self):
        """(N, 27) float32 block, layout documented at INST_FLOATS."""
        out = self.static.copy()
        out[:, 0:3] = self.pos
        out[:, 3:6] = self.fwd
        out[:, 14] = self.phase
        out[:, 15] = self.bend
        return out

    def jelly_instances(self):
        """(J, 8): pos3 size1 phase1 color3."""
        out = np.zeros((self.J, 8), np.float32)
        if self.J:
            out[:, 0:3] = self.jpos
            out[:, 3] = self.jsize
            out[:, 4] = self.jphase
            out[:, 5:8] = self.jcol
        return out
