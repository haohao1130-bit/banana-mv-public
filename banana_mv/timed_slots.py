"""Optional explicit-time story parsing for the Python Slot branch.

User-authoritative scene times are mapped to song slots; metadata, cast and
cinematography instructions are not counted as narrative actions.
No model call, audio processing, or change to legacy chapter allocation.
"""
import re

HEADING = re.compile(r'^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$')
PLAIN_SCENE = re.compile(
    r'^(?:CHAPTER\s*\d+|SEGMENT\s*\d+|ACT\s*\d+|第[一二三四五六七八九十百零〇\d]+[章幕段])'
    r'\s*[｜|:：]\s*', re.I
)
PLAIN_SECTION = re.compile(r'^\d{1,2}\s*[｜|]\s*[^\d].*$')
_TIMED_ACT_SCENE = re.compile(r'^ACT\s*\d+\s*[｜|:：]', re.I)
# The long-form Master Director Prompt uses numbered, unmarked English sections.
# Close an ACT at these headings; never turn final checklists into film events.
_DIRECTOR_SECTION = re.compile(
    r'^(?:0[1-9]|10)\s*[｜|]\s*(?:PROJECT IDENTITY|SUBJECT DEFINITIONS|'
    r'ABSOLUTE CHARACTER ENTRANCE LOCK|AUDIO AND SRT LOCK|MASTER STORY CONCEPT|'
    r'FULL CINEMATIC STORYBOARD|CINEMATOGRAPHY AND EDITING RULES|'
    r'VISUAL CONSISTENCY AND NEGATIVE CONSTRAINTS|DIRECTOR.S PRIORITY ORDER|'
    r'FINAL DIRECTOR CHECKLIST)$', re.I
)
# Only explicit post-timeline notes close a plain ACT script. A scene's ordinary
# numbered beats must not be mistaken for another scene or given to a future clip.
_POST_ACT_SECTION = re.compile(
    r'^[一二三四五六七八九十]+[、.．]\s*'
    r'(?:全片連續性|全片規則|演出規則|最終導演意圖|導演意圖|最終檢查|生成要求|'
    r'最終創作目標|結語).*'
)
# Mirror the hand-written short film headings when MV input has explicit times.
AUTHORED_SECTION = re.compile(
    r'^(?:共同設定|共通設定|共用設定|全片設定|全局設定|全域設定|固定設定|全片固定設定|'
    r'固定角色|固定場景|角色設定|人物設定|角色綁定|世界觀|場景設定|全局電影設定|電影設定|'
    r'故事內容|故事劇情|劇情內容|劇本內容|故事大綱|劇情大綱|故事分段|劇情分段|'
    r'分段劇情|分段腳本|分鏡時間軸|分鏡腳本|分鏡內容|拍攝段落|段落安排|演出內容|'
    r'故事開始|正片內容|精密鏡頭時間軸|鏡頭時間軸|Shared Settings|Common Settings|'
    r'Shot Timeline|Storyboard|subject_definitions|detailed_description|最終畫面原則)\s*[：:]?$', re.I
)
PLAIN_CONTROL = re.compile(
    r'^【?(?:電影導演控制|電影攝影控制|角色表演控制|角色與物件連續性|'
    r'角色語音控制|聲音與語音控制|背景音樂與音效|跨段連續性控制|'
    r'生成優先級|全片限制|核心敘事)】?\s*[：:]?$'
)
TIME_SPAN = re.compile(
    r'(?<!\d)(?P<begin>\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)'
    r'\s*[-–—－~～至]\s*'
    r'(?P<end>\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?|音源結束|音樂結束|歌曲結束|曲終|結尾|結束|END)'
)
# 「03:10–音源結束」：章節一路到音源最後；分配時與實際片段取交集，自然截在曲尾。
AUDIO_END_SECONDS = 86400.0
BRACKET_TIMED_TITLE = re.compile(
    TIME_SPAN.pattern + r'(?:\s*[｜|]\s*.+)?'
)
STORY_NUMBER = re.compile(r'第([一二三四五六七八九十\d]+)段')
TARGET_RULE = re.compile(
    r'^第(?P<a>[一二三四五六七八九十\d]+)'
    r'(?:[、,，及與和]\s*第?(?P<b>[一二三四五六七八九十\d]+))?段'
)
LAST_SECONDS = re.compile(r'^最後\s*\d+(?:\.\d+)?\s*秒')
FINAL_EVENT = re.compile(r'最後(?:以|在|由|才|完成|進行|出現|唱|一段|一句|謝幕)')
SENTENCES = re.compile(r'(?<=[。！？!?；;])\s+')
CHINESE = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}


