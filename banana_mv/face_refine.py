"""Optional FaceRefine pass using a locally configured ComfyUI API workflow."""
import json
from pathlib import Path
import uuid


def template(app, cfg):
    path = app.backend.DATA / 'face_refine_api.json'
    if not path.is_file():
        return default_template(app, cfg)
    source = path.read_text(encoding='utf-8-sig')
    for marker in ('__BANANA_VIDEO__', '__BANANA_FACE__', '__BANANA_OUTPUT__'):
        if json.dumps(marker) not in source:
            raise ValueError('修臉工作流缺少欄位 ' + marker)
    graph = json.loads(source)
    app.preflight(cfg, graph)
    return source


def default_template(app, cfg):
    from banana_mv.core import FPS, MODELS

    info = app.backend.comfy(cfg, '/object_info')
    graph = {}

    def add(key, kind, **inputs):
        if kind not in info:
            raise ValueError(f'缺少 {kind}。安裝修臉外掛後請重啟 ComfyUI。')
        for name, spec in info[kind]['input'].get('required', {}).items():
            if name in inputs:
                continue
            choices = spec[0]
            options = spec[1] if len(spec)>1 and isinstance(spec[1],dict) else {}
            if 'default' in options:
                inputs[name] = options['default']
            elif isinstance(choices,list) and choices:
                inputs[name] = choices[0]
            else:
                raise ValueError(f'修臉節點需要額外設定 {kind}.{name}。')
        graph[key] = {'class_type':kind,'inputs':inputs}
        return [key,0]

    add('model','UNETLoader',unet_name=MODELS['unet'],weight_dtype='default')
    add('clip','CLIPLoader',clip_name=MODELS['clip'],type='minimax',device='default')
    add('vae','VAELoader',vae_name=MODELS['video_vae'])
    audio_vae = add('audio_vae', 'VAELoader', vae_name=MODELS['audio_vae'])
    face = add('face','LoadImage',image='__BANANA_FACE__')
    if 'H3FaceSelect' not in info:
        raise ValueError('請先一鍵安裝 H3-FaceRefine，並重啟 ComfyUI。')
    detector_spec = info['H3FaceSelect']['input']['required']['detector'][0]
    detector = next((item for item in detector_spec if item.endswith('face_yolov8m.pt')),None)
    if detector is None:
        raise ValueError('找不到 face_yolov8m.pt，請確認模型目錄並重啟 ComfyUI。')
    add('source', 'H3FaceSelect', video='__BANANA_VIDEO__', detector=detector,
        select='identity_reference', identity_reference=face,
        cut_detection='auto (pyscenedetect)')
    crop = add('crop','H3FaceTrackCrop',images=['source',0],detector=detector,
               face_pick=['source',2],canvas_width=512,canvas_height=512,canvas_mode='manual',
               absent_shots='by_identity')
    cond = add('cond','MiniMaxH3ReferenceToVideo',clip=['clip',0],vae=['vae',0],
               audio_vae=audio_vae, ref_image_size='match',
               prompt='Preserve the source performance and refine the reference face.',
               width=['crop',4],height=['crop',5],length=['crop',6],
               **{'ref_images.ref_image_0':face})
    latent = add('latent','H3InjectVideoLatent',av_latent=['cond',1],images=crop,vae=['vae',0])
    model = add('shift','MiniMaxH3SigmaShift',model=['model',0],shift_video=12.,shift_audio=3.)
    guider = add('guider','BasicGuider',model=model,conditioning=cond)
    sigmas = add('sigmas','BasicScheduler',model=model,scheduler='simple',steps=8,denoise=.30)
    noise = add('noise','RandomNoise',noise_seed=0)
    sampler = add('sampler','KSamplerSelect',sampler_name='euler')
    sample = add('sample','SamplerCustomAdvanced',noise=noise,guider=guider,sampler=sampler,
                 sigmas=sigmas,latent_image=latent)
    decoded = add('decode','VAEDecode',samples=sample,vae=['vae',0])
    stitched = add('stitch','H3FaceStitch',base_images=['source',0],refined_crops=decoded,transform=['crop',1])
    video = add('video','CreateVideo',images=stitched,fps=float(FPS))
    add('save','SaveVideo',video=video,filename_prefix='__BANANA_OUTPUT__',
        format='mp4',**{'format.codec':'h264'})
    app.preflight(cfg,graph)
    return json.dumps(graph)


