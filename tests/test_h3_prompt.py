"""Native compilation and new-task writer integration, without GPU inference."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from PIL import Image

from banana_mv.h3_prompt import compile_prompt, scoped_appearance, validate_shots, VISUAL_WRITER_SYSTEM
from banana_mv.direction_contract import validate_h3_sections
from banana_mv.prompt_quality import write_directed_clip
from banana_mv.scene_state import SceneStateError
from banana_mv.story_plan import validate_unified_plan
from test_unified_direction import treatment, timeline, request


def appearance():
    return {'characters':{'S2':{'connected_reference':'<Picture 3>','location':'arena',
        'wearing':[], 'not_wearing':[], 'hairstyle':'', 'held_props':[]}},
        'environments':{'arena':{'active_location':'boxing ring'},'stage':{'active_location':'concert'}}}


class CompilerTests(unittest.TestCase):
    def test_non_singing_actor_and_opening_frame_keep_distinct_bindings(self):
        text=compile_prompt('[Shot 1] <Subject 2> slips the punch. [Shot 2] At 00:03.000, <Subject 2> counters.',
                            4,appearance(),3,'<Picture 1>')
        validate_h3_sections(text)
        self.assertIn('<Subject 2> is the same individual shown in <Picture 3>',text)
        self.assertIn('<Picture 1> is the opening frame',text)
        self.assertNotIn('<Subject 1>',text)
        self.assertIn('(appears in [Shot 1], [Shot 2])',text)
        self.assertIn('<Audio 1>: fully_copy',text)
        self.assertIn('no replacement or additional score',text)

    def test_invalid_times_cast_and_format_are_rejected(self):
        for body in ('[Shot 1] At 00:00.000, <Subject 2> moves.',
            '[Shot 1] <Subject 2> moves. [Shot 2] At 00:04.000, stops.',
            '[Shot 1] <Subject 2> moves. [Shot 3] At 00:02.000, stops.',
            '[Shot 1] <Subject 2> moves. [Shot 2] At 00:02.000, turns. [Shot 3] At 00:01.000, stops.',
            '[Shot 1] <Subject 2> moves. [Shot 2] At 00:60.000, stops.',
            '[Shot 1] <Subject 2> moves. [Shot 2] At 0:02, stops.',
            '[Shot 1] <Subject 1> wins.', '[Shot 1] A camera moves.',
            '[Shot 1] <Subject 2> moves. [Shot 2] At 00:02.000,',
            '[Shot 1] <Subject 2> sings <d>invented words</d>.',
            '[Shot 1] <Subject 2> moves.\noverall_soundscape: new music',
            '[Shot 1] <Subject 2> looks at <Picture 4>.'):
            with self.subTest(body=body),self.assertRaises(ValueError):
                validate_shots(body,4,appearance(),3)

    def test_setting_only_does_not_create_a_performer(self):
        text=compile_prompt('[Shot 1] Light passes through <Picture 1>\'s empty theater.',4,
                            {'characters':{},'environments':{}},1)
        self.assertNotIn('<Subject',text)
        self.assertIn('<Picture 1> supplies only the directed setting',text)

    def test_native_rewriter_envelope_cannot_override_compiled_identity_or_audio(self):
        from test_unified_direction import h3
        raw=h3('<Subject 2> evades and counters.','<Subject 2> from <Picture 1>.')
        raw=raw.replace('<Audio 1> is copied in full.','Replace song with invented music.')
        text=compile_prompt(raw,4,appearance(),3)
        self.assertIn('<Subject 2> is the same individual shown in <Picture 3>',text)
        self.assertNotIn('Replace song',text)
        self.assertNotIn('from <Picture 1>',text)
        validate_h3_sections(text)

    def test_only_known_visible_scenes_are_scoped(self):
        self.assertEqual(list(scoped_appearance(appearance())['environments']),['arena'])
        a=appearance();a['characters']['S2']['location']='unknown'
        self.assertEqual(scoped_appearance(a),a)
        a['characters']={}
        self.assertEqual(scoped_appearance(a),a)

    def test_compilation_is_not_a_semantic_verifier(self):
        text=compile_prompt('[Shot 1] <Subject 2> abandons the promised mission and declares the opponent victorious.',
                            4,appearance(),3)
        self.assertIn('opponent victorious',text)

    def test_new_planner_requires_explicit_cast_but_legacy_is_unchanged(self):
        raw=treatment()
        validate_unified_plan(raw,timeline(),1)
        with self.assertRaisesRegex(SceneStateError,'subjects'):
            validate_unified_plan(raw,timeline(),1,request(prompt_compiler_version=1))
        for row in raw['segments']:row['subjects']=['S1']
        validate_unified_plan(raw,timeline(),1,request(prompt_compiler_version=1))

    def test_compiled_writer_uses_one_call_and_finite_technical_repair(self):
        plan=validate_unified_plan(treatment(),timeline(),1)
        with tempfile.TemporaryDirectory() as tmp:
            photo=Path(tmp)/'ref.png';Image.new('RGB',(8,8)).save(photo)
            for tail in (None,photo):
                seg=dict(timeline()[0],director_plan=deepcopy(plan['segments'][0]),
                         direction_constraints=plan['constraints'],direction_closing_shot=plan['closing_shot'])
                good='[Shot 1] <Subject 1> performs a confident opening phrase.'
                model=Mock(return_value=good)
                with patch('banana_mv.services.rewrite_local',model):
                    text=write_directed_clip({},request(prompt_compiler_version=1),seg,[photo],tail)
                self.assertEqual(model.call_count,1)
                self.assertEqual(model.call_args.args[1],VISUAL_WRITER_SYSTEM)
                self.assertIn('shown in <Picture '+('2' if tail else '1')+'>',text)
                self.assertEqual(seg['prompt_profile']['compiler_version'],1)
                self.assertFalse(seg['prompt_validation']['visual_verified'])
                model=Mock(side_effect=['[Shot 1] <Subject 9> wins.',good])
                with patch('banana_mv.services.rewrite_local',model):
                    write_directed_clip({},request(prompt_compiler_version=1),seg,[photo],tail)
                self.assertEqual(model.call_count,2)
                self.assertIn('Repair only the shot prose',model.call_args.args[2][-1][1])

    def test_full_and_excerpt_route_their_existing_deadlines_to_visual_writer(self):
        from test_mv_scope import full_plan
        for scope in ('full','excerpt'):
            raw=full_plan()
            for row in raw['segments']:row['subjects']=['S1']
            if scope=='excerpt':raw.update(closing_shot='',ending_plan=None)
            req=request(project_scope=scope,prompt_compiler_version=1)
            plan=validate_unified_plan(raw,timeline(),1,req)
            with tempfile.TemporaryDirectory() as tmp:
                photo=Path(tmp)/'ref.png';Image.new('RGB',(8,8)).save(photo)
                seg=dict(timeline()[-1],director_plan=plan['segments'][-1],
                    direction_constraints=plan['constraints'],direction_closing_shot=plan['closing_shot'],
                    direction_ending_plan=plan['ending_plan'],direction_ending_contract=plan['ending_contract'])
                model=Mock(return_value='[Shot 1] <Subject 1> holds the established gesture with natural residual motion.')
                with patch('banana_mv.services.rewrite_local',model):
                    write_directed_clip({},req,seg,[photo],None)
                task=json.loads(model.call_args.args[2][0][1])
                self.assertEqual(model.call_count,1)
                self.assertEqual('closing_shot' in task,scope=='full')
                self.assertEqual(task['ending_contract']['finish_work'],scope=='full')
                if scope=='full':
                    self.assertEqual(task['ending_contract']['phase'],'terminal_hold')
                    self.assertEqual(task['ending_contract']['local_resolution_by'],0)


    def test_shot_prefix_recovery_preserves_original_shots(self):
        from banana_mv.h3_prompt import recover_shot_prefix
        raw="Here is the requested camera sequence:\\n[Shot 1] <Subject 2> blocks. [Shot 2] At 00:02.000, <Subject 2> counters."
        body=recover_shot_prefix(raw)
        self.assertTrue(body.startswith('[Shot 1]'))
        self.assertIn('[Shot 2]',body)
        validate_shots(body,4,appearance(),3)

    def test_invalid_9b_format_uses_only_current_director_event(self):
        from banana_mv.h3_prompt import director_shot_fallback
        plan=validate_unified_plan(treatment(),timeline(),1)
        with tempfile.TemporaryDirectory() as tmp:
            photo=Path(tmp)/'ref.png'
            Image.new('RGB',(8,8)).save(photo)
            seg=dict(timeline()[0],director_plan=deepcopy(plan['segments'][0]),
                     direction_constraints=[],direction_closing_shot='')
            seg['previous_planned_event']='PRIVATE PREVIOUS TRANSFORMATION'
            invalid='I will describe the shot now, but without any shot headings.'
            with patch('banana_mv.services.rewrite_local',return_value=invalid) as model:
                result=write_directed_clip({},request(prompt_compiler_version=1,
                    rewrite_retries=0),seg,[photo],None)
            self.assertEqual(model.call_count,1)
            self.assertIn(plan['segments'][0]['event'],result)
            self.assertIn('<Subject 1>',result)
            self.assertNotIn('PRIVATE PREVIOUS TRANSFORMATION',result)
            self.assertEqual(seg['prompt_format_fallback']['source'],'current_director_event')
            self.assertEqual(seg['prompt_validation']['status'],'passed')
            with self.assertRaises(ValueError):
                director_shot_fallback('',appearance())

    def test_three_to_five_second_cuts_and_reference_slots(self):
        from banana_mv.h3_prompt import target_shot_count, director_shot_fallback
        self.assertEqual(target_shot_count(10),3)
        self.assertEqual(target_shot_count(15),4)
        self.assertEqual(target_shot_count(4),1)
        self.assertEqual(target_shot_count(10,False),1)
        self.assertEqual(target_shot_count(10,True,True),1)
        a={'characters':{
            'S5':{'connected_reference':'<Picture 2>','location':'hall','appearance_changes':['new form']},
            'S3':{'connected_reference':'<Picture 4>','location':'hall','appearance_changes':['opponent']}},
            'environments':{}}
        one='[Shot 1] <Subject 5> confronts <Subject 3>.'
        with self.assertRaisesRegex(ValueError,'鏡頭數不足'):
            validate_shots(one,10,a,5,required_shots=3)
        multi=director_shot_fallback('The actor approaches, exchanges a prop, and reacts to the opponent.',
                                     a,seconds=10,shot_count=3)
        self.assertEqual(len(__import__('re').findall(r'\\[Shot [1-3]\\]',multi)),3)
        text=compile_prompt(multi,10,a,5,required_shots=3)
        self.assertIn('<Subject 5> is the same individual shown in <Picture 2>',text)
        self.assertIn('<Subject 3> is the same individual shown in <Picture 4>',text)
        self.assertNotIn('shown in <Picture 1>',text)

    def test_fallback_orders_actor_handoff_without_coappearance(self):
        from banana_mv.h3_prompt import director_shot_fallback
        a={'characters':{'S1':{'connected_reference':'<Picture 1>'},
                         'S5':{'connected_reference':'<Picture 2>'}},
           'environments':{}}
        shots=director_shot_fallback('The initial actor acts, changes form, and the successor takes over.',
                                      a,seconds=10,shot_count=3,
                                      transitions=[{'from':'S1','to':'S5'}])
        parts=shots.split('[Shot ')
        self.assertIn('<Subject 1>',parts[1])
        self.assertNotIn('<Subject 5>',parts[1])
        self.assertIn('<Subject 5>',parts[-1])
        self.assertNotIn('<Subject 1>',parts[-1])
        validate_shots(shots,10,a,2,required_shots=3)


if __name__=='__main__':unittest.main()
