"""Unified creative planning and memory regressions; GPU inference is mocked."""
from copy import deepcopy
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from banana_mv.story_plan import validate_unified_plan, ensure_plan
from banana_mv.scene_state import SceneStateError, ledger_from_direction, clip_input


def h3(description, definitions='<Subject 1> from <Picture 1>.'):
    return ('subject_definitions:\n'+definitions+'\nsummary:\n[reference generation + audio reuse] This interval.\n'
            'retention_analysis:\n<Audio 1>: fully_copy.\ndetailed_description:\n[Shot 1] '+description+
            '\noverall_soundscape:\n<Audio 1> is copied in full.\nnon_diegetic_music:\nN/A')


def timeline():
    from banana_mv.core import segments
    rows=segments(9,4)
    for r in rows:r.update(segment_count=3,song_seconds=9)
    return rows


def treatment():
    return {'constraints':['S1 is the only singer. The stage remains separate from the arena.'],
        'initial_state':{'character_states':{'S1':{'identity_reference':1,'location':'stage',
            'garments':{'coat':{'garment_type':'coat','material':'fabric','color':'red',
                             'current_status':'worn','current_location':'S1'}}}},
            'environment_states':{'stage':{'active_location':'concert','prop_positions':{'chair':'left'}}}},
        'events':[{'description':'The performer places the coat on the chair.',
                   'repeatable':False,'operations':['remove'],'requires_change':True}],
        'segments':[
            {'event':'The singer performs a confident opening phrase at the microphone.',
             'mode':'performance','event_indices':[],'completed_indices':[],'changes':[]},
            {'event':'The singer places the coat on the chair and continues singing.',
             'mode':'performance','event_indices':[0],'completed_indices':[0],
             'changes':[{'kind':'garment','subject_id':'S1','garment_id':'coat','to':'placed',
                         'current_location':'chair_back','event_index':0,'operation':'remove'}]},
            {'event':'The singer continues with a brief final gesture, without the coat.',
             'mode':'performance','event_indices':[],'completed_indices':[],'changes':[]}],
        'closing_shot':'Hold the final gesture as the original song ends.'}


def request(**extra):
    return dict({'director_schema':3,'director_version':2,'optimizer_version':1,
        'director_authority':True,'rewrite':True,'story_plan':True,'director':'auto',
        'intensity':'high','rewrite_retries':1,'prompt':'BRIEF_ONLY_MARKER: adapt my stage story.',
        'scene_state_version':1,'audio_analysis':False,'face_identity':True,
        'mode':'independent','motion_lora':True},**extra)


