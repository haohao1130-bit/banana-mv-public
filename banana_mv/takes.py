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


def describe(job):
    """Cheap read-only status enrichment; preview muxing is lazy, on playback."""
    result=copy.deepcopy(job)
    work=app.job_dir(job['id'])
    if job.get('video') and (work/'final.mp4').is_file():result['final_video']=str(work/'final.mp4')
    for master in result.get('final_versions',[]):
        master['download']='/api/mv/file?'+urllib.parse.urlencode({'id':job['id'],'version':master['version']})
    for i,seg in enumerate(result['segments']):
        try:
            source=take_source(job,i)
            seg['preview']=clip_url(job,i,'current')+'&v='+str(source.stat().st_mtime_ns)
        except ValueError:
            continue
        if not seg.get('takes'):
            seg['takes']=[{'id':'original','status':'ready','seed':(job['seed']+i)%(2**48),'created':job.get('created',0)}]
        seg.setdefault('selected_take','original')
        seg['pending_take']=job.get('pending_takes',{}).get(str(i),seg['selected_take'])
        for take in seg['takes']:
            if take['status']=='ready':take.update(version=take_version(job,i,take['id']), filename=take_file(job,i,take['id'],'part.mp4').name, preview=clip_url(job,i,take['id']))
    return result


def preview(job,index,take_id='current'):
    """Silent trimmed H3 frames; only final assembly mixes the original song."""
    with PREVIEW_LOCK:
        return take_source(job,index,take_id)



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


def retake(job_id,indices,instructions=None):
    if not isinstance(indices,list) or not indices:raise ValueError('請勾選至少一顆需要回爐的丹藥。')
    if not app.GPU_LOCK.acquire(blocking=False):raise ValueError('已有 MV 工作執行中，請先等它完成。')
    try:
        job=app.read_state(job_id);cfg=copy.deepcopy(app.backend.load_config());require_idle(job,cfg)
        for i in indices:segment(job,i)
        indices=sorted(set(indices))
        notes=corrections(indices,instructions)
        if notes:
            if not Path(cfg.get('guides',{}).get('ref','')).is_file():
                raise ValueError('局部修改需要本地 9B 與原生指南，請先完成 Colab 模型下載。')
            app.preflight(cfg,{'encoder':{'class_type':'CLIPLoader','inputs':{'clip_name':cfg['rewriter']['model']}},
                               'generate':{'class_type':'TextGenerate','inputs':{}}})
        for i in indices:
            seg=segment(job,i)
            if not app.valid_part(take_source(job,i),seg,job['size']):raise ValueError('選取段落缺少有效毛片，請先續跑完成。')
            saved=app.job_dir(job_id)/f'{i:02d}_prompt.txt'
            if not (seg.get('prompt') or saved.is_file()):raise ValueError('缺少原段落提示詞，無法保留劇本重拍。')
            if job['request']['mode']=='chain' and i>0:take_source(job,i-1)
        originals,song,drive=app.project_inputs(job,cfg)
        app.restore_render_settings(job)
        first=segment(job,indices[0])
        graph=app.build_workflow(job['images_comfy'],'preflight.wav',*job['size'],first['model_frames'],'',
                                 job['seed'],**app.graph_options(job['request'],first['seconds'],first))
        app.preflight(cfg,graph)
        old_status=job['status'];batch=[]
        for i in indices:
            archive_original(job,i);seg=segment(job,i)
            seeds={t['seed'] for t in seg['takes']};seed=random.randrange(2**48)
            while seed in seeds:seed=random.randrange(2**48)
            disk_versions=[int(m[1]) for p in app.job_dir(job_id).glob(f'{i:02d}_*_v*.*')
                           if (m:=re.search(r'_v(\d+)\.',p.name))]
            version=max(disk_versions+[t.get('version',n) for n,t in enumerate(seg['takes'],1)])+1
            take={'id':uuid.uuid4().hex[:12],'version':version,'seed':seed,'created':time.time(),'status':'waiting'}
            take['base_take']=job.get('pending_takes',{}).get(str(i),seg.get('selected_take','original'))
            take_source(job,i,take['base_take'])
            if i in notes:take['correction']=notes[i]
            seg['takes'].append(take);batch.append((i,take))
        job.update(status='retaking',resumed=time.time(),retake={'indices':indices,'status':'running','completed':0,
                   'takes':{str(i):t['id'] for i,t in batch}})
        app.CANCEL.discard(job_id);app.write_state(job)
        threading.Thread(target=retake_worker,args=(job,cfg,song,drive,batch,old_status,originals),daemon=True).start()
        return describe(job)
    except Exception:
        app.GPU_LOCK.release();raise