def _number(s):
    if s.isdigit():
        return int(s)
    return CHINESE.get(s)


def _seconds(clock):
    if not re.match(r'\d', clock):
        return AUDIO_END_SECONDS
    units = clock.split(':')
    seconds = float(units[-1])
    if len(units) > 1:
        seconds += int(units[-2])*60
    if len(units) > 2:
        seconds += int(units[-3])*3600
    return seconds


def _clean_line(raw):
    line = raw.strip()
    if not line or line in ('---', '——', '━━━━━━━━━━━━━━━━━━', '**', '***'):
        return ''
    line = re.sub(r'^[-*]\s+', '', line)
    line = re.sub(r'^\*\*(.*?)\*\*$', r'\1', line)
    line = line.strip('* ').strip()
    return line



# Plain Chinese screenplay headings commonly put "時間：" on the NEXT line,
# rather than inside a Markdown heading. Treat that as a real author clock.
_NEXT_LINE_CHAPTER = re.compile(
    r'^(?:#{1,6}\s*)?(?:第[一二三四五六七八九十百零〇\d]+[段幕]|'
    r'CHAPTER\s+\d+|SEGMENT\s+\d+|ACT\s+\d+)\s*[｜|:：\-—].+', re.I)
_NEXT_LINE_CLOCK = re.compile(r'^時間\s*[：:]\s*', re.I)
_QUOTED_LYRIC = re.compile(r'「([^」]+)」|“([^”]+)”')
_INLINE_CLOCK = re.compile(r'(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?')
# Storyboard authors often put 00:17.813: on a separate line, followed by
# the first visible action. Anchor that action without adding a fake shot.
_CLOCK_MARKER = re.compile(
    r'^(?P<clock>\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)[：:]?$'
)
_CLOCK_PREFIX = re.compile(
    r'^\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?[：:]\s*\S'
)
_AT_CLOCK = re.compile(
    r'\bat\s+\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\b',re.I
)


def _lift_next_line_chapter_times(prompt):
    """Translate chapter + next-line time syntax into canonical timed headings."""
    raw = prompt.replace('\r\n','\n').splitlines()
    out=[];skip=set()
    for i,line in enumerate(raw):
        if i in skip:continue
        clean=line.strip()
        if _NEXT_LINE_CHAPTER.fullmatch(clean) and not TIME_SPAN.search(clean):
            next_idx=next((j for j in range(i+1,len(raw)) if raw[j].strip()),None)
            if next_idx is not None:
                clock_line=raw[next_idx].strip()
                # Only ACT headings accept an otherwise bare time-only next line.
                # Existing chapter and short-film parsing keeps its old contract.
                clock=(TIME_SPAN.search(clock_line) if _NEXT_LINE_CLOCK.match(clock_line)
                       else TIME_SPAN.fullmatch(clock_line)
                       if re.match(r'^ACT\s+\d+\b',clean,re.I) else None)
                if clock and not clock_line[clock.end():].strip():
                    title=re.sub(r'^#{1,6}\s*','',clean)
                    out.append('### '+title+'｜'+clock.group())
                    skip.add(next_idx)
                    continue
        out.append(line)
    return '\n'.join(out)