class UnifiedPlanTests(unittest.TestCase):
    def test_one_plan_drives_appearance_and_allows_climax_before_outro(self):
        raw=treatment();before=deepcopy(raw)
        plan=validate_unified_plan(raw,timeline(),1)
        self.assertEqual(raw,before)
        self.assertEqual(plan['segments'][2]['appearance_in']['characters']['S1']['wearing'],[])
        self.assertEqual(plan['segments'][2]['appearance_in']['characters']['S1']['not_wearing'][0]['current_location'],'chair_back')
        self.assertFalse(plan['event_catalog']['E1']['reserved_final'])
        self.assertEqual(plan['segments'][1]['completed_source_ids'],['E1'])
        self.assertEqual(plan['segments'][2]['completed_source_ids'],[])

    def test_missing_deltas_cannot_complete_a_declared_state_change(self):
        raw=treatment();raw['segments'][1]['changes']=[]
        with self.assertRaisesRegex(SceneStateError,'缺少changes'):
            validate_unified_plan(raw,timeline(),1)

    def test_intermediate_garment_states_are_visible_without_repeating_the_event(self):
        raw=treatment()
        raw['segments'][0].update(event='The performer unfastens the coat while it remains on the body.',
            event_indices=[0],changes=[{'kind':'garment','subject_id':'S1','garment_id':'coat',
                'to':'unfastened','current_location':'S1','event_index':0,'operation':'remove'}])
        plan=validate_unified_plan(raw,timeline(),1)
        self.assertEqual(plan['segments'][0]['completed_source_ids'],[])
        self.assertEqual(plan['segments'][1]['appearance_in']['characters']['S1']['wearing'][0]['state'],'unfastened')

    def test_replay_and_contradictory_redressing_are_rejected(self):
        for kind in ('replay','redress','bad_from'):
            raw=treatment()
            if kind=='replay':raw['segments'][2]=deepcopy(raw['segments'][1])
            elif kind=='redress':
                raw['events'].append({'description':'An unrelated gesture.','operations':['move']})
                raw['segments'][2].update(event_indices=[1],completed_indices=[1],changes=[{
                    'kind':'garment','subject_id':'S1','garment_id':'coat','to':'worn',
                    'current_location':'S1','operation':'move','event_index':1}])
            else:raw['segments'][1]['changes'][0]['from']='removed'
            with self.subTest(kind=kind),self.assertRaises(SceneStateError):
                validate_unified_plan(raw,timeline(),1)

    def test_incomplete_action_can_continue_without_inventing_a_milestone(self):
        raw=treatment();raw['segments'][0]['event_indices']=[0]
        raw['segments'][0]['event']='The performer reaches toward the coat, still wearing it.'
        plan=validate_unified_plan(raw,timeline(),1)
        self.assertEqual(plan['segments'][0]['completed_source_ids'],[])
        self.assertEqual(plan['segments'][1]['completed_source_ids'],['E1'])

    def test_empty_milestones_and_environment_reference_do_not_create_a_singer(self):
        raw=treatment();raw['initial_state']['character_states']={};raw['events']=[]
        for row in raw['segments']:
            row.update(event_indices=[],completed_indices=[],changes=[],event='Camera explores the supplied building and light changes.',mode='story')
        raw['constraints']=['Image 1 is an architectural scene reference; no performers.']
        plan=validate_unified_plan(raw,timeline(),1)
        self.assertEqual(plan['initial_state']['character_states'],{})
        self.assertTrue(all(not r['source_ids'] for r in plan['segments']))

    def test_global_repair_cache_and_ledger_do_not_replan_the_story(self):
        invalid=treatment();invalid['segments'][1]['changes']=[]
        model=Mock(side_effect=[json.dumps(invalid),json.dumps(treatment())])
        with tempfile.TemporaryDirectory() as tmp:
            image=Path(tmp)/'ref.png';Image.new('RGB',(8,8)).save(image)
            plan=ensure_plan({},request(),timeline(),[image],tmp,model)
            self.assertEqual(model.call_count,2)
            first=ledger_from_direction(request(),timeline(),tmp)
            self.assertEqual(first['event_catalog'],plan['event_catalog'])
            no_model=Mock(side_effect=AssertionError('must reuse saved treatment'))
            self.assertEqual(ensure_plan({},request(),timeline(),[image],tmp,no_model),plan)
            self.assertEqual(ledger_from_direction(dict(request(),rewrite_retries=4),timeline(),tmp),first)
            with self.assertRaises(SceneStateError):
                ensure_plan({},request(prompt='changed brief'),timeline(),[image],tmp,no_model)

    def test_same_bad_plan_is_not_retried_forever(self):
        raw=treatment();raw['segments'][1]['changes']=[]
        model=Mock(return_value=json.dumps(raw))
        with tempfile.TemporaryDirectory() as tmp:
            image=Path(tmp)/'ref.png';Image.new('RGB',(8,8)).save(image)
            with self.assertRaises(SceneStateError):
                ensure_plan({},request(rewrite_retries=5),timeline(),[image],tmp,model)
            self.assertEqual(model.call_count,2)
            self.assertFalse((Path(tmp)/'director_plan.json').exists())

    def test_single_clip_and_faithful_mode_use_the_same_planner(self):
        raw=treatment();raw['events']=[]
        raw['segments']=[dict(raw['segments'][0],event='A single continuous performance phrase with its closing gesture.')]
        segs=[dict(timeline()[0],segment_count=1,song_seconds=4)]
        model=Mock(return_value=json.dumps(raw))
        with tempfile.TemporaryDirectory() as tmp:
            image=Path(tmp)/'ref.png';Image.new('RGB',(8,8)).save(image)
            plan=ensure_plan({},request(story_plan=False),segs,[image],tmp,model)
            self.assertEqual(len(plan['segments']),1)
            self.assertEqual(model.call_count,1)
            self.assertEqual(json.loads(model.call_args.args[2][0][1])['adaptation'],'FAITHFUL')

    def test_parallel_performance_and_nonhuman_action_keep_their_own_locations(self):
        raw=treatment()
        raw['initial_state']['character_states']['S1']['garments']={}
        raw['initial_state']['character_states']['S2']={
            'identity_reference':2,'location':'arena','garments':{}}
        raw['initial_state']['environment_states']['arena']={'active_location':'boxing ring'}
        raw['constraints']=['S1 sings on stage. S2 is a non-singing mascot in the arena. The worlds stay separate.']
        raw['events']=[{'description':'The arena contest is resolved.','operations':[]}]
        raw['segments'][0].update(event='The singer performs on the fixed concert stage.',changes=[],subjects=['S1'])
        raw['segments'][1].update(event='In the arena the mascot finishes the contest; intercut a singing reaction on the separate stage.',
                                 mode='action',changes=[],subjects=['S1','S2'])
        raw['segments'][2].update(event='Return to the stage for the final performance image.',subjects=['S1'])
        plan=validate_unified_plan(raw,timeline(),2)
        for row in plan['segments']:
            chars=row['appearance_out']['characters']
            if 'S1' in chars:self.assertEqual(chars['S1']['location'],'stage')
            if 'S2' in chars:self.assertEqual(chars['S2']['location'],'arena')
        self.assertEqual(plan['segments'][1]['mode'],'action')
        self.assertEqual(plan['segments'][2]['source_ids'],[])


