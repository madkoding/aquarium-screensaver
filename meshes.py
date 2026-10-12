"""Procedural geometry (numpy only): fish, seaweed ribbons, rocks, seabed and
jellyfish. No model files; everything is generated from formulas.

Fish vertex layout (12 floats): pos(3) normal(3) uv(2) part(1) pivot(3)
    part 0 body, 1 tail fin, 2 dorsal fin, 3 pectoral fin, 4 anal fin
    pivot = point a fin scales/flaps around (the vertex shader animates it)
Canonical fish: length 1 along +x (nose at +0.5), up = +y.
"""
import numpy as np

import world


# ------------------------------------------------------------------- helpers
def noise3(p, seed=0):
    """Smooth value noise in [0, 1] for points p of shape (..., 3)."""
    pi = np.floor(p).astype(np.int64)
    pf = p - pi
    u = pf * pf * (3.0 - 2.0 * pf)

    def corner(dx, dy, dz):
        n = ((pi[..., 0] + dx) * 374761393 + (pi[..., 1] + dy) * 668265263
             + (pi[..., 2] + dz) * 2147483647 + seed * 1442695041) & 0xFFFFFFFF
        n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
        n ^= n >> 16
        return (n & 0xFFFF) / 65535.0

    out = 0.0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = ((u[..., 0] if dx else 1 - u[..., 0])
                     * (u[..., 1] if dy else 1 - u[..., 1])
                     * (u[..., 2] if dz else 1 - u[..., 2]))
                out = out + w * corner(dx, dy, dz)
    return out


def _grid_indices(ni, nj, base=0):
    i, j = np.meshgrid(np.arange(ni - 1), np.arange(nj - 1), indexing="ij")
    a = (i * nj + j).ravel()
    b = ((i + 1) * nj + j).ravel()
    c = (i * nj + j + 1).ravel()
    d = ((i + 1) * nj + j + 1).ravel()
    return (np.stack([a, b, c, b, d, c], -1).reshape(-1, 3) + base).astype(np.uint32)


def _normals(P):
    """Normals of a grid as cross(dP/di, dP/dj); degenerate rows fall back to +x."""
    n = np.cross(np.gradient(P, axis=0), np.gradient(P, axis=1))
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    return np.where(ln > 1e-9, n / np.maximum(ln, 1e-9), np.array([1.0, 0.0, 0.0]))


def _fish_part(P, uv, part, pivot):
    ni, nj, _ = P.shape
    verts = np.concatenate([
        P, _normals(P), uv,
        np.full((ni, nj, 1), float(part)),
        np.broadcast_to(np.asarray(pivot, float), (ni, nj, 3)),
    ], axis=-1).reshape(-1, 12)
    return verts.astype(np.float32), _grid_indices(ni, nj)


# ---------------------------------------------------------------------- fish
HALF_H, HALF_T = 0.17, 0.085


def _profile(t):
    """Body thickness along t (0 = nose .. 1 = tail), peak 1, small peduncle."""
    f = np.power(t, 0.55) * np.power(1.0 - t, 0.85) / 0.391
    s = np.clip((t - 0.75) / 0.25, 0, 1)
    return f + 0.10 * s * s * (3 - 2 * s)


def build_fish():
    """-> (vertices float32 (n, 12), indices uint32)."""
    parts = []

    # Body: i = angle around the axis, j = length
    na, nt = 20, 30
    th = np.linspace(0, 2 * np.pi, na + 1)[:, None]
    t = np.linspace(0, 1, nt + 1)[None, :]
    r = _profile(t)
    sin = np.sin(th)
    y = HALF_H * r * np.where(sin > 0, sin, 0.8 * sin)
    P = np.stack([0.5 - t + 0 * th, y, HALF_T * r * np.cos(th)], -1)
    uv = np.stack([t + 0 * th, sin + 0 * t], -1)
    parts.append(_fish_part(P, uv, 0, (0, 0, 0)))

    # Tail fin: i = vertical -1..1, j = outward 0..1 (forked, widening)
    u = np.linspace(-1, 1, 11)[:, None]
    s = np.linspace(0, 1, 7)[None, :]
    P = np.stack([-0.495 - s * (0.09 + 0.15 * np.abs(u) ** 1.5),
                  u * (0.055 + 0.19 * s ** 0.8), 0 * u + 0 * s], -1)
    uv = np.stack([(u + 1) / 2 + 0 * s, s + 0 * u], -1)
    parts.append(_fish_part(P, uv, 1, (-0.495, 0, 0)))

    # Dorsal fin on the back, taller at the front and swept backwards
    a = np.linspace(0, 1, 9)[:, None]
    b = np.linspace(0, 1, 4)[None, :]
    x0 = 0.24 - a * 0.52
    ytop = HALF_H * _profile(0.5 - x0) - 0.01
    hgt = 0.13 * (0.45 + 0.55 * (1 - a) ** 1.2)
    P = np.stack([x0 - b * 0.12 * (0.5 + a), ytop + b * hgt, 0 * a + 0 * b], -1)
    uv = np.stack([a + 0 * b, b + 0 * a], -1)
    parts.append(_fish_part(P, uv, 2, (-0.02, 0.15, 0)))

    # Anal fin under the belly
    x0 = 0.02 - a * 0.30
    ybot = -0.8 * HALF_H * _profile(0.5 - x0) + 0.01
    hgt = 0.08 * (0.5 + 0.5 * (1 - a))
    P = np.stack([x0 - b * 0.10 * (0.5 + a), ybot - b * hgt, 0 * a + 0 * b], -1)
    parts.append(_fish_part(P, uv, 4, (-0.13, -0.12, 0)))

    # Pectoral fins, one per side
    a = np.linspace(0, 1, 4)[:, None]
    s = np.linspace(0, 1, 5)[None, :]
    for side in (1.0, -1.0):
        P = np.stack([0.18 - a * 0.08 * (1 - 0.5 * s) - s * 0.13,
                      -0.035 - a * 0.03 - s * 0.06 + 0 * a,
                      side * (0.07 + s * 0.11) + 0 * a], -1)
        uv = np.stack([a + 0 * s, s + 0 * a], -1)
        parts.append(_fish_part(P, uv, 3, (0.16, -0.04, side * 0.07)))

    verts, idx, base = [], [], 0
    for v, i in parts:
        verts.append(v)
        idx.append(i + base)
        base += len(v)
    return np.concatenate(verts), np.concatenate(idx).reshape(-1)


