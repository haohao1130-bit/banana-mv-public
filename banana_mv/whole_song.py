"""Whole-song planning and frame-exact shot assembly for H3."""
import json
import math
import re
import uuid
from pathlib import Path

from banana_mv.commission_guard import role_pictures
from banana_mv.core import FPS, map_image_mentions, normalize_mv_prompt
from banana_mv.director import INTENSITY, MODES, ORIGINAL_CUT_GUIDANCE
from banana_mv.direction_contract import H3_SECTIONS, validate_h3_sections
from banana_mv.lyrics_reference import clean_lyric_output, excerpt, vocal_timeline, OUTPUT_POLICY
from banana_mv.mv_scope import clip_ending, ending_contract
from banana_mv.scene_state import SceneStateError, atomic_json, digest, parse_object
from banana_mv.shoot_plan import _apply_source_performance, _pictures
from banana_mv.timed_slots import TIME_SPAN, parse_timed_source

VERSION = 7
DIRECT_SCRIPT = 8
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
sub-shots inside a visual. Pick any supported mode per shot. Direct the song as
one continuous timeline. Choose shot starts by story and music. For shots with
ongoing action, include an optional continuation with the pose, props, location
and movement after the action has begun. Do not replay an already completed
action or move a timing cue. No new plot belongs in setup or picture_bindings.

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


BATCH_SIZE = 3
# Screenwriter rules adapted from the front-end "copy to AI" brief for the 35B
# outline pass. Python owns the timeline; the outline never writes shots.
OUTLINE_SYSTEM = """你是 BANANAMV 的編劇。你只寫「共同設定」與「逐段事件」，不寫鏡頭、切點、運鏡或英文提示詞；那是下一階段導演的工作。

輸入：Python 已提供歌曲總長、固定的 clip_windows（段落已切好）、參考圖編號、author_setup、音樂段落與能量、SRT（若有）。不要更動段落時間，也不要回頭提問。

回傳一個 JSON 物件：
{"setup":"共同設定中缺少的穩定事實或角色綁定",
 "beats":[{"index":<段號>,
   "scene":"地點、天氣、光線、看得到的物件（新地點第一次出現才寫）",
   "cast":"本段看得到的角色",
   "event":"誰做了什麼具體動作 → 對方怎麼反應 → 造成什麼結果與情緒",
   "end_state":"段尾的站位、朝向、道具，以及服裝或身上的狀態（濕、髒、破損、受傷）",
   "activity":"本段主要活動，限支援清單",
   "style":"幾個動作或曲風關鍵字，沒有就留空"}]}

共同設定：只寫整首不變的事實——角色外貌與原始服裝（依原圖，不加配件）、體型比例、非人類角色的身體結構與移動方式、多條故事線時各角色所屬場景。author_setup 具權威，不要重複它。使用原始參考圖編號。不寫大綱、未來劇情、結局或導演意圖。

逐段事件：
- 每個 clip_window 都要填，依序，不跳號。
- 一段 1～3 件事，要具體：「A 把信摔在桌上，B 停下腳步回頭，兩人僵在原地」，不要「氣氛緊張」；「A 轉身甩開外套，B 接住後跟上同一組舞步」，不要「熱舞」。
- 每個關鍵動作（出手、碰撞、轉身、落地、交換位置）只發生一次，不重演；已發生的事不在下一段重寫。
- 動作可在段尾沒做完（手伸到一半、舞步轉到一半），下一段同方向接著做完，不倒退重來。
- 多人在場時每個人都有反應和視線，不罰站。
- 還沒登場的角色不能出現。非最後一段不謝幕、不淡出；最後一段照使用者指定收尾。
- 使用者寫好的事件、角色、先後順序與結局要保留；粗 CUE 則發展成完整的因果，重複出現的母題在相關段落回收。
- 粗 CUE 裡的剪接點子（例如不完整切鏡、硬切到另一條線、動作呼應、朝鏡頭逼近）保留在落點那一段的事件裡；重複的招式只放在故事的關鍵時刻，一次比一次強。
- 依曲風與能量決定事件密度：快歌、副歌、打鬥或舞蹈段落動作密；抒情或安靜段落事件少而深。
- 用音樂段落和 SRT 對齊事件；不抄歌詞，不編 SRT，沒有 SRT 的區間不判定為間奏或靜音。
- 有 SRT 才知道誰在唱；沒標聲部就不指定，不叫角色停下來站著唱。
- 不用空泛詞：epic、cinematic、壯觀、震撼、充滿能量。
- 欄位內容用使用者劇本的語言。

參考索引：BANANAMV 有一份實拍驗證過的範例索引，列在 REFERENCE INDEX。不要盲猜拍法：段落的活動或曲風符合某一列時，把該列的關鍵字寫進 style（例如詠春對打寫「wing chun push hands」），Python 會在導演階段調出那份範例。沒有相符的就留空，導演會依通則寫。"""

