"""精簡通告單：9B 只拿這段需要的事實；END_STATE 交接動作方向；通用換裝點；重寫有上限。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_shoot_plan as fixtures
from test_unified_direction import timeline
from banana_mv import services, shoot_plan
from banana_mv.continuity import handoff_note, split_end_state, wardrobe_note
from banana_mv.scene_state import SceneStateError
from banana_mv.shoot_plan import ensure_shoot_plan, write_shoot_prompt

END = ('\nEND_STATE:\npose: <Subject 1> stands screen-left holding the shield\n'
       'motion: spinning clockwise as seen from the camera, fast, mid-turn\n'
       'camera: orbiting left to right\nmood: defiant')


def draft(i=1):
    return fixtures.native_prompt(i) + END


class ContinuityTests(unittest.TestCase):
    def test_end_state_is_cut_off_before_h3(self):
        body, state = split_end_state(draft())
        self.assertNotIn('END_STATE', body)
        self.assertIn('Detailed native camera prose.', body)
        self.assertIn('clockwise', state)
        self.assertEqual(split_end_state('no state here'), ('no state here', None))

    def test_handoff_locks_direction_unless_cut(self):
        note = handoff_note('motion: spinning clockwise')
        self.assertIn('CONTINUITY LOCK', note)
        self.assertIn('SAME', note)
        self.assertNotIn('CONTINUITY LOCK', handoff_note('motion: x', cut=True))
        self.assertEqual(handoff_note(None), '')

    def test_generic_wardrobe_change_points(self):
        script = '【換裝 0:20】S2 → 純白綁帶比基尼\n【換裝 01:05】S2 → 原本的白色洋裝（濕的）\n【換裝 30】S1 → 夏威夷衫'
        before = wardrobe_note(script, 25, 10)
        self.assertIn('S2: 純白綁帶比基尼', before)
        self.assertIn('OUTFIT CHANGE INSIDE THIS CLIP at 5.00s: S1 → 夏威夷衫', before)
        after = wardrobe_note(script, 70, 10)
        self.assertIn('S2: 原本的白色洋裝（濕的）', after)
        self.assertIn('S1: 夏威夷衫', after)
        self.assertEqual(wardrobe_note('沒有換裝', 0, 10), '')


class LeanWriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.images, self.cfg, self.req = fixtures.ShootPlanTests().fixture(root)
        self.req['lean_commission'] = True
        plan = ensure_shoot_plan(self.cfg, self.req, timeline(), self.images, root, Mock(return_value=fixtures.allocation()))
        self.seg = dict(timeline()[1], director_plan=plan['segments'][1], fixed_reference_settings=plan['shared_setup'],
                        direction_ending_contract=plan['ending_contract'])

    def tearDown(self):
        self.tmp.cleanup()

    def test_commission_is_short_and_returns_end_state(self):
        writer = Mock(return_value=draft())
        prompt = write_shoot_prompt(self.cfg, self.req, self.seg, self.images, None, writer)
        text = writer.call_args.args[2][0][1]
        self.assertLess(len(text.split()), 450)
        self.assertIn('THIS CLIP', text)
        self.assertIn('CURRENT_COUNTER', text)
        self.assertIn('END_STATE:', text)
        self.assertIn('resolve_start_by=4s', text)
        for hidden in ('PRIVATE_FULL_STORY', 'FUTURE_STORY_MARKER', 'Never turn the singer'):
            self.assertNotIn(hidden, text)
        self.assertNotIn('END_STATE', prompt)
        self.assertIn('clockwise', self.seg['end_state'])
        self.assertEqual(writer.call_count, 1)

    def test_previous_end_state_reaches_next_clip(self):
        self.seg['previous_end_state'] = 'motion: spinning clockwise as seen from the camera'
        writer = Mock(return_value=draft())
        write_shoot_prompt(self.cfg, self.req, self.seg, self.images, Path(self.images[0]), writer)
        text = writer.call_args.args[2][0][1]
        self.assertIn('spinning clockwise', text)
        self.assertIn('CONTINUITY LOCK', text)
        self.assertIn("<Picture 1> is the previous clip's last frame", text)

    def test_guard_conflicts_stop_after_two_repairs_and_keep_draft(self):
        writer = Mock(return_value=draft())
        with patch.object(shoot_plan, 'check_commission', return_value=['[ERROR] stubborn']):
            prompt = write_shoot_prompt(self.cfg, self.req, self.seg, self.images, None, writer)
        self.assertEqual(writer.call_count, 3)
        self.assertIn('ONLY_BEAT', prompt)
        self.assertEqual(self.seg['commission_guard_warnings'], ['[ERROR] stubborn'])

    def test_bad_drafts_are_capped_and_retries_skip_thinking(self):
        cfg = dict(self.cfg, rewriter={'thinking': True, 'max_length': 16384})
        writer = Mock(return_value='')
        with self.assertRaises(SceneStateError):
            write_shoot_prompt(cfg, self.req, self.seg, self.images, None, writer)
        self.assertEqual(writer.call_count, 2)
        self.assertTrue(writer.call_args_list[0].args[0]['rewriter']['thinking'])
        self.assertFalse(writer.call_args_list[1].args[0]['rewriter']['thinking'])


class ThinkingSettingsTests(unittest.TestCase):
    def test_no_word_cap_and_qwen_thinking_sampling(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = services.load_config()
            cfg['comfy_input_dir'] = tmp
            cfg['rewriter'] = dict(cfg['rewriter'], thinking=True, max_length=16384)
            graph, _ = services.build_rewrite_graph(cfg, 'GUIDE', [('text', 'clip')], 'job')
            inputs = graph['generate']['inputs']
            self.assertNotIn('150 words', inputs['prompt'])
            self.assertEqual((inputs['sampling_mode.temperature'], inputs['sampling_mode.top_p']), (0.6, 0.95))
            cfg['rewriter'] = dict(cfg['rewriter'], thinking=False)
            inputs = services.build_rewrite_graph(cfg, 'GUIDE', [('text', 'clip')], 'job')[0]['generate']['inputs']
            self.assertEqual((inputs['sampling_mode.temperature'], inputs['sampling_mode.top_p']), (0.7, 0.8))


if __name__ == '__main__':
    unittest.main()
