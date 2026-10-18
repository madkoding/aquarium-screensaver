"""u_irid must be sent as 0.0 or 1.0 from cfg['iridescence'], to every shader program.

No GL context: AquariumRenderer is built without __init__ and its programs
are replaced by recording doubles. These tests do not prove that the shaders
compile or that the output looks right on screen.
"""
import os
import re
import shutil
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

import renderer
import settings

HERE = os.path.dirname(os.path.abspath(__file__))

ENV = dict(
    day=0.5,
    top=np.array([0.1, 0.5, 0.6]),
    bot=np.array([0.0, 0.1, 0.2]),
    sun_col=np.array([1.0, 0.9, 0.8]),
    sun_dir=np.array([0.0, 1.0, 0.0]),
)


class _Uniform:
    def __init__(self):
        self.value = None
        self.data = None

    def write(self, data):
        self.data = data


class _Program(dict):
    """Records every uniform the renderer sets on it."""

    def __missing__(self, name):
        uniform = _Uniform()
        self[name] = uniform
        return uniform


def _program_names():
    """Names of the shader programs renderer.py builds in __init__ (name=prog(...))."""
    with open(os.path.join(HERE, "renderer.py"), encoding="utf-8") as fh:
        return re.findall(r"^\s+(\w+)=prog\(", fh.read(), re.MULTILINE)


def _run_uniforms(cfg):
    r = renderer.AquariumRenderer.__new__(renderer.AquariumRenderer)
    r.cfg = cfg
    r.scene_size = (64, 36)
    r.proj = np.eye(4)
    r.jitter_on = False
    r.rt_on = False
    r._frame_idx = 0
    r._rt_n = 0
    r._refr = np.array([0.0, -1.0, 0.0])
    r.occ = types.SimpleNamespace(n_static=0)
    r.p = {name: _Program() for name in _program_names()}
    r._uniforms(1.0, ENV, np.zeros(3), np.eye(4))
    return r


def _load_settings(test, text):
    """Writes text as settings.json under a temporary APPDATA and returns settings.load().

    The temporary directory is removed by addCleanup, even if the test fails.
    APPDATA is only overridden while settings.load() runs; mock restores it on exit.
    """
    appdata = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, appdata, True)
    folder = os.path.join(appdata, "AquariumScreensaver")
    os.makedirs(folder)
    with open(os.path.join(folder, "settings.json"), "w", encoding="utf-8") as fh:
        fh.write(text)
    with mock.patch.dict(os.environ, {"APPDATA": appdata}):
        return settings.load()


class IridescenceWiringTest(unittest.TestCase):
    def _assert_all(self, r, expected):
        names = _program_names()
        self.assertGreaterEqual(len(names), 20)
        self.assertIn("fish", names)
        for name in names:
            with self.subTest(program=name):
                self.assertEqual(r.p[name]["u_irid"].value, expected)

    def test_disabled_sends_zero_to_every_program(self):
        r = _run_uniforms({"iridescence": False, "realism": 0.5})
        self._assert_all(r, 0.0)

    def test_enabled_sends_one_to_every_program(self):
        r = _run_uniforms({"iridescence": True, "realism": 0.5})
        self._assert_all(r, 1.0)

    def test_missing_key_sends_settings_default(self):
        # cfg always comes from settings.load(), which overlays the file on DEFAULTS.
        cfg = _load_settings(self, "{}")
        self.assertEqual(cfg["iridescence"], settings.DEFAULTS["iridescence"])
        r = _run_uniforms(cfg)
        expected = 1.0 if settings.DEFAULTS["iridescence"] else 0.0
        self._assert_all(r, expected)

    def test_taa_missing_key_sends_settings_default(self):
        # 'taa' is a second boolean key: same overlay of the file on DEFAULTS, checked on the cfg the renderer receives.
        cfg = _load_settings(self, "{}")
        self.assertEqual(cfg["taa"], settings.DEFAULTS["taa"])
        r = _run_uniforms(cfg)
        self.assertIs(r.cfg["taa"], settings.DEFAULTS["taa"])

    def test_taa_false_in_file_overrides_default(self):
        # The file overrides DEFAULTS for a second boolean key: taa True -> False.
        cfg = _load_settings(self, '{"taa": false}')
        self.assertIs(cfg["taa"], False)

    def test_taa_false_passed_through_uniforms_sends_no_jitter(self):
        # taa drives jitter_on in __init__ and the TAA pass in render(); both need a GL context.
        # _uniforms() itself only uses the jitter flag, so with taa off the projection must stay unjittered.
        r = _run_uniforms({"taa": False, "iridescence": False, "realism": 0.5})
        self.assertIs(r.cfg["taa"], False)
        self.assertEqual(r._jit, (0.0, 0.0))
        expected = np.ascontiguousarray(np.eye(4).T, dtype="f4").tobytes()
        self.assertEqual(r.p["fish"]["u_proj"].data, expected)


class TaaGateTest(unittest.TestCase):
    def test_taa_off_skips_taa_pass(self):
        self.assertFalse(renderer.taa_pass_enabled({"taa": False}, None))

    def test_taa_on_runs_taa_pass(self):
        self.assertTrue(renderer.taa_pass_enabled({"taa": True}, None))

    def test_temporal_upscaler_takes_over_taa_pass(self):
        self.assertFalse(renderer.taa_pass_enabled({"taa": True}, object()))


if __name__ == "__main__":
    unittest.main()
