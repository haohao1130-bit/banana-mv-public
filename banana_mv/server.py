"""Standalone Banana MV server: own assets, HTTP client and local prompt rewriting."""
import copy
import json
import os
import random
import shutil
import sys
import threading
import time
import urllib.parse
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from banana_mv.director import director_prompt
from banana_mv.core import (FPS, assemble, audio_window, build_workflow, dimensions,
                            duration, enforce_face_identity, fallback_prompt, last_frame, output_dimensions,
                            reference_images, segments, trim_video, probe, source_audio_duration)

from banana_mv import services as backend
from banana_mv.http_server import WebHandler
from banana_mv.lyrics_reference import (normalize_references, clip_reference, clean_lyric_output,
                                        POLICY as LYRIC_POLICY, OUTPUT_POLICY as LYRIC_OUTPUT_POLICY)
from banana_mv.scene_state import (SceneStateError, ensure_scene_state, clip_input, state_context,
                                   plan_clip, save_clip, commit_clip, cached_clip, reconcile_history,
                                   final_context, CLIP_SYSTEM, parse_object as parse_scene_object,
                                   atomic_json as write_scene_json, digest as scene_digest)
from banana_mv.song_context import segment_context
from banana_mv.audio_analysis import VERSION as AUDIO_VERSION, load_analysis, segment_evidence, audio_guidance, rewrite_evidence
from banana_mv.story_plan import ensure_plan, plan_context
from banana_mv.prompt_quality import (reference_policy, enforce_reference_policy,
                                      clip_scope, enforce_clip_scope, director_led, DIRECTOR_AUTHORITY)

WEB = Path(__file__).parent / 'web'
RUNS = backend.DATA/'banana_mv'
RUNS.mkdir(parents=True, exist_ok=True)
GPU_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()
CANCEL = set()


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


def preflight(cfg, graph):
    info = backend.comfy(cfg, '/object_info')
    missing = sorted({n['class_type'] for n in graph.values()} - set(info))
    if missing:
        raise ValueError('缺少節點，請重跑安裝並重啟：' + ', '.join(missing))
    for n in graph.values():
        fields = {'UNETLoader':'unet_name','CLIPLoader':'clip_name','VAELoader':'vae_name',
                  'LoraLoaderModelOnly':'lora_name', 'ModelAttentionBackend':'attention'}
        if n['class_type'] in fields:
            name = fields[n['class_type']]
            choices = info[n['class_type']]['input']['required'][name][0]
            if isinstance(choices,list) and n['inputs'][name] not in choices:
                if name == 'attention':
                    raise ValueError('Kitchen INT8 注意力不可用，請重跑安裝並重啟，或關閉注意力加速。')
                raise ValueError('尚未下載模型：' + n['inputs'][name] + '；請重跑 Colab ② 下載模型。')


def graph_options(req, seconds, segment=None):
    if req.get("realism_lora"):
        raise ValueError("fal 真人 LoRA 已移除；此舊專案曾啟用 fal，請另建不使用 fal 的專案，避免續跑混用設定。")
    _, mode = director_prompt(req, seconds, segment)
    for field in ('acceleration', 'kitchen_attention', 'sparse_attention', 'motion_lora'):
        if field in req and not isinstance(req[field], bool):
            raise ValueError(field + ' 必須為布林值。')
    steps=req.get('sampling_steps',8)
    if isinstance(steps,bool) or steps not in (6,8):
        raise ValueError('採樣步數僅支援 6 或 8。')
    return {'steps':int(steps),'acceleration': req.get('acceleration', True),
            'kitchen_attention': req.get('kitchen_attention',req.get('acceleration',True)),
            'sparse_attention': req.get('sparse_attention',req.get('acceleration',True)),
            'motion_lora': req.get('motion_lora', True),
            'director_mode': mode, 'intensity': req.get('intensity', 'high')}


