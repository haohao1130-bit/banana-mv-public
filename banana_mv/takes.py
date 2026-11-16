"""Per-clip audition and bounded batch retakes; never replan the story ledger."""
import copy
import hashlib
import json
import random
import re
import shutil
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

from banana_mv import server as app
from banana_mv import masters

PREVIEW_LOCK=threading.Lock()
TERMINAL=('done','error','cancelled','interrupted')


def continuous_5070(job):
    """RTX 5070 Python+9B chain: a changed Take invalidates all later shots."""
    req=job.get('request',{})
    return req.get('director_schema')==6 and app.is_continuation(req.get('mode'))



def segment(job, index):
    if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(job['segments']):
        raise ValueError('無效的丹藥段落編號。')
    return job['segments'][index]


def take_dir(job,index,take_id):
    if take_id!='original' and (not isinstance(take_id,str) or len(take_id)!=12 or
                                any(c not in '0123456789abcdef' for c in take_id)):
        raise ValueError('無效的丹藥版本。')
    return app.job_dir(job['id'])/'takes'/f'{index:02d}'/take_id


def take_version(job,index,take_id):
    rows=segment(job,index).get('takes',[])
    for n,row in enumerate(rows,1):
        if row['id']==take_id:return row.get('version',n)
    if take_id=='original':return 1
    raise ValueError('找不到此丹藥版本。')


def take_file(job,index,take_id,name):
    version=take_version(job,index,take_id)
    stem,ext=name.rsplit('.',1)
    return app.job_dir(job['id'])/f'{index:02d}_{stem}_v{version}.{ext}'


def existing_file(job,index,take_id,name):
    path=take_file(job,index,take_id,name)
    if path.is_file():return path
    legacy=take_dir(job,index,take_id)/name
    if legacy.is_file():return legacy
    # Old root RAW belongs to the original render, never to an adopted retake.
    if take_id=='original' and (name=='raw.mp4' or not segment(job,index).get('takes')):
        root=app.job_dir(job['id'])/f'{index:02d}_{"workflow_api.json" if name=="workflow.json" else name}'
        if root.is_file():return root
    return path


def take_source(job,index,take_id='current'):
    seg=segment(job,index)
    if take_id=='current':
        if seg.get('status')!='done':raise ValueError('此段尚未煉製完成。')
        take_id=seg.get('selected_take','original')
    take=next((t for t in seg.get('takes',[]) if t['id']==take_id),None)
    if take_id!='original' and (not take or take['status']!='ready'):
        raise ValueError('此版本尚未完成，不能預覽或採用。')
    if take and take['status']!='ready':raise ValueError('此版本尚未完成。')
    path=existing_file(job,index,take_id,'part.mp4')
    if not path.is_file():raise ValueError('此段毛片遺失。')
    return path


def archive_original(job,index):
    """Copy known legacy versions into flat immutable files; never pair a retake with root RAW."""
    seg=segment(job,index);work=app.job_dir(job['id'])
    if not seg.get('takes'):
        seg['takes']=[{'id':'original','version':1,'status':'ready',
            'seed':seg.get('render_seed',(job['seed']+index)%(2**48)),
            'created':job.get('created',0),'prompt_id':seg.get('prompt_id')}]
        seg.setdefault('selected_take','original')
        # Root PART/prompt are original only before any archived takes exist.
        for name in ('part.mp4','raw.mp4','prompt.txt','workflow.json'):
            old=work/f'{index:02d}_{"workflow_api.json" if name=="workflow.json" else name}'
            target=take_file(job,index,'original',name)
            if old.is_file() and not target.exists():shutil.copyfile(old,target)
    for n,row in enumerate(seg['takes'],1):
        row.setdefault('version',n)
        for name in ('raw.mp4','part.mp4','prompt.txt','workflow.json','repair_request.json','repair_raw.txt','opening.png'):
            source=existing_file(job,index,row['id'],name);target=take_file(job,index,row['id'],name)
            if source.is_file() and source!=target and not target.exists():shutil.copyfile(source,target)
    dest=take_file(job,index,'original','prompt.txt')
    if not dest.exists() and seg.get('selected_take')=='original' and seg.get('prompt'):
        dest.write_text(seg['prompt'],encoding='utf-8')


def clip_url(job,index,take_id):
    return '/api/mv/clip?'+urllib.parse.urlencode({'id':job['id'],'index':index,'take':take_id})


def preview_source(job,index,take_id='current'):
    """Use the original H3 RAW (with its audio track) for audition only.

    Check the chosen take's trimmed part first: this enforces readiness and
    prevents accidentally pairing an earlier take's RAW with a newer video.
    Missing RAW on old projects falls back to the existing silent part.
    Assembly and continuity still exclusively use take_source()/part.mp4.
    """
    part=take_source(job,index,take_id)
    selected=(segment(job,index).get('selected_take','original')
              if take_id=='current' else take_id)
    raw=existing_file(job,index,selected,'raw.mp4')
    return (raw,'raw') if raw.is_file() else (part,'part')


