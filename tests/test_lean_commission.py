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
        self.assertIn('PYTHON FILLS IN LATER', text)
        self.assertIn('need no <Subject> entry', text)
        self.assertIn('never tag a silent actor', text)
        for hidden in ('PRIVATE_FULL_STORY', 'FUTURE_STORY_MARKER', 'Never turn the singer'):
            self.assertNotIn(hidden, text)
        self.assertNotIn('END_STATE', prompt)
        self.assertIn('clockwise', self.seg['end_state'])
        self.assertEqual(writer.call_count, 1)

    def test_role_codes_are_hidden_from_9b(self):
        self.seg['fixed_reference_settings'] = ('<Picture 1> = 男主角 = S1，唯一演唱者。\n<Picture 2> = 小語，不唱歌。\n'
                                                  '只有 S1 男主角依 SRT 自然對嘴。\nS1 = <Picture 1>')
        writer = Mock(return_value=draft())
        write_shoot_prompt(self.cfg, self.req, self.seg, self.images, None, writer)
        text = writer.call_args.args[2][0][1]
        self.assertIn('<Picture 1> = 男主角，唯一演唱者。', text)
        self.assertNotIn('= S1', text)
        self.assertIn('只有 男主角依 SRT', text)
        self.assertIn('S1 = <Picture 1>', text)  # 純對應表給 Python 用，不動

    def test_previous_end_state_reaches_next_clip(self):
        self.seg['previous_end_state'] = 'motion: spinning clockwise as seen from the camera'
        writer = Mock(return_value=draft())
        write_shoot_prompt(self.cfg, self.req, self.seg, self.images, Path(self.images[0]), writer)
        text = writer.call_args.args[2][0][1]
        self.assertIn('spinning clockwise', text)
        self.assertIn('CONTINUITY LOCK', text)
        self.assertIn("<Picture 1> is the previous clip's last frame", text)

    def test_bad_drafts_are_capped_and_retries_skip_thinking(self):
        cfg = dict(self.cfg, rewriter={'thinking': True, 'max_length': 16384})
        writer = Mock(return_value='')
        with self.assertRaises(SceneStateError):
            write_shoot_prompt(cfg, self.req, self.seg, self.images, None, writer)
        self.assertEqual(writer.call_count, 2)
        self.assertTrue(writer.call_args_list[0].args[0]['rewriter']['thinking'])
        self.assertFalse(writer.call_args_list[1].args[0]['rewriter']['thinking'])


class MotionFramesTests(LeanWriterTests):
    def frames(self):
        from PIL import Image
        paths = []
        for n in range(4):
            path = Path(self.tmp.name) / f'last5_{n + 2:02d}.png'
            Image.new('RGB', (64, 36), (n * 60, 0, 0)).save(path)
            paths.append(str(path))
        return paths

    def test_chain5_sends_all_five_frames_without_renumbering_references(self):
        self.req['mode'] = 'chain5'
        self.seg['motion_frames'] = self.frames()
        writer = Mock(return_value=draft())
        write_shoot_prompt(self.cfg, self.req, self.seg, self.images, Path(self.images[0]), writer)
        parts = writer.call_args.args[2]
        labels = [value for kind, value in parts if kind == 'text']
        images = [value for kind, value in parts if kind == 'image']
        self.assertEqual(len(images), 1 + len(self.images) + 4)          # F-4、參考圖、F-3…F-0
        self.assertEqual([l for l in labels if l.startswith('<Picture')], ['<Picture 1>:', '<Picture 2>:', '<Picture 3>:'])
        self.assertEqual([l for l in labels if l.startswith('Motion frame')],
                         ['Motion frame F-3:', 'Motion frame F-2:', 'Motion frame F-1:', 'Motion frame F-0 (final frame):'])
        self.assertTrue(any('MOTION FRAMES' in l for l in labels))
        self.assertIn('frame F-4', parts[0][1])
        self.assertEqual(self.seg['motion_frames_to_9b'], 4)

    def test_single_frame_modes_send_no_motion_frames(self):
        self.req['mode'] = 'chain'
        self.seg['motion_frames'] = self.frames()
        writer = Mock(return_value=draft())
        write_shoot_prompt(self.cfg, self.req, self.seg, self.images, Path(self.images[0]), writer)
        images = [value for kind, value in writer.call_args.args[2] if kind == 'image']
        self.assertEqual(len(images), 1 + len(self.images))
        self.assertEqual(self.seg['motion_frames_to_9b'], 0)