def _lyric_key(value):
    value=re.sub(r'\[\s*S[1-8](?:\s*\+\s*S[1-8])*\s*\]','',value,flags=re.I)
    return re.sub(r'[^\w\u3400-\u9fff]+','',value,flags=re.U).lower()


def _line_cue_times(line, chapter, srt, after):
    """Return SRT cue starts actually named by this specific action line."""
    phrases=[a or b for a,b in _QUOTED_LYRIC.findall(line)]
    times=[]
    for phrase in phrases:
        key=_lyric_key(phrase)
        if not key:continue
        candidates=[]
        for cue in srt:
            if not isinstance(cue,dict):continue
            try:start=float(cue['start'])
            except (ValueError,TypeError,KeyError):continue
            if start < chapter['start']-.250 or start >= chapter['end']+.001:
                continue
            label=_lyric_key(str(cue.get('text','')))
            if key==label or (len(key)>=6 and key in label):
                candidates.append(start)
        next_time=next((t for t in candidates if t >= after-.050),None)
        if next_time is not None:
            times.append((phrase,next_time))
            after=next_time
    return times


def _timed_action_events(chapter,srt):
    """Anchor quoted lyric events to SRT; interpolate only untimed actions.

    A single source action that mentions later lyrics is split by its quoted
    lyric boundaries so no future lyric text is exposed in an earlier clip.
    """
    source=[]
    last_srt=chapter['start']
    pending_clock=None
    for line in chapter['actions']:
        standalone=_CLOCK_MARKER.fullmatch(line.strip())
        if standalone:
            pending_clock=_seconds(standalone['clock'])
            continue
        matches=_line_cue_times(line,chapter,srt,last_srt)
        if len(matches)>1:
            quotes=list(_QUOTED_LYRIC.finditer(line))
            previous_end=0
            for k,(phrase,stamp) in enumerate(matches):
                quote=next((m for m in quotes if (m[1] or m[2])==phrase and m.end()>previous_end),None)
                if quote is None:continue
                fragment=line[previous_end:quote.end()].strip(' ，,、;；')
                previous_end=quote.end()
                if k and not re.search(r'唱|對嘴|lip.sync',fragment,re.I):
                    fragment='依照 SRT 接唱'+fragment
                source.append([fragment,stamp])
            if quotes and previous_end<len(line):
                remaining=line[previous_end:].strip(' ，,、;；')
                if remaining:
                    source.append([remaining,None])
            last_srt=matches[-1][1]
        else:
            explicit=_INLINE_CLOCK.search(line)
            stamp=matches[0][1] if matches else pending_clock
            pending_clock=None
            # Preserve the author's exact entrance and cue timestamps. A
            # standalone timestamp governs the NEXT action; a leading 00:19:
            # or a sentence saying "at 00:17.813" governs that action.
            if stamp is None and explicit and (
                    TIME_SPAN.match(line) or _CLOCK_PREFIX.match(line)
                    or _AT_CLOCK.search(line)
                    or re.search(r'起|開始|切入|轉入', line)):
                stamp=_seconds(explicit.group())
            if stamp is not None:
                stamp=max(chapter['start'],min(chapter['end']-.0001,stamp))
                last_srt=max(last_srt,stamp)
            source.append([line,stamp])
    if not source:return []
    anchors=[(-1,chapter['start'])]
    for i,(_,stamp) in enumerate(source):
        if stamp is not None:anchors.append((i,stamp))
    anchors.append((len(source),chapter['end']))
    for (left,a),(right,b) in zip(anchors,anchors[1:]):
        # Source event clocks must progress, never jump to a future act.
        b=max(a,b)
        for i in range(left+1,right):
            fraction=(i-left)/(right-left)
            source[i][1]=a+(b-a)*fraction
    return [(line,max(chapter['start'],min(chapter['end']-.0001,stamp)))
            for line,stamp in source]