# ------------------------------------------------------------------ seaweed
def build_ribbon(segments=14):
    """Unit ribbon for seaweed: vertices (u 0..1 along the height, side -1/+1)."""
    u = np.linspace(0, 1, segments + 1)
    verts = np.stack([np.repeat(u, 2), np.tile([-1.0, 1.0], segments + 1)], -1)
    k = np.arange(segments) * 2
    idx = np.stack([k, k + 1, k + 2, k + 1, k + 3, k + 2], -1).reshape(-1)
    return verts.astype(np.float32), idx.astype(np.uint32)


def build_kelp_instances(rng, count=55):
    """Per-plant data: base(3) height/width/phase/yaw(4) color(3) -> (n, 10)."""
    palette = np.array([(0.18, 0.62, 0.18), (0.35, 0.72, 0.14), (0.10, 0.55, 0.35),
                        (0.62, 0.66, 0.12), (0.70, 0.35, 0.15), (0.20, 0.68, 0.42)])
    rows = []
    for _ in range(count):
        z = rng.uniform(-16.0, 0.8)
        hw, _, _ = world.view_extent(z, 3.0)
        cx = rng.uniform(-hw, hw) * 1.1
        for _blade in range(rng.integers(3, 7)):
            x, zz = cx + rng.normal(0, 0.35), z + rng.normal(0, 0.3)
            col = palette[rng.integers(0, len(palette))] * rng.uniform(0.8, 1.2)
            rows.append([x, world.floor_y(x, zz) - 0.05, zz,
                         rng.uniform(0.8, 2.7), rng.uniform(0.07, 0.14),
                         rng.uniform(0, 6.28), rng.uniform(0, 6.28), *col])
    return np.array(rows, np.float32)