def local_prompt(cfg, req, segment, original, tail, *, scene_input=None, event_catalog=None):
    # Only local model calls; never silently fall back to a paid API.
    director, mode = director_prompt(req, segment['seconds'], segment)
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
    for attempt in range(2):
        raw = backend.rewrite_local(cfg,guide,attempt_parts,uuid.uuid4().hex[:8]).strip()
        try:
            if scene_input is not None:
                record=plan_clip(raw,scene_input,event_catalog,segment)
                rewritten=normalize_mv_prompt(record['clip_prompt'],picture_count)
                segment['scene_state_debug']=record
            else:
                rewritten=normalize_mv_prompt(raw,picture_count)
            if attempt:
                segment['prompt_reference_repair']={'status':'repaired','message':'9B 結構或媒體引用已自動修正。'}
            break
        except (SceneStateError,MediaReferenceError) as error:
            if scene_input is not None:
                try:parsed=parse_scene_object(raw)
                except SceneStateError:parsed=None
                state_attempts.append({'attempt':attempt,'raw_response':raw,'parsed_response':parsed,
                                       'error':str(error),'validation_errors':getattr(error,'errors',[]),'status':'failed'})
                segment['scene_state_attempt']={'clip_index':segment['index'],'scene_state_in':scene_input,
                                                'error':str(error),'raw_response':raw,'attempts':copy.deepcopy(state_attempts),
                                                'visual_verified':False}
            if not attempt:
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
            state_attempts.append({'attempt':1,'raw_response':raw,'parsed_response':parse_scene_object(raw),'status':'validated'})
            segment['scene_state_rewrite_debug']={'clip_index':segment['index'],'scene_state_in':scene_input,
                                                   'status':'repaired','attempts':state_attempts,'visual_verified':False}
        segment.pop('scene_state_attempt',None)
    return final


def wait_generation(cfg, prompt_id, job):
    deadline = time.monotonic()+7200
    while time.monotonic()<deadline:
        entry = backend.history_entry(cfg,prompt_id)
        if entry:
            if entry.get('status',{}).get('status_str')=='error':
                raise RuntimeError(backend.execution_error(entry))
            if entry.get('status',{}).get('completed'):
                return entry
        time.sleep(2)
    raise RuntimeError('單段生成等待超過兩小時；請檢查 ComfyUI 紀錄。')


def video_info(entry):
    for out in entry.get('outputs',{}).values():
        for key in ('videos','images','gifs'):
            for item in out.get(key,[]):
                if str(item.get('filename','')).lower().endswith(('.mp4','.webm','.mov')):
                    return item
    raise RuntimeError('生成已完成，但沒有找到影片輸出。')


def export_finished_video(job,source):
    """Keep the resumable project master and publish an atomic copy to the finished-video folder."""
    folder=backend.DATA/'videos'
    folder.mkdir(parents=True,exist_ok=True)
    title=''.join(c for c in str(job.get('title') or 'Banana_MV') if c not in '<>:"/\\|?*' and ord(c)>=32).strip(' .')[:60] or 'Banana_MV'
    target=folder/f'{title}_{job["id"]}.mp4'
    temp=target.with_name('.'+target.name+'.tmp')
    try:
        shutil.copyfile(source,temp)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    job['output_video']=str(target)
    job.pop('export_error',None)
    return target


