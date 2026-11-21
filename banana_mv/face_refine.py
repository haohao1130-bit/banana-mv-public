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


def template(app, cfg, *, dual=False, distant_only=False):
    if app.backend.PORT != 8193:
        raise ValueError('遠景救臉僅限本機 5070。')
    path = app.backend.DATA / 'face_refine_api.json'
    if dual or not path.is_file():
        source = default_template(app, cfg)
    else:
        source = path.read_text(encoding='utf-8-sig')
        for marker in ('__BANANA_VIDEO__', '__BANANA_FACE__', '__BANANA_OUTPUT__'):
            if json.dumps(marker) not in source:
                raise ValueError('修臉工作流缺少欄位 ' + marker)
    graph = json.loads(source)
    if distant_only:
        graph = distant_face_graph(graph)
    app.preflight(cfg, graph)
    return json.dumps(graph, ensure_ascii=False)


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
    return json.dumps(graph)


def refine_clip(app, cfg, job, seg, source, part, face, prefix, target, *, size=None):
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
        try:
            entry = app.wait_generation(cfg, app.backend.queue_prompt(cfg, graph), job)
        except RuntimeError as error:
            if 'BANANA_NO_DISTANT_FACE' in str(error):
                return False
            raise
        app.backend.comfy_download(cfg, app.video_info(entry), raw)
        if not app.valid_part(raw, seg, size or job['size']):
            raise ValueError('修臉輸出尺寸或影格數與原毛片不同。')
        trim_video(raw, target, seg['frames'])
    finally:
        raw.unlink(missing_ok=True)
        clip_file.unlink(missing_ok=True)
        if face_file is not None:
            face_file.unlink(missing_ok=True)


def candidates(app, cfg, job, indexed_parts, originals, source):
    import time
    from tempfile import TemporaryDirectory

    from banana_mv import takes
    from banana_mv.core import command

    work = app.job_dir(job['id'])
    selected = references(job['request'], len(originals))
    refined = {}
    for index, part in indexed_parts:
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
                        'stage': 'clip', 'index': index, 'total': len(job['segments']), 'reference': number,
                    }
                    app.write_state(job)
                    target = folder / f'face_{number}.mp4'
                    try:
                        if refine_clip(app, cfg, job, seg, source, candidate,
                                       originals[number - 1], f'{prefix}_{number}', target) is False:
                            continue
                    except Exception as error:
                        errors.append(f'@圖片{number}：{error}')
                    else:
                        candidate = target
                        completed.append(number)
                    if job['id'] in app.CANCEL:
                        return refined
                if not completed:
                    if errors:
                        raise ValueError('；'.join(errors))
                    seg['face_refine_status'] = 'skipped'
                    seg.pop('face_refine_error', None)
                    app.write_state(job)
                    continue
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
                seg.pop('face_refine_error', None)
                if errors:
                    seg['face_refine_error'] = '；'.join(errors)
                refined[index] = take_id
        except Exception as error:
            seg['face_refine_status'] = 'error'
            seg['face_refine_error'] = str(error)
        app.write_state(job)
    return refined


def chained_part(app, cfg, job, seg, part, originals, *, reuse=False):
    """Persist the refined take before using any of its frames as a guide."""
    from banana_mv import takes

    if (not job.get('face_refine_chain') or
            (far_only(job['request']) and job['request'].get('upscale_1080p'))):
        return part
    index = seg['index']
    base = seg.get('selected_take', 'original')
    receipt = seg.get('face_refine_handoff', {}) if reuse else {}
    if receipt.get('base') == base:
        if not receipt.get('take'):
            return part
        try:
            return takes.take_source(job, index, receipt['take'])
        except ValueError:
            # A previously used guide must not silently change during resume.
            raise ValueError(f'第 {index+1} 段修臉接續版本遺失，請恢復該檔案。') from None

    previous_status = job['status']
    job['status'] = 'refining_faces'
    try:
        seg.pop('face_refine_handoff', None)
        seg.pop('face_refine_references', None)
        job['face_refine_progress'] = {'stage': 'clip', 'index': index, 'total': len(job['segments'])}
        app.write_state(job)
        selected = references(job['request'], len(originals))
        source = template(app, cfg, dual=len(selected) == 2, distant_only=far_only(job['request']))
        refined = candidates(app, cfg, job, [(index, part)], originals, source)
        take = refined.get(index)
        if job['id'] not in app.CANCEL:
            seg['face_refine_handoff'] = {'base': base, 'take': take}
        return takes.take_source(job, index, take) if take else part
    except Exception as error:
        seg['face_refine_status'] = 'error'
        seg['face_refine_error'] = str(error)
        if job['id'] not in app.CANCEL:
            seg['face_refine_handoff'] = {'base': base, 'take': None}
        return part
    finally:
        job['status'] = previous_status
        app.write_state(job)


def render_version(app, cfg, job, parts, originals, song=None, **assembly_options):
    from banana_mv import masters, takes

    job.pop('face_refine_error', None)
    job['status'] = 'refining_faces'
    job['face_refine_progress'] = {'stage': 'preparing'}
    if job.get('face_refine_chain'):
        refined = {seg['index']: receipt['take'] for seg in job['segments']
                   if (receipt := seg.get('face_refine_handoff', {})).get('take')
                   and receipt.get('base') == seg.get('selected_take', 'original')}
    else:
        for segment in job['segments']:
            segment.pop('face_refine_status', None)
            segment.pop('face_refine_error', None)
            segment.pop('face_refine_references', None)
        app.write_state(job)
        selected = references(job['request'], len(originals))
        source = template(app, cfg, dual=len(selected) == 2, distant_only=far_only(job['request']))
        refined = candidates(app, cfg, job, enumerate(parts), originals, source)
    if job['id'] in app.CANCEL:
        job['face_refine_error'] = '已停止修臉。'
        return
    if not refined:
        if not all(segment.get('face_refine_status') == 'skipped' for segment in job['segments']):
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

