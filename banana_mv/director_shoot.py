"""5070: let 9B direct camera cuts; Python still owns SRT, cast and wardrobe.

Unlike the older locked_shoot.plan_slots path, a vocal handoff is never a
camera-cut instruction. 9B chooses the shot count, positions and timing from
the isolated current-clip event.  Python validates shot clocks and keeps the
independently timed SRT vocal list in the final H3 prompt.
"""
import re
import uuid

from banana_mv.commission_guard import scene_wardrobe_schedule
from banana_mv.lyrics_reference import excerpt, vocal_timeline
from banana_mv.scene_state import SceneStateError, rewrite_retry_count
from banana_mv.locked_shoot import (
    SHOT, VOCAL_ACTION, PROPS, _active_scene, _cfg, _errors, _extract,
    _native, _native_output_template, _quiet_verb, _repair_vocals,
    _vocal_role, _pronoun_roles, singer_rows,
)

DIRECTOR_SYSTEM = (
    'You are the MiniMax H3 Ref2VA CINEMATOGRAPHER for THIS CLIP ONLY. '
    'Python already owns the current event, identities, wardrobe, scene state '
    'and the original audio SRT vocal windows. Choose your OWN number of shots '
    'and exact CAMERA cut points, based on meaningful physical changes, '
    'character interaction, performance and visual storytelling. '
    'SRT vocal-window boundaries are NOT mandatory camera cuts. '
    'A continuous emotional exchange may be ONE unbroken shot or two '
    'meaningfully distinct reverse angles. A rapid action/rap sequence can '
    'use several purposeful cuts. Avoid multiple nearly identical push-ins, '
    'refilming the same pose or cutting just to zoom closer. '
    'Every cut must create a new visual idea, action, perspective or reaction. '
    'Within a shot, allow several SRT vocal changes without cutting camera. '
    'Preserve the exact source audio; do not add dialogue, lyrics or voices. '
    'Non-singers remain silent during their unassigned SRT windows. '
    'Provide SIX native H3 sections: subject_definitions, summary, '
    'retention_analysis, detailed_description, overall_soundscape, '
    'non_diegetic_music. In detailed_description use sequential [Shot N] '
    'labels, one paragraph per meaningful camera shot. Shot 1 begins at '
    '0 seconds; every subsequent [Shot N] must begin with '
    'At mm:ss.mmm, and its cinematic action. You may write just [Shot 1]. '
    'Do not copy previous/future plot, add performers or change outfits. '
    'The final fixed H3 identity/audio sections are supplied by Python.'
)
REPAIR_SYSTEM = (
    'You are editing ONE existing MiniMax H3 Ref2VA shot paragraph. '
    'Keep the camera cut time and framing, physical action, character identities '
    'and the scene. Fix ONLY the given cast or wardrobe error. '
    'Return the native six-section H3 format with exactly the requested '
    '[Shot N] in detailed_description. No new shots or dialogue.'
)
CLOCK = re.compile(
    r'^\s*(?:At\s+)?(?P<minutes>\d{1,2}):(?P<seconds>\d{2}'
    r'(?:\.\d{1,3})?)\s*[,;:]\s*', re.I
)
MAX_SHOTS = 12


def parse_director_shots(raw, seconds, cues, scene_schedule=()):
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
        for i, mark in enumerate(labels, 1):
            number = int(mark[1])
            if number != i:
                raise ValueError('9B shots must be sequential [Shot 1], [Shot 2]...')
            body = text[mark.end():labels[i].start() if i < len(labels) else len(text)].strip()
            clock = CLOCK.match(body)
            if i == 1:
                start = 0.0
                if clock:
                    start = round(int(clock['minutes']) * 60 + float(clock['seconds']), 3)
                    body = body[clock.end():].strip()
                if abs(start) > 0.001:
                    raise ValueError('First camera shot must start at 0 seconds.')
            else:
                if not clock:
                    raise ValueError(f'[Shot {i}] needs At mm:ss.mmm camera cut time.')
                start = round(int(clock['minutes']) * 60 + float(clock['seconds']), 3)
                body = body[clock.end():].strip()
                if start <= parts[-1][1] + 0.001 or start >= float(seconds) - 0.01:
                    raise ValueError('9B camera shot cut times must strictly increase inside this clip.')
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
    """When one camera shot spans multiple vocal windows, SRT owns the lips.

    Explicit 'sings/raps/speaks' prose in an unbroken mixed/quiet camera shot
    can accidentally imply a voice across an unassigned gap. Neutralize those
    directives WITHOUT adding camera cuts. Source lip-sync is still precisely
    specified in the separate Python-owned SRT window list.
    """
    revised, audit = _repair_vocals(blocks, slots, fixed)
    pronouns = _pronoun_roles(fixed)
    for slot in slots:
        number = slot['number']
        # Exactly one unbroken vocalist may be described as singing.
        rows = slot['rows']
        pure = len(rows) == 1 and (
            ('(S1) ONLY' in rows[0]) or ('(S2) ONLY' in rows[0])
            or ('lip-sync together' in rows[0])
        )
        if pure:
            continue
        def neutralize(match):
            assigned = _vocal_role(match['actor'], pronouns)
            if not assigned:
                return match[0]
            replacement = (match[0][:match.start('verb')-match.start()]
                           + _quiet_verb(match['verb']))
            audit.append({'shot': number, 'from': match[0], 'to': replacement,
                          'reason': 'SRT vocal handoff or silence within one camera shot'})
            return replacement
        revised[number] = VOCAL_ACTION.sub(neutralize, revised[number])
    return revised, audit


