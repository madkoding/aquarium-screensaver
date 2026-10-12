"""World constants shared by the simulation, the meshes and the renderer.

Coordinates: +x right, +y up, the camera sits at +z looking toward -z.
"""
import numpy as np

CAM_Z = 7.0
CAM_Y = 0.0
FOV = np.radians(45.0)
LOOK_AT = np.array([0.0, -0.5, -10.0])
FLOOR_Y = -2.3
SURFACE_Y = 3.0                     # mean height of the water surface
Z_NEAR_LIMIT, Z_FAR_LIMIT = 2.5, -15.0   # swimmable depth range
_TAN = np.tan(FOV / 2)
_SLOPE = (LOOK_AT[1] - CAM_Y) / (LOOK_AT[2] - CAM_Z)   # screen-centre y per unit z


def floor_y(x, z):
    """Height of the sandy bottom (smooth dunes); works on numpy arrays."""
    return (FLOOR_Y + 0.16 * np.sin(x * 0.33 + z * 0.21)
            + 0.10 * np.sin(x * 0.87 - z * 0.53 + 1.3)
            + 0.06 * np.sin(z * 0.9 + x * 0.2))


def view_extent(z, aspect):
    """(half_width, half_height, centre_y) of what the camera sees at depth z."""
    d = CAM_Z - z
    hh = _TAN * d
    return aspect * hh, hh, CAM_Y + (z - CAM_Z) * _SLOPE


def perspective(aspect, near=0.1, far=90.0):
    f = 1.0 / np.tan(FOV / 2)
    m = np.zeros((4, 4))
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye, target, up=(0.0, 1.0, 0.0)):
    eye, target, up = (np.asarray(v, float) for v in (eye, target, up))
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m
