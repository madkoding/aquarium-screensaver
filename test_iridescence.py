import colorsys
import unittest

from iridescence import add_iridescence, iridescence_rgb

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


if __name__ == "__main__":
    unittest.main()