SLOT_SYSTEM = """Write shots only for the supplied clip_windows. Return one JSON object:
{"clips":[{"index":<slot index>,"handoff":"concise visible state at the cut out",
 "shots":[{"at":0,"mode":"story",
 "picture_bindings":"identity or current appearance unique to this shot",
 "visual":"finished English H3 camera prose"}]}]}
Follow the whole-song outline and this batch's source notes. Shared setup applies
throughout. Use original picture numbers. Fill only the requested one-based
slots in order, with a shot at 0 in each. at is clip-local and must increase
strictly below each window's duration; place no new shot at the endpoint.
Python computes shot ends, overlap, media numbering and H3 fields.
Continue ongoing action from incoming_handoff. For each slot, handoff captures
final positions, current appearance, props and ongoing motion for the next slot
in one or two sentences. All structured time values in each window are seconds
from its own start. Start the clock at 0 for every slot, regardless of its index.
Treat music cues as action or editing options; a beat does not require a cut.
A window's planned keys are the outline's scene, cast, activity, style and end
state. Follow them unless the window's source notes say otherwise.
Assign mode by actual on-screen activity. Honor authored events, roles,
chronology and ending. Develop recurring visual motifs.
Write finished English H3 camera prose with usable framing, camera motion,
blocking, physical action and reaction. Give each viewpoint a new detail to
reveal. Vary shot count by action, preserving deliberate long takes.
Use measured or predicted music features as clues. Honor explicit SRT times and
roles. Do not copy lyrics, recite them, or add subtitles. Untagged time does not
imply silence. Do not invent heard sounds or new picture references.
Deliver only this batch. Reserve the ending for its assigned slot."""

# Distilled from validated BANANAMV renders (Dangerous Contract, Little Boxing
# King, Max Power, Banana Sect Abbot). Craft guidance, not an acceptance gate.
SHOT_CRAFT = """SHOT CRAFT for each visual:
- Open with the framing and camera position: shot size, height or angle, and a
  lens when it matters (e.g. low 24mm, long-lens frontal, over-the-shoulder).
- Give the camera a path, speed and destination: tracks backward along the
  exchange line, trucks hard right with the escape, whips along a punch, pushes
  in fast, arcs to a low angle. Moves are motivated by the action they reveal.
- Write action as cause and effect: preparation, contact or accent, reaction or
  recoil, and the resulting position. Name the supporting foot, the hand used,
  the weight transfer and the direction of travel.
- Let material respond: fabric, hair, beads, sweat, dust or leaves.
- Direct performance: gaze, micro-expression, who sings and who stays silent.
- Cut on an unfinished action and name the trigger ("cut as the fist begins its
  wind-up"); the next shot continues it from a contrasting angle.
- Energetic passages: several short shots per window that alternate wide
  geography, inserts (feet, contact, faces) and close-ups. Quiet passages: fewer,
  longer shots.
- Keep the song's established movement vocabulary; vary angle, scale and
  formation instead of switching dance or fighting styles every shot. Avoid
  floor rolls, flips, lifts and spins unless the commission assigns them."""

_MAX_EXAMPLES = 2


