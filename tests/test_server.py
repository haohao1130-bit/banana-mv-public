"""HTTP + worker integration with a mocked Comfy GPU; real uploads/ffmpeg/files.

Standalone backend integration. This does not test GPU.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from banana_mv.core import command

class ServerIntegration(unittest.TestCase):
    def test_both_modes_over_http_with_mock_gpu(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);inp=root/'input';inp.mkdir()
            (root/'config.json').write_text(json.dumps({'comfy_input_dir':str(inp)}))
            sys.modules.pop('banana_mv.server',None)
            from banana_mv import server as app
            data_patch=patch.object(app.backend,'DATA',root);data_patch.start();self.addCleanup(data_patch.stop)
            library_patch=patch.object(app.backend,'LIBRARY',root/'library');library_patch.start();self.addCleanup(library_patch.stop)
            runs_patch=patch.object(app,'RUNS',root/'banana_mv');runs_patch.start();self.addCleanup(runs_patch.stop)
            app.RUNS.mkdir()
            cfg=app.backend.load_config()
            song=root/'song.wav'
            command(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=5.152','-ac','2',song])
            photo=root/'photo.png';Image.new('RGB',(128,96),'orange').save(photo)
            # Exercise final prompt handling on both rewrite paths and both reference layouts.
            guide=root/'guide.md';guide.write_text('Reference generation guide')
            prompt_cfg=dict(cfg,guides={'ref':str(guide)})
            from banana_mv.core import normalize_mv_prompt
            for rewrite in (False,True):
                for tail in (None,photo):
                    req={'prompt':'@圖片2 場景；主角武打','director':'action','rewrite':rewrite}
                    segment={'seconds':15,'model_frames':362}
                    raw_prompt='subject_definitions:\n<Subject 1> performs. <Video 1> uses <Audio 1>.'
                    with patch.object(app.backend,'rewrite_local',return_value=raw_prompt):
                        final=app.local_prompt(prompt_cfg,req,segment,[photo,photo,photo],tail)
                        main=2 if tail else 1
                        self.assertIn(f'same individual shown in <Picture {main}>',final)
                        self.assertEqual(final.count('[BANANA_FACE_IDENTITY_V1]'),1)
                        self.assertTrue(final.endswith('[/BANANA_FACE_IDENTITY_V1]'))
                        self.assertNotIn('<Video',final)
                        normalize_mv_prompt(final,3+int(bool(tail)))
                        req['face_identity']=False
                        baseline=app.local_prompt(prompt_cfg,req,segment,[photo,photo,photo],tail)
                        self.assertNotIn('[BANANA_FACE_IDENTITY_V1]',baseline)
                        if rewrite:
                            expected=normalize_mv_prompt(raw_prompt,3+int(bool(tail)))+'\n\n'+app.director_prompt(req,15)[0]
                            self.assertEqual(baseline,expected)
                    if rewrite:
                        with patch.object(app.backend,'rewrite_local',return_value=' '):
                            with self.assertRaisesRegex(ValueError,'空白'):
                                app.local_prompt(prompt_cfg,req,segment,[photo,photo,photo],tail)
            raw=root/'mock_gpu.mp4'
            command(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=navy:s=1280x736:r=24:d=6',
                     '-c:v','libx264','-threads','1',raw])
            captured=[]
            saved_jobs=[]
            def comfy(config,path,*args,**kwargs):
                if path=='/queue':return {}
                if path=='/object_info':
                    from banana_mv.core import build_workflow,MODELS,MOTION_LORAS
                    g=build_workflow('a','b',128,96,124,'',1,'c',director_mode='action')
                    info={n['class_type']:{'input':{'required':{}}} for n in g.values()}
                    info['UNETLoader']['input']['required']['unet_name']=[[MODELS['unet']]]
                    info['CLIPLoader']['input']['required']['clip_name']=[[MODELS['clip']]]
                    info['VAELoader']['input']['required']['vae_name']=[[MODELS['video_vae'],MODELS['audio_vae']]]
                    info['LoraLoaderModelOnly']['input']['required']['lora_name']=[list(MOTION_LORAS.values())]
                    info['ModelAttentionBackend']['input']['required']['attention']=[['pytorch attention','comfy kitchen attention']]
                    return info
                raise AssertionError(path)
            def queue(config,w):captured.append(w);return str(len(captured))
            def history(*args):return {'status':{'completed':True},'outputs':{'16':{'images':[{'filename':'mock.mp4'}]}}}
            def download(config,item,dest):shutil.copyfile(raw,dest)
            http=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
            threading.Thread(target=http.serve_forever,daemon=True).start()
            base=f'http://127.0.0.1:{http.server_port}'
            def post(path,data,headers=None):
                request=urllib.request.Request(base+path,data=data,headers=headers or {'Content-Type':'application/json'})
                with urllib.request.urlopen(request) as r:return json.load(r)
            try:
                with patch.object(app.backend,'comfy',side_effect=comfy),patch.object(app.backend,'queue_prompt',side_effect=queue),\
                     patch.object(app.backend,'history_entry',side_effect=history),patch.object(app.backend,'comfy_download',side_effect=download):
                    self.assertEqual(app.graph_options({'prompt':'武打','director':'auto'},15)['director_mode'],'action')
                    with self.assertRaisesRegex(ValueError,'布林'):
                        app.graph_options({'acceleration':'false'},15)
                    with self.assertRaisesRegex(ValueError,'fal 真人 LoRA 已移除'):
                        app.graph_options({'realism_lora':True},15)
                    for old in (False,True):
                        opts=app.graph_options({'acceleration':old},15)
                        self.assertEqual(opts['kitchen_attention'],old)
                        self.assertEqual(opts['sparse_attention'],old)
                    from banana_mv.core import build_workflow
                    graph=build_workflow('a','b',1280,736,362,'',1,director_mode='action')
                    info=comfy(cfg,'/object_info')
                    info['ModelAttentionBackend']['input']['required']['attention']=[['pytorch attention']]
                    with patch.object(app.backend,'comfy',return_value=info):
                        with self.assertRaisesRegex(ValueError,'Kitchen'):
                            app.preflight(cfg,graph)
                    info=comfy(cfg,'/object_info')
                    info['LoraLoaderModelOnly']['input']['required']['lora_name']=[[]]
                    with patch.object(app.backend,'comfy',return_value=info):
                        with self.assertRaisesRegex(ValueError,'尚未下載模型'):
                            app.preflight(cfg,graph)
                    with urllib.request.urlopen(base+'/') as r:self.assertIn('大乘蕉宗MV製作所'.encode(),r.read())
                    with urllib.request.urlopen(base+'/api/health') as r:self.assertTrue(json.load(r)['standalone'])
                    with self.assertRaises(urllib.error.HTTPError) as err:
                        urllib.request.urlopen(base+'/toybox')
                    self.assertEqual(err.exception.code,404)
                    image=post('/api/upload',photo.read_bytes(),{'X-Filename':'photo.png'})
                    audio=post('/api/upload',song.read_bytes(),{'X-Filename':'song.wav'})
                    for mode,count,legacy in [('independent',1,True),('chain',1,True),('independent',3,False),('chain',3,False)]:
                        captured.clear()
                        req={'image_id':image['id'],'song_id':audio['id'],'mode':mode,
                             'aspect':'16:9','width':1280,'segment_seconds':4,'rewrite':False,'seed':42,
                             'lyrics':'全曲語意參考','srt_reference':'1\n00:00:00,000 --> 00:00:02,000\n時間參考歌詞',
                             'realism_lora':False,'realism_strength':0.6,
                             'kitchen_attention':True,'sparse_attention':mode=='chain'}
                        if mode=='chain' and legacy:
                            req['audio_analysis']=False
                        if not legacy:
                            req.pop('image_id')
                            req['image_ids']=[image['id']]*count
                            req['prompt']='@圖片1 主唱，@圖片2 角度，@圖片3 舞台'
                        job=post('/api/mv/start',json.dumps(req).encode());saved_jobs.append(job['id'])
                        for _ in range(300):
                            current=app.read_state(job['id'])
                            if current['status'] in ('done','error'):break
                            time.sleep(.1)
                        self.assertEqual(current['status'],'done',current.get('error'))
                        self.assertEqual(current['request']['scene_state_version'],0)
                        self.assertEqual(current['request']['director_schema'],5)
                        self.assertFalse((app.job_dir(job['id'])/'scene_state.json').exists())
                        self.assertEqual(current['request']['srt_reference'],req['srt_reference'])
                        self.assertEqual(current['request']['srt_cues'][0]['text'],'時間參考歌詞')
                        self.assertEqual(Path(current['output_video']).parent,root/'videos')
                        self.assertEqual(Path(current['output_video']).read_bytes(),(app.job_dir(job['id'])/'final.mp4').read_bytes())
                        self.assertEqual(len(captured),2)
                        enabled=req.get('audio_analysis',True)
                        self.assertEqual((app.job_dir(job['id'])/'audio_analysis.json').is_file(),enabled)
                        self.assertEqual('audio_evidence' in current['segments'][0],enabled)
                        self.assertEqual('AUDIO-RESPONSIVE DIRECTION' in captured[0]['7']['inputs']['prompt'],enabled)
                        self.assertEqual('first_frame' in captured[1]['7']['inputs'],mode=='chain')
                        for graph in captured:
                            self.assertIn('attention_backend',graph)
                            self.assertEqual('sparse_attention' in graph,mode=='chain')
                            self.assertNotIn('realism_people',graph)
                            self.assertFalse(graph['7']['inputs']['prompt'].startswith('r34l1sm, '))
                            self.assertEqual(len([k for k in graph['7']['inputs'] if k.startswith('ref_images.')]),count)
                        if not legacy:
                            offset=1 if mode=='chain' else 0
                            self.assertIn(f'<Picture {2+offset}> 角度',captured[1]['7']['inputs']['prompt'])
                        with urllib.request.urlopen(base+current['video']) as r:self.assertGreater(len(r.read()),1000)
                        request=urllib.request.Request(base+current['video'],headers={'Range':'bytes=0-31'})
                        with urllib.request.urlopen(request) as r:
                            self.assertEqual(r.status,206);self.assertEqual(len(r.read()),32)
                        from banana_mv.core import probe
                        stream=next(s for s in probe(app.job_dir(job['id'])/'final.mp4')['streams'] if s['codec_type']=='video')
                        self.assertEqual((stream['width'],stream['height']),(1280,720))
                        # Worker releases its GPU lock in a finally block immediately after saving status.
                        for _ in range(100):
                            if not app.GPU_LOCK.locked():break
                            time.sleep(.01)
                    # Reconnect from saved project without using the library index or reuploading.
                    index_file=app.backend.LIBRARY/'library.json';old_index=index_file.read_bytes()
                    index_file.write_text('[]')
                    try:
                        for job_id in saved_jobs[:2]:
                            previous=app.read_state(job_id)
                            self.assertEqual(previous['request']['lyrics'],'全曲語意參考')
                            self.assertEqual(previous['request']['srt_cues'][0]['start'],0)
                            work=app.job_dir(job_id);original_part=(work/'00_part_v1.mp4').read_bytes()
                            (work/'01_part_v1.mp4').unlink();(work/'final.mp4').unlink()
                            previous['segments'][1]['status']='generating'
                            previous['segments'][1].pop('prompt_id',None)
                            previous.update(status='interrupted',error='simulated restart')
                            app.write_state(previous)
                            with patch.object(app.backend,'comfy',return_value={'queue_pending':['busy']}):
                                with self.assertRaises(ValueError):app.resume(job_id)
                            self.assertFalse(app.GPU_LOCK.locked())
                            captured.clear()
                            post('/api/mv/resume',json.dumps({'id':job_id,'rewrite_retries':2}).encode())
                            for _ in range(300):
                                resumed=app.read_state(job_id)
                                if resumed['status'] in ('done','error'):break
                                time.sleep(.1)
                            self.assertEqual(resumed['status'],'done',resumed.get('error'))
                            self.assertEqual(resumed['request']['rewrite_retries'],2)
                            self.assertEqual(len(captured),1)
                            self.assertIn('attention_backend',captured[0])
                            self.assertEqual('sparse_attention' in captured[0],previous['request']['sparse_attention'])
                            self.assertNotIn('realism_people',captured[0])
                            self.assertEqual((work/'00_part_v1.mp4').read_bytes(),original_part)
                            self.assertEqual('first_frame' in captured[0]['7']['inputs'],previous['request']['mode']=='chain')
                            for _ in range(100):
                                if not app.GPU_LOCK.locked():break
                                time.sleep(.01)
                            with urllib.request.urlopen(base+'/api/mv/projects') as response:
                                listing=json.load(response)
                            self.assertEqual(len(listing),4)
                            self.assertEqual(next(r for r in listing if r['id']==job_id)['completed'],2)
                            with urllib.request.urlopen(base+'/api/mv/reference?id='+job_id+'&image=0') as response:
                                self.assertGreater(len(response.read()),0)
                            with self.assertRaises(ValueError):app.resume(job_id) # Cannot resume an already finished job.
                            # All video parts survived, only assembly failed: merge without any new GPU submission.
                            resumed.update(status='error',error='assembly failed');app.write_state(resumed)
                            (work/'final.mp4').unlink();captured.clear()
                            post('/api/mv/resume',json.dumps({'id':job_id}).encode())
                            for _ in range(300):
                                merged=app.read_state(job_id)
                                if merged['status'] in ('done','error'):break
                                time.sleep(.1)
                            self.assertEqual(merged['status'],'done',merged.get('error'))
                            self.assertEqual(captured,[])
                            for _ in range(100):
                                if not app.GPU_LOCK.locked():break
                                time.sleep(.01)

                    finally:
                        index_file.write_bytes(old_index)
                    guide=root/'guide.txt';guide.write_text('H3 reference guide')
                    cfg['guides']['ref']=str(guide)
                    green=root/'green.png';blue=root/'blue.png'
                    Image.new('RGB',(128,96),'green').save(green)
                    Image.new('RGB',(128,96),'blue').save(blue)
                    with patch.object(app.backend,'rewrite_local',return_value='rewritten') as rewrite:
                        app.local_prompt(cfg,{'prompt':'@圖片2 場景','rewrite':True},
                                         {'seconds':5,'model_frames':124},[photo,green],blue)
                        parts=rewrite.call_args.args[2]
                        pics=[im for kind,im in parts if kind=='image']
                        self.assertEqual([im.getpixel((0,0)) for im in pics],[(0,0,255),(255,165,0),(0,128,0)])
                        self.assertIn('<Picture 3> 場景',parts[0][1])
            finally:
                http.shutdown();http.server_close()
