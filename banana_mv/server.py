"""Standalone Banana MV server: own assets, HTTP client and local prompt rewriting."""
import copy
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if __name__=='__main__':
    sys.modules['banana_mv.server']=sys.modules[__name__]
from banana_mv.director import director_prompt
from banana_mv import anti_jelly
from banana_mv.core import (FPS, H3_NVFP4_MODEL, H3_REF2VA_TURBO_LORA, ACTION_LORA_FILES, DANCE_LORA_SPECS, action_lora_mounts,
                            normalize_action_loras, align_frames, assemble, audio_window, build_workflow, dimensions,
                            duration, enforce_face_identity, fallback_prompt, last_frame, last_frames,
                            output_dimensions, reference_images, segments, trim_video, probe,
                            source_audio_duration)

from banana_mv import services as backend
from banana_mv.http_server import WebHandler
from banana_mv.live_progress import LiveProgress
from banana_mv.fire_monitor import FireMonitor
from banana_mv.lyrics_reference import (normalize_references, clip_reference, clean_lyric_output,
                                        POLICY as LYRIC_POLICY, OUTPUT_POLICY as LYRIC_OUTPUT_POLICY)
from banana_mv.scene_state import (SceneStateError, ensure_scene_state, clip_input, state_context,
                                   plan_clip, save_clip, commit_clip, cached_clip, reconcile_history,
                                   final_context, CLIP_SYSTEM, parse_object as parse_scene_object,
                                   atomic_json as write_scene_json, update_scene_memory, rewrite_retry_count, digest as scene_digest)
from banana_mv.song_context import segment_context
from banana_mv.music_structure import load_structure, local_structure
from banana_mv.audio_analysis import VERSION as AUDIO_VERSION, load_analysis, segment_evidence, audio_guidance, rewrite_evidence
from banana_mv.story_plan import ensure_plan, plan_context
from banana_mv import whole_song
from banana_mv.prompt_quality import (reference_policy, enforce_reference_policy,
                                      clip_scope, enforce_clip_scope, director_led, DIRECTOR_AUTHORITY)

WEB = Path(__file__).parent / 'web'
RUNS = backend.DATA/'banana_mv'
RUNS.mkdir(parents=True, exist_ok=True)
ANALYSIS_CACHE = backend.DATA/'analysis_cache'
GPU_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
CANCEL = set()
# Deliberately separate: do not interrupt H3; finish and save the current clip.
STOP_AFTER_CURRENT = set()
RESTART_LOCK = threading.Lock()
SERVER_INSTANCE = uuid.uuid4().hex
LIVE_PROGRESS = LiveProgress() if backend.PORT == 8193 else None
FIRE_MONITOR = FireMonitor(LIVE_PROGRESS.sampling_state) if LIVE_PROGRESS is not None and sys.platform == 'win32' else None
RESTART_REQUEST = backend.DATA / 'restart-request.json'
RESTART_HEARTBEAT = backend.DATA / 'restart-controller.heartbeat'


def detect_build_version():
    """Report the running checkout at server startup; never invent a release number."""
    root = Path(__file__).resolve().parents[1]
    if not (root / '.git').exists():
        return {'branch': 'unknown', 'commit': 'unknown'}

    def git(*args):
        try:
            result = subprocess.run(['git', *args], cwd=root, check=True,
                                    capture_output=True, text=True, timeout=2)
            return result.stdout.strip() or 'unknown'
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return 'unknown'

    return {'branch': git('symbolic-ref', '--quiet', '--short', 'HEAD'),
            'commit': git('rev-parse', '--short=9', 'HEAD')}


SERVER_BUILD = detect_build_version()


def restart_capability():
    """The button is live only while the external desktop supervisor is alive."""
    enabled = (backend.PORT == 8193 and
               os.environ.get('BANANA_SUPERVISED_RESTART') == '1')
    if enabled:
        try:
            enabled = time.time() - RESTART_HEARTBEAT.stat().st_mtime < 12
        except OSError:
            enabled = False
    return {'available': enabled, 'busy': GPU_LOCK.locked(),
            'reason': ('5070 桌面管家尚未啟動，請使用 V4 桌面捷徑。' if not enabled
                       else '目前有任務正在執行，請等完成再重啟。' if GPU_LOCK.locked() else '')}


def request_desktop_restart(handler, payload):
    """Request, never execute, a privileged restart; Windows supervisor owns processes."""
    if handler.headers.get('X-Banana-Control') != '5070-restart':
        raise ValueError('缺少本機控制確認標頭。')
    if handler.headers.get('Content-Type','').split(';',1)[0].strip().lower() != 'application/json':
        raise ValueError('請使用 JSON 傳送重新啟動要求。')
    origin = handler.headers.get('Origin', '')
    if not origin or urllib.parse.urlparse(origin).scheme not in ('http','https'):
        raise ValueError('重新啟動只能由 BANANAMV 網頁發起。')
    if handler.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none'):
        raise ValueError('跨網站請求不能控制重新啟動。')
    origin_host = urllib.parse.urlparse(origin).netloc.casefold()
    request_host = handler.headers.get('Host', '').casefold()
    forwarded_host = handler.headers.get('X-Forwarded-Host', '').casefold()
    # Tailscale Serve may forward the original Host or supply X-Forwarded-Host.
    if origin_host not in (request_host, forwarded_host):
        raise ValueError('來源網址不符合目前的 5070 前端。')
    if payload.get('confirm') != 'restart-5070':
        raise ValueError('尚未確認重新啟動。')
    with RESTART_LOCK:
        state = restart_capability()
        if not state['available'] or state['busy']:
            raise ValueError(state['reason'])
        try:
            queue = backend.comfy(backend.load_config(), '/queue')
        except Exception:
            queue = None  # Unreachable ComfyUI can be repaired by its owning supervisor.
        if isinstance(queue, dict) and (queue.get('queue_running') or queue.get('queue_pending')):
            raise ValueError('ComfyUI 還有正在執行或等待的工作，請先完成再重新啟動。')
        if RESTART_REQUEST.exists():
            raise ValueError('重新啟動要求已送出，請勿重複點擊。')
        RESTART_REQUEST.parent.mkdir(parents=True, exist_ok=True)
        tmp = RESTART_REQUEST.with_suffix('.tmp')
        tmp.write_text(json.dumps({'version':1,'issued_at':time.time(),
                                  'instance':SERVER_INSTANCE}),encoding='utf-8')
        tmp.replace(RESTART_REQUEST)
    return {'ok':True,'restarting':True,'instance':SERVER_INSTANCE}


def is_continuation(mode):
    return mode in ('chain', 'chain5')


def write_state(job):
    with STATE_LOCK:
        p = RUNS/job['id']/'status.json'
        tmp = p.with_suffix('.tmp')
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(p)


def job_dir(job_id):
    if not isinstance(job_id, str) or len(job_id)!=12 or any(c not in '0123456789abcdef' for c in job_id):
        raise ValueError('無效的工作編號')
    return RUNS/job_id


def read_state(job_id):
    with STATE_LOCK:
        return json.loads((job_dir(job_id)/'status.json').read_text(encoding='utf-8'))


def progress_config(cfg, job_id):
    if LIVE_PROGRESS is None:
        return cfg
    return dict(cfg, _observe_comfy_prompt=lambda prompt_id, graph:
                LIVE_PROGRESS.queued(job_id, prompt_id, graph))


def clear_progress(job_id):
    if LIVE_PROGRESS is not None:
        LIVE_PROGRESS.clear(job_id)


def preflight(cfg, graph):
    # Only remove the 9B-specific preflight pair, never H3 CLIPLoader nodes.
    if cfg.get('director35') is not None and graph.get('encoder',{}).get('class_type') == 'CLIPLoader' and graph.get('generate',{}).get('class_type') == 'TextGenerate':
        graph = {key: node for key,node in graph.items() if key not in ('encoder','generate')}
        if not graph:
            return
    info = backend.comfy(cfg, '/object_info')
    if 'tlu_repair' in graph:
        anti_jelly.require_capability(info)
    missing = sorted({n['class_type'] for n in graph.values()} - set(info))
    if missing:
        raise ValueError('缺少節點，請重跑安裝並重啟：' + ', '.join(missing))
    for n in graph.values():
        fields = {'UNETLoader':'unet_name','CLIPLoader':'clip_name','VAELoader':'vae_name',
                  'LoraLoaderModelOnly':'lora_name', 'ModelAttentionBackend':'attention'}
        if n['class_type'] in fields:
            name = fields[n['class_type']]
            if name == 'lora_name' and n['inputs'][name] in {spec[0] for spec in DANCE_LORA_SPECS.values()}:
                if n['inputs'][name] not in anti_jelly._combo_options(info, n['class_type'], name):
                    raise ValueError('舞蹈 LoRA 找不到：' + n['inputs'][name] +
                                     '。請執行舞蹈模型安裝包並重啟 ComfyUI。')
                continue
            choices = info[n['class_type']]['input']['required'][name][0]
            if isinstance(choices,list) and n['inputs'][name] not in choices:
                if name == 'attention':
                    raise ValueError('Kitchen INT8 注意力不可用，請重跑安裝並重啟，或關閉注意力加速。')
                if name == 'unet_name' and n['inputs'][name] == H3_NVFP4_MODEL:
                    raise ValueError(r'ComfyUI 找不到 H3 NVFP4。請執行一鍵安裝包或將模型放到 F:\AI\Models\diffusion_models，再重啟 ComfyUI。')
                if name == 'lora_name' and n['inputs'][name] == H3_REF2VA_TURBO_LORA:
                    raise ValueError(r'ComfyUI 找不到 Ref2VA Turbo LoRA。請執行 Install_H3_Ref2VA_Turbo8.bat，把檔案裝到 F:\AI\Models\loras，再重啟 ComfyUI。')
                if name == 'lora_name' and n['inputs'][name] in (ACTION_LORA_FILES['fight_flow'], ACTION_LORA_FILES['repair_v2']):
                    raise ValueError('ComfyUI 找不到動作 LoRA：' + n['inputs'][name] +
                                     r'。請執行 tools\install_action_loras.py，或放到 F:\AI\Models\loras 後重啟 ComfyUI；'
                                     '也可以先在「動作 LoRA 控制台」關掉這顆再開爐。')
                raise ValueError('尚未下載模型：' + n['inputs'][name] + '；請重跑 Colab ② 下載模型。')


