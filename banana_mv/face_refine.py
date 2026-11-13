"""Optional FaceRefine pass using a locally configured ComfyUI API workflow."""
import json
from pathlib import Path
import uuid


def template(app, cfg):
    if app.backend.PORT != 8193:
        raise ValueError('遠景救臉僅限本機 5070。')
    path = app.backend.DATA / 'face_refine_api.json'
    if not path.is_file():
        raise ValueError('請先安裝 H3-FaceRefine 並將 API 工作流存成 ' + str(path))
    source = path.read_text(encoding='utf-8-sig')
    for marker in ('__BANANA_VIDEO__', '__BANANA_FACE__', '__BANANA_OUTPUT__'):
        if json.dumps(marker) not in source:
            raise ValueError('修臉工作流缺少欄位 ' + marker)
    graph = json.loads(source)
    app.preflight(cfg, graph)
    return source


def candidates(app, cfg, job, parts, originals, source):
    from banana_mv import takes
    import shutil
    import time

    work = app.job_dir(job['id'])
    inputs = Path(cfg['comfy_input_dir'])
    face = originals[job['request']['face_refine_reference'] - 1]
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
            finally:
                temp.unlink(missing_ok=True)
        except Exception as error:
            seg['face_refine_status'] = 'error'
            seg['face_refine_error'] = str(error)
        finally:
            clip_file.unlink(missing_ok=True)
            face_file.unlink(missing_ok=True)
        app.write_state(job)
