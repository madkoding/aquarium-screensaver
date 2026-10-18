import colorsys
import unittest

import iridescence
from iridescence import add_iridescence, flip, iridescence_rgb, metal_weight

BASE = (0.8, 0.4, 0.2)


def hue(rgb):
    return colorsys.rgb_to_hsv(*rgb)[0]


class IridescenceTest(unittest.TestCase):
    def test_colour_changes_with_angle_but_not_with_time(self):
        low = iridescence_rgb(0.2)
        high = iridescence_rgb(0.8)
        self.assertGreater(sum(abs(a - b) for a, b in zip(low, high)), 0.3)     # the film shifts with the angle
        self.assertGreater(abs(hue(add_iridescence(BASE, 0.2)) - hue(BASE)), 0.0)
        self.assertEqual(iridescence_rgb(0.4), iridescence_rgb(0.4))             # nothing drifts: no hologram

    def test_channels_stay_in_valid_range(self):
        for i in range(21):
            ndv = i / 20.0
            for ny in (-1.0, 0.0, 1.0):
                for c in add_iridescence(BASE, ndv, strength=1.0, ny=ny):
                    self.assertGreaterEqual(c, 0.0)
                    self.assertLessEqual(c, 1.0)
                for c in iridescence_rgb(ndv, ny):
                    self.assertGreaterEqual(c, 0.0)
                    self.assertLessEqual(c, 1.0)

    def test_effect_is_additive_only(self):
        for ndv in (0.0, 0.3, 0.7, 1.0):
            out = add_iridescence(BASE, ndv)
            for before, after in zip(BASE, out):
                self.assertGreaterEqual(after, before)

    def test_disabled_keeps_base_colour_exactly(self):
        self.assertEqual(add_iridescence(BASE, 0.2, enabled=False), BASE)
        self.assertEqual(add_iridescence(BASE, 0.2, strength=0.0), BASE)

    def test_sheen_is_visible_face_on(self):
        face_on = add_iridescence(BASE, 1.0)
        self.assertTrue(any(after - before > 0.01 for before, after in zip(BASE, face_on)))

    def test_stays_in_the_cool_to_pink_range_never_a_rainbow(self):
        for i in range(41):
            r, g, b = iridescence_rgb(i / 40.0, ny=(i % 5 - 2) / 2.0)
            self.assertGreaterEqual(b, 0.9)            # always blue-ish: no yellows, greens or reds
            self.assertGreaterEqual(r, min(c[0] for c in (iridescence.COOL, iridescence.WARM)) - 1e-9)
            self.assertLessEqual(r, max(c[0] for c in (iridescence.COOL, iridescence.WARM)) + 1e-9)

    def test_glow_is_faint_and_independent_of_the_base_colour(self):
        out = add_iridescence((0.0, 0.0, 0.0), 0.3)
        self.assertGreater(max(out), 0.02)             # a black fish still glows a little
        self.assertLess(max(out), 0.2)                 # but it is not neon

    def test_metallic_bands_have_bright_and_dim_zones(self):
        weights = [metal_weight(i / 200.0) for i in range(201)]
        self.assertGreater(max(weights) / min(weights), 2.0)
        self.assertTrue(all(0.0 <= flip(i / 20.0) <= 1.0 for i in range(21)))

    def test_shader_gets_its_constants_from_the_module(self):
        for name in ("STRENGTH", "FLUOR", "METAL_PEAK", "FLIP_RATE", "MIRROR"):
            line = "const float IRID_%s = %.3f;" % (name, getattr(iridescence, name))
            self.assertIn(line, iridescence.GLSL_CONSTS)
        self.assertIn("const vec3 IRID_COOL = vec3(0.300, 0.850, 1.000);", iridescence.GLSL_CONSTS)
        with open("shaders.py", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("FISH_FUNCS + IRID_GLSL", source)
        self.assertIn("IRID_STRENGTH", source)


if __name__ == "__main__":
    unittest.main()
