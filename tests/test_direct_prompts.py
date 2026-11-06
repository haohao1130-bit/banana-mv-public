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
from banana_mv.story_plan import ensure_plan, validate_direct_prompts
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
            self.assertIn('OFFICIAL_NATIVE_GUIDE_MARKER',model.call_args.args[1])
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
                model=Mock(return_value=json.dumps(delivery()));lock=threading.Lock();lock.acquire()
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