def graph_options(req, seconds, segment=None, *, edited_prompt=False):
    if req.get("realism_lora"):
        raise ValueError("fal 真人 LoRA 已移除；此舊專案曾啟用 fal，請另建不使用 fal 的專案，避免續跑混用設定。")
    _, mode = director_prompt(req, seconds, segment)
    for field in ('acceleration', 'kitchen_attention', 'sparse_attention', 'motion_lora', 'h3_nvfp4', 'h3_ref2va_turbo'):
        if field in req and not isinstance(req[field], bool):
            raise ValueError(field + ' 必須為布林值。')
    repair = req.get('anti_jelly', False)
    if not isinstance(repair, bool):
        raise ValueError('anti_jelly 必須為布林值。')
    repair_sparse = req.get('anti_jelly_sparse', False)
    if not isinstance(repair_sparse, bool):
        raise ValueError('anti_jelly_sparse 必須為布林值。')
    repair_sparse_final = req.get('anti_jelly_sparse_final', False)
    if not isinstance(repair_sparse_final, bool):
        raise ValueError('anti_jelly_sparse_final 必須為布林值。')
    if repair:
        anti_jelly.validate_request(req, local5070=backend.PORT == 8193)
    h3_nvfp4 = req.get('h3_nvfp4', False)
    h3_ref2va_turbo = req.get('h3_ref2va_turbo', False)
    steps = req.get('sampling_steps', 8)
    if h3_ref2va_turbo and (not h3_nvfp4 or steps != 8):
        raise ValueError('Ref2VA Turbo 須搭配 NVFP4 並使用 8 步。')
    allowed_steps = (4, 6, 8, 10) if h3_nvfp4 else (4, 6, 8, 10, 12)
    if isinstance(steps, bool) or steps not in allowed_steps:
        model = 'H3 NVFP4' if h3_nvfp4 else 'PRISM INT8'
        supported = '、'.join(map(str, allowed_steps))
        raise ValueError(f'{model} 採樣步數支援 {supported} 步。')
    native = {}
    if req.get('native_sound'):
        cues = req.get('native_sound_cues')
        if cues:
            if segment is not None and (cue := cues.get(str(segment['index'] + 1))):
                native['native_sound'] = cue
        else:
            native['native_sound'] = True
            if segment is not None and req.get('rewrite', True) and not edited_prompt:
                native['native_sound_event'] = segment.get('director_plan', {}).get('event')
    return {'steps': int(steps), 'h3_nvfp4': h3_nvfp4, 'h3_ref2va_turbo': h3_ref2va_turbo,
            'acceleration': req.get('acceleration', True),
            'kitchen_attention': req.get('kitchen_attention',req.get('acceleration',True)),
            'sparse_attention': req.get('sparse_attention',req.get('acceleration',True)),
            'motion_lora': req.get('motion_lora', True),
            'director_mode': mode, 'intensity': req.get('intensity', 'high'),
            # 新的動作 LoRA 控制台；舊專案沒有這欄，照舊走 motion_lora。
            **({'action_loras': normalize_action_loras(req['action_loras'])} if 'action_loras' in req else {}),
            **({'anti_jelly': True,
                **({'anti_jelly_sparse': True} if repair_sparse else {}),
                **({'anti_jelly_sparse_final': True} if repair_sparse and repair_sparse_final else {})} if repair else {}),
            **native}


def preflight_five_frame(cfg, req, images, size, seg, seed):
    """Fail before filming if the selected H3 five-frame guide nodes are absent."""
    if req.get('mode') != 'chain5':
        return
    guide = ['__banana_last5_preflight.png'] * 5
    graph = build_workflow(images, 'preflight.wav', *size,
        align_frames(max(124, seg['frames'] + 5)), '', seed,
        guide[0], guide_frames=guide, **graph_options(req, seg['seconds'], seg))
    preflight(cfg, graph)


def local_prompt(cfg, req, segment, original, tail, *, scene_input=None, event_catalog=None,progress=None):
    # Only local model calls; never silently fall back to a paid API.
    if req.get('director_schema') == whole_song.DIRECT_SCRIPT:
        segment['director_mode'] = segment['director_plan']['mode']
        segment['prompt_profile'] = {'source':'python_direct_script', 'writer_calls':0, 'contract_check_calls':0}
        return whole_song.direct_script_prompt(req, segment, len(original) if isinstance(original, list) else 1, tail)
    if req.get('director_schema') == whole_song.VERSION:
        segment['director_mode'] = segment['director_plan']['mode']
        segment['prompt_profile'] = {'source':'whole_song_director', 'writer_calls':0, 'contract_check_calls':0}
        return whole_song.h3_prompt(req, segment, len(original) if isinstance(original, list) else 1, tail)
    if req.get('director_schema') in (5,6) and req.get('rewrite',True):
        from banana_mv.shoot_plan import write_shoot_prompt
        originals=original if isinstance(original,list) else [original]
        return write_shoot_prompt(cfg,req,segment,originals,tail,backend.rewrite_local,progress)
    if req.get('director_schema')==4 and req.get('rewrite',True):
        from banana_mv.core import normalize_mv_prompt
        originals=original if isinstance(original,list) else [original]
        segment['director_mode']=segment['director_plan']['mode']
        return normalize_mv_prompt(segment['director_plan']['prompt'],len(originals)+int(bool(tail)))
    if req.get('director_schema')==3 and req.get('rewrite',True):
        from banana_mv.prompt_quality import write_directed_clip
        originals=original if isinstance(original,list) else [original]
        return write_directed_clip(cfg,req,segment,originals,tail,scene_input=scene_input,
                                   event_catalog=event_catalog,progress=progress)
    director, mode = director_prompt(req, segment['seconds'], segment)
    if scene_input is not None:
        director=director.replace('Preserve costumes, locations and source audio; do not invent lyrics.',
                                  'Preserve current scene-state appearance, locations and source audio; follow explicit appearance changes and do not invent lyrics.')
    segment['director_mode'] = mode
    originals = original if isinstance(original, list) else [original]
    from banana_mv.core import normalize_mv_prompt, map_image_mentions, MediaReferenceError
    picture_count = len(originals) + int(bool(tail))
    optimize = req.get('optimizer_version',0) >= 1
    roles = reference_policy(picture_count,bool(tail),mutable_appearance=scene_input is not None) if optimize else ''
    brief = map_image_mentions(req['prompt'],len(originals),bool(tail))
    # Reject incorrect user references before asking the model to rewrite them.
    if brief.strip():
        normalize_mv_prompt(brief, picture_count)
    creative = director_led(req)
    scope = clip_scope(segment,brief,creative) if optimize else ''
    if 'project_scope' in req:
        from banana_mv.mv_scope import clip_ending
        scope=json.dumps(clip_ending(req,segment),ensure_ascii=False)
    context = segment_context(segment)
    allocation = plan_context(segment,creative)
    if allocation:
        context += '\n\n' + allocation
    evidence = segment.get('audio_evidence')
    audio_direction = audio_guidance(evidence) if evidence else ''
    def finalize(text):
        if context:
            text += '\n\n' + context
        if audio_direction:
            text += '\n\n' + audio_direction
        if scope:
            text = enforce_clip_scope(text,scope)
        if roles:
            text = enforce_reference_policy(text,roles)
        if req.get('face_identity', True):
            text = enforce_face_identity(text, 2 if tail else 1)
        if req.get('lyrics_reference_version') and (req.get('lyrics') or req.get('srt_reference')):
            text,removed = clean_lyric_output(text,req)
            segment['lyric_reference_cleanup']={'removed_spans':removed}
            text += '\n\n'+LYRIC_OUTPUT_POLICY
        if scene_input is not None:
            text += '\n\n'+final_context(segment['scene_state_debug'])
        return normalize_mv_prompt(text, picture_count)
    fallback_lyrics = '' if req.get('lyrics_reference_version') else req.get('lyrics','')
    prompt = fallback_prompt(req['prompt'], bool(tail), fallback_lyrics, len(originals),scene_aware=optimize)
    if not req.get('rewrite', True):
        if optimize:
            segment.pop('prompt_review',None)
            segment['prompt_validation']={'status':'passed','kind':'technical_only'}
        return finalize(prompt + '\n\n' + director)
    from PIL import Image, ImageOps
    refs = ([tail] if tail else []) + originals
    target=segment['seconds'] if optimize else segment['model_frames']/FPS
    if optimize:
        prompt=('WHOLE-SONG USER REFERENCE — NOT THE CURRENT CLIP SCRIPT:\n'
                +brief+'\nEND WHOLE-SONG USER REFERENCE.\n'
                +'Use this reference to preserve identities, scene rules and original story requirements. '
                'Only the assigned current event belongs in the generated summary and shots; '
                'future events and the ending remain reference until their source interval.\n'+scope)
        if req.get('lyrics') and not req.get('lyrics_reference_version'):
            prompt+='\nUSER LYRICS REFERENCE ONLY (do not add new lyrics):\n'+req['lyrics']
    parts = [('text', f'Target visible duration: {target:.6f} seconds. '
              'The user supplies source audio but you do not receive audio tokens. Do not guess lyrics. '
              'Keep <Audio 1>: fully_copy and synchronize the visible singer to that audio.\n' + prompt
              + '\n\n' + director + ('\n\n' + context if context else ''))]
    lyric_context = clip_reference(req, segment)
    if lyric_context:
        parts.append(('text',lyric_context))
    if scene_input is not None:
        parts.append(('text',state_context(scene_input,event_catalog,bool(tail))))
    if roles:
        parts[0] = ('text',parts[0][1]+'\n\n'+roles)
    if creative:
        parts[0] = ('text',parts[0][1]+'\n\n'+DIRECTOR_AUTHORITY)
    if evidence:
        parts.append(('text', '\n\n' + rewrite_evidence(evidence)))
    for i,p in enumerate(refs,1):
        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im).convert('RGB')
            im.thumbnail((768,768))
            parts += [('text', f'<Picture {i}>:'), ('image', im.copy())]
    guide = Path(cfg['guides']['ref']).read_text(encoding='utf-8')
    guide += (f'\nConnected media: {picture_count} pictures, one audio, ZERO reference videos. '
              'Use only connected Picture tags and <Audio 1>. Refer to the output as '
              'the generated clip in plain text, never as a Video media tag. '
              'Subject numbers are character identifiers, not picture numbers. Additional characters '
              'permitted by the brief may be generated without reference images: describe their appearance '
              'and role in plain text. Never invent a Picture tag for an unreferenced character, location '
              'or prop, and never bind them to an existing reference belonging to someone else.')
    if optimize:
        guide += ('\nOUTPUT SCOPE OVERRIDE: Rewrite ONLY this clip, never the whole-song reference. '
                  'Every summary sentence and shot must belong to the current source interval. '
                  'Preserve user requirements; do not execute reserved future events.\n'+scope)
    if creative:
        guide += '\n'+DIRECTOR_AUTHORITY
    if lyric_context:
        guide += '\nFINAL LYRIC OUTPUT OVERRIDE:\n'+LYRIC_POLICY+'\n'+LYRIC_OUTPUT_POLICY
    if scene_input is not None:
        guide += '\n'+CLIP_SYSTEM
    segment.pop('prompt_reference_repair',None)
    segment.pop('scene_state_rewrite_debug',None)
    state_attempts=[]
    attempt_parts=list(parts)
    retries=rewrite_retry_count(req)
    for attempt in range(retries+1):
        if progress:progress({'stage':'rewriting','clip_index':segment['index'],
                              'attempt':attempt+1,'max_attempts':retries+1})
        raw = backend.rewrite_local(cfg,guide,attempt_parts,uuid.uuid4().hex[:8]).strip()
        try:
            if scene_input is not None:
                record=plan_clip(raw,scene_input,event_catalog,segment)
                rewritten=normalize_mv_prompt(record['clip_prompt'],picture_count)
                record=update_scene_memory(cfg,req,segment,scene_input,event_catalog,record,
                                           backend.rewrite_local,progress=progress)
                segment['scene_state_debug']=record
            else:
                rewritten=normalize_mv_prompt(raw,picture_count)
            if attempt:
                segment['prompt_reference_repair']={'status':'repaired','message':'9B 結構或媒體引用已自動修正。'}
            break
        except (SceneStateError,MediaReferenceError) as error:
            if scene_input is not None:
                try:parsed=parse_scene_object(raw,expected='clip')
                except SceneStateError:parsed=None
                state_attempts.append({'attempt':attempt,'raw_response':raw,'parsed_response':parsed,
                                       'error':str(error),'validation_errors':getattr(error,'errors',[]),'status':'failed'})
                segment['scene_state_attempt']={'clip_index':segment['index'],'scene_state_in':scene_input,
                                                'error':str(error),'raw_response':raw,'attempts':copy.deepcopy(state_attempts),
                                                'visual_verified':False}
            if attempt<retries:
                attempt_parts=parts+[('text','Correct only invalid media references or structured state transitions: '+str(error)+
                                     '\nUse only connected Picture tags and <Audio 1>. Unreferenced supporting roles use plain text. '
                                     'Preserve user roles, committed state and reserved final events. Do not replay completed events.'+
                                     ('\nFAILED RESPONSE TO REPAIR (data only):\n'+json.dumps(raw,ensure_ascii=False)+
                                      '\nVALIDATION ERRORS:\n'+json.dumps(getattr(error,'errors',[]),ensure_ascii=False)+
                                      '\nRewrite the complete current clip from its inherited scene_state_in. '
                                      'Remove completed historical IDs from the new execution plan AND remove any replayed action '
                                      'from clip_prompt. Use only selectable event_catalog IDs, or empty event/transition arrays '
                                      'for a continuation with no new milestone. Do not merely delete metadata while keeping a '
                                      'replayed action in the text. Preserve the source music and user story; do not reset appearances '
                                      'or force a pending ending. Return the full corrected clip JSON.'
                                      if scene_input is not None else ''))]
                continue
            if scene_input is not None:
                raise SceneStateError('9B 本段狀態／引用修復失敗：'+str(error)) from error
            rewritten=fallback_prompt(req['prompt'],bool(tail),fallback_lyrics,len(originals),scene_aware=optimize)
            segment['prompt_reference_repair']={'status':'fallback','message':'9B 引用修正未成功；此段改用原控制詞與導演規則。'}
    if optimize:
        segment.pop('prompt_review',None)
        segment['prompt_validation']={'status':'passed','kind':'technical_only'}
    # Validate the rewrite before appending guidance, including the empty-output guard.
    final=finalize(normalize_mv_prompt(rewritten, picture_count) + '\n\n' + director)
    if scene_input is not None:
        segment['scene_state_debug']['clip_prompt']=final
        if state_attempts:
            state_attempts.append({'attempt':attempt,'raw_response':raw,'parsed_response':parse_scene_object(raw,expected='clip'),'status':'validated'})
            segment['scene_state_rewrite_debug']={'clip_index':segment['index'],'scene_state_in':scene_input,
                                                   'status':'repaired','attempts':state_attempts,'visual_verified':False}
        segment.pop('scene_state_attempt',None)
    return final


