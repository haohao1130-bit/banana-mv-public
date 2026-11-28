"""5070 optional director transport. Same Python commission, same validators, different LLM."""
import base64
import importlib.util
import io
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(r'F:\BANANA35B')

def options(request):
    engine = request.get('director_engine', '9b')
    if engine not in ('9b', '35b'):
        raise ValueError('未知導演引擎。')
    if engine == '9b':
        return None
    o = {'ctx': request.get('director35_context', 16384),
         'moe': request.get('director35_cpu_moe', 36),
         'kv': request.get('director35_kv', 'q8_0'),
         'mtp': request.get('director35_mtp', True),
         'max_tokens': request.get('director35_output', 4096)}
    if (type(o['ctx']) is not int or o['ctx'] not in (8192,16384,32768)
            or type(o['moe']) is not int or not 24 <= o['moe'] <= 40
            or o['kv'] not in ('q8_0','q4_0','f16')
            or type(o['mtp']) is not bool
            or type(o['max_tokens']) is not int or not 512 <= o['max_tokens'] <= 16384
            or o['max_tokens'] + 64 >= o['ctx']):
        raise ValueError('35B context / CPU experts / KV / MTP / output 設定無效。')
    return o

def load():
    # Separate module instance: lab Cancel cannot stop a formal MV director.
    if not (ROOT/'installed.json').is_file() or not (ROOT/'banana35.py').is_file():
        raise ValueError('請先安裝 BANANA35B V2 及模型。')
    spec = importlib.util.spec_from_file_location('_banana35b_formal', ROOT/'banana35.py')
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    if getattr(lab,'BRIDGE_VERSION',0) != 2:
        raise ValueError('請先套用 BANANA35B V2 8193 更新包。')
    return lab

def preflight():
    lab = load()
    lab.executable()
    for name in (lab.MODEL,lab.MM):
        lab.check_gguf(lab.ROOT/'models'/name)

def messages(system, parts):
    content = []
    for kind,value in parts:
        if kind == 'text':
            content.append({'type':'text','text':value})
        elif kind == 'image':
            buf = io.BytesIO()
            value.convert('RGB').save(buf,format='JPEG',quality=92)
            content.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode('ascii')}})
        else:
            raise ValueError('35B 不支援的導演素材：'+str(kind))
    if not any(x['type']=='image_url' for x in content):
        content = '\n'.join(x['text'] for x in content)
    return [{'role':'system','content':system},{'role':'user','content':content}]

def rewrite(cfg,system,parts,job_id,stopped):
    from banana_mv import services as backend
    lab = load()
    o = dict(cfg['director35'])
    msg = messages(system,parts)
    vision = isinstance(msg[1]['content'],list)
    o.update(vision=vision, thinking=bool(cfg['rewriter']['thinking']), seed=secrets.randbelow(2**31))
    if o['thinking']:
        o['max_tokens'] = min(cfg['rewriter']['max_length'], o['ctx']-1024)
    # Use the existing verified runtime. V2 lab args_for disallows MTP+vision,
    # so construct the combined experimental command explicitly. No fallback.
    p = lab.executable()
    argv = lab.args_for(dict(o,vision=False),p)
    if vision:
        mm = lab.ROOT/'models'/lab.MM
        lab.check_gguf(mm)
        argv = [v for v in argv if v != '--no-mmproj'] + ['--mmproj',str(mm)]
    run = ROOT/'runs'/('mv_'+time.strftime('%Y%m%d_%H%M%S')+'_'+job_id+'_'+secrets.token_hex(3))
    run.mkdir(parents=True)
    lab.save(run/'settings.json',dict(o,argv=argv))
    lab.save(run/'messages.json',msg)
    monitor_stop=threading.Event()
    monitor=None
    def guard():
        q=backend.comfy(cfg,'/queue',timeout=4)
        if not all(isinstance(q.get(k),list) for k in ('queue_running','queue_pending')):
            raise RuntimeError('無法確認 ComfyUI 工作佇列。')
        if q['queue_running'] or q['queue_pending']:
            raise RuntimeError('ComfyUI 工作衝突，停止35B。')
    def watch():
        while not monitor_stop.wait(1):
            if stopped.is_set():
                lab.STOP.set()
                lab.stop_process()
                return
            try:
                guard()
                if lab.gpu()['free_mib'] < 700:
                    raise RuntimeError('35B 剩餘顯存低於 700 MiB，請增加 CPU 專家層數。')
            except Exception as e:
                (run/'guard_error.txt').write_text(str(e),encoding='utf-8')
                lab.STOP.set()
                lab.stop_process()
                return
    try:
        target=urlparse(cfg['comfy_url'])
        if backend.PORT!=8193 or sys.platform!='win32' or target.hostname not in ('127.0.0.1','localhost') or target.port!=8000:
            raise ValueError('35B 僅支援 Windows 5070 本機版。')
        if lab.port_in_use(8091) or lab.port_in_use(8092):
            raise RuntimeError('請先關閉獨立35B實驗室；不接管既有程序。')
        if stopped.is_set():
            raise InterruptedError('已停止35B。')
        guard()
        backend.comfy(cfg,'/free',{'unload_models':True,'free_memory':True},timeout=30)
        until=time.monotonic()+30
        while lab.gpu()['free_mib']<10500:
            if stopped.wait(1):raise InterruptedError('已停止35B。')
            if time.monotonic()>until:raise RuntimeError('顯存未回收至10500 MiB；停止35B。')
        lab.save(run/'gpu_before.json',lab.gpu())
        with (run/'llama_server.log').open('wb') as log:
            if stopped.is_set():raise InterruptedError('已停止35B。')
            lab.PROC=subprocess.Popen(argv,cwd=p.parent,env=lab.runtime_env(p),stdout=log,stderr=subprocess.STDOUT)
            monitor=threading.Thread(target=watch,daemon=True)
            monitor.start()
            until=time.monotonic()+600
            while time.monotonic()<until:
                if stopped.is_set() or lab.STOP.is_set():raise InterruptedError('35B 停止／顯存保護。')
                if lab.PROC is None or lab.PROC.poll() is not None:
                    raise RuntimeError('35B 啟動失敗，請檢查 '+str(run/'llama_server.log'))
                try:
                    if lab.local_json('/health',timeout=2).get('status')=='ok':break
                except Exception:pass
                time.sleep(.5)
            else:raise TimeoutError('35B 載入逾時。')
            for attempt in range(2):
                if stopped.is_set() or lab.STOP.is_set():raise InterruptedError('已停止35B。')
                out,metrics=lab.stream_call(msg,o,run,0,attempt)
                if stopped.is_set() or lab.STOP.is_set():raise InterruptedError('已停止35B。')
                if out:
                    (run/'formal.txt').write_text(out,encoding='utf-8')
                    return out
                if not o['thinking']:break
            raise ValueError('35B 正式稿空白（思考關閉重試後仍失敗）。')
    except Exception as e:
        (run/'error.txt').write_text(str(e),encoding='utf-8')
        if stopped.is_set():raise InterruptedError('已停止35B。') from e
        raise RuntimeError('35B 導演失敗（未切回9B）：'+str(e)+'；紀錄 '+str(run)) from e
    finally:
        monitor_stop.set()
        if monitor:monitor.join(20)
        lab.stop_process()
        try:lab.save(run/'gpu_after.json',lab.gpu())
        except Exception:pass