def parse_timed_source(prompt, *, authored_intervals=False):
    """Return (fixed_setup, timed_chapters) or None for legacy non-timed briefs.

    A time-coded heading starts a scene. In authored scripts, plain CHAPTER
    and SEGMENT markers also start scenes, and plain section titles close them. Unscoped metadata remains global, except ordinal-specific constraints,
    which are attached only to the corresponding scene(s), avoiding future leak.
    """
    fixed = []
    chapters = []
    current = None
    current_level = 0
    interval = None
    for raw in _lift_next_line_chapter_times(prompt).splitlines():
        line = raw.strip()
        if not line or line in ('---', '——', '━━━━━━━━━━━━━━━━━━'):
            continue
        heading = HEADING.match(line)
        bracket_span = False
        bracket = re.fullmatch(r'【([^】]+)】\s*[：:]?', line) if authored_intervals else None
        if bracket:
            title = bracket[1].strip()
            timed_title = BRACKET_TIMED_TITLE.fullmatch(title)
            if timed_title:
                if current is None or 'bracket_span' in current:
                    bracket_span = True
                    line = '### ' + title
                    heading = HEADING.match(line)
                else:
                    line = TIME_SPAN.match(title).group()
            elif PLAIN_SECTION.fullmatch(title) or AUTHORED_SECTION.fullmatch(title):
                line = '## ' + title
                heading = HEADING.match(line)
        # Story synopsis / concluding director intention is context, never an ACT.
        # Use explicit section titles instead of attempting semantic plot review.
        section_title = (heading.group('title') if heading else line).strip().rstrip('：:')
        if chapters and section_title in ('故事大綱', '劇情大綱',
                                          '最終導演意圖', '導演意圖'):
            current = None
            interval = None
            fixed.append(line)
            continue
        plain_scene = bool(
            PLAIN_SCENE.match(line) and TIME_SPAN.search(line)
            and (authored_intervals or _TIMED_ACT_SCENE.match(line))
        )
        plain_section = bool(
            (authored_intervals and (PLAIN_SECTION.fullmatch(line) or
                PLAIN_CONTROL.fullmatch(line) or AUTHORED_SECTION.fullmatch(line)))
            or _DIRECTOR_SECTION.fullmatch(line)
            or (_POST_ACT_SECTION.fullmatch(line) and
                any(_TIMED_ACT_SCENE.match(chapter['title']) for chapter in chapters))
        )
        if heading or plain_scene or plain_section:
            title = heading.group('title').strip() if heading else line
            level = len(heading.group('marks')) if heading else (3 if plain_scene else 2)
            timed = TIME_SPAN.search(title)
            if timed and not plain_section and (STORY_NUMBER.search(title) or '段' in title or '幕' in title or level >= 2):
                start, end = _seconds(timed.group('begin')), _seconds(timed.group('end'))
                if not 0 <= start < end:
                    raise ValueError(f'劇情段落時間不正確：{title}')
                number = STORY_NUMBER.search(title)
                current = {'title': title, 'actions': [], 'start':start, 'end':end,
                           'ordinal':_number(number.group(1)) if number else None,
                           'constraints':[]}
                if bracket_span:
                    current['bracket_span'] = True
                chapters.append(current)
                interval = None
                current_level = level
                continue
            if (heading and authored_intervals and current is not None and level == current_level
                    and re.match(r'^CHAPTER\s+\d+', current['title'], re.I)
                    and not current['actions'] and interval is None
                    and not current['constraints']):
                current['constraints'].append(title)
                continue
            if current is None or level <= current_level:
                current = None
                interval = None
                fixed.append(line)
            else:
                # A nested subheading inside a scene labels staging, not an action.
                current['constraints'].append(title)
            continue
        cleaned = _clean_line(line)
        if not cleaned:
            continue
        if current is None:
            fixed.append(cleaned)
        else:
            timed_body = TIME_SPAN.fullmatch(cleaned) if authored_intervals else None
            if timed_body:
                start, end = _seconds(timed_body.group('begin')), _seconds(timed_body.group('end'))
                if not current['start'] <= start < end <= current['end']:
                    raise ValueError(f'章內時間碼超出章節範圍：{cleaned}')
                intervals = current.setdefault('intervals', [])
                if intervals and start < intervals[-1]['end']:
                    raise ValueError(f'章內時間碼重疊或順序錯誤：{cleaned}')
                interval = {'start': start, 'end': end, 'actions': []}
                intervals.append(interval)
                continue
            actions = [text for text in SENTENCES.split(cleaned) if text]
            current['actions'].extend(actions)
            if interval is not None:
                interval['actions'].extend(actions)
    if not chapters:
        return None
    if any(not chapter['actions'] for chapter in chapters):
        raise ValueError('標記時間的故事段落缺少事件內容，請檢查全咒。')

    retained = []
    for line in fixed:
        if (LAST_SECONDS.match(line) or FINAL_EVENT.search(line) or
                authored_intervals and re.match(r'^(?:最後畫面|FINAL HARD STOP|夕陽告別)', line, re.I)):
            # Keep user-authored finale notes out of earlier clips.
            last = chapters[-1]
            if last.get('intervals'):
                last['intervals'][-1].setdefault('closing_notes', []).append(line)
            else:
                last['constraints'].append(line)
            continue
        match = TARGET_RULE.match(line)
        target_numbers = set()
        if match:
            target_numbers = {_number(match.group('a'))}
            if match.group('b'):
                target_numbers.add(_number(match.group('b')))
        matched = [chapter for chapter in chapters if chapter['ordinal'] in target_numbers]
        if matched:
            for chapter in matched:
                chapter['constraints'].append(line)
        else:
            retained.append(line)
    expanded = []
    for chapter in chapters:
        if 'intervals' not in chapter:
            expanded.append(chapter)
            continue
        # Preface and headings give context. Narrative starts at its explicit timestamp.
        for item in chapter['intervals']:
            if item['actions']:
                expanded.append({**chapter, **item, 'constraints':
                                 chapter['constraints'] + item.get('closing_notes', [])})
    return '\n'.join(retained), expanded or chapters


