"""Offline NVIDIA RTX Video Super Resolution for local 5070 jobs."""
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread

from banana_mv import core, masters


UPGRADE_RESOLUTION = 1440


def face_after_upscale(request):
    return bool(request.get('face_refine') and request.get('upscale_1080p')
                and request.get('upscale_resolution') == UPGRADE_RESOLUTION)


def executable():
    configured = os.environ.get('BANANA_NVENC')
    path = configured or shutil.which('NVEncC64.exe') or r'F:\AI\NVEncC\NVEncC64.exe'
    if not Path(path).is_file():
        raise ValueError('找不到 NVEncC64.exe。請解壓 NVEncC 至 F:\\AI\\NVEncC，或設定 BANANA_NVENC 為執行檔完整路徑。')
    return str(Path(path).resolve())


def video_size(path):
    video = next(stream for stream in core.probe(path)['streams'] if stream['codec_type'] == 'video')
    return video['width'], video['height']


def output_size(width, height, resolution=UPGRADE_RESOLUTION):
    long_side = resolution * 16 // 9
    box = (long_side, resolution) if width >= height else (resolution, long_side)
    scale = min(box[0] / width, box[1] / height)
    if scale <= 1:
        return None
    return tuple(max(2, round(side * scale / 2) * 2) for side in (width, height))


def encode(tool, source, target, size, cancelled):
    log = target.with_suffix('.log')
    with log.open('wb') as output:
        with subprocess.Popen([
            tool, '--avsw', '--codec', 'h264', '--qvbr', '18',
            '--vpp-resize', 'algo=ngx-vsr,vsr-quality=4',
            '--output-res', f'{size[0]}x{size[1]}',
            '-i', str(source), '-o', str(target),
        ], stdout=output, stderr=subprocess.STDOUT) as process:
            while process.poll() is None:
                if cancelled():
                    process.kill()
                    process.wait()
                    return False
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    continue
    if process.returncode:
        with log.open('rb') as stream:
            stream.seek(max(0, log.stat().st_size - 4000))
            lines = stream.read().decode(errors='replace').splitlines()
        errors = [line.strip() for line in lines if line.strip() and '%' not in line]
        raise RuntimeError('NVEncC 放大失敗：' + (' '.join(errors[-8:]) or f'exit {process.returncode}'))
    return True


def start_finished(app, job_id, version=None):
    """Queue VSR for an existing immutable master, without entering generation."""
    if not app.GPU_LOCK.acquire(blocking=False):
        raise ValueError('目前有任務在跑，完成後再回爐升級。')
    launched = False
    try:
        job = app.read_state(job_id)
        if job['status'] != 'done' and not (
                job['status'] == 'interrupted' and job.get('upscale_manual')):
            raise ValueError('請先完成影片，再回爐升級。')
        work = app.job_dir(job_id)
        masters.preserve_current(job, work)
        if version is None:
            version = job.get('current_master')
        if type(version) is not int:
            raise ValueError('找不到可升級的成片版本。')
        current = job.get('current_master')
        row = next((item for item in job['final_versions'] if item['version'] == version), None)
        if not row or (version != current and not (
                row['reason'] == 'face_refine' and row.get('source_master') == current)):
            raise ValueError('請重新開啟成片，再選擇目前母片或修臉版。')
        source = masters.source(job, work, version)
        if output_size(*video_size(source)) is None:
            raise ValueError('來源已達 2K（1440P）。')
        executable()
        cfg = app.backend.load_config()
        app.CANCEL.discard(job_id)
        job.pop('upscale_error', None)
        job.pop('error', None)
        job.update(status='upscaling_1080p', upscale_manual=True, upscale_resolution=UPGRADE_RESOLUTION)
        app.write_state(job)
        try:
            Thread(target=finished_worker, args=(app, cfg, job, row), daemon=True).start()
        except Exception as error:
            job.update(status='done', upscale_error=str(error))
            job.pop('upscale_manual', None)
            app.write_state(job)
            raise
        launched = True
        return {'id': job_id, 'status': 'upscaling_1080p'}
    finally:
        if not launched:
            app.GPU_LOCK.release()


def finished_worker(app, cfg, job, source_row):
    try:
        master = render(app, cfg, job, source_row=source_row, resolution=UPGRADE_RESOLUTION)
        refine_upscaled(app, cfg, job, master)
    except Exception as error:
        job['upscale_error'] = str(error)
    finally:
        job['status'] = 'done'
        job.pop('upscale_manual', None)
        app.CANCEL.discard(job['id'])
        try:
            app.write_state(job)
        finally:
            app.GPU_LOCK.release()


