import colorsys
import unittest

import iridescence
from iridescence import add_iridescence, flip, iridescence_rgb, metal_weight

BASE = (0.8, 0.4, 0.2)


def hue(rgb):
    return colorsys.rgb_to_hsv(*rgb)[0]


class IridescenceTest(unittest.TestCase):
    def test_hue_changes_with_angle_and_time(self):
        at_low_angle = add_iridescence(BASE, 0.2, 0.0)
        at_high_angle = add_iridescence(BASE, 0.6, 0.0)
        later = add_iridescence(BASE, 0.2, 10.0)
        self.assertGreater(abs(hue(at_low_angle) - hue(at_high_angle)), 0.005)
        self.assertGreater(abs(hue(at_low_angle) - hue(later)), 0.005)

    def test_channels_stay_in_valid_range(self):
        for i in range(21):
            ndv = i / 20.0
            for t in (0.0, 1.5, 7.3, 120.0):
                for c in add_iridescence(BASE, ndv, t, strength=1.0):
                    self.assertGreaterEqual(c, 0.0)
                    self.assertLessEqual(c, 1.0)
                for c in iridescence_rgb(ndv, t):
                    self.assertGreaterEqual(c, 0.0)
                    self.assertLessEqual(c, 1.0)

    def test_effect_is_additive_only(self):
        for ndv in (0.0, 0.3, 0.7, 1.0):
            out = add_iridescence(BASE, ndv, 4.2)
            for before, after in zip(BASE, out):
                self.assertGreaterEqual(after, before)

    def test_disabled_keeps_base_colour_exactly(self):
        self.assertEqual(add_iridescence(BASE, 0.2, 3.0, enabled=False), BASE)
        self.assertEqual(add_iridescence(BASE, 0.2, 3.0, strength=0.0), BASE)

    def test_sheen_is_visible_face_on(self):
        face_on = add_iridescence(BASE, 1.0, 2.0)
        self.assertTrue(any(after - before > 0.01 for before, after in zip(BASE, face_on)))

    def test_hue_is_fully_saturated(self):
        for i in range(21):
            rgb = iridescence_rgb(i / 20.0, 3.0)
            self.assertAlmostEqual(max(rgb), 1.0, places=3)
            self.assertLess(min(rgb), 0.9)          # never washed out to white

    def test_glow_does_not_depend_on_the_base_colour(self):
        out = add_iridescence((0.0, 0.0, 0.0), 0.3, 2.0)
        self.assertGreater(max(out), 0.05)          # a black fish still glows: it is fluorescent

    def test_metallic_flip_flop_has_bright_bands_and_dark_gaps(self):
        weights = [metal_weight(i / 200.0, 0.0) for i in range(201)]
        self.assertGreater(max(weights) / min(weights), 4.0)
        self.assertTrue(all(0.0 <= flip(i / 20.0, 1.0) <= 1.0 for i in range(21)))

    def test_shader_gets_its_constants_from_the_module(self):
        for name in ("STRENGTH", "FLUOR", "SATURATION_POWER", "METAL_PEAK", "FLIP_RATE"):
            line = "const float IRID_%s = %.3f;" % (name if name != "SATURATION_POWER" else "SAT_POWER", getattr(iridescence, name))
            self.assertIn(line, iridescence.GLSL_CONSTS)
        with open("shaders.py", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("FISH_FUNCS + IRID_GLSL", source)
        self.assertIn("IRID_STRENGTH", source)


if __name__ == "__main__":
    unittest.main()
