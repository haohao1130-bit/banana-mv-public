"""Stop the CURRENT task by ID without touching finished clips or other Comfy jobs."""
import unittest
from unittest.mock import Mock, patch

from banana_mv import comfy, services, server as app


class PreciseStopTests(unittest.TestCase):
    def tearDown(self):
        app.CANCEL.discard('stop_test')
        app.CANCEL.discard('resume_test')
        app.STOP_AFTER_CURRENT.discard('stop_test')
        app.STOP_AFTER_CURRENT.discard('resume_test')
        services._REWRITE_PROMPT_ID=None

    def test_graceful_stop_never_interrupts_comfy_and_records_after_current(self):
        job={'id':'stop_test','status':'running',
             'segments':[{'index':0,'status':'generating','prompt_id':'active-h3'},
                         {'index':1,'status':'waiting'}]}
        with patch.object(app,'read_state',return_value=job), \
             patch.object(comfy,'cancel_prompt',side_effect=AssertionError('graceful must not interrupt')), \
             patch.object(app.backend,'active_rewrite_prompt_id',side_effect=AssertionError('no rewrite cancel')):
            response=app.stop_after_current_job('stop_test')
        self.assertEqual(response['interruption'],'after_current_requested')
        self.assertIn('stop_test',app.STOP_AFTER_CURRENT)
        self.assertNotIn('stop_test',app.CANCEL)
        self.assertEqual(job['segments'][0]['status'],'generating')
        with patch.object(app,'write_state') as write:
            self.assertTrue(app.pause_after_committed_clip(job))
        write.assert_called_once_with(job)
        self.assertEqual(job['status'],'interrupted')
        self.assertEqual(job['stop_reason'],'after_current')
        self.assertEqual(job['segments'][1]['status'],'waiting')
        self.assertFalse(app.GPU_LOCK.locked())

    def test_emergency_overrides_graceful_wait_and_targets_active_h3(self):
        app.STOP_AFTER_CURRENT.add('stop_test')
        job={'id':'stop_test','status':'running',
             'segments':[{'index':0,'status':'generating','prompt_id':'h3-current'}]}
        with patch.object(app,'read_state',return_value=job), \
             patch.object(app.backend,'load_config',return_value={}), \
             patch.object(comfy,'cancel_prompt',return_value='interrupt_requested') as cancel:
            response=app.stop_job('stop_test')
        cancel.assert_called_once_with({},'h3-current')
        self.assertEqual(response['interruption'],'interrupt_requested')
        self.assertNotIn('stop_test',app.STOP_AFTER_CURRENT)
        self.assertIn('stop_test',app.CANCEL)

    def test_graceful_stop_is_not_available_for_finished_or_unapproved_recipe(self):
        for status in ('done','plan_ready','cancelled','interrupted','assembling'):
            with patch.object(app,'read_state',return_value={'id':'stop_test','status':status}):
                response=app.stop_after_current_job('stop_test')
            self.assertEqual(response['interruption'],'not_running')
            self.assertNotIn('stop_test',app.STOP_AFTER_CURRENT)

    def test_comfy_interrupts_only_the_matching_active_prompt(self):
        calls=[]
        def fake(cfg,path,payload=None):
            calls.append((path,payload))
            if path=='/queue':
                return {'queue_running':[[1,'h3-current',{}]],
                        'queue_pending':[[2,'someone-else',{}]]} if payload is None else {}
            return {}
        with patch.object(comfy,'comfy',side_effect=fake):
            self.assertEqual(comfy.cancel_prompt({},'h3-current'),'interrupt_requested')
        self.assertEqual(calls,[('/queue',None),('/interrupt',{'prompt_id':'h3-current'})])
        self.assertFalse(any(p.get('clear') for _,p in calls if isinstance(p,dict)))

    def test_pending_prompt_deleted_without_global_interrupt(self):
        calls=[]
        def fake(cfg,path,payload=None):
            calls.append((path,payload))
            if path=='/queue' and payload is None:
                return {'queue_running':[[1,'other-running',{}]],
                        'queue_pending':[[2,'our-waiting',{}]]}
            return {}
        with patch.object(comfy,'comfy',side_effect=fake):
            self.assertEqual(comfy.cancel_prompt({},'our-waiting'),'removed_from_queue')
            self.assertEqual(comfy.cancel_prompt({},'unknown'),'already_finished_or_unknown')
        self.assertIn(('/queue',{'delete':['our-waiting']}),calls)
        self.assertFalse(any(path=='/interrupt' for path,_ in calls))

    def test_active_h3_stop_is_prompt_scoped(self):
        job={'id':'stop_test','status':'running',
             'segments':[{'index':0,'status':'done','prompt_id':'finished'},
                         {'index':1,'status':'generating','prompt_id':'h3-current'}]}
        with patch.object(app,'read_state',return_value=job), \
             patch.object(app.backend,'load_config',return_value={'comfy_url':'http://localhost'}), \
             patch.object(comfy,'cancel_prompt',return_value='interrupt_requested') as cancel:
            response=app.stop_job('stop_test')
        self.assertEqual(response['interruption'],'interrupt_requested')
        self.assertIn('stop_test',app.CANCEL)
        cancel.assert_called_once_with({'comfy_url':'http://localhost'},'h3-current')
        self.assertEqual(job['segments'][0]['status'],'done')

    def test_current_retake_prompt_is_targeted_not_the_original(self):
        job={'id':'stop_test','status':'retaking',
             'retake':{'current':1,'takes':{'1':'new-version'}},
             'segments':[{'index':0,'status':'done'},
                         {'index':1,'status':'done','prompt_id':'original-id',
                          'takes':[{'id':'new-version','prompt_id':'retake-current'}]}]}
        with patch.object(app,'read_state',return_value=job), \
             patch.object(app.backend,'load_config',return_value={}), \
             patch.object(comfy,'cancel_prompt',return_value='interrupt_requested') as cancel:
            app.stop_job('stop_test')
        cancel.assert_called_once_with({},'retake-current')

    def test_active_9b_is_interruptible_too(self):
        job={'id':'stop_test','status':'running','segments':[{'status':'rewriting'}]}
        with patch.object(app,'read_state',return_value=job), \
             patch.object(app.backend,'load_config',return_value={}), \
             patch.object(app.backend,'active_rewrite_prompt_id',return_value='9b-director'), \
             patch.object(comfy,'cancel_prompt',return_value='interrupt_requested') as cancel:
            app.stop_job('stop_test')
        cancel.assert_called_once_with({},'9b-director')

    def test_wait_generation_does_not_wait_after_manual_cancel(self):
        job={'id':'stop_test'}
        app.CANCEL.add('stop_test')
        with patch.object(app.backend,'history_entry',
                          side_effect=AssertionError('should not poll after cancel')):
            with self.assertRaisesRegex(InterruptedError,'取消'):
                app.wait_generation({},'h3-current',job)

    def test_rewrite_prompt_id_cleared_even_after_interruption(self):
        def see_active(cfg,pid):
            self.assertEqual(services.active_rewrite_prompt_id(),'9b-in-progress')
            raise InterruptedError('9B cancelled')
        with patch.object(services,'build_rewrite_graph',return_value=({},[])), \
             patch.object(services,'queue_prompt',return_value='9b-in-progress'), \
             patch.object(services,'wait_prompt',side_effect=see_active):
            with self.assertRaises(InterruptedError):
                services.rewrite_local({},'system',[],'test')
        self.assertIsNone(services.active_rewrite_prompt_id())

    def test_resume_must_not_reuse_stopped_partial_clip(self):
        job={'id':'resume_test','status':'cancelled','segments':[
            {'index':0,'status':'done','seconds':10,'frames':124,
             'model_frames':124},
            {'index':1,'status':'waiting','seconds':10,'frames':124,
             'model_frames':124,'interrupted_render':True,'prompt_id':'stale'}],
            'request':{'mode':'independent'},'images_comfy':['a.png'],
            'size':[1280,736],'seed':1}
        worker_threads=[]
        class NoStart:
            def __init__(self,*args,**kwargs):worker_threads.append(kwargs)
            def start(self):pass
        with patch.object(app,'read_state',return_value=job), \
             patch.object(app.backend,'load_config',return_value={}), \
             patch.object(app.backend,'comfy',return_value={}), \
             patch.object(app,'project_inputs',return_value=([],None,None)), \
             patch.object(app,'repair_unstarted_timeline'), \
             patch.object(app,'restore_render_settings'), \
             patch.object(app,'adopted_part',return_value='video.mp4'), \
             patch.object(app,'valid_part',return_value=True), \
             patch.object(app,'build_workflow',return_value={}), \
             patch.object(app,'preflight'), \
             patch.object(app,'preflight_five_frame'), \
             patch.object(app,'write_state'), \
             patch.object(app.threading,'Thread',NoStart):
            try:
                app.resume('resume_test')
                self.assertEqual(job['segments'][0]['status'],'done')
                self.assertEqual(job['segments'][1]['status'],'waiting')
                self.assertNotIn('interrupted_render',job['segments'][1])
                self.assertEqual(job['status'],'running')
                self.assertEqual(len(worker_threads),1)
            finally:
                if app.GPU_LOCK.locked():app.GPU_LOCK.release()
