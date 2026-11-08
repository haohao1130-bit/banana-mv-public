"""Regression: new MV photographic burst must not increase motion LoRA strength."""
import unittest
from unittest.mock import patch

from banana_mv import server


class MVMotionIntensityTests(unittest.TestCase):
    def _options(self, intensity, version=None):
        req = {'intensity': intensity, 'motion_lora': True}
        if version is not None:
            req['mv_motion_version'] = version
        with patch.object(server, 'director_prompt', return_value=('', 'action')):
            return server.graph_options(req, 10)

    def test_new_cinematic_burst_uses_high_motion_lora_level(self):
        options = self._options('extreme', 2)
        self.assertEqual(options['intensity'], 'high')
        self.assertTrue(options['motion_lora'])
        self.assertEqual(options['director_mode'], 'action')

    def test_high_and_natural_levels_remain_unchanged(self):
        self.assertEqual(self._options('high', 2)['intensity'], 'high')
        self.assertEqual(self._options('normal', 2)['intensity'], 'normal')

    def test_old_projects_keep_original_extreme_multiplier(self):
        self.assertEqual(self._options('extreme')['intensity'], 'extreme')
        self.assertEqual(self._options('extreme', 1)['intensity'], 'extreme')

    def test_invalid_level_rejected(self):
        with self.assertRaisesRegex(ValueError, '未知攝影強度'):
            self._options('warp', 2)


if __name__ == '__main__':
    unittest.main()
