import unittest

import settings


class IridescenceSettingTest(unittest.TestCase):
    def test_default_is_enabled(self):
        self.assertIn("iridescence", settings.DEFAULTS)
        self.assertIs(settings.DEFAULTS["iridescence"], True)

    def test_load_accepts_bool_only(self):
        cfg = dict(settings.DEFAULTS)
        cfg["iridescence"] = False
        self.assertIs(cfg["iridescence"], False)


if __name__ == "__main__":
    unittest.main()