def wait_generation(cfg, prompt_id, job):
    deadline = time.monotonic()+7200
    while time.monotonic()<deadline:
        if job['id'] in CANCEL:
            raise InterruptedError('已取消目前段落生成；不採用中斷影片。')
        entry = backend.history_entry(cfg,prompt_id)
        if job['id'] in CANCEL:
            raise InterruptedError('已取消目前段落生成；不採用中斷影片。')
        if entry:
            if entry.get('status',{}).get('status_str')=='error':
                raise RuntimeError(backend.execution_error(entry))
            if entry.get('status',{}).get('completed'):
                return entry
        time.sleep(1)
    raise RuntimeError('單段生成等待超過兩小時；請檢查 ComfyUI 紀錄。')


def stop_after_current_job(job_id):
    """Request a safe pause AFTER the in-flight clip is fully committed.

    The H3 prompt keeps running. Only the worker observes this flag between
    clips; completed video, tail-frame continuity and source files stay intact.
    Emergency stop remains an entirely separate endpoint.
    """
    job = read_state(job_id)
    if job.get('status') not in ('running', 'retaking', 'planning_story',
                                 'planning_state', 'analyzing_audio',
                                 'translating_review'):
        return {'ok': True, 'interruption': 'not_running',
                'message': '目前沒有可在本段完成後停止的拍攝任務。'}
    STOP_AFTER_CURRENT.add(job_id)
    return {'ok': True, 'interruption': 'after_current_requested',
            'message': '已設定：目前這段完整生成並保存後停止；不會立即中斷 H3。'}


def pause_after_committed_clip(job):
    """Only called after this clip's video and continuation frame are saved."""
    if job['id'] not in STOP_AFTER_CURRENT:
        return False
    job['status']='interrupted'
    job['stop_reason']='after_current'
    write_state(job)
    return True


def stop_job(job_id):
    """Stop the current GPU task, not just the next clip.

    Only an active prompt ID owned by this BANANAMV run is targeted.
    Finished clips, saved sources, master versions and other Comfy jobs
    are untouched. The worker acknowledges cancellation and releases GPU_LOCK.
    """
    from banana_mv.comfy import cancel_prompt
    job=read_state(job_id)
    if job.get('status') in ('done','cancelled','error','interrupted','plan_ready'):
        return {'ok':True,'message':'目前沒有正在煉製的段落。','interruption':'not_running'}
    STOP_AFTER_CURRENT.discard(job_id)
    CANCEL.add(job_id)
    backend.request_rewrite_stop()
    pid=None
    if job.get('status')=='retaking':
        i=(job.get('retake') or {}).get('current')
        if isinstance(i,int) and 0<=i<len(job.get('segments',[])):
            take_ids=(job.get('retake') or {}).get('takes',{})
            target=take_ids.get(str(i))
            take=next((x for x in job['segments'][i].get('takes',[])
                       if x.get('id')==target),None)
            if take:pid=take.get('prompt_id')
    else:
        for seg in job.get('segments',[]):
            if seg.get('status')=='generating' and seg.get('prompt_id'):
                pid=seg['prompt_id']
                break
    if not pid:
        pid=backend.active_rewrite_prompt_id()
    if not pid:
        return {'ok':True,'message':'已要求停止；此階段尚未取得 ComfyUI 任務 ID，將停止後續生成。',
                'interruption':'cancel_requested'}
    try:
        cfg=backend.load_config()
        result=cancel_prompt(cfg,pid)
        return {'ok':True,'message':'已要求立即中斷此段；不採用未完成的影片。',
                'interruption':result}
    except Exception as error:
        # The stop flag still prevents later clips. Surface API failure so
        # the user is not falsely told that sampling stopped already.
        return {'ok':True,'message':'已停止後續段落，但目前 ComfyUI 中斷指令未確認：'+str(error),
                'interruption':'api_error'}



def video_info(entry):
    for out in entry.get('outputs',{}).values():
        for key in ('videos','images','gifs'):
            for item in out.get(key,[]):
                if str(item.get('filename','')).lower().endswith(('.mp4','.webm','.mov')):
                    return item
    raise RuntimeError('生成已完成，但沒有找到影片輸出。')


def finished_video_target(job,*,refined_version=None,upscaled_version=None,upscaled_resolution=1080,refined_resolution=None):
    configured = os.environ.get('BANANA_FINISHED_VIDEOS')
    if configured:
        folder = Path(configured)
    elif sys.platform == 'win32' and backend.PORT == 8193:
        folder = Path(r'F:\BANANAMV\videos')
    else:
        folder = backend.DATA / 'videos'
    title=''.join(c for c in str(job.get('title') or 'Banana_MV') if c not in '<>:"/\\|?*' and ord(c)>=32).strip(' .')[:60] or 'Banana_MV'
    suffix=f'_v{job["current_master"]:03d}' if job.get('current_master') else ''
    if refined_version is not None:
        if refined_resolution is not None:
            suffix += f'_{refined_resolution}p'
        suffix += f'_face_refine_v{refined_version:03d}'
    if upscaled_version is not None:
        suffix += f'_{upscaled_resolution}p_v{upscaled_version:03d}'
    return folder/f'{title}_{job["id"]}{suffix}.mp4'


def export_finished_video(job,source,*,refined_version=None,upscaled_version=None,upscaled_resolution=1080,refined_resolution=None):
    """Keep the resumable project master and publish an atomic copy to the finished-video folder."""
    target=finished_video_target(job,refined_version=refined_version,upscaled_version=upscaled_version,
                                 upscaled_resolution=upscaled_resolution,refined_resolution=refined_resolution)
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_name('.'+target.name+'.tmp')
    try:
        shutil.copyfile(source,temp)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    if refined_version is None and upscaled_version is None:
        job['output_video']=str(target)
        job.pop('export_error',None)
    return target