def worker(job, cfg, original, song, drive):
    work = job_dir(job['id'])
    inp = Path(cfg['comfy_input_dir'])
    parts, tail = [], None
    try:
        # Old projects keep their saved prompt behavior. New projects opt in by
        # a persisted request field; no GPU or additional model downloads needed.
        needs_analysis = job['request'].get('audio_analysis', False) and any(
            not (seg.get('status') == 'done' and valid_part(work/f'{seg["index"]:02d}_part.mp4', seg, job['size']))
            and not (job.get('resuming') and (work/f'{seg["index"]:02d}_prompt.txt').is_file()
                     and not seg.get('refresh_prompt')) for seg in job['segments'])
        if needs_analysis:
            job['status'] = 'analyzing_audio'; write_state(job)
            music_analysis = load_analysis(song, work/'audio_analysis.json')
            vocal_analysis = load_analysis(drive, work/'vocal_analysis.json') if drive != song else None
            for seg in job['segments']:
                seg['audio_evidence'] = segment_evidence(music_analysis, seg, vocal_analysis)
            job['audio_analysis'] = {'version': AUDIO_VERSION, 'status': 'ready',
                                     'pulse': music_analysis['pulse']}
            job['status'] = 'running'; write_state(job)
        needs_plan = (job['request'].get('director_version', 1) >= 2
                      and job['request'].get('story_plan', True)
                      and job['request'].get('rewrite', True) and len(job['segments']) > 1
                      and any(not (s.get('status') == 'done' and valid_part(work/f'{s["index"]:02d}_part.mp4', s, job['size']))
                              and not (job.get('resuming') and (work/f'{s["index"]:02d}_prompt.txt').is_file()
                                       and not s.get('refresh_prompt')) for s in job['segments']))
        if needs_plan:
            if job['id'] in CANCEL:
                job['status']='cancelled'; write_state(job); return
            job['status']='planning_story'; write_state(job)
            plan = ensure_plan(cfg, job['request'], job['segments'], original, work, backend.rewrite_local)
            for index, (seg, row) in enumerate(zip(job['segments'], plan['segments'])):
                seg['director_plan'] = row
                if index:
                    seg['previous_planned_event'] = plan['segments'][index-1]['event']
            job['director_plan'] = {'version':plan['version'], 'status':'ready'}
            job['status']='running'; write_state(job)
        ledger=None
        if job['request'].get('scene_state_version')==1:
            if job['id'] in CANCEL:
                job['status']='cancelled';write_state(job);return
            job['status']='planning_state';write_state(job)
            ledger=ensure_scene_state(cfg,job['request'],job['segments'],original,work,backend.rewrite_local)
            reconcile_history(job,work,ledger,lambda s:valid_part(work/f'{s["index"]:02d}_part.mp4',s,job['size']))
            job['scene_state_summary']={'version':1,'committed_clips':len(ledger['commits']),'visual_verified':False}
            job['status']='running';write_state(job)
        for seg in job['segments']:
            if job['id'] in CANCEL:
                job['status']='cancelled'; write_state(job); return
            i = seg['index']
            part = work/f'{i:02d}_part.mp4'
            if seg.get('status')=='done' and valid_part(part,seg,job['size']):
                if ledger is not None:
                    record=cached_clip(work,ledger,seg)
                    if record is None:raise SceneStateError('已完成影片缺少可繼承的狀態快照，不能猜測或重置。')
                    commit_clip(work,ledger,record)
                    seg['scene_state_debug']=record
                    job['scene_state_summary']['committed_clips']=len(ledger['commits'])
                parts.append(part)
                if job['request']['mode']=='chain':
                    tail = work/f'{i:02d}_last.png'
                    last_frame(part,tail)
                continue
            seg['status']='preparing'; job['current']=i+1; write_state(job)
            name = f'banana_{job["id"]}_{i}.wav'
            audio_window(drive,inp/name,seg['start'],seg['model_frames']/FPS)
            first = None
            if tail:
                first = f'banana_{job["id"]}_{i}.png'
                (inp/first).write_bytes(tail.read_bytes())
            seg['status']='rewriting'; write_state(job)
            saved = work/f'{i:02d}_prompt.txt'
            state_replanned=False
            state_in=clip_input(ledger,seg) if ledger is not None else None
            record=cached_clip(work,ledger,seg) if ledger is not None else None
            if ledger is not None and record is not None and job.get('resuming'):
                prompt=record['clip_prompt'];seg['scene_state_debug']=record
            elif ledger is None and job.get('resuming') and saved.is_file() and not seg.get('refresh_prompt'):
                from banana_mv.core import normalize_mv_prompt
                prompt=normalize_mv_prompt(saved.read_text(encoding='utf-8'),len(original)+int(bool(tail)))
            else:
                state_replanned=ledger is not None
                prompt=local_prompt(cfg,job['request'],seg,original,tail,scene_input=state_in,
                                    event_catalog=ledger['event_catalog'] if ledger is not None else None)
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
            (work/f'{i:02d}_prompt.txt').write_text(prompt,encoding='utf-8')
            if state_replanned:
                seg.pop('prompt_id',None)
                seg.pop('scene_state_prompt_sha256',None)
                seg.pop('refresh_prompt',None) # the new prompt/state pair is now durable
            wf = build_workflow(job['images_comfy'],name,*job['size'],seg['model_frames'],prompt,
                                (job['seed']+i) % (2**48),first,
                                **graph_options(job['request'],seg['seconds'],seg))
            preflight(cfg,wf)
            (work/f'{i:02d}_workflow_api.json').write_text(json.dumps(wf,ensure_ascii=False,indent=2),encoding='utf-8')
            seg['status']='generating'; write_state(job)
            entry = None
            if (job.get('resuming') and seg.get('prompt_id') and
                (ledger is None or seg.get('scene_state_prompt_sha256')==scene_digest(prompt))):
                candidate = backend.history_entry(cfg,seg['prompt_id'])
                if candidate and candidate.get('status',{}).get('completed') and candidate.get('status',{}).get('status_str')!='error':
                    entry = candidate
            if entry is None:
                pid = backend.queue_prompt(cfg,wf)
                seg['prompt_id']=pid
                if ledger is not None:seg['scene_state_prompt_sha256']=scene_digest(prompt)
                write_state(job)
                entry = wait_generation(cfg,pid,job)
            raw = work/f'{i:02d}_raw.mp4'
            backend.comfy_download(cfg,video_info(entry),raw)
            part = work/f'{i:02d}_part.mp4'
            trim_video(raw,part,seg['frames'])
            parts.append(part)
            if job['request']['mode']=='chain':
                tail = work/f'{i:02d}_last.png'
                last_frame(part,tail)
            if ledger is not None:
                if not valid_part(part,seg,job['size']):raise SceneStateError('片段未成功保存，不提交規劃狀態。')
                commit_clip(work,ledger,seg['scene_state_debug'])
                job['scene_state_summary']['committed_clips']=len(ledger['commits'])
            seg.pop('refresh_prompt',None)
            seg['status']='done'; write_state(job)
            (inp/name).unlink(missing_ok=True)
            if first:
                (inp/first).unlink(missing_ok=True)
        if job['id'] in CANCEL:
            job['status']='cancelled'; write_state(job); return
        job['status']='assembling'; write_state(job)
        assemble(parts,song,work/'final.mp4',job['duration'],job['output_size'])
        try:
            export_finished_video(job,work/'final.mp4')
        except OSError as error:
            job['export_error']=f'成品已合成，但另存 videos 資料夾失敗：{error}；仍可由前端下載。'
        job.pop('resuming',None)
        job['status']='done'; job['video']=f'/api/mv/file?id={job["id"]}'; write_state(job)
    except Exception as e:
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
        CANCEL.discard(job['id'])
        GPU_LOCK.release()


