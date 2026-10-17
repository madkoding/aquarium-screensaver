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
    """-> (vertices float32 (n, 12), body indices, fin indices) as uint32."""
    parts = []

    # Body: i = angle around the axis, j = length
    na, nt = 48, 84
    th = np.linspace(0, 2 * np.pi, na + 1)[:, None]
    t = np.linspace(0, 1, nt + 1)[None, :]
    r = _profile(t)
    sin = np.sin(th)
    cos = np.cos(th)
    y = HALF_H * r * np.where(sin > 0, sin, 0.8 * sin)
    z = HALF_T * r * cos
    x = 0.5 - t + 0 * th
    # head: the lower jaw sits back from the snout, the brow rises a little behind it
    head = np.clip(1.0 - t / 0.30, 0.0, 1.0) ** 1.6
    x = x - 0.020 * head * np.clip(-sin, 0.0, 1.0)
    y = y + 0.012 * head * np.clip(sin, 0.0, 1.0) * (1.0 - head)
    # eyeball bulging out of the head (eye centre at x = 0.375, y = 0.03)
    de = np.hypot(x - 0.375, y - 0.03)
    dome = 0.014 * np.sqrt(np.clip(1.0 - (de / 0.036) ** 2, 0.0, 1.0))
    socket = -0.004 * np.exp(-(((de - 0.052) / 0.012) ** 2))
    side = np.clip((np.abs(cos) - 0.35) / 0.25, 0.0, 1.0)
    z = z + np.sign(cos) * (dome + socket) * side
    P = np.stack([x, y, z], -1)
    uv = np.stack([t + 0 * th, sin + 0 * t], -1)
    parts.append(_fish_part(P, uv, 0, (0, 0, 0)))

    # Tail fin: i = vertical -1..1, j = outward 0..1 (forked, widening)
    u = np.linspace(-1, 1, 25)[:, None]
    s = np.linspace(0, 1, 9)[None, :]
    P = np.stack([-0.495 - s * (0.09 + 0.15 * np.abs(u) ** 1.5),
                  u * (0.055 + 0.19 * s ** 0.8), 0 * u + 0 * s], -1)
    uv = np.stack([(u + 1) / 2 + 0 * s, s + 0 * u], -1)
    parts.append(_fish_part(P, uv, 1, (-0.495, 0, 0)))

    # Dorsal fin on the back, taller at the front and swept backwards
    a = np.linspace(0, 1, 22)[:, None]
    b = np.linspace(0, 1, 6)[None, :]
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
    a = np.linspace(0, 1, 8)[:, None]
    s = np.linspace(0, 1, 9)[None, :]
    for side in (1.0, -1.0):
        P = np.stack([0.18 - a * 0.08 * (1 - 0.5 * s) - s * 0.13,
                      -0.035 - a * 0.03 - s * 0.06 + 0 * a,
                      side * (0.07 + s * 0.11) + 0 * a], -1)
        uv = np.stack([a + 0 * s, s + 0 * a], -1)
        parts.append(_fish_part(P, uv, 3, (0.16, -0.04, side * 0.07)))

    a = np.linspace(0, 1, 6)[:, None]
    s = np.linspace(0, 1, 7)[None, :]
    for side in (1.0, -1.0):
        x0 = 0.13 - a * 0.07
        ybase = -0.8 * HALF_H * _profile(0.5 - x0) + 0.006
        P = np.stack([x0 - s * 0.075 * (0.4 + 0.6 * a), ybase - s * 0.085 * (1.0 - 0.35 * a),
                      side * (0.032 + s * 0.030) + 0 * a], -1)
        uv = np.stack([a + 0 * s, s + 0 * a], -1)
        parts.append(_fish_part(P, uv, 4, (0.10, float(-0.8 * HALF_H * _profile(0.40) + 0.006), side * 0.032)))

    verts, idx, base = [], [], 0
    for v, i in parts:
        verts.append(v)
        idx.append(i + base)
        base += len(v)
    body = idx[0].reshape(-1)                       # drawn opaque
    fins = np.concatenate(idx[1:]).reshape(-1)      # drawn translucent
    return np.concatenate(verts), body, fins