def render_version(app, cfg, job):
    if not job['request'].get('upscale_1080p') or job['id'] in app.CANCEL:
        return
    job.pop('upscale_error', None)
    try:
        master = render(app, cfg, job, resolution=job['request'].get('upscale_resolution', 1080))
        refine_upscaled(app, cfg, job, master)
    except Exception as error:
        job['upscale_error'] = str(error)


def refine_upscaled(app, cfg, job, master):
    if (not master or master['upscale_resolution'] != UPGRADE_RESOLUTION
            or not job['request'].get('face_refine') or job['id'] in app.CANCEL):
        return
    from banana_mv import face_refine
    try:
        face_refine.render_upscaled_version(app, cfg, job, master)
    except Exception as error:
        job['face_refine_error'] = str(error)


def render(app, cfg, job, *, source_row=None, resolution=UPGRADE_RESOLUTION):
    work = app.job_dir(job['id'])
    current = job['current_master']
    versions = job['final_versions']
    if source_row is None:
        source_row = next(row for row in versions if row['version'] == current)
        if resolution == 1080 and job['request'].get('face_refine'):
            source_row = next((row for row in reversed(versions)
                               if row['reason'] == 'face_refine' and row.get('source_master') == current), None)
            if source_row is None:
                raise ValueError(f'本次未產生修臉版，已略過 {resolution}P 放大。')

    source = masters.source(job, work, source_row['version'])
    size = output_size(*video_size(source), resolution)
    if size is None:
        raise ValueError(f'來源尺寸已達 {resolution}P 輸出範圍，已略過放大。')
    tool = executable()
    job.update(status='upscaling_1080p', upscale_resolution=resolution)
    app.write_state(job)
    try:
        app.backend.comfy(cfg, '/free', {'unload_models': True, 'free_memory': True})
    except Exception:
        # NVEncC can still run if ComfyUI cannot release its cached models.
        pass

    def cancelled():
        return job['id'] in app.CANCEL

    with TemporaryDirectory(prefix='nv_upscale_', dir=work) as temp:
        encoded = Path(temp) / 'video.mp4'
        pending = Path(temp) / 'final.mp4'
        if not encode(tool, source, encoded, size, cancelled) or cancelled():
            job['upscale_error'] = f'已停止 {resolution}P 放大。'
            return
        core.command(['ffmpeg', '-v', 'error', '-i', encoded, '-i', source,
                      '-map', '0:v:0', '-map', '1:a?', '-c', 'copy',
                      '-movflags', '+faststart', pending])
        if video_size(pending) != size:
            raise ValueError(f'{resolution}P 影片輸出尺寸驗證失敗。')
        if cancelled():
            job['upscale_error'] = f'已停止 {resolution}P 放大。'
            return
        choices = {int(index): take for index, take in source_row['takes'].items()}
        master = masters.archive(job, work, pending, f'upscale_{resolution}p', choices)
        master.update(source_master=current, source_version=source_row['version'], output_size=list(size),
                      upscale_resolution=resolution)

    try:
        master['output_video'] = str(app.export_finished_video(
            job, work / master['file'], upscaled_version=master['version'], upscaled_resolution=resolution))
    except OSError as error:
        master['export_error'] = f'{resolution}P 另存失敗：{error}'
    return master


def has_audio(path):
    return any(stream['codec_type'] == 'audio' for stream in core.probe(path)['streams'])


def clip_file(app, job, index, take_id):
    from banana_mv import takes
    return takes.take_file(job, index, take_id, '2k.mp4')


def clip_download_name(app, job, index, take_id):
    from banana_mv import takes
    title = ''.join(c for c in str(job.get('title') or 'Banana_MV')
                    if c not in '<>:"/\\|?*' and ord(c) >= 32).strip(' .')[:60] or 'Banana_MV'
    return f'{title}_{job["id"]}_第{index + 1:02d}段_V{takes.take_version(job, index, take_id)}_2K.mp4'


def clip_export_folder(app, job):
    if hasattr(app, 'finished_video_target'):
        return app.finished_video_target(job).parent
    return Path(os.environ.get('BANANA_FINISHED_VIDEOS') or app.backend.DATA / 'videos')


