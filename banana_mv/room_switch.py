"""Local 5070 handoff between the two installed desktop launchers."""
import os
from pathlib import Path
import subprocess
import threading
from urllib.parse import urlsplit


def launcher(target, port):
    if os.name != 'nt' or port != 8193:
        return None
    local = os.environ.get('LOCALAPPDATA')
    candidates = []
    if target == 'film':
        if local:
            candidates.append(Path(local) / 'BananaFilm-5070-CU130-Launcher' / 'Bootstrap_BANANA_FILM_5070.ps1')
        candidates.append(Path(r'F:\AI\BANANA_FILM_5070_STUDIO\Launcher\Bootstrap_BANANA_FILM_5070.ps1'))
    elif target == 'mv' and local:
        candidates.append(Path(local) / 'BananaMV-5070-CU130-Launcher' / 'Launch_Banana_5070.ps1')
    return next((path for path in candidates if path.is_file()), None)


def switch(handler, target, backend, gpu_lock):
    path = launcher(target, backend.PORT)
    if not path:
        return handler.send_json({'ok': False, 'error': '找不到另一套 5070 桌面啟動器。'}, 503)
    origin = urlsplit(handler.headers.get('Origin', ''))
    hosts = [handler.headers.get(name, '').casefold() for name in ('Host', 'X-Forwarded-Host')]
    if (origin.scheme not in ('http', 'https') or not origin.netloc
            or origin.netloc.casefold() not in hosts
            or handler.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none')
            or handler.headers.get('X-Banana-Control') != '5070-room-switch'):
        return handler.send_json({'ok': False, 'error': '切換請求來源無效。'}, 403)
    if not gpu_lock.acquire(blocking=False):
        return handler.send_json({'ok': False, 'error': '作品處理中，請等完成再切換。'}, 409)
    try:
        queue = backend.comfy(backend.load_config(), '/queue')
        if not isinstance(queue, dict) or queue.get('queue_running') or queue.get('queue_pending'):
            gpu_lock.release()
            return handler.send_json({'ok': False, 'error': 'ComfyUI 還有任務。'}, 409)
        script = str(path).replace("'", "''")
        args = ' -Port 8193 -NoBrowser' if target == 'film' else ''
        command = (f'Wait-Process -Id {os.getpid()} -Timeout 30 -ErrorAction Stop; '
                   f"& '{script}'{args}")
        subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
    except Exception:
        gpu_lock.release()
        return handler.send_json({'ok': False, 'error': '無法確認佇列或啟動另一個服務。'}, 503)
    try:
        return handler.send_json({'ok': True}, 202)
    finally:
        threading.Thread(target=handler.server.shutdown, daemon=True).start()