def _srt_safe_action(action):
    """Omit copied whole-verse lyrics; keep timed action lines with short cues."""
    if re.fullmatch(r'「[^」]*」|“[^”]*”', action.strip()):
        return ''
    return action


def _last_narrative(actions, previous):
    for line in reversed(actions):
        if not re.match(r'^(?:攝影機|鏡頭|機位|鏡位|運鏡|畫面|配樂|音效|此動作|本段拍攝|本段時間)', line):
            return line
    return previous


def allocate_authored_cues(chapters, segments):
    """Package authored cues on the clip clock, keeping actions in source order."""
    rows = []
    for segment in segments:
        start = segment['start']
        end = start + segment['seconds']
        cues = []
        for chapter in chapters:
            cue_start, cue_end = chapter['start'], chapter['end']
            begin, finish = max(start, cue_start), min(end, cue_end)
            if finish - begin <= 1e-6:
                continue
            actions = chapter['actions']
            duration = cue_end - cue_start
            # When there are no inner timestamps, estimate where action lines
            # fall within their authored cue by the elapsed fraction.
            first = int(len(actions) * (begin - cue_start) / duration + 1e-8)
            last = int(len(actions) * (finish - cue_start) / duration + 1e-8)
            local = actions[first:last]
            if not local:
                local = ['延續目前的動作與運鏡。']
            if finish >= cue_end - 1e-6:
                local = [*local, *chapter['constraints']]
            cues.append(f'{begin-start:.3f}–{finish-start:.3f} 秒\n' + '\n'.join(local))
        rows.append('\n\n'.join(cues) or '延續已建立的場景、動作與運鏡。')
    return rows