# ------------------------------------------------------------- seabed, rocks
def build_seabed(rng, rock_count=22, coral_count=16):
    """Sand dunes, rocks and coral as one static mesh: pos(3) normal(3) color(3).

    Also returns the rocks/corals as ray-tracing occluders (ellipsoids):
    centre3 forward3 radii3 kind opacity colour3, shape (n, 14).
    """
    occ = []
    nz, nx = 90, 200
    z = np.linspace(-34.0, 6.0, nz)[:, None]
    x = np.linspace(-34.0, 34.0, nx)[None, :]
    P = np.stack([x + 0 * z, world.floor_y(x, z), z + 0 * x], -1)   # i=z, j=x
    n = _normals(P)
    nz_ = noise3(np.stack([x * 1.7 + 0 * z, 0 * x + 0 * z, z * 1.7 + 0 * x], -1))
    ripple = 0.5 + 0.5 * np.sin(x * 4.0 + nz_ * 6.0)
    sand = np.array([0.80, 0.72, 0.52])
    col = sand * (0.85 + 0.12 * nz_[..., None] + 0.05 * ripple[..., None])
    verts = [np.concatenate([P, n, col], -1).reshape(-1, 9)]
    idx = [_grid_indices(nz, nx)]
    base = nz * nx

    for k in range(rock_count):
        z0 = rng.uniform(-15.0, 1.2)
        hw, _, _ = world.view_extent(z0, 3.0)
        x0 = rng.uniform(-hw, hw) * 1.1
        scale = rng.uniform(0.35, 1.5) * (1.0 + 0.04 * -z0)
        th = np.linspace(0, 2 * np.pi, 33)[:, None]
        ph = np.linspace(0, np.pi, 21)[None, :]
        d = np.stack([np.sin(ph) * np.cos(th), np.cos(ph) + 0 * th,
                      np.sin(ph) * np.sin(th)], -1)
        nn = noise3(d * 1.9 + k * 7.1, seed=k) * 0.55 + noise3(d * 4.3, seed=k + 9) * 0.18
        rad = 0.7 + nn
        pts = d * rad[..., None] * np.array([1.0, 0.62, 0.85]) * scale
        pts[..., 1] = np.maximum(pts[..., 1], -0.25 * scale)       # flat-ish bottom
        c = pts + np.array([x0, world.floor_y(x0, z0) + 0.12 * scale, z0])
        tone = np.array([0.34, 0.31, 0.29]) * rng.uniform(0.7, 1.2)
        shade = (0.75 + 0.5 * noise3(d * 6.0, seed=k + 3))[..., None]
        verts.append(np.concatenate([c, _normals(c), tone * shade], -1).reshape(-1, 9))
        occ.append([x0, world.floor_y(x0, z0) + 0.15 * scale, z0, 1, 0, 0,
                    1.05 * scale, 0.62 * scale, 0.90 * scale, 1, 1.0, *(tone * 1.3)])
        idx.append(_grid_indices(33, 21, base))
        base += 33 * 21
    coral = np.array([(0.95, 0.35, 0.50), (1.0, 0.55, 0.15), (0.62, 0.30, 0.88),
                      (0.95, 0.80, 0.20), (0.20, 0.78, 0.72), (0.90, 0.25, 0.25)])
    for k in range(coral_count):
        z0 = rng.uniform(-12.0, 0.5)
        hw, _, _ = world.view_extent(z0, 3.0)
        x0 = rng.uniform(-hw, hw) * 1.05
        scale = rng.uniform(0.25, 0.75) * (1.0 + 0.04 * -z0)
        th = np.linspace(0, 2 * np.pi, 41)[:, None]
        ph = np.linspace(0, np.pi, 27)[None, :]
        d = np.stack([np.sin(ph) * np.cos(th), np.cos(ph) + 0 * th,
                      np.sin(ph) * np.sin(th)], -1)
        bumps = noise3(d * 5.5 + k * 3.7, seed=k + 40) * 0.30 + noise3(d * 14.0, seed=k + 70) * 0.10
        pts = d * (0.8 + bumps)[..., None] * np.array([1.0, 0.7, 1.0]) * scale
        pts[..., 1] = np.maximum(pts[..., 1], -0.2 * scale)
        c = pts + np.array([x0, world.floor_y(x0, z0) + 0.1 * scale, z0])
        tone = coral[rng.integers(0, len(coral))]
        polyp = (0.7 + 0.5 * noise3(d * 16.0, seed=k + 5))[..., None]
        verts.append(np.concatenate([c, _normals(c), tone * polyp], -1).reshape(-1, 9))
        occ.append([x0, world.floor_y(x0, z0) + 0.12 * scale, z0, 1, 0, 0,
                    1.0 * scale, 0.7 * scale, 1.0 * scale, 1, 1.0, *tone])
        idx.append(_grid_indices(41, 27, base))
        base += 41 * 27
    return (np.concatenate(verts).astype(np.float32),
            np.concatenate(idx).reshape(-1).astype(np.uint32),
            np.array(occ, np.float32))


# ---------------------------------------------------------------- jellyfish
def build_jelly_bell():
    """Bell: pos(3) normal(3), y up, opening downward, rim curled inward."""
    th = np.linspace(0, 2 * np.pi, 33)[:, None]
    ph = np.linspace(0.0, 1.75, 16)[None, :]
    rho = np.sin(ph) * (1.0 + 0.10 * np.sin(3 * ph))
    P = np.stack([rho * np.cos(th), np.cos(ph) * 0.8 + 0 * th, rho * np.sin(th)], -1)
    verts = np.concatenate([P, _normals(P)], -1).reshape(-1, 6)
    return verts.astype(np.float32), _grid_indices(33, 16).reshape(-1)


def build_jelly_tentacles(count=14, segments=18):
    """Hanging ribbons: (u 0..1 down the tentacle, side -1/+1, index k)."""
    rows, idx, base = [], [], 0
    for k in range(count):
        for i in range(segments + 1):
            u = i / segments
            rows += [[u, -1.0, k], [u, 1.0, k]]
        s = np.arange(segments) * 2 + base
        idx.append(np.stack([s, s + 1, s + 2, s + 1, s + 3, s + 2], -1).reshape(-1))
        base += (segments + 1) * 2
    return np.array(rows, np.float32), np.concatenate(idx).astype(np.uint32)
