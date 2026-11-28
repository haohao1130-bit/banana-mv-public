"""Optional 5070-only bridge to the installed, isolated BANANA35B V2 lab."""
import atexit
import importlib.util
import json
import secrets
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(r'F:\BANANA35B')
TOKEN = secrets.token_urlsafe(32)
LOAD_LOCK = threading.Lock()
LAB = None

def ready():
    return all((ROOT / name).is_file() for name in ('banana35.py', 'index.html', 'installed.json'))

def load():
    global LAB
    with LOAD_LOCK:
        if LAB is None:
            if not ready():
                raise ValueError('請先安裝 BANANA35B，再套用 8193 實驗室更新包。')
            spec = importlib.util.spec_from_file_location('_banana35b_lab', ROOT / 'banana35.py')
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if getattr(mod, 'BRIDGE_VERSION', 0) != 2:
                raise ValueError('請先套用 BANANA35B V2 8193 更新包（不需重抓模型）。')
            LAB = mod
            atexit.register(mod.cancel)
        return LAB

def _guard(backend, lab, *, monitor=False):
    cfg = backend.load_config()
    target = urlparse(cfg['comfy_url'])
    if target.hostname not in ('127.0.0.1', 'localhost') or target.port != 8000:
        raise ValueError('35B 實驗室只允許本機 8000 ComfyUI。')
    if not lab.port_in_use(8000):
        return
    queue = backend.comfy(cfg, '/queue', timeout=4)
    if not all(isinstance(queue.get(k), list) for k in ('queue_running','queue_pending')):
        raise ValueError('無法確認 ComfyUI 工作佇列。')
    if queue['queue_running'] or queue['queue_pending']:
        raise ValueError('ComfyUI 有工作執行中或等待中，拒絕同時運行35B。')
    if not monitor:
        backend.comfy(cfg, '/free', {'unload_models': True, 'free_memory': True}, timeout=15)

def start(lab, backend, gpu_lock, body, restart_lock, restart_request):
    if body.get('model_path'):
        raise ValueError('遠端實驗室僅允許已安裝的模型。')
    if lab.port_in_use(8092):
        raise ValueError('請先關閉舊版獨立 8092 實驗室，再由8193進入。')
    with restart_lock:
        if restart_request.exists():
            raise ValueError('丹爐正在重啟。')
        if not gpu_lock.acquire(blocking=False):
            raise ValueError('MV 或其他丹爐工作執行中。')
        try:
            with lab.LOCK:
                if lab.STATE['busy']:
                    raise ValueError('35B 已在執行。')
                lab.STOP.clear()
                lab.STATE.update(busy=True,status='檢查丹爐…',error='',output='',thinking='',metrics={},gpu_after=None,peak_used_mib=None,run='')
            def work():
                try:
                    lab.run_job(body, managed_guard=lambda monitor=False: _guard(backend, lab, monitor=monitor))
                except Exception as error:
                    lab.status(status='失敗：'+str(error),error=str(error))
                finally:
                    try:
                        lab.stop_process()
                    finally:
                        lab.status(busy=False)
                        gpu_lock.release()
            threading.Thread(target=work, daemon=True).start()
        except Exception:
            lab.status(busy=False)
            gpu_lock.release()
            raise

def _auth(handler):
    if handler.headers.get('X-Banana-Token') != TOKEN:
        raise ValueError('實驗室控制憑證失效，請重新開啟頁面。')
    if handler.headers.get('Sec-Fetch-Site','same-origin') not in ('same-origin','none'):
        raise ValueError('不允許跨網站控制。')
    origin = urlparse(handler.headers.get('Origin',''))
    if origin.scheme not in ('http','https') or origin.netloc.casefold() not in (
            handler.headers.get('Host','').casefold(),handler.headers.get('X-Forwarded-Host','').casefold()):
        raise ValueError('實驗室請求必須來自目前 BANANAMV 網頁。')
    if handler.headers.get('Content-Type','').split(';',1)[0].strip().lower() != 'application/json':
        raise ValueError('請使用 JSON。')

def get(handler, path, backend):
    if backend.PORT != 8193 or sys.platform != 'win32':
        return handler.send_error(404)
    if path == '/banana35b/capability':
        return handler.send_json({'local5070': True, 'installed': ready()})
    try:
        lab = load()
        if path in ('/banana35b','/banana35b/'):
            html = (ROOT/'index.html').read_text(encoding='utf-8')
            if '__BASE__' not in html:
                raise ValueError('請套用 V2 前端更新。')
            data = html.replace('__TOKEN__',TOKEN).replace('__BASE__','/banana35b').encode('utf-8')
            handler.send_response(200)
            handler.send_header('Content-Type','text/html; charset=utf-8')
            handler.send_header('Content-Length',str(len(data)))
            handler.send_header('Cache-Control','no-store')
            handler.end_headers()
            if handler.command != 'HEAD':
                handler.wfile.write(data)
            return
        if path == '/banana35b/state':
            with lab.LOCK:
                return handler.send_json(dict(lab.STATE))
        return handler.send_error(404)
    except (ValueError, OSError, ImportError) as error:
        return handler.send_json({'error':str(error)},503)

def post(handler, path, backend, gpu_lock, restart_lock, restart_request):
    if backend.PORT != 8193 or sys.platform != 'win32':
        return handler.send_error(404)
    try:
        _auth(handler)
        lab = load()
        if path == '/banana35b/run':
            body = json.loads(handler.read_body(100_000_000))
            if not isinstance(body,dict):
                raise ValueError('請求須為 JSON 物件。')
            start(lab,backend,gpu_lock,body,restart_lock,restart_request)
        elif path == '/banana35b/cancel':
            lab.cancel()
        else:
            return handler.send_error(404)
        return handler.send_json({'ok':True})
    except Exception as error:
        return handler.send_json({'error':str(error)},400)
