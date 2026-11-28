"""5070: let 9B direct camera cuts; Python still owns SRT, cast and wardrobe.

Unlike the older locked_shoot.plan_slots path, a vocal handoff is never a
camera-cut instruction. 9B chooses the shot count, positions and timing from
the isolated current-clip event.  Python validates shot clocks and keeps the
independently timed SRT vocal list in the final H3 prompt.
"""
import logging
import re
import uuid

from banana_mv.commission_guard import scene_wardrobe_schedule
from banana_mv.body_form import declared_body_forms
from banana_mv.lyrics_reference import excerpt, vocal_timeline
from banana_mv.scene_state import SceneStateError, rewrite_retry_count
from banana_mv.locked_shoot import (
    SHOT, VOCAL_ACTION, PROPS, _active_scene, _cfg, _errors, _extract,
    _native, _native_output_template, _quiet_verb, _repair_vocals,
    _vocal_role, _pronoun_roles, singer_rows, clip_screen_cast_rule,
)

DIRECTOR_SYSTEM = (
    'You are the MiniMax H3 Ref2VA CREATIVE MV FILM DIRECTOR for THIS CLIP. '
    'Bring the current commissioned event to life with purposeful character blocking, '
    'evolving emotion, reactions, physical interplay, visual ideas and cinematography. '
    'Develop expressive acting and local micro-beats freely within the assigned event; '
    'its established starting state and required outcome remain authoritative. '
    'Choose your own number of camera shots and exact cut points to serve the performance. '
    'Vary scale, perspective, motion, lighting and duration with dramatic purpose, '
    'including wide views, full-body action, inserts and intimate lip-sync as appropriate. '
    'Use natural lip-sync where it suits the scene. Tagged SRT windows guide who to show '
    'if filming lip-sync in that window. Keep camera cuts and coverage scene-led. '
    'The original song is the only audible voice source; add no independent voice from lip-sync. '
    'Maintain reference identities, current wardrobe and physical cause/effect; '
    'performers may move, react and change expressions as the scene develops. '
    'Honor the explicitly authorized on-screen cast and source audio; '
    'later plot milestones and extra recorded dialogue stay outside this clip. '
    'Return native H3 sections: subject_definitions, summary, retention_analysis, '
    'detailed_description, overall_soundscape, non_diegetic_music. '
    'In detailed_description, use [Shot 1] at 0 seconds and, for each further cut, '
    '[Shot N] At mm:ss.mmm, with a concrete visual action. One continuous take is valid. '
    'Python supplies the final fixed H3 identity and audio fields.'
)
SHOT_DRAFT_VERSION = '35b-director-first-v1'
SHOT_DRAFT_SYSTEM = """You are the cinematic MV director for the current clip.
Your job is the performance, choreography, photography and editing, not
reference metadata or audio paperwork. Python supplies the authoritative cast,
wardrobe, SRT windows, clip scope and final H3 packaging. Follow the current
commission, including established starting state, required outcomes and explicit
camera constraints. References establish identity, not a fixed pose. Use the
assigned subject labels rather than guessing character names.

CREATIVE APPROACH: Develop the current event into expressive physical action.
Choose suitable movement phrases, character intentions and responses first;
then choose camera viewpoints, trajectories and editorial timing to reveal them.
Deepen the same action rather than piling on unrelated actions. For substantial
shots, integrate these cinematic dimensions naturally in continuous prose:
body mechanics (support, weight, direction, acceleration, follow-through);
material and environmental response (fabric, hair, props, contact and inertia);
performance (gaze, expression, intention and interaction);
spatial composition (positions, depth, foreground, screen direction);
camera and editing (lens perspective, height, starting and ending framing,
travel, speed and action continuity across cuts);
light and image (motivated sources, shadow, reflections and texture).
Use the selected specialty and demonstration to develop concrete visible
details at the quality of Dangerous Contract V2, not generic movement names.
Its substantive shots often use around 120–160 English words; this illustrates
depth, not a quota, a ceiling or a reason to pad. A brief insert may be brief.
Choose shot count freely within the existing 12-shot interface, including an
expressive continuous take. Existing shot clocks allow at least 0.250s per shot.
For high-energy scenes, make bold, precise choices in moving coverage, proximity,
perspective and motivated cuts; quiet scenes deserve equally precise restraint.
Carry unfinished action and changing positions through the edit and clip handoff.
Honor the assigned intensity, music evidence, cast and continuity; add no future
events, independent vocals, dialogue, subtitles or replacement audio.

DELIVERY: Write only detailed_description: followed by the finished English
shot paragraphs. [Shot 1] starts at zero; subsequent shots begin
[Shot N] At mm:ss.mmm, using clip-local cut times. No other H3 fields, outline,
analysis, or explanation in the formal answer. Spend creative effort on the
actual shot prose, not on drafting or reviewing fields that Python assembles.
"""
REPAIR_SYSTEM = (
    'You are editing ONE existing MiniMax H3 Ref2VA shot paragraph. '
    'Keep the camera cut time and framing, physical action, character identities '
    'and the scene. Fix ONLY the given cast or wardrobe error. '
    'Return the native six-section H3 format with exactly the requested '
    '[Shot N] in detailed_description. No new shots or dialogue.'
)
CLOCK = re.compile(
    # mm:ss.mmm；也讀 hh:mm:ss.mmm、mm:ss:mmm、mm:ss,mmm（9B 偶爾這樣寫，以前會被讀錯）。
    r'^\s*(?:(?:At\s+)?(?:(?P<hours>\d{1,2}):(?=\d{2}:\d{2}[.,]))?'
    r'(?P<minutes>\d{1,2}):(?P<seconds>\d{2})(?:[.,](?P<frac>\d{1,3})|:(?P<ms>\d{3}))?'
    # 9B 也常照官方範例寫秒數：At 1.500s / At 1.5 秒 / At 1.5–3.2s（取起點）。
    r'|At\s+(?P<plain>\d{1,3}(?:\.\d{1,3})?)(?:\s*[–-]\s*\d{1,3}(?:\.\d{1,3})?)?'
    r'\s*(?:s|sec|secs|seconds|秒)(?![A-Za-z]))'
    r'(?:\s*[,;:，—–-]+\s*|\s+)', re.I
)


