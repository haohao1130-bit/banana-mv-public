"""CPU audio measurements for the visual rewriter, not semantic music understanding.

No audio tokens are sent to Qwen. Source timestamps are converted to clip-local
times only when constructing a segment's evidence. Analysis never edits audio.
"""
import hashlib
import json
import math
import subprocess
from pathlib import Path

VERSION = 1
RATE = 16000
HOP = 400
STEP = HOP / RATE


def source_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def analyze_audio(path):
    """Decode at most the supported five minutes, with a sentinel for overlength."""
    import numpy as np
    result = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', str(path), '-t', '301', '-map', '0:a:0', '-vn',
         '-ac', '1', '-ar', str(RATE), '-f', 'f32le', 'pipe:1'],
        capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError('歌曲分析無法解碼：' + result.stderr.decode(errors='replace')[-1000:])
    samples = np.frombuffer(result.stdout, dtype='<f4')
    if not len(samples) or not np.isfinite(samples).all():
        raise ValueError('歌曲分析收到空白或無效音訊。')
    if len(samples) > RATE * 300 + RATE // 24:
        raise ValueError('歌曲分析最多支援五分鐘。')
    seconds = len(samples) / RATE
    count = math.ceil(len(samples) / HOP)
    padded = np.pad(samples, (0, count * HOP - len(samples)))
    rms = np.sqrt(np.mean(padded.reshape(-1, HOP).astype('float64') ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-6))
    # Positive spectral change: transient candidates, NOT guaranteed musical beats.
    fft_size = 1024
    padded = np.pad(samples, (0, fft_size))
    window = np.hanning(fft_size)
    flux = np.zeros(count)
    previous = np.zeros(fft_size // 2 + 1)
    for i in range(count):
        spectrum = np.abs(np.fft.rfft(padded[i*HOP:i*HOP+fft_size] * window))
        flux[i] = np.maximum(spectrum - previous, 0).sum() / max(spectrum.sum() + previous.sum(), 1e-8)
        previous = spectrum
    peak_db = float(np.max(db))
    gate = max(-60., peak_db - 35.)
    floor = max(.08, float(np.median(flux) + .5 * np.std(flux)))
    candidates = [i for i in range(1, count-1)
                  if flux[i] > floor and flux[i] >= flux[i-1] and flux[i] >= flux[i+1]
                  and np.max(db[i:min(count, i+3)]) > gate]
    selected = []
    for i in sorted(candidates, key=lambda k: -flux[k]):
        if all(abs(i-j)*STEP >= .18 for j in selected):
            selected.append(i)
    onsets = [{'time': round(min(seconds, i*STEP + fft_size/(2*RATE)), 3), 'strength': round(float(flux[i]), 3)}
              for i in sorted(selected)]
    quiet, start = [], None
    for i in range(count+1):
        is_quiet = i < count and db[i] <= gate
        if is_quiet and start is None:
            start = i
        elif not is_quiet and start is not None:
            end = min(i*STEP, seconds)
            if end-start*STEP >= .35:
                quiet.append([round(start*STEP, 3), round(end, 3)])
            start = None
    active = db[db > gate]
    reference = np.percentile(active, [20, 50, 80]).tolist() if len(active) else [-120.]*3
    # Only call this a pulse estimate when transients support a periodic grid.
    pulse = None
    if len(onsets) >= 8:
        grid = np.zeros(count)
        grid[selected] = 1
        best = (0., 0)
        for lag in range(round(60/200/STEP), round(60/60/STEP)+1):
            hits = sum((1. if delta == 0 else .5) * np.dot(grid[lag+delta:], grid[:count-lag-delta])
                       for delta in (-1, 0, 1))
            score = min(1., float(hits) / max(1., float(grid[:-lag].sum())))
            if score > best[0] + .01:
                best = score, lag
        if best[0] >= .55:
            pulse = {'bpm_estimate': round(60/(best[1]*STEP), 1),
                     'grid_match': round(best[0], 2), 'ambiguous_half_double_tempo': True}
    return {'version': VERSION, 'seconds': round(seconds, 4), 'step': STEP,
            'energy_dbfs': [round(float(v), 2) for v in db],
            'active_energy_percentiles': [round(v, 2) for v in reference],
            'quiet_intervals': quiet, 'onsets': onsets, 'pulse': pulse,
            'limitations': 'Acoustic measurements only; no lyrics, emotion, instruments or chorus recognition.'}


def load_analysis(source, cache):
    """Project-local cache follows the immutable source copy; never reuse stale data."""
    cache = Path(cache)
    digest = source_hash(source)
    if cache.is_file():
        try:
            saved = json.loads(cache.read_text(encoding='utf-8'))
            if saved.get('version') == VERSION and saved.get('source_sha256') == digest:
                return saved
        except (ValueError, OSError):
            pass
    result = analyze_audio(source)
    result['source_sha256'] = digest
    temp = cache.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    temp.replace(cache)
    return result


def segment_evidence(analysis, segment, vocal=None):
    """Bound evidence size; use only the source interval, excluding H3 padding."""
    import numpy as np
    start = segment['start']
    end = min(start + segment['seconds'], analysis['seconds'])
    step = analysis['step']
    energy = np.array(analysis['energy_dbfs'][int(start/step):math.ceil(end/step)])
    if not len(energy):
        # Older projects may have a one-frame tail beyond decoded audio EOF.
        # Keep it explicitly unmeasured, never reuse the first/last energy bin.
        if analysis['seconds'] <= start <= analysis['seconds']+.05 and segment['seconds'] <= .05:
            return {'source_interval':[round(analysis['seconds'],3)]*2,
                    'time_basis':'Clip-local seconds; this legacy tail is outside decoded audio.',
                    'relative_energy':'unmeasured','energy_change_db':0,
                    'transient_candidates_s':[],'quiet_intervals_s':[],
                    'pulse_estimate':None,'limits':'Legacy sub-frame/container padding; no measured music cues.'}
        raise ValueError('歌曲分析與分段時間不一致。')
    low, median, high = analysis['active_energy_percentiles']
    average = float(np.mean(energy))
    level = 'quiet' if np.max(energy) < -55 else 'steady' if high-low < 3 else 'high' if average >= high-2 else 'low' if average <= low else 'medium'
    third = max(1, len(energy)//3)
    change = float(np.mean(energy[-third:]) - np.mean(energy[:third]))
    strongest = sorted((p for p in analysis['onsets'] if start <= p['time'] < end),
                       key=lambda p: -p['strength'])[:8]
    peaks = sorted(round(p['time']-start, 2) for p in strongest)
    quiet = [[round(max(a, start)-start, 2), round(min(b, end)-start, 2)]
             for a,b in analysis['quiet_intervals'] if min(b,end)-max(a,start) >= .35]
    evidence = {'source_interval': [round(start, 3), round(end, 3)],
                'time_basis': 'All cue times below are local seconds from this clip start.',
                'relative_energy': level, 'energy_change_db': round(change, 1),
                'transient_candidates_s': peaks, 'quiet_intervals_s': quiet,
                'pulse_estimate': analysis['pulse'],
                'limits': analysis['limitations']}
    if vocal:
        # A user-provided aligned vocal stem is the only basis for this evidence.
        evidence['provided_vocal_stem_quiet_intervals_s'] = segment_evidence(vocal, segment)['quiet_intervals_s']
    return evidence


def audio_guidance(evidence):
    """A short actionable cue retained after rewriting and on the no-rewrite path."""
    peaks = evidence['transient_candidates_s']
    text = ('AUDIO-RESPONSIVE DIRECTION: Follow the supplied source audio. '
            f'This interval has {evidence["relative_energy"]} relative acoustic energy. ')
    change = evidence['energy_change_db']
    if change >= 3:
        text += 'Build visible movement toward the rising energy. '
    elif change <= -3:
        text += 'Let movement settle as acoustic energy falls. '
    if peaks:
        text += ('Possible accent times (clip-local seconds): ' + ', '.join(map(str, peaks)) +
                 '. Choose a few for a motivated action, visible consequence or camera reveal; do not cut on every accent. ')
    if evidence['quiet_intervals_s']:
        text += ('Quiet intervals (clip-local seconds): ' + json.dumps(evidence['quiet_intervals_s']) +
                 '; allow a pause or reaction where the actual audio supports it. ')
    if evidence.get('music_structure'):
        from banana_mv.music_structure import direction
        text += direction(evidence['music_structure']) + '\n'
    text += ('Keep the requested story and singer roles. Match visible singing to the actual audio, '
             'not to energy or transient estimates. Acoustic cues alone do not identify lyrics or choruses; separately supplied structure labels are predictions.')
    return text


def rewrite_evidence(evidence):
    return ('MEASURED AUDIO EVIDENCE (CPU analysis of the supplied recording; you do not receive audio tokens):\n'
            + json.dumps(evidence, ensure_ascii=False) + '\n'
            'Use these measurements to choose concrete visual actions and their timing within the user brief. '
            'Do not infer lyrics, instruments, mood or song sections from loudness. '
            'Return only the requested H3 prompt, without this analysis JSON.')