def worker(job, cfg, original, song, drive):
    from banana_mv import face_refine

    app = sys.modules[__name__]
    cfg = progress_config(cfg, job['id'])
    work = job_dir(job['id'])
    inp = Path(cfg['comfy_input_dir'])
    parts, tail, tail_frames = [], None, []
    def rewrite_progress(info):
        job['rewrite_attempt']=info;write_state(job)
    try:
        if job.get('resuming') and job['request'].get('director_schema')==6:
            from banana_mv.python_slots import refresh_stale_timed_plan
            refresh_stale_timed_plan(job,original,work)
        approved_review=bool(job['request'].get('plan_review') and job.get('plan_approved'))
        if approved_review and job['plan_approved']!=plan_revision(job):
            raise ValueError('已確認丹方與保存內容不一致，停止開爐，請重新檢查專案。')
        # Old projects keep their saved prompt behavior. New projects opt in by
        # a persisted request field. Structure inference is CPU-only in an isolated process.
        single_pass = job['request'].get('director_schema') == whole_song.VERSION
        needs_analysis = not approved_review and (single_pass or job['request'].get('audio_analysis', False)) and any(
            not (seg.get('status') == 'done' and valid_part(adopted_part(job,seg), seg, job['size']))
            and not (job.get('resuming') and ((work/f'{seg["index"]:02d}_prompt_v1.txt').is_file() or (work/f'{seg["index"]:02d}_prompt.txt').is_file())
                     and not seg.get('refresh_prompt')) for seg in job['segments'])
        if needs_analysis:
            job['status'] = 'analyzing_audio'; write_state(job)
            shared = ANALYSIS_CACHE   # 同一首歌（SHA-256 相同）跨專案共用分析結果
            music_analysis = load_analysis(song, work/'audio_analysis.json', shared)
            structure = None
            if job['request'].get('music_structure',False):
                job['audio_analysis']={'status':'analyzing_structure'}; write_state(job)
                structure = load_structure(song, work/'music_structure.json', music_analysis['seconds'], shared)
            vocal_analysis = load_analysis(drive, work/'vocal_analysis.json', shared) if drive != song else None
            for seg in job['segments']:
                seg['audio_evidence'] = segment_evidence(music_analysis, seg, vocal_analysis)
                if structure:
                    seg['audio_evidence']['music_structure'] = local_structure(structure, seg)
            job['audio_analysis'] = {'version': AUDIO_VERSION, 'status': 'ready',
                                     'pulse': music_analysis['pulse'],
                                     'structure': {'status':'ready','bpm':structure['bpm'],
                                                   'segments':structure['segments']} if structure else None}
            job['status'] = 'running'; write_state(job)
        direct_script = job['request'].get('director_schema') == whole_song.DIRECT_SCRIPT
        needs_plan = (not approved_review and job['request'].get('director_version', 1) >= 2
                      and (job['request'].get('story_plan', True) or job['request'].get('director_schema') in (3,4,5,6,whole_song.VERSION,whole_song.DIRECT_SCRIPT))
                      and (direct_script or job['request'].get('rewrite', True))
                      and (len(job['segments']) > 1 or job['request'].get('director_schema') in (3,4,5,6,whole_song.VERSION,whole_song.DIRECT_SCRIPT))
                      and any(not (s.get('status') == 'done' and valid_part(adopted_part(job,s), s, job['size']))
                              and not (job.get('resuming') and ((work/f'{s["index"]:02d}_prompt_v1.txt').is_file() or (work/f'{s["index"]:02d}_prompt.txt').is_file())
                                       and not s.get('refresh_prompt')) for s in job['segments']))
        if needs_plan:
            if job['id'] in CANCEL:
                job['status']='cancelled'; write_state(job); return
            job['status']='planning_story'; write_state(job)
            if single_pass:
                plan = whole_song.ensure_whole_song_plan(cfg, job['request'], job['segments'], original, work, backend.rewrite_local)
                if job['id'] in CANCEL:
                    job['status']='cancelled'; write_state(job); return
            elif direct_script or job['request'].get('director_schema')==6:
                from banana_mv.python_slots import ensure_python_slot_plan
                plan = ensure_python_slot_plan(job['request'], job['segments'], original, work)
            else:
                plan = ensure_plan(cfg, job['request'], job['segments'], original, work, backend.rewrite_local)
            for index, (seg, row) in enumerate(zip(job['segments'], plan['segments'])):
                seg['director_plan'] = row
                if plan['version'] in (5,6,whole_song.VERSION):
                    seg.pop('shoot_setup',None)
                    seg['fixed_reference_settings']=plan.get('shared_setup','')
                    seg['direction_ending_contract']=plan['ending_contract']
                if plan['version']==4:
                    seg['prompt']=row['prompt']
                    (work/f'{seg["index"]:02d}_prompt_v1.txt').write_text(row['prompt'],encoding='utf-8')
                    seg['prompt_profile']={'source':'whole_song_director','writer_calls':0,'contract_check_calls':0}
                if plan['version'] in (3,4):
                    seg['direction_constraints']=plan['constraints']
                    seg['direction_closing_shot']=plan['closing_shot']
                    seg['direction_requires_change']=plan['requires_change']
                    if 'project_scope' in plan:
                        seg['direction_ending_plan']=plan.get('ending_plan')
                        seg['direction_ending_contract']=plan['ending_contract']
                if index and plan['version'] not in (5,whole_song.VERSION):
                    seg['previous_planned_event'] = plan['segments'][index-1]['event']
            job['director_plan'] = {'version':plan['version'], 'status':'ready'}
            if direct_script or job['request'].get('plan_review'):
                job['plan_preview_setup']=plan.get('shared_setup','')
            job['status']='running'; write_state(job)
        if job['request'].get('plan_review') and not approved_review:
            if job['id'] in CANCEL:
                job['status']='cancelled';write_state(job);return
            if not all(s.get('director_plan') for s in job['segments']):
                raise ValueError('丹方尚未完整，不能進入審閱或開爐。')
            job.update(status='plan_ready',plan_revision=plan_revision(job))
            write_state(job);return
        ledger=None
        if job['request'].get('scene_state_version')==1:
            if job['id'] in CANCEL:
                job['status']='cancelled';write_state(job);return
            job['status']='planning_state';write_state(job)
            ledger=ensure_scene_state(cfg,job['request'],job['segments'],original,work,backend.rewrite_local,
                                      progress=rewrite_progress)
            reconcile_history(job,work,ledger,lambda s:valid_part(work/f'{s["index"]:02d}_part_v1.mp4' if (work/f'{s["index"]:02d}_part_v1.mp4').is_file() else adopted_part(job,s),s,job['size']))
            job['scene_state_summary']={'version':1,'committed_clips':len(ledger['commits']),'visual_verified':False}
            job['status']='running';write_state(job)
        for seg in job['segments']:
            if job['id'] in CANCEL:
                job['status']='cancelled'; write_state(job); return
            i = seg['index']
            from banana_mv import takes
            try:part=takes.take_source(job,i)
            except ValueError:
                if seg.get('takes') and seg.get('status')=='done':
                    raise ValueError('已採用的丹藥版本檔案遺失，請恢復該版本或另選現存丹藥。')
                part=work/f'{i:02d}_part_v1.mp4'
            if seg.get('status')=='done' and valid_part(part,seg,job['size']):
                if ledger is not None:
                    record=cached_clip(work,ledger,seg)
                    if record is None:raise SceneStateError('已完成影片缺少可繼承的狀態快照，不能猜測或重置。')
                    commit_clip(work,ledger,record)
                    seg['scene_state_debug']=record
                    job['scene_state_summary']['committed_clips']=len(ledger['commits'])
                parts.append(part)
                if is_continuation(job['request']['mode']):
                    guide = face_refine.chained_part(app, cfg, job, seg, part, original, reuse=True)
                    if job['request']['mode'] == 'chain5' and i+1 < len(job['segments']):
                        tail_frames = last_frames(guide, work/f'{i:02d}_last5_%02d.png')
                        shutil.copyfile(tail_frames[-1], work/f'{i:02d}_last.png')
                        tail = tail_frames[0]
                    else:
                        tail = work/f'{i:02d}_last.png'
                        last_frame(guide,tail)
                continue
            seg['status']='preparing'; job['current']=i+1; write_state(job)
            name = f'banana_{job["id"]}_{i}.wav'
            overlap = 5 if job['request']['mode'] == 'chain5' and tail_frames else 0
            render_frames = (align_frames(max(124, seg['frames']+overlap))
                             if overlap else seg['model_frames'])
            audio_window(drive, inp/name, seg['start']-overlap/FPS, render_frames/FPS)
            first = None
            guide_files = []
            if tail:
                first = f'banana_{job["id"]}_{i}.png'
                (inp/first).write_bytes(tail.read_bytes())
                if overlap:
                    guide_files = [first]
                    for number, image_path in enumerate(tail_frames[1:], 1):
                        filename = f'banana_{job["id"]}_{i}_guide_{number}.png'
                        (inp/filename).write_bytes(image_path.read_bytes())
                        guide_files.append(filename)
            if overlap:
                seg['handoff_overlap_frames'] = overlap
            seg['status']='preparing' if job['request'].get('director_schema') in (4,whole_song.VERSION,whole_song.DIRECT_SCRIPT) else 'rewriting'; write_state(job)
            saved = takes.existing_file(job,i,seg.get('selected_take','original'),'prompt.txt')
            state_replanned=False
            state_in=clip_input(ledger,seg) if ledger is not None else None
            record=cached_clip(work,ledger,seg) if ledger is not None else None
            if job['request'].get('lean_commission') and i:
                # 把上一段 9B 寫的 END_STATE（姿勢、動作方向、鏡頭運動）交給這一段。
                seg['previous_end_state']=job['segments'][i-1].get('end_state')
                # 末五幀：9B 也看完整的 F-4…F-0，親眼看 H3 實際拍出的動作方向。
                if overlap and tail_frames:
                    seg['motion_frames']=[str(path) for path in tail_frames[1:]]
                else:
                    seg.pop('motion_frames',None)
            if job['request'].get('prompt_source_job'):
                # 定稿重拍：沿用草稿那份已確認的提示詞，不再叫 9B 重寫。
                prompt=draft_prompt(job['request']['prompt_source_job'],i,len(original)+int(bool(tail)))
            elif single_pass or direct_script:
                prompt=local_prompt(cfg,job['request'],seg,original,tail)
            elif ledger is not None and record is not None and job.get('resuming'):
                prompt=record['clip_prompt'];seg['scene_state_debug']=record
            elif ledger is None and job.get('resuming') and saved.is_file() and not seg.get('refresh_prompt'):
                from banana_mv.core import normalize_mv_prompt
                prompt=normalize_mv_prompt(saved.read_text(encoding='utf-8'),len(original)+int(bool(tail)))
            else:
                state_replanned=ledger is not None
                prompt=local_prompt(cfg,job['request'],seg,original,tail,scene_input=state_in,
                                    event_catalog=ledger['event_catalog'] if ledger is not None else None,
                                    progress=rewrite_progress)
            if ledger is not None:
                rewrite_debug=seg.pop('scene_state_rewrite_debug',None)
                if rewrite_debug:
                    rewrite_log=f'{i:02d}_scene_state_rewrite_debug.json'
                    write_scene_json(work/rewrite_log,rewrite_debug)
                    seg['scene_state_repair_log']=rewrite_log
                save_clip(work,seg['scene_state_debug'])
            if not prompt:
                raise RuntimeError('提示詞改寫回傳空白，請關閉改寫或檢查本地模型。')
            seg['prompt']=prompt
            (work/f'{i:02d}_prompt_v1.txt').write_text(prompt,encoding='utf-8')
            if state_replanned:
                seg.pop('prompt_id',None)
                seg.pop('scene_state_prompt_sha256',None)
                seg.pop('refresh_prompt',None) # the new prompt/state pair is now durable
            wf = build_workflow(job['images_comfy'],name,*job['size'],render_frames,prompt,
                                seg.get('render_seed',(job['seed']+i) % (2**48)),first,
                                guide_frames=guide_files or None,
                                **graph_options(job['request'],seg['seconds'],seg))
            wf['16']['inputs']['filename_prefix']=f'BananaMV/{job["id"]}/{i:02d}_v1'
            preflight(cfg,wf)
            (work/f'{i:02d}_workflow_v1.json').write_text(json.dumps(wf,ensure_ascii=False,indent=2),encoding='utf-8')
            seg['status']='generating'; write_state(job)
            entry = None
            if (job.get('resuming') and seg.get('prompt_id') and
                (ledger is None or seg.get('scene_state_prompt_sha256')==scene_digest(prompt))):
                candidate = backend.history_entry(cfg,seg['prompt_id'])
                if candidate and candidate.get('status',{}).get('completed') and candidate.get('status',{}).get('status_str')!='error':
                    entry = candidate
            if entry is None:
                if job['id'] in CANCEL:
                    raise InterruptedError('手動緊急停爐；不開始新的 H3 任務。')
                pid = backend.queue_prompt(cfg,wf)
                seg['prompt_id']=pid
                if ledger is not None:seg['scene_state_prompt_sha256']=scene_digest(prompt)
                write_state(job)
                if job['id'] in CANCEL:
                    from banana_mv.comfy import cancel_prompt
                    try:cancel_prompt(cfg,pid)
                    except Exception:pass
                    raise InterruptedError('已取消剛提交的 H3 任務。')
                entry = wait_generation(cfg,pid,job)
            if job['id'] in CANCEL:
                raise InterruptedError('已中斷本段生成；不採用輸出。')
            raw = work/f'{i:02d}_raw_v1.mp4'
            backend.comfy_download(cfg,video_info(entry),raw)
            part = work/f'{i:02d}_part_v1.mp4'
            if overlap:
                trim_video(raw,part,seg['frames'],skip_frames=overlap)
            else:
                trim_video(raw,part,seg['frames'])
            if job['id'] in CANCEL:
                raise InterruptedError('已中斷本段生成；不提交影片。')
            parts.append(part)
            if ledger is not None:
                if not valid_part(part,seg,job['size']):raise SceneStateError('片段未成功保存，不提交規劃狀態。')
                commit_clip(work,ledger,seg['scene_state_debug'])
                job['scene_state_summary']['committed_clips']=len(ledger['commits'])
            seg.pop('refresh_prompt',None)
            if job.get('face_refine_chain') and not valid_part(part,seg,job['size']):
                raise ValueError('片段未成功保存，無法交接修臉尾幀。')
            seg['status']='done'
            if is_continuation(job['request']['mode']):
                guide = face_refine.chained_part(app, cfg, job, seg, part, original)
                if job['request']['mode'] == 'chain5' and i+1 < len(job['segments']):
                    tail_frames = last_frames(guide, work/f'{i:02d}_last5_%02d.png')
                    shutil.copyfile(tail_frames[-1], work/f'{i:02d}_last.png')
                    tail = tail_frames[0]
                else:
                    tail = work/f'{i:02d}_last.png'
                    last_frame(guide,tail)
            write_state(job)
            (inp/name).unlink(missing_ok=True)
            if first:
                (inp/first).unlink(missing_ok=True)
            for filename in guide_files[1:]:
                (inp/filename).unlink(missing_ok=True)
            # Complete the current video, finalize its tail frame and clean
            # temporary inputs BEFORE honoring the graceful pause.
            if pause_after_committed_clip(job):
                return
        if job['id'] in CANCEL:
            job['status']='cancelled'; write_state(job); return
        job['status']='assembling'; write_state(job)
        from banana_mv import masters
        masters.preserve_current(job,work)
        assemble(parts,song,work/'final.mp4',job['duration'],job['output_size'],**({'effects':effects_source(job)} if job.get('effects_mix') else {}))
        master=masters.archive(job,work,work/'final.mp4','resume' if job.get('current_master') else 'original')
        job['current_master']=master['version']
        # A successful NEW master ends the obsolete-timeline state, even if
        # optional face refinement or 1080p processing subsequently fails.
        job.pop('final_stale',None)
        try:
            export_finished_video(job,work/'final.mp4')
        except OSError as error:
            job['export_error']=f'成品已合成，但另存 videos 資料夾失敗：{error}；仍可由前端下載。'
        from banana_mv.native_sound import export_track
        export_track(sys.modules[__name__], job, master)
        from banana_mv import nv_upscale
        if (job['request'].get('face_refine') and job['id'] not in CANCEL
                and not nv_upscale.face_after_upscale(job['request'])):
            try:
                face_refine.render_version(
                    sys.modules[__name__], cfg, job, parts, original, song,
                    **({'effects': effects_source(job)} if job.get('effects_mix') else {}))
            except Exception as error:
                job['face_refine_error'] = str(error)
        if job['request'].get('upscale_1080p'):
            nv_upscale.render_version(sys.modules[__name__], cfg, job)
        job.pop('resuming',None)
        job['status']='done'; job['video']=f'/api/mv/file?id={job["id"]}'; write_state(job)
    except Exception as e:
        if job['id'] in CANCEL or isinstance(e,InterruptedError):
            # Never adopt a half-rendered current clip, even when some output
            # files arrived during cancellation. Completed earlier clips stay.
            current=job.get('current',0)
            if isinstance(current,int) and 1<=current<=len(job['segments']):
                interrupted=job['segments'][current-1]
                if interrupted.get('status')!='done':
                    interrupted['status']='waiting'
                    interrupted['interrupted_render']=True
                    interrupted.pop('prompt_id',None)
                    interrupted.pop('scene_state_prompt_sha256',None)
            job.pop('error',None);job.pop('error_stage',None)
            job['status']='cancelled';write_state(job)
            return
        stage=job.get('status','running')
        if stage=='running' and job.get('current'):
            stage=job['segments'][job['current']-1].get('status',stage)
        if job.get('current'):
            failed=job['segments'][job['current']-1]
            if failed.get('scene_state_attempt'):
                from banana_mv.scene_state import atomic_json
                atomic_json(work/f'{failed["index"]:02d}_scene_state_attempt.json',failed['scene_state_attempt'])
        job['error_stage']=stage
        job['status']='error'; job['error']=f'{type(e).__name__}: {e}'; write_state(job)
    finally:
        clear_progress(job['id'])
        CANCEL.discard(job['id'])
        STOP_AFTER_CURRENT.discard(job['id'])
        GPU_LOCK.release()