def candidates(app, cfg, job, parts, originals, source):
    from banana_mv import takes
    import shutil
    import subprocess
    import time

    work = app.job_dir(job['id'])
    inputs = Path(cfg['comfy_input_dir'])
    face = originals[job['request']['face_refine_reference'] - 1]
    refined = {}
    for index, part in enumerate(parts):
        if job['id'] in app.CANCEL:
            return
        seg = job['segments'][index]
        take_id = uuid.uuid4().hex[:12]
        prefix = f"banana_face_{job['id']}_{index:02d}_{take_id}"
        clip_file = inputs / (prefix + '.mp4')
        face_file = inputs / (prefix + face.suffix)
        try:
            shutil.copyfile(part, clip_file)
            shutil.copyfile(face, face_file)
            graph = json.loads(source.replace(
                '"__BANANA_VIDEO__"', json.dumps(str(clip_file))).replace(
                '"__BANANA_FACE__"', json.dumps(face_file.name)).replace(
                '"__BANANA_OUTPUT__"', json.dumps(prefix)))
            entry = app.wait_generation(cfg, app.backend.queue_prompt(cfg, graph), job)
            temp = work / (prefix + '.mp4')
            try:
                app.backend.comfy_download(cfg, app.video_info(entry), temp)
                if not app.valid_part(temp, seg, job['size']):
                    raise ValueError('修臉輸出尺寸或影格數與原毛片不同。')
                normalized = temp.with_suffix('.normalized.mp4')
                try:
                    from banana_mv.core import trim_video
                    trim_video(temp, normalized, seg['frames'])
                    normalized.replace(temp)
                finally:
                    normalized.unlink(missing_ok=True)
                if job['request'].get('production') == 'film':
                    muxed = temp.with_suffix('.audio.mp4')
                    try:
                        subprocess.run(['ffmpeg','-y','-v','error','-i',str(temp),'-i',str(part),
                                        '-map','0:v:0','-map','1:a:0','-c','copy',str(muxed)],check=True)
                        muxed.replace(temp)
                    finally:
                        muxed.unlink(missing_ok=True)
                takes.archive_original(job,index)
                version = max(takes.take_version(job,index,t['id']) for t in seg['takes']) + 1
                target = work / f'{index:02d}_part_v{version}.mp4'
                while target.exists():
                    version += 1
                    target = work / f'{index:02d}_part_v{version}.mp4'
                temp.replace(target)
                seg['takes'].append({'id':take_id, 'version':version, 'status':'ready',
                                     'seed':seg.get('render_seed',job['seed']+index),
                                     'created':time.time(), 'kind':'face_refine'})
                seg['face_refine_status'] = 'ready'
                seg.pop('face_refine_error', None)
                refined[index] = take_id
            finally:
                temp.unlink(missing_ok=True)
        except Exception as error:
            seg['face_refine_status'] = 'error'
            seg['face_refine_error'] = str(error)
        finally:
            clip_file.unlink(missing_ok=True)
            face_file.unlink(missing_ok=True)
        app.write_state(job)
    return refined


def render_version(app, cfg, job, parts, originals, song=None, **assembly_options):
    from banana_mv import masters, takes

    job.pop('face_refine_error', None)
    job['status'] = 'refining_faces'
    app.write_state(job)
    source = template(app, cfg)
    refined = candidates(app, cfg, job, parts, originals, source)
    if job['id'] in app.CANCEL:
        job['face_refine_error'] = '已停止修臉。'
        return
    if not refined:
        job['face_refine_error'] = '沒有成功修臉的片段，可在毛片放映室查看各段狀態。'
        return

    work = app.job_dir(job['id'])
    pending = work / 'face_refine_pending.mp4'
    source_master = job['current_master']
    base = next(row for row in job['final_versions'] if row['version'] == source_master)
    choices = {int(index): take_id for index, take_id in base['takes'].items()}
    compare = list(parts)
    for index, take_id in refined.items():
        choices[index] = take_id
        compare[index] = takes.take_source(job, index, take_id)
    try:
        app.assemble(compare, song, pending, job['duration'], job['output_size'], **assembly_options)
        master = masters.archive(job, work, pending, 'face_refine', choices)
        master.update(source_master=source_master, refined_clips=len(refined))
        try:
            output = app.export_finished_video(job, work / master['file'],
                                               refined_version=master['version'])
        except OSError as error:
            master['export_error'] = f'修臉版另存失敗：{error}'
        else:
            master['output_video'] = str(output)
    finally:
        pending.unlink(missing_ok=True)
        pending.with_suffix('.ffconcat').unlink(missing_ok=True)
