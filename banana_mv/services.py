"""Banana-owned settings, compatible asset storage and local prompt rewriting."""
import copy
import json
import os
import random
import shutil
import threading
import time
import uuid
from pathlib import Path

from banana_mv.comfy import comfy, queue_prompt, history_entry, execution_error, comfy_download, wait_prompt
from banana_mv.core import probe

ROOT = Path(__file__).resolve().parents[1]
# Legacy environment is accepted only to keep existing local launchers/data usable.
DATA = Path(os.environ.get('BANANA_DATA') or os.environ.get('H3TOYBOX_DATA') or '/content/banana_mv_data')
LIBRARY = DATA/'library'
PORT = int(os.environ.get('BANANA_PORT', '8190'))
ASSET_LOCK = threading.Lock()
DEFAULTS = {
    'comfy_url': 'http://127.0.0.1:8188',
    'comfy_input_dir': '/content/ComfyUI/input',
    'guides': {'ref': str(ROOT/'guides/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md')},
    'free_after_rewrite': True,
    'rewriter': {'model': 'minimax_h3_rewriter_ref2va_qwen3.5_9b_w4a8.safetensors',
                 'thinking': False, 'mtp': 'auto', 'max_length': 8192,
                 'temperature': 0.7, 'top_p': 0.8, 'top_k': 20},
}


def load_config():
    cfg = copy.deepcopy(DEFAULTS)
    path = DATA/'config.json'
    saved = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    # Import only settings used by Banana. Remote provider credentials are never loaded.
    for key in ('comfy_url', 'comfy_input_dir', 'free_after_rewrite'):
        if key in saved:
            cfg[key] = saved[key]
    for key in cfg['rewriter']:
        if key in saved.get('rewriter', {}):
            cfg['rewriter'][key] = saved['rewriter'][key]
    return cfg


def project_config(request):
    cfg = load_config()
    thinking = request.get('rewriter_thinking', cfg['rewriter']['thinking'])
    if not isinstance(thinking, bool):
        raise ValueError('9B 思考模式必須為布林值。')
    cfg['rewriter']['thinking'] = thinking
    if thinking:
        cfg['rewriter']['max_length'] = 16384
    return cfg


def safe_child(root, relative):
    root = Path(root).resolve()
    child = (root/relative).resolve()
    if not child.is_relative_to(root) or child == root:
        raise ValueError('無效的檔案路徑。')
    return child


def library_index():
    path = LIBRARY/'library.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []


def asset(asset_id):
    item = next((row for row in library_index() if row['id'] == asset_id), None)
    if item is None:
        raise ValueError('找不到素材，請重新上傳。')
    safe_child(LIBRARY, item['file'])
    safe_child(Path(load_config()['comfy_input_dir']), item['comfy_name'])
    return item


def restore_inputs(cfg):
    inp = Path(cfg['comfy_input_dir']); inp.mkdir(parents=True, exist_ok=True)
    restored = 0
    for item in library_index():
        source = safe_child(LIBRARY, item['file'])
        dest = safe_child(inp, item['comfy_name'])
        if source.is_file() and not dest.exists():
            shutil.copyfile(source, dest); restored += 1
    return restored


def add_asset(cfg, filename, body):
    suffix = Path(filename).suffix.lower()
    image = suffix in ('.png', '.jpg', '.jpeg', '.webp')
    if not image and suffix not in ('.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aac', '.mp4', '.webm'):
        raise ValueError('請上傳 PNG/JPEG/WebP 圖片或支援的音訊檔。')
    LIBRARY.mkdir(parents=True, exist_ok=True)
    aid = uuid.uuid4().hex[:12]
    stored = LIBRARY/(aid+suffix)
    inp = Path(cfg['comfy_input_dir']); inp.mkdir(parents=True, exist_ok=True)
    name = 'banana_asset_' + stored.name
    target = inp/name
    try:
        stored.write_bytes(body)
        row = {'id': aid, 'name': Path(filename).name, 'file': stored.name,
               'comfy_name': name, 'created': time.time(), 'kind': 'image' if image else 'audio'}
        if image:
            from PIL import Image, ImageOps
            with Image.open(stored) as pic:
                pic.load()
                row['width'], row['height'] = ImageOps.exif_transpose(pic).size
        elif not any(s['codec_type']=='audio' for s in probe(stored)['streams']):
            raise ValueError('檔案內沒有音軌。')
        shutil.copyfile(stored, target)
        with ASSET_LOCK:
            index = library_index()
            index.insert(0, row)
            temp = LIBRARY/'library.json.tmp'
            temp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(LIBRARY/'library.json')
        return row
    except Exception as error:
        stored.unlink(missing_ok=True); target.unlink(missing_ok=True)
        if image and isinstance(error, OSError):
            raise ValueError('無法讀取圖片，請重新匯出 PNG/JPEG/WebP。') from None
        raise


