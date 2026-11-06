"""Per-clip audition and bounded batch retakes; never replan the story ledger."""
import copy
import json
import random
import shutil
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

from banana_mv import server as app

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


def take_source(job,index,take_id='current'):
    seg=segment(job,index)
    if take_id=='current':
        if seg.get('status')!='done':raise ValueError('此段尚未煉製完成。')
        path=app.job_dir(job['id'])/f'{index:02d}_part.mp4'
    else:
        take_dir(job,index,take_id)  # validate even before metadata lookup
        take=next((t for t in seg.get('takes',[]) if t['id']==take_id),None)
        if take is None and take_id=='original' and not seg.get('selected_take'):
            return take_source(job,index)
        if not take or take['status']!='ready':raise ValueError('此版本尚未完成，不能預覽或採用。')
        path=take_dir(job,index,take_id)/'part.mp4'
    if not path.is_file():raise ValueError('此段毛片遺失。')
    return path


def clip_url(job,index,take_id):
    return '/api/mv/clip?'+urllib.parse.urlencode({'id':job['id'],'index':index,'take':take_id})


def describe(job):
    """Cheap read-only status enrichment; preview muxing is lazy, on playback."""
    result=copy.deepcopy(job)
    for i,seg in enumerate(result['segments']):
        try:
            source=take_source(job,i)
            seg['preview']=clip_url(job,i,'current')+'&v='+str(source.stat().st_mtime_ns)
        except ValueError:
            continue
        if not seg.get('takes'):
            seg['takes']=[{'id':'original','status':'ready','seed':(job['seed']+i)%(2**48),'created':job.get('created',0)}]
        seg.setdefault('selected_take','original')
        for take in seg['takes']:
            if take['status']=='ready':take['preview']=clip_url(job,i,take['id'])
    return result


def preview(job,index,take_id='current'):
    """Silent trimmed H3 frames; only final assembly mixes the original song."""
    with PREVIEW_LOCK:
        return take_source(job,index,take_id)


def archive_original(job,index):
    seg=segment(job,index)
    if seg.get('takes'):return
    dest=take_dir(job,index,'original');dest.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(take_source(job,index),dest/'part.mp4')
    work=app.job_dir(job['id'])
    for source,name in ((work/f'{index:02d}_prompt.txt','prompt.txt'),
                        (work/f'{index:02d}_workflow_api.json','workflow.json')):
        if source.is_file():shutil.copyfile(source,dest/name)
    seg['takes']=[{'id':'original','status':'ready','seed':seg.get('render_seed',(job['seed']+index)%(2**48)),
                   'created':job.get('created',0),'prompt_id':seg.get('prompt_id')}]
    seg['selected_take']='original'


def require_idle(job,cfg,check_queue=True):
    if job['status'] not in TERMINAL:raise ValueError('請先等這爐完成，或停止後再回爐／選丹。')
    if check_queue:
        queue=app.backend.comfy(cfg,'/queue')
        if queue.get('queue_running') or queue.get('queue_pending'):
            raise ValueError('ComfyUI 還有工作，請等佇列清空再回爐。')


def retake(job_id,indices):
    if not isinstance(indices,list) or not indices:raise ValueError('請勾選至少一顆需要回爐的丹藥。')
    if not app.GPU_LOCK.acquire(blocking=False):raise ValueError('已有 MV 工作執行中，請先等它完成。')
    try:
        job=app.read_state(job_id);cfg=copy.deepcopy(app.backend.load_config());require_idle(job,cfg)
        for i in indices:segment(job,i)
        indices=sorted(set(indices))
        for i in indices:
            seg=segment(job,i)
            if not app.valid_part(take_source(job,i),seg,job['size']):raise ValueError('選取段落缺少有效毛片，請先續跑完成。')
            saved=app.job_dir(job_id)/f'{i:02d}_prompt.txt'
            if not (seg.get('prompt') or saved.is_file()):raise ValueError('缺少原段落提示詞，無法保留劇本重拍。')
            if job['request']['mode']=='chain' and i>0:take_source(job,i-1)
        _,song,drive=app.project_inputs(job,cfg)
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
            take={'id':uuid.uuid4().hex[:12],'seed':seed,'created':time.time(),'status':'waiting'}
            seg['takes'].append(take);batch.append((i,take))
        job.update(status='retaking',resumed=time.time(),retake={'indices':indices,'status':'running','completed':0,
                   'takes':{str(i):t['id'] for i,t in batch}})
        app.CANCEL.discard(job_id);app.write_state(job)
        threading.Thread(target=retake_worker,args=(job,cfg,song,drive,batch,old_status),daemon=True).start()
        return describe(job)
    except Exception:
        app.GPU_LOCK.release();raise


