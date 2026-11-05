"""Banana's small ComfyUI HTTP client; no websocket or frontend dependency."""
import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

CLIENT_ID = 'banana-' + uuid.uuid4().hex


def comfy(cfg, path, payload=None, timeout=60):
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(cfg['comfy_url'].rstrip('/') + path, data=body,
                                     headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            if not raw.strip():
                # ComfyUI /free acknowledges with HTTP 200 and no JSON body.
                if path == '/free' and payload is not None:
                    return {}
                raise RuntimeError(f'ComfyUI {path} 回傳空內容（HTTP {response.status}），請檢查 ComfyUI 是否仍在執行。')
            try:
                result = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError):
                kind = response.headers.get('Content-Type', 'unknown')
                raise RuntimeError(f'ComfyUI {path} 回傳非 JSON（HTTP {response.status}，{kind}），請檢查服務與代理連線。') from None
            if not isinstance(result, dict):
                raise RuntimeError(f'ComfyUI {path} 回應不是預期的 JSON 物件。')
            return result
    except urllib.error.HTTPError as error:
        detail = error.read(4000).decode('utf-8', errors='replace')
        raise RuntimeError(f'ComfyUI HTTP {error.code}: {detail}') from None


def queue_prompt(cfg, graph):
    result = comfy(cfg, '/prompt', {'prompt': graph, 'client_id': CLIENT_ID})
    if result.get('error') or not result.get('prompt_id'):
        raise RuntimeError('ComfyUI 拒絕工作流：' + json.dumps(result, ensure_ascii=False)[:4000])
    return result['prompt_id']


def history_entry(cfg, prompt_id):
    key = urllib.parse.quote(str(prompt_id), safe='')
    return comfy(cfg, '/history/' + key).get(str(prompt_id))


def execution_error(entry):
    for event in entry.get('status', {}).get('messages', []):
        if len(event) == 2 and event[0] == 'execution_error':
            info = event[1]
            return f"{info.get('node_type', 'ComfyUI')}: {info.get('exception_message', '').strip()}"
    return 'ComfyUI 生成失敗，請查看 comfyui.log。'


def wait_prompt(cfg, prompt_id, timeout=1800):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entry = history_entry(cfg, prompt_id)
        if entry:
            status = entry.get('status', {})
            if status.get('status_str') == 'error':
                raise RuntimeError(execution_error(entry))
            if status.get('completed'):
                return entry
        time.sleep(1)
    raise RuntimeError('等待 ComfyUI 逾時；未取消伺服器上的工作，請先檢查佇列。')


def comfy_download(cfg, fileinfo, dest):
    query = urllib.parse.urlencode({key: fileinfo.get(key, default) for key, default in
                                    [('filename', ''), ('subfolder', ''), ('type', 'output')]})
    with urllib.request.urlopen(cfg['comfy_url'].rstrip('/') + '/view?' + query, timeout=600) as response:
        with open(dest, 'wb') as output:
            shutil.copyfileobj(response, output)