def draft_prompt(source_id,index,reference_count):
    """草稿專案第 index 段目前採用的提示詞（含手動重配後採用的版本）。"""
    from banana_mv import takes
    from banana_mv.core import normalize_mv_prompt
    source=read_state(source_id)
    if index>=len(source['segments']):
        raise ValueError('草稿段數與正式版不同，無法沿用提示詞。')
    seg=source['segments'][index]
    work=job_dir(source_id)
    for path in (takes.existing_file(source,index,seg.get('selected_take','original'),'prompt.txt'),
                 work/f'{index:02d}_prompt_v1.txt', work/f'{index:02d}_prompt.txt'):
        if path.is_file():
            return normalize_mv_prompt(path.read_text(encoding='utf-8'),reference_count)
    if seg.get('prompt'):
        return normalize_mv_prompt(seg['prompt'],reference_count)
    raise ValueError(f'草稿第 {index+1} 段沒有提示詞，請先讓草稿跑完這一段。')


def promote_draft(source_id,steps=8):
    """用草稿的提示詞開一桌 720P 正式版。草稿本身不受影響。"""
    from banana_mv.core import OUTPUT_SIZE_PRESETS
    source=read_state(source_id)
    if source.get('status')=='running':
        raise ValueError('草稿還在跑，請等它完成或停爐後再升級。')
    missing=[s['index']+1 for s in source['segments']
             if not ((job_dir(source_id)/f"{s['index']:02d}_prompt_v1.txt").is_file() or s.get('prompt'))]
    if missing:
        raise ValueError('草稿第 '+'、'.join(map(str,missing))+' 段還沒有提示詞。')
    if steps not in (6,8):
        raise ValueError('正式版步數請選 6 或 8。')
    req=dict(source['request'])
    aspect=req.get('aspect','16:9')
    req.update(width=OUTPUT_SIZE_PRESETS['720p'][aspect][0],sampling_steps=steps,
               plan_review=False,prompt_source_job=source_id,
               project_name=str(source.get('title') or 'MV')[:100]+'｜正式版')
    for key in ('director_schema','director_version','optimizer_version','story_scope_version',
                'ending_policy_version','prompt_compiler_version','rewrite_retries','scene_state_version',
                'persistent_scene_state','director_authority'):
        req.pop(key,None)
    return start(req)


