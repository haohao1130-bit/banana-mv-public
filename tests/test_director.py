import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from banana_mv.director import RECIPES, director_prompt, mode_candidates, resolve_modes
from banana_mv.story_plan import ensure_plan, plan_context, validate_plan


class DirectorTests(unittest.TestCase):
    def request(self, **changes):
        return dict({'director_version':2,'director':'auto','intensity':'extreme',
                     'prompt':'主唱在廢棄工廠演唱，武打與劇情交錯。'}, **changes)

    def test_exclusions_boundaries_and_auto_can_use_planned_mode(self):
        for text in ('不要武打，只要樂團演唱', '不加入武打，但有樂團演唱',
                     'No fighting or chase, but a band performance', "Don't add a fight; band performance",
                     'band performance instead of fighting'):
            req=self.request(prompt=text)
            self.assertNotIn('action',resolve_modes(req))
            self.assertIn('band',resolve_modes(req))
        self.assertNotIn('band',mode_candidates(self.request(prompt='bandwidth test'))[0])
        self.assertIn('action',mode_candidates(self.request(prompt='拳擊演唱'))[0])
        self.assertIn('action',mode_candidates(self.request(prompt='不要只演唱，要武打'))[0])
        self.assertEqual(resolve_modes(self.request(),{'director_plan':{'mode':'story'}})[0],'story')
        self.assertEqual(resolve_modes(self.request(director='dance')),['dance'])
        self.assertNotIn('action',resolve_modes(self.request(director='action',prompt='不要武打，樂團演唱')))

    def test_each_recipe_and_intensity_uses_actual_evidence(self):
        for mode in RECIPES:
            text,chosen=director_prompt(self.request(director=mode),15)
            self.assertEqual(chosen,mode)
            self.assertIn(RECIPES[mode],text)
            self.assertIn('waist-up or closer',text)
        req=self.request(director='action')
        low={'audio_evidence':{'relative_energy':'low','energy_change_db':0,'transient_candidates_s':[2,9]}}
        high={'audio_evidence':{'relative_energy':'high','energy_change_db':5,'transient_candidates_s':[2,9]}}
        self.assertIn('CINEMATIC CONTRAST',director_prompt(req,15,low)[0])
        text=director_prompt(req,15,high)[0]
        self.assertIn('local 9.00s',text)
        self.assertIn('reaction or aftermath',text)
        self.assertIn('Short window',director_prompt(req,4,high)[0])
        self.assertIn('rather than cuts',director_prompt(self.request(dynamic_cuts=False),15)[0])
        self.assertIn('NATURAL',director_prompt(self.request(intensity='normal'),15)[0])
        self.assertIn('HIGH:',director_prompt(self.request(intensity='high'),15)[0])
        self.assertNotIn('V2',director_prompt({'director':'action'},15)[0])

    def test_lora_follows_planned_primary_mode(self):
        from banana_mv.server import graph_options
        req=self.request()
        self.assertEqual(graph_options(req,15,{'director_plan':{'mode':'story'}})['director_mode'],'story')
        self.assertEqual(graph_options(req,15,{'director_plan':{'mode':'action'}})['director_mode'],'action')


