"""Banana-owned Colab install, model download and launch; no upstream notebook execution."""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMFY = Path('/content/ComfyUI')
PINS = {
    str(COMFY): ('https://github.com/Comfy-Org/ComfyUI.git', '56f179f6c50dad0c4c860ae4da427415c8e86415'),
    str(COMFY/'custom_nodes/minimax-h3-audio-t8'): (
        'https://github.com/T8mars/comfyui-minimax-h3-audio-T8.git', '3a23f333537d9a715aad7ce79af8d9ec891d9ad8'),
}
MODEL_FILES = [
    ('OliviaRossi/Minimax-h3_Singularity-x-10Eros-Max_PRISM', 'Minimax-h3_Singularity_x_10Eros-Max_PRISM_int8.safetensors', 'diffusion_models'),
    ('Comfy-Org/MiniMax-H3', 'text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors', 'text_encoders'),
    ('Comfy-Org/MiniMax-H3', 'vae/minimax_h3_video_vae_int8_convrot.safetensors', 'vae'),
    ('Comfy-Org/MiniMax-H3', 'vae/minimax_h3_audio_vae_fp32.safetensors', 'vae'),
    ('dseditor/minimax-h3-studio-assets', 'loras/H3_Combat_V2.safetensors', 'loras'),
    ('dseditor/minimax-h3-studio-assets', 'loras/Motion_Repair.safetensors', 'loras'),
]
REWRITER = ('dseditor/minimax-h3-studio-assets',
            'text_encoders/minimax_h3_rewriter_ref2va_qwen3.5_9b_w4a8.safetensors', 'text_encoders')
GUIDE = 'VIDEO_PROMPT_WRITING_GUIDE_ref_en.md'


def checkout(path, url, revision):
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'clone', '--no-checkout', url, str(path)], check=True)
    subprocess.run(['git', '-C', str(path), 'fetch', '--depth', '1', 'origin', revision], check=True)
    subprocess.run(['git', '-C', str(path), 'checkout', '--detach', revision], check=True)


def install(ns):
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('請在執行階段設定選擇 G4 GPU。')
    capability = torch.cuda.get_device_capability(0)
    driver = subprocess.check_output(['nvidia-smi', '--query-gpu=driver_version', '--format=csv,noheader'], text=True).splitlines()[0]
    print('GPU:', torch.cuda.get_device_name(0), '| 驅動:', driver)
    if capability < (8, 0) or int(driver.split('.')[0]) < 580:
        raise RuntimeError('目前 INT8 ConvRot 配置需要 capability ≥ 8.0、驅動 ≥ 580；請更換執行階段。')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('找不到 ffmpeg/ffprobe，請使用標準 Colab GPU 執行階段。')
    try:
        from google.colab import userdata
        os.environ['HF_TOKEN'] = userdata.get('HF_TOKEN')
    except Exception:
        print('未設定 HF_TOKEN，模型將匿名下載。')
    for path, (url, revision) in PINS.items():
        checkout(path, url, revision)
    if not (torch.version.cuda or '').startswith('13'):
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'torch', 'torchvision', 'torchaudio',
                        '--index-url', 'https://download.pytorch.org/whl/cu130'], check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', str(COMFY/'requirements.txt'),
                    'huggingface_hub', 'hf_xet', 'Pillow', 'numpy'], check=True)
    install_music_analysis()
    ns['COMFY'] = COMFY
    print('✅ Banana MV、固定版 ComfyUI 與 H3 Audio T8 安裝完成。')


def music_install_command(command, log_path):
    """Keep resolver output and include the useful error in Colab's traceback."""
    print('安裝音樂分析器；完整日誌：',log_path,flush=True)
    with Path(log_path).open('w',encoding='utf-8') as log:
        result = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,text=True)
    if result.returncode:
        tail='\n'.join(Path(log_path).read_text(encoding='utf-8',errors='replace').splitlines()[-60:])
        raise RuntimeError(f'音樂分析器安裝失敗（代碼 {result.returncode}）；日誌：{log_path}\n{tail}')


