"""State-machine and persistence checks; these do not assert rendered-video correctness."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from banana_mv.scene_state import (initial_state,clip_input,plan_clip,commit_clip,save_clip,cached_clip,
                                  restore_clip_input,reconcile_history,ensure_scene_state,SceneStateError,
                                  state_context,digest,read_json,atomic_json)


def segments(n=5):
    return [{'index':i,'start':i*10,'seconds':10,'segment_count':n,'song_seconds':n*10,'model_frames':242,'frames':240} for i in range(n)]


def event(eid,description,ops=(),*,final=False,deps=(),repeat=False):
    return {'event_id':eid,'description':description,'allowed_operations':list(ops),
            'reserved_final':final,'repeatable':repeat,'depends_on':list(deps)}


def fixture():
    garments={g:{'garment_id':g,'garment_type':g,'material':'fabric','color':'black',
                 'current_status':'worn','current_location':'S1'} for g in ('coat','vest','skirt','opaque_base')}
    return {'initial_state':{'character_states':{'S1':{'identity_reference':1,'hairstyle':'short hair',
                    'garments':garments,'appearance_changes':[],'injuries':[],'held_props':[],'location':'stage'}},
             'environment_states':{'stage':{'active_location':'a stage','persistent_changes':[],
                                            'damaged_objects':{'table':'intact'},'prop_positions':{'cup':'table'}}}},
            'events':[event('intro','ongoing performance',('move','update'),repeat=True),
                      event('coat','remove coat',('remove',)),
                      event('vest','remove vest',('remove',),deps=('coat',)),
                      event('skirt','remove skirt',('remove',),deps=('vest',)),
                      event('final','finish the full song',final=True,deps=('skirt',))]}


def ledger_for(raw=None,segs=None):
    state,cat=initial_state(raw or fixture(),segs or segments(),1)
    return {'version':1,'initial_state':state,'event_catalog':cat,'commits':[],'visual_verified':False}


def response(eids,changes=(),prompt='A purposeful visual event with a different camera angle.'):
    return {'clip_prompt':prompt,'planned_events':list(eids),'completed_events':list(eids),'state_transitions':list(changes)}


def garment(gid,before='worn',after='removed',eid=None,operation='remove'):
    return {'kind':'garment','subject_id':'S1','garment_id':gid,'from':before,'to':after,
            'current_location':'floor','event_id':eid or gid,'operation':operation}


class SceneStateTests(unittest.TestCase):
    def test_a_progressive_wardrobe_never_resets_and_inputs_can_be_restored(self):
        ledger=ledger_for();segs=segments()
        with tempfile.TemporaryDirectory() as work:
            actions=[response(['intro']),response(['coat'],[garment('coat')]),
                     response(['vest'],[garment('vest')]),response(['skirt'],[garment('skirt')]),response(['final'])]
            for i,(seg,raw) in enumerate(zip(segs,actions)):
                incoming=clip_input(ledger,seg)
                record=plan_clip(raw,incoming,ledger['event_catalog'],seg)
                save_clip(work,record)
                self.assertEqual(restore_clip_input(work,i),incoming)
                self.assertEqual(len(ledger['commits']),i) # planning alone never advances the ledger
                commit_clip(work,ledger,record)
                self.assertFalse(record['visual_verified'])
                self.assertEqual(len(ledger['commits']),i+1)
            out=ledger['commits'][-1]['scene_state_out']['character_states']['S1']
            self.assertEqual(out['current_outfit'],['opaque_base'])
            self.assertEqual(set(out['removed_garments']),{'coat','vest','skirt'})
            for gid in ('coat','vest','skirt'):self.assertEqual(out['garments'][gid]['current_status'],'removed')
            saved=read_json(Path(work)/'scene_state.json')
            self.assertEqual(saved,ledger)
            self.assertEqual(restore_clip_input(work,2)['character_states']['S1']['removed_garments'],['coat'])
            self.assertEqual(cached_clip(work,ledger,segs[2])['scene_state_in'],restore_clip_input(work,2))

    def test_no_redress_without_explicit_event_permission(self):
        ledger=ledger_for();state=clip_input(ledger,segments()[0]);state['timeline'].update(current_clip_index=1,current_start_time=10,current_end_time=20)
        state=plan_clip(response(['coat'],[garment('coat')]),state,ledger['event_catalog'],segments()[1])['scene_state_out']
        state['timeline'].update(current_clip_index=2,current_start_time=20,current_end_time=30)
        for operation in ('update','dress'):
            with self.assertRaises(SceneStateError):
                plan_clip(response(['intro'],[garment('coat','removed','worn',eid='intro',operation=operation)]),
                          state,ledger['event_catalog'],segments()[2])
        ledger['event_catalog']['redress']={'description':'explicitly put coat back on','repeatable':False,
            'reserved_final':False,'depends_on':['coat'],'allowed_operations':['dress']}
        out=plan_clip(response(['redress'],[garment('coat','removed','worn',eid='redress',operation='dress')]),state,ledger['event_catalog'],segments()[2])
        self.assertIn('coat',out['scene_state_out']['character_states']['S1']['current_outfit'])

    def test_b_completed_combat_events_cannot_replay(self):
        raw=fixture();raw['events']=[event('A_attack','A attacks'),event('A_retreat','A is driven back',deps=['A_attack']),
            event('turn_B','turn to B',deps=['A_retreat']),event('B_down','B falls',deps=['turn_B']),
            event('end','final resolution',final=True,deps=['B_down'])]
        ledger=ledger_for(raw)
        with tempfile.TemporaryDirectory() as work:
            for seg,eid in zip(segments(),['A_attack','A_retreat','turn_B','B_down','end']):
                state=clip_input(ledger,seg)
                if seg['index']==2:
                    with self.assertRaisesRegex(SceneStateError,'不得重播'):
                        plan_clip(response(['A_attack']),state,ledger['event_catalog'],seg)
                record=plan_clip(response([eid]),state,ledger['event_catalog'],seg);commit_clip(work,ledger,record)
            self.assertEqual(ledger['commits'][-1]['scene_state_out']['narrative_states']['completed_events'],
                             ['A_attack','A_retreat','turn_B','B_down','end'])

    def test_vehicle_exit_is_inherited_without_repeating_entry_or_exit(self):
        raw=fixture();raw['initial_state']['character_states']['S1']['location']='driver_seat'
        raw['events']=[event('exit_car','leave the car and stand outside',ops=['move']),
            event('walk_away','walk away from the parked car',ops=['move'],deps=['exit_car']),
            event('end','song ends',final=True,deps=['walk_away'])]
        ledger=ledger_for(raw,segs=segments(3));segs=segments(3)
        def move(before,after,eid):
            return {'kind':'character','subject_id':'S1','field':'location','from':before,
                    'to':after,'event_id':eid,'operation':'move'}
        with tempfile.TemporaryDirectory() as work:
            first=plan_clip(response(['exit_car'],[move('driver_seat','outside_car','exit_car')]),
                            clip_input(ledger,segs[0]),ledger['event_catalog'],segs[0])
            commit_clip(work,ledger,first)
            incoming=clip_input(ledger,segs[1])
            self.assertEqual(incoming['character_states']['S1']['location'],'outside_car')
            self.assertEqual(incoming['narrative_states']['previous_clip_events'],[{
                'event_id':'exit_car','description':'leave the car and stand outside',
                'completed_in_previous_clip':True}])
            self.assertEqual(incoming['narrative_states']['previous_clip_transitions'],first['state_transitions'])
            with self.assertRaisesRegex(SceneStateError,'不得重播'):
                plan_clip(response(['exit_car']),incoming,ledger['event_catalog'],segs[1])
            second=plan_clip(response(['walk_away'],[move('outside_car','pavement','walk_away')]),
                             incoming,ledger['event_catalog'],segs[1])
            commit_clip(work,ledger,second)
            self.assertEqual(clip_input(ledger,segs[2])['character_states']['S1']['location'],'pavement')

    def test_c_destruction_and_different_cameras_are_independent(self):
        raw=fixture();raw['events']=[event('topple','table is knocked over',ops=['damage']),
            event('walk','walk around table',repeat=True),event('end','end',final=True)]
        ledger=ledger_for(raw);segs=segments(4)
        change={'kind':'environment','scene_id':'stage','field':'damaged_objects','from':{'table':'intact'},
                'to':{'table':'toppled'},'event_id':'topple','operation':'damage'}
        with tempfile.TemporaryDirectory() as work:
            for i,seg in enumerate(segs):
                incoming=clip_input(ledger,seg)
                raw=response(['topple'] if i==0 else ['end'] if i==3 else ['walk'],[change] if i==0 else [],
                             ['low angle 24mm','overhead 50mm','close-up 85mm','wide static'][i])
                record=plan_clip(raw,incoming,ledger['event_catalog'],seg);commit_clip(work,ledger,record)
                self.assertEqual(record['scene_state_out']['environment_states']['stage']['damaged_objects']['table'],'toppled')
                self.assertEqual(record['clip_prompt'],raw['clip_prompt'])
            self.assertNotIn('camera',ledger['commits'][-1]['scene_state_out'])

    def test_final_events_cannot_start_or_complete_early_and_dependencies_are_structural(self):
        ledger=ledger_for();state=clip_input(ledger,segments()[0]);state['timeline'].update(current_clip_index=3,current_start_time=30,current_end_time=40)
        for done in ([],['final']):
            with self.assertRaises(SceneStateError):
                plan_clip(dict(response(['final']),completed_events=done),state,ledger['event_catalog'],segments()[3])
        with self.assertRaisesRegex(SceneStateError,'前置'):
            plan_clip(response(['vest']),state,ledger['event_catalog'],segments()[3])
        state['timeline'].update(current_clip_index=4,current_start_time=40,current_end_time=50)
        with self.assertRaisesRegex(SceneStateError,'最終段'):
            plan_clip(response(['intro']),state,ledger['event_catalog'],segments()[-1])

    def test_rejects_snapshot_reset_stale_from_identity_and_unbound_changes(self):
        ledger=ledger_for();seg=segments()[0];incoming=clip_input(ledger,seg)
        bads=[response(['intro'],[dict(garment('coat'),event_id='missing')]),
              response(['coat'],[garment('coat',before='removed')]),
              response(['intro'],[{'kind':'character','subject_id':'S1','field':'identity_reference',
                                  'from':1,'to':2,'event_id':'intro','operation':'update'}]),
              dict(response(['intro']),scene_state_out={})]
        for bad in bads:
            with self.assertRaises(SceneStateError):plan_clip(bad,incoming,ledger['event_catalog'],seg)
        self.assertEqual(incoming,clip_input(ledger,seg)) # validation never mutates committed input

    def test_draft_does_not_commit_and_rewind_invalidates_downstream_without_deleting_history(self):
        ledger=ledger_for();segs=segments()
        with tempfile.TemporaryDirectory() as work:
            draft=plan_clip(response(['intro']),clip_input(ledger,segs[0]),ledger['event_catalog'],segs[0])
            save_clip(work,draft)
            self.assertEqual(len(ledger['commits']),0)
            self.assertIsNotNone(cached_clip(work,ledger,segs[0]))
            commit_clip(work,ledger,draft)
            second=plan_clip(response(['coat'],[garment('coat')]),clip_input(ledger,segs[1]),ledger['event_catalog'],segs[1]);commit_clip(work,ledger,second)
            segs[0]['status']='done';segs[1]['status']='done'
            job={'segments':segs}
            (Path(work)/'00_part.mp4').write_bytes(b'old-first')
            (Path(work)/'01_part.mp4').write_bytes(b'old-second')
            self.assertEqual(reconcile_history(job,work,ledger,lambda s:s['index']!=0),0)
            self.assertEqual(ledger['commits'],[])
            self.assertFalse((Path(work)/'00_part.mp4').exists())
            self.assertFalse((Path(work)/'01_part.mp4').exists())
            self.assertEqual(len(list(Path(work).glob('*_part_history_*.mp4'))),2)
            self.assertTrue(all(s['refresh_prompt'] for s in segs))
            self.assertTrue(list(Path(work).glob('scene_state_history_*.json')))
            self.assertEqual(restore_clip_input(work,1),second['scene_state_in'])
            moved={'kind':'character','subject_id':'S1','field':'location','from':'stage','to':'side_stage','event_id':'intro','operation':'move'}
            redone=plan_clip(response(['intro'],[moved]),clip_input(ledger,segs[0]),ledger['event_catalog'],segs[0]);save_clip(work,redone);commit_clip(work,ledger,redone)
            self.assertTrue(list(Path(work).glob('00_scene_state_history_*.json')))
            segs[1].pop('refresh_prompt')
            self.assertIsNone(cached_clip(work,ledger,segs[1]))

    def test_initialization_persists_once_retries_format_and_does_not_reinitialize_on_resume(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);image=root/'ref.png';Image.new('RGB',(16,16)).save(image)
            req={'prompt':'a changing costume and moving prop','scene_state_version':1}
            with patch('banana_mv.services.rewrite_local',side_effect=['bad JSON',json.dumps(fixture())]) as model:
                ledger=ensure_scene_state({},req,segments(),[image],root,model)
                self.assertEqual(model.call_count,2)
                loaded=ensure_scene_state({},req,segments(),[image],root,model)
                self.assertEqual(model.call_count,2);self.assertEqual(loaded,ledger)
                with self.assertRaises(SceneStateError):ensure_scene_state({},dict(req,prompt='changed'),segments(),[image],root,model)
            self.assertEqual(state_context(clip_input(ledger,segments()[0]),ledger['event_catalog'],True).count('<Picture 2>'),1)

    def test_garment_and_event_initial_schema_is_checked(self):
        for update in ('cycle','image','garment'):
            raw=fixture()
            if update=='cycle':raw['events'][0]['depends_on']=['intro']
            if update=='image':raw['initial_state']['character_states']['S1']['identity_reference']=9
            if update=='garment':raw['initial_state']['character_states']['S1']['garments']['coat']['current_status']='unknown'
            with self.assertRaises(SceneStateError):initial_state(raw,segments(),1)

    def test_actual_local_rewriter_receives_state_and_outputs_canonical_snapshot_without_extra_judge(self):
        from PIL import Image
        from banana_mv import server
        ledger=ledger_for();seg=segments()[1]
        incoming=clip_input(ledger,dict(seg,index=0))
        # Run the removal clip with a supplied canonical input, without requiring a last-frame image.
        incoming['timeline'].update(current_clip_index=1,current_start_time=10,current_end_time=20)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);image=root/'ref.png';Image.new('RGB',(16,16)).save(image)
            guide=root/'guide.md';guide.write_text('base guide')
            req={'prompt':'The referenced performer changes a costume over the full song.','rewrite':True,
                 'optimizer_version':1,'face_identity':True,'scene_state_version':1}
            draft=json.dumps(response(['coat'],[garment('coat')],prompt='The performer removes the coat in an independent close-up.'))
            with patch.object(server.backend,'rewrite_local',return_value=draft) as model:
                prompt=server.local_prompt({'guides':{'ref':str(guide)}},req,seg,[image],None,
                                          scene_input=incoming,event_catalog=ledger['event_catalog'])
            self.assertEqual(model.call_count,1)
            context='\n'.join(v for kind,v in model.call_args.args[2] if kind=='text')
            self.assertIn('scene_state_in',context);self.assertIn('current_outfit',context)
            self.assertIn('PERSISTENT STATE OUTPUT CONTRACT',model.call_args.args[1])
            self.assertEqual(seg['scene_state_debug']['scene_state_out']['character_states']['S1']['garments']['coat']['current_status'],'removed')
            self.assertIn('[BANANA_PERSISTENT_SCENE_STATE_V1]',prompt)
            self.assertIn('facial identity only',prompt)
            self.assertNotIn('distinctive features and clothing across cuts',prompt)
            self.assertFalse(seg['scene_state_debug']['visual_verified'])

    def test_ongoing_events_can_span_clips_without_being_marked_completed(self):
        ledger=ledger_for();seg=segments()[0];state=clip_input(ledger,seg)
        raw=response(['coat'],[garment('coat',after='unfastened')]);raw['completed_events']=[]
        record=plan_clip(raw,state,ledger['event_catalog'],seg)
        self.assertEqual(record['scene_state_out']['narrative_states']['current_event'],'coat')
        continued=response(['coat'],[garment('coat',before='unfastened')])
        incoming=deepcopy(record['scene_state_out']);incoming['timeline'].update(current_clip_index=1,current_start_time=10,current_end_time=20)
        out=plan_clip(continued,incoming,ledger['event_catalog'],segments()[1])
        self.assertIn('coat',out['scene_state_out']['narrative_states']['completed_events'])

    def test_worker_commits_only_saved_media_and_resume_reuses_exact_draft(self):
        from contextlib import ExitStack
        from PIL import Image
        from banana_mv import server
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);work=root/'runs'/'123456789abc';work.mkdir(parents=True)
            inputs=root/'input';inputs.mkdir();photo=root/'ref.png';Image.new('RGB',(16,16)).save(photo)
            guide=root/'guide.md';guide.write_text('base H3 guide');song=root/'song.wav';song.write_bytes(b'audio')
            segs=segments(2)
            req={'prompt':'The performer moves to the side stage, then finishes the song.',
                 'scene_state_version':1,'persistent_scene_state':True,'rewrite':True,'story_plan':False,
                 'audio_analysis':False,'mode':'independent','optimizer_version':1,'director_version':2,
                 'director':'performance','intensity':'high','sampling_steps':8}
            job={'id':'123456789abc','status':'running','request':req,'segments':segs,'size':(1280,736),
                 'output_size':(1280,720),'duration':20,'seed':42,'images_comfy':['ref.png'],'title':'test'}
            raw=fixture();raw['events']=[event('move','move to the side stage',ops=['move']),event('end','finish song',final=True,deps=['move'])]
            move={'kind':'character','subject_id':'S1','field':'location','from':'stage','to':'side_stage','event_id':'move','operation':'move'}
            replies=[json.dumps(raw),json.dumps(response(['move'],[move],'A lateral tracking shot follows the performer.')),
                     json.dumps(response(['end'],prompt='A close-up concludes the source song.'))]
            def create_audio(*args):Path(args[1]).write_bytes(b'slice')
            def download(cfg,info,path):path.write_bytes(b'raw')
            def trim(src,path,frames):path.write_bytes(b'part')
            def assemble(parts,audio,dest,*args):dest.write_bytes(b'final')
            cfg={'guides':{'ref':str(guide)},'comfy_input_dir':str(inputs)}
            def media_ok(path,seg,size):return Path(path).is_file() and Path(path).read_bytes()==b'part'
            with ExitStack() as stack:
                stack.enter_context(patch.object(server,'RUNS',root/'runs'))
                stack.enter_context(patch.object(server.backend,'DATA',root))
                model=stack.enter_context(patch.object(server.backend,'rewrite_local',side_effect=replies))
                stack.enter_context(patch.object(server,'preflight'))
                stack.enter_context(patch.object(server,'audio_window',side_effect=create_audio))
                stack.enter_context(patch.object(server.backend,'queue_prompt',return_value='pid'))
                history=stack.enter_context(patch.object(server.backend,'history_entry',return_value={'status':{'completed':True}}))
                waiting=stack.enter_context(patch.object(server,'wait_generation',side_effect=[{},RuntimeError('mock sampling failure'),{}]))
                stack.enter_context(patch.object(server,'video_info',return_value={}))
                stack.enter_context(patch.object(server.backend,'comfy_download',side_effect=download))
                stack.enter_context(patch.object(server,'trim_video',side_effect=trim))
                stack.enter_context(patch.object(server,'assemble',side_effect=assemble))
                stack.enter_context(patch.object(server,'valid_part',side_effect=media_ok))
                self.assertTrue(server.GPU_LOCK.acquire(blocking=False))
                server.worker(job,cfg,[photo],song,song)
                self.assertEqual(job['status'],'error');self.assertIn('mock sampling failure',job['error'])
                ledger=read_json(work/'scene_state.json');self.assertEqual(len(ledger['commits']),1)
                failed=read_json(work/'01_scene_state.json');self.assertEqual(failed['status'],'planned')
                self.assertEqual(failed['scene_state_in']['character_states']['S1']['location'],'side_stage')
                self.assertEqual(failed['scene_state_in']['narrative_states']['previous_clip_events'][0]['event_id'],'move')
                self.assertTrue(failed['scene_state_in']['narrative_states']['previous_clip_events'][0]['completed_in_previous_clip'])
                self.assertEqual(model.call_count,3)
                # Resume the failed clip: the source input and already prepared prompt/state pair are reused.
                job.update(status='running',resuming=True);job.pop('error',None)
                job['segments'][1]['status']='waiting'
                job['segments'][1]['scene_state_prompt_sha256']='stale result from another prompt'
                self.assertTrue(server.GPU_LOCK.acquire(blocking=False))
                server.worker(job,cfg,[photo],song,song)
                self.assertEqual(job['status'],'done',job.get('error'))
                self.assertEqual(model.call_count,3) # no reinitialization and no repeated state advancement
                ledger=read_json(work/'scene_state.json');self.assertEqual(len(ledger['commits']),2)
                self.assertEqual(restore_clip_input(work,1),failed['scene_state_in'])
                self.assertEqual(job['scene_state_summary']['committed_clips'],2)
                self.assertEqual(waiting.call_count,3)
                history.assert_not_called() # never reuse a stale GPU result with another prompt hash
                for call in model.call_args_list[1:]:
                    contents='\n'.join(v for kind,v in call.args[2] if kind=='text')
                    self.assertNotIn('previous final frame',contents)
                self.assertEqual(ledger['commits'][-1]['scene_state_out']['narrative_states']['reserved_final_events'],[])
                # Emulate a hard crash after media was saved but before the final state commit.
                ledger['commits']=ledger['commits'][:1];atomic_json(work/'scene_state.json',ledger)
                last=read_json(work/'01_scene_state.json');last['status']='planned';atomic_json(work/'01_scene_state.json',last)
                job.update(status='running',resuming=True)
                self.assertTrue(server.GPU_LOCK.acquire(blocking=False))
                server.worker(job,cfg,[photo],song,song)
                self.assertEqual(job['status'],'done',job.get('error'))
                self.assertEqual(model.call_count,3);self.assertEqual(waiting.call_count,3)
                self.assertEqual(len(read_json(work/'scene_state.json')['commits']),2)
                self.assertEqual(job['scene_state_summary']['committed_clips'],2)


    def test_invalid_state_retry_is_bounded_and_terminal_scene_does_not_leak_early(self):
        from PIL import Image
        from banana_mv import server
        ledger=ledger_for();seg=segments()[0];incoming=clip_input(ledger,seg)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);photo=root/'ref.png';Image.new('RGB',(16,16)).save(photo)
            guide=root/'guide.md';guide.write_text('H3 guide')
            bad=json.dumps(response(['final'],prompt='CUT TO BLACK'))
            good=json.dumps(response(['intro'],prompt='A naturally ending medium shot of the ongoing performance.'))
            req={'prompt':'performance with a final resolution','rewrite':True,'optimizer_version':1}
            with patch.object(server.backend,'rewrite_local',side_effect=[bad,good]) as model:
                prompt=server.local_prompt({'guides':{'ref':str(guide)}},req,seg,[photo],None,
                                          scene_input=incoming,event_catalog=ledger['event_catalog'])
            self.assertEqual(model.call_count,2)
            self.assertNotIn('CUT TO BLACK',prompt)
            self.assertEqual(seg['scene_state_debug']['completed_events'],['intro'])
            with patch.object(server.backend,'rewrite_local',return_value=bad) as model:
                with self.assertRaises(SceneStateError):
                    server.local_prompt({'guides':{'ref':str(guide)}},req,seg,[photo],None,
                                        scene_input=incoming,event_catalog=ledger['event_catalog'])
            self.assertEqual(model.call_count,2)
            self.assertEqual(ledger['commits'],[])
            self.assertIn('scene_state_in',seg['scene_state_attempt'])

    def test_operation_permissions_and_direct_removal_into_hand(self):
        ledger=ledger_for();seg=segments()[0];state=clip_input(ledger,seg)
        with self.assertRaisesRegex(SceneStateError,'remove'):
            plan_clip(response(['intro'],[garment('coat',eid='intro',operation='move')]),state,ledger['event_catalog'],seg)
        record=plan_clip(response(['coat'],[garment('coat',after='held')]),state,ledger['event_catalog'],seg)
        self.assertNotIn('coat',record['scene_state_out']['character_states']['S1']['current_outfit'])
        self.assertIn('coat',record['scene_state_out']['character_states']['S1']['removed_garments'])

    def test_corrupted_cached_input_and_ledger_output_are_not_silently_accepted(self):
        ledger=ledger_for();seg=segments()[0]
        with tempfile.TemporaryDirectory() as work:
            record=plan_clip(response(['intro']),clip_input(ledger,seg),ledger['event_catalog'],seg)
            save_clip(work,record);commit_clip(work,ledger,record)
            changed=read_json(Path(work)/'00_scene_state.json');changed['scene_state_in']['character_states']['S1']['location']='wrong'
            atomic_json(Path(work)/'00_scene_state.json',changed)
            with self.assertRaises(SceneStateError):cached_clip(work,ledger,seg)
            ledger['commits'][0]['scene_state_out']['character_states']['S1']['location']='wrong'
            with self.assertRaises(SceneStateError):clip_input(ledger,segments()[1])

    def test_mascot_wardrobe_is_optional_and_reference_numbering_preserves_originals(self):
        raw=fixture();raw['initial_state']['character_states']['S2']={'identity_reference':2,'garments':{},'location':'stage'}
        state,catalog=initial_state(raw,segments(),2)
        self.assertEqual(state['character_states']['S2']['garments'],{})
        self.assertIn('<Picture 3>',state_context(state,catalog,True))
        bad=fixture();bad['initial_state']['character_states']['lead']=bad['initial_state']['character_states'].pop('S1')
        with self.assertRaises(SceneStateError):initial_state(bad,segments(),1)
