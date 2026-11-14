"""One 9B delivery of timed shots, sliced deterministically for H3."""
import json
import math
import re
import uuid
from pathlib import Path

from banana_mv.core import FPS, map_image_mentions, normalize_mv_prompt
from banana_mv.director import INTENSITY, MODES, ORIGINAL_CUT_GUIDANCE
from banana_mv.direction_contract import H3_SECTIONS, validate_h3_sections
from banana_mv.lyrics_reference import clean_lyric_output, OUTPUT_POLICY
from banana_mv.mv_scope import ending_contract
from banana_mv.scene_state import SceneStateError, atomic_json, digest, parse_object
from banana_mv.shoot_plan import _pictures

VERSION = 7
SYSTEM = """You are directing the entire MV in one pass. Return only one JSON object.
Use this schema:
{"setup":"timeless appearance, visual style and named original picture bindings",
 "shots":[{"at":0,"mode":"story","picture_bindings":"local identity and current
 appearance using <Picture N> for referenced actors","visual":"final camera and
 action instructions for H3","continuation":"how this shot is sustained if bisected"}]}
All at values are absolute seconds from the start of the supplied song. Start at
zero, strictly increase, and keep every start before the actual song end. The next
shot's start ends the preceding shot. Write in the language of the user's brief.
One row is one filmable shot, not one processing interval. Never put timestamped
sub-shots inside a visual. Pick any supported mode per shot. The Python runner will
cut at the listed clip boundaries. Do not span more than one boundary per shot. Prefer completing causal beats before these
boundaries. For any shot that crosses one, write continuation for the part after
the boundary, with current pose, props and location, and only the remaining
movement. Do not replay an already completed action. Do not move a timing cue
to another interval. Avoid starting a new performance or story beat in a short
technical tail. No new plot belongs in setup or picture_bindings.

Expand a rough cue into a complete, causal story unless this is an excerpt.
For a supplied developed story, preserve its order, mandatory milestones, roles
and ending. Adapt framing, local reactions and motion under the stated policy.
Respect the supplied ending contract. Use musical peaks and predicted sections
as optional timing evidence, never as a source of plot or character roles.
Only explicitly assigned or story-appropriate vocalists visibly lip-sync, in their
assigned shots, timed to source audio. Lyrics and optional SRT are reference
material, never dialogue, subtitles or words to copy. With no SRT use the source
audio and coarse music evidence without claiming exact lyric times. Do not
invent heard sounds. Use original picture numbers in setup, bindings and shots.
An unused reference must not create a character. Never require a new picture.
Write concrete framing, blocking, action, reaction and outcome, ready to film.
No notes for a downstream writer, no commentary, no extra JSON fields required."""


def _validated(raw, req, count, duration):
    data = parse_object(raw)

    def visual(value, label, required=True):
        if not isinstance(value, str) or required and not value.strip():
            raise SceneStateError(f'全曲拍攝稿缺少有效的 {label}。')
        value, _ = clean_lyric_output(value, req)
        if not value.strip() and not required:
            return ''
        return normalize_mv_prompt(map_image_mentions(value, count), count)

    setup = visual(data.get('setup', ''), 'setup', required=False)
    shots = data.get('shots')
    if not isinstance(shots, list) or not shots:
        raise SceneStateError('全曲拍攝稿缺少 shots。')
    result = []
    previous = -1
    for index, row in enumerate(shots):
        at = row.get('at') if isinstance(row, dict) else None
        if type(at) not in (int, float) or not math.isfinite(at) or not 0 <= at < duration:
            raise SceneStateError(f'全曲第 {index + 1} 鏡起點超出歌曲時間。')
        frame = math.floor(at * FPS + 1e-7)
        if frame <= previous or index == 0 and at != 0:
            raise SceneStateError('全曲鏡頭須從 0 秒開始，且每鏡至少相隔一影格。')
        mode = row.get('mode')
        if not isinstance(mode, str) or mode not in MODES:
            raise SceneStateError(f'全曲第 {index + 1} 鏡的拍攝模式無效。')
        result.append({'frame': frame, 'mode': mode,
                       'bindings': visual(row.get('picture_bindings', ''), 'picture_bindings', False),
                       'visual': visual(row.get('visual'), 'visual'),
                       'continuation': visual(row.get('continuation', ''), 'continuation', False)})
        previous = frame
    return setup, result


def slice_shots(shots, segments):
    """Intersect authored shots with frame-exact source windows."""
    total_frames = segments[-1]['start_frame'] + segments[-1]['frames']
    ends = [shot['frame'] for shot in shots[1:]] + [total_frames]
    result = []
    for segment in segments:
        start = segment['start_frame']
        end = start + segment['frames']
        local = []
        for shot, stop in zip(shots, ends):
            if shot['frame'] >= end or stop <= start:
                continue
            continued = shot['frame'] < start
            if continued and not shot['continuation']:
                raise SceneStateError(f'跨越第 {segment["index"]+1} 段的鏡頭缺少 continuation。')
            local.append({
                'frame': max(shot['frame'], start) - start,
                'frames': min(stop, end) - max(shot['frame'], start),
                'mode': shot['mode'],
                'bindings': shot['bindings'],
                'visual': shot['continuation'] if continued else shot['visual'],
            })
        primary = max(local, key=lambda shot: shot['frames'])['mode']
        result.append({'index': segment['index'], 'mode': primary, 'shots': local,
                       'event': shot_text(local, include_bindings=True)})
    return result