def build_rewrite_graph(cfg, system, parts, job_id):
    """Use ComfyUI's native TextGenerate contract with the existing 9B settings."""
    rw = cfg['rewriter']
    contents = ''.join(value if kind == 'text' else '<|vision_start|><|image_pad|><|vision_end|>'
                       for kind, value in parts)
    chat = (f'<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n'
            f'{contents.strip()}<|im_end|>\n<|im_start|>assistant\n')
    chat += '<think>\n' if rw['thinking'] else '<think>\n\n</think>\n\n'
    graph = {'encoder': {'class_type': 'CLIPLoader', 'inputs': {
        'clip_name': rw['model'], 'type': 'stable_diffusion', 'device': 'default'}}}
    names, batch = [], None
    inp = Path(cfg['comfy_input_dir']); inp.mkdir(parents=True, exist_ok=True)
    try:
        for index, (_, pic) in enumerate(part for part in parts if part[0]=='image'):
            name = f'banana_rewrite_{job_id}_{index}.jpg'
            names.append(name); pic.save(inp/name, quality=92)
            key = f'picture_{index}'
            graph[key] = {'class_type': 'LoadImage', 'inputs': {'image': name}}
            if batch is None:
                batch = [key, 0]
            else:
                merged = f'batch_{index}'
                graph[merged] = {'class_type': 'ImageBatch', 'inputs': {'image1': batch, 'image2': [key, 0]}}
                batch = [merged, 0]
        inputs = {'clip': ['encoder', 0], 'prompt': chat, 'max_length': int(rw['max_length']),
                  'sampling_mode': 'on', 'sampling_mode.temperature': float(rw['temperature']),
                  'sampling_mode.top_k': int(rw['top_k']), 'sampling_mode.top_p': float(rw['top_p']),
                  'sampling_mode.min_p': 0.0, 'sampling_mode.repetition_penalty': 1.0,
                  'sampling_mode.seed': random.randint(0, 2**31-1), 'sampling_mode.presence_penalty': 0.0,
                  'thinking': bool(rw['thinking']), 'use_default_template': True, 'mtp': rw['mtp']}
        if batch is not None:
            inputs['image'] = batch
        graph['generate'] = {'class_type': 'TextGenerate', 'inputs': inputs}
        graph['result'] = {'class_type': 'PreviewAny', 'inputs': {'source': ['generate', 0]}}
        if rw['thinking']:
            graph['thinking_preview'] = {'class_type': 'PreviewAny',
                                         'inputs': {'source': ['generate', 1]}}
        return graph, names
    except Exception:
        for name in names:
            (inp/name).unlink(missing_ok=True)
        raise


def _preview_text(outputs, node):
    preview = outputs.get(node)
    values = preview.get('text') if isinstance(preview, dict) else None
    if isinstance(values, str):
        return values.strip()
    if isinstance(values, (list, tuple)) and all(isinstance(value, str) for value in values):
        return ''.join(values).strip()
    return None


def rewrite_local(cfg, system, parts, job_id):
    graph, names = build_rewrite_graph(cfg, system, parts, job_id)
    entry = None
    try:
        entry = wait_prompt(cfg, queue_prompt(cfg, graph))
        outputs = entry.get('outputs', {})
        text = _preview_text(outputs, 'result')
        if text:
            return text
        if 'thinking_preview' in graph:
            thinking = _preview_text(outputs, 'thinking_preview')
            final_status = '空白' if text is not None else '讀不到預覽欄位'
            thinking_status = f'{len(thinking)} 字' if thinking is not None else '讀不到預覽欄位'
            raise ValueError(f'本地 9B 改寫回傳空白。正式稿端：{final_status}；'
                             f'思考端：{thinking_status}。ComfyUI 任務 ID：{prompt_id}')
        raise ValueError('本地 9B 改寫回傳空白。')
    finally:
        for name in names:
            (Path(cfg['comfy_input_dir'])/name).unlink(missing_ok=True)
        if entry is not None and cfg.get('free_after_rewrite', True):
            comfy(cfg, '/free', {'unload_models': True, 'free_memory': True})
