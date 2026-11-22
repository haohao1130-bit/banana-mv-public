"""獨立的「共同設定」格：原封不動帶給每一段，劇本只放 ACT；組合可存、載入、刪除。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from banana_mv import presets, services
from banana_mv.python_slots import ensure_python_slot_plan

SHARED = ('@圖片1 = 男主角 = S1，整首歌唯一的演唱者。\n'
          '@圖片2 = 小語，不唱歌、不對嘴。\n'
          'Story spine: 這行在舊版會被當成故事大綱濾掉，但使用者明確放進共同設定就要保留。')
SCRIPT = ('標題：老婆去玩水\n'
          'HEADER_NOT_SHARED 這行是劇本前言，不是共同設定。\n'
          'ACT 01｜00:00.000–00:10.000\n入鏡：小語\n0–5秒：小語扛著泳圈走進樂園。\n'
          'ACT 02｜00:10.000–00:20.000\n入鏡：男主角\n0–5秒：男主角坐進電競椅。\n')


def clips():
    return [{'index': i, 'start': i * 10.0, 'seconds': 10.0, 'song_seconds': 20.0, 'segment_count': 2}
            for i in range(2)]


def request(**extra):
    return {'prompt': SCRIPT, 'director': 'auto', 'story_plan': True, 'project_scope': 'full',
            'ending_policy_version': 2, 'director_schema': 6, 'rewrite_retries': 0,
            'intensity': 'high', 'dynamic_cuts': True, 'mode': 'chain', **extra}


class SharedSetupBoxTests(unittest.TestCase):
    def test_explicit_box_replaces_script_preamble(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = ensure_python_slot_plan(request(shared_setup=SHARED), clips(), [root / 'a.png', root / 'b.png'], root)
            self.assertIn('男主角 = S1', plan['shared_setup'])
            self.assertIn('<Picture 1>', plan['shared_setup'])
            self.assertNotIn('HEADER_NOT_SHARED', plan['shared_setup'])
            self.assertEqual(len(plan['segments']), 2)
            self.assertIn('扛著泳圈', plan['segments'][0]['event'])
            self.assertNotIn('電競椅', plan['segments'][0]['event'])

    def test_without_box_old_behavior_and_fingerprint_are_unchanged(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            old = ensure_python_slot_plan(request(), clips(), [Path(a) / 'x.png'], a)
            again = ensure_python_slot_plan(request(shared_setup=''), clips(), [Path(b) / 'x.png'], b)
            self.assertIn('HEADER_NOT_SHARED', old['shared_setup'])
            self.assertEqual(old['input_sha256'], again['input_sha256'])

    def test_explicit_setup_reaches_9b_without_story_filter(self):
        import test_shoot_plan as fixtures
        from banana_mv.shoot_plan import write_shoot_prompt
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            images, cfg, req = fixtures.ShootPlanTests().fixture(root)
            req.update(prompt=SCRIPT, shared_setup=SHARED, lean_commission=True, director_schema=6, srt_cues=[])
            plan = ensure_python_slot_plan(req, clips(), images, root)
            seg = dict(clips()[0], director_plan=plan['segments'][0], fixed_reference_settings=plan['shared_setup'],
                       direction_ending_contract=plan['ending_contract'])
            writer = Mock(return_value=fixtures.native_prompt(1))
            write_shoot_prompt(cfg, req, seg, images, None, writer)
            text = writer.call_args.args[2][0][1]
            self.assertIn('Story spine: 這行在舊版會被當成故事大綱濾掉', text)
            self.assertNotIn('HEADER_NOT_SHARED', text)

    def test_server_validates_and_drops_blank_box(self):
        from banana_mv import server
        with self.assertRaisesRegex(ValueError, '12000'):
            server.start({'shared_setup': 'x' * 12001})
        with self.assertRaisesRegex(ValueError, '共同設定'):
            server.start({'shared_setup': 123})


class PresetStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        library = root / 'library'
        library.mkdir()
        (library / 'man.png').write_bytes(b'png')
        (library / 'library.json').write_text(json.dumps([{'id': 'man', 'file': 'man.png', 'kind': 'image'}]), encoding='utf-8')
        self.patches = [patch.object(services, 'DATA', root), patch.object(services, 'LIBRARY', library)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def test_save_update_missing_delete(self):
        slots = ['man'] + [None] * 8
        rows = presets.save_preset({'name': '老婆去玩水', 'shared': SHARED, 'slots': slots})
        self.assertEqual((rows[0]['name'], rows[0]['missing']), ('老婆去玩水', []))
        rows = presets.save_preset({'name': '老婆去玩水', 'shared': '改過', 'slots': slots})
        self.assertEqual((len(rows), rows[0]['shared']), (1, '改過'))
        (services.LIBRARY / 'library.json').write_text('[]', encoding='utf-8')
        self.assertEqual(presets.list_presets()[0]['missing'], [1])
        self.assertEqual(presets.delete_preset({'id': rows[0]['id']}), [])
        with self.assertRaisesRegex(ValueError, '9 格'):
            presets.save_preset({'name': 'x', 'shared': 'y', 'slots': [None] * 8})


if __name__ == '__main__':
    unittest.main()
