"""Initialization format regressions; mocked 9B output is not a GPU/visual acceptance test."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from banana_mv.scene_state import (INITIAL_EXAMPLE,INITIAL_EVENT_SCHEMA,INIT_SYSTEM,
    SceneStateError,ensure_scene_state,initial_state,parse_object,read_json)
from tests.test_scene_state import fixture,event


def timeline(count,seconds):
    return [{'index':i,'start':i*seconds,'seconds':seconds,'segment_count':count,
             'song_seconds':count*seconds,'model_frames':int(seconds*24)+2,'frames':int(seconds*24)}
            for i in range(count)]


class InitialSceneStateTests(unittest.TestCase):
    def test_prompt_example_obeys_actual_event_validator(self):
        state,catalog=initial_state(INITIAL_EXAMPLE,timeline(4,15),0)
        self.assertEqual(list(catalog),['E1'])
        self.assertEqual(INITIAL_EVENT_SCHEMA['required'],['event_id','description'])
        self.assertIn(json.dumps(INITIAL_EXAMPLE,ensure_ascii=False),INIT_SYSTEM)
        self.assertEqual(state['timeline']['total_duration'],60)

    def test_configurable_retry_budget_and_progress_do_not_invalidate_saved_state(self):
        from banana_mv.scene_state import rewrite_retry_count
        self.assertEqual(rewrite_retry_count({}),3)
        for value in (-1,6,True,1.5,'3'):
            with self.subTest(value=value),self.assertRaises(ValueError):rewrite_retry_count({'rewrite_retries':value})
        with tempfile.TemporaryDirectory() as temp:
            req={'prompt':'sing','rewrite_retries':3};progress=[]
            # Distinct failures may use the configured budget; an identical
            # response now stops after one unsuccessful format-repair attempt.
            model=Mock(side_effect=['bad','different invalid JSON',json.dumps(INITIAL_EXAMPLE)])
            ledger=ensure_scene_state({},req,timeline(6,10),[],temp,model,progress=progress.append)
            self.assertEqual(model.call_count,3)
            self.assertEqual([v['attempt'] for v in progress],[1,2,3])
            self.assertTrue(all(v['max_attempts']==4 for v in progress))
            # Old projects had no explicit budget; retry-only changes must not break the fingerprint.
            for changed in ({'prompt':'sing'},{'prompt':'sing','rewrite_retries':5}):
                loaded=ensure_scene_state({},changed,timeline(6,10),[],temp,model)
                self.assertEqual(loaded,ledger);self.assertEqual(model.call_count,3)
        for retries in (0,2):
            with self.subTest(retries=retries),tempfile.TemporaryDirectory() as temp:
                model=Mock(return_value='bad')
                with self.assertRaises(SceneStateError):
                    ensure_scene_state({}, {'prompt':'sing','rewrite_retries':retries},timeline(6,10),[],temp,model)
                self.assertEqual(model.call_count,min(retries+1,2))

    def test_performance_combat_and_multistage_costumes_for_both_timelines(self):
        from PIL import Image
        performance=fixture();performance['events']=[event('sing','perform the requested song',repeat=True)]
        combat=fixture();combat['events']=[event('sing','perform the song',repeat=True),
            event('attack','opponent attacks'),event('counter','lead counters',deps=['attack']),
            event('finish','return to the final singing close-up',final=True,deps=['counter'])]
        for name,source in [('performance',performance),('intercut',combat),('costume',fixture())]:
            for count,seconds in [(4,15),(6,10)]:
                with self.subTest(kind=name,clips=count),tempfile.TemporaryDirectory() as temp:
                    req={'prompt':name,'scene_state_version':1};model=Mock(return_value=json.dumps(source))
                    reference=Path(temp)/'ref.png';Image.new('RGB',(16,16)).save(reference)
                    ledger=ensure_scene_state({},req,timeline(count,seconds),[reference],temp,model)
                    self.assertEqual(ledger['initial_state']['timeline']['total_duration'],60)
                    self.assertTrue(ledger['event_catalog']);self.assertEqual(model.call_count,1)
                    debug=read_json(Path(temp)/'scene_state_init_debug.json')
                    self.assertEqual(debug['status'],'validated')
                    self.assertEqual(debug['attempts'][0]['parsed_response'],source)
                    self.assertEqual(debug['attempts'][0]['events'],source['events'])

    def test_standard_json_and_common_markdown_wrappers(self):
        raw=json.dumps(INITIAL_EXAMPLE)
        for wrapped in [raw,'```json\n'+raw+'\n```','```JSON\r\n'+raw+'\r\n```',
                        'Result:\n```json\n'+raw+'\n```\nEnd.', '\ufeff'+raw,
                        '<think>hidden reasoning</think>\n```json\n'+raw+'\n```']:
            with self.subTest(wrapper=wrapped[:20]):self.assertEqual(parse_object(wrapped),INITIAL_EXAMPLE)
        self.assertEqual(parse_object('```json\n{}\n```\n```json\n{}\n```'),{})
        with self.assertRaisesRegex(SceneStateError,'內容衝突'):
            parse_object('```json\n{"events": []}\n```\n```json\n{"events": ["different"]}\n```')
        with self.assertRaises(SceneStateError):parse_object('{"events": NaN}')

    def test_initial_json_blocks_can_split_fields_or_repeat_without_changing_events(self):
        initial=json.dumps({'initial_state':INITIAL_EXAMPLE['initial_state']})
        events=json.dumps({'events':INITIAL_EXAMPLE['events']})
        raw='```json\n'+initial+'\n```\n```json\n'+events+'\n```'
        with tempfile.TemporaryDirectory() as temp:
            model=Mock(return_value=raw)
            ledger=ensure_scene_state({}, {'prompt':'sing','rewrite_retries':1},timeline(6,10),[],temp,model)
            self.assertEqual(model.call_count,1);self.assertEqual(list(ledger['event_catalog']),['E1'])
            debug=read_json(Path(temp)/'scene_state_init_debug.json')['attempts'][0]
            self.assertEqual(debug['raw_response'],raw)
            self.assertEqual(debug['parsed_response'],INITIAL_EXAMPLE)

    def test_invalid_json_logs_raw_parse_error_and_repairs_once_using_failed_response(self):
        invalid='```json\n{"events": [}\n```';valid=json.dumps(INITIAL_EXAMPLE)
        with tempfile.TemporaryDirectory() as temp:
            model=Mock(side_effect=[invalid,valid])
            ledger=ensure_scene_state({}, {'prompt':'sing the supplied song'},timeline(4,15),[],temp,model)
            self.assertEqual(model.call_count,2);self.assertTrue(ledger['event_catalog'])
            attempts=read_json(Path(temp)/'scene_state_init_debug.json')['attempts']
            self.assertEqual(attempts[0]['raw_response'],invalid)
            self.assertIsNone(attempts[0]['parsed_response'])
            self.assertEqual(attempts[0]['schema_validation_errors'][0]['code'],'invalid_json')
            self.assertIn('第 1 行',attempts[0]['schema_validation_errors'][0]['message'])
            repair=model.call_args_list[1]
            text='\n'.join(v for kind,v in repair.args[2] if kind=='text')
            self.assertIn(json.dumps(invalid,ensure_ascii=False),text)
            self.assertIn('invalid_json',text);self.assertIn('preserve the user story',text)
            self.assertIn('application retry budget',repair.args[1])
            self.assertEqual(attempts[1]['schema_validation_errors'],[])

    def test_empty_events_stays_failed_keeps_media_and_all_raw_attempts(self):
        source=deepcopy(INITIAL_EXAMPLE);source['events']=[]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);part=root/'00_part.mp4';part.write_bytes(b'existing valid media')
            final=root/'final.mp4';final.write_bytes(b'existing final')
            model=Mock(return_value=json.dumps(source))
            with self.assertRaisesRegex(SceneStateError,r'\$\.events.*實際有 0 個'):
                ensure_scene_state({}, {'prompt':'sing','rewrite_retries':1},timeline(6,10),[],root,model)
            self.assertEqual(model.call_count,2);self.assertFalse((root/'scene_state.json').exists())
            self.assertEqual(part.read_bytes(),b'existing valid media');self.assertEqual(final.read_bytes(),b'existing final')
            debug=read_json(root/'scene_state_init_debug.json')
            self.assertEqual(debug['status'],'failed');self.assertEqual(len(debug['attempts']),2)
            for attempt in debug['attempts']:
                self.assertEqual(attempt['events'],[]);self.assertTrue(attempt['events_present'])
                self.assertEqual(attempt['parsed_response'],source)
                self.assertEqual(attempt['schema_validation_errors'][0]['code'],'count')
            self.assertEqual(len(list(root.glob('scene_state_init_*_0*.json'))),2)

    def test_missing_misplaced_wrong_type_and_non_object_events_are_distinguished(self):
        for value,code in [('missing','required'),('nested','misplaced'),('dict','type'),('row','type')]:
            with self.subTest(kind=value),tempfile.TemporaryDirectory() as temp:
                source=deepcopy(INITIAL_EXAMPLE)
                if value=='missing':source.pop('events')
                elif value=='nested':source['initial_state']['events']=source.pop('events')
                elif value=='dict':source['events']={'E1':source['events'][0]}
                else:source['events']=['sing']
                model=Mock(side_effect=[json.dumps(source),json.dumps(INITIAL_EXAMPLE)])
                ensure_scene_state({}, {'prompt':'sing','rewrite_retries':1},timeline(4,15),[],temp,model)
                first=read_json(Path(temp)/'scene_state_init_debug.json')['attempts'][0]
                self.assertEqual(first['schema_validation_errors'][0]['code'],code)
                self.assertEqual(first['parsed_response'],source)
                if value=='nested':self.assertEqual(first['nested_events'],INITIAL_EXAMPLE['events'])

    def test_missing_event_fields_report_exact_paths_together(self):
        source=deepcopy(INITIAL_EXAMPLE);source['events']=[{'repeatable':'yes','allowed_operations':['fly']}]
        with self.assertRaises(SceneStateError) as ctx:initial_state(source,timeline(4,15),0)
        errors=ctx.exception.errors
        self.assertEqual({e['path'] for e in errors},{'$.events[0].event_id','$.events[0].description',
                         '$.events[0].repeatable','$.events[0].allowed_operations'})
        source['events']=[{'event_id':'sing','description':'sing'}]
        _,catalog=initial_state(source,timeline(4,15),0)
        self.assertEqual(catalog['sing'],{'description':'sing','repeatable':False,'reserved_final':False,
                                        'depends_on':[],'allowed_operations':[]})

    def test_event_dependency_and_operation_errors_are_path_specific(self):
        for field,value,code in [('depends_on',['missing'],'unknown_event'),('depends_on',['E1'],'cycle'),
                                 ('allowed_operations','move','type'),('description','  ','type')]:
            with self.subTest(field=field,value=value):
                source=deepcopy(INITIAL_EXAMPLE);source['events'][0][field]=value
                with self.assertRaises(SceneStateError) as ctx:initial_state(source,timeline(4,15),0)
                self.assertEqual(ctx.exception.errors[0]['path'],'$.events[0].'+field)
                self.assertEqual(ctx.exception.errors[0]['code'],code)

    def test_transport_failure_is_logged_without_a_format_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            model=Mock(side_effect=RuntimeError('ComfyUI unavailable'))
            with self.assertRaisesRegex(SceneStateError,'ComfyUI unavailable'):
                ensure_scene_state({}, {'prompt':'sing','rewrite_retries':1},timeline(4,15),[],temp,model)
            self.assertEqual(model.call_count,1)
            attempt=read_json(Path(temp)/'scene_state_init_debug.json')['attempts'][0]
            self.assertEqual(attempt['stage'],'generation');self.assertEqual(attempt['status'],'failed')

    def test_format_repair_cannot_replace_existing_valid_event_content(self):
        source=deepcopy(INITIAL_EXAMPLE);source['initial_state']['events']=source.pop('events')
        replacement=deepcopy(INITIAL_EXAMPLE);replacement['events'][0]['description']='invent an unrelated fight'
        with tempfile.TemporaryDirectory() as temp:
            model=Mock(side_effect=[json.dumps(source),json.dumps(replacement)])
            with self.assertRaisesRegex(SceneStateError,'格式修復改動'):
                ensure_scene_state({}, {'prompt':'sing','rewrite_retries':1},timeline(4,15),[],temp,model)
            self.assertEqual(model.call_count,2);self.assertFalse((Path(temp)/'scene_state.json').exists())
            last=read_json(Path(temp)/'scene_state_init_debug.json')['attempts'][-1]
            self.assertEqual(last['schema_validation_errors'][0]['code'],'repair_changed_content')

    def test_repeated_failed_initializations_keep_prior_diagnostics(self):
        with tempfile.TemporaryDirectory() as temp:
            for _ in range(2):
                with self.assertRaises(SceneStateError):
                    ensure_scene_state({}, {'prompt':'sing','rewrite_retries':1},timeline(4,15),[],temp,Mock(return_value='bad'))
            self.assertEqual(len(list(Path(temp).glob('scene_state_init_*_0*.json'))),4)

    def test_worker_never_plans_clips_or_removes_successful_media_after_bad_initialization(self):
        from banana_mv import server
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);work=root/'runs'/'abcdef123456';work.mkdir(parents=True)
            media=work/'00_part.mp4';media.write_bytes(b'successful existing clip')
            req={'prompt':'sing','rewrite_retries':1,'scene_state_version':1,'rewrite':True,'story_plan':False,
                 'audio_analysis':False,'director_version':2}
            segs=timeline(4,15);segs[0]['status']='done'
            job={'id':'abcdef123456','request':req,'segments':segs,'status':'running','size':(720,1280)}
            source=deepcopy(INITIAL_EXAMPLE);source['events']=[]
            with patch.object(server,'RUNS',root/'runs'),patch.object(server.backend,'rewrite_local',return_value=json.dumps(source)) as model, \
                 patch.object(server,'local_prompt') as clip_model,patch.object(server,'reconcile_history') as reconcile, \
                 patch.object(server.backend,'queue_prompt') as gpu:
                self.assertTrue(server.GPU_LOCK.acquire(blocking=False))
                server.worker(job,{'comfy_input_dir':str(root)},[],root/'song.mp3',root/'song.mp3')
                self.assertEqual(job['status'],'error');self.assertEqual(job['error_stage'],'planning_state')
                self.assertEqual(job['segments'][0]['status'],'done')
                self.assertEqual(media.read_bytes(),b'successful existing clip')
                self.assertEqual(model.call_count,2);clip_model.assert_not_called()
                reconcile.assert_not_called();gpu.assert_not_called()


if __name__=='__main__':unittest.main()


class EnvironmentFormatTests(unittest.TestCase):

    def test_redundant_scene_id_and_empty_map_arrays_are_lossless_and_idempotent(self):
        from banana_mv.scene_state import normalize_environment
        raw={'scene_id':'room','active_location':'studio','persistent_changes':[],
             'damaged_objects':[],'prop_positions':{'chair':'left'}}
        before=deepcopy(raw)
        result=normalize_environment(raw,'room')
        self.assertEqual(raw,before)
        self.assertEqual(result,{'active_location':'studio','persistent_changes':[],
                                'damaged_objects':{},'prop_positions':{'chair':'left'}})
        self.assertEqual(normalize_environment(result,'room'),result)

    def test_conflicting_ids_nonempty_arrays_unknown_fields_and_null_keep_precise_errors(self):
        from banana_mv.scene_state import normalize_environment
        for raw,field in [({'scene_id':'elsewhere'},'scene_id'),
                          ({'damaged_objects':['broken chair', 42]},'damaged_objects'),
                          ({'prop_positions':None},'prop_positions'),
                          ({'unknown':True},'unknown')]:
            with self.subTest(raw=raw),self.assertRaises(SceneStateError) as caught:
                normalize_environment(raw,'room')
            self.assertEqual(caught.exception.errors[0]['path'],
                             '$.initial_state.environment_states.room.'+field)

    def test_normalization_survives_initial_state_and_keeps_nonempty_maps(self):
        raw=deepcopy(INITIAL_EXAMPLE)
        raw['initial_state']['environment_states']={'room':{'scene_id':'room',
            'active_location':'studio','damaged_objects':{'chair':'broken'},'prop_positions':[]}}
        state,_=initial_state(raw,timeline(8,10),0)
        self.assertEqual(state['environment_states']['room']['damaged_objects'],{'chair':'broken'})
        self.assertEqual(state['environment_states']['room']['prop_positions'],{})
        self.assertEqual(raw['initial_state']['environment_states']['room']['prop_positions'],[])

    def test_unified_planner_receives_same_task_at_both_resolutions(self):
        from banana_mv.story_plan import ensure_plan
        raw={'initial_state':{'character_states':{},'environment_states':{'room':{
                 'scene_id':'room','active_location':'studio','damaged_objects':[]}}},
             'constraints':[],'events':[],
             'segments':[{'event':f'Distinct camera task {i}.','mode':'story',
                          'event_indices':[],'completed_indices':[],'changes':[]} for i in range(8)],
             'closing_shot':'Hold the final image.'}
        calls=[]
        for width in (854,1280):
            with tempfile.TemporaryDirectory() as tmp:
                model=Mock(return_value=json.dumps(raw))
                plan=ensure_plan({}, {'director_schema':3,'width':width,'prompt':'Same brief.'},
                                 timeline(8,10),[],tmp,model)
                calls.append(model.call_args.args[1:3])
                self.assertEqual(model.call_count,1)
                self.assertEqual(len(plan['segments']),8)
        self.assertEqual(calls[0],calls[1])

