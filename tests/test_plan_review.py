"""Plan-only MV review and approval; real saved allocation, simulated models/GPU."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from banana_mv import server
import test_shoot_plan as fixtures
from test_unified_direction import timeline


class PlanReviewTests(unittest.TestCase):
    def setUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        root=Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.root=root;self.images,self.cfg,self.req=fixtures.ShootPlanTests().fixture(root)
        self.req['plan_review']=True
        self.work=root/'abcdef123456';self.work.mkdir()
        self.job={'id':self.work.name,'request':self.req,'segments':timeline(),'status':'running',
                  'size':[32,32],'images_comfy':['ref0.png','ref1.png'],'seed':42,
                  'duration':9,'output_size':[32,32]}
        self.lock=threading.Lock()
        self.model=Mock(return_value=fixtures.allocation())
        self.queue=Mock(return_value='pid')
        for obj,name,value in [(server,'RUNS',root),(server,'GPU_LOCK',self.lock),
                (server.backend,'rewrite_local',self.model),(server.backend,'load_config',Mock(return_value=self.cfg)),
                (server.backend,'comfy',Mock(return_value={})),(server,'preflight',Mock()),
                (server,'project_inputs',Mock(return_value=(self.images,root/'song.wav',root/'song.wav'))),
                (server.backend,'queue_prompt',self.queue)]:
            self.stack.enter_context(patch.object(obj,name,value))

    def plan(self):
        self.lock.acquire()
        server.worker(self.job,self.cfg,self.images,self.root/'song.wav',self.root/'song.wav')
        self.assertEqual(self.job['status'],'plan_ready',self.job.get('error'))
        self.assertFalse(self.lock.locked());self.queue.assert_not_called()

    def test_plan_only_persists_all_events_and_never_calls_clip_writer_or_h3(self):
        with patch.object(server,'local_prompt') as writer,patch.object(server,'audio_window') as audio:
            self.plan();writer.assert_not_called();audio.assert_not_called()
        self.assertEqual(self.model.call_count,1)
        saved=server.read_state(self.job['id'])
        self.assertEqual(saved['plan_revision'],server.plan_revision(saved))
        self.assertIn('CURRENT_COUNTER',saved['segments'][1]['director_plan']['event'])
        self.assertTrue(saved['plan_preview_setup'])
        self.assertEqual(saved['segments'][0]['fixed_reference_settings'],saved['plan_preview_setup'])
        self.assertFalse(list(self.work.glob('*_workflow*.json')))

    def test_approval_reuses_exact_plan_and_only_then_generates_clips(self):
        self.plan();original=copy.deepcopy(self.job['segments'])
        with patch.object(server.threading,'Thread') as thread:
            approved=server.open_furnace(self.job['id'],self.job['plan_revision'])
            thread.return_value.start.assert_called_once()
        self.assertTrue(self.lock.locked());self.assertEqual(approved['segments'],original)
        self.assertEqual(approved['seed'],42);self.queue.assert_not_called()
        with self.assertRaisesRegex(ValueError,'已有 MV'):server.open_furnace(self.job['id'],self.job['plan_revision'])
        with ExitStack() as stack:
            for obj,name,value in [(server,'ensure_plan',Mock(side_effect=AssertionError('replanned'))),
                    (server,'local_prompt',Mock(side_effect=[fixtures.native_prompt(i) for i in range(3)])),
                    (server,'valid_part',lambda p,*_:p.is_file()),
                    (server,'audio_window',lambda src,dest,*_:dest.write_bytes(b'audio')),
                    (server,'wait_generation',Mock(return_value={})),(server,'video_info',Mock(return_value={})),
                    (server.backend,'comfy_download',lambda c,i,d:d.write_bytes(b'raw')),
                    (server,'trim_video',lambda s,d,*_:d.write_bytes(b'part')),
                    (server,'assemble',lambda p,s,d,*_:d.write_bytes(b'final')),
                    (server,'export_finished_video',Mock())]:
                stack.enter_context(patch.object(obj,name,value))
            server.worker(approved,self.cfg,self.images,self.root/'song.wav',self.root/'song.wav')
        self.assertEqual(approved['status'],'done',approved.get('error'))
        self.assertEqual(self.queue.call_count,3);self.assertEqual(self.model.call_count,1)
        self.assertFalse(self.lock.locked())
        with self.assertRaises(ValueError):server.open_furnace(self.job['id'],self.job['plan_revision'])

    def test_stale_or_tampered_plan_cannot_open(self):
        self.plan()
        with self.assertRaisesRegex(ValueError,'更新'):server.open_furnace(self.job['id'],'stale')
        self.assertFalse(self.lock.locked())
        p=self.work/'director_plan.json';data=json.loads(p.read_text());data['shared_setup']='changed';p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'更新'):server.open_furnace(self.job['id'],self.job['plan_revision'])
        self.queue.assert_not_called();self.assertFalse(self.lock.locked())

    def test_failed_launch_preserves_ready_plan_and_releases_lock(self):
        self.plan()
        with patch.object(server.threading,'Thread') as thread:
            thread.return_value.start.side_effect=RuntimeError('cannot start')
            with self.assertRaises(RuntimeError):server.open_furnace(self.job['id'],self.job['plan_revision'])
        saved=server.read_state(self.job['id']);self.assertEqual(saved['status'],'plan_ready')
        self.assertNotIn('plan_approved',saved);self.assertFalse(self.lock.locked())

    def test_cancelled_unapproved_job_resume_stops_at_review_again(self):
        self.plan();self.job.update(status='cancelled',resuming=True)
        self.lock.acquire();server.worker(self.job,self.cfg,self.images,self.root/'song.wav',self.root/'song.wav')
        self.assertEqual(self.job['status'],'plan_ready');self.assertEqual(self.model.call_count,1)
        self.queue.assert_not_called()

    def test_invalid_review_setting_or_disabled_rewriter_fails_before_start(self):
        for value in ('yes',1,None):
            with self.assertRaisesRegex(ValueError,'布林'):server.start({'plan_review':value})
        with self.assertRaisesRegex(ValueError,'本地提示詞改寫'):
            server.start({'plan_review':True,'rewrite':False})

    def test_start_review_checks_only_rewriter_and_saves_review_mode(self):
        self.cfg['rewriter']={'model':'local-9b'}
        (self.root/'song.wav').write_bytes(b'song')
        def asset(key):
            return {'kind':'audio','file':'song.wav','name':'song'} if key=='song' else {
                'kind':'image','file':self.images[0].name,'comfy_name':'ref0.png'}
        with patch.object(server.backend,'LIBRARY',self.root),patch.object(server.backend,'asset',side_effect=asset),patch.object(server,'source_audio_duration',return_value=9),patch.object(server.threading,'Thread') as thread:
            try:
                job=server.start(dict(self.req,image_ids=['image'],song_id='song',width=1280))
                self.assertTrue(job['request']['plan_review'])
                graph=server.preflight.call_args.args[1]
                self.assertEqual({n['class_type'] for n in graph.values()},{'CLIPLoader','TextGenerate'})
                self.assertEqual(thread.call_args.kwargs['target'],server.worker)
                self.queue.assert_not_called()
            finally:
                if self.lock.locked():self.lock.release()

    def test_approval_http_route_passes_job_and_revision(self):
        handler=object.__new__(server.Handler);handler.path='/api/mv/open-furnace'
        handler.body_json=Mock(return_value={'id':'abcdef123456','revision':'approved'})
        handler.send_json=Mock()
        with patch.object(server,'open_furnace',return_value={'status':'running'}) as launch:
            handler.do_POST();launch.assert_called_once_with('abcdef123456','approved')
        self.assertEqual(handler.send_json.call_args.args[0]['status'],'running')