def install_music_analysis():
    """Keep all music dependencies outside the working ComfyUI environment."""
    revision = subprocess.check_output([sys.executable,'-c',
        'from banana_mv.music_structure import REVISION; print(REVISION)'],cwd=ROOT,text=True).strip()
    torch_version = subprocess.check_output([sys.executable,'-c','import torch; print(torch.__version__)'],text=True).strip()
    folder = ROOT/'.music-venv'
    python = folder/'bin/python'
    if not python.is_file():
        subprocess.run([sys.executable,'-m','venv','--system-site-packages','--without-pip',str(folder)],check=True)
    # Colab's distro Python can lack ensurepip. Bootstrap using the working
    # host pip's --python support; also repairs an existing half-created venv.
    music_install_command([sys.executable,'-m','pip','--python',str(python),
                           'install','--upgrade','pip'], folder/'bootstrap.log')
    constraints = folder/'torch-constraint.txt'
    constraints.write_text('torch=='+torch_version+'\n',encoding='utf-8')
    music_install_command([str(python),'-m','pip','install','-c',str(constraints),
                    'all-in-one-infer @ git+https://github.com/openmirlab/all-in-one-infer.git@'+revision],
                    folder/'install.log')
    subprocess.run([str(python),'-c','import allin1_infer; import torch; print("音樂結構分析器已安裝（CPU；首次分析會下載模型）")'],check=True)


def download(ns, include_rewriter=True, use_drive_cache=False):
    from huggingface_hub import hf_hub_download
    cache = None
    if use_drive_cache:
        from google.colab import drive
        drive.mount('/content/drive')
        cache = Path('/content/drive/MyDrive/H3_models'); cache.mkdir(parents=True, exist_ok=True)
    items = MODEL_FILES + ([REWRITER] if include_rewriter else [])
    # Resolve once per download run, record exact remote revisions for reproducibility.
    # Existing model files/cache remain untouched; do not replace a successful setup.
    from huggingface_hub import HfApi
    revisions = {}
    receipt = []
    for repo, filename, folder in items:
        target = COMFY/'models'/folder/Path(filename).name
        target.parent.mkdir(parents=True, exist_ok=True)
        cached = cache/target.name if cache else None
        source = 'existing'
        revision = None
        if not target.is_file():
            if cached and cached.is_file():
                shutil.copyfile(cached, target); source = 'drive-cache'
            else:
                if repo not in revisions:
                    revisions[repo] = HfApi().model_info(repo).sha
                revision = revisions[repo]
                got = hf_hub_download(repo, filename=filename, revision=revision, local_dir='/content/banana_hf_downloads')
                shutil.move(got, target); source = 'huggingface'
        if not target.stat().st_size:
            raise RuntimeError('模型檔案為空：' + target.name)
        if cached and not cached.is_file():
            shutil.copyfile(target, cached)
        receipt.append({'file': target.name, 'repo': repo, 'revision': revision, 'source': source,
                        'bytes': target.stat().st_size})
        print(f'✅ {target.name} ({target.stat().st_size/2**30:.2f} GiB)')
    guide = ROOT/'guides'/GUIDE; guide.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(hf_hub_download('MiniMaxAI/MiniMax-H3', filename='docs/'+GUIDE, local_dir='/content/banana_hf_downloads'), guide)
    (ROOT/'model_download_receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print('✅ 只下載 Banana MV 使用的模型；不下載生圖、SelfLift、Turbo 或語意橋。')


def wait_http(url, timeout=180, *, process=None, label='服務', log_path=None):
    deadline = time.monotonic()+timeout
    next_notice = time.monotonic()+15
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, TimeoutError):
            pass
        if process is not None and process.poll() is not None:
            raise RuntimeError(f'{label} 啟動程序已退出（代碼 {process.returncode}）；請查看 {log_path or "服務日誌"}。')
        if time.monotonic() >= next_notice:
            print(f'⏳ {label} 仍在啟動，會自動繼續等待，不需重按③。',flush=True)
            next_notice = time.monotonic()+15
        time.sleep(1)
    raise RuntimeError(f'{label} 啟動等待超過 {timeout} 秒；請查看 {log_path or "服務日誌"}。仍在執行的程序會保留，重試時沿用。')


def launch_once(ns, key, args, *, log_path, cwd, env=None):
    """Reuse a still-starting owned process, not just an already-open HTTP port."""
    process = ns.get(key)
    if process is not None and process.poll() is None:
        print('沿用仍在啟動的程序，等待服務就緒。',flush=True)
        return process
    with open(log_path,'a') as log:
        process = subprocess.Popen(args,cwd=str(cwd),env=env,stdout=log,stderr=subprocess.STDOUT)
    ns[key] = process
    return process


