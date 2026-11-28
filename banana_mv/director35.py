"""5070 optional director transport. Same Python commission, same validators, different LLM."""
import base64
import importlib.util
import io
import json
import math
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

# Read-only telemetry for the existing 8193 dashboard; no GPU work or polling here.
_STATS_LOCK = threading.Lock()
_STATS = {}

def _stats(**values):
    with _STATS_LOCK:
        _STATS.update(values)

def snapshot():
    with _STATS_LOCK:
        state = dict(_STATS)
    if state.get('active'):
        state['elapsed_s'] = round(time.monotonic()-state['started'],1)
    state.pop('started',None)
    return state

def _number(value):
    return value if type(value) in (int,float) and math.isfinite(value) and value >= 0 else None

def _stream_stats(event, stage, first=None):
    values = {'stage':stage}
    p = event.get('prompt_progress')
    if isinstance(p,dict):
        total,processed,cache,ms = (_number(p.get(k)) for k in ('total','processed','cache','time_ms'))
        values.update(prompt_total=total,prompt_processed=processed,prompt_cache=cache)
        if ms and processed is not None and cache is not None and processed >= cache:
            values['prefill_tps'] = (processed-cache)*1000/ms
    t = event.get('timings')
    if isinstance(t,dict):
        for src,dst in (('prompt_n','prompt_evaluated'),('predicted_n','output_tokens'),('draft_n','draft_n'),('draft_n_accepted','draft_accepted')):
            v = _number(t.get(src))
            if v is not None:values[dst]=v
        for src,dst,mskey in (('prompt_per_second','prefill_tps','prompt_ms'),('predicted_per_second','decode_tps','predicted_ms')):
            v = _number(t.get(src))
            if v is not None and (_number(t.get(mskey)) or 0)>0:values[dst]=v
        if values.get('draft_n'):
            accepted=values.get('draft_accepted')
            if accepted is not None:values['mtp_accept_pct']=100*accepted/values['draft_n']
    if first is not None:values['ttft_s']=first
    _stats(**values)

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

def stream_call(lab, msg, o, run, attempt, sampling):
    """Keep the original caller's sampling/repair settings, save raw SSE and formal output."""
    from urllib.request import Request
    thinking = o['thinking'] and attempt == 0
    kwargs = {'enable_thinking':thinking}
    _stats(stage='prefill',attempt=attempt+1,thinking=thinking,prompt_total=None,prompt_processed=None,prompt_cache=None,prompt_evaluated=None,prefill_tps=None,decode_tps=None,output_tokens=0,draft_n=None,draft_accepted=None,mtp_accept_pct=None,ttft_s=None)
    if not o['vision']:
        rendered = lab.local_json('/apply-template',{'messages':msg,'chat_template_kwargs':kwargs,'add_generation_prompt':True})
        prompt = rendered.get('prompt')
        if not isinstance(prompt,str):raise RuntimeError('無法取得完整文字模板。')
        tokens = lab.local_json('/tokenize',{'content':prompt,'add_special':False,'parse_special':True}).get('tokens')
        if not isinstance(tokens,list):raise RuntimeError('無法取得 prompt tokens。')
        _stats(prompt_total=len(tokens))
        if len(tokens)+o['max_tokens']+64>o['ctx']:
            raise RuntimeError(f"Context 不足：{len(tokens)} + {o['max_tokens']} + 64 > {o['ctx']}。請增加 context 或減少生成上限。")
    payload={'model':'banana35b','messages':msg,'stream':True,'stream_options':{'include_usage':True},'timings_per_token':True,'return_progress':True,
             'max_tokens':o['max_tokens'],'temperature':float(sampling.get('temperature',.7)),
             'top_p':float(sampling.get('top_p',.8)),'top_k':int(sampling.get('top_k',20)),
             'seed':o['seed'],'chat_template_kwargs':kwargs,'cache_prompt':False}
    if 'presence_penalty' in sampling:payload['presence_penalty']=float(sampling['presence_penalty'])
    started=time.monotonic();first=None;out='';reason='';metrics={};finish=None;done=False
    request=Request(lab.BASE+'/v1/chat/completions',data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
    with (run/f'attempt{attempt+1}_raw.sse').open('wb') as raw, lab.OPENER.open(request,timeout=600) as response:
        for line in response:
            raw.write(line);raw.flush()
            if lab.STOP.is_set():raise InterruptedError('35B 已停止。')
            if not line.startswith(b'data:'):continue
            data=line[5:].strip()
            if data==b'[DONE]':done=True;break
            event=json.loads(data)
            if event.get('error'):raise RuntimeError(str(event['error']))
            for key in ('usage','timings'):
                if event.get(key):metrics[key]=event[key]
            for c in event.get('choices',[]):
                d=c.get('delta',{});r=d.get('reasoning_content') or d.get('reasoning') or '';t=d.get('content') or ''
                if (r or t) and first is None:first=time.monotonic()-started
                reason+=r;out+=t;finish=c.get('finish_reason') or finish
            stage = 'prefill'
            if first is not None:
                stage = 'thinking' if thinking and (not out or ('<think>' in out and '</think>' not in out)) else 'writing'
            _stream_stats(event,stage,first)
    if '</think>' in out:
        prefix,out=out.rsplit('</think>',1);reason+=prefix
    elif '<think>' in out:
        reason+=out;out=''
    metrics.update(ttft_s=first,wall_s=time.monotonic()-started,finish_reason=finish,sse_done=done,thinking=thinking)
    (run/f'attempt{attempt+1}_thinking.txt').write_text(reason,encoding='utf-8')
    (run/f'attempt{attempt+1}_formal.txt').write_text(out,encoding='utf-8')
    lab.save(run/f'attempt{attempt+1}_metrics.json',metrics)
    if finish!='stop' and not (finish=='length' and thinking and not out.strip()):
        raise RuntimeError('35B 未完整交稿：'+str(finish)+'；請調高生成上限或 context。')
    return out.strip(),metrics

def rewrite(cfg,system,parts,job_id,stopped):
    started=time.monotonic()
    with _STATS_LOCK:
        _STATS.clear()
        _STATS.update(active=True,stage='loading',started=started,mtp=cfg['director35']['mtp'],thinking=bool(cfg['rewriter']['thinking']),context=cfg['director35']['ctx'],cpu_moe=cfg['director35']['moe'],budget=cfg['director35']['max_tokens'],attempt=1)
    outcome='done'
    try:
        return _rewrite(cfg,system,parts,job_id,stopped)
    except Exception:
        outcome='cancelled' if stopped.is_set() else 'error'
        raise
    finally:
        _stats(active=False,stage=outcome,elapsed_s=round(time.monotonic()-started,1))

def _rewrite(cfg,system,parts,job_id,stopped):
    from banana_mv import services as backend
    lab = load()
    o = dict(cfg['director35'])
    msg = messages(system,parts)
    vision = isinstance(msg[1]['content'],list)
    _stats(vision=vision)
    o.update(vision=vision, thinking=bool(cfg['rewriter']['thinking']), seed=secrets.randbelow(2**31))
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
                out,metrics=stream_call(lab,msg,o,run,attempt,cfg['rewriter'])
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
        _stats(stage='unloading')
        monitor_stop.set()
        if monitor:monitor.join(20)
        lab.stop_process()
        try:lab.save(run/'gpu_after.json',lab.gpu())
        except Exception:pass