def start(req):
    cfg = copy.deepcopy(backend.load_config())
    req=dict(req,sampling_steps=req.get('sampling_steps',8),audio_analysis=req.get('audio_analysis', True),
             director_version=2,optimizer_version=1,story_plan=req.get('story_plan', True),
             director_authority=bool(req.get('story_plan',True) and req.get('rewrite',True)),
             kitchen_attention=req.get('kitchen_attention',req.get('acceleration',True)),
             sparse_attention=req.get('sparse_attention',req.get('acceleration',False)))
    if not isinstance(req.get('persistent_scene_state',True),bool):
        raise ValueError('persistent_scene_state 必須為布林值。')
    req['scene_state_version']=1 if req.get('persistent_scene_state',True) and req.get('rewrite',True) else 0
    if 'face_identity' in req and not isinstance(req['face_identity'], bool):
        raise ValueError('face_identity 必須為布林值。')
    if not isinstance(req['audio_analysis'], bool):
        raise ValueError('audio_analysis 必須為布林值。')
    if not isinstance(req['story_plan'], bool):
        raise ValueError('story_plan 必須為布林值。')
    if req.get('mode') not in ('independent','chain'):
        raise ValueError('請選獨立版或末幀接續版。')
    image_ids = req.get('image_ids')
    if image_ids is None:
        image_ids = [req.get('image_id')]
    image_ids = reference_images(image_ids, req['mode']=='chain')
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
    plan = segments(seconds,float(req.get('segment_seconds',15)))
    for seg in plan:
        seg.update(song_seconds=seconds,segment_count=len(plan))
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
    req = normalize_references(dict(req,prompt=str(req.get('prompt',''))[:10000]),seconds)
    # Fail invalid image mentions before queueing any rewrite or GPU work.
    fallback_prompt(req['prompt'], False, '', len(images))
    images_comfy = [img['comfy_name'] for img in images]
    graph = build_workflow(images_comfy,'preflight.wav',*size,plan[0]['model_frames'],'',seed,
                           **graph_options(req,plan[0]['seconds']))
    preflight(cfg,graph)
    if not GPU_LOCK.acquire(blocking=False):
        raise ValueError('已有 MV 工作執行中，請等它完成。')
    try:
        queue = backend.comfy(cfg,'/queue')
        if queue.get('queue_running') or queue.get('queue_pending'):
            raise ValueError('ComfyUI 還有其他工作，請先等它完成。')
        job_id=uuid.uuid4().hex[:12]
        (RUNS/job_id).mkdir()
        job={'id':job_id,'status':'running','created':time.time(),'request':req,
             'duration':seconds,'segments':plan,'size':size,'seed':seed,'timeline_source':'decoded_audio',
             'output_size':output_size, 'title':str(req.get('project_name') or music['name'])[:120],
             'settings_version':2,
             'image_comfy':images_comfy[0], 'images_comfy':images_comfy,
             'note':'尚未完成 Colab GPU 實測；末幀接續不攜帶前段動作 latent。'}
        save_sources(job,original,song,drive)
        original,song,drive = project_inputs(job,cfg)
        write_state(job)
        threading.Thread(target=worker,args=(job,cfg,original,song,drive),daemon=True).start()
        return job
    except Exception:
        GPU_LOCK.release(); raise


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
    if any(list(work.glob(pattern)) for pattern in ('*_prompt.txt','*_workflow_api.json','*_part.mp4','*_raw.mp4')):
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


