"""Routing and isolation regression tests for 35B's advisory library."""
import unittest

from banana_mv.director import MODES
from banana_mv.director_library import VERSION, MODE_LIBRARY, build_library, creative_prompt


class DirectorLibraryTests(unittest.TestCase):
    def test_all_specialties(self):
        self.assertEqual(set(MODES), set(MODE_LIBRARY))
        for mode in MODES:
            segment = {'index': 0, 'seconds': 10, 'director_plan': {'mode': mode, 'event': 'Current event'}}
            text, info = build_library({'director': 'auto'}, segment)
            self.assertEqual(info['mode'], mode)
            self.assertIn('selected specialty: ' + mode, text)
            self.assertIn('optional creative ingredients', text)
            self.assertLess(info['words'], 1000)

    def test_explicit_dance_without_adapters(self):
        segment = {'index': 0, 'seconds': 15, 'director_plan': {'mode': 'performance', 'event': 'Waacking dance duel'}}
        text, info = build_library({'director': 'dance'}, segment)
        self.assertEqual(info['mode'], 'dance')
        self.assertIn('Waacking', text)
        self.assertNotIn('ACTIVE DOWNSTREAM ADAPTERS', text)
        self.assertNotIn('Guitar phrase', text)

    def test_adapters_are_independent_and_zero_weight_is_off(self):
        req = {'director': 'dance', 'action_loras': {
            'dance': {'enabled': True, 'strength': .7},
            'beat_sync': {'enabled': True, 'strength': 1.0},
            'choreography': {'enabled': True, 'strength': 0},
        }}
        text, info = build_library(req, {'seconds': 15})
        self.assertEqual(info['active_loras'], ['dance', 'beat_sync'])
        self.assertIn('Beat-sync adapter is mounted', text)
        self.assertNotIn('Choreography adapter is mounted', text)
        self.assertIn('No new trigger words', text)

    def test_local_scope_and_rotation(self):
        req = {'director': 'auto', 'prompt': 'FUTURE_ONLY_SECRET'}
        seg = {'index': 0, 'director_plan': {'mode': 'dance', 'event': 'duet'}, 'seconds': 10}
        first, _ = build_library(req, seg)
        second, _ = build_library(req, dict(seg, index=1))
        self.assertNotEqual(first, second)
        self.assertNotIn('FUTURE_ONLY_SECRET', first)

    def test_natural_short_take_and_metadata(self):
        seg = {'index': 1, 'seconds': 3, 'director_plan': {'mode': 'story', 'event': 'quiet reaction'}}
        system = creative_prompt('OFFICIAL', {'intensity': 'normal', 'dynamic_cuts': False}, seg)
        self.assertTrue(system.startswith('OFFICIAL'))
        self.assertIn('Natural intensity', system)
        self.assertIn('Short interval', system)
        self.assertIn('disabled dynamic editing', system)
        self.assertEqual(seg['director_library']['version'], VERSION)


if __name__ == '__main__':
    unittest.main()
