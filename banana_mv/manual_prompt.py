"""Manually re-run the clip's local 9B director, without rendering H3.

The finished prompt is a reviewable draft. Only the user's later per-clip
retake action can generate video; neither the original prompt nor any
previously rendered media is overwritten by this module.
"""
import copy
import threading
import time
from pathlib import Path

from banana_mv import server as app


def _segment(job,index):
    if isinstance(index,bool) or not isinstance(index,int) or index<0 or index>=len(job['segments']):
        raise ValueError('無效的段落編號。')
    return job['segments'][index]


def rewrite_clip(job_id,index,previous_take=None):
    from banana_mv import takes
    if not app.GPU_LOCK.acquire(blocking=False):
        raise ValueError('已有 MV 或 9B 工作進行中，請稍後再重配丹方。')
    try:
        job=app.read_state(job_id)
        seg=_segment(job,index)
        if job['request'].get('director_schema') not in (5,6) or not job['request'].get('rewrite',True):
            raise ValueError('本功能適用於使用本地 9B 當段導演的作品。')
        if not isinstance(seg.get('director_plan'),dict) or seg['director_plan'].get('handoff_version')!=1:
            raise ValueError('這段缺少原始拍攝工單，無法安全重配；原提示詞不受影響。')
        cfg=copy.deepcopy(app.backend.load_config())
        takes.require_idle(job,cfg)
        originals,_,_=app.project_inputs(job,cfg)
        from banana_mv.python_slots import refresh_stale_timed_plan
        refresh_stale_timed_plan(job,originals,app.job_dir(job_id))
        source_take=None
        if app.is_continuation(job['request']['mode']) and index:
            source_take=(previous_take if previous_take is not None else
                         job.get('pending_takes',{}).get(str(index-1),
                         job['segments'][index-1].get('selected_take','original')))
            if not isinstance(source_take,str) or not source_take:
                raise ValueError('上一段接續版本無效，請選擇完整的丹藥版本。')
            previous=takes.take_source(job,index-1,source_take)
            if not app.valid_part(previous,job['segments'][index-1],job['size']):
                raise ValueError('上一段選定丹藥無效，不能用錯誤尾幀重配丹方。')
        elif previous_take is not None:
            raise ValueError('獨立模式／第一段沒有上一段尾幀。')
        app.preflight(cfg,{'encoder':{'class_type':'CLIPLoader','inputs':{'clip_name':cfg['rewriter']['model']}},
                           'generate':{'class_type':'TextGenerate','inputs':{}}})
        prev=seg.get('prompt_rewrite') or {}
        version=max(int(prev.get('version') or 0),int(prev.get('pending_version') or 0))+1
        seg['prompt_rewrite']={**prev,'status':'running','pending_version':version,
                               'previous_take':source_take,'error':''}
        app.write_state(job)
        threading.Thread(target=_worker,args=(job,cfg,index,originals,version,source_take),daemon=True).start()
        return takes.describe(job)
    except Exception:
        app.GPU_LOCK.release()
        raise


def _worker(job,cfg,index,originals,version,previous_take=None):
    seg=job['segments'][index];work=app.job_dir(job['id'])
    try:
        tail=None
        if app.is_continuation(job['request']['mode']) and index:
            from banana_mv import takes
            previous=takes.take_source(job,index-1,previous_take or job.get('pending_takes',{}).get(str(index-1),'current'))
            if job['request']['mode']=='chain5':
                frames=app.last_frames(previous,work/f'{index:02d}_manual_rewrite_tail_%02d.png')
                tail=frames[0]
            else:
                tail=work/f'{index:02d}_manual_rewrite_tail.png'
                app.last_frame(previous,tail)
        candidate=copy.deepcopy(seg)
        candidate.pop('prompt_rewrite',None)
        result=app.local_prompt(cfg,job['request'],candidate,originals,tail)
        if not isinstance(result,str) or not result.strip():
            raise ValueError('9B 沒有交出有效提示詞，原始提示詞與成片已保留。')
        file=work/f'{index:02d}_manual_prompt_v{version}.txt'
        tmp=file.with_suffix('.tmp')
        tmp.write_text(result,encoding='utf-8')
        tmp.replace(file)
        seg['prompt_rewrite']={
            'status':'ready','version':version,'text':result,'file':file.name,
            'created':time.time(),'previous_take':previous_take,
            'writer_calls':candidate.get('prompt_profile',{}).get('writer_calls'),
            'error':'',
        }
    except Exception as error:
        previous=seg.get('prompt_rewrite') or {}
        seg['prompt_rewrite']={**previous,'status':'error','error':str(error),
                               'pending_version':version}
    finally:
        try:app.write_state(job)
        finally:app.GPU_LOCK.release()