MIN_SHOT_SECONDS = 0.25


def _clock_value(clock):
    if clock['plain'] is not None:
        return round(float(clock['plain']), 3)
    fraction = (float('0.' + clock['frac']) if clock['frac'] else
                int(clock['ms']) / 1000 if clock['ms'] else 0.0)
    return round(int(clock['hours'] or 0) * 3600 + int(clock['minutes']) * 60
                 + int(clock['seconds']) + fraction, 3)
MAX_SHOTS = 12


def _clock(value):
    minutes = int(value // 60)
    return f'{minutes:02d}:{value - minutes * 60:06.3f}'


def _shot_time(clock, seconds, clip_start):
    """段內秒數；9B 若寫成整首歌的時間（例如 10–20 秒段寫 At 00:12.300），換回段內時間。"""
    value = _clock_value(clock)
    if (value >= float(seconds) and clip_start is not None
            and clip_start <= value < clip_start + float(seconds)):
        value = round(value - clip_start, 3)
    return value


def _fill_cut_times(bodies, seconds, clip_start=None):
    """回傳每一鏡補上的切鏡秒數（沒漏寫的是 None）；第一鏡不需要時間。
    只補「完全沒寫時間」的鏡頭；開頭有 At 但格式怪的不補，免得變成兩組時間。"""
    times = []
    for i, body in enumerate(bodies):
        clock = CLOCK.match(body)
        if i == 0:
            times.append(0.0)
        elif clock:
            times.append(_shot_time(clock, seconds, clip_start))
        elif re.match(r'\s*At\b', body, re.I):
            return [None] * len(bodies)
        else:
            times.append(None)
    missing = [i for i, value in enumerate(times) if value is None]
    if not missing:
        return [None] * len(bodies)
    filled = list(times)
    for i in missing:
        later = next((j for j in range(i + 1, len(times)) if times[j] is not None), None)
        after = times[later] if later is not None else float(seconds)
        steps = (later if later is not None else len(times)) - i + 1
        filled[i] = round(filled[i - 1] + (after - filled[i - 1]) / steps, 3)
    logging.getLogger(__name__).warning('9B 漏寫切鏡時間，已自動補上第 %s 鏡。',
                                        '、'.join(str(i + 1) for i in missing))
    return [filled[i] if i in missing else None for i in range(len(bodies))]


def parse_director_shots(raw, seconds, cues, scene_schedule=(), clip_start=None):
    """Parse 9B-authored CAMERA cuts; do not divide shots at SRT boundaries."""
    text = re.sub(r'<think>.*?</think>', '', raw, flags=re.I | re.S)
    has_native = bool(re.search(r'(?im)^\s*detailed_description\s*:', text))
    if has_native:
        text = re.split(r'(?im)^\s*detailed_description\s*:', text, maxsplit=1)[1]
        text = re.split(
            r'(?im)^\s*(?:overall_soundscape|non_diegetic_music)\s*:',
            text, maxsplit=1
        )[0]
    labels = list(SHOT.finditer(text))
    if not labels:
        # A single unlabelled native detailed_description is a legitimate
        # ONE-SHOT film; unlike a five-shot camera template, do not invent cuts.
        if not has_native or not text.strip():
            raise ValueError('9B must supply a detailed_description and [Shot 1].')
        parts = [(1, 0.0, text.strip())]
    else:
        if len(labels) > MAX_SHOTS:
            raise ValueError('9B camera cuts exceed the practical per-clip limit.')
        parts = []
        bodies = [text[mark.end():labels[i].start() if i < len(labels) else len(text)].strip()
                  for i, mark in enumerate(labels, 1)]
        filled = _fill_cut_times(bodies, seconds, clip_start)
        for i, mark in enumerate(labels, 1):
            number = int(mark[1])
            if number != i:
                raise ValueError('9B shots must be sequential [Shot 1], [Shot 2]...')
            body = bodies[i - 1]
            clock = CLOCK.match(body)
            if clock is None and filled[i - 1] is not None:
                # 9B 漏寫這一鏡的 At 時間：取前後兩鏡的中點補上，不整份退稿重寫。
                body = f'At {_clock(filled[i - 1])}, ' + body
                clock = CLOCK.match(body)
            if i == 1:
                start = 0.0
                if clock:
                    start = _clock_value(clock)
                    body = body[clock.end():].strip()
                if abs(start) > 0.001:
                    raise ValueError('First camera shot must start at 0 seconds.')
            else:
                if not clock:
                    raise ValueError(f'[Shot {i}] needs At mm:ss.mmm camera cut time.')
                start = _shot_time(clock, seconds, clip_start)
                body = body[clock.end():].strip()
                # 每鏡至少 0.25 秒：529e579d3225 的 9B 把 2.8 秒寫成 At 00:00.002，
                # 一路 0.002、0.005… 以前只要「晚 1 毫秒」就放行。
                if start < parts[-1][1] + MIN_SHOT_SECONDS or start > float(seconds) - MIN_SHOT_SECONDS:
                    raise ValueError(
                        '9B camera shot cut times must strictly increase inside this clip, each shot lasting '
                        f'at least {MIN_SHOT_SECONDS} s. Write seconds in the seconds field: At 00:02.800 '
                        'means 2.8 s; At 00:00.002 means 2 milliseconds.')
            if not body:
                raise ValueError(f'[Shot {i}] is empty.')
            parts.append((number, start, body))
    for scene in list(scene_schedule)[1:]:
        cut = float(scene['start'])
        if cut < 0.001 or cut >= float(seconds):
            continue
        if not any(abs(start - cut) < .012 for _, start, _ in parts):
            # A REAL location / wardrobe transition, unlike a singer handoff,
            # must be represented; otherwise the current outfit can leak.
            raise ValueError(f'Author-assigned scene/wardrobe cut at {cut:.3f}s is missing.')
    slots = []
    for i, (number, start, body) in enumerate(parts):
        end = parts[i+1][1] if i + 1 < len(parts) else round(float(seconds), 3)
        rows = singer_rows(start, end, cues)
        allowed = sorted({
            role for cue in cues
            if float(cue['clip_start']) < end and float(cue['clip_end']) > start
            for role in cue.get('subjects', ()) if role in ('S1', 'S2')
        })
        duet = any(
            set(cue.get('subjects', ())) == {'S1', 'S2'}
            and float(cue['clip_start']) < end and float(cue['clip_end']) > start
            for cue in cues
        )
        slots.append({'number': number, 'start': start, 'end': end,
                      'rows': rows, 'allowed_singers': allowed,
                      'duet_authorized': duet})
    return {number: body for number, _, body in parts}, slots


def _safe_vocals(blocks, slots, fixed):
    """Preserve acting and vocal delivery in shots spanning multiple SRT windows.

    Python's timed SRT rows control *when* visible lip-sync is allowed; a
    camera shot may span several voices and silence without losing the actor's
    expressive speaking, rapping or singing direction. Correct only an
    explicitly unauthorized singer/duet, leaving valid performance prose intact.
    """
    return _repair_vocals(blocks, slots, fixed)


def _clip_phase_note(ending):
    """Expose only local boundary semantics, never the future ending plan."""
    if not ending:
        return ''
    phase = ('excerpt' if ending.get('project_scope') == 'excerpt'
             else ending.get('phase'))
    notes = {
        'continuing': (
            'This is an ongoing part of the MV. The technical clip boundary '
            'is not a story ending. Carry the current performance and physical '
            'momentum naturally into the next clip. A motivated local pause or '
            'completed movement is fine; do not manufacture a closing pose or finale.'),
        'resolving': (
            'Film the decisive events and consequences actually assigned to '
            'this interval. Respect the commissioned timing and outcome; '
            'do not invent a final pose, fade, or extra hold.'),
        'terminal_hold': (
            'Carry the achieved result, present conditions, reactions or '
            'ongoing performance through this residual interval. Do not replay '
            'the climax. An explicitly assigned local final event takes priority.'),
        'excerpt': (
            'This is an excerpt of a larger MV, not the whole-work ending. '
            'Complete the assigned local event and leave the larger story open; '
            'do not manufacture a finale.'),
    }
    if phase not in notes:
        return ''
    return 'CLIP PHASE: ' + phase.upper() + '\n' + notes[phase]


def _free_commission(req, segment, event, pictures, wardrobe, cues,
                     continuity=False, scene_schedule=(), direction_policy='', body_form=None,
                     fixed='', creative35=False, ending=None):
    body_form = body_form or {}
    duration = float(segment['seconds'])
    lines = []
    if fixed and fixed.strip():
        # 共同設定全文：跟精簡通告單一樣給 9B 看，兩條拍攝路徑資訊量一致。
        from banana_mv.shoot_plan import fixed_settings_block
        lines += ['=== 0. SHARED SETUP — USER-AUTHORED, APPLIES TO EVERY CLIP ===',
                  fixed_settings_block(fixed.strip(), subjects=True), '']
    lines += [
        '=== 1. CURRENT CLIP FACTS — VOCALS / CAST / CONTINUITY ===',
        f'CLIP DURATION: {duration:.3f}s (ALL times local).',
        'Singer S1 = <Subject 1>, identity picture ' + pictures['S1'] + '.',
        'Singer S2 = <Subject 2>, identity picture ' + pictures['S2'] + '.',
        'CURRENT WARDROBE / PICTURE CONTINUITY:',
    ]
    cast_rule = clip_screen_cast_rule(event)
    if cast_rule:
        lines.extend(('=== CURRENT ON-SCREEN CAST: PYTHON FILMING AUTHORITY ===',
                      cast_rule))
    for role, number in (('S1', 1), ('S2', 2)):
        if role in wardrobe:
            lines.append(
                f'<Subject {number}> ({role}): face and hair from '
                f'{pictures[role]}; CURRENT OUTFIT: {wardrobe[role]}. '
                'The outfit is an already established state, not a dressing scene.')
        else:
            lines.append(
                f'<Subject {number}> ({role}): face and hair from '
                f'{pictures[role]}; preserve the actual CURRENT outfit '
                'in the opening frame/current event; do not reset it.')
    for role, number in (('S1', 1), ('S2', 2)):
        if role in body_form:
            lines.append(
                f'<Subject {number}> ({role}) BODY FORM / ANATOMY '
                f'(a stable identity fact, not clothing or an event): {body_form[role]}')
    lines.append('SRT CAST HINTS — use when choosing whom to show lip-syncing:')
    lines.extend(singer_rows(0, duration, cues))
    lines.append('Cover lip-sync only when useful to the scene. Follow the scene where nobody is tagged.')
    if scene_schedule:
        lines.append('AUTHOR-ASSIGNED PHYSICAL LOCATION / WARDROBE STATES:')
        for row in scene_schedule:
            lines.append(
                f'{row["start"]:.3f}–{row["end"]:.3f}s: {row["scene"]}; '
                + '; '.join(role + ' outfit: ' + item for role, item in row['wardrobe'].items()))
        for row in scene_schedule[1:]:
            lines.append(
                f'REQUIRED REAL SCENE CUT at {row["start"]:.3f}s: '
                'place a [Shot N] boundary here to keep location/outfit continuity. '
                'This is a physical scene change, not an SRT singer cut.')
    if phase_note := _clip_phase_note(ending):
        lines.extend(('', phase_note))
    if creative35:
        # The original production facts stay intact. Put the actual current
        # commission last, after policy/reference material, not before it.
        if direction_policy:
            lines.extend(('', '=== FILMING AUTHORITY ===', direction_policy))
        from banana_mv.core import action_lora_brief
        if brief := action_lora_brief(req):
            lines.extend(('', brief))
        lines.extend((
            '', '=== CURRENT EVENT — THE ONLY CLIP TO FILM ===',
            ('OPENING CONTINUITY: the preceding frame shows the CURRENT physical '
             'pose, prop positions, lighting and present clothes; advance naturally '
             'from those established results.' if continuity else
             'OPENING CONTINUITY: begin directly with the assigned current event.'),
            event,
            '',
            'DELIVER THE FINISHED SHOTS: Write only detailed_description: and the '
            'English [Shot N] paragraphs. Develop the assigned performance and '
            'its physical and cinematic detail to the depth of the reference example. '
            'Choose your own meaningful camera cuts using local times. '
            'Python assembles the other five H3 fields. Do not draft them.',
            'Camera energy: ' + str(req.get('intensity', 'high')) + '.',
        ))
        return '\n'.join(lines)
    lines += [
        '',
        '=== 2. CURRENT EVENT — DIRECT ITS PERFORMANCE ===',
        ('OPENING CONTINUITY: the preceding frame shows the CURRENT physical '
         'pose, prop positions, lighting and present clothes; advance naturally '
         'from those established results.' if continuity else
         'OPENING CONTINUITY: begin directly with the assigned current event.'),
        'DEVELOP AND FILM THIS CURRENT CLIP EVENT:',
        event,
        '',
        '=== 3. 9B DIRECTING — YOU CHOOSE SHOT COUNT, CAMERA AND PERFORMANCE ===',
        'Design local acting, body movement, expression changes, visual responses, '
        'camera coverage and dramatic timing around the assigned beat.',
        'Choose an unbroken emotional take or several distinct views as the events demand. '
        'Use scale and perspective to reveal full action, environment and character intimacy.',
        'Vocal changes and SRT line endings do not force camera cuts; '
        'characters continue their performance through the original song.',
        'Begin with established positions, props, wardrobe and scene geography. '
        'Let their movement, interactions, lighting and visible consequences evolve '
        'when motivated by this clip event.',
        'Keep the user-specified causal milestones in sequence, '
        'without staging a later chapter or adding new recorded dialogue.',
        'Write native SIX H3 Ref2VA sections. Python will assemble fixed '
        'identity, wardrobe and audio fields, so direct specific visual acting '
        'and cinematography in detailed_description.',
        'Use [Shot 1] at 0.000s; later camera cuts use [Shot N] At mm:ss.mmm. '
        'Choose freely up to 12 meaningful shots, including a valid one-shot.',
        'Camera energy: ' + str(req.get('intensity', 'high')) + '.',
    ]
    lines.extend([
        '',
        '=== NATIVE SIX-SECTION DELIVERY EXAMPLE (ONE-SHOT SHAPE) ===',
        'subject_definitions:\nReference the specified cast and current outfits.',
        'summary:\nFilm ONLY the current assigned event.',
        'retention_analysis:\n<Audio 1>: fully_copy, original unchanged.',
        'detailed_description:',
        '[Shot 1] A concrete cinematic paragraph showing this clip event, '
        'with deliberate composition, physical action and character interaction.',
        'overall_soundscape:\nThe supplied source song remains unchanged.',
        'non_diegetic_music:\nThe supplied original song.',
    ])
    if direction_policy:
        lines.extend(('', '=== 4. ADAPTATION / PERFORMANCE / EDITING AUTHORITY ===',
                      direction_policy))
    from banana_mv.core import action_lora_brief
    if brief := action_lora_brief(req):
        lines.extend(('', brief))
    return '\n'.join(lines)


def write_director_shoot_prompt(cfg, req, segment, event, fixed, pictures,
                                wardrobe, refs, images, rewrite, progress=None, direction_policy='',
                                body_form=None, shoot_event=None, ending=None):
    """Actual 5070 two-singer path: independent SRT windows + 9B camera."""
    body_form = body_form if body_form is not None else declared_body_forms(fixed)
    if body_form:
        segment['body_form'] = dict(body_form)
    cues = vocal_timeline(excerpt(req, segment))
    schedule = scene_wardrobe_schedule(event, fixed, pictures, segment['seconds'])
    if schedule:
        segment['scene_wardrobe_schedule'] = schedule
    else:
        segment.pop('scene_wardrobe_schedule', None)
    creative35 = cfg.get('director35') is not None
    task = _free_commission(req, segment, shoot_event if shoot_event is not None else event,
                            pictures, wardrobe, cues,
                            continuity=len(refs) > 2, scene_schedule=schedule,
                            direction_policy=direction_policy, body_form=body_form,
                            fixed=fixed, creative35=creative35, ending=ending)
    calls = 0
    retry_limit = rewrite_retry_count(req)
    draft_temperature = float(cfg['rewriter'].get('temperature', .7))
    max_calls = (retry_limit+1) * (3 + 2 * MAX_SHOTS)
    # 每次退稿的原因留在專案裡（status.json 會即時看到），查「為什麼重寫好幾次」不用猜。
    rejections = segment['writer_rejections'] = []

    def rejected(kind, reason):
        rejections.append({'call': calls, 'kind': kind, 'reason': str(reason)[:500]})
        del rejections[:-20]
    def call(parts, temperature, system=DIRECTOR_SYSTEM):
        nonlocal calls
        calls += 1
        if progress:
            progress({'stage': 'rewriting', 'clip_index': segment['index'],
                      'attempt': calls, 'max_attempts': max_calls})
        call_cfg = _cfg(cfg, temperature)
        # Existing 9B path stays non-thinking; selected 35B may think on the first draft only.
        if cfg.get('director35') is not None:
            if calls == 1:
                call_cfg['rewriter']['thinking'] = bool(cfg['rewriter'].get('thinking', False))
            if system == DIRECTOR_SYSTEM:
                # Python already assembles all six fields on this route.
                # Do not teach a second, conflicting six-field writing task.
                from banana_mv.director_library import creative_prompt
                system = creative_prompt(SHOT_DRAFT_SYSTEM, req, segment)
        return rewrite(call_cfg, system, parts, uuid.uuid4().hex[:8])

    for restart in range(retry_limit+1):
        blocks = None
        slots = None
        why = ''
        for attempt in range(3):
            prompt = (task if not why else task + '\nFORMAT REMINDER: ' + why
                      + ('\nReissue only detailed_description and the finished shots. '
                         if creative35 else '\nReissue the SIX H3 sections. ')
                      + 'You choose the Shot count. All non-first shots require At mm:ss.mmm.')
            try:
                blocks, slots = parse_director_shots(
                    call(images + [('text', prompt)], draft_temperature if attempt == 0 else .15),
                    segment['seconds'], cues, schedule, segment.get('start'))
                break
            except ValueError as error:
                why = str(error)
                rejected('format', why)
        if blocks is None:
            if restart < retry_limit:
                continue
            raise SceneStateError('9B 無法安排有效自由攝影鏡位：' + why)

        blocks, vocal_fixes = _safe_vocals(blocks, slots, fixed)
        failure = None
        for attempt in range(3):
            errors = _errors(blocks, wardrobe, schedule, slots)
            if not errors:
                break
            segment['commission_guard_errors'] = [
                msg for messages in errors.values() for msg in messages
            ]
            rejected('repair', ' | '.join(segment['commission_guard_errors']))
            if attempt >= 2:
                failure = SceneStateError(
                    '9B 局部修稿仍有服裝或人物衝突：'
                    + ' | '.join(segment['commission_guard_errors']))
                break
            for number, messages in errors.items():
                shot = slots[number-1]
                note = (
                    f'REPAIR ONE SHOT ONLY: [Shot {number}] '
                    f'({shot["start"]:.3f}–{shot["end"]:.3f}s, clip-local).\n'
                    'SRT CAST HINTS FOR LIP-SYNC:\n' + '\n'.join(shot['rows'])
                    + '\nCURRENT WARDROBE: ' + repr(wardrobe)
                    + '\nERRORS (repair only these):\n' + '\n'.join(messages)
                    + '\nORIGINAL VISUAL SHOT:\n' + blocks[number]
                    + '\nKeep the original framing, timing and physical event. '
                    'Return the SIX native Ref2VA sections containing ONLY '
                    f'[Shot {number}] in detailed_description.\n'
                    + _native_output_template([shot], pictures, wardrobe, body_form)
                )
                try:
                    blocks[number] = _extract(
                        call([('text', note)], .15, REPAIR_SYSTEM),
                        slots, only=number)[number]
                    blocks, fixes = _safe_vocals(blocks, slots, fixed)
                    vocal_fixes.extend(fixes)
                except ValueError as error:
                    rejected('repair_format', f'[Shot {number}] {error}')
                    failure = SceneStateError(
                        f'9B 第 {number} 鏡修稿格式錯誤：{error}')
                    break
            if failure is not None:
                break
        if failure is not None:
            if restart < retry_limit:
                continue
            raise SceneStateError(
                f'9B 自動重新起稿 {restart} 次後仍未通過：{failure}') from failure
        segment.pop('commission_guard_errors', None)
        segment['vocal_auto_corrections'] = vocal_fixes
        segment['prompt_profile'] = {
            'source': 'python_srt_free_camera',
            **({'draft_contract': SHOT_DRAFT_VERSION} if creative35 else {}),
            'writer_calls': calls,
            'contract_check_calls': 1 + attempt,
            'director_shot_count': len(slots),
            'vocal_auto_correction_count': len(vocal_fixes),
            'fresh_restarts': restart,
        }
        return _native(blocks, slots, pictures, wardrobe, len(refs) > 2,
                       event, len(refs), fixed, schedule, body_form=body_form)