# ------------------------------------------------------------------ seaweed
def build_ribbon(segments=14):
    """Unit ribbon for seaweed: vertices (u 0..1 along the height, side -1/+1)."""
    u = np.linspace(0, 1, segments + 1)
    verts = np.stack([np.repeat(u, 2), np.tile([-1.0, 1.0], segments + 1)], -1)
    k = np.arange(segments) * 2
    idx = np.stack([k, k + 1, k + 2, k + 1, k + 3, k + 2], -1).reshape(-1)
    return verts.astype(np.float32), idx.astype(np.uint32)


def build_kelp_instances(rng, count=55):
    """Kelp blades: base(3) height/width/phase/yaw(4) colour(3) kind(1) -> (n, 11).

    Also returns one soft occluder per clump so kelp forests cast shadows:
    centre3 forward3 radii3 kind opacity colour3, shape (m, 14).
    """
    palette = np.array([(0.18, 0.62, 0.18), (0.35, 0.72, 0.14), (0.10, 0.55, 0.35),
                        (0.62, 0.66, 0.12), (0.70, 0.35, 0.15), (0.20, 0.68, 0.42)])
    rows, occ = [], []
    for _ in range(count):
        z = rng.uniform(-16.0, 0.8)
        hw, _, _ = world.view_extent(z, 3.0)
        cx = rng.uniform(-hw, hw) * 1.1
        hs = []
        for _blade in range(rng.integers(3, 7)):
            x, zz = cx + rng.normal(0, 0.35), z + rng.normal(0, 0.3)
            col = palette[rng.integers(0, len(palette))] * rng.uniform(0.8, 1.2)
            h = rng.uniform(0.8, 2.7)
            hs.append(h)
            rows.append([x, world.floor_y(x, zz) - 0.05, zz, h, rng.uniform(0.07, 0.14),
                         rng.uniform(0, 6.28), rng.uniform(0, 6.28), *col, 0.0])
        hm = float(np.mean(hs))
        occ.append([cx, world.floor_y(cx, z) + 0.5 * hm, z, 1, 0, 0,
                    0.55, 0.5 * hm, 0.55, 1, 0.35, 0.2, 0.5, 0.2])
    return np.array(rows, np.float32), np.array(occ, np.float32)


def build_seagrass_instances(rng, patches=20):
    """Short grass blades in patches, same layout as the kelp rows (kind 2)."""
    rows = []
    for _ in range(patches):
        z = rng.uniform(-12.0, 1.5)
        hw, _, _ = world.view_extent(z, 3.0)
        cx = rng.uniform(-hw, hw)
        for _b in range(rng.integers(18, 34)):
            a, r = rng.uniform(0, 6.28), 0.55 * np.sqrt(rng.uniform())
            x, zz = cx + r * np.cos(a), z + r * np.sin(a)
            col = np.array([0.22, 0.58, 0.20]) * rng.uniform(0.75, 1.3)
            rows.append([x, world.floor_y(x, zz) - 0.03, zz, rng.uniform(0.35, 0.85),
                         rng.uniform(0.035, 0.06), rng.uniform(0, 6.28),
                         rng.uniform(0, 6.28), *col, 2.0])
    return np.array(rows, np.float32)


def build_anemone_instances(rng, anemones):
    """Tentacles (kind 1) around each anemone base: (n, 11) kelp-layout rows."""
    palette = np.array([(0.95, 0.35, 0.55), (0.40, 0.85, 0.50), (0.98, 0.72, 0.22),
                        (0.70, 0.45, 0.95)])
    rows = []
    for x, y, z, sc, pal in anemones:
        col = palette[int(pal) % len(palette)]
        for _ in range(38):
            a, r = rng.uniform(0, 6.28), 0.2 * sc * np.sqrt(rng.uniform())
            tx, tz = x + r * np.cos(a), z + r * np.sin(a)
            rows.append([tx, world.floor_y(tx, tz) + 0.04 * sc, tz,
                         rng.uniform(0.30, 0.55) * sc, 0.035 * sc ** 0.5,
                         rng.uniform(0, 6.28), a, *(col * rng.uniform(0.85, 1.15)), 1.0])
    return np.array(rows, np.float32)


