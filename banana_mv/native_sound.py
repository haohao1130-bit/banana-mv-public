"""Opt-in, per-clip H3 sound and a separate full-length postproduction track."""
import json
import re
import uuid
from urllib.parse import urlencode

from banana_mv.core import FPS, command

CUE = re.compile(r'^\s*【原生聲音\s*第\s*(\d+)\s*段】\s*(.*)$')

def split_cues(script, segment_count):
    lines, cues = [], {}
    for line in script.splitlines(keepends=True):
        if not line.lstrip().startswith('【原生聲音'):
            lines.append(line)
            continue
        match = CUE.fullmatch(line.rstrip('\r\n'))
        if not match or not match[2].strip():
            raise ValueError('原生聲音請用一行「【原生聲音 第3段】音效與指定台詞」。')
        number = int(match[1])
        if not 1 <= number <= segment_count or str(number) in cues:
            raise ValueError(f'原生聲音第 {number} 段超出範圍或重複。')
        cues[str(number)] = match[2].strip()
    if not cues:
        raise ValueError('請在劇本加入「【原生聲音 第3段】」及要生成的聲音。')
    return ''.join(lines), cues


def prompt_for_sound(prompt, cue):
    prompt = re.sub(r'(?im)^\s*<Audio\s+1>\s*:.*$', '', prompt)
    prompt = re.sub(r'(?is)<d>.*?</d>', '', prompt)
    prompt = re.sub(r'<Audio\s+1>', 'the music added later', prompt, flags=re.I)
    for section in ('overall_soundscape', 'non_diegetic_music'):
        prompt = re.sub(rf'(?ims)^{section}:.*?(?=^\w+:|\Z)', '', prompt)
    return (prompt.rstrip() + '\n\noverall_soundscape:\n'
            'Generate only the following diegetic sound cue, timed to the visible action. '
            'Spoken words are permitted only where explicitly quoted and assigned to a speaker '
            'in this cue. Use those exact words. Treat all other text as visual direction. '
            'Otherwise the characters remain silent. '
            'No extra voices, babble, ad-libs, singing, or humming.\n'
            + cue +
            '\n\nnon_diegetic_music:\nNone. Do not generate any music or soundtrack.')


def track_path(work, version):
    return work / f'native_sound_v{version:03d}.mp3'


def export_track(app, job, master):
    from banana_mv import takes

    cues = job['request'].get('native_sound_cues')
    if not cues:
        return
    work = app.job_dir(job['id'])
    target = track_path(work, master['version'])
    pending = target.with_name(f'.native_sound_{uuid.uuid4().hex}.mp3')
    inputs, filters, clips = [], [], []
    try:
        for index, seg in enumerate(job['segments']):
            seconds = seg['frames'] / FPS
            if str(index + 1) in cues:
                take_id = master['takes'][str(index)]
                workflow = takes.existing_file(job, index, take_id, 'workflow.json')
                graph = json.loads(workflow.read_text(encoding='utf-8'))
                if 'native_audio_decode' not in graph:
                    raise ValueError(f'第 {index + 1} 段所選版本沒有原生聲音。')
                raw = takes.existing_file(job, index, take_id, 'raw.mp4')
                skip = 5 / FPS if 'guide_last5' in graph else 0
                source = (f'[{len(inputs) // 2}:a:0]atrim=start={skip:.9f},'
                          'asetpts=PTS-STARTPTS,apad,')
                inputs.extend(('-i', raw))
            else:
                source = 'anullsrc=r=48000:cl=stereo,'
            label = f'[clip{index}]'
            filters.append(f'{source}atrim=duration={seconds:.9f},'
                           f'aformat=sample_rates=48000:channel_layouts=stereo{label}')
            clips.append(label)
        filters.append(''.join(clips) + f'concat=n={len(clips)}:v=0:a=1[sound]')
        command(['ffmpeg', '-y', '-v', 'error', *inputs, '-filter_complex', ';'.join(filters),
                 '-map', '[sound]', '-t', f'{job["duration"]:.9f}', '-c:a', 'libmp3lame',
                 '-q:a', '2', pending])
        pending.replace(target)
        master['native_sound_track'] = True
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        master['native_sound_error'] = f'原生聲音 MP3 未匯出：{error}'
    finally:
        pending.unlink(missing_ok=True)


def download_url(job):
    if job.get('final_stale'):
        return None
    master = next((row for row in job.get('final_versions', [])
                   if row['version'] == job.get('current_master')), {})
    if master.get('native_sound_track'):
        return '/api/mv/native-sound?' + urlencode({'id': job['id'], 'version': master['version']})
    return None