def _slot_system(req, windows, setup):
    """Shot-writing system with craft guidance and up to two validated examples."""
    from banana_mv.director_examples import example_prompt, select_example
    fallback = req.get('director', 'auto')
    chosen, examples = set(), []
    for window in windows:
        planned = window.get('planned') or {}
        mode = planned.get('activity') or (fallback if fallback in MODES else None)
        if not mode:
            continue
        style = ' '.join(filter(None, (planned.get('style', ''), setup)))
        item = select_example(mode, style)
        if not item or item['source'] in chosen or len(examples) >= _MAX_EXAMPLES:
            continue
        chosen.add(item['source'])
        examples.append(example_prompt(mode, style))
    if examples:
        examples.insert(0, 'The reference examples below were retrieved from the validated BANANAMV index '
                           "for these windows' planned style. Use them for the level of detail instead "
                           'of guessing, but design your own shots for the current events.')
    return '\n\n'.join([SLOT_SYSTEM + '\nSupported modes: ' + ', '.join(MODES), SHOT_CRAFT, *examples])


def _visual(value, label, req, count, required=True):
    if not isinstance(value, str) or required and not value.strip():
        raise SceneStateError(f'全曲拍攝稿缺少有效的 {label}。')
    value, _ = clean_lyric_output(value, req)
    if not value.strip() and not required:
        return ''
    return normalize_mv_prompt(map_image_mentions(value, count), count)


def _shot_rows(shots, req, count, duration, label):
    if not isinstance(shots, list) or not shots:
        raise SceneStateError(f'{label}拍攝稿缺少 shots。')
    result = []
    previous = -1
    for index, row in enumerate(shots):
        at = row.get('at') if isinstance(row, dict) else None
        if type(at) not in (int, float) or not math.isfinite(at) or not 0 <= at < duration:
            raise SceneStateError(f'{label}第 {index + 1} 鏡起點無效（{at!r}；範圍為 0 至 {duration:g} 秒，終點不含）。')
        frame = math.floor(at * FPS + 1e-7)
        if frame <= previous or index == 0 and at != 0:
            raise SceneStateError(f'{label}鏡頭須從 0 秒開始，且每鏡至少相隔一影格。')
        mode = row.get('mode')
        if not isinstance(mode, str) or mode not in MODES:
            raise SceneStateError(f'{label}第 {index + 1} 鏡的拍攝模式無效。')
        result.append({'frame': frame, 'mode': mode,
                       'bindings': _visual(row.get('picture_bindings', ''), 'picture_bindings', req, count, False),
                       'visual': _visual(row.get('visual'), 'visual', req, count),
                       'continuation': _visual(row.get('continuation', ''), 'continuation', req, count, False)})
        previous = frame
    return result