# ------------------------------------------------------------- seabed, rocks
def _vrows(pos, nrm, col, mat, uv=None):
    """Grid arrays (..., 3) -> vertex rows (n, 12): pos nrm colour material uv."""
    shape = pos.shape[:-1]
    col = np.broadcast_to(np.asarray(col, float), shape + (3,))
    m = np.full(shape + (1,), float(mat))
    u = np.zeros(shape + (2,)) if uv is None else uv
    return np.concatenate([pos, nrm, col, m, u], -1).reshape(-1, 12)


def _sphere_dirs(nth, nph):
    th = np.linspace(0, 2 * np.pi, nth)[:, None]
    ph = np.linspace(0, np.pi, nph)[None, :]
    return np.stack([np.sin(ph) * np.cos(th), np.cos(ph) + 0 * th,
                     np.sin(ph) * np.sin(th)], -1)


def _tube(pts, radii, col_base, col_tip, sides=14):
    """Tapered tube along a polyline -> (P, N, C) grids of shape (n, sides+1, 3)."""
    n = len(pts)
    T = np.gradient(pts, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True) + 1e-9
    ref = np.where(np.abs(T[:, 2:3]) < 0.9, np.array([[0.0, 0.0, 1.0]]), np.array([[1.0, 0.0, 0.0]]))
    n1 = np.cross(T, ref)
    n1 /= np.linalg.norm(n1, axis=1, keepdims=True) + 1e-9
    n2 = np.cross(T, n1)
    a = np.linspace(0, 2 * np.pi, sides + 1)
    ring = np.cos(a)[None, :, None] * n1[:, None, :] + np.sin(a)[None, :, None] * n2[:, None, :]
    P = pts[:, None, :] + radii[:, None, None] * ring
    t = np.linspace(0, 1, n)[:, None, None]
    C = np.asarray(col_base) * (1 - t) + np.asarray(col_tip) * t + 0 * ring
    return P, ring, C


def _unit(v):
    return v / (np.linalg.norm(v) + 1e-9)


def _branching_coral(rng, base, scale, col_base, col_tip):
    """Staghorn-style colony: main branches with side branches, as tube meshes."""
    tubes = []
    for _ in range(rng.integers(6, 10)):
        ang, spread = rng.uniform(0, 2 * np.pi), rng.uniform(0.25, 0.75)
        d = _unit(np.array([np.cos(ang) * spread, 1.0, np.sin(ang) * spread]))
        length = rng.uniform(0.6, 1.2) * scale
        pts = base + d[None, :] * np.linspace(0, 1, 5)[:, None] * length
        pts = pts + rng.normal(0, 0.03 * scale, pts.shape) * np.linspace(0, 1, 5)[:, None]
        tubes.append((pts, np.linspace(0.07, 0.025, 5) * scale))
        for _s in range(rng.integers(2, 4)):
            start = pts[int(rng.uniform(0.35, 0.8) * 4)]
            a2 = rng.uniform(0, 2 * np.pi)
            d2 = _unit(d + np.array([np.cos(a2) * 0.9, 0.2, np.sin(a2) * 0.9]))
            pts2 = start + d2[None, :] * np.linspace(0, 1, 4)[:, None] * length * rng.uniform(0.35, 0.55)
            tubes.append((pts2, np.linspace(0.04, 0.015, 4) * scale))
    out = []
    for pts, radii in tubes:
        P, N, C = _tube(pts, radii, col_base, col_tip)
        out.append((P, N, C))
    return out


