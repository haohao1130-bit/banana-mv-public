"""Restore legacy creative freedom without forwarding the upstream finale."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import test_shoot_plan as fixtures
from test_unified_direction import timeline
from banana_mv.shoot_plan import ensure_shoot_plan, write_shoot_prompt, DYNAMIC_EDITING


class ClassicIsolationTests(unittest.TestCase):
    def test_outcome_is_upstream_only_and_local_state_and_identity_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            images,cfg,req=fixtures.ShootPlanTests().fixture(root)
            raw=fixtures.allocation().replace('=== CLIP 0 story ===',
                '=== STORY OUTCOME ===\nPRIVATE_FINALE_RECORD\n=== CLIP 0 story ===')
            plan=ensure_shoot_plan(cfg,req,timeline(),images,root,Mock(return_value=raw))
            self.assertEqual(plan['story_outcome'],'PRIVATE_FINALE_RECORD')
            self.assertNotIn('PRIVATE_FINALE_RECORD',plan['shared_setup'])
            seg=dict(timeline()[1],director_plan=plan['segments'][1],
                fixed_reference_settings=plan['shared_setup'],
                direction_ending_contract=plan['ending_contract'])
            writer=Mock(return_value=fixtures.native_prompt(1))
            write_shoot_prompt(cfg,req,seg,images,None,writer)
            system,parts=writer.call_args.args[1:3]
            text=parts[0][1]
            for hidden in ['PRIVATE_FINALE_RECORD','FINAL_BEAT','HUMAN_OPENING','PRIVATE_FULL_STORY']:
                self.assertNotIn(hidden,text)
            self.assertIn('CURRENT_COUNTER',text)
            self.assertIn('already transformed',text)
            self.assertIn('damaged shield',text)
            self.assertIn('non-singing hero',text)
            self.assertIn('OFFICIAL_NATIVE_GUIDE_MARKER',system)
            self.assertEqual(writer.call_count,1)

    def test_internal_cuts_do_not_trigger_rejection_or_another_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            images,cfg,req=fixtures.ShootPlanTests().fixture(root)
            plan=ensure_shoot_plan(cfg,req,timeline(),images,root,Mock(return_value=fixtures.allocation()))
            seg=dict(timeline()[1],director_plan=plan['segments'][1],direction_ending_contract=plan['ending_contract'])
            prompt=('subject_definitions:\n<Subject 1> is <Picture 2>.\nsummary:\nAn expressive MV.\n'
                'retention_analysis:\n<Audio 1>: fully_copy.\ndetailed_description:\n'
                '[Shot 1] The hero shields the singer. Cut to a close view of the damaged shield; '
                'reverse angle to the singer reacting. '+('Foreground ropes frame the action. '*70)+
                '\noverall_soundscape:\nSource unchanged.\nnon_diegetic_music:\nOriginal song.')
            writer=Mock(return_value=prompt)
            actual=write_shoot_prompt(cfg,req,seg,images,None,writer)
            self.assertIn('Cut to a close view',actual)
            self.assertIn('reverse angle',actual)
            self.assertEqual(writer.call_count,1)
            self.assertIn('may include motivated internal cuts',DYNAMIC_EDITING)

    def test_explicit_legacy_outcome_block_is_not_forwarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            images,cfg,req=fixtures.ShootPlanTests().fixture(root)
            plan=ensure_shoot_plan(cfg,req,timeline(),images,root,Mock(return_value=fixtures.allocation()))
            seg=dict(timeline()[1],director_plan=plan['segments'][1],
                fixed_reference_settings=plan['shared_setup']+'\n=== STORY OUTCOME ===\nLEGACY_FINALE',
                direction_ending_contract=plan['ending_contract'])
            writer=Mock(return_value=fixtures.native_prompt(1))
            write_shoot_prompt(cfg,req,seg,images,None,writer)
            text=writer.call_args.args[2][0][1]
            self.assertNotIn('LEGACY_FINALE',text)
            self.assertIn('non-singing hero',text)
