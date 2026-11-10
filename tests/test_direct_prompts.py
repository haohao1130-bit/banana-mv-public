"""One upstream delivery; downstream renders its exact clip, including on resume."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from PIL import Image

from banana_mv import server
from banana_mv.story_plan import ensure_plan, validate_direct_prompts, direct_delivery
from banana_mv.scene_state import SceneStateError
from test_unified_direction import timeline, request


def delivery():
    return {'segments':[
        {'index':0,'event':'Opening identity changes once.','mode':'story',
         'prompt':'subject_definitions: <Subject 1> from <Picture 1>.\n'
                  'summary: SOURCE_OPENING_MARKER.\ndetailed_description: Shot 1: Transform once.\n'
                  'overall_soundscape: <Audio 1>: fully_copy.'},
        {'index':1,'event':'Already transformed, block the attack.','mode':'action',
         'prompt':'<Picture 2> is the current transformed hero. CURRENT_FIGHT_MARKER: '
                  'Shot 1: Block and counter. Keep <Audio 1>: fully_copy.'},
        {'index':2,'event':'Keep fighting.','mode':'action',
         'prompt':'<Picture 2> evades the next strike. <Audio 1>: fully_copy.'}],
        'closing_shot':'','ending_plan':None}


class DirectPromptTests(unittest.TestCase):
    def fixture(self,root,mode='independent'):
        images=[]
        for i in range(2):
            p=root/f'ref{i}.png';Image.new('RGB',(8,8)).save(p);images.append(p)
        guide=root/'guide.md';guide.write_text('OFFICIAL_NATIVE_GUIDE_MARKER')
        cfg={'guides':{'ref':str(guide)},'comfy_input_dir':str(root)}
        req=request(director_schema=4,scene_state_version=0,prompt_compiler_version=0,
                    project_scope='excerpt',mode=mode,rewrite_retries=0)
        return images,cfg,req

    def test_one_model_delivery_and_exact_downstream_without_format_policing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root)
            raw=delivery();model=Mock(return_value=json.dumps(raw))
            plan=ensure_plan(cfg,req,timeline(),images,root,model)
            self.assertEqual(model.call_count,1)
            self.assertNotIn('OFFICIAL_NATIVE_GUIDE_MARKER',model.call_args.args[1])
            self.assertIn('No downstream',model.call_args.args[1])
            self.assertTrue(plan['direct_prompts'])
            with patch.object(server.backend,'rewrite_local',side_effect=AssertionError('No downstream 9B')):
                for seg,row in zip(timeline(),plan['segments']):
                    prompt=server.local_prompt(cfg,req,dict(seg,director_plan=row),images,None)
                    self.assertEqual(prompt,raw['segments'][seg['index']]['prompt'])
                fight=server.local_prompt(cfg,req,dict(timeline()[1],director_plan=plan['segments'][1]),images,None)
            self.assertNotIn('SOURCE_OPENING_MARKER',fight)
            self.assertNotIn('Transform once',fight)
            self.assertIn('CURRENT_FIGHT_MARKER',fight)
            again=ensure_plan(cfg,req,timeline(),images,root,model)
            self.assertEqual(again,plan);self.assertEqual(model.call_count,1)

    def test_only_missing_delivery_and_unconnected_media_are_rejected(self):
        req={'project_scope':'excerpt'}
        for change in ('missing','blank','media'):
            raw=delivery()
            if change=='missing':raw['segments'].pop()
            elif change=='blank':raw['segments'][0]['prompt']=' '
            else:raw['segments'][0]['prompt']='<Picture 9>'
            with self.subTest(change=change),self.assertRaises(ValueError):
                validate_direct_prompts(raw,timeline(),2,req)

    def test_multiple_images_require_explicit_binding_not_unbound_story_translation(self):
        raw=delivery()
        raw['segments'][0]['prompt']='A named hero fights, obtains a prop and transforms. S1 acts.'
        with self.assertRaisesRegex(SceneStateError,'未綁定任何原始參考圖'):
            validate_direct_prompts(raw,timeline(),5,{'project_scope':'excerpt'})

    def test_source_cues_are_clipped_to_their_interval_before_directing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root)
            req['prompt']='@圖片1 is the first actor; @圖片2 is the successor.'
            req['srt_cues']=[{'start':1,'end':3,'text':'opening cue'},
                             {'start':5,'end':7,'text':'activation cue'},
                             {'start':7.5,'end':8.5,'text':'cross-boundary cue'}]
            model=Mock(return_value=json.dumps(delivery()))
            ensure_plan(cfg,req,timeline(),images,root,model)
            system=model.call_args.args[1];task=json.loads(model.call_args.args[2][0][1])
            self.assertNotIn('OFFICIAL_NATIVE_GUIDE_MARKER',system)
            self.assertNotIn('Return ONLY JSON',system)
            self.assertNotIn('segment_template',task)
            self.assertNotIn('srt',task)
            self.assertIn('<Picture 1>',task['brief'])
            self.assertEqual(task['timeline'][0]['local_srt'],[{'start':1,'end':3,'text':'opening cue'}])
            self.assertEqual(task['timeline'][1]['local_srt'][0],{'start':1,'end':3,'text':'activation cue'})
            self.assertEqual(task['timeline'][1]['local_srt'][1]['end'],4)
            self.assertEqual(task['timeline'][2]['local_srt'][0]['start'],0)
            self.assertIn('preserves causal order',system.lower())
            self.assertEqual(model.call_count,1)

    def test_plain_clip_blocks_preserve_prose_without_json_or_six_section_checks(self):
        raw='=== CLIP 0 action ===\n<Picture 1> blocks. "Quoted" text and {braces} stay literal.\n=== CLIP 1 story ===\n<Picture 2> fights; do not replay the opening.\n=== CLIP 2 action ===\n<Picture 2> holds the final image. <Audio 1>: fully_copy.\n=== END ==='
        req={'project_scope':'full'}
        plan=validate_direct_prompts(raw,timeline(),2,req)
        self.assertEqual(len(plan['segments']),3)
        self.assertEqual(plan['segments'][0]['prompt'],'<Picture 1> blocks. "Quoted" text and {braces} stay literal.')
        self.assertNotIn('opening',plan['segments'][0]['prompt'])
        self.assertIsNone(plan['ending_plan'])
        self.assertTrue(plan['ending_contract']['finish_work'])
        for broken in (raw.replace('=== END ===',''),raw.replace('=== CLIP 1 story ===',''),
                       raw+'\nMore unassigned output',raw.replace('CLIP 1 story','CLIP 0 story')):
            with self.subTest(raw=broken),self.assertRaises(ValueError):
                validate_direct_prompts(broken,timeline(),2,req)
        with self.assertRaisesRegex(SceneStateError,'不是空白'):
            direct_delivery('Let me analyze the entire story instead of delivering clip drafts.')

    def test_plain_delivery_retries_upstream_only_and_does_not_append_failed_long_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root)
            req['rewrite_retries']=1
            raw='\n'.join(f'=== CLIP {i} action ===\n<Picture 1> performs local beat {i}. <Audio 1>: fully_copy.' for i in range(3))+'\n=== END ==='
            bad='Let me analyze. '+('long failed analysis '*1000)
            model=Mock(side_effect=[bad,raw])
            plan=ensure_plan(cfg,req,timeline(),images,root,model)
            self.assertEqual(model.call_count,2)
            self.assertNotIn('long failed analysis',model.call_args.args[2][-1][1])
            self.assertIn('=== END ===',model.call_args.args[2][-1][1])
            self.assertEqual(plan['segments'][1]['prompt'],'<Picture 1> performs local beat 1. <Audio 1>: fully_copy.')

    def test_chain_offsets_are_supplied_upstream_not_rewritten_downstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=self.fixture(root,'chain')
            raw=delivery();raw['segments'][1]['prompt']='<Picture 1> is the prior frame; <Picture 3> is the hero.'
            model=Mock(return_value=json.dumps(raw))
            plan=ensure_plan(cfg,req,timeline(),images,root,model)
            task=json.loads(model.call_args.args[2][0][1])
            self.assertEqual([x['picture_offset'] for x in task['timeline']],[0,1,1])
            with patch.object(server.backend,'rewrite_local',side_effect=AssertionError('No rewrite')):
                got=server.local_prompt(cfg,req,dict(timeline()[1],director_plan=plan['segments'][1]),images,images[0])
            self.assertEqual(got,raw['segments'][1]['prompt'])

    def test_worker_failure_resume_keeps_one_plan_and_does_not_replay_completed_clip(self):
        for mode in ('independent','chain'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
                root=Path(tmp);images,cfg,req=self.fixture(root,mode)
                work=root/'abcdef123456';work.mkdir()
                job={'id':work.name,'request':req,'segments':timeline(),'status':'running',
                     'size':[32,32],'images_comfy':['ref0.png','ref1.png'],'seed':42,
                     'duration':9,'output_size':[32,32]}
                blocks='\n'.join(f'=== CLIP {r["index"]} {r["mode"]} ===\n'+r['prompt'] for r in delivery()['segments'])+'\n=== END ==='
                model=Mock(return_value=blocks);lock=threading.Lock();lock.acquire()
                downloads=[0];graphs=[]
                def download(config,item,dest):
                    downloads[0]+=1
                    if downloads[0]==2:raise RuntimeError('interrupted')
                    dest.write_bytes(b'raw')
                def queue(config,graph):graphs.append(copy.deepcopy(graph));return str(len(graphs))
                for owner,name,value in [(server,'RUNS',root),(server,'GPU_LOCK',lock),
                    (server.backend,'DATA',root),(server.backend,'rewrite_local',model),
                    (server,'preflight',Mock()),(server,'valid_part',lambda p,*a:p.is_file()),
                    (server,'audio_window',lambda src,dest,*a:dest.write_bytes(b'audio')),
                    (server.backend,'queue_prompt',queue),(server.backend,'history_entry',Mock(return_value=None)),
                    (server,'wait_generation',Mock(return_value={'outputs':{'x':{'videos':[{'filename':'out.mp4'}]}}})),
                    (server.backend,'comfy_download',download),
                    (server,'trim_video',lambda src,dest,*a:dest.write_bytes(b'part')),
                    (server,'last_frame',lambda src,dest:Image.new('RGB',(8,8)).save(dest)),
                    (server,'assemble',lambda parts,song,dest,*a:dest.write_bytes(b'final'))]:
                    stack.enter_context(patch.object(owner,name,value))
                server.worker(job,cfg,images,root/'song.wav',root/'song.wav')
                self.assertEqual(job['status'],'error');self.assertEqual(model.call_count,1)
                self.assertTrue(all((work/f'{i:02d}_prompt.txt').is_file() for i in range(3)))
                first=(work/'00_part.mp4').read_bytes()
                job['resuming']=True;lock.acquire()
                server.worker(job,cfg,images,root/'song.wav',root/'song.wav')
                self.assertEqual(job['status'],'done',job.get('error'))
                self.assertEqual(model.call_count,1)
                self.assertEqual((work/'00_part.mp4').read_bytes(),first)
                prompts=[g['7']['inputs']['prompt'] for g in graphs]
                self.assertEqual(prompts,[r['prompt'] for r in delivery()['segments'][:2]]+
                                 [r['prompt'] for r in delivery()['segments'][1:]])
                self.assertTrue(all(g['7']['inputs']['audio_mode']=='lock_source' for g in graphs))


if __name__=='__main__':unittest.main()
