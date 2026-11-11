"""Optional explicit-time Markdown story parsing for the local Python Slot branch.

User-authoritative scene times are mapped to song slots; metadata, cast and
cinematography instructions are not counted as narrative actions.
No model call, audio processing, or change to legacy chapter allocation.
"""
import re

HEADING = re.compile(r'^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$')
TIME_SPAN = re.compile(
    r'(?<!\d)(?P<begin>\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)'
    r'\s*[-–—－~～至]\s*'
    r'(?P<end>\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)'
)
STORY_NUMBER = re.compile(r'第([一二三四五六七八九十\d]+)段')
TARGET_RULE = re.compile(
    r'^第(?P<a>[一二三四五六七八九十\d]+)'
    r'(?:[、,，及與和]\s*第?(?P<b>[一二三四五六七八九十\d]+))?段'
)
LAST_SECONDS = re.compile(r'^最後\s*\d+(?:\.\d+)?\s*秒')
SENTENCES = re.compile(r'(?<=[。！？!?；;])\s+')
CHINESE = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}


def _number(s):
    if s.isdigit():
        return int(s)
    return CHINESE.get(s)


def _seconds(clock):
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


def parse_timed_source(prompt):
    """Return (fixed_setup, timed_chapters) or None for legacy non-timed briefs.

    Every time-coded Markdown heading starts a scene; a peer/higher heading ends
    it. Unscoped metadata remains global, except ordinal-specific constraints,
    which are attached only to the corresponding scene(s), avoiding future leak.
    """
    fixed = []
    chapters = []
    current = None
    current_level = 0
    for raw in prompt.replace('\r\n', '\n').splitlines():
        line = raw.strip()
        if not line or line in ('---', '——', '━━━━━━━━━━━━━━━━━━'):
            continue
        heading = HEADING.match(line)
        if heading:
            title = heading.group('title').strip()
            level = len(heading.group('marks'))
            timed = TIME_SPAN.search(title)
            if timed and (STORY_NUMBER.search(title) or '段' in title or '幕' in title or level >= 2):
                start, end = _seconds(timed.group('begin')), _seconds(timed.group('end'))
                if not 0 <= start < end:
                    raise ValueError(f'劇情段落時間不正確：{title}')
                number = STORY_NUMBER.search(title)
                current = {'title': title, 'actions': [], 'start':start, 'end':end,
                           'ordinal':_number(number.group(1)) if number else None,
                           'constraints':[]}
                chapters.append(current)
                current_level = level
                continue
            if current is None or level <= current_level:
                current = None
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
            current['actions'].extend(s for s in SENTENCES.split(cleaned) if s)
    if not chapters:
        return None
    if any(not chapter['actions'] for chapter in chapters):
        raise ValueError('標記時間的故事段落缺少事件內容，請檢查全咒。')

    retained = []
    for line in fixed:
        match = TARGET_RULE.match(line)
        target_numbers = set()
        if match:
            target_numbers = {_number(match.group('a'))}
            if match.group('b'):
                target_numbers.add(_number(match.group('b')))
        elif LAST_SECONDS.match(line):
            if chapters:
                target_numbers.add(chapters[-1]['ordinal'])
        matched = [chapter for chapter in chapters if chapter['ordinal'] in target_numbers]
        if matched:
            for chapter in matched:
                chapter['constraints'].append(line)
        else:
            retained.append(line)
    return '\n'.join(retained), chapters


def _last_narrative(actions, previous):
    for line in reversed(actions):
        if not re.match(r'^(?:攝影機|鏡頭|機位|鏡位|運鏡|畫面|配樂|音效|此動作|本段拍攝|本段時間)', line):
            return line
    return previous


def allocate_timed_chapters(chapters, segments, commission):
    """Map time-anchored scenes onto exact audio slots (including transitions).

    commission is the existing local 9B handoff writer, unmodified. No future
    scene content is passed to earlier slots.
    """
    overlaps = []
    for chapter in chapters:
        matches = [i for i, segment in enumerate(segments)
                   if min(chapter['end'], segment['start']+segment['seconds'])
                   - max(chapter['start'], segment['start']) > 1e-6]
        overlaps.append(matches)
    allocated = []
    previous = ''
    for i, segment in enumerate(segments):
        fragments = []
        clip_start = segment['start']
        clip_end = clip_start+segment['seconds']
        for chapter, matches in zip(chapters, overlaps):
            if i not in matches:
                continue
            phase = matches.index(i)
            assigned, _ = commission(chapter, phase, len(matches), previous)
            begin = max(chapter['start'], clip_start)-clip_start
            end = min(chapter['end'], clip_end)-clip_start
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
            size = len(chapter['actions'])
            first = phase*size//len(matches)
            last = (phase+1)*size//len(matches)
            local = chapter['actions'][first:last]
            previous = _last_narrative(local, previous)
        if not fragments:
            fragments = [
                'PYTHON-OWNED SOURCE INTERVAL — no explicitly timed story event '
                'was allocated here. Maintain the established scene and continue '
                'the ongoing performance; do not pull a future timed event forward.'
                + ('\nALREADY ESTABLISHED: '+previous if previous else '')
            ]
        allocated.append('\n\n'.join(fragments))
    return allocated