def apply_takes(job,choices,song):
    """Build the new master before replacing any adopted clip; retain all old takes."""
    work=app.job_dir(job['id']);parts=[];copies=[];token=uuid.uuid4().hex[:12]
    final=work/f'final_{token}_pending.mp4'
    complete=all(s.get('status')=='done' and (work/f'{s["index"]:02d}_part.mp4').is_file() for s in job['segments'])
    try:
        for i,seg in enumerate(job['segments']):
            source=take_source(job,i,choices[i]) if i in choices else work/f'{i:02d}_part.mp4'
            if i in choices:
                if not app.valid_part(source,seg,job['size']):raise ValueError('新版毛片驗證失敗，保留原版。')
                temp=work/f'{i:02d}_{token}_pending.mp4';shutil.copyfile(source,temp);copies.append((temp,work/f'{i:02d}_part.mp4'))
            parts.append(source)
        if complete:app.assemble(parts,song,final,job['duration'],job['output_size'])
        with PREVIEW_LOCK:
            for temp,target in copies:temp.replace(target)
            for i,take_id in choices.items():
                seg=segment(job,i);take=next(t for t in seg['takes'] if t['id']==take_id)
                seg.update(selected_take=take_id,render_seed=take['seed'])
                # Missing-media recovery must refer to the selected render, not the old queue entry.
                seg.pop('prompt_id',None)
                if take.get('prompt_id'):seg['prompt_id']=take['prompt_id']
                workflow=take_dir(job,i,take_id)/'workflow.json'
                if workflow.is_file():shutil.copyfile(workflow,work/f'{i:02d}_workflow_api.json')
            if complete:
                final.replace(work/'final.mp4')
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
        for temp,_ in copies:temp.unlink(missing_ok=True)


def retake_worker(job,cfg,song,drive,batch,old_status):
    work=app.job_dir(job['id']);choices={};temporary=[];current=None
    try:
        for i,take in batch:
            if job['id'] in app.CANCEL:raise RuntimeError('已停止回爐；完成的新版本已保留，尚未替換原版。')
            current=take;seg=segment(job,i);dest=take_dir(job,i,take['id']);dest.mkdir(parents=True,exist_ok=True)
            prompt=seg.get('prompt') or (work/f'{i:02d}_prompt.txt').read_text(encoding='utf-8')
            (dest/'prompt.txt').write_text(prompt,encoding='utf-8')
            take['status']='generating';job['retake']['current']=i;app.write_state(job)
            name=f'banana_retake_{job["id"]}_{take["id"]}.wav';inp=Path(cfg['comfy_input_dir'])
            temporary.append(inp/name);app.audio_window(drive,inp/name,seg['start'],seg['model_frames']/app.FPS)
            first=None
            if job['request']['mode']=='chain' and i>0:
                previous=choices.get(i-1,'current');frame=dest/'opening.png'
                app.last_frame(take_source(job,i-1,previous),frame)
                first=f'banana_retake_{take["id"]}.png';temporary.append(inp/first);shutil.copyfile(frame,inp/first)
                take['previous_take']=previous if previous!='current' else segment(job,i-1).get('selected_take','original')
            graph=app.build_workflow(job['images_comfy'],name,*job['size'],seg['model_frames'],prompt,take['seed'],first,
                                     **app.graph_options(job['request'],seg['seconds'],seg))
            app.preflight(cfg,graph);(dest/'workflow.json').write_text(json.dumps(graph,ensure_ascii=False,indent=2))
            take['prompt_id']=app.backend.queue_prompt(cfg,graph);app.write_state(job)
            entry=app.wait_generation(cfg,take['prompt_id'],job)
            app.backend.comfy_download(cfg,app.video_info(entry),dest/'raw.mp4')
            app.trim_video(dest/'raw.mp4',dest/'part.mp4',seg['frames'])
            if not app.valid_part(dest/'part.mp4',seg,job['size']):raise ValueError('回爐毛片影格或尺寸不符。')
            take['status']='ready';choices[i]=take['id'];job['retake']['completed']=len(choices);app.write_state(job)
        if job['id'] in app.CANCEL:raise RuntimeError('已停止回爐；完成的新版本已保留，尚未替換原版。')
        job['status']='assembling';app.write_state(job)
        complete=apply_takes(job,choices,song)
        job['status']='done' if complete else old_status
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
    if not app.GPU_LOCK.acquire(blocking=False):raise ValueError('已有 MV 工作執行中，請先等它完成。')
    try:
        job=app.read_state(job_id);cfg=copy.deepcopy(app.backend.load_config());require_idle(job,cfg,False)
        seg=segment(job,index);source=take_source(job,index,take_id)
        if take_id=='current' or take_id==seg.get('selected_take','original'):raise ValueError('這已是目前採用的版本。')
        if not app.valid_part(source,seg,job['size']):raise ValueError('此版本毛片無效，保留原版。')
        _,song,_=app.project_inputs(job,cfg);old_status=job['status']
        job.update(status='assembling',retake={'indices':[index],'status':'selecting'},resumed=time.time());app.write_state(job)
        threading.Thread(target=selection_worker,args=(job,index,take_id,song,old_status),daemon=True).start()
        return describe(job)
    except Exception:
        app.GPU_LOCK.release();raise


def selection_worker(job,index,take_id,song,old_status):
    try:
        complete=apply_takes(job,{index:take_id},song)
        job['status']='done' if complete else old_status;job['retake']['status']='done'
    except Exception as e:
        job['status']=old_status;job['retake'].update(status='error',error=str(e))
    finally:
        try:app.write_state(job)
        finally:app.GPU_LOCK.release()