def resume(job_id):
    if not GPU_LOCK.acquire(blocking=False):
        raise ValueError('已有 MV 執行中，不能重複續跑。')
    try:
        job=read_state(job_id)
        if job['status'] not in ('error','cancelled','interrupted'):
            raise ValueError('這個專案沒有待續跑的失敗或中斷工作。')
        cfg=copy.deepcopy(backend.load_config())
        queue=backend.comfy(cfg,'/queue')
        if queue.get('queue_running') or queue.get('queue_pending'):
            raise ValueError('ComfyUI 仍在執行工作，請等佇列清空再續跑。')
        originals,song,drive=project_inputs(job,cfg)
        repair_unstarted_timeline(job,song)
        if 'sampling_steps' not in job['request']:
            # Existing projects keep their saved schedule rather than silently mixing 6 and 8 steps.
            saved=sorted(job_dir(job_id).glob('*_workflow_api.json'))
            saved_steps=6
            if saved:
                previous=json.loads(saved[0].read_text(encoding='utf-8'))
                saved_steps=next((n['inputs']['steps'] for n in previous.values()
                                  if n['class_type']=='BasicScheduler'),6)
            job['request']['sampling_steps']=saved_steps
        # Older projects predate explicit feature switches. Infer only absent switches.
        if not job.get('settings_version'):
            workflows=sorted(job_dir(job_id).glob('*_workflow_api.json'))
            prompts=sorted(job_dir(job_id).glob('*_prompt.txt'))
            if workflows:
                graph=json.loads(workflows[0].read_text(encoding='utf-8'))
                kinds={n['class_type'] for n in graph.values()}
                job['request'].setdefault('kitchen_attention','ModelAttentionBackend' in kinds)
                job['request'].setdefault('sparse_attention','BlockSparseAttention' in kinds)
                job['request'].setdefault('acceleration','BlockSparseAttention' in kinds)
                job['request'].setdefault('motion_lora','LoraLoaderModelOnly' in kinds)
            if prompts:
                job['request'].setdefault('face_identity','[BANANA_FACE_IDENTITY_V1]' in prompts[0].read_text(encoding='utf-8'))
        missing=False
        for seg in job['segments']:
            part=job_dir(job_id)/f"{seg['index']:02d}_part.mp4"
            usable=valid_part(part,seg,job['size'])
            if not usable or (missing and job['request']['mode']=='chain'):
                seg['status']='waiting'
                if missing and job['request']['mode']=='chain':
                    seg.pop('prompt_id',None)
                    seg['refresh_prompt']=True
                missing=True
            else:
                seg['status']='done'
        if missing:
            graph=build_workflow(job['images_comfy'],'preflight.wav',*job['size'],job['segments'][0]['model_frames'],'',
                                 job['seed'],**graph_options(job['request'],job['segments'][0]['seconds']))
            preflight(cfg,graph)
        job.update(status='running',resuming=True,resumed=time.time())
        job.pop('error',None);job.pop('video',None);CANCEL.discard(job_id)
        write_state(job)
        threading.Thread(target=worker,args=(job,cfg,originals,song,drive),daemon=True).start()
        return job
    except Exception:
        GPU_LOCK.release();raise