def stop_owned_comfy(ns):
    """Stop only the ComfyUI process started by this notebook; never kill by port."""
    process = ns.get('banana_comfy_process')
    if process is None:
        return '沒有此筆記本啟動的 ComfyUI 程序紀錄，未關閉其他程序。'
    if process.poll() is not None:
        return 'ComfyUI 已停止。需要時重新執行③。'
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    return 'ComfyUI 已關閉；已保存的段落與前端保留。需要時重新執行③。'


def show_shutdown_control(ns):
    """Executing the cell only renders widgets. Shutdown lives exclusively in the click callback."""
    import ipywidgets as widgets
    from IPython.display import display
    previous = ns.get('banana_shutdown_button')
    if previous is not None:
        previous.disabled = True
    button = widgets.Button(description='關閉 ComfyUI', button_style='danger',
                            tooltip='立即停止 ComfyUI；執行中的 MV 可能中斷')
    output = widgets.Output()

    def clicked(_):
        button.disabled = True
        with output:
            output.clear_output(wait=True)
            try:
                print(stop_owned_comfy(ns))
            except Exception as error:
                print('關閉未完成：', error)
            finally:
                button.disabled = False

    button.on_click(clicked)
    ns['banana_shutdown_button'] = button
    print('此格只顯示按鈕，全部執行不會關閉服務。手動點擊才立即停止 ComfyUI。')
    print('執行中的 MV 可能中斷；完成的段落保留。關閉 ComfyUI 不會解除 Colab GPU 配置。')
    display(button, output)


def launch(ns, save_to_drive=True, drive_folder='BananaMV'):
    if drive_folder not in ('BananaMV', 'BananaMVClassicPythonSlot'):
        raise ValueError('資料資料夾名稱未經核准。')
    data = Path('/content/banana_mv_python_slot_data' if drive_folder == 'BananaMVClassicPythonSlot'
                else '/content/banana_mv_data')
    if save_to_drive:
        from google.colab import drive
        drive.mount('/content/drive')
        data = Path('/content/drive/MyDrive') / drive_folder
    data.mkdir(parents=True, exist_ok=True)
    cfg_path = data/'config.json'
    cfg = json.loads(cfg_path.read_text(encoding='utf-8')) if cfg_path.is_file() else {}
    cfg.update(comfy_url='http://127.0.0.1:8188', comfy_input_dir=str(COMFY/'input'), free_after_rewrite=True)
    # Leave existing unrelated config/secret files alone; Banana reads an explicit allowlist.
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    (COMFY/'input').mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen('http://127.0.0.1:8188/system_stats', timeout=2):
            print('沿用執行中的 ComfyUI。')
    except OSError:
        launch_once(ns,'banana_comfy_process',
            [sys.executable, 'main.py', '--listen', '127.0.0.1', '--port', '8188'],cwd=COMFY,
            log_path='/content/comfyui.log')
    wait_http('http://127.0.0.1:8188/system_stats',timeout=600,process=ns.get('banana_comfy_process'),
              label='ComfyUI',log_path='/content/comfyui.log')
    # Never start a second frontend or kill an unrelated process silently.
    try:
        with urllib.request.urlopen('http://127.0.0.1:8190/api/health', timeout=2) as response:
            health = json.load(response)
        if health.get('service') == 'banana-mv' and health.get('standalone'):
            print('沿用獨立版 Banana MV。')
        else:
            raise RuntimeError('8190 已有其他服務，請先停止舊前端。')
    except urllib.error.HTTPError:
        raise RuntimeError('8190 仍是舊前端；請先停止舊前端，或使用新的執行階段。') from None
    except urllib.error.URLError:
        launch_once(ns,'banana_frontend_process',
            [sys.executable, str(ROOT/'banana_mv/server.py')],cwd=ROOT,
            env=dict(os.environ, BANANA_DATA=str(data), BANANA_PORT='8190'),log_path='/content/banana_mv.log')
    wait_http('http://127.0.0.1:8190/api/health',timeout=180,process=ns.get('banana_frontend_process'),
              label='Banana MV',log_path='/content/banana_mv.log')
    with urllib.request.urlopen('http://127.0.0.1:8190/api/health',timeout=5) as response:
        health = json.load(response)
    if health.get('service')!='banana-mv' or not health.get('standalone'):
        raise RuntimeError('8190 並非獨立版 Banana MV，請檢查前端服務。')
    print('🍌 Banana MV｜素材、分段與作品：', data)
    from google.colab import output
    output.serve_kernel_port_as_window(8190, anchor_text='🍌 打開大乘蕉宗 MV 製作所')
