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

    def test_invalid_index_is_rejected(self):
        job={'segments':[{'index':0}]}
        for value in (-1,True,3,'0'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                manual_prompt._segment(job,value)
