"""Deterministic scope/binding guards and one-call writer regressions; no GPU."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from banana_mv.direction_contract import scoped_constraints, validate_subject_bindings, validate_h3_sections
from banana_mv.prompt_quality import write_directed_clip, CLIP_WRITER_SYSTEM
from banana_mv.scene_state import SceneStateError
from banana_mv.story_plan import validate_unified_plan, ensure_plan, UNIFIED_SYSTEM
from test_unified_direction import treatment, timeline, request, h3


class DirectionContractTests(unittest.TestCase):
    def fixture(self,root,chain=False):
        photo=root/'ref.png';Image.new('RGB',(8,8)).save(photo)
        plan=validate_unified_plan(treatment(),timeline(),1)
        seg=dict(timeline()[0],director_plan=plan['segments'][0],direction_constraints=plan['constraints']+
                 ['The final image shows a terminal marker.'],direction_closing_shot=plan['closing_shot'])
        return photo,seg

    def test_terminal_clause_hidden_but_role_and_location_survive(self):
        lines=['S1 sings. The worlds stay separate. The final image shows S2 holding a medal.']
        self.assertEqual(scoped_constraints(lines,False),['S1 sings.','The worlds stay separate.'])
        self.assertIn('medal',' '.join(scoped_constraints(lines,True)))
        self.assertEqual(scoped_constraints(['最後畫面回到劇院。角色保持同一身份。'],False),['角色保持同一身份。'])

    def test_explicit_terminal_event_rejected_early_but_climax_allowed(self):
        raw=treatment();raw['events'][0]['reserved_final']=True
        with self.assertRaisesRegex(SceneStateError,'非最終段'):
            validate_unified_plan(raw,timeline(),1)
        raw['events'][0]['reserved_final']=False
        validate_unified_plan(raw,timeline(),1)
        raw['events'][0]['reserved_final']='false'
        with self.assertRaises(SceneStateError):validate_unified_plan(raw,timeline(),1)

    def test_explicit_binding_swap_is_repaired_without_a_reviewer(self):
        for chain in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                photo,seg=self.fixture(Path(tmp))
                wrong=3 if chain else 2;correct=2 if chain else 1
                bad=h3('A performance.',f'<Subject 1> from <Picture {wrong}>.')
                good=bad.replace(f'Picture {wrong}',f'Picture {correct}')
                model=Mock(side_effect=[bad,good])
                with patch('banana_mv.services.rewrite_local',model):
                    result=write_directed_clip({},request(),seg,[photo,photo],photo if chain else None)
                self.assertEqual(model.call_count,2)
                self.assertIn(good,result)
                self.assertIn('必須綁定',model.call_args.args[2][-1][1])
                self.assertEqual(seg['prompt_profile']['contract_check_calls'],0)
                self.assertEqual(seg['prompt_validation']['kind'],'technical_only')

    def test_empty_repeated_output_does_not_publish_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo,seg=self.fixture(Path(tmp));model=Mock(return_value=' ')
            with patch('banana_mv.services.rewrite_local',model),self.assertRaises(SceneStateError):
                write_directed_clip({},request(),seg,[photo],None)
            self.assertEqual(model.call_count,2)
            self.assertNotIn('scene_state_debug',seg);self.assertNotIn('prompt_validation',seg)

    def test_planner_repairs_only_invalid_structure_then_saves_without_extra_call(self):
        bad=treatment();bad['segments']=bad['segments'][:-1]
        with tempfile.TemporaryDirectory() as tmp:
            photo,_=self.fixture(Path(tmp));model=Mock(side_effect=[json.dumps(bad),json.dumps(treatment())])
            ensure_plan({},request(),timeline(),[photo],tmp,model)
            self.assertEqual(model.call_count,2)
            self.assertTrue((Path(tmp)/'director_plan.json').exists())
            self.assertIn('segment',model.call_args.args[2][-1][1])

    def test_unchanged_appearance_not_duplicated_and_changed_appearance_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo,seg=self.fixture(Path(tmp));model=Mock(return_value=h3('A performance. <Picture 1>.'))
            with patch('banana_mv.services.rewrite_local',model):
                write_directed_clip({},request(),seg,[photo],None)
                task=json.loads(model.call_args.args[2][0][1])
                self.assertNotIn('appearance_end',task)
                self.assertNotIn('terminal marker',json.dumps(task))
                self.assertEqual(model.call_count,1)
                plan=validate_unified_plan(treatment(),timeline(),1)
                seg['director_plan']=plan['segments'][1]
                write_directed_clip({},request(),seg,[photo],None)
                task=json.loads(model.call_args.args[2][0][1])
                self.assertEqual(task['appearance_end']['characters']['S1']['not_wearing'][0]['state'],'placed')

    def test_incomplete_native_output_is_repaired_in_same_writer_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo,seg=self.fixture(Path(tmp))
            model=Mock(side_effect=['summary: incomplete',h3('The event continues.')])
            with patch('banana_mv.services.rewrite_local',model):
                result=write_directed_clip({},request(),seg,[photo],None)
            self.assertEqual(model.call_count,2)
            validate_h3_sections(result)
            self.assertIn('六個區塊',model.call_args.args[2][-1][1])

    def test_empty_native_sections_are_not_successful_output(self):
        for section in ('summary','retention_analysis','detailed_description'):
            text=h3('A readable action.')
            import re
            text=re.sub(r'(?ms)^'+section+r':.*?(?=^[a-z_]+:)',section+':\n',text)
            with self.subTest(section=section),self.assertRaisesRegex(ValueError,'不可空白'):
                validate_h3_sections(text)

    def test_no_external_guide_and_preserve_official_six_section_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo,seg=self.fixture(Path(tmp));model=Mock(return_value=h3('A performance. <Picture 1>.'))
            with patch('banana_mv.services.rewrite_local',model):
                write_directed_clip({'guides':{'ref':'/does/not/exist.md'}},request(),seg,[photo],None)
            self.assertEqual(model.call_count,1)
            system=model.call_args.args[1]
            for heading in ('subject_definitions','summary','retention_analysis','detailed_description','overall_soundscape','non_diegetic_music'):
                self.assertIn(heading,system)
            self.assertIn('MM:SS.mmm',system)
            self.assertLess(len(system),2500)
            self.assertLess(len(UNIFIED_SYSTEM),4000)
            self.assertNotIn('violations',system)

if __name__=='__main__':unittest.main()