def start(req):
    cfg = backend.project_config(req)
    req = dict(req)
    req.pop('native_sound', None)
    req.pop('native_sound_cues', None)
    if not isinstance(req.get('upscale_1080p', False), bool):
        raise ValueError('升頻設定必須是布林值。')
    if type(req.get('upscale_resolution', 1080)) is not int or req.get('upscale_resolution', 1080) not in (1080, 1440):
        raise ValueError('升頻解析度必須為 1080P 或 1440P。')
    if not isinstance(req.get('face_refine', False), bool):
        raise ValueError('遠景救臉設定必須為布林值。')
    if req.get('face_refine'):
        from banana_mv.face_refine import references, template
        images = req.get('image_ids')
        selected = references(req, len(images) if isinstance(images, list) else 0)
        template(sys.modules[__name__], cfg, dual=len(selected) == 2,
                 distant_only=req.get('upscale_resolution') == 1440)
    if req.get('direct_script') is True:
        req = dict(req, rewrite=False, story_plan=False)
    shared_setup=req.get('shared_setup','')
    if not isinstance(shared_setup,str) or len(shared_setup)>12000:
        raise ValueError('共同設定最多 12000 字。')
    req=dict(req)
    if shared_setup.strip():req['shared_setup']=shared_setup.strip()
    else:req.pop('shared_setup',None)
    if not isinstance(req.get('lean_commission', True), bool):
        raise ValueError('精簡通告單必須為勾選值。')
    req=dict(req,lean_commission=req.get('lean_commission', True),
             sampling_steps=req.get('sampling_steps',8),audio_analysis=req.get('audio_analysis', True),
             director_version=2,optimizer_version=1,story_plan=req.get('story_plan', True),
             director_schema=whole_song.DIRECT_SCRIPT if req.get('direct_script') is True else 6,
             story_scope_version=1,ending_policy_version=2,prompt_compiler_version=0,project_scope=req.get('project_scope','full'),
             director_authority=bool(req.get('story_plan',True) and req.get('rewrite',True)),
             kitchen_attention=req.get('kitchen_attention',req.get('acceleration',True)),
             sparse_attention=req.get('sparse_attention',req.get('acceleration',False)))
    from banana_mv.mv_scope import validate_scope
    validate_scope(req['project_scope'])
    req['rewrite_retries']=rewrite_retry_count(req)
    req.setdefault('plan_review',False)
    if not isinstance(req['plan_review'],bool):
        raise ValueError('先搓丹方必須為布林值。')
    req.pop('preview_zh', None)
    if req['plan_review'] and not req.get('rewrite',True) and req['director_schema'] != whole_song.DIRECT_SCRIPT:
        raise ValueError('先搓丹方需要開啟本地提示詞改寫。')
    if not isinstance(req.get('persistent_scene_state',True),bool):
        raise ValueError('persistent_scene_state 必須為布林值。')
    # New jobs persist their director version; resuming keeps the original workflow.
    req.update(scene_state_version=0,persistent_scene_state=False)
    if 'face_identity' in req and not isinstance(req['face_identity'], bool):
        raise ValueError('face_identity 必須為布林值。')
    req.setdefault('music_structure',False)
    if not isinstance(req['music_structure'],bool):
        raise ValueError('music_structure 必須為布林值。')
    if req['music_structure'] and not req['audio_analysis']:
        raise ValueError('音樂結構分析需要同時開啟音樂分析引導。')
    if not isinstance(req['audio_analysis'], bool):
        raise ValueError('audio_analysis 必須為布林值。')
    if not isinstance(req['story_plan'], bool):
        raise ValueError('story_plan 必須為布林值。')
    if req.get('mode') not in ('independent','chain','chain5'):
        raise ValueError('請選獨立、末幀或末五幀接續模式。')
    image_ids = req.get('image_ids')
    if image_ids is None:
        image_ids = [req.get('image_id')]
    image_ids = reference_images(image_ids, is_continuation(req['mode']))
    images = [backend.asset(aid) for aid in image_ids]
    music = backend.asset(req.get('song_id'))
    if any(img['kind']!='image' for img in images) or music['kind']!='audio':
        raise ValueError('請上傳參考圖片和一段歌曲。')
    vocal = backend.asset(req.get('vocal_id')) if req.get('vocal_id') else None
    if vocal and vocal['kind']!='audio':
        raise ValueError('人聲必須是音訊檔。')
    original = [backend.LIBRARY / img['file'] for img in images]
    song = backend.LIBRARY/music['file']
    drive = backend.LIBRARY/vocal['file'] if vocal else song
    seconds = source_audio_duration(song)
    effects = backend.asset(req['effects_id']) if req.get('effects_id') else None
    effects_info = None
    if effects:
        if effects['kind']!='audio':raise ValueError('音效／配音軌必須是音訊。')
        from banana_mv.sound_effects import validate_effects
        effects_info=validate_effects(backend.LIBRARY/effects['file'],song,seconds)
    plan = segments(seconds,float(req.get('segment_seconds',15)))
    for seg in plan:
        seg.update(song_seconds=seconds,segment_count=len(plan))
    if req.get('prompt_source_job') is not None:
        source=read_state(req['prompt_source_job'])
        if len(source['segments'])!=len(plan) or source['request'].get('mode')!=req.get('mode'):
            raise ValueError('草稿與正式版的分段或接續模式不同，無法沿用提示詞。')
    if vocal and abs(source_audio_duration(drive)-seconds)>1/FPS:
        raise ValueError('人聲與原曲長度不一致；請輸出同起點、保留前後靜音的人聲。')
    aspect = req.get('aspect','16:9')
    width = int(req['width']) if 'width' in req else None
    if 'long_side' in req and 'width' not in req:
        raise ValueError('解析度設定已改為橫向寬度，請載入新版前端再生成。')
    size = dimensions(aspect,width)
    output_size = output_dimensions(aspect,width)
    director_prompt(req, plan[0]['seconds'])
    seed = random.randrange(2**48) if req.get('seed') in (None,'') else int(req['seed'])
    authored_prompt = str(req.get('prompt',''))
    if req['director_schema'] == 6 and not (backend.PORT == 8193 and req.get('rewrite', True)):
        authored_prompt = authored_prompt[:10000]
    req = normalize_references(dict(req, prompt=authored_prompt), seconds)
    # Fail invalid image mentions before queueing any rewrite or GPU work.
    fallback_prompt(req['prompt'], False, '', len(images))
    images_comfy = [img['comfy_name'] for img in images]
    options = graph_options(req, plan[0]['seconds'])
    if req['plan_review'] and req.get('rewrite', True):
        graph = {'encoder': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': cfg['rewriter']['model']}},
                 'generate': {'class_type': 'TextGenerate', 'inputs': {}}}
        if options['h3_nvfp4']:
            graph['unet'] = {'class_type': 'UNETLoader', 'inputs': {'unet_name': H3_NVFP4_MODEL}}
        if options['h3_ref2va_turbo']:
            graph['turbo'] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {'lora_name': H3_REF2VA_TURBO_LORA}}
        for key, name, _ in action_lora_mounts(options['action_loras']) if 'action_loras' in options else ():
            graph['action_' + key] = {'class_type': 'LoraLoaderModelOnly', 'inputs': {'lora_name': name}}
    else:
        graph = build_workflow(images_comfy, 'preflight.wav', *size, plan[0]['model_frames'], '', seed, **options)
    if options.get('anti_jelly') and req['plan_review'] and req.get('rewrite', True):
        graph.update(build_workflow(images_comfy, 'preflight.wav', *size, plan[0]['model_frames'], '', seed, **options))
    preflight(cfg, graph)
    if req['director_schema'] == whole_song.VERSION and not req['plan_review']:
        preflight(cfg, {'encoder':{'class_type':'CLIPLoader','inputs':{'clip_name':cfg['rewriter']['model']}},
                        'generate':{'class_type':'TextGenerate','inputs':{}}})
    preflight_five_frame(cfg, req, images_comfy, size, plan[0], seed)
    if not GPU_LOCK.acquire(blocking=False):
        raise ValueError('已有 MV 工作執行中，請等它完成。')
    try:
        queue = backend.comfy(cfg,'/queue')
        if queue.get('queue_running') or queue.get('queue_pending'):
            raise ValueError('ComfyUI 還有其他工作，請先等它完成。')
        job_id=uuid.uuid4().hex[:12]
        (RUNS/job_id).mkdir()
        job={'id':job_id,'status':'running','created':time.time(),'request':req,
             'face_refine_chain': bool(req.get('face_refine') and req['mode'] in ('chain', 'chain5')
                                       and not (req.get('upscale_1080p') and req.get('upscale_resolution') == 1440)),
             'duration':seconds,'segments':plan,'size':size,'seed':seed,'timeline_source':'decoded_audio',
             'output_size':output_size, 'title':str(req.get('project_name') or music['name'])[:120],
             'settings_version':2,
             'image_comfy':images_comfy[0], 'images_comfy':images_comfy,
             'note':'尚未完成 Colab GPU 實測；末幀接續不攜帶前段動作 latent；末五幀使用五幀引導與重疊裁切。'}
        save_sources(job,original,song,drive)
        if effects:
            src=backend.LIBRARY/effects['file']
            dest=job_dir(job_id)/'sources'/('effects'+src.suffix.lower())
            shutil.copyfile(src,dest)
            job['sources']['effects']=str(dest.relative_to(job_dir(job_id)))
            job['effects_mix']=effects_info
        original,song,drive = project_inputs(job,cfg)
        write_state(job)
        threading.Thread(target=worker,args=(job,cfg,original,song,drive),daemon=True).start()
        return job
    except Exception:
        GPU_LOCK.release(); raise


def plan_revision(job):
    """Bind approval to saved allocation, timing, source bindings and render settings."""
    path=job_dir(job['id'])/'director_plan.json'
    if not path.is_file():raise ValueError('保存的丹方遺失，不能開爐。')
    return scene_digest({'request':{k:v for k,v in job['request'].items() if k!='rewrite_retries'},'seed':job['seed'],
                         'size':job['size'],'output_size':job.get('output_size'),
                         'sources':job.get('sources'),'images_comfy':job['images_comfy'],
                         'duration':job['duration'],
                         'allocation':json.loads(path.read_text(encoding='utf-8')),
                         **({'effects_mix':job['effects_mix']} if job.get('effects_mix') else {}),
                         'segments':[{k:s.get(k) for k in ('index','start','seconds','frames',
                                      'model_frames','director_plan','direction_ending_contract') +
                                     (('fixed_reference_settings',) if 'fixed_reference_settings' in s else ()) +
                                     (('audio_evidence',) if job['request'].get('music_structure') else ())}
                                     for s in job['segments']]})


def open_furnace(job_id,revision):
    """Approve an existing plan once; reuse its exact allocation without replanning."""
    if not GPU_LOCK.acquire(blocking=False):raise ValueError('已有 MV 工作執行中，請稍後開爐。')
    handed_off=False
    try:
        job=read_state(job_id)
        if (job['status']!='plan_ready' or not job['request'].get('plan_review') or
                job['request'].get('production')=='film'):
            raise ValueError('只有待確認的 MV 丹方可以開爐。')
        if not isinstance(revision,str) or revision!=job.get('plan_revision') or revision!=plan_revision(job):
            raise ValueError('丹方已有更新或內容不符，請重新開啟專案檢查。')
        if any(s.get('prompt_id') or s.get('prompt') or s.get('status')=='done' for s in job['segments']):
            raise ValueError('此專案已有開拍內容，不能重複確認丹方。')
        cfg=backend.project_config(job['request'])
        q=backend.comfy(cfg,'/queue')
        if q.get('queue_running') or q.get('queue_pending'):
            raise ValueError('ComfyUI 還有工作，請稍後開爐。')
        original,song,drive=project_inputs(job,cfg)
        seg=job['segments'][0]
        preflight(cfg,build_workflow(job['images_comfy'],'preflight.wav',*job['size'],
                  seg['model_frames'],'',job['seed'],**graph_options(job['request'],seg['seconds'])))
        preflight_five_frame(cfg, job['request'], job['images_comfy'], job['size'], seg, job['seed'])
        job.update(status='running',plan_approved=revision,resumed=time.time())
        CANCEL.discard(job_id)
        STOP_AFTER_CURRENT.discard(job_id)
        write_state(job)
        try:
            threading.Thread(target=worker,args=(job,cfg,original,song,drive),daemon=True).start()
            handed_off=True
        except Exception:
            job.pop('plan_approved',None);job['status']='plan_ready';write_state(job);raise
        return job
    finally:
        if not handed_off:GPU_LOCK.release()


def adopted_part(job,seg):
    from banana_mv.takes import existing_file
    return existing_file(job,seg['index'],seg.get('selected_take','original'),'part.mp4')


def valid_part(path, seg, size):
    if not path.is_file():
        return False
    try:
        stream = next(s for s in probe(path)['streams'] if s['codec_type']=='video')
        return (int(stream.get('nb_frames',-1))==seg['frames'] and
                (stream['width'],stream['height'])==tuple(size))
    except (RuntimeError, KeyError, StopIteration, ValueError):
        return False


