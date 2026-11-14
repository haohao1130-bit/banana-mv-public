"""Optional FaceRefine pass using a locally configured ComfyUI API workflow."""
import json
from pathlib import Path
import uuid


def references(request, count):
    primary = request.get('face_refine_reference')
    secondary = request.get('face_refine_reference_2')
    selected = (primary,) if secondary is None else (primary, secondary)
    if any(type(number) is not int or not 1 <= number <= count for number in selected):
        raise ValueError('請選擇已上傳的角色臉部參考圖。')
    if len(selected) == 2 and primary == secondary:
        raise ValueError('兩位角色請選不同的參考圖。')
    return selected


def template(app, cfg, *, dual=False):
    if app.backend.PORT != 8193:
        raise ValueError('遠景救臉僅限本機 5070。')
    path = app.backend.DATA / 'face_refine_api.json'
    if dual or not path.is_file():
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


def refine_clip(app, cfg, job, seg, source, part, face, prefix, target):
    import shutil

    from banana_mv.core import trim_video

    work = target.parent
    clip_file = work / (prefix + '.source.mp4')
    raw = work / (prefix + '.raw.mp4')
    face_file = None
    try:
        shutil.copyfile(part, clip_file)
        uploaded = app.backend.upload_comfy_image(
            cfg, prefix + face.suffix, face.read_bytes(), 'application/octet-stream')
        face_file = app.backend.safe_child(Path(cfg['comfy_input_dir']), uploaded)
        graph = json.loads(source.replace(
            '"__BANANA_VIDEO__"', json.dumps(str(clip_file.resolve()))).replace(
            '"__BANANA_FACE__"', json.dumps(uploaded)).replace(
            '"__BANANA_OUTPUT__"', json.dumps(prefix)))
        entry = app.wait_generation(cfg, app.backend.queue_prompt(cfg, graph), job)
        app.backend.comfy_download(cfg, app.video_info(entry), raw)
        if not app.valid_part(raw, seg, job['size']):
            raise ValueError('修臉輸出尺寸或影格數與原毛片不同。')
        trim_video(raw, target, seg['frames'])
    finally:
        raw.unlink(missing_ok=True)
        clip_file.unlink(missing_ok=True)
        if face_file is not None:
            face_file.unlink(missing_ok=True)


def candidates(app, cfg, job, parts, originals, source):
    import time
    from tempfile import TemporaryDirectory

    from banana_mv import takes
    from banana_mv.core import command

    work = app.job_dir(job['id'])
    selected = references(job['request'], len(originals))
    refined = {}
    for index, part in enumerate(parts):
        if job['id'] in app.CANCEL:
            break
        seg = job['segments'][index]
        take_id = uuid.uuid4().hex[:12]
        prefix = f"banana_face_{job['id']}_{index:02d}_{take_id}"
        completed, errors = [], []
        try:
            with TemporaryDirectory(prefix='face_refine_', dir=work) as scratch:
                folder = Path(scratch)
                candidate = part
                for number in selected:
                    job['face_refine_progress'] = {
                        'stage': 'clip', 'index': index, 'total': len(parts), 'reference': number,
                    }
                    app.write_state(job)
                    target = folder / f'face_{number}.mp4'
                    try:
                        refine_clip(app, cfg, job, seg, source, candidate,
                                    originals[number - 1], f'{prefix}_{number}', target)
                    except Exception as error:
                        errors.append(f'@圖片{number}：{error}')
                    else:
                        candidate = target
                        completed.append(number)
                    if job['id'] in app.CANCEL:
                        return refined
                if not completed:
                    raise ValueError('；'.join(errors))
                if job['request'].get('production') == 'film':
                    muxed = folder / 'with_audio.mp4'
                    command(['ffmpeg', '-v', 'error', '-i', candidate, '-i', part,
                             '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', muxed])
                    candidate = muxed
                takes.archive_original(job,index)
                version = max(takes.take_version(job,index,t['id']) for t in seg['takes']) + 1
                target = work / f'{index:02d}_part_v{version}.mp4'
                while target.exists():
                    version += 1
                    target = work / f'{index:02d}_part_v{version}.mp4'
                candidate.replace(target)
                seg['takes'].append({'id':take_id, 'version':version, 'status':'ready',
                                     'seed':seg.get('render_seed',job['seed']+index),
                                     'created':time.time(), 'kind':'face_refine'})
                seg['face_refine_status'] = 'partial' if errors else 'ready'
                seg['face_refine_references'] = completed
                if errors:
                    seg['face_refine_error'] = '；'.join(errors)
                refined[index] = take_id
        except Exception as error:
            seg['face_refine_status'] = 'error'
            seg['face_refine_error'] = str(error)
        app.write_state(job)
    return refined


def render_version(app, cfg, job, parts, originals, song=None, **assembly_options):
    from banana_mv import masters, takes

    job.pop('face_refine_error', None)
    job['status'] = 'refining_faces'
    job['face_refine_progress'] = {'stage': 'preparing'}
    for segment in job['segments']:
        segment.pop('face_refine_status', None)
        segment.pop('face_refine_error', None)
        segment.pop('face_refine_references', None)
    app.write_state(job)
    selected = references(job['request'], len(originals))
    source = template(app, cfg, dual=len(selected) == 2)
    refined = candidates(app, cfg, job, parts, originals, source)
    if job['id'] in app.CANCEL:
        job['face_refine_error'] = '已停止修臉。'
        return
    if not refined:
        job['face_refine_error'] = '沒有成功修臉的片段。'
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
    job['face_refine_progress'] = {'stage': 'assembling'}
    app.write_state(job)
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
