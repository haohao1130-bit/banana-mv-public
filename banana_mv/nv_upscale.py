"""Offline NVIDIA RTX Video Super Resolution for local 5070 jobs."""
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from banana_mv import core, masters


def executable():
    configured = os.environ.get('BANANA_NVENC')
    path = configured or shutil.which('NVEncC64.exe') or r'F:\AI\NVEncC\NVEncC64.exe'
    if not Path(path).is_file():
        raise ValueError('找不到 NVEncC64.exe。請解壓 NVEncC 至 F:\\AI\\NVEncC，或設定 BANANA_NVENC 為執行檔完整路徑。')
    return str(Path(path).resolve())


def video_size(path):
    video = next(stream for stream in core.probe(path)['streams'] if stream['codec_type'] == 'video')
    return video['width'], video['height']


def output_size(width, height):
    box = (1920, 1080) if width >= height else (1080, 1920)
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


def render_version(app, cfg, job):
    if not job['request'].get('upscale_1080p') or job['id'] in app.CANCEL:
        return
    job.pop('upscale_error', None)
    try:
        render(app, cfg, job)
    except Exception as error:
        job['upscale_error'] = str(error)


def render(app, cfg, job):
    work = app.job_dir(job['id'])
    current = job['current_master']
    versions = job['final_versions']
    source_row = next(row for row in versions if row['version'] == current)
    if job['request'].get('face_refine'):
        source_row = next((row for row in reversed(versions)
                           if row['reason'] == 'face_refine' and row.get('source_master') == current), None)
        if source_row is None:
            raise ValueError('本次未產生修臉版，已略過 1080P 放大。')

    source = masters.source(job, work, source_row['version'])
    size = output_size(*video_size(source))
    if size is None:
        raise ValueError('來源尺寸已達 1080P 輸出範圍，已略過放大。')
    tool = executable()
    job['status'] = 'upscaling_1080p'
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
            job['upscale_error'] = '已停止 1080P 放大。'
            return
        core.command(['ffmpeg', '-v', 'error', '-i', encoded, '-i', source,
                      '-map', '0:v:0', '-map', '1:a?', '-c', 'copy',
                      '-movflags', '+faststart', pending])
        if video_size(pending) != size:
            raise ValueError('1080P 影片輸出尺寸驗證失敗。')
        if cancelled():
            job['upscale_error'] = '已停止 1080P 放大。'
            return
        choices = {int(index): take for index, take in source_row['takes'].items()}
        master = masters.archive(job, work, pending, 'upscale_1080p', choices)
        master.update(source_master=current, source_version=source_row['version'], output_size=list(size))

    try:
        master['output_video'] = str(app.export_finished_video(
            job, work / master['file'], upscaled_version=master['version']))
    except OSError as error:
        master['export_error'] = f'1080P 另存失敗：{error}'
