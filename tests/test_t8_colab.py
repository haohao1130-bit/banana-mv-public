import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import colab_runtime as runtime
from banana_mv import t8_storyboard

ROOT=Path(__file__).resolve().parents[1]


class T8ColabTests(unittest.TestCase):
    def test_entry_uses_experimental_checkout_and_enables_t8(self):
        nb=json.loads((ROOT/'Banana_MV_T8_Test.ipynb').read_text())
        for cell in nb['cells']:
            if cell['cell_type']=='code':compile(''.join(cell['source']),'<cell>','exec')
        setup=''.join(nb['cells'][1]['source']);launch=''.join(nb['cells'][3]['source'])
        self.assertIn("BRANCH='experiment/native9b-t8-policy-ab'",setup)
        self.assertIn("'--branch',BRANCH",setup)
        self.assertIn('T8_STORYBOARD = True',launch)
        self.assertIn('runtime.launch(globals()',launch)
        self.assertIn('include_rewriter=True',''.join(nb['cells'][2]['source']))

    def test_toggle_preserves_unrelated_config_and_source_is_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg={'unrelated':'keep'}
            with patch.object(t8_storyboard,'prepare',return_value={'revision':'1.0.0'}) as prepare:
                runtime.configure_t8(cfg,Path(tmp),True)
            prepare.assert_called_once_with(Path(tmp)/'cache/t8/storyboard_director.py')
            self.assertTrue(cfg['t8_storyboard']);self.assertEqual(cfg['unrelated'],'keep')
            self.assertIn('rewrite_trace_dir',cfg)
            runtime.configure_t8(cfg,Path(tmp),False,False)
            self.assertFalse(cfg['t8_storyboard']);self.assertNotIn('rewrite_trace_dir',cfg)
            with self.assertRaises(ValueError):runtime.configure_t8(cfg,Path(tmp),'on')

    def test_failed_source_does_not_enable_t8(self):
        cfg={}
        with patch.object(t8_storyboard,'prepare',side_effect=ValueError('hash mismatch')):
            with self.assertRaises(ValueError):runtime.configure_t8(cfg,Path('/unused'),True)
        # launch writes config only after successful verification; no server started.
        self.assertNotIn('t8_source_path',cfg)
        self.assertNotIn('t8_storyboard',cfg)


if __name__=='__main__':unittest.main()