def start_clip(app, job_id, index, take_id):
    """Upscale one finished clip version to 2K on its own, for editing elsewhere."""
    from banana_mv import takes
    if not app.GPU_LOCK.acquire(blocking=False):
        raise ValueError('目前有任務在跑，完成後再升級這顆丹藥。')
    launched = False
    try:
        job = app.read_state(job_id)
        idle = takes.TERMINAL + (('kitchen_ready',) if job.get('kitchen') else ())
        if job['status'] not in idle:
            raise ValueError('請先等這爐完成或停爐，再升級單段 2K。')
        if not isinstance(take_id, str) or take_id == 'current':
            raise ValueError('請選擇明確的丹藥版本。')
        takes.segment(job, index)
        source = takes.take_source(job, index, take_id)
        executable()
        cfg = app.backend.load_config()
        app.CANCEL.discard(job_id)
        job['clip_upscale'] = {'index': index, 'take': take_id, 'status': 'running'}
        app.write_state(job)
        Thread(target=clip_worker, args=(app, cfg, job, index, take_id, source), daemon=True).start()
        launched = True
        return takes.describe(job)
    finally:
        if not launched:
            app.GPU_LOCK.release()


def clip_worker(app, cfg, job, index, take_id, source):
    from banana_mv import takes
    work = app.job_dir(job['id'])
    state = job['clip_upscale']

    def cancelled():
        return job['id'] in app.CANCEL

    try:
        tool = executable()
        try:
            app.backend.comfy(cfg, '/free', {'unload_models': True, 'free_memory': True})
        except Exception:
            pass
        with TemporaryDirectory(prefix='nv_clip_', dir=work) as temp:
            temp = Path(temp)
            width, height = video_size(source)
            prepared = source
            crop = job.get('output_size')
            # 跟母片一樣先切掉 32 對齊的補邊，再升頻。
            if crop and (crop[0], crop[1]) != (width, height) and crop[0] <= width and crop[1] <= height:
                prepared = temp / 'cropped.mp4'
                core.command(['ffmpeg', '-y', '-v', 'error', '-i', source, '-map', '0:v:0',
                              '-vf', f'crop={crop[0]}:{crop[1]}', '-c:v', 'libx264', '-crf', '14',
                              '-pix_fmt', 'yuv420p', prepared])
                width, height = crop
            size = output_size(width, height)
            if size is None:
                raise ValueError('這段已達 2K（1440P）。')
            encoded = temp / 'video.mp4'
            if not encode(tool, prepared, encoded, size, cancelled) or cancelled():
                raise InterruptedError('已停止單段 2K 升級。')
            pending = temp / 'clip.mp4'
            seg = takes.segment(job, index)
            song = job.get('sources', {}).get('song')
            if has_audio(source):
                # 短片的毛片自帶 H3 原生聲音，原樣保留。
                core.command(['ffmpeg', '-y', '-v', 'error', '-i', encoded, '-i', source,
                              '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy', '-movflags', '+faststart', pending])
            elif song:
                # MV 毛片沒有聲音：配上這段在原曲裡的同一段時間，拿去剪就對得上拍。
                core.command(['ffmpeg', '-y', '-v', 'error', '-i', encoded,
                              '-ss', f'{seg["start"]:.9f}', '-t', f'{seg["seconds"]:.9f}',
                              '-i', app.backend.safe_child(work, song),
                              '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
                              '-shortest', '-movflags', '+faststart', pending])
            else:
                shutil.copyfile(encoded, pending)
            if video_size(pending) != size:
                raise ValueError('2K 單段輸出尺寸驗證失敗。')
            target = clip_file(app, job, index, take_id)
            shutil.copyfile(pending, target)
        # 從沒回爐過的段還沒有版本表；先建好，才記得住這顆的 2K 檔。
        takes.archive_original(job, index)
        row = next(take for take in takes.segment(job, index)['takes'] if take['id'] == take_id)
        row['upscaled_2k'] = {'file': target.name, 'size': list(size)}
        try:
            folder = clip_export_folder(app, job)
            folder.mkdir(parents=True, exist_ok=True)
            exported = folder / clip_download_name(app, job, index, take_id)
            shutil.copyfile(target, exported)
            row['upscaled_2k']['output_video'] = str(exported)
        except OSError as error:
            row['upscaled_2k']['export_error'] = f'另存失敗：{error}'
        state.update(status='done')
    except Exception as error:
        state.update(status='error', error=str(error))
    finally:
        app.CANCEL.discard(job['id'])
        try:
            app.write_state(job)
        finally:
            app.GPU_LOCK.release()
