"""Ray-tracing support data (CPU side).

Occluders (fish, jellyfish, rocks, coral) are ellipsoids stored in a float
texture. To answer "is this point in shadow?" cheaply, they are also binned in
a uniform 2D grid in *sun space*: projecting every point along the light
direction onto a plane makes all points of one sun ray land in the same cell,
so a shadow ray only tests the few ellipsoids of its own cell.
"""
import numpy as np

# Grid in sun space (x, z of the projection onto y = 0)
GRID_ORIGIN = (-40.0, -34.0)
CELL = 0.6
GRID_W, GRID_H = 134, 78
K = 12                      # occluders remembered per cell
MAX_OCC = 400

# World-space grid (x, z cells) used by ambient-occlusion rays
WGRID_ORIGIN = (-40.0, -34.0)
WCELL = 2.0
WGRID_W, WGRID_H = 42, 25
WK = 14

# Caustic map: where refracted sunlight lands on the sea floor plane
# irradiance probe grid (ambient cube per probe)
GI_ORIGIN = (-28.0, -2.4, -36.0)
GI_STEP = (1.5, 1.1, 1.5)
GI_DIM = (38, 6, 30)

MAP_ORIGIN = (-32.0, -22.0)
MAP_SIZE = (64.0, 30.0)
MAP_RES = (2560, 1200)         # ~2.5 cm per texel: caustic lines are thin
# Grid of water-surface points the sun rays pass through
SURF_X, SURF_Z, SURF_STEP = (-36.0, 36.0), (-26.0, 12.0), 0.09   # dense: one ray per vertex
WATER_ETA = 1.0 / 1.333


def refracted_down(light_dir):
    """Direction of sunlight after entering a flat water surface (unit, y < 0)."""
    i = -np.asarray(light_dir, float) / np.linalg.norm(light_dir)
    n = np.array([0.0, 1.0, 0.0])
    cosi = -np.dot(n, i)
    k = 1.0 - WATER_ETA ** 2 * (1.0 - cosi ** 2)
    return WATER_ETA * i + (WATER_ETA * cosi - np.sqrt(k)) * n


class OccluderSet:
    def __init__(self, static):
        self.static = np.asarray(static, np.float32)
        self.n_static = len(self.static)
        self._key = None
        self._grid = self._cnt = None
        self._wgrid = np.full((WGRID_H, WGRID_W, WK), -1.0, np.float32)   # static part, built once
        self._wcnt = np.zeros((WGRID_H, WGRID_W), np.int32)
        for i, rec in enumerate(self.static):
            self._insert_world(self._wgrid, self._wcnt, rec, i)

    @staticmethod
    def _insert_world(grid, cnt, rec, ident):
        """Register an occluder in every world cell its bounding sphere touches.
        See-through occluders (kelp, jellyfish) are left out of the AO grid."""
        if rec[10] < 0.5:
            return
        r = max(rec[6:9]) + 0.1
        x0 = max(int((rec[0] - r - WGRID_ORIGIN[0]) // WCELL), 0)
        x1 = min(int((rec[0] + r - WGRID_ORIGIN[0]) // WCELL), WGRID_W - 1)
        z0 = max(int((rec[2] - r - WGRID_ORIGIN[1]) // WCELL), 0)
        z1 = min(int((rec[2] + r - WGRID_ORIGIN[1]) // WCELL), WGRID_H - 1)
        for cz in range(z0, z1 + 1):
            for cx in range(x0, x1 + 1):
                n = cnt[cz, cx]
                if n < WK:
                    grid[cz, cx, n] = ident
                    cnt[cz, cx] = n + 1

    # ----------------------------------------------------------------- grid
    def _insert(self, grid, cnt, rec, ident, light):
        ly = max(light[1], 0.3)
        r = max(rec[6:9]) * 1.5 / ly + CELL
        qx = rec[0] - light[0] * (rec[1] / light[1])
        qz = rec[2] - light[2] * (rec[1] / light[1])
        x0 = max(int((qx - r - GRID_ORIGIN[0]) // CELL), 0)
        x1 = min(int((qx + r - GRID_ORIGIN[0]) // CELL), GRID_W - 1)
        z0 = max(int((qz - r - GRID_ORIGIN[1]) // CELL), 0)
        z1 = min(int((qz + r - GRID_ORIGIN[1]) // CELL), GRID_H - 1)
        for cz in range(z0, z1 + 1):
            for cx in range(x0, x1 + 1):
                n = cnt[cz, cx]
                if n < K:
                    grid[cz, cx, n] = ident
                    cnt[cz, cx] = n + 1

    def build(self, dynamic, light):
        """-> (occluder texture (4, MAX_OCC, 4), sun-space grid (H, W*K),
        world grid (WH, WW*WK), count)."""
        light = np.asarray(light, float)
        key = tuple(np.round(light, 3))
        if key != self._key:                      # rocks/coral only depend on the light
            grid = np.full((GRID_H, GRID_W, K), -1.0, np.float32)
            cnt = np.zeros((GRID_H, GRID_W), np.int32)
            for i, rec in enumerate(self.static):
                self._insert(grid, cnt, rec, i, light)
            self._grid, self._cnt, self._key = grid, cnt, key
        grid, cnt = self._grid.copy(), self._cnt.copy()
        room = MAX_OCC - self.n_static
        dyn = np.asarray(dynamic, np.float32)[:room]
        wgrid, wcnt = self._wgrid.copy(), self._wcnt.copy()
        for j, rec in enumerate(dyn):
            self._insert(grid, cnt, rec, self.n_static + j, light)
            self._insert_world(wgrid, wcnt, rec, self.n_static + j)

        recs = np.concatenate([self.static, dyn]) if len(dyn) else self.static
        tex = np.zeros((4, MAX_OCC, 4), np.float32)
        n = len(recs)
        tex[0, :n, 0:3], tex[0, :n, 3] = recs[:, 0:3], recs[:, 6]
        tex[1, :n, 0:3], tex[1, :n, 3] = recs[:, 3:6], recs[:, 7]
        tex[2, :n, 0], tex[2, :n, 1], tex[2, :n, 2] = recs[:, 8], recs[:, 9], recs[:, 10]
        tex[3, :n, 0:3] = recs[:, 11:14]
        tex[3, :n, 3] = recs[:, 6:9].max(axis=1)        # bounding sphere for quick rejection
        return tex, grid.reshape(GRID_H, GRID_W * K), wgrid.reshape(WGRID_H, WGRID_W * WK), n


def surface_grid():
    """Static vertex grid (x, z) of the water surface used to trace sun rays."""
    xs = np.arange(SURF_X[0], SURF_X[1] + 1e-6, SURF_STEP, dtype=np.float32)
    zs = np.arange(SURF_Z[0], SURF_Z[1] + 1e-6, SURF_STEP, dtype=np.float32)
    gx, gz = np.meshgrid(xs, zs)
    verts = np.stack([gx, gz], -1).reshape(-1, 2).astype(np.float32)
    ni, nj = len(zs), len(xs)
    i, j = np.meshgrid(np.arange(ni - 1), np.arange(nj - 1), indexing="ij")
    a = (i * nj + j).ravel()
    b = ((i + 1) * nj + j).ravel()
    c = (i * nj + j + 1).ravel()
    d = ((i + 1) * nj + j + 1).ravel()
    idx = np.stack([a, b, c, b, d, c], -1).reshape(-1).astype(np.uint32)
    return verts, idx
