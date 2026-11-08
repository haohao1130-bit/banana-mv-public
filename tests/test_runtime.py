"""Offline checks for standalone model download and notebook generation."""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('banana_colab_runtime',ROOT/'tools/colab_runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)


class RuntimeTests(unittest.TestCase):
    def test_music_venv_skips_ensurepip_and_repairs_existing_partial_environment(self):
        for existing in (False,True):
            with self.subTest(existing=existing),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);python=root/'.music-venv/bin/python'
                if existing:
                    python.parent.mkdir(parents=True);python.touch()
                commands=[]
                def run(command,**kwargs):
                    commands.append(command)
                    if 'venv' in command:
                        python.parent.mkdir(parents=True,exist_ok=True);python.touch()
                    return types.SimpleNamespace(returncode=0)
                with patch.object(runtime,'ROOT',root),patch.object(runtime.subprocess,'run',side_effect=run), \
                     patch.object(runtime.subprocess,'check_output',side_effect=['revision123\n','2.9.0+cu130\n']):
                    runtime.install_music_analysis()
                creates=[c for c in commands if 'venv' in c]
                self.assertEqual(len(creates),int(not existing))
                if creates:self.assertIn('--without-pip',creates[0])
                bootstrap=next(c for c in commands if '--python' in c)
                self.assertEqual(bootstrap[bootstrap.index('--python')+1],str(python))
                self.assertTrue((root/'.music-venv/bootstrap.log').exists())
                self.assertTrue((root/'.music-venv/install.log').exists())
                self.assertEqual((root/'.music-venv/torch-constraint.txt').read_text(),'torch==2.9.0+cu130\n')

    def test_music_install_error_preserves_actual_pip_cause(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'install.log'
            def fail(command,**kwargs):
                kwargs['stdout'].write('ERROR: No module named pip\n')
                return types.SimpleNamespace(returncode=1)
            with patch.object(runtime.subprocess,'run',side_effect=fail),self.assertRaisesRegex(RuntimeError,'No module named pip'):
                runtime.music_install_command(['test'],path)
            self.assertIn('ERROR:',path.read_text())


    def test_shutdown_cell_only_renders_until_manual_click(self):
        process=Mock();process.poll.return_value=None
        old=Mock(disabled=False)
        ns={'banana_comfy_process':process,'banana_shutdown_button':old}
        button=Mock();output=Mock()
        output.__enter__=Mock(return_value=output);output.__exit__=Mock(return_value=False)
        widgets=types.SimpleNamespace(Button=Mock(return_value=button),Output=Mock(return_value=output))
        with patch.dict(sys.modules,{'ipywidgets':widgets}),patch('IPython.display.display') as display:
            runtime.show_shutdown_control(ns)
            process.terminate.assert_not_called();process.kill.assert_not_called()
            display.assert_called_once_with(button,output)
            self.assertTrue(old.disabled)
            callback=button.on_click.call_args.args[0]
            callback(button)
        process.terminate.assert_called_once();process.wait.assert_called_once_with(timeout=10)
        process.kill.assert_not_called()
        self.assertFalse(button.disabled)

    def test_shutdown_handles_missing_exited_and_stuck_owned_process(self):
        self.assertIn('未關閉其他程序',runtime.stop_owned_comfy({}))
        process=Mock();process.poll.return_value=0
        runtime.stop_owned_comfy({'banana_comfy_process':process})
        process.terminate.assert_not_called()
        process.poll.return_value=None
        process.wait.side_effect=[runtime.subprocess.TimeoutExpired('comfy',10),0]
        runtime.stop_owned_comfy({'banana_comfy_process':process})
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_args_list[-1].kwargs,{'timeout':5})

    def test_waits_for_a_slow_service_with_progress_instead_of_thirty_second_failure(self):
        clock=[0]
        response=Mock(status=200)
        context=Mock();context.__enter__=Mock(return_value=response);context.__exit__=Mock(return_value=False)
        def connect(*args,**kwargs):
            if clock[0]<35:
                raise runtime.urllib.error.URLError('still starting')
            return context
        with patch.object(runtime.time,'monotonic',side_effect=lambda:clock[0]), \
             patch.object(runtime.time,'sleep',side_effect=lambda n:clock.__setitem__(0,clock[0]+n)), \
             patch.object(runtime.urllib.request,'urlopen',side_effect=connect),patch('builtins.print') as progress:
            runtime.wait_http('http://localhost/health',timeout=180,label='frontend')
        self.assertEqual(clock[0],35)
        self.assertTrue(progress.called)

    def test_launch_reuses_a_live_starting_process_but_replaces_an_exited_one(self):
        live=Mock();live.poll.return_value=None
        ns={'frontend':live}
        with patch.object(runtime.subprocess,'Popen') as spawn:
            self.assertIs(runtime.launch_once(ns,'frontend',['server'],log_path='unused',cwd=ROOT),live)
            spawn.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp:
            live.poll.return_value=1
            replacement=Mock()
            with patch.object(runtime.subprocess,'Popen',return_value=replacement) as spawn:
                self.assertIs(runtime.launch_once(ns,'frontend',['server'],log_path=str(Path(tmp)/'server.log'),cwd=ROOT),replacement)
                spawn.assert_called_once()

    def test_wait_reports_process_exit_early(self):
        process=Mock(returncode=7);process.poll.return_value=7
        with patch.object(runtime.urllib.request,'urlopen',side_effect=runtime.urllib.error.URLError('not ready')):
            with self.assertRaisesRegex(RuntimeError,'已退出.*7'):
                runtime.wait_http('http://localhost/health',process=process,label='frontend',log_path='server.log')

    def test_download_only_required_models_and_reuse_existing_files(self):
        from banana_mv.core import MODELS,MOTION_LORAS
        names={Path(f).name for _,f,_ in runtime.MODEL_FILES}
        self.assertEqual(names,set(MODELS.values())|set(MOTION_LORAS.values()))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);comfy=root/'comfy';downloads=root/'downloads';downloads.mkdir()
            calls=[]
            def fetch(repo,filename,**kwargs):
                calls.append((repo,filename,kwargs))
                path=downloads/Path(filename).name;path.write_text('downloaded-model-or-guide')
                return str(path)
            fake=types.SimpleNamespace(hf_hub_download=fetch,
                HfApi=lambda:types.SimpleNamespace(model_info=lambda repo:types.SimpleNamespace(sha='fixed-revision')))
            with patch.dict(sys.modules,{'huggingface_hub':fake}),patch.object(runtime,'ROOT',root),patch.object(runtime,'COMFY',comfy):
                existing=comfy/'models/diffusion_models'/runtime.MODEL_FILES[0][1]
                existing.parent.mkdir(parents=True);existing.write_text('keep-successful-weight')
                runtime.download({},include_rewriter=True)
                self.assertEqual(existing.read_text(),'keep-successful-weight')
                self.assertTrue((root/'guides'/runtime.GUIDE).is_file())
                self.assertFalse(any('SelfLift' in file or 'turbo' in file for _,file,_ in calls))
                self.assertTrue(all(args['revision']=='fixed-revision' for _,file,args in calls if file.endswith('.safetensors')))
                first=len(calls)
                runtime.download({},include_rewriter=True)
                self.assertEqual(len(calls),first+1) # Only the guide is fetched again.
                receipt=json.loads((root/'model_download_receipt.json').read_text())
                self.assertTrue(all(row['source']=='existing' for row in receipt))

    def test_notebook_code_cells_compile_and_have_no_image_install_option(self):
        path=ROOT/'Banana_MV_Public.ipynb'
        if not path.exists():path=ROOT/'Banana_MV_Colab.ipynb'
        notebook=json.loads(path.read_text())
        for cell in notebook['cells']:
            source=''.join(cell['source'])
            self.assertNotIn('INSTALL_IMAGE',source)
            if cell['cell_type']=='code':
                compile(source,'colab-cell','exec')
                self.assertEqual(cell['outputs'],[])
        self.assertEqual(notebook['metadata']['colab']['gpuType'],'G4')