def allocate_timed_chapters(chapters, segments, commission, srt_cues=None):
    """Map time-anchored scenes onto exact audio slots (including transitions).

    commission is the existing local 9B handoff writer, unmodified. No future
    scene content is passed to earlier slots.
    """
    audio_end = segments[-1]['start']+segments[-1]['seconds'] if segments else 0.0
    for chapter in chapters:
        if chapter['end'] >= AUDIO_END_SECONDS:
            chapter['end'] = max(audio_end, chapter['start'])   # 「音源結束」＝實際曲尾
    overlaps = []
    for chapter in chapters:
        matches = [i for i, segment in enumerate(segments)
                   if min(chapter['end'], segment['start']+segment['seconds'])
                   - max(chapter['start'], segment['start']) > 1e-6]
        overlaps.append(matches)
    allocated = []
    previous = ''
    # Anchor the chapter's own lyric-identified actions to their real SRT
    # times. Other chapters without lyric evidence retain legacy pacing.
    srt_cues=srt_cues or []
    aligned=[_timed_action_events(chapter,srt_cues)
             if srt_cues and any(
                 TIME_SPAN.match(action) or
                 _line_cue_times(action,chapter,srt_cues,chapter['start'])
                 for action in chapter['actions']) else None
             for chapter in chapters]
    for i, segment in enumerate(segments):
        fragments = []
        clip_start = segment['start']
        clip_end = clip_start+segment['seconds']
        for chapter, matches in zip(chapters, overlaps):
            if i not in matches:
                continue
            phase = matches.index(i)
            begin = max(chapter['start'], clip_start)-clip_start
            end = min(chapter['end'], clip_end)-clip_start
            aligned_events=aligned[chapters.index(chapter)]
            if aligned_events is not None:
                # Supplied SRT already carries the authoritative lyrics. Do not
                # ship whole multi-line verses to a clip-local cinematographer.
                chosen=[(_srt_safe_action(action),stamp) for action,stamp in aligned_events
                        if clip_start-1e-6 <= stamp < clip_end-1e-6]
                chosen=[(action,stamp) for action,stamp in chosen if action]
                local=[action for action,_ in chosen]
                assigned='PYTHON-OWNED CURRENT EVENT — scene '+chapter['title']+'\n'
                if previous:
                    assigned+='ALREADY ESTABLISHED (do not replay): '+previous+'\n'
                assigned+='Current interval actions (at their actual source-song times):\n'
                assigned+='\n'.join(f'- @{stamp-clip_start:.3f}s '+action
                                    for action,stamp in chosen) if chosen else (
                    'Continue established acting and staging inside this scene; '
                    'no future lyric/event may be performed yet.')
                if chosen:previous=_last_narrative(local,previous)
            else:
                assigned, _ = commission(chapter, phase, len(matches), previous)
                size = len(chapter['actions'])
                first = phase*size//len(matches)
                last = (phase+1)*size//len(matches)
                local = chapter['actions'][first:last]
                previous = _last_narrative(local, previous)
            fragments.append(
                'USER-SPECIFIED SONG TIME — this chapter is assigned to '
                f'{chapter["start"]:.3f}–{chapter["end"]:.3f}s source time; '
                f'its active time inside THIS clip is {begin:.3f}–{end:.3f}s. '
                'Follow its action order; do not film future chapters early.\n'
                + assigned
                + ('\nConstraints for THIS chapter only (not extra events):\n'
                   + '\n'.join('- '+note for note in chapter['constraints'])
                   if chapter['constraints'] else '')
            )
        if not fragments:
            fragments = [
                'PYTHON-OWNED SOURCE INTERVAL — no explicitly timed story event '
                'was allocated here. Maintain the established scene and continue '
                'the ongoing performance; do not pull a future timed event forward.'
                + ('\nALREADY ESTABLISHED: '+previous if previous else '')
            ]
        allocated.append('\n\n'.join(fragments))
    return allocated
