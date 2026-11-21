"""Exercise owned storage and local rewriter without upstream files or a GPU."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from banana_mv import services


class ServicesTests(unittest.TestCase):
    def test_existing_library_restore_and_path_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);lib=root/'library';lib.mkdir();inp=root/'input'
            with patch.object(services,'DATA',root),patch.object(services,'LIBRARY',lib):
                (root/'config.json').write_text(json.dumps({'comfy_input_dir':str(inp),
                    'rewriter':{'openai':{'api_key':'do-not-load'},'temperature':0.5},
                    'guides':{'ref':'old/frontend/guide.md'}}))
                (lib/'old.png').write_bytes(b'preserved-original')
                (lib/'library.json').write_text(json.dumps([{'id':'legacy','file':'old.png','comfy_name':'h3fe_old.png'}]))
                cfg=services.load_config()
                self.assertNotIn('openai',cfg['rewriter'])
                self.assertEqual(cfg['rewriter']['temperature'],0.5)
                self.assertNotIn('old/frontend',cfg['guides']['ref'])
                self.assertEqual(services.restore_inputs(cfg),1)
                self.assertEqual((inp/'h3fe_old.png').read_bytes(),b'preserved-original')
                self.assertEqual(services.asset('legacy')['file'],'old.png')
                with self.assertRaises(ValueError):services.safe_child(lib,'../config.json')
                with self.assertRaises(ValueError):services.add_asset(cfg,'bad.png',b'not an image')
                self.assertEqual(len(services.library_index()),1)

    def test_project_thinking_options_reach_text_generate(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(services, 'DATA', Path(tmp)):
            for budget in (16384, 32768):
                cfg = services.project_config({'rewriter_thinking': True, 'rewriter_budget': budget})
                cfg['comfy_input_dir'] = tmp
                guide = 'Length: normally 350–500 English words for generation tasks.'
                graph, _ = services.build_rewrite_graph(cfg, guide, [('text','shot')], 'test')
                inputs = graph['generate']['inputs']
                self.assertTrue(inputs['thinking'])
                self.assertEqual(inputs['max_length'], budget)
                self.assertTrue(inputs['prompt'].endswith('<think>\n'))
                system = inputs['prompt'].split('<|im_end|>', 1)[0]
                self.assertIn('up to 1,500 English words', system)
                self.assertNotIn('350–500', system)
                self.assertIn('aim for under 150 words', system)
                self.assertIn('close it with </think>', system)
                self.assertEqual(graph['result']['inputs']['source'], ['generate', 0])
                self.assertEqual(graph['thinking_preview']['inputs']['source'], ['generate', 1])
            cfg = services.project_config({'rewriter_thinking': False, 'rewriter_budget': 32768})
            self.assertFalse(cfg['rewriter']['thinking'])
            self.assertEqual(cfg['rewriter']['max_length'], 8192)
            self.assertEqual(services.project_config({})['rewriter'], services.load_config()['rewriter'])
            with self.assertRaises(ValueError):
                services.project_config({'rewriter_thinking': True, 'rewriter_budget': 99999})

    def test_thinking_preview_diagnoses_empty_final_without_replacing_it(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(services, 'DATA', Path(tmp)):
            cfg = services.project_config({'rewriter_thinking': True, 'rewriter_budget': 16384})
            cfg.update(comfy_input_dir=tmp, free_after_rewrite=False)
            with patch.object(services, 'queue_prompt', return_value='prompt-id') as queue, \
                 patch.object(services, 'wait_prompt') as wait:
                outputs = {'result': {'text': ['final']}, 'thinking_preview': {'text': ['思考中']}}
                wait.return_value = {'outputs': outputs}
                self.assertEqual(services.rewrite_local(cfg, 'guide', [('text', 'shot')], 'test'), 'final')
                outputs['result']['text'] = [' ']
                with self.assertLogs('banana_mv.services', level='WARNING'), \
                     self.assertRaisesRegex(ValueError, '正式稿端：空白；思考端：3 字.*重試後仍無法取得正式稿'):
                    services.rewrite_local(cfg, 'guide', [('text', 'shot')], 'test')
                self.assertEqual(queue.call_count, 3)
                del outputs['result']
                outputs['thinking_preview']['text'] = ['']
                with self.assertRaisesRegex(ValueError, '正式稿端：讀不到預覽欄位；思考端：0 字'):
                    services.rewrite_local(cfg, 'guide', [('text', 'shot')], 'test')
                self.assertEqual(queue.call_count, 4)

    def test_thinking_only_retries_once_without_changing_project_settings(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(services, 'DATA', Path(tmp)):
            cfg = services.project_config({'rewriter_thinking': True, 'rewriter_budget': 32768})
            cfg.update(comfy_input_dir=tmp, free_after_rewrite=False)
            blank = {'outputs': {'result': {'text': ['']}, 'thinking_preview': {'text': ['思考中']}}}
            success = {'outputs': {'result': {'text': ['final']}}}
            with patch.object(services, 'queue_prompt', side_effect=['first', 'retry']) as queue, \
                 patch.object(services, 'wait_prompt', side_effect=[blank, success]), \
                 self.assertLogs('banana_mv.services', level='WARNING'):
                self.assertEqual(services.rewrite_local(cfg, 'guide', [('text', 'shot')], 'test'), 'final')
                graphs = [call.args[1] for call in queue.call_args_list]
                settings = [g['generate']['inputs'] for g in graphs]
                self.assertEqual([(s['thinking'], s['max_length']) for s in settings],
                                 [(True, 32768), (False, 8192)])
                self.assertEqual(cfg['rewriter']['max_length'], 32768)
                self.assertTrue(cfg['rewriter']['thinking'])

            def stop_before_result(*args):
                services.request_rewrite_stop()
                return blank

            with patch.object(services, 'queue_prompt', return_value='stop') as queue, \
                 patch.object(services, 'wait_prompt', side_effect=stop_before_result):
                with self.assertRaises(InterruptedError):
                    services.rewrite_local(cfg, 'guide', [('text', 'shot')], 'test')
                queue.assert_called_once()
            self.assertIsNone(services.active_rewrite_prompt_id())

    def test_rewriter_contract_cleanup_and_unload(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg=services.load_config();cfg['comfy_input_dir']=tmp
            pics=[Image.new('RGB',(64,64),c) for c in ('red','blue')]
            parts=[('text','<Picture 1>'),('image',pics[0]),('text','<Picture 2>'),('image',pics[1])]
            captured=[]
            def queue(config,graph):captured.append(graph);return 'prompt'
            with patch.object(services,'queue_prompt',side_effect=queue),\
                 patch.object(services,'wait_prompt',return_value={'outputs':{'result':{'text':['hello']}}}),\
                 patch.object(services,'comfy',return_value={}) as api:
                self.assertEqual(services.rewrite_local(cfg,'guide',parts,'test'),'hello')
                api.assert_called_once_with(cfg,'/free',{'unload_models':True,'free_memory':True})
            graph=captured[0]
            self.assertNotIn('thinking_preview', graph)
            self.assertNotIn('aim for under 150 words', graph['generate']['inputs']['prompt'])
            self.assertEqual(graph['generate']['inputs']['image'],['batch_1',0])
            self.assertEqual(graph['batch_1']['inputs']['image1'],['picture_0',0])
            self.assertEqual(graph['generate']['inputs']['prompt'].count('<|image_pad|>'),2)
            self.assertEqual(graph['generate']['inputs']['max_length'],8192)
            self.assertEqual(list(Path(tmp).glob('*.jpg')),[])
            with patch.object(services,'queue_prompt',side_effect=RuntimeError('rejected')):
                with self.assertRaisesRegex(RuntimeError,'rejected'):
                    services.rewrite_local(cfg,'guide',parts,'failed')
            self.assertEqual(list(Path(tmp).glob('*.jpg')),[])
