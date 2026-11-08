import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from banana_mv import server
from banana_mv.story_plan import ensure_plan
from banana_mv.mv_scope import ending_contract,clip_ending
import test_shoot_plan as fixtures
from test_unified_direction import timeline


class ReferenceHandoffTests(unittest.TestCase):
    def test_fixed_identity_reaches_writer_without_future_story(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=fixtures.ShootPlanTests().fixture(root,'chain')
            plan=ensure_plan(cfg,req,timeline(),images,root,Mock(return_value=fixtures.allocation()))
            seg=dict(timeline()[1],director_plan=plan['segments'][1],
                     fixed_reference_settings=plan['shared_setup'],direction_ending_contract=plan['ending_contract'])
            writer=Mock(return_value=fixtures.native_prompt(1,1))
            with patch.object(server.backend,'rewrite_local',writer):
                server.local_prompt(cfg,req,seg,images,images[0])
            text=writer.call_args.args[2][0][1]
            context=json.loads(text.split('Clip timing and audio context:\n',1)[1])
            fixed=context['fixed_reference_settings']
            self.assertIn('<Picture 2> is the human singer',fixed)
            self.assertIn('<Picture 3> is the non-singing hero',fixed)
            self.assertIn('industrial',fixed)
            for future in ('PRIVATE_FULL_STORY','FUTURE_STORY_MARKER','FINAL_BEAT','HUMAN_OPENING'):
                self.assertNotIn(future,text)
            system=writer.call_args.args[1]
            self.assertNotIn('adding relevant visual and sound details',system)
            self.assertIn('not N/A',text)
            self.assertIn('microphone grip and free-hand',text)

    def test_tiny_tail_receives_result_and_previous_full_clip_gets_resolution(self):
        rows=[{'index':i,'start':a,'seconds':b,'segment_count':4,'song_seconds':31}
              for i,(a,b) in enumerate(((0,10),(10,10),(20,10),(30,1)))]
        req={'project_scope':'full'};contract=ending_contract(req,31,rows)
        self.assertEqual(contract['resolve_start_by'],20)
        local=[clip_ending(req,dict(s,direction_ending_contract=contract)) for s in rows]
        self.assertEqual(local[0]['phase'],'continuing')
        self.assertEqual(local[1]['phase'],'continuing')
        self.assertEqual(local[2]['phase'],'resolving')
        self.assertEqual(local[3]['phase'],'terminal_hold')
        self.assertFalse(local[0]['finish_work']);self.assertTrue(local[2]['finish_work'])