def save_sources(job, originals, song, drive):
    directory = job_dir(job['id'])/'sources'
    directory.mkdir(exist_ok=True)
    images = []
    for i,path in enumerate(originals):
        dest = directory/f'image_{i}{path.suffix.lower()}'
        shutil.copyfile(path,dest); images.append(str(dest.relative_to(job_dir(job['id']))))
    dest = directory/('song'+song.suffix.lower()); shutil.copyfile(song,dest)
    song_name = str(dest.relative_to(job_dir(job['id'])))
    drive_name = song_name
    if drive != song:
        dest = directory/('vocal'+drive.suffix.lower()); shutil.copyfile(drive,dest)
        drive_name = str(dest.relative_to(job_dir(job['id'])))
    job['sources'] = {'images':images,'song':song_name,'drive':drive_name}


def effects_source(job):
    if not job.get('effects_mix'):return None
    path=backend.safe_child(job_dir(job['id']),job['sources']['effects'])
    if not path.is_file():raise ValueError('專案音效軌遺失，停止混音以免漏掉已確認素材。')
    return {'path':path,'gain':job['effects_mix']['gain']}


def project_inputs(job, cfg):
    if 'sources' not in job:
        req = job['request']
        rows = [backend.asset(aid) for aid in (req.get('image_ids') or [req['image_id']])]
        originals = [backend.LIBRARY/item['file'] for item in rows]
        song = backend.LIBRARY/backend.asset(req['song_id'])['file']
        drive = backend.LIBRARY/backend.asset(req['vocal_id'])['file'] if req.get('vocal_id') else song
        if not all(p.is_file() for p in originals+[song,drive]):
            raise ValueError('原始素材遺失，無法續跑。')
        job.setdefault('images_comfy',[item['comfy_name'] for item in rows])
        save_sources(job,originals,song,drive)
    source = job['sources']
    originals = [backend.safe_child(job_dir(job['id']),p) for p in source['images']]
    song = backend.safe_child(job_dir(job['id']),source['song'])
    drive = backend.safe_child(job_dir(job['id']),source['drive'])
    if not all(p.is_file() for p in originals+[song,drive]):
        raise ValueError('專案原始素材遺失，請還原 sources 資料夾。')
    if job.get('effects_mix'):effects_source(job)
    names = job['images_comfy']
    if len(names) != len(originals):
        raise ValueError('專案圖片數量不符。')
    inp = Path(cfg['comfy_input_dir']); inp.mkdir(parents=True,exist_ok=True)
    for path,name in zip(originals,names):
        shutil.copyfile(path,backend.safe_child(inp,name))
    return originals,song,drive


def projects():
    rows=[]
    for path in RUNS.glob('*/status.json'):
        try:
            job=json.loads(path.read_text(encoding='utf-8'))
            job_dir(job['id'])
            rows.append({'id':job['id'],'title':job.get('title',job['id']),
                'created':job.get('created',0),'updated':job.get('resumed',job.get('created',0)),'status':job['status'],'duration':job['duration'],
                'completed':sum(s.get('status')=='done' for s in job['segments']),
                'total':len(job['segments'])})
        except (ValueError,KeyError,OSError):
            continue
    return sorted(rows,key=lambda r:r['updated'],reverse=True)


def repair_unstarted_timeline(job, song):
    """Correct container-padding tails only before any prompt or GPU work.

    Already generated projects retain their original clip/frame allocation.
    Archive any unused plan rather than deleting user project history.
    """
    if job.get('timeline_source') == 'decoded_audio':
        return
    work = job_dir(job['id'])
    if any(seg.get('prompt_id') or seg.get('status')=='done' for seg in job['segments']):
        return
    if any(list(work.glob(pattern)) for pattern in ('*_prompt*.txt','*_workflow*.json','*_part*.mp4','*_raw*.mp4')):
        return
    actual = source_audio_duration(song)
    if abs(actual-job['duration']) > .25:
        return  # A substantial mismatch needs diagnosis, not a silent retime.
    plan = segments(actual,float(job['request'].get('segment_seconds',15)))
    for seg in plan:
        seg.update(song_seconds=actual,segment_count=len(plan))
    previous = {'duration':job['duration'],'segments':len(job['segments'])}
    for name in ('director_plan.json','director_plan_draft.json'):
        saved = work/name
        if saved.is_file():
            saved.rename(work/(saved.stem+'_before_timing_fix_'+uuid.uuid4().hex[:8]+'.json'))
    job.update(duration=actual,segments=plan,timeline_source='decoded_audio',timeline_repair=previous)
    job.pop('director_plan',None)


def restore_render_settings(job):
    """Infer absent legacy render switches without changing saved choices."""
    if 'sampling_steps' not in job['request']:
        # Existing projects keep their saved schedule rather than silently mixing 6 and 8 steps.
        saved=sorted(job_dir(job['id']).glob('*_workflow*.json'))
        saved_steps=6
        if saved:
            previous=json.loads(saved[0].read_text(encoding='utf-8'))
            saved_steps=next((n['inputs']['steps'] for n in previous.values()
                              if n['class_type']=='BasicScheduler'),6)
        job['request']['sampling_steps']=saved_steps
    # Older projects predate explicit feature switches. Infer only absent switches.
    if not job.get('settings_version'):
        workflows=sorted(job_dir(job['id']).glob('*_workflow*.json'))
        prompts=sorted(job_dir(job['id']).glob('*_prompt*.txt'))
        if workflows:
            graph=json.loads(workflows[0].read_text(encoding='utf-8'))
            kinds={n['class_type'] for n in graph.values()}
            job['request'].setdefault('kitchen_attention','ModelAttentionBackend' in kinds)
            job['request'].setdefault('sparse_attention','BlockSparseAttention' in kinds)
            job['request'].setdefault('acceleration','BlockSparseAttention' in kinds)
            job['request'].setdefault('motion_lora','LoraLoaderModelOnly' in kinds)
        if prompts:
            job['request'].setdefault('face_identity','[BANANA_FACE_IDENTITY_V1]' in prompts[0].read_text(encoding='utf-8'))


def resume(job_id,rewrite_retries=None):
    retries=rewrite_retry_count({'rewrite_retries':rewrite_retries}) if rewrite_retries is not None else None
    # The selected emergency-stop retake defines a NEW shooting timeline.
    # "Continue" must start the 9B+H3 branch from its next clip, not the
    # ordinary legacy resumer that skips done clips and can reuse old prompts.
    prior=read_state(job_id)
    stopped=prior.get('status') in ('error','cancelled','interrupted')
    local_chain=(is_continuation(prior['request']['mode'])
                 and prior['request'].get('director_schema')==6)
    restart=prior.get('continuation_restart')
    # Interrupted during a NEW continuation? Resume after the last genuinely
    # regenerated clip, never mistake an old archived downstream Take for a
    # completed segment in the new branch.
    generation=prior.get('continuation_generation')
    if stopped and local_chain and generation and not restart:
        parent=int(generation['anchor_index'])
        for i in range(parent+1,len(prior['segments'])):
            segment=prior['segments'][i]
            if segment.get('status')!='done':
                break
            parent=i
        from banana_mv.takes import continue_from_take
        return continue_from_take(job_id,parent,
                                  prior['segments'][parent].get('selected_take','original'),
                                  'cascade',rewrite_retries=retries)
    if stopped and local_chain and not restart:
        # Migration: an older 5070 build treated "選用此丹" as pending.
        # Before continuing, adopt that explicit user choice instead of
        # accidentally taking an old selected_take or reusing old prompts.
        pending=prior.get('pending_takes') or {}
        if pending:
            if len(pending)!=1:
                raise ValueError('停爐專案有多個待採用丹藥，請逐段選用正式版本後再續拍。')
            from banana_mv.takes import select_take
            key, chosen=next(iter(pending.items()))
            prior=select_take(job_id,int(key),chosen)
            restart=prior.get('continuation_restart')
    if restart and stopped and local_chain:
        from banana_mv.takes import continue_from_take
        return continue_from_take(job_id,restart['index'],restart['take'],
                                  'cascade',rewrite_retries=retries)
    if not GPU_LOCK.acquire(blocking=False):
        raise ValueError('已有 MV 執行中，不能重複續跑。')
    try:
        job=read_state(job_id)
        if retries is not None:job['request']['rewrite_retries']=retries
        if job['status'] not in ('error','cancelled','interrupted'):
            raise ValueError('這個專案沒有待續跑的失敗或中斷工作。')
        cfg=backend.project_config(job['request'])
        queue=backend.comfy(cfg,'/queue')
        if queue.get('queue_running') or queue.get('queue_pending'):
            raise ValueError('ComfyUI 仍在執行工作，請等佇列清空再續跑。')
        originals,song,drive=project_inputs(job,cfg)
        repair_unstarted_timeline(job,song)
        restore_render_settings(job)
        missing=False
        for seg in job['segments']:
            part=adopted_part(job,seg)
            usable=valid_part(part,seg,job['size']) and not seg.get('interrupted_render')
            if not usable and seg.get('takes'):
                raise ValueError('採用版毛片遺失或損壞，請恢復該版本或另選現存版本；不覆寫原丹。')
            if not usable or (missing and is_continuation(job['request']['mode'])):
                seg['status']='waiting'
                seg.pop('interrupted_render',None)
                if missing and is_continuation(job['request']['mode']):
                    seg.pop('prompt_id',None)
                    seg['refresh_prompt']=True
                missing=True
            else:
                seg['status']='done'
        if missing:
            graph=build_workflow(job['images_comfy'],'preflight.wav',*job['size'],job['segments'][0]['model_frames'],'',
                                 job['seed'],**graph_options(job['request'],job['segments'][0]['seconds']))
            preflight(cfg,graph)
            preflight_five_frame(cfg, job['request'], job['images_comfy'], job['size'],
                                 job['segments'][0], job['seed'])
        job.update(status='running',resuming=True,resumed=time.time())
        job.pop('error',None);job.pop('video',None);CANCEL.discard(job_id)
        STOP_AFTER_CURRENT.discard(job_id)
        job.pop('stop_reason',None)
        write_state(job)
        threading.Thread(target=worker,args=(job,cfg,originals,song,drive),daemon=True).start()
        return job
    except Exception:
        GPU_LOCK.release();raise