def shot_text(shots, overlap=0, *, include_bindings=False):
    lines = []
    if overlap:
        lines.append('[Shot 1] Continue through the five supplied overlapping frames in order.')
    for index, shot in enumerate(shots, len(lines) + 1):
        time = round((shot['frame'] + overlap) / FPS * 1000)
        minutes, rest = divmod(time, 60000)
        seconds, milliseconds = divmod(rest, 1000)
        marker = f' At {minutes:02d}:{seconds:02d}.{milliseconds:03d},' if index > 1 else ''
        binding = f'{shot["bindings"]} ' if include_bindings and shot["bindings"] else ''
        lines.append(f'[Shot {index}]{marker} {binding}{shot["visual"]}')
    return '\n'.join(lines)


def h3_prompt(req, segment, picture_count, tail):
    row = segment['director_plan']
    overlap = segment.get('handoff_overlap_frames', 0) if tail else 0
    setup = segment.get('fixed_reference_settings', '')
    audio = '<Audio 1>: fully_copy. Preserve the supplied source track and its timing.'
    definitions = 'Apply the original-picture bindings and current appearance stated in each shot.'
    body = shot_text(row['shots'], overlap, include_bindings=True)
    values = [definitions, setup or 'Follow the assigned shots in order.',
              ('Preserve assigned reference facial identity. ' if req.get('face_identity', True) else '') + audio,
              body, audio + ' ' + OUTPUT_POLICY,
              'Use only the music in <Audio 1>.']
    prompt = '\n\n'.join(f'{key}:\n{value}' for key, value in zip(H3_SECTIONS, values))
    if tail:
        prompt = re.sub(r'<Picture (\d+)>', lambda m: f'<Picture {int(m[1])+1}>', prompt)
        prompt += '\n<Picture 1> is the supplied opening continuity frame.'
    validate_h3_sections(prompt)
    return normalize_mv_prompt(prompt, picture_count + int(bool(tail)))


def ensure_whole_song_plan(cfg, req, segments, originals, work, rewrite):
    count = len(originals)
    duration = segments[-1]['song_seconds']
    contract = ending_contract(req, duration, segments)
    task = {
        'brief': map_image_mentions(req.get('prompt', ''), count),
        'duration': duration,
        'style': req.get('director', 'auto'),
        'intensity': INTENSITY[req.get('intensity', 'high')],
        'adaptation': 'FREE' if req.get('story_plan', True) else 'FAITHFUL',
        'editing': ORIGINAL_CUT_GUIDANCE if req.get('dynamic_cuts', True) else 'Prefer motivated longer takes.',
        'ending': contract,
        'lyrics': req.get('lyrics', ''),
        'srt': [cue for cue in req.get('srt_cues', []) if cue['start'] < duration],
        'reference_count': count,
        'clip_windows': [{'start': seg['start'], 'end': min(duration, seg['start'] + seg['seconds']),
                          'music': seg.get('audio_evidence', {})} for seg in segments],
    }
    fingerprint = digest(task)
    path = Path(work) / 'director_plan.json'
    if path.is_file():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if (saved.get('version') != VERSION or saved.get('input_sha256') != fingerprint or
                saved.get('content_sha256') != digest({k: v for k, v in saved.items()
                                                       if k not in ('input_sha256', 'content_sha256')})):
            raise SceneStateError('保存的全曲拍攝稿與專案資料不一致。')
        return saved
    parts = [('text', json.dumps(task, ensure_ascii=False))] + _pictures(originals)
    raw = rewrite(cfg, SYSTEM + '\nSupported modes: ' + ', '.join(MODES), parts, uuid.uuid4().hex[:8])
    (Path(work) / 'whole_song_director_raw.txt').write_text(str(raw), encoding='utf-8')
    try:
        setup, shots = _validated(raw, req, count, duration)
        rows = slice_shots(shots, segments)
        for row in rows:
            h3_prompt(req, {'director_plan': row, 'fixed_reference_settings': setup}, count, None)
    except ValueError as error:
        raise SceneStateError('9B 全曲拍攝稿交稿失敗：' + str(error)) from error
    plan = {'version': VERSION, 'shared_setup': setup, 'shots': shots,
            'segments': rows, 'ending_contract': contract}
    plan['content_sha256'] = digest(plan)
    plan['input_sha256'] = fingerprint
    atomic_json(path, plan)
    return plan