def describe(job):
    """Cheap read-only status enrichment; preview RAW before trimmed fallback."""
    result=copy.deepcopy(job)
    work=app.job_dir(job['id'])
    if job.get('video') and (work/'final.mp4').is_file():result['final_video']=str(work/'final.mp4')
    for master in result.get('final_versions',[]):
        master['download']='/api/mv/file?'+urllib.parse.urlencode({'id':job['id'],'version':master['version']})
    for i,seg in enumerate(result['segments']):
        try:
            source,kind=preview_source(job,i)
            seg['preview']=clip_url(job,i,'current')+'&v='+str(source.stat().st_mtime_ns)
            seg['preview_kind']=kind
            seg['preview_filename']=source.name
        except ValueError:
            continue
        if not seg.get('takes'):
            seg['takes']=[{'id':'original','status':'ready','seed':(job['seed']+i)%(2**48),'created':job.get('created',0)}]
        seg.setdefault('selected_take','original')
        seg['pending_take']=job.get('pending_takes',{}).get(str(i),seg['selected_take'])
        for take in seg['takes']:
            if take['status']=='ready':
                audition,kind=preview_source(job,i,take['id'])
                take.update(version=take_version(job,i,take['id']),
                            filename=take_file(job,i,take['id'],'part.mp4').name,
                            preview=clip_url(job,i,take['id']),
                            preview_kind=kind,preview_filename=audition.name)
    return result


def preview(job,index,take_id='current'):
    """Stream original H3 RAW with native audio; never alter the final cut."""
    with PREVIEW_LOCK:
        return preview_source(job,index,take_id)[0]



def require_idle(job,cfg,check_queue=True):
    if job['status'] not in TERMINAL:raise ValueError('請先等這爐完成，或停止後再回爐／選丹。')
    if check_queue:
        queue=app.backend.comfy(cfg,'/queue')
        if queue.get('queue_running') or queue.get('queue_pending'):
            raise ValueError('ComfyUI 還有工作，請等佇列清空再回爐。')


def corrections(indices,instructions):
    if instructions is None:return {}
    if not isinstance(instructions,dict):raise ValueError('局部修改建議需按段落提供。')
    result={}
    for key,text in instructions.items():
        if key not in {str(i) for i in indices} or not isinstance(text,str):
            raise ValueError('局部修改建議只能指定已勾選的段落，內容需為文字。')
        if len(text)>3000:raise ValueError('每段局部修改建議最多 3000 字。')
        if text.strip():result[int(key)]=text.strip()
    return result


def manual_prompts(indices,prompts):
    """Validate an explicit per-clip editing override; do not invoke 9B."""
    if prompts is None:return {}
    if not isinstance(prompts,dict):
        raise ValueError('手動提示詞需依段落編號提供。')
    found={}
    for key,value in prompts.items():
        if not isinstance(key,str) or key not in {str(i) for i in indices}:
            raise ValueError('手動提示詞只能指定要回爐的段落。')
        if not isinstance(value,str) or len(value)>50000 or not value.strip():
            raise ValueError('手動提示詞必須是非空白文字，最多 50000 字。')
        found[int(key)]=value.strip()
    return found