class Handler(WebHandler):
    def do_GET(self):
        if self.path == '/api/5070/switch':
            from banana_mv.room_switch import launcher
            return self.send_json({'available': bool(launcher('film', backend.PORT)),
                                   'busy': GPU_LOCK.locked()})
        url = urllib.parse.urlparse(self.path)
        if url.path == '/banana35b' or url.path.startswith('/banana35b/'):
            from banana_mv import lab35_bridge
            return lab35_bridge.get(self, url.path, backend)
        if url.path in ('/','/mv'):
            return self.send_file(WEB/'index.html')
        if url.path=='/clip_review.js':
            return self.send_file(WEB/'clip_review.js')
        if url.path=='/api/health':
            return self.send_json({'service':'banana-mv','standalone':True,'instance':SERVER_INSTANCE,
                                   'version':SERVER_BUILD})
        if url.path=='/api/mv/face-refine-capability':
            return self.send_json({'local5070':backend.PORT==8193})
        if url.path=='/api/mv/director35-progress':
            if backend.PORT != 8193:
                return self.send_json({'local5070':False})
            from banana_mv import director35
            return self.send_json(dict(director35.snapshot(),local5070=True))
        if url.path=='/api/mv/dan-fire':
            if FIRE_MONITOR is None:
                return self.send_json({'local5070': False, 'available': False})
            return self.send_json(dict(FIRE_MONITOR.snapshot(), local5070=True))
        if url.path=='/api/mv/anti-jelly-capability':
            if backend.PORT != 8193:
                return self.send_json({'local5070': False, 'available': False})
            try:
                info = backend.comfy(backend.load_config(), '/object_info', timeout=8)
                anti_jelly.require_capability(info)
                return self.send_json({'local5070': True, 'available': True})
            except (ValueError, RuntimeError, OSError) as error:
                return self.send_json({'local5070': True, 'available': False, 'reason': str(error)})
        if url.path=='/api/mv/restart-capability':
            return self.send_json(restart_capability())
        if url.path=='/api/config':
            return self.send_json({'config':{'comfy_url':backend.load_config()['comfy_url']}})
        if url.path=='/api/mv/reference':
            try:
                args=dict(urllib.parse.parse_qsl(url.query)); job=read_state(args['id']); index=int(args.get('image',0))
                if index < 0: raise ValueError('無效的圖片編號。')
                if job.get('sources'):
                    path=backend.safe_child(job_dir(job['id']),job['sources']['images'][index])
                else:
                    req=job['request']; ids=req.get('image_ids') or [req['image_id']]
                    path=backend.safe_child(backend.LIBRARY,backend.asset(ids[index])['file'])
                return self.send_file(path)
            except (ValueError,KeyError,IndexError) as e:
                return self.send_json({'error':str(e)},400)
        if url.path=='/api/mv/projects':
            return self.send_json(projects())
        if url.path=='/api/mv/presets':
            from banana_mv import presets
            return self.send_json(presets.list_presets())
        if url.path=='/api/mv/asset':
            try:
                from banana_mv import presets
                return self.send_file(presets.image_asset(dict(urllib.parse.parse_qsl(url.query)).get('id',''))[1])
            except (ValueError,OSError) as e:
                return self.send_json({'error':str(e)},404)
        if url.path=='/api/library':
            return self.send_json(backend.library_index())
        if url.path=='/api/mv/status':
            try:
                from banana_mv.takes import describe
                job = describe(read_state(dict(urllib.parse.parse_qsl(url.query))['id']))
                if LIVE_PROGRESS is not None:
                    job['comfy_progress'] = LIVE_PROGRESS.snapshot(job['id'])
                return self.send_json(job)
            except Exception as e:
                return self.send_json({'error':str(e)},400)
        if url.path=='/api/mv/clip':
            try:
                from banana_mv.takes import preview
                args=dict(urllib.parse.parse_qsl(url.query));job=read_state(args['id'])
                return self.send_file(preview(job,int(args['index']),args.get('take','current')))
            except (ValueError,KeyError,OSError,RuntimeError) as e:
                return self.send_json({'error':str(e)},400)
        if url.path=='/api/mv/clip-2k':
            try:
                from banana_mv import nv_upscale
                args=dict(urllib.parse.parse_qsl(url.query));job=read_state(args['id'])
                index=int(args['index']);take=args['take']
                return self.send_file(nv_upscale.clip_file(sys.modules[__name__],job,index,take),
                                      download_name=nv_upscale.clip_download_name(sys.modules[__name__],job,index,take))
            except (ValueError,KeyError,OSError) as e:
                return self.send_json({'error':str(e)},400)
        if url.path=='/api/mv/native-sound':
            from banana_mv.native_sound import download_url, track_path
            try:
                args = dict(urllib.parse.parse_qsl(url.query))
                job = read_state(args['id'])
                version = job.get('current_master')
                if not download_url(job) or args.get('version') != str(version):
                    return self.send_error(404)
                path = track_path(job_dir(job['id']), version)
                name = finished_video_target(job).stem + '_原生聲音.mp3'
                return self.send_file(path, download_name=name)
            except (KeyError, ValueError, OSError):
                return self.send_error(404)
        if url.path=='/api/mv/file':
            try:
                from banana_mv import masters
                args=dict(urllib.parse.parse_qsl(url.query))
                job=read_state(args['id'])
                work=job_dir(args['id'])
                version=args.get('version')
                if args.get('download')=='1':
                    if job.get('final_stale'):
                        raise ValueError('目前成片等待重新合成。')
                    current=job.get('current_master')
                    if version is None or (current is not None and version==str(current)):
                        target=finished_video_target(job)
                        if job.get('output_video')==str(target) and not job.get('export_error') and target.is_file():
                            return self.send_file(target,download_name=target.name)
                        path=masters.source(job,work,version)
                    else:
                        path=masters.source(job,work,version)
                        row=next((r for r in job.get('final_versions',[]) if str(r.get('version'))==version),{})
                        exported=Path(row['output_video']) if row.get('output_video') else None
                        if exported and exported.is_file() and exported.stat().st_size==path.stat().st_size:
                            # 修臉版、2K 版在 videos 裡有自己的檔名（含 _1440p_v002 這類後綴）
                            return self.send_file(exported,download_name=exported.name)
                        target=finished_video_target(dict(job,current_master=int(version)))
                    return self.send_file(path,download_name=target.name)
                return self.send_file(masters.source(job,work,version))
            except Exception as e:
                return self.send_json({'error':str(e)},400)
        return self.send_error(404)

    def do_POST(self):
        if self.path == '/api/5070/switch':
            from banana_mv.room_switch import switch
            return switch(self, 'film', backend, GPU_LOCK)
        path=urllib.parse.urlparse(self.path).path
        if path.startswith('/banana35b/'):
            from banana_mv import lab35_bridge
            return lab35_bridge.post(self, path, backend, GPU_LOCK, RESTART_LOCK, RESTART_REQUEST)
        try:
            if path=='/api/mv/restart':
                result = request_desktop_restart(self, self.body_json())
                return self.send_json(result, 202)
            if path in ('/api/mv/preset_save','/api/mv/preset_delete'):
                from banana_mv import presets
                handler=presets.save_preset if path.endswith('save') else presets.delete_preset
                return self.send_json(handler(self.body_json()))
            if path=='/api/upload':
                if not GPU_LOCK.acquire(blocking=False):
                    raise ValueError('MV 執行中，請完成後再上傳素材。')
                try:
                    filename=urllib.parse.unquote(self.headers.get('X-Filename',''))
                    return self.send_json(backend.add_asset(backend.load_config(),filename,self.read_body()))
                finally:
                    GPU_LOCK.release()
            if path=='/api/mv/start':
                return self.send_json(start(self.body_json()))
            if path=='/api/mv/open-furnace':
                body=self.body_json()
                return self.send_json(open_furnace(body['id'],body.get('revision')))
            if path=='/api/mv/resume':
                body=self.body_json()
                return self.send_json(resume(body['id'],body.get('rewrite_retries')))
            if path=='/api/mv/upscale':
                from banana_mv import nv_upscale
                body=self.body_json()
                return self.send_json(nv_upscale.start_finished(sys.modules[__name__], body['id'], body.get('version')), 202)
            if path=='/api/mv/upscale-clip':
                from banana_mv import nv_upscale
                body=self.body_json()
                return self.send_json(nv_upscale.start_clip(sys.modules[__name__],body['id'],body.get('index'),body.get('take')),202)
            if path=='/api/mv/promote-draft':
                body=self.body_json()
                return self.send_json(promote_draft(body['id'],body.get('steps',8)))
            if path=='/api/mv/rewrite-clip':
                from banana_mv.manual_prompt import rewrite_clip
                body=self.body_json()
                overrides={key:body[key] for key in ('rewriter_thinking','rewriter_budget','director_engine','director35_mtp','director35_context','director35_cpu_moe','director35_kv','director35_output') if key in body}
                return self.send_json(rewrite_clip(body['id'],body.get('index'),body.get('previous_take'),
                                                   rewriter_options=overrides),202)
            if path=='/api/mv/retake':
                from banana_mv.takes import retake
                body=self.body_json()
                return self.send_json(retake(body['id'],body.get('indices'),body.get('instructions'),body.get('prompts'),body.get('auto_resume',False),body.get('rebuild_prompt',False),body.get('previous_takes'),body.get('adopt_continue',False)))
            if path=='/api/mv/continue-branch':
                from banana_mv.takes import continue_from_take
                body=self.body_json()
                return self.send_json(continue_from_take(body['id'],body.get('index'),
                                                         body.get('take'),body.get('mode')),202)
            if path=='/api/mv/condense':
                from banana_mv.takes import condense
                body=self.body_json()
                return self.send_json(condense(body['id'],body.get('revision')))
            if path=='/api/mv/select-take':
                from banana_mv.takes import select_take
                body=self.body_json()
                return self.send_json(select_take(body['id'],body.get('index'),body.get('take')))
            if path=='/api/mv/stop-after-current':
                return self.send_json(stop_after_current_job(self.body_json()['id']))
            if path=='/api/mv/stop':
                return self.send_json(stop_job(self.body_json()['id']))
            return self.send_error(404)
        except Exception as e:
            if path == '/api/upload':
                # The browser only displays a short error. Preserve a LOCAL
                # traceback so NoneType failures can be pinpointed without
                # uploading recordings or exposing diagnostic paths via HTTP.
                import traceback
                try:
                    (backend.DATA/'upload_error.log').write_text(
                        traceback.format_exc(), encoding='utf-8')
                except OSError:
                    pass
            return self.send_json({'error':str(e)},400)


if __name__=='__main__':
    backend.LIBRARY.mkdir(parents=True,exist_ok=True)
    # Selected images are restored by project_inputs(); audio_window() writes
    # the needed audio slice. Do not block startup copying the entire Drive library.
    # Don't leave stale runs looking active after a Colab restart.
    for p in RUNS.glob('*/status.json'):
        job=json.loads(p.read_text(encoding='utf-8'))
        if job['status'] not in ('done','error','cancelled','interrupted','plan_ready'):
            job.update(status='interrupted',error='執行階段已重啟；已完成片段仍保存在工作資料夾。')
            write_state(job)
        if job.get('clip_upscale',{}).get('status')=='running':
            job['clip_upscale'].update(status='error',error='執行階段已重啟，單段 2K 未完成。')
            write_state(job)
    print(f'Banana MV on http://127.0.0.1:{backend.PORT}',flush=True)
    if LIVE_PROGRESS is not None:
        from banana_mv.comfy import CLIENT_ID
        try:
            LIVE_PROGRESS.start(backend.load_config()['comfy_url'], CLIENT_ID)
        except (OSError, ValueError, KeyError) as error:
            print(f'ComfyUI 即時進度無法啟動：{error}', flush=True)
    ThreadingHTTPServer(('127.0.0.1',backend.PORT),Handler).serve_forever()