def build_seabed(rng, rock_count=22, coral_count=16):
    """Sand, rocks, pebbles, coral, anemone bases and sea fans as one static mesh.

    Vertex rows: pos3 normal3 colour3 material1 uv2 (12 floats).
    Material: 0 sand, 1 rock, 2 coral head, 3 pebble, 4 branching coral,
              5 table coral, 6 sea fan (alpha-cut lattice).
    Returns (vertices, indices, occluders (n, 14), anemones (m, 5)); occluders
    are ellipsoids for shadow rays: centre3 forward3 radii3 kind opacity colour3.
    """
    verts, idx, occ, base = [], [], [], 0

    def add(rows, ni, nj):
        nonlocal base
        verts.append(rows)
        idx.append(_grid_indices(ni, nj, base))
        base += ni * nj

    # --- sand dunes (i = z, j = x)
    nz, nx = 90, 200
    z = np.linspace(-34.0, 6.0, nz)[:, None]
    x = np.linspace(-34.0, 34.0, nx)[None, :]
    P = np.stack([x + 0 * z, world.floor_y(x, z), z + 0 * x], -1)
    n = _normals(P)
    nz_ = noise3(np.stack([x * 1.7 + 0 * z, 0 * x + 0 * z, z * 1.7 + 0 * x], -1))
    ripple = 0.5 + 0.5 * np.sin(x * 4.0 + nz_ * 6.0)
    sand = np.array([0.80, 0.72, 0.52])
    col = sand * (0.85 + 0.12 * nz_[..., None] + 0.05 * ripple[..., None])
    add(_vrows(P, n, col, 0), nz, nx)

    # --- rocks: layered displacement, flat bottoms
    for k in range(rock_count):
        z0 = rng.uniform(-15.0, 1.2)
        hw, _, _ = world.view_extent(z0, 3.0)
        x0 = rng.uniform(-hw, hw) * 1.1
        scale = rng.uniform(0.35, 1.5) * (1.0 + 0.04 * -z0)
        d = _sphere_dirs(97, 65)
        nn = (noise3(d * 1.9 + k * 7.1, seed=k) * 0.55 + noise3(d * 4.3, seed=k + 9) * 0.18
              + np.abs(noise3(d * 9.0, seed=k + 21) - 0.5) * 0.14
              + np.abs(noise3(d * 21.0, seed=k + 33) - 0.5) * 0.045)
        pts = d * (0.7 + nn)[..., None] * np.array([1.0, 0.62, 0.85]) * scale
        pts[..., 1] = np.maximum(pts[..., 1], -0.25 * scale)
        c = pts + np.array([x0, world.floor_y(x0, z0) + 0.12 * scale, z0])
        tone = np.array([0.34, 0.31, 0.29]) * rng.uniform(0.7, 1.2)
        shade = (0.75 + 0.5 * noise3(d * 6.0, seed=k + 3))[..., None]
        add(_vrows(c, _normals(c), tone * shade, 1), 97, 65)
        occ.append([x0, world.floor_y(x0, z0) + 0.15 * scale, z0, 1, 0, 0,
                    1.05 * scale, 0.62 * scale, 0.90 * scale, 1, 1.0, *(tone * 1.3)])

    # --- pebbles scattered over the sand
    peb = np.array([(0.45, 0.43, 0.40), (0.62, 0.58, 0.50), (0.30, 0.30, 0.32), (0.78, 0.74, 0.66)])
    for k in range(520):
        z0 = rng.uniform(-13.0, 3.0)
        hw, _, _ = world.view_extent(z0, 3.0)
        x0 = rng.uniform(-hw, hw) * 1.1
        sc = rng.uniform(0.025, 0.13)
        d = _sphere_dirs(9, 7)
        pts = d * np.array([1.0, 0.65, 0.85]) * sc * (1.0 + 0.2 * noise3(d * 3.0 + k, seed=k))[..., None]
        c = pts + np.array([x0, world.floor_y(x0, z0) + 0.2 * sc, z0])
        add(_vrows(c, _normals(c), peb[rng.integers(0, 4)] * rng.uniform(0.8, 1.15), 3), 9, 7)

    # --- coral heads (brain/boulder)
    coral = np.array([(0.95, 0.35, 0.50), (1.0, 0.55, 0.15), (0.62, 0.30, 0.88),
                      (0.95, 0.80, 0.20), (0.20, 0.78, 0.72), (0.90, 0.25, 0.25)])
    for k in range(coral_count):
        z0 = rng.uniform(-12.0, 0.5)
        hw, _, _ = world.view_extent(z0, 3.0)
        x0 = rng.uniform(-hw, hw) * 1.05
        scale = rng.uniform(0.25, 0.75) * (1.0 + 0.04 * -z0)
        d = _sphere_dirs(81, 55)
        bumps = noise3(d * 5.5 + k * 3.7, seed=k + 40) * 0.30 + noise3(d * 14.0, seed=k + 70) * 0.10
        pts = d * (0.8 + bumps)[..., None] * np.array([1.0, 0.7, 1.0]) * scale
        pts[..., 1] = np.maximum(pts[..., 1], -0.2 * scale)
        c = pts + np.array([x0, world.floor_y(x0, z0) + 0.1 * scale, z0])
        tone = coral[rng.integers(0, len(coral))]
        polyp = (0.7 + 0.5 * noise3(d * 16.0, seed=k + 5))[..., None]
        add(_vrows(c, _normals(c), tone * polyp, 2), 81, 55)
        occ.append([x0, world.floor_y(x0, z0) + 0.12 * scale, z0, 1, 0, 0,
                    1.0 * scale, 0.7 * scale, 1.0 * scale, 1, 1.0, *tone])

    # --- branching (staghorn) colonies
    for k in range(9):
        z0 = rng.uniform(-11.0, 0.5)
        hw, _, _ = world.view_extent(z0, 3.0)
        x0 = rng.uniform(-hw, hw) * 1.05
        scale = rng.uniform(0.7, 1.3) * (1.0 + 0.04 * -z0)
        b = np.array([x0, world.floor_y(x0, z0), z0])
        cb = coral[rng.integers(0, len(coral))]
        for P, N, C in _branching_coral(rng, b, scale, cb * 0.75, np.clip(cb * 1.25 + 0.15, 0, 1)):
            add(_vrows(P, N, C, 4), P.shape[0], P.shape[1])
        occ.append([x0, b[1] + 0.55 * scale, z0, 1, 0, 0, 0.6 * scale, 0.55 * scale, 0.6 * scale,
                    1, 0.7, *cb])

    # --- table corals: a ruffled plate on a short stalk
    for k in range(6):
        z0 = rng.uniform(-10.0, 0.0)
        hw, _, _ = world.view_extent(z0, 3.0)
        x0 = rng.uniform(-hw, hw)
        R = rng.uniform(0.5, 0.95) * (1.0 + 0.04 * -z0)
        h = rng.uniform(0.25, 0.5)
        tone = np.array([(0.85, 0.55, 0.70), (0.60, 0.78, 0.40), (0.55, 0.65, 0.90)])[k % 3]
        th = np.linspace(0, 2 * np.pi, 49)[:, None]
        rr = np.linspace(0, 1, 14)[None, :]
        ruffle = 1.0 + 0.12 * np.sin(5 * th + 1.7 * k) + 0.06 * np.sin(11 * th)
        for side in (1.0, -1.0):
            pts = np.stack([R * rr * ruffle * np.cos(th), 0 * th + side * 0.035 * R * (1.0 - 0.6 * rr ** 2)
                            + 0.05 * R * rr ** 2 * (1 if side > 0 else 0.5), R * rr * ruffle * np.sin(th)], -1)
            c = pts + np.array([x0, world.floor_y(x0, z0) + h, z0])
            add(_vrows(c, _normals(c) * side, tone * (0.9 + 0.2 * rr[..., None] + 0 * th[..., None]), 5), 49, 14)
        stalk = np.array([[x0, world.floor_y(x0, z0), z0], [x0, world.floor_y(x0, z0) + h, z0]])
        stalk = np.linspace(stalk[0], stalk[1], 4)
        P, N, C = _tube(stalk, np.array([0.10, 0.08, 0.07, 0.07]) * R, tone * 0.7, tone * 0.8)
        add(_vrows(P, N, C, 5), P.shape[0], P.shape[1])
        occ.append([x0, world.floor_y(x0, z0) + h, z0, 1, 0, 0, R * 0.95, 0.08 * R + 0.04, R * 0.95,
                    1, 0.9, *tone])

    # --- sea fans: a lattice cut out of a bent plane
    fan_cols = np.array([(0.78, 0.14, 0.34), (0.90, 0.45, 0.10), (0.62, 0.22, 0.75)])
    for k in range(8):
        z0 = rng.uniform(-10.0, 0.5)
        hw, _, _ = world.view_extent(z0, 3.0)
        x0 = rng.uniform(-hw, hw)
        W, H = rng.uniform(0.7, 1.2), rng.uniform(0.8, 1.4)
        yaw = rng.uniform(0, np.pi)
        u = np.linspace(0, 1, 15)[:, None]
        v = np.linspace(0, 1, 19)[None, :]
        lx = (u - 0.5) * W * (0.25 + 0.75 * v)
        ly = v * H + 0 * u
        lz = 0.12 * np.sin(u * 3.0 + k) * v + 0.0 * u
        px = lx * np.cos(yaw) - lz * np.sin(yaw)
        pz = lx * np.sin(yaw) + lz * np.cos(yaw)
        c = np.stack([px + x0, ly + world.floor_y(x0, z0) - 0.02, pz + z0], -1)
        add(_vrows(c, _normals(c), fan_cols[k % 3] * (0.8 + 0.3 * v[..., None] + 0 * u[..., None]), 6,
                   np.stack([u + 0 * v, v + 0 * u], -1)), 15, 19)

    # --- anemones: a flat base here, the tentacles are instanced elsewhere
    anemones = []
    for k in range(10):
        z0 = rng.uniform(-9.0, 0.5)
        hw, _, _ = world.view_extent(z0, 3.0)
        x0 = rng.uniform(-hw, hw)
        sc = rng.uniform(0.8, 1.5) * (1.0 + 0.03 * -z0)
        d = _sphere_dirs(25, 15)
        pts = d * np.array([0.22, 0.09, 0.22]) * sc
        pts[..., 1] = np.maximum(pts[..., 1], -0.02 * sc)
        c = pts + np.array([x0, world.floor_y(x0, z0) + 0.03 * sc, z0])
        add(_vrows(c, _normals(c), np.array([0.55, 0.30, 0.35]), 2), 25, 15)
        anemones.append([x0, world.floor_y(x0, z0), z0, sc, k])

    return (np.concatenate(verts).astype(np.float32),
            np.concatenate(idx).reshape(-1).astype(np.uint32),
            np.array(occ, np.float32), np.array(anemones, np.float32))


# ---------------------------------------------------------------- jellyfish
def build_jelly_bell():
    """Bell: pos(3) normal(3), y up, opening downward, rim curled inward."""
    th = np.linspace(0, 2 * np.pi, 97)[:, None]
    ph = np.linspace(0.0, 1.75, 40)[None, :]
    rho = np.sin(ph) * (1.0 + 0.10 * np.sin(3 * ph))
    rim = np.clip((ph - 1.25) / 0.5, 0.0, 1.0)
    rho = rho * (1.0 + 0.045 * np.sin(16 * th) * rim)            # scalloped margin
    y = np.cos(ph) * 0.8 - 0.035 * np.abs(np.sin(8 * th)) * rim
    P = np.stack([rho * np.cos(th), y + 0 * th, rho * np.sin(th)], -1)
    verts = np.concatenate([P, _normals(P)], -1).reshape(-1, 6)
    return verts.astype(np.float32), _grid_indices(97, 40).reshape(-1)


def build_jelly_tentacles(count=18, segments=28):
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
