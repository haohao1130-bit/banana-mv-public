"""Predicted musical structure; isolated from H3 and never inferred from volume."""
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

from banana_mv.audio_analysis import source_hash

VERSION = 1
REVISION = '566f96c3f007c783ab5eb6db0123bf3335af8f31'
MODEL = 'harmonix-all'
LABELS = {'start', 'end', 'intro', 'outro', 'break', 'bridge', 'inst', 'solo', 'verse', 'chorus'}
ROOT = Path(__file__).resolve().parents[1]


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('音樂結構包含無效數值。')
    return float(value)


def validate_result(raw, seconds):
    """Reject incompatible/truncated output, preserve predictions as predictions."""
    duration = number(seconds)
    bpm = number(raw['bpm'])
    if not 0 <= bpm <= 400:
        raise ValueError('音樂結構 BPM 超出範圍。')
    result = {'bpm': bpm}
    for key in ('beats', 'downbeats'):
        values = [number(t) for t in raw[key]]
        if len(values) > 10000 or any(t < 0 or t > duration + .1 for t in values) or any(b <= a for a,b in zip(values, values[1:])):
            raise ValueError('音樂結構節拍時間無效。')
        result[key] = [round(min(t, duration), 3) for t in values if t < duration]
    segments = []
    for item in raw['segments']:
        a, b = number(item['start']), number(item['end'])
        label = item['label']
        if label not in LABELS or not 0 <= a < b <= duration + .15:
            raise ValueError('音樂段落標籤或時間無效。')
        if segments and abs(a-segments[-1]['end']) > .15:
            raise ValueError('音樂段落有重疊或缺口。')
        segments.append({'start':round(a,3), 'end':round(min(b,duration),3), 'label':label})
    if not segments or len(segments)>500 or segments[0]['start'] > .15 or abs(segments[-1]['end']-duration) > .5:
        raise ValueError('音樂段落未涵蓋完整歌曲。')
    result['segments'] = segments
    return result


def load_structure(source, cache, seconds):
    source, cache = Path(source), Path(cache)
    identity = {'version':VERSION, 'source_sha256':source_hash(source), 'revision':REVISION, 'model':MODEL}
    if cache.is_file():
        try:
            saved = json.loads(cache.read_text(encoding='utf-8'))
            if all(saved.get(k)==v for k,v in identity.items()):
                return dict(identity, **validate_result(saved, seconds))
        except (ValueError, KeyError, TypeError, OSError):
            pass
    python = Path(os.environ.get('BANANA_MUSIC_PYTHON', ROOT/'.music-venv/bin/python'))
    if not python.is_file():
        raise RuntimeError('音樂結構分析器尚未安裝，請重新執行 Colab 安裝格；或關閉「音樂結構分析」做對照。')
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='music-', dir=cache.parent) as temp:
        work = Path(temp)
        decoded = work/'source.wav'
        decode = subprocess.run(['ffmpeg','-v','error','-i',str(source),'-t','301','-map','0:a:0','-vn',
                                 '-ar','44100','-ac','2',str(decoded)], capture_output=True, timeout=120)
        if decode.returncode:
            raise RuntimeError('音樂結構分析無法解碼：'+decode.stderr.decode(errors='replace')[-1000:])
        output = work/'result.json'
        log = cache.with_suffix('.log')
        # CPU by design: no second GPU model remains resident beside ComfyUI/9B.
        with log.open('w', encoding='utf-8') as stream:
            try:
                done = subprocess.run([str(python),'-m','banana_mv.music_structure',str(decoded),str(output),str(work)],
                                      cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=1200,
                                      env=dict(os.environ, CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='4',MKL_NUM_THREADS='4'))
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError('音樂結構分析超過 20 分鐘，已停止；請查看 music_structure.log。') from exc
        if done.returncode or not output.is_file():
            raise RuntimeError('音樂結構分析失敗，請查看 music_structure.log；尚未進入 9B 規劃或影片生成。')
        result = dict(identity, **validate_result(json.loads(output.read_text()), seconds))
        atomic = cache.with_suffix('.tmp')
        atomic.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        atomic.replace(cache)
        return result


def local_structure(result, segment):
    start, end = segment['start'], segment['start']+segment['seconds']
    sections = [{'start_s':round(max(s['start'],start)-start,3),
                 'end_s':round(min(s['end'],end)-start,3),'predicted_label':s['label'],
                 'begins_here':start <= s['start'] < end}
                for s in result['segments'] if min(s['end'],end)>max(s['start'],start)]
    return {'source':'all-in-one-infer', 'prediction':True, 'bpm':result['bpm'],
            'sections':sections,
            'beats_s':[round(t-start,3) for t in result['beats'] if start<=t<end],
            'downbeats_s':[round(t-start,3) for t in result['downbeats'] if start<=t<end],
            'limits':'Predictions can be wrong. Chorus/solo labels do not prove a climax, instrument or singing. No lyric transcription. Times are clip-local; never move song boundaries.'}


def direction(structure):
    sections = '; '.join(f"{s['start_s']}–{s['end_s']}s {s['predicted_label']}" for s in structure['sections'])
    downbeats = ', '.join(map(str,structure['downbeats_s'])) or 'none detected'
    return (f"PREDICTED MUSIC STRUCTURE (clip-local seconds): {sections}. "
            f"Predicted downbeats: {downbeats}. "
            'Use section changes and selected downbeats to time concrete action payoffs, performance highlights or reveals. '
            'Build contrast and anticipation before a payoff; do not cut on every beat or repeat the finale in every chorus. '
            'Treat labels as fallible guidance, respect actual singing and the requested story. A solo label does not identify its instrument.')


def run_model(source, output, work):
    from dataclasses import asdict
    import torch
    import allin1_infer
    torch.set_num_threads(4)
    result = allin1_infer.analyze(source, model=MODEL, device='cpu', multiprocess=False,
                                demix_dir=Path(work)/'demix',spec_dir=Path(work)/'spec',overwrite=True)
    raw = asdict(result)
    Path(output).write_text(json.dumps({k:raw[k] for k in ('bpm','beats','downbeats','segments')},allow_nan=False))


if __name__ == '__main__':
    import sys
    run_model(*sys.argv[1:])