def distant_face_graph(graph):
    for key, stitch in list(graph.items()):
        if stitch.get('class_type') != 'H3FaceStitch':
            continue
        inputs = stitch['inputs']
        transform = inputs.get('transform')
        if not isinstance(transform, list) or len(transform) != 2:
            raise ValueError('遠景修臉工作流需要 H3FaceTrackCrop 的 transform。')
        crops = [transform[0], 0]
        injections = [node['inputs'] for node in graph.values()
                      if node.get('class_type') == 'H3InjectVideoLatent'
                      and node['inputs'].get('images') == crops]
        if not injections:
            raise ValueError('遠景修臉工作流需要將裁切影像接到 H3InjectVideoLatent。')
        gate = f'banana_far_face_{key}'
        graph[gate] = {'class_type': 'BananaFarFaceGate',
                       'inputs': {'crops': crops, 'transform': transform}}
        for injection in injections:
            injection['images'] = [gate, 0]
        inputs.update(transform=[gate, 1], undetected_frames='fade_out')
    if not any(node.get('class_type') == 'BananaFarFaceGate' for node in graph.values()):
        raise ValueError('遠景修臉工作流缺少 H3FaceStitch。')
    return graph


def far_only(request):
    return request.get('upscale_resolution') == 1440


def render_upscaled_version(app, cfg, job, upscaled):
    """Refine the archived upscale as a separate master, keeping its original audio."""
    from tempfile import TemporaryDirectory
    from banana_mv import masters
    from banana_mv.core import FPS, command

    work = app.job_dir(job['id'])
    originals = [app.backend.safe_child(work, path) for path in job['sources']['images']]
    selected = references(job['request'], len(originals))
    workflow = template(app, cfg, dual=len(selected) == 2, distant_only=True)
    full_video = masters.source(job, work, upscaled['version'])
    size = upscaled['output_size']
    job.pop('face_refine_error', None)
    job['status'] = 'refining_faces'
    corrected = 0
    with TemporaryDirectory(prefix='face_after_vsr_', dir=work) as scratch:
        folder = Path(scratch)
        clips, start_frame = [], 0
        for index, segment in enumerate(job['segments']):
            if job['id'] in app.CANCEL:
                return
            base = folder / f'{index:02d}_base.mp4'
            command(['ffmpeg', '-v', 'error', '-ss', f'{start_frame / FPS:.9f}',
                     '-i', full_video, '-map', '0:v:0', '-frames:v', str(segment['frames']),
                     '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '0', base])
            if not app.valid_part(base, segment, size):
                raise ValueError(f'升頻成品第 {index+1} 段切片尺寸或影格數不符。')
            start_frame += segment['frames']
            candidate = base
            errors = []
            for number in selected:
                if job['id'] in app.CANCEL:
                    return
                job['face_refine_progress'] = {'stage': 'clip', 'index': index,
                                                'total': len(job['segments']), 'reference': number}
                app.write_state(job)
                prefix = f'banana_face_vsr_{job["id"]}_{index:02d}_{number}_{uuid.uuid4().hex[:8]}'
                target = folder / f'{index:02d}_refined_{number}.mp4'
                try:
                    if refine_clip(app, cfg, job, segment, workflow, candidate,
                                   originals[number - 1], prefix, target, size=size) is not False:
                        candidate = target
                except Exception as error:
                    errors.append(f'@圖片{number}：{error}')
            segment.pop('face_refine_error', None)
            if errors:
                segment['face_refine_error'] = '；'.join(errors)
            changed = candidate != base
            corrected += int(changed)
            segment['face_refine_status'] = ('partial' if changed else 'error') if errors else (
                'ready' if changed else 'skipped')
            clips.append(candidate.name)
        if job['id'] in app.CANCEL:
            return
        if not corrected:
            if any(segment.get('face_refine_error') for segment in job['segments']):
                job['face_refine_error'] = '沒有成功修臉的片段。'
            return

        job['face_refine_progress'] = {'stage': 'assembling'}
        app.write_state(job)
        listing = folder / 'frames.ffconcat'
        listing.write_text(''.join(f"file '{name}'\n" for name in clips), encoding='utf-8')
        pending = folder / 'refined.mp4'
        command(['ffmpeg', '-v', 'error', '-f', 'concat', '-i', listing, '-i', full_video,
                 '-map', '0:v:0', '-map', '1:a?', '-c:v', 'libx264', '-preset', 'fast',
                 '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-movflags', '+faststart', pending])
        if not app.valid_part(pending, {'frames': start_frame}, size):
            raise ValueError('升頻修臉版合成尺寸或影格數不符。')
        if job['id'] in app.CANCEL:
            return
        master = masters.archive(job, work, pending, 'face_refine',
                                 {int(index): take for index, take in upscaled['takes'].items()})
        master.update(source_master=upscaled['source_master'], source_version=upscaled['version'],
                      output_size=size, upscale_resolution=upscaled['upscale_resolution'], refined_clips=corrected)
    try:
        master['output_video'] = str(app.export_finished_video(
            job, work / master['file'], refined_version=master['version'],
            refined_resolution=upscaled['upscale_resolution']))
    except OSError as error:
        master['export_error'] = f'修臉版另存失敗：{error}'
