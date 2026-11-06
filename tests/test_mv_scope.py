"""Whole-work closure, excerpt continuation and short-tail regressions; no GPU."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from banana_mv.mv_scope import ending_contract, clip_ending, validate_scope
from banana_mv.story_plan import validate_unified_plan, ensure_plan
from test_unified_direction import treatment, timeline, request, h3


def full_plan():
    raw=treatment()
    raw['ending_plan']={'start_time':4,'resolved_by':7.5,'resolution':'Finish the performance gesture before settling.'}
    return raw


class ScopeTests(unittest.TestCase):
    def test_scope_is_explicit_not_guessed_from_duration(self):
        for seconds in (2,15,72,203):
            self.assertFalse(ending_contract({'project_scope':'excerpt'},seconds)['finish_work'])
            full=ending_contract({'project_scope':'full'},seconds)
            self.assertTrue(full['finish_work'])
            self.assertLess(full['resolve_start_by'],full['settle_by'])
            self.assertLess(full['settle_by'],seconds)
        for value in ('auto','',None,True):
            with self.assertRaises(ValueError):validate_scope(value)

    def test_short_tail_holds_an_ending_begun_in_prior_interval(self):
        seg={'index':7,'segment_count':8,'start':70,'seconds':2,'song_seconds':72,
             'direction_ending_plan':{'start_time':62,'resolved_by':69,'resolution':'The supplied story resolves.'}}
        final=clip_ending({'project_scope':'full'},seg)
        self.assertEqual(final['local_resolution_start'],0)
        self.assertEqual(final['local_settle_by'],.5)
        self.assertEqual(final['local_resolution_by'],0)
        earlier=clip_ending({'project_scope':'full'},dict(seg,index=6,start=60,seconds=10))
        self.assertEqual(earlier['phase'],'resolving')
        self.assertEqual(earlier['local_resolution_start'],2)
        self.assertEqual(earlier['local_resolution_by'],9)
        edge=clip_ending({'project_scope':'full'},dict(seg,index=6,start=60,seconds=9))
        self.assertEqual(edge['local_resolution_by'],9)
        very_early=clip_ending({'project_scope':'full'},dict(seg,index=0,start=0,seconds=10))
        self.assertEqual(very_early['phase'],'continuing')
        self.assertNotIn('resolution',very_early)

    def test_full_interval_budget_matches_early_ending_behavior(self):
        from banana_mv.core import segments
        for total,chunk,latest in ((72,10,60),(60,15,45),(59,15,45),(203,10,190),(9,4,4)):
            contract=ending_contract({'project_scope':'full'},total,segments(total,chunk))
            self.assertEqual(contract['resolve_start_by'],latest)

    def test_full_plan_requires_real_time_for_resolution_and_hold(self):
        raw=full_plan();before=deepcopy(raw)
        plan=validate_unified_plan(raw,timeline(),1,{'project_scope':'full'})
        self.assertEqual(raw,before)
        self.assertEqual(plan['ending_plan'],raw['ending_plan'])
        for change in ({'start_time':8,'resolved_by':8.5},{'resolved_by':9},
                       {'resolved_by':float('nan')},{'resolved_by':True}):
            bad=full_plan();bad['ending_plan'].update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_unified_plan(bad,timeline(),1,{'project_scope':'full'})
        with self.assertRaisesRegex(ValueError,'ending_plan'):
            validate_unified_plan(treatment(),timeline(),1,{'project_scope':'full'})

    def test_excerpt_must_not_force_a_terminal_image(self):
        raw=treatment();raw.update(closing_shot='',ending_plan=None)
        result=validate_unified_plan(raw,timeline(),1,{'project_scope':'excerpt'})
        self.assertEqual(result['closing_shot'],'');self.assertIsNone(result['ending_plan'])
        raw['closing_shot']='Farewell to the entire show.'
        with self.assertRaisesRegex(ValueError,'片段 MV'):
            validate_unified_plan(raw,timeline(),1,{'project_scope':'excerpt'})

    def test_planner_scope_is_persisted_and_changing_it_rejects_cached_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw=full_plan();raw['initial_state']['character_states']['S1']['identity_reference']=None
            model=Mock(return_value=json.dumps(raw))
            req=request(project_scope='full')
            ensure_plan({},req,timeline(),[],tmp,model)
            task=json.loads(model.call_args.args[2][0][1])
            self.assertTrue(task['ending_contract']['finish_work'])
            self.assertEqual(task['ending_contract']['settle_by'],7.5)
            with self.assertRaises(ValueError):
                ensure_plan({},dict(req,project_scope='excerpt'),timeline(),[],tmp,model)
            self.assertEqual(model.call_count,1)

    def test_writer_restores_recipes_and_routes_last_excerpt_without_closing(self):
        from banana_mv.prompt_quality import write_directed_clip
        for scope in ('full','excerpt'):
            raw=full_plan()
            if scope=='excerpt':raw.update(closing_shot='',ending_plan=None)
            req=request(project_scope=scope)
            plan=validate_unified_plan(raw,timeline(),1,req)
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);photo=root/'ref.png';Image.new('RGB',(8,8)).save(photo)
                guide=root/'guide.md';guide.write_text('H3 visual guide')
                seg=dict(timeline()[-1],director_plan=plan['segments'][-1],direction_constraints=plan['constraints'],
                         direction_closing_shot=plan['closing_shot'],direction_ending_plan=plan['ending_plan'],
                         direction_ending_contract=plan['ending_contract'])
                model=Mock(return_value=h3('A purposeful performance gesture. <Picture 1>.'))
                with patch('banana_mv.services.rewrite_local',model):
                    write_directed_clip({'guides':{'ref':str(guide)}},req,seg,[photo],None)
                task=json.loads(model.call_args.args[2][0][1])
                self.assertIn('Hold the established final composition' if scope=='full' else 'Give the singer a purposeful response',task['cinematography'])
                self.assertEqual(task['ending_contract']['finish_work'],scope=='full')
                self.assertEqual('closing_shot' in task,scope=='full')
                if scope=='excerpt':self.assertNotIn('Hold the final gesture',json.dumps(task))

    def test_api_rejects_unknown_scope_before_loading_assets(self):
        from banana_mv import server
        with patch.object(server.backend,'load_config',return_value={}):
            with self.assertRaisesRegex(ValueError,'作品範圍'):
                server.start({'project_scope':'guess'})

    def test_no_rewrite_path_obeys_excerpt_even_in_last_interval(self):
        from banana_mv import server
        with tempfile.TemporaryDirectory() as tmp:
            photo=Path(tmp)/'ref.png';Image.new('RGB',(8,8)).save(photo)
            result=server.local_prompt({},request(project_scope='excerpt',rewrite=False,director_schema=2),
                                       timeline()[-1],[photo],None)
            self.assertIn('This is an excerpt',result)
            self.assertNotIn('FINAL SONG WINDOW',result)

if __name__=='__main__':unittest.main()
