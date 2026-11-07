"""Paired policy test using the existing Banana 9B/Comfy service and frozen plan.

Run from the existing successful checkout; no model or Comfy installation here.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from banana_mv import services, shoot_plan
from banana_mv.scene_state import atomic_json
from banana_mv.t8_storyboard import DEFAULT_PATH, prepare


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(project,images,output,clip=0,seed=42,tail=None,t8_source=DEFAULT_PATH,workflow=None):
    project,output=Path(project),Path(output)
    # Never reuse either arm's saved prompt, or an existing comparison directory.
    output.mkdir(parents=True,exist_ok=False)
    status=json.loads((project/'status.json').read_text(encoding='utf-8'))
    plan=json.loads((project/'director_plan.json').read_text(encoding='utf-8'))
    req=copy.deepcopy(status['request']);req['rewrite_retries']=0
    if req.get('director_schema')!=5:raise ValueError('Only existing schema-5 projects are supported.')
    cfg=copy.deepcopy(services.load_config())
    if images is None:
        ids=req.get('image_ids') or [req.get('image_id')]
        images=[services.LIBRARY/services.asset(aid)['file'] for aid in ids]
    if not 0<=clip<len(status['segments']):raise ValueError('Clip index is outside the saved project.')
    queue=services.comfy(cfg,'/queue')
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise ValueError('Existing Comfy queue is busy; wait before starting this paired test.')
    # Verify before either GPU call. Downloads only the fixed source, not nodes/models.
    t8=prepare(t8_source)
    base=copy.deepcopy(status['segments'][clip])
    base.update(director_plan=copy.deepcopy(plan['segments'][clip]),
                direction_ending_contract=plan['ending_contract'])
    base.pop('shoot_setup',None)
    if base['director_plan'].get('handoff_version')!=1:
        raise ValueError('Old plan has no self-contained local commission; create a new project before this scope-isolated comparison.')
    if req.get('mode')=='chain' and clip>0 and not tail:
        raise ValueError('Chain comparisons need the same actual previous last frame for both arms.')
    files=list(images)+([tail] if tail else [])
    git=subprocess.run(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
    record={'experiment':'formal_camera_policy_vs_pinned_t8_v1','status':'prepared',
            'loaded_commit':git.stdout.strip() if git.returncode==0 else None,
            'loaded_shoot_plan_sha256':shoot_plan.LOADED_SHOOT_PLAN_SHA256,
            'loaded_services_sha256':services.LOADED_SERVICE_SHA256,
            'guide_sha256':sha(cfg['guides']['ref']),'guide':Path(cfg['guides']['ref']).read_text(),
            't8_source':t8,'seed_9b':int(seed),'cache':'bypassed; same frozen plan; fresh output',
            'source_files':{str(p):sha(p) for p in files},'frozen_request':req,'frozen_segment':base,
            'arms':{},'scope':'Paired whole-camera-policy test; not a single-sentence attribution or quality verdict.'}
    graph=None
    if workflow:
        graph=json.loads(Path(workflow).read_text(encoding='utf-8'))
        if 'prompt' not in graph.get('7',{}).get('inputs',{}):raise ValueError('Expected H3 node 7 prompt.')
        media=[]
        for node in graph.values():
            field={'LoadImage':'image','LoadAudio':'audio'}.get(node.get('class_type'))
            if field:
                value=node['inputs'][field]
                p=Path(value) if Path(value).is_absolute() else Path(cfg['comfy_input_dir'])/value
                if not p.is_file():raise ValueError('Frozen H3 media is missing: '+str(p))
                media.append({'path':str(p),'sha256':sha(p)})
        record['h3_template']=graph;record['h3_media']=media
    report=output/'comparison.json';atomic_json(report,record)
    for arm,enabled in [('A_current',False),('B_t8',True)]:
        folder=output/arm;folder.mkdir()
        arm_cfg=copy.deepcopy(cfg)
        arm_cfg.update(t8_storyboard=enabled,t8_source_path=str(t8_source),rewrite_trace_dir=str(folder/'trace'))
        arm_cfg['rewriter']['seed']=int(seed)
        seg=copy.deepcopy(base);result={'stage':'9b_rewrite','status':'running'}
        record['arms'][arm]=result;atomic_json(report,record)
        try:
            prompt=shoot_plan.write_shoot_prompt(arm_cfg,req,seg,images,tail,services.rewrite_local)
            (folder/'prompt.txt').write_text(prompt,encoding='utf-8')
            result.update(status='ok',final_prompt_sha256=sha(folder/'prompt.txt'))
            if graph is not None:
                result.update(stage='h3_generation',status='running');atomic_json(report,record)
                actual=copy.deepcopy(graph);actual['7']['inputs']['prompt']=prompt
                atomic_json(folder/'workflow_api.json',actual)
                # Only node 7 text changes. All renderer seeds/media/parameters stay frozen.
                pid=services.queue_prompt(cfg,actual);result['h3_prompt_id']=pid;atomic_json(report,record)
                history=services.wait_prompt(cfg,pid)
                atomic_json(folder/'h3_history.json',history)
                videos=[]
                for node in history.get('outputs',{}).values():
                    for values in node.values():
                        if not isinstance(values,list):continue
                        for item in values:
                            if isinstance(item,dict) and str(item.get('filename','')).lower().endswith('.mp4'):
                                dest=folder/f'{len(videos):02d}_{Path(item["filename"]).name}'
                                services.comfy_download(cfg,item,dest);videos.append(dest.name)
                result.update(status='ok',videos=videos)
                if not videos:raise ValueError('H3 completed but no MP4 output was found; inspect saved history.')
        except Exception as error:
            result.update(status='error',error_type=type(error).__name__,error=str(error))
            record['status']='error';atomic_json(report,record)
            # Queue timeout/failure may leave a task active; never blindly submit B.
            raise
        atomic_json(report,record)
    record['status']='completed';atomic_json(report,record)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',required=True,help='Existing job directory with status.json and director_plan.json')
    p.add_argument('--images',nargs='+',type=Path,help='Original references in fixed slot order; omitted uses saved asset IDs')
    p.add_argument('--output',required=True,type=Path,help='New empty destination (must not exist)')
    p.add_argument('--clip',default=0,type=int);p.add_argument('--seed',default=42,type=int)
    p.add_argument('--tail',type=Path);p.add_argument('--t8-source',default=DEFAULT_PATH,type=Path)
    p.add_argument('--workflow',type=Path,help='Opt in to H3 rendering using an existing frozen workflow and connected input files')
    a=p.parse_args()
    try:print(run(a.project,a.images,a.output,a.clip,a.seed,a.tail,a.t8_source,a.workflow))
    except Exception as error:
        if a.output.is_dir() and not (a.output/'comparison.json').is_file():
            atomic_json(a.output/'setup_error.json',{'stage':'preparation','type':type(error).__name__,'error':str(error)})
        raise