def _validated(raw, req, count, duration):
    data = parse_object(raw)
    setup = _visual(data.get('setup', ''), 'setup', req, count, False)
    return setup, _shot_rows(data.get('shots'), req, count, duration, '全曲')


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
            visual = shot['visual']
            if continued:
                visual = shot['continuation'] or (
                    'Continue this shot already in progress. Maintain the current scene, pose '
                    'and props, and show only the remaining action. Shot context: ' + visual)
            local.append({
                'frame': max(shot['frame'], start) - start,
                'frames': min(stop, end) - max(shot['frame'], start),
                'mode': shot['mode'],
                'bindings': shot['bindings'],
                'visual': visual,
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


def direct_script_prompt(req, segment, picture_count, tail):
    """Package just this authored interval for H3 without invoking 9B."""
    setup = segment.get('fixed_reference_settings', '')
    event = segment['director_plan']['event']
    audio = '<Audio 1>: fully_copy. Preserve the supplied source track and its timing.'
    values = [
        'Use the original reference images according to the author’s bindings.',
        setup or 'Follow the author’s instructions for this interval.',
        audio,
        '[Shot 1] ' + (
            '以下秒數皆以本段第一幀為 0 秒。每個時間碼是目前鏡頭裡的動作提示。'
            '依原稿維持攝影機的連續位置與運動。\n\n'
            if segment['director_plan'].get('authored_cues') and not req.get('dynamic_cuts', True) else ''
        ) + event,
        audio,
        'Use the supplied soundtrack.',
    ]
    prompt = '\n\n'.join(f'{key}:\n{value}' for key, value in zip(H3_SECTIONS, values))
    if tail:
        prompt = re.sub(r'<Picture (\d+)>', lambda m: f'<Picture {int(m[1])+1}>', prompt)
        opening = '<Picture 1> 是上一段交接的起始畫面。'
        if segment['director_plan'].get('authored_cues'):
            opening += ('從畫面中的位置與朝向延續。角色、載具與攝影機各自維持原有行進方向和動勢，'
                        '到原稿指定的時間才轉向或變速。攝影機的朝向及移動與載具獨立，'
                        '攝影機倒飛時，載具仍照原稿沿自己的路線行駛。')
        prompt = prompt.replace('detailed_description:\n[Shot 1] ',
                                'detailed_description:\n[Shot 1] ' + opening + '\n\n', 1)
    validate_h3_sections(prompt)
    return normalize_mv_prompt(prompt, picture_count + int(bool(tail)))


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
    if req.get('whole_song_director'):
        vocals = vocal_timeline(excerpt(req, segment))
        if vocals:
            for cue in vocals:
                cue['clip_start'] += overlap / FPS
                cue['clip_end'] += overlap / FPS
            prompt = _apply_source_performance(prompt, vocals, setup)
    if tail:
        prompt = re.sub(r'<Picture (\d+)>', lambda m: f'<Picture {int(m[1])+1}>', prompt)
        if req.get('whole_song_director'):
            prompt = prompt.replace('subject_definitions:\n', 'subject_definitions:\n'
                                    '<Picture 1> is the supplied opening continuity frame.\n', 1)
        else:
            prompt += '\n<Picture 1> is the supplied opening continuity frame.'
    validate_h3_sections(prompt)
    return normalize_mv_prompt(prompt, picture_count + int(bool(tail)))


def _repair_batch_json(raw):
    """Repair known wrapper mistakes at parser-confirmed clip boundaries."""
    source = re.sub(r'^\x60\x60\x60(?:json)?\s*|\s*\x60\x60\x60$', '', raw.strip(), flags=re.I)
    repairs = 0
    while True:
        try:
            parsed = json.loads(source)
        except json.JSONDecodeError as error:
            pos = error.pos
            if error.msg == 'Extra data' and re.fullmatch(r'\]\s*\}', source[pos:]):
                prefix = parse_object(source[:pos])
                if set(prefix) == {'clips', 'index', 'handoff', 'shots'}:
                    clips = prefix.pop('clips')
                    if (isinstance(clips, list) and 0 < len(clips) < BATCH_SIZE
                            and isinstance(clips[-1], dict)
                            and type(clips[-1].get('index')) is int
                            and type(prefix['index']) is int
                            and prefix['index'] == clips[-1]['index'] + 1):
                        return {'clips': [*clips, prefix]}
                return None
            if (repairs >= BATCH_SIZE - 1 or error.msg != "Expecting ',' delimiter"
                    or not re.search(r'\]\s*\}\s*$', source[:pos])
                    or not re.match(r'\}\s*,\s*\{\s*"index"\s*:', source[pos:])):
                return None
            source = source[:pos] + source[pos + 1:]
            repairs += 1
        else:
            if repairs and isinstance(parsed, dict) and list(parsed) == ['clips']:
                return parse_object(source)
            return None


def _recover_batch(work, label, previous_error):
    if not previous_error.startswith('狀態回傳不是有效 JSON：'):
        return None
    candidates = list(work.glob(f'whole_song_{label}_????????_raw.txt'))
    if not candidates:
        return None
    path = max(candidates, key=lambda candidate: candidate.stat().st_mtime_ns)
    raw = path.read_text(encoding='utf-8')
    try:
        parse_object(raw)
    except SceneStateError as error:
        if str(error) == previous_error:
            return _repair_batch_json(raw)
    return None


# Shot-level timing arrays are for the shot-writing passes only. The outline
# leaves timing to them, so it receives coarse sections and energy instead.
_OUTLINE_DROP = ('transient_candidates_s', 'predicted_downbeats_s')
_KEY_LIMIT = 400


def _outline_task(task):
    """The outline's view of the commission, without per-beat timing arrays."""
    music = {key: value for key, value in task['music'].items() if key not in _OUTLINE_DROP}
    music['time_basis'] = ('Window boundaries, source notes, SRT, and global music cues are song-relative. '
                           'Section times within each window are clip-relative.')
    return {**task, 'music': music,
            'clip_windows': [{key: value for key, value in window.items() if key not in _OUTLINE_DROP}
                             for window in task['clip_windows']]}


def _beat_keys(beat, req, count):
    """Optional outline index keys. A malformed key is dropped, never fatal."""
    keys = {}
    activity = beat.get('activity')
    if isinstance(activity, str) and activity.strip().lower() in MODES:
        keys['activity'] = activity.strip().lower()
    for name in ('scene', 'cast', 'style', 'formation', 'end_state'):
        value = beat.get(name)
        if isinstance(value, str) and value.strip():
            value = _visual(value, name, req, count, False).strip()
            if value:
                keys[name] = value[:_KEY_LIMIT]
    return keys


def _shot_window(req, segment, window, ending):
    """Project authored windows onto the same clock as music cues and shot starts."""
    start = window['start']
    end = window['end']
    duration = window['duration']
    local = {key: value for key, value in window.items() if key not in ('start', 'end', 'source_notes')}
    local['source_notes'] = [
        {'title': TIME_SPAN.sub('', chapter['title']).strip(' ｜|:：'),
         'start_s': round(max(chapter['start'], start) - start, 6),
         'end_s': round(min(chapter['end'], end) - start, 6),
         'actions': chapter['actions'], 'constraints': chapter['constraints']}
        for chapter in window['source_notes']
    ]
    local_segment = {**segment, 'seconds': duration, 'direction_ending_contract': ending}
    local['srt'] = [
        {key: cue[key] for key in ('clip_start', 'clip_end', 'text')}
        for cue in excerpt(req, local_segment)
    ]
    for key in ('transient_candidates_s', 'predicted_downbeats_s'):
        local[key] = [at for at in local[key] if 0 <= at < duration]

    policy = clip_ending(req, local_segment)
    local['ending'] = {key: policy[key] for key in ('finish_work', 'phase', 'instruction') if key in policy}
    # Carry only deadlines this slot can act on. A passed deadline maps to the opening.
    local['ending'].update({
        key: round(max(0, policy[key] - start), 6)
        for key in ('resolve_start_by', 'settle_by', 'end_time')
        if key in policy and policy[key] <= end + 1e-6
    })
    return local


def _batch_shots(cfg, req, segments, originals, work, rewrite, task, fingerprint, progress, cancelled):
    count = len(originals)
    work = Path(work)
    checkpoint = work / 'whole_song_checkpoint.json'
    if checkpoint.is_file():
        stored = json.loads(checkpoint.read_text(encoding='utf-8'))
        state = stored['state']
        if (stored.get('version') != 1 or stored.get('input_sha256') != fingerprint
                or stored.get('content_sha256') != digest(state)):
            raise SceneStateError('保存的 35B 分批稿與本次專案資料不一致。')
    else:
        state = {'setup': '', 'beats': [], 'beat_keys': [], 'accepted': [], 'last_error': ''}
    # Checkpoints written before outline index keys simply have none.
    state.setdefault('beat_keys', [])
    accepted = state['accepted']
    pictures = _pictures(originals)

    def save():
        atomic_json(checkpoint, {'version': 1, 'input_sha256': fingerprint,
                                 'content_sha256': digest(state), 'state': state})
        if progress:
            progress(len(accepted), len(segments), bool(state['beats']))

    def direct(system, payload, label, *, batch=False):
        if cancelled and cancelled():
            raise InterruptedError('已停止 35B 全曲導演。')
        call_id = uuid.uuid4().hex[:8]
        parts = [('text', json.dumps(payload, ensure_ascii=False, separators=(',', ':')))] + pictures
        raw = rewrite(cfg, system, parts, call_id)
        (work / f'whole_song_{label}_{call_id}_raw.txt').write_text(str(raw), encoding='utf-8')
        try:
            return parse_object(raw)
        except SceneStateError as error:
            if batch and isinstance(raw, str) and error.errors[0]['code'] == 'invalid_json':
                repaired = _repair_batch_json(raw)
                if repaired is not None:
                    return repaired
            raise

    if progress:
        progress(len(accepted), len(segments), bool(state['beats']))
    if not state['beats']:
        from banana_mv.director_examples import reference_index
        outline = direct(OUTLINE_SYSTEM + '\nSupported activities: ' + ', '.join(MODES)
                         + '\nREFERENCE INDEX (activity: keys):\n' + reference_index(),
                         _outline_task(task), 'outline')
        beats = outline.get('beats')
        if not isinstance(beats, list) or len(beats) != len(segments):
            raise SceneStateError(f'全曲大綱須完整填寫 {len(segments)} 個段落槽。')
        for number, beat in enumerate(beats, 1):
            if not isinstance(beat, dict) or type(beat.get('index')) is not int or beat['index'] != number:
                raise SceneStateError(f'全曲大綱第 {number} 槽編號不符。')
        setup = _visual(outline.get('setup', ''), 'setup', req, count, False)
        authored_roles = role_pictures(task['author_setup'])
        for role, picture in role_pictures(setup).items():
            if role in authored_roles and authored_roles[role] != picture:
                raise SceneStateError(f'全曲大綱改動了共同設定的 {role} 圖片綁定。')
        state['beats'] = [_visual(beat.get('event'), 'event', req, count) for beat in beats]
        state['beat_keys'] = [_beat_keys(beat, req, count) for beat in beats]
        state['setup'] = '\n\n'.join(filter(None, (task['author_setup'], setup)))
        save()

    while len(accepted) < len(segments):
        start = len(accepted)
        stop = min(start + BATCH_SIZE, len(segments))
        local_task = {
            'shared_setup': state['setup'],
            'whole_song_outline': state['beats'],
            'style': task['style'],
            'intensity': task['intensity'],
            'editing': task['editing'],
            'incoming_handoff': accepted[-1]['handoff'] if accepted else '',
            'clip_windows': [_shot_window(req, seg, window, task['ending']) for window, seg in
                             zip(task['clip_windows'][start:stop], segments[start:stop])],
            'predicted_bpm': task['music']['predicted_bpm'],
        }
        for offset, window in enumerate(local_task['clip_windows']):
            keys = state['beat_keys'][start + offset] if start + offset < len(state['beat_keys']) else {}
            if keys:
                window['planned'] = keys
        if state['last_error']:
            local_task['previous_validation_error'] = state['last_error']
        try:
            if cancelled and cancelled():
                raise InterruptedError('已停止 35B 全曲導演。')
            label = f'slots_{start + 1:02d}_{stop:02d}'
            delivery = _recover_batch(work, label, state['last_error'])
            if delivery is None:
                delivery = direct(_slot_system(req, local_task['clip_windows'], state['setup']),
                                  local_task, label, batch=True)
            clips = delivery.get('clips')
            if not isinstance(clips, list) or len(clips) > stop - start:
                raise SceneStateError(f'本批只接受第 {start + 1} 至 {stop} 槽。')
            for number in range(start + 1, stop + 1):
                offset = number - start - 1
                clip = clips[offset] if offset < len(clips) else None
                if not isinstance(clip, dict) or type(clip.get('index')) is not int or clip['index'] != number:
                    raise SceneStateError(f'全曲拍攝稿第 {number} 槽的編號缺漏、重複或順序錯誤。')
                seg = segments[number - 1]
                seconds = task['clip_windows'][number - 1]['duration']
                local = _shot_rows(clip.get('shots'), req, count, seconds, f'第 {number} 槽')
                handoff = _visual(clip.get('handoff'), 'handoff', req, count)
                if len(handoff) > 1000:
                    raise SceneStateError(f'第 {number} 槽的交接摘要超過 1000 字元。')
                shots = [dict(shot, frame=shot['frame'] + seg['start_frame']) for shot in local]
                row, = slice_shots(shots, [seg])
                h3_prompt(req, {**seg, 'director_plan': row,
                                'fixed_reference_settings': state['setup']}, count, None)
                accepted.append({'shots': shots, 'handoff': handoff})
                state['last_error'] = ''
                save()
        except ValueError as error:
            state['last_error'] = str(error)[:1000]
            save()
            raise
    return state['setup'], [shot for clip in accepted for shot in clip['shots']]


def ensure_whole_song_plan(cfg, req, segments, originals, work, rewrite, *, progress=None, cancelled=None):
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
    fixed_slots = req.get('whole_song_director') is True
    if fixed_slots:
        author_setup = map_image_mentions(req.get('shared_setup', ''), count)
        task['author_setup'] = normalize_mv_prompt(author_setup, count) if author_setup else ''
        task['director'] = req.get('director_engine', '9b')
        task['delivery'] = 'fixed_slots'
    fingerprint = digest(task)
    path = Path(work) / 'director_plan.json'
    if path.is_file():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if (saved.get('version') != VERSION or saved.get('input_sha256') != fingerprint or
                saved.get('content_sha256') != digest({k: v for k, v in saved.items()
                                                       if k not in ('input_sha256', 'content_sha256')})):
            raise SceneStateError('保存的全曲拍攝稿與專案資料不一致。')
        return saved
    if fixed_slots and req.get('director_engine', '9b') != '35b':
        raise SceneStateError('新的全曲拍攝稿只使用 35B。')
    director_task = {key: value for key, value in task.items() if key not in ('clip_windows', 'ending')}
    director_task['ending'] = ending_contract({**req, 'segment_seconds': duration}, duration)
    peaks = set()
    downbeats = set()
    for seg in segments:
        evidence = seg.get('audio_evidence', {})
        start = seg['start']
        peaks.update(round(start + t, 3) for t in evidence.get('transient_candidates_s', []))
        downbeats.update(round(start + t, 3) for t in evidence.get('music_structure', {}).get('downbeats_s', []))
    director_task['music'] = {
        'transient_candidates_s': sorted(t for t in peaks if t < duration),
        'predicted_downbeats_s': sorted(t for t in downbeats if t < duration),
        'pulse_estimate': next((seg['audio_evidence']['pulse_estimate'] for seg in segments
                                if seg.get('audio_evidence', {}).get('pulse_estimate')), None),
    }
    try:
        if fixed_slots:
            director_task['ending'] = contract
            timed = parse_timed_source(task['brief'])
            chapters = timed[1] if timed is not None else []
            director_task['clip_windows'] = [
                {'index': seg['index'] + 1, 'start': window['start'], 'end': window['end'],
                 'duration': round(min(seg['seconds'], duration - seg['start']), 9),
                 'energy': window['music'].get('relative_energy'),
                 'quiet_intervals_s': window['music'].get('quiet_intervals_s', []),
                 'sections': window['music'].get('music_structure', {}).get('sections', []),
                 'transient_candidates_s': window['music'].get('transient_candidates_s', []),
                 'predicted_downbeats_s': window['music'].get('music_structure', {}).get('downbeats_s', []),
                 'source_notes': [chapter for chapter in chapters
                                  if chapter['start'] < window['end'] and chapter['end'] > window['start']]}
                for seg, window in zip(segments, task['clip_windows'])]
            director_task['music']['predicted_bpm'] = next(
                (structure['bpm'] for window in task['clip_windows']
                 if 'bpm' in (structure := window['music'].get('music_structure', {}))), None)
            director_task['music']['time_basis'] = (
                'Window boundaries, source notes, SRT, and global music cues are song-relative. '
                'Music offsets within each window are clip-relative.')
            setup, shots = _batch_shots(cfg, req, segments, originals, work, rewrite, director_task,
                                        fingerprint, progress, cancelled)
        else:
            parts = [('text', json.dumps(director_task, ensure_ascii=False, separators=(',', ':')))] + _pictures(originals)
            raw = rewrite(cfg, SYSTEM + '\nSupported modes: ' + ', '.join(MODES), parts, uuid.uuid4().hex[:8])
            (Path(work) / 'whole_song_director_raw.txt').write_text(str(raw), encoding='utf-8')
            setup, shots = _validated(raw, req, count, duration)
        rows = slice_shots(shots, segments)
        for row in rows:
            h3_prompt(req, {**segments[row['index']], 'director_plan': row,
                            'fixed_reference_settings': setup}, count, None)
    except ValueError as error:
        engine = req.get('director_engine', '9b').upper() if fixed_slots else '9B'
        raise SceneStateError(f'{engine} 全曲拍攝稿交稿失敗：' + str(error)) from error
    plan = {'version': VERSION, 'shared_setup': setup, 'shots': shots,
            'segments': rows, 'ending_contract': contract}
    plan['content_sha256'] = digest(plan)
    plan['input_sha256'] = fingerprint
    atomic_json(path, plan)
    return plan