class StoryPlanTests(unittest.TestCase):
    def setUp(self):
        self.req={'director_version':2,'director':'auto','prompt':'工廠演唱與武打劇情交錯'}
        self.segs=[{'index':0,'start':0,'seconds':4}, {'index':1,'start':4,'seconds':4}]
        self.plan={'segments':[{'index':0,'event':'The singer notices the challenger entering the factory.','mode':'story'},
                               {'index':1,'event':'The challenger attacks; the singer evades and counters to end the duel.','mode':'action'}]}

    def test_strict_plan_validation(self):
        wrapped='```json\n'+json.dumps(self.plan)+'\n```'
        self.assertEqual(len(validate_plan(wrapped,self.segs,self.req)['segments']),2)
        # The media timeline owns clip count and indices, not the model.
        for mutate in ('mode','empty'):
            bad=copy.deepcopy(self.plan)
            if mutate=='missing':bad['segments'].pop()
            elif mutate=='duplicate':bad['segments'][1]['event']=bad['segments'][0]['event']
            elif mutate=='indices':bad['segments'][1]['index']=0
            elif mutate=='mode':bad['segments'][1]['mode']='invalid-mode'
            else:bad['segments'][0]['event']=''
            with self.assertRaises(ValueError):validate_plan(bad,self.segs,self.req)
        with self.assertRaises(ValueError):validate_plan('not JSON',self.segs,self.req)
        self.assertEqual(len(validate_plan(self.plan,self.segs,dict(self.req,prompt='不要武打，工廠劇情'))['segments']),2) # generation rules are not semantic vetoes
        missing=copy.deepcopy(self.plan);missing['segments'].pop()
        self.assertEqual(len(validate_plan(missing,self.segs,self.req)['events']),1)
        wrong_indices=copy.deepcopy(self.plan);wrong_indices['segments'][1]['index']=99
        self.assertEqual(validate_plan(wrong_indices,self.segs,self.req)['segments'][1]['index'],1)
        duplicate=copy.deepcopy(self.plan);duplicate['segments'][1]['event']=duplicate['segments'][0]['event']
        self.assertEqual(len(validate_plan(duplicate,self.segs,self.req)['events']),2)

    def test_five_events_for_six_clips_are_completed_from_content(self):
        from banana_mv.core import segments
        segs=segments(60,10)
        actions=['The singer blocks the opening attack in the factory.',
                 'The singer slips to the side of the advancing opponent.',
                 'The opponent changes direction and throws another punch.',
                 'The singer drives the opponent back toward the factory wall.',
                 'The singer lands the final counter and returns to singing.']
        draft={'segments':[{'index':i,'event':event,'mode':'action'} for i,event in enumerate(actions)]}
        completion={'event':'The singer parries the punch and answers with a short body counter.','mode':'action'}
        rewrite=Mock(side_effect=[json.dumps(draft),json.dumps(completion)])
        with tempfile.TemporaryDirectory() as tmp:
            plan=ensure_plan({},self.req,segs,[],tmp,rewrite)
            self.assertEqual(len(plan['segments']),6)
            self.assertEqual(rewrite.call_count,2) # draft + one genuinely missing development
            events=[row['event'] for row in plan['segments']]
            self.assertIn(completion['event'],events)
            self.assertEqual(events[0],actions[0]);self.assertEqual(events[-1],actions[-1])
            self.assertIn('CONTENT-BASED COMPLETION TASK',rewrite.call_args.args[2][-1][1])
            self.assertNotIn('progress',json.dumps(plan))
            cached=ensure_plan({},self.req,segs,[],tmp,Mock(side_effect=AssertionError('must reuse completed content')))
            self.assertEqual(cached['segments'],plan['segments'])

    def test_one_whole_story_event_is_expanded_without_early_resolution(self):
        draft={'events':[{'event':'The singer fights in the factory, wins and returns to singing.','mode':'action'}]}
        rewrite=Mock(side_effect=[json.dumps(draft),json.dumps(self.plan['segments'][0]),json.dumps(self.plan['segments'][1])])
        with tempfile.TemporaryDirectory() as tmp:
            plan=ensure_plan({},self.req,self.segs,[],tmp,rewrite)
            self.assertEqual(len(plan['segments']),2)
            self.assertNotIn('wins',plan['segments'][0]['event'])
            self.assertIn('Only the final clip',rewrite.call_args_list[1].args[1])

    def test_excess_events_are_condensed_by_9b_in_order(self):
        draft={'events':[{'event':'Concrete factory story development '+letter,'mode':'story'} for letter in 'ABC']}
        summary={'event':'The singer responds to the disturbance, then signals to the challenger.','mode':'story'}
        rewrite=Mock(side_effect=[json.dumps(draft),json.dumps(summary)])
        with tempfile.TemporaryDirectory() as tmp:
            plan=ensure_plan({},self.req,self.segs,[],tmp,rewrite)
            self.assertEqual(len(plan['segments']),2)
            self.assertEqual(plan['segments'][0]['event'],draft['events'][0]['event'])
            self.assertEqual(plan['segments'][1]['event'],summary['event'])
            task=json.loads(rewrite.call_args.args[2][-1][1].split('CONTENT-BASED COMPLETION TASK:\n')[1])
            self.assertEqual(task['events_to_condense_here'],draft['events'][1:])

    def test_plan_cache_retry_and_changed_request_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            rewrite=Mock(side_effect=['bad format',json.dumps(self.plan)])
            first=ensure_plan({},self.req,self.segs,[],tmp,rewrite)
            self.assertEqual(rewrite.call_count,2)
            self.assertEqual(ensure_plan({},self.req,self.segs,[],tmp,Mock(side_effect=AssertionError('must reuse'))),first)
            with self.assertRaisesRegex(ValueError,'不符'):
                ensure_plan({},dict(self.req,prompt='別的故事'),self.segs,[],tmp,rewrite)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'全曲事件規劃失敗'):
                ensure_plan({},self.req,self.segs,[],tmp,Mock(return_value='broken'))
            self.assertFalse((Path(tmp)/'director_plan.json').exists())

    def test_context_tracks_intent_not_claimed_video_observations(self):
        seg={'director_plan':self.plan['segments'][1], 'previous_planned_event':self.plan['segments'][0]['event']}
        context=plan_context(seg)
        self.assertIn('not visually verified',context)
        self.assertIn('do not replay',context)

    def test_worker_plans_once_then_supplies_allocations_to_9b_and_h3(self):
        from PIL import Image
        from banana_mv import server
        from banana_mv.core import segments
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); job_id='abcdef123456';work=root/job_id;work.mkdir()
            photo=root/'photo.png';Image.new('RGB',(32,32)).save(photo)
            guide=root/'guide.md';guide.write_text('Write the H3 prompt.')
            cfg={'comfy_input_dir':str(root),'guides':{'ref':str(guide)}}
            segs=segments(8,4)
            for seg in segs:seg.update(song_seconds=8,segment_count=2)
            req=dict(self.req,mode='independent',rewrite=True,story_plan=True,audio_analysis=False,
                     face_identity=False,motion_lora=True,intensity='high')
            job={'id':job_id,'request':req,'status':'running','segments':segs,'size':[32,32],
                 'images_comfy':['photo.png'],'seed':0,'duration':8,'output_size':[32,32]}
            prompts=[];graphs=[]
            def rewrite(config,system,parts,token):
                texts=''.join(value for kind,value in parts if kind=='text')
                prompts.append(texts)
                if 'Allocate the user' in system:return json.dumps(self.plan)
                self.assertIn('CURRENT SEGMENT EVENT ALLOCATION',texts)
                return 'subject_definitions: <Picture 1> singer. <Audio 1>: fully_copy.\nsummary: '+self.plan['segments'][len(prompts)-2]['event']
            def queue(config,graph):graphs.append(graph);return 'mock'
            lock=threading.Lock();lock.acquire()
            with patch.object(server,'RUNS',root),patch.object(server,'GPU_LOCK',lock), \
                 patch.object(server.backend,'rewrite_local',side_effect=rewrite), \
                 patch.object(server,'audio_window'),patch.object(server,'preflight'), \
                 patch.object(server.backend,'queue_prompt',side_effect=queue), \
                 patch.object(server,'wait_generation',return_value={'outputs':{'video':{'images':[{'filename':'x.mp4'}]}}}), \
                 patch.object(server.backend,'comfy_download'),patch.object(server,'trim_video'),patch.object(server,'assemble'):
                server.worker(job,cfg,[photo],root/'song.wav',root/'song.wav')
            self.assertEqual(job['status'],'done',job.get('error'))
            self.assertEqual(len(prompts),3) # one full-song plan, two segment rewrites
            self.assertEqual(job['director_plan']['status'],'ready')
            self.assertTrue((work/'director_plan.json').is_file())
            self.assertIn('not visually verified',prompts[2])
            self.assertIn('CURRENT SEGMENT EVENT ALLOCATION',graphs[1]['7']['inputs']['prompt'])
            self.assertEqual(job['segments'][0]['director_mode'],'story')
            self.assertEqual(job['segments'][1]['director_mode'],'action')
            combat=[n for n in graphs[1].values() if n['class_type']=='LoraLoaderModelOnly'
                    and 'Combat' in n['inputs']['lora_name']]
            self.assertEqual(len(combat),1)
            self.assertFalse(lock.locked())
            # All clips survived: an assembly-only resume must not replan or rewrite.
            lock.acquire();job.update(status='running',resuming=True)
            with patch.object(server,'RUNS',root),patch.object(server,'GPU_LOCK',lock), \
                 patch.object(server,'valid_part',return_value=True),patch.object(server,'assemble'), \
                 patch.object(server,'ensure_plan',side_effect=AssertionError('must not replan')), \
                 patch.object(server.backend,'rewrite_local',side_effect=AssertionError('must not rewrite')):
                server.worker(job,cfg,[photo],root/'song.wav',root/'song.wav')
            self.assertEqual(job['status'],'done',job.get('error'))
            self.assertFalse(lock.locked())