def apply_takes(job,choices,song):
    """Build the new master before replacing any adopted clip; retain all old takes."""
    work=app.job_dir(job['id']);parts=[];prompts={};token=uuid.uuid4().hex[:12]
    for i in range(len(job['segments'])):
        if segment(job,i).get('status')=='done':archive_original(job,i)
    final=work/f'final_{token}_pending.mp4'
    complete=all(s.get('status')=='done' for s in job['segments'])
    try:
        for i,seg in enumerate(job['segments']):
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
    try:
        for i,take in batch:
            if job['id'] in app.CANCEL:raise RuntimeError('已停止回爐；完成的新版本已保留，尚未替換原版。')
            current=take;seg=segment(job,i);dest=work
            def output(name):return take_file(job,i,take['id'],name)
            base=take.get('base_take',seg.get('selected_take','original'))
            saved=existing_file(job,i,base,'prompt.txt')
            prompt=saved.read_text(encoding='utf-8') if saved.is_file() else (seg.get('prompt') or (work/f'{i:02d}_prompt.txt').read_text(encoding='utf-8'))
            take['status']='generating';job['retake']['current']=i;app.write_state(job)
            name=f'banana_retake_{job["id"]}_{take["id"]}.wav';inp=Path(cfg['comfy_input_dir'])
            temporary.append(inp/name);app.audio_window(drive,inp/name,seg['start'],seg['model_frames']/app.FPS)
            first=None
            if job['request']['mode']=='chain' and i>0:
                previous=choices.get(i-1,job.get('pending_takes',{}).get(str(i-1),'current'));frame=output('opening.png')
                app.last_frame(take_source(job,i-1,previous),frame)
                first=f'banana_retake_{take["id"]}.png';temporary.append(inp/first);shutil.copyfile(frame,inp/first)
                take['previous_take']=previous if previous!='current' else segment(job,i-1).get('selected_take','original')
            if take.get('correction'):
                take['status']='rewriting';app.write_state(job)
                take['base_prompt_sha256']=hashlib.sha256(prompt.encode()).hexdigest()
                prompt=repair_prompt(cfg,job,seg,prompt,take['correction'],originals,frame if first else None,dest,prefix=f'{i:02d}_v{take["version"]}_')
            (output('prompt.txt')).write_text(prompt,encoding='utf-8')
            take['status']='generating';app.write_state(job)
            graph=app.build_workflow(job['images_comfy'],name,*job['size'],seg['model_frames'],prompt,take['seed'],first,
                                     **app.graph_options(job['request'],seg['seconds'],seg))
            graph['16']['inputs']['filename_prefix']=f'BananaMV/{job["id"]}/{i:02d}_v{take["version"]}'
            app.preflight(cfg,graph);(output('workflow.json')).write_text(json.dumps(graph,ensure_ascii=False,indent=2))
            take['prompt_id']=app.backend.queue_prompt(cfg,graph);app.write_state(job)
            entry=app.wait_generation(cfg,take['prompt_id'],job)
            app.backend.comfy_download(cfg,app.video_info(entry),output('raw.mp4'))
            app.trim_video(output('raw.mp4'),output('part.mp4'),seg['frames'])
            if not app.valid_part(output('part.mp4'),seg,job['size']):raise ValueError('回爐毛片影格或尺寸不符。')
            take['status']='ready';choices[i]=take['id'];job['retake']['completed']=len(choices);app.write_state(job)
        if job['id'] in app.CANCEL:raise RuntimeError('已停止回爐；完成的新版本已保留，尚未替換原版。')
        # Candidates remain separate from adopted parts and the current master.
        job['status']=old_status
        job['retake']['status']='done'
    except Exception as e:
        if current and current['status']!='ready':current.update(status='error',error=str(e))
        job['status']=old_status;job['retake'].update(status='error',error=str(e))
    finally:
        for _,take in batch:
            if take['status']=='waiting':take['status']='cancelled'
        for p in temporary:p.unlink(missing_ok=True)
        app.CANCEL.discard(job['id'])
        try:app.write_state(job)
        finally:app.GPU_LOCK.release()



def select_take(job_id,index,take_id):
    """Persist an audition choice only; never replace media or assemble here."""
    if not app.GPU_LOCK.acquire(blocking=False):raise ValueError('已有 MV 工作執行中，請先等它完成。')
    try:
        job=app.read_state(job_id);cfg=copy.deepcopy(app.backend.load_config());require_idle(job,cfg,False)
        seg=segment(job,index);source=take_source(job,index,take_id)
        if take_id=='current':raise ValueError('請選擇明確的丹藥版本。')
        if not app.valid_part(source,seg,job['size']):raise ValueError('此版本毛片無效，保留原版。')
        archive_original(job,index)
        pending=job.setdefault('pending_takes',{})
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