class Handler(WebHandler):
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path in ('/','/mv'):
            return self.send_file(WEB/'index.html')
        if url.path=='/api/health':
            return self.send_json({'service':'banana-mv','standalone':True})
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
        if url.path=='/api/library':
            return self.send_json(backend.library_index())
        if url.path=='/api/mv/status':
            try:
                return self.send_json(read_state(dict(urllib.parse.parse_qsl(url.query))['id']))
            except Exception as e:
                return self.send_json({'error':str(e)},400)
        if url.path=='/api/mv/file':
            try:
                path=job_dir(dict(urllib.parse.parse_qsl(url.query))['id'])/'final.mp4'
                return self.send_file(path)
            except Exception as e:
                return self.send_json({'error':str(e)},400)
        return self.send_error(404)

    def do_POST(self):
        path=urllib.parse.urlparse(self.path).path
        try:
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
            if path=='/api/mv/resume':
                return self.send_json(resume(self.body_json()['id']))
            if path=='/api/mv/stop':
                job_id=self.body_json()['id']; read_state(job_id); CANCEL.add(job_id)
                return self.send_json({'ok':True,'message':'目前這段完成後停止。'})
            return self.send_error(404)
        except Exception as e:
            return self.send_json({'error':str(e)},400)


if __name__=='__main__':
    backend.LIBRARY.mkdir(parents=True,exist_ok=True)
    # Selected images are restored by project_inputs(); audio_window() writes
    # the needed audio slice. Do not block startup copying the entire Drive library.
    # Don't leave stale runs looking active after a Colab restart.
    for p in RUNS.glob('*/status.json'):
        job=json.loads(p.read_text(encoding='utf-8'))
        if job['status'] not in ('done','error','cancelled','interrupted'):
            job.update(status='interrupted',error='執行階段已重啟；已完成片段仍保存在工作資料夾。')
            write_state(job)
    print(f'Banana MV on http://127.0.0.1:{backend.PORT}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',backend.PORT),Handler).serve_forever()

