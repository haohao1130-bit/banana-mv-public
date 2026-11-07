import ast
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from PIL import Image
from banana_mv import shoot_plan,services,t8_storyboard
import test_shoot_plan as fixtures
from test_shoot_plan import allocation,native_prompt,timeline


class T8PolicyTests(unittest.TestCase):
    def test_camera_policy_replaced_once_and_upstream_unchanged(self):
        for enabled in (False,True):
            for dynamic in (False,True):
                for free in (False,True):
                    with self.subTest(enabled=enabled,dynamic=dynamic,free=free),tempfile.TemporaryDirectory() as tmp:
                        root=Path(tmp);images,cfg,req=fixtures.ShootPlanTests().fixture(root,'chain')
                        cfg['t8_storyboard']=enabled;req.update(dynamic_cuts=dynamic,story_plan=free)
                        allocator=Mock(return_value=allocation())
                        plan=shoot_plan.ensure_shoot_plan(cfg,req,timeline(),images,root,allocator)
                        seg=dict(timeline()[1],director_plan=plan['segments'][1],shoot_setup=plan['shared_setup'])
                        writer=Mock(return_value=native_prompt(1,1))
                        with patch.object(t8_storyboard,'load_method',return_value=('PINNED_T8_MARKER',{'commit':'pinned'})) as loader:
                            result=shoot_plan.write_shoot_prompt(cfg,req,seg,images,images[0],writer)
                        self.assertEqual(result,native_prompt(1,1));self.assertEqual(writer.call_count,1)
                        system=writer.call_args.args[1];text=writer.call_args.args[2][0][1]
                        self.assertEqual(system.count('PINNED_T8_MARKER'),int(enabled))
                        self.assertEqual(loader.call_count,int(enabled))
                        self.assertNotIn('PINNED_T8_MARKER',allocator.call_args.args[1])
                        self.assertEqual(shoot_plan.AUTO_FILMING in text,not enabled)
                        self.assertEqual(shoot_plan.DYNAMIC_EDITING in text,not enabled and dynamic)
                        self.assertIn(shoot_plan.REFERENCE_PERFORMANCE,text)
                        self.assertIn('<Picture 3>, already transformed',text)
                        self.assertIn('<Audio 1>: fully_copy',text)
                        if enabled:self.assertNotIn('When a permitted singer appears, prefer waist-up',text)
                        if not dynamic:self.assertIn('Prefer motivated longer takes.',text)

    def test_missing_or_corrupt_t8_stops_before_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'upstream.py'
            with self.assertRaises(ValueError):t8_storyboard.load_method(path)
            path.write_text('raise RuntimeError("must not execute")')
            with self.assertRaisesRegex(ValueError,'雜湊'):t8_storyboard.load_method(path)

    def test_ast_string_extraction_rejects_calls(self):
        self.assertEqual(t8_storyboard._string(ast.parse('"a"+name',mode='eval').body,{'name':'b'}),'ab')
        with self.assertRaises(ValueError):t8_storyboard._string(ast.parse('open("secret")',mode='eval').body,{})

    def test_actual_graph_seed_images_raw_response_and_cleanup_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=copy.deepcopy(services.DEFAULTS)
            cfg.update(comfy_input_dir=str(root/'input'),rewrite_trace_dir=str(root/'traces'),free_after_rewrite=False)
            cfg['rewriter']['seed']=31415
            parts=[('text','ORIGINAL_USER'),('image',Image.new('RGB',(8,8),'red'))]
            entry={'outputs':{'result':{'text':['  RAW_RESPONSE\n']}},'status':{'completed':True}}
            with patch.object(services,'queue_prompt',return_value='pid'),patch.object(services,'wait_prompt',return_value=entry):
                self.assertEqual(services.rewrite_local(cfg,'SYSTEM',parts,'fixed'),'RAW_RESPONSE')
            trace=root/'traces/fixed';record=json.loads((trace/'request.json').read_text())
            self.assertEqual(record['graph']['generate']['inputs']['sampling_mode.seed'],31415)
            self.assertIn('ORIGINAL_USER',record['graph']['generate']['inputs']['prompt'])
            self.assertEqual(record['prompt_id'],'pid')
            ref=record['images'][0];self.assertEqual(hashlib.sha256((trace/ref['name']).read_bytes()).hexdigest(),ref['sha256'])
            self.assertEqual(json.loads((trace/'response.json').read_text())['raw_text'],'  RAW_RESPONSE\n')
            self.assertFalse((root/'input'/ref['name']).exists())

    def test_error_keeps_trace_and_does_not_resubmit(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg=copy.deepcopy(services.DEFAULTS)
            cfg.update(comfy_input_dir=str(Path(tmp)/'input'),rewrite_trace_dir=str(Path(tmp)/'trace'),free_after_rewrite=False)
            with patch.object(services,'queue_prompt',return_value='uncertain') as queue,patch.object(services,'wait_prompt',side_effect=RuntimeError('timeout')):
                with self.assertRaisesRegex(RuntimeError,'timeout'):services.rewrite_local(cfg,'S',[('text','U')],'failure')
            self.assertEqual(queue.call_count,1)
            error=json.loads((Path(tmp)/'trace/failure/error.json').read_text())
            self.assertEqual(error['prompt_id'],'uncertain')

    def test_pair_freezes_plan_media_seed_and_renderer_except_prompt(self):
        from tools.compare_t8 import run
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);images,cfg,req=fixtures.ShootPlanTests().fixture(root)
            cfg['rewriter']=copy.deepcopy(services.DEFAULTS['rewriter'])
            plan=shoot_plan.ensure_shoot_plan(cfg,req,timeline(),images,root,Mock(return_value=allocation()))
            (root/'status.json').write_text(json.dumps({'request':req,'segments':timeline()}))
            workflow=root/'workflow.json';original={'7':{'inputs':{'prompt':'OLD'}},'8':{'inputs':{'seed':17}}}
            workflow.write_text(json.dumps(original))
            outputs=[native_prompt(0)+' A',native_prompt(0)+' B']
            history={'outputs':{'save':{'gifs':[{'filename':'test.mp4','type':'output','subfolder':''}]}}}
            def download(cfg,info,dest):Path(dest).write_bytes(b'test video fixture')
            with patch.object(services,'load_config',return_value=cfg),patch.object(services,'comfy',return_value={'queue_running':[],'queue_pending':[]}),patch('tools.compare_t8.prepare',return_value={'commit':'pinned'}),patch.object(t8_storyboard,'load_method',return_value=('PINNED_T8_MARKER',{})),patch.object(services,'rewrite_local',side_effect=outputs) as writer,patch.object(services,'queue_prompt',return_value='pid') as queue,patch.object(services,'wait_prompt',return_value=history),patch.object(services,'comfy_download',side_effect=download):
                report=run(root,images,root/'pair',seed=123,workflow=workflow)
            self.assertEqual(writer.call_count,2);self.assertEqual(queue.call_count,2)
            a,b=[copy.deepcopy(c.args[1]) for c in queue.call_args_list]
            self.assertNotEqual(a['7']['inputs']['prompt'],b['7']['inputs']['prompt'])
            a['7']['inputs']['prompt']=b['7']['inputs']['prompt']='OLD'
            self.assertEqual(a,original);self.assertEqual(b,original)
            for call in writer.call_args_list:self.assertEqual(call.args[0]['rewriter']['seed'],123)
            saved=json.loads(report.read_text());self.assertEqual(saved['status'],'completed')
            self.assertEqual(saved['frozen_segment']['director_plan'],plan['segments'][0])
            self.assertEqual(len(list((root/'pair').glob('*/trace'))),0) # Mock service; no fake real trace.
            with self.assertRaises(FileExistsError):run(root,images,root/'pair')


if __name__=='__main__':unittest.main()
