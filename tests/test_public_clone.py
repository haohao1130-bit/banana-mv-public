"""Anonymous bootstrap must not leave partial installs or execute on an existing checkout."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('public_clone',ROOT/'tools/public_clone.py')
bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)


class PublicCloneTests(unittest.TestCase):
    def test_success_and_existing_checkout(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'project'
            def clone(cmd,**kwargs):
                checkout=Path(cmd[-1]);(checkout/'tools').mkdir(parents=True)
                (checkout/'tools/colab_runtime.py').write_text('# runtime')
                self.assertEqual(kwargs['env']['GIT_TERMINAL_PROMPT'],'0')
                self.assertIn('credential.helper=',cmd)
                return Mock(returncode=0)
            with patch.object(bootstrap.subprocess,'run',side_effect=clone) as run:
                bootstrap.clone_project(target,'https://github.com/example/public.git')
                bootstrap.clone_project(target,'https://github.com/example/public.git')
                self.assertEqual(run.call_count,1)
            self.assertTrue((target/'tools/colab_runtime.py').exists())

    def test_failure_leaves_no_partial_install(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'project'
            def failed(cmd,**kwargs):
                Path(cmd[-1]).mkdir()
                return Mock(returncode=128)
            with patch.object(bootstrap.subprocess,'run',side_effect=failed):
                with self.assertRaisesRegex(RuntimeError,'公開版下載失敗'):
                    bootstrap.clone_project(target,'https://github.com/example/public.git')
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(temp).iterdir()),[])

    def test_existing_incomplete_directory_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError,'不完整'):
                bootstrap.clone_project(temp,'https://github.com/example/public.git')
