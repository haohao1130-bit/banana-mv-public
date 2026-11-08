import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from banana_mv import server
from banana_mv.story_plan import ensure_plan
from banana_mv.story_completion import source_fragments,parse_requirements
from banana_mv.core import normalize_mv_prompt,MediaReferenceError
import test_shoot_plan as fixtures
from test_unified_direction import timeline
import test_story_completion as completion


class OriginalCastTests(unittest.TestCase):
    def test_original_musicians_are_designed_upstream_and_reach_native_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=fixtures.ShootPlanTests().fixture(root)
            req['prompt']='@圖片1 is the sole singer. @圖片2 is the boxer. Create distinct adult lead guitarist, rhythm guitarist, bassist and drummer without additional reference images.'
            designs=('Original supporting cast: Lead guitarist Lumen, adult, silver short hair, red jacket, violet guitar, stage left. '
                     'Rhythm guitarist Vale, adult, dark braid, black vest, white guitar, stage right. '
                     'Bassist Reed, adult, shaved head, blue coat, black bass, center rear. '
                     'Drummer Dawn, adult, curly hair, teal shirt, gold drum kit, rear center. None sing.')
            raw=fixtures.allocation().replace('=== CLIP 0 story ===',designs+'\n=== CLIP 0 story ===')
            allocator=Mock(return_value=raw)
            plan=ensure_plan(cfg,req,timeline(),images,root,allocator)
            system=allocator.call_args.args[1]
            self.assertIn('CREATE their fixed designs',system)
            self.assertIn('not a\nclosed cast list',system)
            seg=dict(timeline()[1],director_plan=plan['segments'][1],fixed_reference_settings=plan['shared_setup'])
            native=('<Subject 7> is Lumen, an original adult lead guitarist with silver short hair, red jacket and violet guitar. '
                    '<Picture 1> remains the singer. Lumen performs a fretboard close-up.')
            writer=Mock(return_value=native)
            with patch.object(server.backend,'rewrite_local',writer):out=server.local_prompt(cfg,req,seg,images,None)
            sent=writer.call_args.args[2][0][1]
            for name in ('Lumen','Vale','Reed','Dawn','violet guitar','rear center'):
                self.assertIn(name,sent)
            self.assertIn('without a\nreference image',sent)
            self.assertIn('<Subject 7>',out)
            self.assertNotIn('<Picture 7>',out)
            with self.assertRaises(MediaReferenceError):normalize_mv_prompt('<Picture 7> is Lumen.',2)

    def test_chinese_source_layout_and_ordered_excerpts_are_not_story_errors(self):
        original='影片從拳擊場開始，歌曲同步播放。\n\n高大的拳王站在擂台一側。\n\n猴哥確認準備完成。'
        joined='影片從拳擊場開始，歌曲同步播放。高大的拳王站在擂台一側。猴哥確認準備完成。'
        self.assertTrue(source_fragments(joined,original))
        self.assertTrue(source_fragments('影片從拳擊場開始，歌曲同步播放。猴哥確認準備完成。',original))
        self.assertTrue(source_fragments('影片從拳擊場開始，歌曲同步播放。...猴哥確認準備完成。',original))
        self.assertIsNone(source_fragments('猴哥確認準備完成。影片從拳擊場開始，歌曲同步播放。',original))
        self.assertIsNone(source_fragments('影片從拳擊場開始，歌曲同步播放。小語擊倒拳王。',original))
        # Full requirement delivery preserves mandatory phase checks after layout tolerance.
        source=completion.BRIEF.replace('。','。\n\n')
        self.assertEqual(len(parse_requirements(completion.REQUIRED,source)),4)