def repair_prompt(cfg,job,seg,prompt,note,originals,tail,dest,prefix=""):
    """One bounded edit of the chosen clip prompt; never sees the full story."""
    from banana_mv.shoot_plan import NATIVE_ENHANCER_SYSTEM,REFERENCE_PERFORMANCE,_pictures,_text
    from banana_mv.core import normalize_mv_prompt
    from banana_mv.lyrics_reference import excerpt
    guide=Path(cfg['guides']['ref']).read_text(encoding='utf-8')
    system=NATIVE_ENHANCER_SYSTEM+guide+'\n'+REFERENCE_PERFORMANCE
    text=('Revise ONE existing H3 clip prompt using only the requested local corrections. '
          'Preserve everything not targeted by the correction, including identity bindings, '
          'vocal roles, scene separation, action continuity and the local ending. '
          'Keep the target duration and native output format. Return the complete revised prompt, not a diff. '
          'The source audio is supplied to H3, not heard by you; retain <Audio 1>: fully_copy. '
          'Add no speech, lyrics, replacement soundtrack or subtitles. '
          'References identify actors, not frozen expressions or required cast attendance.\n'
          f'Target duration: {seg["seconds"]} seconds.\nOriginal clip prompt:\n'+prompt+
          '\nRequested local corrections:\n'+note+
          '\nLocal SRT timing reference:\n'+json.dumps(excerpt(job['request'],seg),ensure_ascii=False))
    refs=([tail] if tail else [])+list(originals)
    if tail:text+='\n<Picture 1> is the actual preceding last frame; other picture numbers already include this slot.'
    request={'system':system,'user':text,'references':[{'slot':i+1,'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()} for i,p in enumerate(refs)]}
    (dest/(prefix+'repair_request.json')).write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf-8')
    raw=app.backend.rewrite_local(cfg,system,[('text',text)]+_pictures(refs),uuid.uuid4().hex[:8])
    (dest/(prefix+'repair_raw.txt')).write_text(raw,encoding='utf-8')
    return normalize_mv_prompt(_text(raw),len(refs))


def retake(job_id,indices,instructions=None,prompts=None,auto_resume=False,rebuild_prompt=False,previous_takes=None):
    if not isinstance(indices,list) or not indices:raise ValueError('請勾選至少一顆需要回爐的丹藥。')
    if not isinstance(auto_resume,bool):raise ValueError('自動續跑參數必須為布林值。')
    if not isinstance(rebuild_prompt,bool):raise ValueError('重配提示詞參數必須為布林值。')
    if not app.GPU_LOCK.acquire(blocking=False):raise ValueError('已有 MV 工作執行中，請先等它完成。')
    try:
        job=app.read_state(job_id);cfg=copy.deepcopy(app.backend.load_config());require_idle(job,cfg)
        for i in indices:segment(job,i)
        indices=sorted(set(indices))
        if continuous_5070(job):
            if len(indices)!=1:
                raise ValueError('連續拍攝只能逐段修正；選用新版後請從其尾幀重新接拍後續。')
            restart=job.get('continuation_restart')
            if restart and indices[0]>restart['index']:
                raise ValueError('後續片段屬於舊時間線；請先從正式採用的新版尾幀續拍。')
        notes=corrections(indices,instructions)
        overrides=manual_prompts(indices,prompts)
        if previous_takes is None:previous_takes={}
        if not isinstance(previous_takes,dict):
            raise ValueError('上一段來源版本必須依段落指定。')
        resolved={}
        for key,take_id in previous_takes.items():
            if (not isinstance(key,str) or key not in {str(i) for i in indices}
                    or not isinstance(take_id,str) or not take_id):
                raise ValueError('上一段版本只能指定本次回爐的段落。')
            i=int(key)
            if i==0 or not app.is_continuation(job['request']['mode']):
                raise ValueError('第一段或獨立模式沒有上一段尾幀。')
            preceding=segment(job,i-1)
            source=take_source(job,i-1,take_id)
            if not app.valid_part(source,preceding,job['size']):
                raise ValueError('上一段的選定 Take 已經損壞，停止回爐。')
            resolved[i]=take_id
        if any(i-1 in indices for i in resolved):
            raise ValueError('前段也在這批重新生成時，尾幀必須採用那個新版本，不可指定舊版。')
        if any(i in notes for i in overrides):
            raise ValueError('同一段不能同時指定手動完整提示詞與局部 9B 修稿。')
        if rebuild_prompt and (notes or overrides):
            raise ValueError('重新分析與手動丹方／局部修稿不能同時進行。')
        if rebuild_prompt and (job['request'].get('director_schema') not in (5,6) or not job['request'].get('rewrite',True)):
            raise ValueError('完整重新分析需要啟用本地 9B 導演。')
        if notes:
            if not Path(cfg.get('guides',{}).get('ref','')).is_file():
                raise ValueError('局部修改需要本地 9B 與原生指南，請先完成 Colab 模型下載。')
            app.preflight(cfg,{'encoder':{'class_type':'CLIPLoader','inputs':{'clip_name':cfg['rewriter']['model']}},
                               'generate':{'class_type':'TextGenerate','inputs':{}}})
        first_takes=set()
        for i in indices:
            seg=segment(job,i)
            # A failed 9B step can leave a planned clip with no first video.
            # A user-supplied full H3 prompt can film it as version 1.
            if seg.get('status')!='done' and not seg.get('takes') and i in overrides:
                first_takes.add(i)
            else:
                if not app.valid_part(take_source(job,i),seg,job['size']):
                    raise ValueError('選取段落缺少有效毛片，請先提供本段完整手動提示詞。')
                saved=app.job_dir(job_id)/f'{i:02d}_prompt.txt'
                if not (seg.get('prompt') or saved.is_file()):
                    raise ValueError('缺少原段落提示詞，無法保留劇本重拍。')
            if app.is_continuation(job['request']['mode']) and i>0:take_source(job,i-1)
        if auto_resume:
            if (len(indices)!=1 or indices[0] not in first_takes or
                    job['status'] not in ('error','cancelled','interrupted') or
                    any(seg.get('status')!='done' for seg in job['segments'][:indices[0]])):
                raise ValueError('自動續跑只適用於已停止的專案，從第一個未完成段落貼新稿回爐。')
        originals,song,drive=app.project_inputs(job,cfg)
        from banana_mv.python_slots import refresh_stale_timed_plan
        refresh_stale_timed_plan(job,originals,app.job_dir(job_id))
        if rebuild_prompt:
            app.preflight(cfg,{'encoder':{'class_type':'CLIPLoader',
                                          'inputs':{'clip_name':cfg['rewriter']['model']}},
                               'generate':{'class_type':'TextGenerate','inputs':{}}})
        # Retake with a user's full prompt: verify only media references,
        # not the model's creative vocabulary or arbitrary shot counts.
        from banana_mv.core import normalize_mv_prompt
        overrides={i:normalize_mv_prompt(text,len(originals)+
                       int(app.is_continuation(job['request']['mode']) and i>0))
                   for i,text in overrides.items()}
        app.restore_render_settings(job)
        first=segment(job,indices[0])
        graph=app.build_workflow(job['images_comfy'],'preflight.wav',*job['size'],first['model_frames'],'',
                                 job['seed'],**app.graph_options(job['request'],first['seconds'],first))
        app.preflight(cfg,graph)
        app.preflight_five_frame(cfg,job['request'],job['images_comfy'],job['size'],first,job['seed'])
        old_status=job['status'];batch=[]
        for i in indices:
            seg=segment(job,i)
            if i not in first_takes:archive_original(job,i)
            seeds={t['seed'] for t in seg.get('takes',[])};seed=random.randrange(2**48)
            while seed in seeds:seed=random.randrange(2**48)
            disk_versions=[int(m[1]) for p in app.job_dir(job_id).glob(f'{i:02d}_*_v*.*')
                           if (m:=re.search(r'_v(\d+)\.',p.name))]
            version=max(disk_versions+[t.get('version',n) for n,t in enumerate(seg.get('takes',[]),1)]+[0])+1
            take={'id':uuid.uuid4().hex[:12],'version':version,'seed':seed,'created':time.time(),'status':'waiting'}
            if i in first_takes:
                take['first_render']=True
            else:
                take['base_take']=job.get('pending_takes',{}).get(str(i),seg.get('selected_take','original'))
                take_source(job,i,take['base_take'])
            if i in notes:take['correction']=notes[i]
            if i in overrides:take['manual_prompt']=overrides[i]
            if rebuild_prompt:take['rebuild_prompt']=True
            if i in resolved:take['previous_take_override']=resolved[i]
            seg.setdefault('takes',[]).append(take);batch.append((i,take))
        job.update(status='retaking',resumed=time.time(),retake={'indices':indices,'status':'running','completed':0,
                   'auto_resume':auto_resume,'takes':{str(i):t['id'] for i,t in batch}})
        app.CANCEL.discard(job_id);app.write_state(job)
        threading.Thread(target=retake_worker,args=(job,cfg,song,drive,batch,old_status,originals),daemon=True).start()
        return describe(job)
    except Exception:
        app.GPU_LOCK.release();raise




def _lineage(job,index,take_id):
    """Get immutable generated-parent dependencies of a selected Take."""
    chosen={index:take_id}
    while index>0:
        current=chosen[index]
        row=next((t for t in segment(job,index).get('takes',[]) if t['id']==current),None)
        parent=row.get('previous_take') if row else None
        if parent is None:
            break  # Legacy video: no recorded version dependency.
        selected=segment(job,index-1).get('selected_take','original')
        chosen[index-1]=parent
        take_source(job,index-1,parent)
        index-=1
        if parent==selected:
            # Still inspect older recorded links: these Takes may themselves be
            # chained from a changed ancestor.
            continue
    return chosen

def _adopt_branch_clips(job, choices):
    """Adopt only ready immutable Takes for an unfinished project.

    Do not assemble a misleading partial master. Existing films and old Takes
    remain on disk for manual rollback.
    """
    pending=job.setdefault('pending_takes',{})
    for i, take_id in sorted(choices.items()):
        seg=segment(job,i)
        source=take_source(job,i,take_id)
        if not app.valid_part(source,seg,job['size']):
            raise ValueError('接續版毛片無效，保留原片。')
        archive_original(job,i)
        chosen=next((row for row in seg['takes'] if row['id']==take_id),None)
        if chosen is None:
            raise ValueError('找不到接續版丹藥。')
        seg['selected_take']=take_id
        seg['render_seed']=chosen['seed']
        seg['status']='done'
        prompt=existing_file(job,i,take_id,'prompt.txt')
        if prompt.is_file():
            seg['prompt']=prompt.read_text(encoding='utf-8')
        seg.pop('prompt_id',None)
        if chosen.get('prompt_id'):seg['prompt_id']=chosen['prompt_id']
        pending.pop(str(i),None)
    # Every previously unrendered clip needs an up-to-date initial frame and
    # freshly generated local filming prompt. Never replay completed shots.
    for seg in job['segments']:
        if seg.get('status')!='done':
            seg['status']='waiting'
            seg['refresh_prompt']=True
            seg.pop('prompt_id',None)
            seg.pop('interrupted_render',None)
            seg.pop('scene_state_prompt_sha256',None)
    job.pop('video',None)
    job['final_stale']=True


def _branch_finish(job, choices, song, cfg, originals, drive):
    """Finish one of two user-selected continuation semantics under GPU lock.

    Returns True only when the normal MV worker takes ownership of GPU_LOCK.
    """
    complete=all(s.get('status')=='done' for s in job['segments'])
    if complete:
        apply_takes(job,choices,song)
        job['status']='done'
        job['retake']['status']='done'
        for i in choices:job.setdefault('pending_takes',{}).pop(str(i),None)
        job['selection_revision']=uuid.uuid4().hex
        app.write_state(job)
        return False
    app.repair_unstarted_timeline(job,song)
    app.restore_render_settings(job)
    _adopt_branch_clips(job,choices)
    job.update(status='running',resuming=True,resumed=time.time())
    job['retake'].update(status='done',auto_resume=True,auto_resume_status='running')
    job.pop('error',None);job.pop('error_stage',None)
    app.CANCEL.discard(job['id'])
    app.write_state(job)
    return True


def _branch_direct_worker(job, choices, song, cfg, originals, drive, old_status):
    handoff=False
    try:
        # _branch_finish calls the standard worker synchronously for incomplete
        # jobs, which releases the GPU lock in its own finally block.
        handoff=_branch_finish(job,choices,song,cfg,originals,drive)
        if handoff:app.worker(job,cfg,originals,song,drive)
    except Exception as error:
        job['status']=old_status
        job['retake'].update(status='error',error=str(error))
        app.write_state(job)
    finally:
        if not handoff and app.GPU_LOCK.locked():
            app.GPU_LOCK.release()


def continue_from_take(job_id, index, take_id, mode, rewrite_retries=None):
    """Two explicit choices after an auditioned clip retake.

    only: adopt just this Take, keep existing downstream videos untouched.
    cascade: retake every completed downstream clip from the new tail frame
             with fresh, clip-local 9B prompts; resume any unrendered tail.
    """
    if mode not in ('only', 'cascade'):
        raise ValueError('請選擇只替換這段，或由新版尾幀重拍後續。')
    if not app.GPU_LOCK.acquire(blocking=False):
        raise ValueError('已有 MV 工作執行中，不能同時分支續跑。')
    handed_off=False
    try:
        job=app.read_state(job_id)
        cfg=copy.deepcopy(app.backend.load_config())
        require_idle(job,cfg)
        if rewrite_retries is not None:
            job['request']['rewrite_retries']=rewrite_retries
        seg=segment(job,index)
        if continuous_5070(job) and mode!='cascade':
            raise ValueError('5070 連續拍攝不可只換一段保留後續；請從新版尾幀重拍後段。')
        if continuous_5070(job) and seg.get('selected_take','original')!=take_id:
            raise ValueError('請先按「選用此丹」正式採用新版，再從它的尾幀接拍。')
        restart=job.get('continuation_restart')
        if continuous_5070(job) and restart and (
                restart['index']!=index or restart['take']!=take_id):
            raise ValueError('目前已有正式採用的待接拍版本；請從該段開始，勿混接舊時間線。')
        if seg.get('status')!='done':
            raise ValueError('請先完成這一段回爐，再選擇接續分支。')
        candidate=take_source(job,index,take_id)
        if not app.valid_part(candidate,seg,job['size']):
            raise ValueError('選取版本的影片無效，原片保留。')
        if any(s.get('status')!='done' for s in job['segments'][:index]):
            raise ValueError('前面仍有未完成片段，不能從這段繼續接拍。')
        lineage=_lineage(job,index,take_id)
        other_pending=[k for k,v in job.get('pending_takes',{}).items()
                       if int(k)>index
                       or (int(k)==index and v!=take_id)
                       or (int(k)<index and
                           (int(k) not in lineage or lineage[int(k)]!=v))]
        if other_pending:
            raise ValueError('尚有與本次接續鏈不一致的待採用版本，請先確認或取消那些選擇。')
        if mode=='cascade' and not app.is_continuation(job['request']['mode']):
            raise ValueError('新版尾幀接拍只適用於末幀／末五幀接續模式。')
        done_after=[i for i in range(index+1,len(job['segments']))
                    if job['segments'][i].get('status')=='done']
        if mode=='cascade' and done_after:
            # This branch is intentionally limited to the Python-owned
            # director; the whole-song plan stays frozen.
            if job['request'].get('director_schema')!=6 or not job['request'].get('rewrite',True):
                raise ValueError('後續逐段重寫需要啟用 5070 本機 Python 通告單與 9B。')
            if done_after!=list(range(index+1,index+1+len(done_after))):
                raise ValueError('後續已完成段落不連續，請先整理狀態再分支接拍。')
            app.preflight(cfg,{'encoder':{'class_type':'CLIPLoader',
                                          'inputs':{'clip_name':cfg['rewriter']['model']}},
                               'generate':{'class_type':'TextGenerate','inputs':{}}})
        originals,song,drive=app.project_inputs(job,cfg)
        from banana_mv.python_slots import refresh_stale_timed_plan
        refresh_stale_timed_plan(job,originals,app.job_dir(job_id))
        app.restore_render_settings(job)
        if mode=='cascade' and index+1>=len(job['segments']) and not continuous_5070(job):
            raise ValueError('這已是最後一段，沒有後續影片可重新接拍。')
        first=(segment(job,index+1) if mode=='cascade' and index+1<len(job['segments'])
               else (seg if not done_after else segment(job,done_after[0])))
        graph=app.build_workflow(job['images_comfy'],'preflight.wav',*job['size'],first['model_frames'],'',
                                 job['seed'],**app.graph_options(job['request'],first['seconds'],first))
        app.preflight(cfg,graph)
        app.preflight_five_frame(cfg,job['request'],job['images_comfy'],job['size'],first,job['seed'])
        old_status=job['status']
        # The current job timeline changes immediately: all successors are
        # newly pending, even if older Takes or root files still exist.
        # The archived video bytes stay intact for rollback only.
        if mode=='cascade':
            job['continuation_generation']={
                'anchor_index':index,'anchor_take':take_id,
                'anchor_version':take_version(job,index,take_id),
                'from_index':index+1,'total':len(job['segments'])-index-1,
                'started_at':time.time(),
            }
            for child in job['segments'][index+1:]:
                child['status']='waiting'
                child['refresh_prompt']=True
                child.pop('prompt_id',None)
                child.pop('interrupted_render',None)
                child.pop('scene_state_prompt_sha256',None)
        # Once the user starts the requested branch, it must not replay on a
        # later generic resume or silently pick a stale former continuation.
        job.pop('continuation_restart',None)
        job['retake']={'indices':[index], 'status':'running', 'operation':'continue_branch',
                       'branch':{'index':index,'take':take_id,'mode':mode,
                                 'lineage':{str(i):t for i,t in lineage.items()}},
                       'completed':0}
        if mode=='cascade' and done_after:
            archive_original(job,index)
            batch=[]
            for i in done_after:
                child=segment(job,i)
                archive_original(job,i)
                existing=[int(m[1]) for p in app.job_dir(job_id).glob(f'{i:02d}_*_v*.*')
                          if (m:=re.search(r'_v(\d+)\.',p.name))]
                version=max(existing+[t.get('version',n) for n,t in enumerate(child['takes'],1)]+[0])+1
                taken={'id':uuid.uuid4().hex[:12],'version':version,
                       'seed':random.randrange(2**48),'created':time.time(),
                       'status':'waiting','rebuild_prompt':True}
                child['takes'].append(taken);batch.append((i,taken))
            job.setdefault('pending_takes',{}).update({str(i):t for i,t in lineage.items()})
            job['retake'].update(indices=done_after,takes={str(i):t['id'] for i,t in batch})
            job.update(status='retaking',resumed=time.time())
            app.CANCEL.discard(job_id);app.write_state(job)
            threading.Thread(target=retake_worker,
                             args=(job,cfg,song,drive,batch,old_status,originals),
                             daemon=True).start()
        else:
            job.update(status='assembling',resumed=time.time())
            app.CANCEL.discard(job_id);app.write_state(job)
            threading.Thread(target=_branch_direct_worker,
                             args=(job,lineage,song,cfg,originals,drive,old_status),
                             daemon=True).start()
        handed_off=True
        return describe(job)
    finally:
        if not handed_off:
            app.GPU_LOCK.release()


def apply_takes(job,choices,song):
    """Build the new master before replacing any adopted clip; retain all old takes."""
    work=app.job_dir(job['id']);parts=[];prompts={};token=uuid.uuid4().hex[:12]
    for i in range(len(job['segments'])):
        if segment(job,i).get('status')=='done':archive_original(job,i)
    final=work/f'final_{token}_pending.mp4'
    complete=all(s.get('status')=='done' for s in job['segments'])
    try:
        for i,seg in enumerate(job['segments']):
            selected=choices.get(i,seg.get('selected_take','original'))
            row=next((t for t in seg.get('takes',[]) if t['id']==selected),None)
            if i and row and row.get('previous_take'):
                parent=choices.get(i-1,segment(job,i-1).get('selected_take','original'))
                if parent!=row['previous_take']:
                    raise ValueError(f'第 {i+1} 段接續版本需要第 {i} 段 Take '
                                     +row['previous_take']+'，凝丹選擇不一致。')
            source=take_source(job,i,choices.get(i,'current'))
            if not app.valid_part(source,seg,job['size']):raise ValueError('毛片驗證失敗，保留原版。')
            chosen=choices.get(i,seg.get('selected_take','original'))
            saved=existing_file(job,i,chosen,'prompt.txt')
            if saved.is_file():prompts[i]=saved.read_text(encoding='utf-8')
            parts.append(source)
        master=None
        if complete:
            masters.preserve_current(job,work)
            app.assemble(parts,song,final,job['duration'],job['output_size'],**({'effects':app.effects_source(job)} if job.get('effects_mix') else {}))
            master=masters.archive(job,work,final,'selection' if job.get('retake',{}).get('status')=='selecting' else 'retake',choices)
        with PREVIEW_LOCK:
            for i,take_id in choices.items():
                seg=segment(job,i);take=next(t for t in seg['takes'] if t['id']==take_id)
                seg.update(selected_take=take_id,render_seed=take['seed'])
                if i in prompts:seg['prompt']=prompts[i]
                # Missing-media recovery must refer to the selected render, not the old queue entry.
                seg.pop('prompt_id',None)
                if take.get('prompt_id'):seg['prompt_id']=take['prompt_id']
            if complete:
                final.replace(work/'final.mp4')
                job['current_master']=master['version']
                job['video']=f'/api/mv/file?id={job["id"]}&v={token}'
                job.pop('final_stale',None)
                job.pop('error',None);job.pop('error_stage',None)
                job.pop('resuming',None)
            else:
                job.pop('video',None);job['final_stale']=True
        if complete:
            try:app.export_finished_video(job,work/'final.mp4')
            except OSError as e:job['export_error']=f'成品已合成，但另存失敗：{e}；仍可下載。'
        return complete
    finally:
        final.unlink(missing_ok=True);final.with_suffix('.ffconcat').unlink(missing_ok=True)


def retake_worker(job,cfg,song,drive,batch,old_status,originals=None):
    work=app.job_dir(job['id']);choices={};temporary=[];current=None
    handoff=False
    try:
        for i,take in batch:
            if job['id'] in app.CANCEL:raise RuntimeError('已停止回爐；完成的新版本已保留，尚未替換原版。')
            current=take;seg=segment(job,i);dest=work
            def output(name):return take_file(job,i,take['id'],name)
            if take.get('first_render'):
                prompt=seg.get('prompt') or ''
            else:
                base=take.get('base_take',seg.get('selected_take','original'))
                saved=existing_file(job,i,base,'prompt.txt')
                prompt=saved.read_text(encoding='utf-8') if saved.is_file() else (seg.get('prompt') or (work/f'{i:02d}_prompt.txt').read_text(encoding='utf-8'))
            take['status']='generating';job['retake']['current']=i
            if job['retake'].get('branch',{}).get('mode')=='cascade':
                seg['status']='preparing'
            app.write_state(job)
            name=f'banana_retake_{job["id"]}_{take["id"]}.wav';inp=Path(cfg['comfy_input_dir'])
            overlap=5 if job['request']['mode']=='chain5' and i>0 else 0
            render_frames=(app.align_frames(max(124,seg['frames']+overlap))
                           if overlap else seg['model_frames'])
            temporary.append(inp/name)
            app.audio_window(drive,inp/name,seg['start']-overlap/app.FPS,render_frames/app.FPS)
            first=None;guide_files=[]
            if app.is_continuation(job['request']['mode']) and i>0:
                previous=choices.get(i-1,take.get('previous_take_override',
                    job.get('pending_takes',{}).get(str(i-1),'current')))
                source=take_source(job,i-1,previous)
                frame=output('opening.png')
                app.last_frame(source,frame)
                guide_paths=app.last_frames(source,output('last5_%02d.png')) if overlap else []
                anchor=guide_paths[0] if overlap else frame
                first=f'banana_retake_{take["id"]}.png'
                temporary.append(inp/first);shutil.copyfile(anchor,inp/first)
                if overlap:
                    guide_files=[first]
                    for number,image_path in enumerate(guide_paths[1:],1):
                        filename=f'banana_retake_{take["id"]}_guide_{number}.png'
                        temporary.append(inp/filename)
                        shutil.copyfile(image_path,inp/filename)
                        guide_files.append(filename)
                take['previous_take']=previous if previous!='current' else segment(job,i-1).get('selected_take','original')
            if take.get('manual_prompt') is not None:
                take['base_prompt_sha256']=hashlib.sha256(prompt.encode()).hexdigest()
                prompt=take.pop('manual_prompt')
                take['prompt_source']='manual_editor'
            elif take.get('correction'):
                take['status']='rewriting';app.write_state(job)
                take['base_prompt_sha256']=hashlib.sha256(prompt.encode()).hexdigest()
                prompt=repair_prompt(cfg,job,seg,prompt,take['correction'],originals,frame if first else None,dest,prefix=f'{i:02d}_v{take["version"]}_')
            elif take.get('rebuild_prompt'):
                take['status']='rewriting'
                if job['retake'].get('branch',{}).get('mode')=='cascade':
                    seg['status']='rewriting'
                app.write_state(job)
                candidate=copy.deepcopy(seg)
                prompt=app.local_prompt(cfg,job['request'],candidate,originals,
                                        frame if first else None)
                take['prompt_source']='fresh_9b_from_current_commission'
                take['prompt_profile']=candidate.get('prompt_profile',{})
            (output('prompt.txt')).write_text(prompt,encoding='utf-8')
            take['status']='generating'
            if job['retake'].get('branch',{}).get('mode')=='cascade':
                seg['status']='generating'
            app.write_state(job)
            graph=app.build_workflow(job['images_comfy'],name,*job['size'],render_frames,prompt,take['seed'],first,
                                     guide_frames=guide_files or None,
                                     **app.graph_options(job['request'],seg['seconds'],seg))
            graph['16']['inputs']['filename_prefix']=f'BananaMV/{job["id"]}/{i:02d}_v{take["version"]}'
            app.preflight(cfg,graph);(output('workflow.json')).write_text(json.dumps(graph,ensure_ascii=False,indent=2))
            if job['id'] in app.CANCEL:raise InterruptedError('已停止本次回爐。')
            take['prompt_id']=app.backend.queue_prompt(cfg,graph);app.write_state(job)
            if job['id'] in app.CANCEL:
                from banana_mv.comfy import cancel_prompt
                try:cancel_prompt(cfg,take['prompt_id'])
                except Exception:pass
                raise InterruptedError('已取消剛提交的回爐任務。')
            entry=app.wait_generation(cfg,take['prompt_id'],job)
            if job['id'] in app.CANCEL:raise InterruptedError('回爐生成已停止。')
            app.backend.comfy_download(cfg,app.video_info(entry),output('raw.mp4'))
            if overlap:
                app.trim_video(output('raw.mp4'),output('part.mp4'),seg['frames'],skip_frames=overlap)
            else:
                app.trim_video(output('raw.mp4'),output('part.mp4'),seg['frames'])
            if not app.valid_part(output('part.mp4'),seg,job['size']):raise ValueError('回爐毛片影格或尺寸不符。')
            take['status']='ready';choices[i]=take['id']
            if job['retake'].get('branch',{}).get('mode')=='cascade':
                # Commit each successful newly filmed segment as this run's
                # continuation source; never let an interrupted run silently
                # use the former selected take as if it were the new result.
                seg['status']='done'
                seg['selected_take']=take['id']
                seg['prompt']=prompt
                seg['render_seed']=take['seed']
                seg['prompt_id']=take['prompt_id']
                seg.pop('refresh_prompt',None)
                seg.pop('interrupted_render',None)
            if take.get('first_render'):
                # The first successful clip has no old film to audition.
                # Select it as the original version for safe later resume.
                seg['status']='done'
                seg['selected_take']=take['id']
                seg['prompt']=prompt
                seg['render_seed']=take['seed']
                seg['prompt_id']=take['prompt_id']
                seg.pop('interrupted_render',None)
            job['retake']['completed']=len(choices);app.write_state(job)
        if job['id'] in app.CANCEL:raise RuntimeError('已停止回爐；完成的新版本已保留，尚未替換原版。')
        # Completed clips remain separate candidates in the usual audition
        # path. Only a user's FIRST render of an interrupted clip is adopted
        # automatically, then the already-running GPU worker owns the handoff.
        job['retake']['status']='done'
        job['status']=old_status
        branch=job['retake'].get('branch')
        if branch and branch['mode']=='cascade':
            try:
                selected={int(i):v for i,v in branch.get('lineage',{}).items()}
                selected.update(choices)
                handoff=_branch_finish(job,selected,song,cfg,originals,drive)
            except Exception as error:
                job['retake'].update(status='error',error='接拍交接失敗：'+str(error))
                job['status']=old_status
        elif job['retake'].get('auto_resume'):
            try:
                app.repair_unstarted_timeline(job,song)
                app.restore_render_settings(job)
                job.update(status='running',resuming=True,resumed=time.time())
                job.pop('error',None);job.pop('error_stage',None)
                job.pop('video',None)
                job['retake']['auto_resume_status']='running'
                handoff=True
            except Exception as error:
                job['retake']['auto_resume_status']='error'
                job['retake']['auto_resume_error']=str(error)
    except Exception as e:
        cancelled=job['id'] in app.CANCEL or isinstance(e,InterruptedError)
        if current and current['status']!='ready':
            if cancelled:current.update(status='cancelled',error='使用者緊急停爐')
            else:current.update(status='error',error=str(e))
        job['status']=old_status
        if cancelled:job['retake'].update(status='cancelled',error='使用者緊急停爐')
        else:job['retake'].update(status='error',error=str(e))
    finally:
        for _,take in batch:
            if take['status']=='waiting':take['status']='cancelled'
        for p in temporary:p.unlink(missing_ok=True)
        app.CANCEL.discard(job['id'])
        try:app.write_state(job)
        finally:
            if not handoff:app.GPU_LOCK.release()
    if handoff:
        # Run in the same background worker under the existing GPU lock:
        # no new user click, no stale prompt, no queue handoff race.
        # app.worker releases that lock when finished (or interrupted).
        try:
            app.worker(job,cfg,originals,song,drive)
        except Exception as error:
            job['status']='error'
            job['error']='回爐成功，但自動續跑交接失敗：'+str(error)
            job['retake']['auto_resume_status']='error'
            job['retake']['auto_resume_error']=str(error)
            try:app.write_state(job)
            finally:
                if app.GPU_LOCK.locked():app.GPU_LOCK.release()



def select_take(job_id,index,take_id):
    """Adopt immediately for 5070 continuous shots; independent/legacy keeps pending selection."""
    if not app.GPU_LOCK.acquire(blocking=False):raise ValueError('已有 MV 工作執行中，請先等它完成。')
    try:
        job=app.read_state(job_id);cfg=copy.deepcopy(app.backend.load_config());require_idle(job,cfg,False)
        seg=segment(job,index);source=take_source(job,index,take_id)
        if take_id=='current':raise ValueError('請選擇明確的丹藥版本。')
        if not app.valid_part(source,seg,job['size']):raise ValueError('此版本毛片無效，保留原版。')
        archive_original(job,index)
        pending=job.setdefault('pending_takes',{})
        # RTX5070 emergency-stop editing is an ACTIVE Take adoption, not
        # the old, completed-project "select now / condense later" workflow.
        # The next filming run must observe selected_take immediately.
        emergency=continuous_5070(job)
        if emergency:
            lineage=_lineage(job,index,take_id)
            _adopt_branch_clips(job,lineage)
            # Pending selections are the OLD mix-and-condense workflow.
            # Adopt one authoritative lineage; never mix pending descendants.
            pending.clear()
            job.pop('continuation_generation',None)
            seg.pop('prompt_rewrite',None)
            if index+1 < len(job['segments']):
                job['continuation_restart']={'index':index,'take':take_id,
                                             'from_index':index+1,
                                             'rewrite_next_prompt':True}
            else:
                job.pop('continuation_restart',None)
        else:
            if take_id==seg.get('selected_take','original'):pending.pop(str(index),None)
            else:pending[str(index)]=take_id
        job['selection_revision']=uuid.uuid4().hex
        app.write_state(job);return describe(job)
    finally:app.GPU_LOCK.release()


def condense(job_id,revision=None):
    """Explicitly commit all pending choices into one new complete MV."""
    if not app.GPU_LOCK.acquire(blocking=False):raise ValueError('已有 MV 工作執行中，請稍後凝丹。')
    try:
        job=app.read_state(job_id);cfg=copy.deepcopy(app.backend.load_config());require_idle(job,cfg,False)
        if continuous_5070(job):
            raise ValueError('5070 連續拍攝已停用混選凝丹；請正式採用單段版本，再從該段尾幀重拍後續。')
        if revision is not None and revision!=job.get('selection_revision'):
            raise ValueError('選丹已有更新，請重新開啟專案核對後凝丹。')
        choices={int(i):t for i,t in job.get('pending_takes',{}).items()}
        if not choices:raise ValueError('請先選擇要採用的丹藥版本，再確認凝丹。')
        for i,t in choices.items():
            seg=segment(job,i)
            if not app.valid_part(take_source(job,i,t),seg,job['size']):raise ValueError('待採用毛片無效，請重新選丹。')
        if not all(seg.get('status')=='done' and app.valid_part(take_source(job,i),seg,job['size']) for i,seg in enumerate(job['segments'])):
            raise ValueError('尚有未完成片段，請先續跑完成，再確認凝丹。')
        _,song,_=app.project_inputs(job,cfg);old_status=job['status']
        job.update(status='assembling',retake={'indices':sorted(choices),'status':'selecting','operation':'condense'},resumed=time.time())
        app.write_state(job)
        try:threading.Thread(target=selection_worker,args=(job,choices,song,old_status),daemon=True).start()
        except Exception:
            job['status']=old_status;app.write_state(job);raise
        return describe(job)
    except Exception:app.GPU_LOCK.release();raise


def selection_worker(job,choices,song,old_status):
    try:
        complete=apply_takes(job,choices,song)
        if not complete:raise ValueError('片段尚未齊全，保留待採用選擇。')
        job['pending_takes']={};job['selection_revision']=uuid.uuid4().hex
        job['status']='done';job['retake']['status']='done'
    except Exception as e:
        job['status']=old_status;job['retake'].update(status='error',error=str(e))
    finally:
        try:app.write_state(job)
        finally:app.GPU_LOCK.release()

