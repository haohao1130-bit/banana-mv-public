"""Install H3-FaceRefine into an existing Banana ComfyUI environment."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--comfy-source', type=Path, required=True)
parser.add_argument('--comfy-base', type=Path, required=True)
args = parser.parse_args()
source = args.comfy_source.resolve()
if not (source / 'main.py').is_file():
    parser.error(f'ComfyUI main.py missing: {source}')
base = args.comfy_base.resolve()
if not base.is_dir():
    parser.error(f'ComfyUI base directory missing: {base}')
nodes = base / 'custom_nodes'
nodes.mkdir(exist_ok=True)
plugin = nodes / 'ComfyUI-H3-FaceRefine'
if not plugin.exists():
    revision = 'd8521d14fe0d721d80cd9417fff5a559cbc21aba'
    with tempfile.TemporaryDirectory(dir=nodes.parent) as temporary:
        checkout = Path(temporary) / 'checkout'
        subprocess.run(['git', 'init', str(checkout)], check=True)
        subprocess.run(['git', '-C', str(checkout), 'fetch', '--depth', '1',
                        'https://github.com/Carasibana/ComfyUI-H3-FaceRefine.git', revision], check=True)
        subprocess.run(['git', '-C', str(checkout), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
        checkout.rename(plugin)
if not (plugin / 'requirements.txt').is_file():
    parser.error(f'Incomplete FaceRefine checkout: {plugin}')
# Constrain the existing GPU stack while resolving plugin dependencies.
from importlib.metadata import PackageNotFoundError, version
with tempfile.TemporaryDirectory() as temporary:
    constraints = Path(temporary) / 'constraints.txt'
    pins = []
    for name in ('torch','torchvision','torchaudio','onnxruntime','onnxruntime-gpu'):
        try:
            pins.append(f'{name}=={version(name)}')
        except PackageNotFoundError:
            pass
    constraints.write_text('\n'.join(pins), encoding='utf-8')
    pip = [sys.executable,'-m','pip','install','-c',str(constraints)]
    subprocess.run(pip+['-r',str(plugin / 'requirements.txt')],check=True)
    if importlib.util.find_spec('onnxruntime') is None:
        subprocess.run(pip+['onnxruntime'],check=True)
detector = base / 'models' / 'ultralytics' / 'bbox' / 'face_yolov8m.pt'
detector.parent.mkdir(parents=True, exist_ok=True)
if not detector.exists():
    pending = detector.with_suffix('.download')
    try:
        urllib.request.urlretrieve(
            'https://huggingface.co/Bingsu/adetailer/resolve/88768cbdfd2168b4a1ee5500598105b791508eb5/face_yolov8m.pt',pending)
        pending.replace(detector)
    finally:
        pending.unlink(missing_ok=True)
print('Installed FaceRefine and detector. Restart ComfyUI to load the nodes.')
