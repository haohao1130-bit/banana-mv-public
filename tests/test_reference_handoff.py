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

    def test_global_outcome_stays_upstream_but_assigned_finale_reaches_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=fixtures.ShootPlanTests().fixture(root,'chain')
            rows=[{'index':i,'start':i*10,'seconds':10 if i<8 else 9.958333333333334,
                   'segment_count':9,'song_seconds':89.95833333333333} for i in range(9)]
            req['segment_seconds']=10
            events=[f'LOCAL_EVENT_{i}: <Picture 2> advances the fight.' for i in range(7)]+[
                'DECISIVE_COUNTER: <Picture 2> wins; the referee declares the result. End in the neutral corner.',
                'BELT_AWARD: Staff fit the oversized belt; it slips off the winner. The winner steps onto it and raises both fists.']
            raw=('=== SETUP ===\n<Picture 1> is the only singer at the concert. '
                 '<Picture 2> is the boxer in the separate ring.\n'
                 '=== STORY OUTCOME ===\nGLOBAL_FINALE_MARKER: The winner stands on a fallen belt.\n'+
                 ''.join(f'=== CLIP {i} action ===\n{event}\n' for i,event in enumerate(events))+
                 '=== END ===')
            allocator=Mock(return_value=raw)
            plan=ensure_plan(cfg,req,rows,images,root,allocator)
            self.assertEqual(allocator.call_count,1)
            self.assertIn('GLOBAL_FINALE_MARKER',plan['story_outcome'])
            self.assertNotIn('GLOBAL_FINALE_MARKER',plan['shared_setup'])
            self.assertNotIn('fallen belt',plan['shared_setup'])
            before=(root/'director_plan.json').read_bytes()
            for i in (7,8):
                seg=dict(rows[i],director_plan=plan['segments'][i],
                         fixed_reference_settings=plan['shared_setup'],
                         direction_ending_contract=plan['ending_contract'])
                writer=Mock(return_value=fixtures.native_prompt(i,1))
                with patch.object(server.backend,'rewrite_local',writer):
                    server.local_prompt(cfg,req,seg,images,images[0])
                text=writer.call_args.args[2][0][1]
                context=json.loads(text.split('Clip timing and audio context:\n',1)[1])
                self.assertNotIn('GLOBAL_FINALE_MARKER',text)
                self.assertIn('<Picture 2> is the only singer',context['fixed_reference_settings'])
                if i==7:
                    self.assertIn('DECISIVE_COUNTER',text)
                    self.assertNotIn('BELT_AWARD',text)
                    self.assertEqual(context['ending']['phase'],'continuing')
                else:
                    self.assertIn('BELT_AWARD',text)
                    self.assertEqual(context['ending']['phase'],'resolving')
                self.assertEqual(seg['prompt_profile']['writer_calls'],1)
            self.assertEqual((root/'director_plan.json').read_bytes(),before)
            ensure_plan(cfg,req,rows,images,root,allocator)
            self.assertEqual(allocator.call_count,1)

    def test_short_tail_still_receives_ending_assigned_to_previous_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=fixtures.ShootPlanTests().fixture(root,'chain')
            req['segment_seconds']=10
            rows=[{'index':i,'start':a,'seconds':b,'segment_count':4,'song_seconds':31}
                  for i,(a,b) in enumerate(((0,10),(10,10),(20,10),(30,1)))]
            raw=('=== SETUP ===\n<Picture 1> is the singer. <Picture 2> is the boxer.\n'
                 '=== STORY OUTCOME ===\nGLOBAL_END_ONLY\n'
                 '=== CLIP 0 action ===\nThe boxers meet.\n'
                 '=== CLIP 1 action ===\nThe opponent presses forward.\n'
                 '=== CLIP 2 action ===\nDECIDE_AND_AWARD: <Picture 2> wins and stands on the fallen oversized belt.\n'
                 '=== CLIP 3 story ===\nHold the established winner on the belt without repeating the award.\n'
                 '=== END ===')
            plan=ensure_plan(cfg,req,rows,images,root,Mock(return_value=raw))
            seg=dict(rows[2],director_plan=plan['segments'][2],
                     fixed_reference_settings=plan['shared_setup'],
                     direction_ending_contract=plan['ending_contract'])
            writer=Mock(return_value=fixtures.native_prompt(2,1))
            with patch.object(server.backend,'rewrite_local',writer):
                server.local_prompt(cfg,req,seg,images,images[0])
            text=writer.call_args.args[2][0][1]
            self.assertIn('DECIDE_AND_AWARD',text)
            self.assertNotIn('GLOBAL_END_ONLY',text)
            context=json.loads(text.split('Clip timing and audio context:\n',1)[1])
            self.assertEqual(context['ending']['phase'],'resolving')