class UnifiedWriterTests(unittest.TestCase):
    def test_plain_writer_compact_output_and_reference_mapping_in_both_modes(self):
        from banana_mv import server
        plan=validate_unified_plan(treatment(),timeline(),1)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'ref.png';Image.new('RGB',(8,8)).save(image)
            guide=root/'guide.md';guide.write_text('Write H3 format.')
            draft=h3('The singer performs. <Audio 1>: fully_copy.')
            for chain in (False,True):
                seg=dict(timeline()[0],director_plan=plan['segments'][0],
                    direction_constraints=plan['constraints'],direction_closing_shot=plan['closing_shot'],
                    direction_requires_change=plan['requires_change'])
                model=Mock(return_value=draft.replace('<Picture 1>','<Picture 2>') if chain else draft)
                with patch.object(server.backend,'rewrite_local',model):
                    final=server.local_prompt({'guides':{'ref':str(guide)}},request(),seg,[image],image if chain else None)
                task=json.loads(model.call_args.args[2][0][1])
                self.assertNotIn('BRIEF_ONLY_MARKER',json.dumps(task))
                self.assertNotIn('event_catalog',task)
                self.assertNotIn('Return ONLY JSON',model.call_args.args[1])
                self.assertEqual(model.call_count,1)
                self.assertEqual(task['appearance_start']['characters']['S1']['connected_reference'],
                                 f'<Picture {2 if chain else 1}>')
                self.assertNotIn('BANANA_REFERENCE_ROLES',final)
                self.assertNotIn('BANANA_PERSISTENT_SCENE_STATE',final)
                self.assertIn('BANANA_FACE_IDENTITY_V1',final)
                self.assertEqual(seg['prompt_profile']['memory_calls'],0)
                # Compare the actual old and new finalization paths using the
                # same model output, rather than an arbitrary character limit.
                legacy_seg=dict(timeline()[0],director_plan={'event':'The singer performs.','mode':'performance'})
                with patch.object(server.backend,'rewrite_local',return_value=draft):
                    legacy=server.local_prompt({'guides':{'ref':str(guide)}},
                        {k:v for k,v in request().items() if k!='director_schema'},legacy_seg,[image],None)
                self.assertLess(len(final),len(legacy))

    def test_nonhuman_and_location_references_are_not_declared_adult_performers(self):
        from banana_mv import server
        raw=treatment();raw['constraints']=['S1 is a banana mascot; preserve nonhuman anatomy.']
        plan=validate_unified_plan(raw,timeline(),1)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);photo=root/'ref.png';Image.new('RGB',(8,8)).save(photo)
            guide=root/'guide.md';guide.write_text('H3 guide')
            seg=dict(timeline()[0],director_plan=plan['segments'][0],direction_constraints=plan['constraints'],
                     direction_closing_shot=plan['closing_shot'])
            model=Mock(return_value=h3('A banana mascot dances. <Picture 1> preserves its identity. <Audio 1>: fully_copy.'))
            with patch.object(server.backend,'rewrite_local',model):
                final=server.local_prompt({'guides':{'ref':str(guide)}},request(),seg,[photo],None)
            self.assertNotIn('adult performer',final)
            self.assertIn('banana mascot',model.call_args.args[2][0][1])
            seg['director_plan']['appearance_in']['characters']={}
            seg['director_plan']['appearance_out']['characters']={}
            with patch.object(server.backend,'rewrite_local',return_value=h3('A building in changing light. <Picture 1>. <Audio 1>: fully_copy.')):
                final=server.local_prompt({'guides':{'ref':str(guide)}},request(),seg,[photo],None)
            self.assertNotIn('BANANA_FACE_IDENTITY_V1',final)

    def test_first_picture_can_be_a_location_with_actor_identity_from_second(self):
        from banana_mv import server
        raw=treatment();raw['initial_state']['character_states']['S1']['identity_reference']=2
        raw['constraints']=['Image 1 defines the stage. S1 uses image 2 as character identity.']
        plan=validate_unified_plan(raw,timeline(),2)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);photo=root/'ref.png';Image.new('RGB',(8,8)).save(photo)
            guide=root/'guide.md';guide.write_text('H3 guide')
            seg=dict(timeline()[0],director_plan=plan['segments'][0],direction_constraints=plan['constraints'],
                     direction_closing_shot=plan['closing_shot'])
            with patch.object(server.backend,'rewrite_local',return_value=h3('S1 performs on the supplied stage. <Audio 1>: fully_copy.','<Subject 1> from <Picture 2>.')):
                result=server.local_prompt({'guides':{'ref':str(guide)}},request(),seg,[photo,photo],None)
            self.assertIn('same individual shown in <Picture 2>',result)
            self.assertNotIn('same individual shown in <Picture 1>',result)


