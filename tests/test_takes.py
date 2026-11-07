"""Batch retakes reuse prompts and preserve media/ledgers on failed generation."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from banana_mv import server as app
from banana_mv import takes
from banana_mv import masters


class TakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.work=self.root/'abcdef123456';self.work.mkdir()
        (self.root/'input').mkdir();(self.work/'sources').mkdir()
        (self.work/'sources'/'image.png').write_bytes(b'image')
        (self.work/'sources'/'song.wav').write_bytes(b'original song')
        (self.work/'sources'/'vocal.wav').write_bytes(b'isolated vocal')
        self.cfg={'comfy_input_dir':str(self.root/'input')}
        self.job={'id':self.work.name,'status':'done','created':1,'seed':42,'size':[32,32],'output_size':[32,32],
            'duration':4,'images_comfy':['image.png'],'video':'old-video',
            'request':{'mode':'independent','sampling_steps':8,'director':'performance','intensity':'normal','motion_lora':False},
            'sources':{'images':['sources/image.png'],'song':'sources/song.wav','drive':'sources/vocal.wav'},
            'segments':[{'index':i,'start':i,'seconds':1,'frames':24,'model_frames':39,'status':'done','prompt':f'fixed story {i}'} for i in range(4)]}
        for i in range(4):
            (self.work/f'{i:02d}_part.mp4').write_bytes(f'old{i}'.encode())
            (self.work/f'{i:02d}_prompt.txt').write_text(f'fixed story {i}')
            (self.work/f'{i:02d}_scene_state.json').write_bytes(b'original planned scene state')
        (self.work/'final.mp4').write_bytes(b'old master')
        (self.work/'scene_state.json').write_bytes(b'original planned ledger')
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.thread=Mock();self.assemble=Mock(side_effect=self.join)
        for owner,name,value in [(app,'RUNS',self.root),(app,'GPU_LOCK',threading.Lock()),(app,'CANCEL',set()),
            (app.backend,'DATA',self.root),(app.backend,'load_config',Mock(return_value=self.cfg)),
            (app.backend,'comfy',Mock(return_value={})),(app,'preflight',Mock()),
            (app,'valid_part',Mock(side_effect=lambda p,*a:p.is_file())),
            (app,'audio_window',Mock(side_effect=lambda s,d,*a:d.write_bytes(b'audio'))),
            (app.backend,'queue_prompt',Mock(side_effect=lambda *a:str(app.backend.queue_prompt.call_count))),
            (app,'wait_generation',Mock(return_value={'outputs':{'x':{'videos':[{'filename':'out.mp4'}]}}})),
            (app.backend,'comfy_download',Mock(side_effect=lambda c,i,d:d.write_bytes(b'new'))),
            (app,'trim_video',Mock(side_effect=lambda src,dst,*a:shutil.copyfile(src,dst))),
            (app,'last_frame',Mock(side_effect=lambda src,dst:dst.write_bytes(b'frame'))),
            (app,'assemble',self.assemble),(takes.threading,'Thread',self.thread),
            (app.backend,'rewrite_local',Mock(side_effect=AssertionError('must not rewrite story')))]:
            self.stack.enter_context(patch.object(owner,name,value))
        app.write_state(self.job)

    def join(self,parts,song,dest,*a):dest.write_bytes(b'|'.join(p.read_bytes() for p in parts))

    def run_background(self):
        call=self.thread.call_args
        call.kwargs['target'](*call.kwargs['args'])
        self.assertFalse(app.GPU_LOCK.locked())
        return app.read_state(self.job['id'])

    def test_multi_select_only_renders_selected_and_assembles_once(self):
        result=takes.retake(self.job['id'],[2,1,2])
        self.assertEqual(result['retake']['indices'],[1,2])
        job=self.run_background()
        self.assertEqual(job['status'],'done');self.assertEqual(job['retake']['status'],'done')
        self.assertEqual(app.backend.queue_prompt.call_count,2);self.assemble.assert_called_once()
        self.assertEqual((self.work/'00_part.mp4').read_bytes(),b'old0')
        self.assertEqual((self.work/'03_part.mp4').read_bytes(),b'old3')
        self.assertEqual((self.work/'final.mp4').read_bytes(),b'old0|new|new|old3')
        self.assertEqual((self.work/'scene_state.json').read_bytes(),b'original planned ledger')
        for i in (1,2):
            seg=job['segments'][i];self.assertNotEqual(seg['render_seed'],42+i)
            self.assertEqual((takes.take_dir(job,i,'original')/'part.mp4').read_bytes(),f'old{i}'.encode())
            self.assertEqual((self.work/f'{i:02d}_scene_state.json').read_bytes(),b'original planned scene state')
        self.assertIn('&v=',job['video'])
        windows=app.audio_window.call_args_list
        self.assertEqual([c.args[0] for c in windows],[self.work/'sources/vocal.wav']*2)
        self.assertEqual([c.args[2] for c in windows],[1,2])
        for call in app.backend.queue_prompt.call_args_list:
            graph=call.args[1]
            self.assertEqual(graph['7']['inputs']['drive_audio'],['6',0])
            self.assertEqual(graph['7']['inputs']['audio_mode'],'lock_source')
            self.assertEqual(graph['7']['inputs']['audio_denoise_strength'],0)

    def test_failed_second_render_keeps_old_master_and_completed_candidate(self):
        app.wait_generation.side_effect=[{'outputs':{'x':{'videos':[{'filename':'out.mp4'}]}}},RuntimeError('GPU failed')]
        takes.retake(self.job['id'],[1,2]);job=self.run_background()
        self.assertEqual(job['retake']['status'],'error');self.assemble.assert_not_called()
        self.assertEqual(job['segments'][1]['takes'][-1]['status'],'ready')
        self.assertEqual(job['segments'][2]['takes'][-1]['status'],'error')
        self.assertEqual((self.work/'01_part.mp4').read_bytes(),b'old1')
        self.assertEqual((self.work/'final.mp4').read_bytes(),b'old master')
        candidate=job['segments'][1]['takes'][-1]['id']
        takes.select_take(job['id'],1,candidate);selected=self.run_background()
        self.assertEqual(selected['segments'][1]['selected_take'],candidate)
        self.assertEqual(app.backend.queue_prompt.call_count,2) # adoption needs no GPU render

    def test_failed_assembly_does_not_replace_current_clips(self):
        self.assemble.side_effect=RuntimeError('ffmpeg failed')
        takes.retake(self.job['id'],[1,2]);job=self.run_background()
        self.assertEqual(job['retake']['status'],'error')
        for i in range(4):self.assertEqual((self.work/f'{i:02d}_part.mp4').read_bytes(),f'old{i}'.encode())
        self.assertEqual((self.work/'final.mp4').read_bytes(),b'old master')

    def test_stop_keeps_completed_take_and_does_not_queue_remaining(self):
        def stop(*a):
            app.CANCEL.add(self.job['id'])
            return {'outputs':{'x':{'videos':[{'filename':'out.mp4'}]}}}
        app.wait_generation.side_effect=stop
        takes.retake(self.job['id'],[1,2]);job=self.run_background()
        self.assertEqual(app.backend.queue_prompt.call_count,1)
        self.assertEqual(job['segments'][1]['takes'][-1]['status'],'ready')
        self.assertEqual(job['segments'][2]['takes'][-1]['status'],'cancelled')
        self.assertEqual((self.work/'01_part.mp4').read_bytes(),b'old1')

    def test_chain_selected_neighbors_use_new_previous_take(self):
        self.job['request']['mode']='chain';app.write_state(self.job)
        takes.retake(self.job['id'],[1,2]);job=self.run_background()
        sources=[c.args[0] for c in app.last_frame.call_args_list]
        self.assertEqual(sources[0],self.work/'00_part.mp4')
        first=job['segments'][1]['selected_take']
        self.assertEqual(sources[1],takes.take_dir(job,1,first)/'part.mp4')
        self.assertEqual(job['segments'][2]['takes'][-1]['previous_take'],first)
        self.assertEqual((self.work/'03_part.mp4').read_bytes(),b'old3')

    def test_legacy_render_settings_are_recovered_before_retaking(self):
        del self.job['request']['sampling_steps'];app.write_state(self.job)
        (self.work/'00_workflow_api.json').write_text(json.dumps({
            'schedule':{'class_type':'BasicScheduler','inputs':{'steps':6}},
            'attention':{'class_type':'ModelAttentionBackend','inputs':{}}}))
        takes.retake(self.job['id'],[1]);job=self.run_background()
        graph=app.backend.queue_prompt.call_args.args[1]
        self.assertEqual(graph['12']['inputs']['steps'],6)
        self.assertTrue(job['request']['kitchen_attention'])
        self.assertFalse(job['request']['sparse_attention'])

    def test_revert_original_reassembles_without_rewriting_or_sampling(self):
        takes.retake(self.job['id'],[1]);self.run_background()
        takes.select_take(self.job['id'],1,'original');job=self.run_background()
        self.assertEqual((self.work/'01_part.mp4').read_bytes(),b'old1')
        self.assertEqual(job['segments'][1]['render_seed'],43)
        self.assertEqual(app.backend.queue_prompt.call_count,1)
        self.assertEqual(self.assemble.call_count,2)
        app.backend.rewrite_local.assert_not_called()

    def test_invalid_indices_paths_and_busy_queue_do_not_change_project(self):
        for indices in ([],[True],[-1],[4],['1']):
            with self.subTest(indices=indices),self.assertRaises(ValueError):takes.retake(self.job['id'],indices)
            self.assertFalse(app.GPU_LOCK.locked())
        for index,take_id in ((-1,'original'),(1,'../part.mp4'),(1,'deadbeef0000')):
            with self.assertRaises(ValueError):takes.select_take(self.job['id'],index,take_id)
            self.assertFalse(app.GPU_LOCK.locked())
        app.backend.comfy.return_value={'queue_running':[{}]}
        with self.assertRaisesRegex(ValueError,'佇列'):takes.retake(self.job['id'],[1])
        self.assertEqual(app.read_state(self.job['id']),self.job)

    def test_partial_project_retakes_without_claiming_finished_master(self):
        self.job['status']='error';self.job['segments'][3]['status']='waiting'
        (self.work/'03_part.mp4').unlink();app.write_state(self.job)
        takes.retake(self.job['id'],[1]);job=self.run_background()
        self.assertEqual(job['status'],'error');self.assertTrue(job['final_stale'])
        self.assertNotIn('video',job);self.assemble.assert_not_called()

    def test_preview_serves_silent_trimmed_part_without_audio_processing(self):
        source=takes.preview(self.job,1)
        self.assertEqual(source,self.work/'01_part.mp4')
        self.assertEqual(source.read_bytes(),b'old1')
        app.audio_window.assert_not_called()
        self.assemble.assert_not_called()

    def configure_repair(self):
        guide=self.root/'guide.md';guide.write_text('NATIVE_GUIDE')
        self.cfg.update(guides={'ref':str(guide)},rewriter={'model':'9b'})

    def test_local_correction_only_changes_selected_prompt_and_revert_restores_it(self):
        self.configure_repair()
        with patch.object(takes,'repair_prompt',return_value='fixed story 1 with closer hands') as repair:
            takes.retake(self.job['id'],[1,2],{'1':'Only add a hand insert.','2':'  '})
            job=self.run_background()
        repair.assert_called_once()
        self.assertEqual(repair.call_args.args[3],'fixed story 1')
        self.assertEqual(job['segments'][1]['prompt'],'fixed story 1 with closer hands')
        self.assertEqual(job['segments'][2]['prompt'],'fixed story 2')
        self.assertEqual((self.work/'01_prompt.txt').read_text(),'fixed story 1 with closer hands')
        takes.retake(self.job['id'],[1]);job=self.run_background()
        self.assertEqual(app.backend.queue_prompt.call_args.args[1]['7']['inputs']['prompt'],'fixed story 1 with closer hands')
        takes.select_take(self.job['id'],1,'original');job=self.run_background()
        self.assertEqual(job['segments'][1]['prompt'],'fixed story 1')
        self.assertEqual((self.work/'01_prompt.txt').read_text(),'fixed story 1')

    def test_failed_local_rewrite_keeps_current_master_and_prompt(self):
        self.configure_repair()
        with patch.object(takes,'repair_prompt',side_effect=RuntimeError('9B failed')):
            takes.retake(self.job['id'],[1],{'1':'Stronger expression.'});job=self.run_background()
        app.backend.queue_prompt.assert_not_called()
        self.assertEqual(job['retake']['status'],'error')
        self.assertEqual((self.work/'01_prompt.txt').read_text(),'fixed story 1')
        self.assertEqual((self.work/'final.mp4').read_bytes(),b'old master')

    def test_master_versions_keep_first_second_and_reverted_complete_movies(self):
        takes.retake(self.job['id'],[1]);job=self.run_background()
        self.assertEqual(job['current_master'],2)
        self.assertEqual((self.work/'final_v001.mp4').read_bytes(),b'old master')
        second=(self.work/'final_v002.mp4').read_bytes()
        self.assertEqual(second,(self.work/'final.mp4').read_bytes())
        takes.select_take(self.job['id'],1,'original');job=self.run_background()
        self.assertEqual(job['current_master'],3)
        self.assertEqual((self.work/'final_v002.mp4').read_bytes(),second)
        self.assertEqual((self.work/'final_v003.mp4').read_bytes(),(self.work/'final.mp4').read_bytes())
        self.assertEqual(masters.source(job,self.work,'1'),self.work/'final_v001.mp4')
        described=takes.describe(job)
        self.assertEqual(described['final_video'],str(self.work/'final.mp4'))
        self.assertIn('version=1',described['final_versions'][0]['download'])
        for value in ('../final.mp4','0','999'):
            with self.assertRaises(ValueError):masters.source(job,self.work,value)

    def test_invalid_correction_payload_does_not_change_project(self):
        for notes in ([],{'2':'unselected'},{'1':123},{'1':'x'*3001}):
            with self.subTest(notes=str(notes)[:40]),self.assertRaises(ValueError):
                takes.retake(self.job['id'],[1],notes)
            self.assertFalse(app.GPU_LOCK.locked())
            self.assertEqual(app.read_state(self.job['id']),self.job)

    def test_repair_model_sees_only_current_prompt_notes_and_local_references(self):
        from PIL import Image
        self.configure_repair()
        image=self.root/'actual.png';Image.new('RGB',(8,8)).save(image)
        self.job['request']['prompt']='WHOLE_STORY_SECRET_FINAL_END'
        self.job['segments'][0]['shoot_setup']='FUTURE_SETUP_SECRET'
        dest=self.root/'repair';dest.mkdir()
        with patch.object(app.backend,'rewrite_local',return_value='<Picture 1> UPDATED_NATIVE <Audio 1>: fully_copy.') as model:
            result=takes.repair_prompt(self.cfg,self.job,self.job['segments'][0],'LOCAL_ORIGINAL','LOCAL_CORRECTION',[image],None,dest)
        text=model.call_args.args[1]+model.call_args.args[2][0][1]
        self.assertIn('LOCAL_ORIGINAL',text);self.assertIn('LOCAL_CORRECTION',text)
        self.assertNotIn('WHOLE_STORY_SECRET_FINAL_END',text);self.assertNotIn('FUTURE_SETUP_SECRET',text)
        self.assertIn('UPDATED_NATIVE',result)
        self.assertTrue((dest/'repair_raw.txt').is_file())


class PreviewHTTPTests(unittest.TestCase):
    def test_script_launcher_and_take_routes_share_the_same_server_locks(self):
        import os
        import subprocess
        import sys
        script='''import runpy, sys
from unittest.mock import patch
def check():
    from banana_mv import takes
    server=sys.modules['banana_mv.server']
    assert takes.app is server
    assert takes.app.GPU_LOCK is server.GPU_LOCK
with patch('http.server.ThreadingHTTPServer') as http:
    http.return_value.serve_forever.side_effect=check
    runpy.run_path(SERVER_PATH,run_name='__main__')
'''.replace('SERVER_PATH',repr(app.__file__))
        with tempfile.TemporaryDirectory() as tmp:
            result=subprocess.run([sys.executable,'-c',script],env={**os.environ,'BANANA_DATA':tmp},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_silent_preview_real_ffmpeg_range_head_and_safe_routes(self):
        import urllib.request
        import urllib.error
        from banana_mv.core import command, probe
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'RUNS',Path(tmp)):
            work=Path(tmp)/'abcdef123456';work.mkdir()
            command(['ffmpeg','-y','-v','error','-f','lavfi','-i','color=c=navy:s=32x32:r=24:d=1',
                     '-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-threads','1',
                     '-c:a','aac','-shortest',work/'raw.mp4'])
            app.trim_video(work/'raw.mp4',work/'00_part.mp4',24)
            streams=probe(work/'00_part.mp4')['streams']
            self.assertEqual([s['codec_type'] for s in streams],['video'])
            job={'id':work.name,'status':'done','seed':42,'request':{},'segments':[
                {'index':0,'start':0,'seconds':1,'status':'done'}]}
            app.write_state(job)
            shutil.copyfile(work/'00_part.mp4',work/'final.mp4')
            shutil.copyfile(work/'00_part.mp4',work/'final_v001.mp4')
            job['final_versions']=[{'version':1,'file':'final_v001.mp4'}];app.write_state(job)
            http=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
            thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{http.server_port}'
            try:
                url=base+f'/api/mv/clip?id={job["id"]}&index=0'
                with urllib.request.urlopen(url) as r:
                    self.assertEqual(r.read(),(work/'00_part.mp4').read_bytes())
                    self.assertEqual(r.headers['Content-Type'],'video/mp4')
                with urllib.request.urlopen(urllib.request.Request(url,headers={'Range':'bytes=0-15'})) as r:
                    self.assertEqual(r.status,206);self.assertEqual(len(r.read()),16)
                with urllib.request.urlopen(urllib.request.Request(url,method='HEAD')) as r:
                    self.assertEqual(r.status,200);self.assertEqual(r.read(),b'')
                for suffix in ('&take=../raw.mp4','&take=deadbeef0000'):
                    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(url+suffix)
                    self.assertEqual(error.exception.code,400)
                with urllib.request.urlopen(base+f'/api/mv/status?id={job["id"]}') as r:
                    status=json.load(r);self.assertIn('preview',status['segments'][0])
                with urllib.request.urlopen(base+'/clip_review.js') as r:self.assertIn(b'renderClipPreviews',r.read())
                master=base+f'/api/mv/file?id={job["id"]}&version=1'
                with urllib.request.urlopen(master) as r:self.assertEqual(r.read(),(work/'final_v001.mp4').read_bytes())
                with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(master.replace('version=1','version=../raw.mp4'))
            finally:http.shutdown();http.server_close();thread.join()


if __name__=='__main__':unittest.main()