def _free_commission(req, segment, event, pictures, wardrobe, cues,
                     continuity=False, scene_schedule=()):
    duration = float(segment['seconds'])
    lines = [
        '=== 1. CURRENT CLIP AUTHORITY — PYTHON FACTS ===',
        f'CLIP DURATION: {duration:.3f}s (ALL times local).',
        'Singer S1 = <Subject 1>, identity picture ' + pictures['S1'] + '.',
        'Singer S2 = <Subject 2>, identity picture ' + pictures['S2'] + '.',
        'CURRENT WARDROBE / PICTURE CONTINUITY:',
    ]
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
    lines.append('SRT VOCAL WINDOWS — they control lip-sync, NEVER camera cuts:')
    lines.extend(singer_rows(0, duration, cues))
    lines.append('Never add singing, Rap or Spoken in a non-assigned interval.')
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
    lines += [
        '',
        '=== 2. THIS CLIP EVENT — DO NOT LEAK OTHER CLIPS ===',
        ('OPENING CONTINUITY: the preceding frame shows the CURRENT physical '
         'pose, prop positions, lighting and present clothes; advance the action, '
         'never replay completed events.' if continuity else
         'OPENING CONTINUITY: begin directly with the assigned current event.'),
        'ACT ONLY ON THIS CURRENT CLIP EVENT:',
        event,
        '',
        '=== 3. 9B CINEMATOGRAPHY — YOU CHOOSE SHOT COUNT AND CUT TIMES ===',
        'Choose meaningful camera cuts ONLY when the visual storytelling needs them.',
        'DO NOT make a new Shot when the camera simply pushes closer to the '
        'same pose/face and nothing meaningful changes.',
        'A still, emotional Spoken exchange can be one sustained take or a '
        'motivated reaction reverse-shot. Rap/action can have several distinct angles.',
        'Do not equate SRT vocal handoffs, line endings, rests, or song beats '
        'with obligatory CAMERA cuts. A continuous take can contain multiple SRT vocals.',
        'The actor in an SRT gap can listen, breathe or move but not vocalize.',
        'No previous/next events, invented dialogue, new person or costume reset.',
        'Preserve current position, direction, prop handling, lighting and stage.',
        'Write native SIX H3 Ref2VA sections. Python supplies final '
        'identity/wardrobe/audio sections, so spend creativity on '
        'detailed_description: camera position, action, expression, consequence.',
        'Use [Shot 1] for the first shot (starts at 0.000s). '
        'For EACH later camera CUT label [Shot N] At mm:ss.mmm, ...',
        'One-shot is valid: output only [Shot 1], no forced [Shot 2]. '
        'Choose freely up to 12 meaningful shots for a clip.',
        'Camera energy: ' + str(req.get('intensity', 'high')) + '.',
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
    ]
    return '\n'.join(lines)


def write_director_shoot_prompt(cfg, req, segment, event, fixed, pictures,
                                wardrobe, refs, images, rewrite, progress=None):
    """Actual 5070 two-singer path: independent SRT windows + 9B camera."""
    cues = vocal_timeline(excerpt(req, segment))
    schedule = scene_wardrobe_schedule(event, fixed, pictures, segment['seconds'])
    if schedule:
        segment['scene_wardrobe_schedule'] = schedule
    else:
        segment.pop('scene_wardrobe_schedule', None)
    task = _free_commission(req, segment, event, pictures, wardrobe, cues,
                            continuity=len(refs) > 2, scene_schedule=schedule)
    calls = 0
    retry_limit = rewrite_retry_count(req)
    max_calls = (retry_limit+1) * (3 + 2 * MAX_SHOTS)
    def call(parts, temperature, system=DIRECTOR_SYSTEM):
        nonlocal calls
        calls += 1
        if progress:
            progress({'stage': 'rewriting', 'clip_index': segment['index'],
                      'attempt': calls, 'max_attempts': max_calls})
        return rewrite(_cfg(cfg, temperature), system, parts, uuid.uuid4().hex[:8])

    for restart in range(retry_limit+1):
        blocks = None
        slots = None
        why = ''
        for attempt in range(3):
            prompt = (task if not why else task + '\nFORMAT REMINDER: ' + why
                      + '\nReissue the SIX H3 sections. You choose the Shot count. '
                      'All non-first shots require At mm:ss.mmm.')
            try:
                blocks, slots = parse_director_shots(
                    call(images + [('text', prompt)], .4 if attempt == 0 else .15),
                    segment['seconds'], cues, schedule)
                break
            except ValueError as error:
                why = str(error)
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
                    'SRT VOCAL AUTHORITY:\n' + '\n'.join(shot['rows'])
                    + '\nCURRENT WARDROBE: ' + repr(wardrobe)
                    + '\nERRORS (repair only these):\n' + '\n'.join(messages)
                    + '\nORIGINAL VISUAL SHOT:\n' + blocks[number]
                    + '\nKeep the original framing, timing and physical event. '
                    'Return the SIX native Ref2VA sections containing ONLY '
                    f'[Shot {number}] in detailed_description.\n'
                    + _native_output_template([shot], pictures, wardrobe)
                )
                try:
                    blocks[number] = _extract(
                        call([('text', note)], .15, REPAIR_SYSTEM),
                        slots, only=number)[number]
                    blocks, fixes = _safe_vocals(blocks, slots, fixed)
                    vocal_fixes.extend(fixes)
                except ValueError as error:
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
            'writer_calls': calls,
            'contract_check_calls': 1 + attempt,
            'director_shot_count': len(slots),
            'vocal_auto_correction_count': len(vocal_fixes),
            'fresh_restarts': restart,
        }
        return _native(blocks, slots, pictures, wardrobe, len(refs) > 2,
                       event, len(refs), fixed, schedule)
