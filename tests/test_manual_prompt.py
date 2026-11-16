"""Manual per-segment 9B recompose writes only a separate reviewable prompt."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from banana_mv import manual_prompt
from banana_mv import server as app


class ManualPromptTests(unittest.TestCase):
    def test_worker_keeps_old_prompt_and_never_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            job={'id':'abcdef123456','request':{'mode':'independent'},
                 'segments':[{'index':0,'seconds':10,'prompt':'OLD H3 PROMPT',
                              'director_plan':{'handoff_version':1}}]}
            cfg={'rewriter':{'model':'dummy'}}
            with patch.object(app,'job_dir',return_value=Path(tmp)), \
                 patch.object(app,'GPU_LOCK',Mock()), \
                 patch.object(app,'write_state',Mock()) as save, \
                 patch.object(app,'local_prompt',return_value='NEW H3 PROMPT') as model, \
                 patch.object(app,'build_workflow',side_effect=AssertionError('Do not run H3')):
                manual_prompt._worker(job,cfg,0,[Path(tmp)/'photo.png'],1)
                self.assertEqual(job['segments'][0]['prompt'],'OLD H3 PROMPT')
                self.assertEqual(job['segments'][0]['prompt_rewrite']['status'],'ready')
                self.assertEqual(job['segments'][0]['prompt_rewrite']['text'],'NEW H3 PROMPT')
                self.assertEqual((Path(tmp)/'00_manual_prompt_v1.txt').read_text(),'NEW H3 PROMPT')
                self.assertEqual(model.call_count,1)
                save.assert_called_once()


    def test_9b_rewrite_pins_an_explicit_retake_tail_not_the_current_original(self):
        from banana_mv import takes
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            original=root/'old.mp4'
            revised=root/'new.mp4'
            original.write_bytes(b'old')
            revised.write_bytes(b'new')
            job={'id':'abcdef123456','status':'done','seed':42,'size':[32,32],
                 'request':{'mode':'chain','director_schema':6,'rewrite':True},
                 'segments':[
                     {'index':0,'status':'done','selected_take':'original','takes':[
                         {'id':'original','status':'ready'},
                         {'id':'abcdefabcdef','status':'ready'}]},
                     {'index':1,'status':'done','seconds':10,
                      'director_plan':{'handoff_version':1},
                      'prompt':'OLD H3 PROMPT'}]}
            cfg={'rewriter':{'model':'dummy'}}
            seen=[]
            def source(state,index,take='current'):
                seen.append((index,take))
                return revised if take=='abcdefabcdef' else original
            def frame(video,target):
                target.write_bytes(video.read_bytes())
            def writer(config,req,segment,originals,tail):
                self.assertEqual(tail.read_bytes(),b'new')
                return 'H3 DRAFT NEW TAIL'
            def inline_thread(*args,**kwargs):
                call=kwargs['target'];params=kwargs['args']
                return Mock(start=lambda:call(*params))
            with patch.object(app,'job_dir',return_value=root), \
                 patch.object(app,'GPU_LOCK',threading.Lock()), \
                 patch.object(app,'read_state',return_value=job), \
                 patch.object(app,'write_state',Mock()), \
                 patch.object(app,'project_inputs',return_value=([root/'photo.png'],root/'song.wav',root/'song.wav')), \
                 patch.object(app,'preflight',Mock()), \
                 patch.object(app,'valid_part',return_value=True), \
                 patch.object(app,'last_frame',side_effect=frame), \
                 patch.object(app,'local_prompt',side_effect=writer), \
                 patch.object(takes,'take_source',side_effect=source), \
                 patch.object(takes,'require_idle',Mock()), \
                 patch.object(takes,'describe',side_effect=lambda state:state), \
                 patch('banana_mv.python_slots.refresh_stale_timed_plan',return_value=False), \
                 patch.object(manual_prompt.threading,'Thread',side_effect=inline_thread):
                result=manual_prompt.rewrite_clip(job['id'],1,previous_take='abcdefabcdef')
            self.assertIn((0,'abcdefabcdef'),seen)
            self.assertTrue(all(take=='abcdefabcdef' for _,take in seen))
            self.assertEqual(job['segments'][1]['prompt'],'OLD H3 PROMPT')
            self.assertEqual(job['segments'][1]['prompt_rewrite']['previous_take'],'abcdefabcdef')
            self.assertEqual(job['segments'][1]['prompt_rewrite']['text'],'H3 DRAFT NEW TAIL')

    def test_invalid_index_is_rejected(self):
        job={'segments':[{'index':0}]}
        for value in (-1,True,3,'0'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                manual_prompt._segment(job,value)