class OnScreenCastTests(unittest.TestCase):
    FIXED = '<Picture 2> = 男主角 = S1。\n<Picture 3> = 小語。\n<Picture 4> = 蕉彌，外型依參考圖。'

    def test_absent_reference_is_named_and_mentions_count_as_present(self):
        from banana_mv.continuity import cast_note
        note = cast_note('入鏡：小語、男主角\n小語漂流。', self.FIXED)
        self.assertIn('ON-SCREEN IN THIS CLIP: 小語、男主角', note)
        self.assertIn('NOT IN THIS CLIP: 蕉彌 (<Picture 4>)', note)
        self.assertNotIn('NOT IN THIS CLIP', cast_note('入鏡：男主角、小語\n桌上的蕉彌公仔在前景。', self.FIXED))
        self.assertEqual(cast_note('沒有入鏡行', self.FIXED), '')

    def test_python_sliced_format_and_previous_handoff(self):
        from banana_mv.continuity import cast_note, onscreen_cast
        event = ('ALREADY ESTABLISHED; do not restage or repeat: 【交棒】蕉彌公仔還在桌上。\n'
                 'Current interval actions in original order:\n- 入鏡：小語、男主角\n- 小語漂流。')
        self.assertEqual(onscreen_cast(event), ['小語', '男主角'])
        self.assertIn('NOT IN THIS CLIP: 蕉彌 (<Picture 4>)', cast_note(event, self.FIXED))
        self.assertEqual(onscreen_cast('【入鏡】小語'), ['小語'])

    def test_real_four_legs_prompt_is_caught(self):
        from banana_mv.continuity import cast_errors
        bad = (Path(__file__).parent / 'fixtures' / 'four_legs_act02_prompt.txt').read_text(encoding='utf-8')
        errors = cast_errors(bad, '入鏡：小語、男主角', self.FIXED, tail=True)
        self.assertEqual(len(errors), 2)
        self.assertIn('<Picture 1> is the previous clip', errors[0])
        self.assertIn('蕉彌 (<Picture 4>) is not on screen', errors[1])
        good = bad.replace('<Subject 1> is the young man in <Picture 1>', '<Subject 1> is the young man in <Picture 2>')
        good = good.split('<Subject 2> is the small', 1)[0] + good.split('never at life size.\n', 1)[1]
        self.assertEqual(cast_errors(good, '入鏡：小語、男主角', self.FIXED, tail=True), [])

    def test_lean_writer_repairs_cast_errors(self):
        import test_shoot_plan as fixtures
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images, cfg, req = fixtures.ShootPlanTests().fixture(root)
            req['lean_commission'] = True
            plan = ensure_shoot_plan(cfg, req, timeline(), images, root, Mock(return_value=fixtures.allocation()))
            row = dict(plan['segments'][1], event='入鏡：歌手\n' + plan['segments'][1]['event'])
            seg = dict(timeline()[1], director_plan=row, direction_ending_contract=plan['ending_contract'],
                       fixed_reference_settings='<Picture 1> = 歌手。\n<Picture 2> = 英雄。')
            bad = ('subject_definitions:\n<Subject 1> is the hero in <Picture 2>.\nsummary:\nx\n'
                   + fixtures.native_prompt(1))
            writer = Mock(side_effect=[bad, fixtures.native_prompt(1)])
            write_shoot_prompt(cfg, req, seg, images, None, writer)
            text = writer.call_args_list[0].args[2][0][1]
            self.assertIn('NOT IN THIS CLIP: 英雄 (<Picture 2>)', text)
            parts = writer.call_args_list[0].args[2]
            labels = [value for kind, value in parts if kind == 'text']
            self.assertIn('<Picture 2>: not in this clip (image withheld; do not use it).', labels)
            self.assertEqual(sum(kind == 'image' for kind, _ in parts), 1)      # 只給歌手的圖
            self.assertEqual(seg['withheld_pictures'], [2])
            self.assertEqual(writer.call_count, 2)
            self.assertIn('英雄 (<Picture 2>) is not on screen', writer.call_args_list[1].args[2][-1][1])


class ThinkingSettingsTests(unittest.TestCase):
    def test_no_word_cap_and_qwen_thinking_sampling(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = services.load_config()
            cfg['comfy_input_dir'] = tmp
            cfg['rewriter'] = dict(cfg['rewriter'], thinking=True, max_length=16384)
            graph, _ = services.build_rewrite_graph(cfg, 'GUIDE', [('text', 'clip')], 'job')
            inputs = graph['generate']['inputs']
            self.assertNotIn('150 words', inputs['prompt'])
            self.assertEqual((inputs['sampling_mode.temperature'], inputs['sampling_mode.top_p'],
                              inputs['sampling_mode.presence_penalty']), (1.0, 0.95, 1.5))
            self.assertIn('never reopen a settled decision', inputs['prompt'])
            cfg['rewriter'] = dict(cfg['rewriter'], thinking=False)
            inputs = services.build_rewrite_graph(cfg, 'GUIDE', [('text', 'clip')], 'job')[0]['generate']['inputs']
            self.assertEqual((inputs['sampling_mode.temperature'], inputs['sampling_mode.top_p'],
                              inputs['sampling_mode.presence_penalty']), (0.7, 0.8, 0.0))
            cfg['rewriter'] = dict(cfg['rewriter'], thinking=True, presence_penalty=0.5)
            inputs = services.build_rewrite_graph(cfg, 'GUIDE', [('text', 'clip')], 'job')[0]['generate']['inputs']
            self.assertEqual(inputs['sampling_mode.presence_penalty'], 0.5)      # config.json 自訂值優先


if __name__ == '__main__':
    unittest.main()
