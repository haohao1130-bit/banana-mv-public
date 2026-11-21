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
    return ''.join(lines), cues


def prompt_for_sound(prompt, cue=None, *, authored_event=None):
    prompt = re.sub(r'(?im)^[ \t]*<Audio\s+1>\s*:.*$', '', prompt)
    prompt = re.sub(r'(?im)^Use the original song from <Audio 1> unchanged .*?The following clip-local intervals are authoritative\. No spoken rendition, repeated line, new vocals or subtitles\.',
                    'Follow the clip-local visual lip movements at these timestamps.', prompt)
    prompt = re.sub(r'<\s*Audio\s+1\s*>', 'the song added in postproduction', prompt, flags=re.I)
    for section in ('overall_soundscape', 'non_diegetic_music'):
        prompt = re.sub(rf'(?ims)^{section}:.*?(?=^\w+:|^\[BANANA_|\Z)', '', prompt)
    if cue or authored_event:
        # Dialogue from the original scene takes priority over rewriter dialogue.
        prompt = re.sub(r'(?is)<d\b[^>]*>.*?</d\s*>', '', prompt)
    if authored_event:
        authored_event = re.sub(
            r'(?im)^[ \t]*(?:ALREADY ESTABLISHED\b|Previously established:|Source chapter:|PYTHON-OWNED CURRENT EVENT\b).*$', '',
            authored_event,
        ).strip()
        authored_event = re.sub(r'<\s*Audio\s+1\s*>', 'the song added in postproduction',
                                authored_event, flags=re.I)
    soundscape = (
        'Generate the original on-screen sound of this clip. Match sound effects to their visible '
        'actions and timing. Keep quiet moments quiet. Only speak exact words explicitly assigned '
        'to a speaker in the current authored scene. Use the original language. '
        'Treat lyric, SRT, vocalist and lip-sync instructions as visual timing only. '
        'No invented speech, babble, narration, background voices, singing, humming, '
        'background music or musical performances, even when instruments are visible. '
        'Never repeat audio from a prior scene or read the directions aloud.'
    )
    if cue:
        soundscape += '\nOnly use this sound cue:\n' + cue
    else:
        soundscape += ('\n<Audio 1> is a reference for the timing of visual lip movements only. '
                       'The generated soundtrack contains only the scene sounds and scripted dialogue.')
        if authored_event:
            soundscape += ('\nUse this original scene for audio intent. Follow the shot directions above for timing:\n'
                           + authored_event)
    return (prompt.rstrip() + '\n\noverall_soundscape:\n' + soundscape
            + '\n\nnon_diegetic_music:\nNone. Do not generate music.')


def track_path(work, version):
    return work / f'native_sound_v{version:03d}.mp3'


def export_track(app, job, master):
    from banana_mv import takes

    cues = job['request'].get('native_sound_cues')
    if not cues and not job['request'].get('native_sound'):
        return
    work = app.job_dir(job['id'])
    target = track_path(work, master['version'])
    pending = target.with_name(f'.native_sound_{uuid.uuid4().hex}.mp3')
    inputs, filters, clips = [], [], []
    try:
        for index, seg in enumerate(job['segments']):
            seconds = seg['frames'] / FPS
            source = 'anullsrc=r=48000:cl=stereo,'
            if not cues or str(index + 1) in cues:
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
