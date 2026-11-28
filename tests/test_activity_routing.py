"""Offline tests only; these fixtures never enter the director prompt."""
import unittest

from banana_mv.activity_router import route_activity
from banana_mv.director_library import build_library, select_mode


class ActivityRoutingTests(unittest.TestCase):
    def test_actual_activity_takes_precedence_over_accompanying_vocals(self):
        for event, expected in (
            ('三人群舞並合唱', 'dance'),
            ('五人跳舞 battle', 'dance'),
            ('拳擊選手揮拳格擋，舞台主唱演唱', 'action'),
            ('吉他手演奏，主唱演唱', 'band'),
            ('主唱演唱，不跳舞', 'performance'),
            ('追逐逃跑', 'chase'),
            ('施法變身', 'fantasy'),
            ('詭異反射，驚悚懸疑', 'horror'),
            ('一本正經胡說八道', 'comedy'),
            ('舞台空景', 'story'),
        ):
            with self.subTest(event=event):
                self.assertEqual(route_activity(event), expected)

    def test_current_event_and_manual_override(self):
        event = ('ALREADY ESTABLISHED: dancing\n'
                 'Current interval actions in original order:\n- She sings.')
        self.assertEqual(route_activity(event), 'performance')
        self.assertEqual(route_activity('舞蹈表演', 'performance'), 'performance')

    def test_saved_auto_plan_and_music_are_independent(self):
        seg = {'seconds': 15, 'director_plan': {
            'mode': 'performance', 'event': '三人群舞並合唱'},
            'audio_evidence': {'music_structure': {'bpm': 130}}}
        req = {'director': 'auto'}
        self.assertEqual(select_mode(req, seg), 'dance')
        self.assertEqual(seg['director_plan']['mode'], 'performance')
        for mode in ('dance', 'performance', 'story', 'action', 'band',
                     'chase', 'fantasy', 'horror', 'comedy'):
            text, info = build_library({'director': mode}, seg)
            self.assertEqual(info['mode'], mode)
            self.assertEqual(text.count('CURRENT CLIP MUSIC EVIDENCE'), 1)
            self.assertIn('Predicted BPM: 130', text)
        text, info = build_library({'director': 'dance', 'audio_analysis': False}, seg)
        self.assertFalse(info['music_evidence'])
        self.assertNotIn('CURRENT CLIP MUSIC EVIDENCE', text)


if __name__ == '__main__':
    unittest.main()