class UnifiedWorkerTests(unittest.TestCase):
    def test_failure_resume_preserves_finished_video_and_commits_only_after_save(self):
        from banana_mv import server
        for mode,compiled in (('independent',False),('chain',False),('independent',True),('chain',True)):
            with self.subTest(mode=mode,compiled=compiled),tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
                root=Path(tmp);work=root/'abcdef123456';work.mkdir()
                photo=root/'ref.png';Image.new('RGB',(8,8)).save(photo)
                guide=root/'guide.md';guide.write_text('H3 guide')
                cfg={'comfy_input_dir':str(root),'guides':{'ref':str(guide)}}
                req=request(mode=mode);segs=timeline()
                if compiled:req['prompt_compiler_version']=1
                job={'id':work.name,'request':req,'segments':segs,'status':'running',
                     'size':[32,32],'images_comfy':['ref.png'],'seed':42,'duration':9,'output_size':[32,32]}
                lock=threading.Lock();lock.acquire();calls=[];graphs=[];downloads=[0]
                def rewrite(config,system,parts,token):
                    calls.append(system)
                    if system.startswith('Plan the supplied MV once'):
                        raw=treatment()
                        if compiled:
                            for row in raw['segments']:row['subjects']=['S1']
                        return json.dumps(raw)
                    task=json.loads(parts[0][1])
                    if compiled:return '[Shot 1] <Subject 1> '+task['visual_task']
                    return h3(task['visual_task']+' <Audio 1>: fully_copy.',
                              '<Subject 1> from '+task['appearance_start']['characters']['S1']['connected_reference']+'.')
                def download(config,item,dest):
                    downloads[0]+=1
                    if downloads[0]==2:raise RuntimeError('simulated download interruption')
                    dest.write_bytes(b'raw')
                def trim(source,dest,frames):dest.write_bytes(b'saved video')
                def last_frame(source,dest):Image.new('RGB',(8,8)).save(dest)
                for owner,name,value in [(server,'RUNS',root),(server,'GPU_LOCK',lock),
                    (server.backend,'DATA',root),(server.backend,'rewrite_local',Mock(side_effect=rewrite)),
                    (server,'audio_window',Mock()),(server,'preflight',Mock()),
                    (server.backend,'queue_prompt',Mock(side_effect=lambda c,g:graphs.append(g) or str(len(graphs)))),
                    (server,'wait_generation',Mock(return_value={'outputs':{'x':{'videos':[{'filename':'out.mp4'}]}}})),
                    (server.backend,'history_entry',Mock(return_value=None)),
                    (server.backend,'comfy_download',Mock(side_effect=download)),
                    (server,'trim_video',Mock(side_effect=trim)),(server,'last_frame',Mock(side_effect=last_frame)),
                    (server,'valid_part',Mock(side_effect=lambda p,s,size:p.is_file())),
                    (server,'assemble',Mock(side_effect=lambda p,a,d,*rest:d.write_bytes(b'final')))]:
                    stack.enter_context(patch.object(owner,name,value))
                server.worker(job,cfg,[photo],root/'song.wav',root/'song.wav')
                self.assertEqual(job['status'],'error',job.get('error'))
                self.assertEqual(len(json.loads((work/'scene_state.json').read_text())['commits']),1)
                first=(work/'00_part.mp4').read_bytes()
                lock.acquire();job.update(status='running',resuming=True)
                server.worker(job,cfg,[photo],root/'song.wav',root/'song.wav')
                self.assertEqual(job['status'],'done',job.get('error'))
                ledger=json.loads((work/'scene_state.json').read_text())
                self.assertEqual(len(ledger['commits']),3)
                self.assertEqual(ledger['commits'][2]['scene_state_out']['character_states']['S1']['garments']['coat']['current_status'],'placed')
                self.assertEqual((work/'00_part.mp4').read_bytes(),first)
                self.assertEqual(sum(s.startswith('Plan the supplied MV once') for s in calls),1)
                self.assertEqual(len(calls),4) # one whole-song plan, three plain writers
                self.assertEqual(graphs[0]['10']['inputs']['noise_seed'],42)
                self.assertEqual(graphs[-1]['12']['inputs']['steps'],8)
                self.assertEqual('first_frame' in graphs[-1]['7']['inputs'],mode=='chain')
                self.assertFalse(lock.locked())


if __name__=='__main__':unittest.main()

