"""Python-owned chronological clip slots, with one native 9B filming call per clip.

No LLM runs here. Python owns decoded-audio segment boundaries, ordered source
actions, stable references, saved plans and short-tail continuity. It does not
infer narrative meaning from loudness or fabricate a complete story.
"""
import json
import math
import re
from pathlib import Path

from banana_mv.core import map_image_mentions, normalize_mv_prompt
from banana_mv.director import MODES
from banana_mv.mv_scope import ending_contract
from banana_mv.scene_state import SceneStateError, atomic_json, digest
from banana_mv.timed_slots import parse_timed_source, allocate_timed_chapters


CHAPTER = re.compile(
    r'^\s*(?:第[一二三四五六七八九十百零〇\d]+[幕段]|終幕|尾聲|'
    r'ACT\s+\d+|FINALE)\s*[|｜:：\-—]\s*(.+)$', re.I)
GLOBAL_RULES = re.compile(r'^\s*(?:全曲執行原則|GLOBAL\s+RULES|全曲固定原則)\s*$', re.I)
SENTENCES = re.compile(r'(?<=[。！？!?；;])\s*')


# Normalize presentation syntax only when the brief has identifiable story sections.
SECTION_PREFIX = re.compile(r'^(?:(?:\d+|[一二三四五六七八九十]+)\s*[｜|、.．:：\-—]\s*)?')
SECTION_STORY = frozenset(('故事內容', '故事劇情', '劇情內容', '故事大綱', '劇情大綱', '劇本內容', 'MV 故事'))
SECTION_SETUP = frozenset(('角色設定', '人物設定', '人物介紹', '角色介紹', '人物',
                           '角色綁定', 'MV 主題', '主題', '風格', '世界觀', '場景設定',
                           '演唱與劇情安排', '演唱與攝影', '演唱安排', '劇情連續性',
                           '特殊要求', '攝影與舞蹈', '導演自由發揮', '全曲執行原則',
                           '全曲固定原則', 'GLOBAL RULES'))
MARKDOWN_HEADING = re.compile(r'^\s{0,3}#{1,6}\s+')


def _plain_source_line(original):
    """Remove visual Markdown without discarding the text that follows it."""
    line = original.strip()
    if not line or re.fullmatch(r'(?:-{3,}|\*{3,}|_{3,}|━{3,}|\x60{3,}.*)', line):
        return ''
    line = re.sub(r'^\s{0,3}#{1,6}\s+', '', line)
    line = re.sub(r'^>\s*', '', line)
    line = re.sub(r'^[-*+]\s+', '', line)
    line = re.sub(r'^\d+[.)]\s+', '', line)
    line = re.sub(r'\*\*(.+?)\*\*|__(.+?)__',
                  lambda m: m.group(1) or m.group(2), line)
    return line.strip()


def _source_section(line):
    title = SECTION_PREFIX.sub('', line).strip().rstrip('：:').strip()
    if title in SECTION_STORY:
        return 'story', title
    if title in SECTION_SETUP:
        return 'setup', title
    return None, title


def _sectioned_source(prompt):
    """Separate sectioned briefs into setup and source chapters before allocation.

    Both Markdown and plain-text numbered headings are valid. This adapter
    makes no slot, event-timing or narrative decisions.
    """
    raw_lines = prompt.replace('\r\n', '\n').splitlines()
    lines = [(_plain_source_line(line), bool(MARKDOWN_HEADING.match(line)))
             for line in raw_lines]
    has_story_section = any(_source_section(line)[0] == 'story'
                            for line, _ in lines if line)
    has_new_chapter = any(CHAPTER.match(line) and
                          (md or re.match(r'^第[一二三四五六七八九十百零〇\d]+段', line))
                          for line, md in lines if line)
    if not has_story_section and not has_new_chapter:
        return None
    fixed, chapters = [], []
    in_story = not has_story_section
    current = None
    for line, markdown_heading in lines:
        if not line:
            continue
        kind, title = _source_section(line)
        if kind == 'story':
            in_story = True
            current = None
            continue
        if kind == 'setup':
            in_story = False
            current = None
            fixed.append(title + '：')
            continue
        if CHAPTER.match(line) and in_story:
            current = {'title': line, 'actions': []}
            chapters.append(current)
            continue
        if markdown_heading:
            # Other headings are labels, never filmable actions.
            if not in_story:
                fixed.append(line)
            continue
        if in_story:
            if current is None:
                current = {'title': 'User story', 'actions': []}
                chapters.append(current)
            current['actions'].extend(x.strip() for x in SENTENCES.split(line) if x.strip())
        else:
            fixed.append(line)
    chapters = [chapter for chapter in chapters if chapter['actions']]
    if not chapters:
        return None
    return '\n'.join(fixed), chapters


# Opt-in, deterministic physical wardrobe ledger. No 9B call or story inference.
WARDROBE_KINDS = (
    ('Torso', re.compile(r'馬甲|胸衣|抹胸|上衣|襯衫|背心|皮衣|外套|夾克|制服|T恤|胸罩|內衣', re.I)),
    ('Bottom', re.compile(r'內褲|短褲|長褲|裙|泳褲|褲子|褲', re.I)),
    ('Feet', re.compile(r'高跟|舞鞋|鞋|靴|襪', re.I)),
)
SCOPE_NOTE = re.compile(r'^(?:本段|此段|這段|本章|此章)(?:只|僅|完成|保留|維持|建立)(?=.|$)')
REMOVAL = re.compile(r'卸除|脫下|脫掉|脫去|摘下|取下|移除|拿掉|褪下')
UNFASTEN = re.compile(r'解開|解扣|鬆開')
DRESS = re.compile(r'穿上|重新穿上|穿回|戴上|重新戴上|換上')


def _opening_actor_state(fixed, chapters):
    """Use only explicitly declared opening wardrobe, never future synopsis."""
    state = {}
    taking = False
    for raw in fixed.splitlines():
        line = raw.strip().lstrip('-* ').strip()
        opener = re.match(r'^(?:開場穿著|初始穿著|初始服裝|開場服裝)\s*[:：]\s*(.*)$', line)
        if opener:
            taking = True
            line = opener.group(1).strip()
        elif taking and (not line or line.endswith(('：', ':'))):
            taking = False
        elif taking and re.match(r'^(?:服裝隨|已卸除|不重新|人物|整體|故事|演唱)', line):
            taking = False
        if not taking or not line:
            continue
        for kind, pattern in WARDROBE_KINDS:
            if pattern.search(line):
                state[kind] = {'label': line, 'status': 'worn'}
    if not state and chapters and chapters[0]['actions']:
        first = chapters[0]['actions'][0]
        if re.search(r'穿著|身穿|穿上|佩戴', first):
            for kind, pattern in WARDROBE_KINDS:
                match = pattern.search(first)
                if match:
                    state[kind] = {'label': match.group(), 'status': 'worn'}
    return state


def _local_filmed_actions(commission_text):
    """Read this clip's action bullets only, not history or chapter annotations."""
    active = False
    for line in commission_text.splitlines():
        if line.startswith('Current interval actions in original order:'):
            active = True
            continue
        if line.startswith('Stage these actions'):
            active = False
        if active and line.startswith('- '):
            action = line[2:].strip()
            if not SCOPE_NOTE.match(action):
                yield action
        elif not active and line.startswith('- ') and ' | ' in line and 'Current interval actions' not in commission_text:
            action = line.split(' | ', 1)[1].strip()
            if not SCOPE_NOTE.match(action):
                yield action


def _advance_actor_state(state, action):
    """Advance from explicit local events; never infer changes from future plot."""
    if SCOPE_NOTE.match(action):
        return
    if re.search(r'上身裸露|上身赤裸|裸露上身|赤裸上身', action) and 'Torso' in state:
        state['Torso']['status'] = 'removed'
    if '全裸' in action or '一絲不掛' in action:
        for kind in ('Torso', 'Bottom'):
            if kind in state:
                state[kind]['status'] = 'removed'
    if re.search(r'赤腳|赤足|光腳', action) and 'Feet' in state:
        state['Feet']['status'] = 'removed'
    for kind, pattern in WARDROBE_KINDS:
        if kind not in state or not pattern.search(action):
            continue
        if REMOVAL.search(action) or (UNFASTEN.search(action) and re.search(r'完成.*(?:服裝變化|卸除|脫除)', action)):
            state[kind]['status'] = 'removed'
        elif UNFASTEN.search(action):
            state[kind]['status'] = 'unfastened'
        elif DRESS.search(action):
            state[kind]['status'] = 'worn'


def _actor_state_lines(state):
    lines = []
    for kind in ('Torso', 'Bottom', 'Feet'):
        if kind not in state:
            continue
        item = state[kind]
        if item['status'] == 'removed':
            label = 'Barefoot' if kind == 'Feet' else 'Bare'
            lines.append(f'- {kind}: {label}; {item["label"]} already removed, stays off.')
        elif item['status'] == 'unfastened':
            lines.append(f'- {kind}: {item["label"]} unfastened (transitional, not reset).')
        else:
            lines.append(f'- {kind}: {item["label"]} worn.')
    return '\n'.join(lines)


def _inject_actor_state(events, fixed, chapters):
    """Carry the actual planned before/after state through every local slot."""
    state = _opening_actor_state(fixed, chapters)
    if not state:
        return events
    out = []
    for event in events:
        before = _actor_state_lines(state)
        for action in _local_filmed_actions(event):
            _advance_actor_state(state, action)
        after = _actor_state_lines(state)
        out.append('CURRENT_ACTOR_STATE (at clip start; authoritative over opening wardrobe in fixed references):\n'
                   + before + '\nEXPECTED_ACTOR_STATE_AFTER_THIS_CLIP (planned consequence):\n'
                   + after + '\nOnly the assigned actions below may change this state. '
                   'Do not put back removed items, even when a reference image or global setup shows them. '
                   'Do not replay an already completed event.\n\n' + event)
    return out

def split_source(prompt):
    """Return fixed references and chaptered plot in original user order.

    Headed source is split at original chapter boundaries. Unheaded source
    remains source material; only unambiguous image binding lines are fixed.
    Global rules after '全曲執行原則' remain fixed, never plotted as action.
    """
    sectioned = _sectioned_source(prompt)
    if sectioned is not None:
        return sectioned
    baseline, rules, chapters = [], [], []
    current = None
    in_rules = False
    for original in prompt.replace('\r\n', '\n').splitlines():
        line = original.strip()
        if not line or line in ('---', '——', '━━━━━━━━━━━━━━━━━━'):
            continue
        if GLOBAL_RULES.fullmatch(line):
            in_rules = True
            continue
        match = CHAPTER.match(line)
        if match and not in_rules:
            current = {'title': line, 'actions': []}
            chapters.append(current)
            continue
        if in_rules:
            rules.append(line)
        elif current is None:
            baseline.append(line)
        else:
            current['actions'].extend(x.strip() for x in SENTENCES.split(line) if x.strip())
    if chapters:
        fixed = '\n'.join(baseline + rules)
    else:
        fixed_lines, loose_actions = [], []
        for line in baseline:
            if re.match(r'^(?:@圖片\d+|<Picture \d+>|角色綁定\s*$)', line):
                fixed_lines.append(line)
            else:
                loose_actions.extend(x.strip() for x in SENTENCES.split(line) if x.strip())
        fixed = '\n'.join(fixed_lines + rules)
        chapters = [{'title': 'User story', 'actions': loose_actions}]
    chapters = [c for c in chapters if c['actions']]
    if not chapters:
        raise SceneStateError('Python 分段沒有找到具體事件；請在提示詞中描述故事或演出動作。')
    return fixed, chapters


def span_counts(chapters, slots):
    """At least one slot per chapter when possible; allocate the rest by weight."""
    if not chapters or slots <= 0:
        raise ValueError('分段數量不正確。')
    if len(chapters) > slots:
        return None  # Chapters are merged chronologically, not dropped.
    counts = [1] * len(chapters)
    left = slots - len(chapters)
    weights = [math.sqrt(max(1, len(c['actions']))) for c in chapters]
    total = sum(weights)
    raw = [left*w/total for w in weights]
    bases = [int(v) for v in raw]
    counts = [a+b for a,b in zip(counts, bases)]
    remain = left-sum(bases)
    order = sorted(range(len(chapters)), key=lambda j: (-(raw[j]-bases[j]), j))
    for j in order[:remain]:
        counts[j] += 1
    return counts


def mode_for(event, req):
    user_mode = req.get('director', 'auto')
    if user_mode != 'auto' and user_mode in MODES:
        return user_mode
    if re.search(r'唱|歌|RAP|舞台|主唱|副歌|SING|VOCAL|CHORUS', event, re.I):
        return 'performance'
    if re.search(r'拳|戰|打|擊|爆炸|追逐|衝刺|FIGHT|BOX|EXPLODE', event, re.I):
        return 'action'
    if re.search(r'變身|法術|魔法|幻影|量子|MAGIC', event, re.I):
        return 'fantasy'
    return 'story'


def commission(chapter, chapter_slot, chapter_slots, previous):
    """Split actions by order; avoid copying the entire act to every slot."""
    # Scope notes describe already-achieved results, not filmable actions.
    actions = [action for action in chapter['actions'] if not SCOPE_NOTE.match(action)]
    size = len(actions)
    begin = (chapter_slot*size)//chapter_slots
    end = ((chapter_slot+1)*size)//chapter_slots
    local = actions[begin:end]
    if not local:
        local = [
            'Develop fresh anticipation, environmental interaction and character '
            'behavior within this chapter without performing its NEXT listed '
            'turning point. Keep the current causal state advancing.'
        ]
    instructions = [
        'PYTHON-OWNED SOURCE INTERVAL — film ONLY this local commission.',
        'Source chapter: '+chapter['title'],
        'Phase inside chapter: '+str(chapter_slot+1)+' of '+str(chapter_slots)+'.',
    ]
    if previous:
        instructions.append('ALREADY ESTABLISHED; do not restage or repeat: '+previous)
    instructions.extend([
        'Current interval actions in original order:',
        *('- '+action for action in local),
        'Stage these actions with physical cause, response and visible consequence.',
        'Carry resulting positions, props and emotions forward; no future chapter, '
        'premature victory, repeated finale or arbitrary reset.',
    ])
    # Handoff the last character event, not a camera move or a chapter note.
    previous_result = next((action for action in reversed(local)
                            if not re.match(r'^(?:攝影機|鏡頭|機位|運鏡|畫面)', action)),
                           previous)
    return '\n'.join(instructions), previous_result


def ensure_python_slot_plan(req, segments, originals, work):
    """Save a deterministic 1:1 plan. Calls no rewrite/model/backend service."""
    if not segments:
        raise SceneStateError('缺少歌曲分段。')
    count = len(originals)
    brief = map_image_mentions(req.get('prompt', ''), count)
    contract = ending_contract(req, segments[-1]['start']+segments[-1]['seconds'], segments)
    task = {
        'format': 'python_owned_slots_v1',
        'brief': brief,
        'style': req.get('director', 'auto'),
        'adaptation': 'FREE' if req.get('story_plan', True) else 'FAITHFUL',
        'timeline': [{k:s[k] for k in ('index', 'start', 'seconds')} for s in segments],
        'ending_contract': contract,
    }
    fingerprint = digest(task)
    path = Path(work)/'director_plan.json'
    if path.is_file():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if (saved.get('version') != 6 or saved.get('input_sha256') != fingerprint or
                saved.get('content_sha256') != digest({
                    k:v for k,v in saved.items()
                    if k not in ('content_sha256', 'input_sha256')})):
            raise SceneStateError('實驗版 Python 槽位與保存的丹方不一致；不覆蓋原始計畫。')
        return saved

    # Explicit Markdown chapter timestamps outrank text-count allocation.
    # Preserve the proven legacy allocator for non-timecoded source scripts.
    timed = parse_timed_source(brief)
    fixed, chapters = timed if timed is not None else split_source(brief)
    fixed = normalize_mv_prompt(fixed, count) if fixed else ''
    short_tail = (timed is None and bool(contract.get('short_tail_seconds', 0))
                  and len(segments)>1)
    usable = len(segments)-int(short_tail)
    counts = span_counts(chapters, usable) if timed is None else None
    allocated = []
    previous = ''
    if timed is not None:
        allocated = allocate_timed_chapters(chapters, segments, commission)
    elif counts is not None:
        for chapter, slots in zip(chapters, counts):
            for j in range(slots):
                event, previous = commission(chapter, j, slots, previous)
                allocated.append(event)
    else:
        # Very short excerpts with more source chapters than technical slots:
        # merge adjacent source chapters into the available slots without losing
        # user actions or reordering them.
        source = [(c['title'], a) for c in chapters for a in c['actions']]
        for i in range(usable):
            start = (i*len(source))//usable
            end = ((i+1)*len(source))//usable
            chunk = source[start:end]
            lines = ['PYTHON-OWNED SOURCE INTERVAL — film ONLY these actions.']
            if previous:
                lines.append('ALREADY ESTABLISHED; do not restage: '+previous)
            lines.extend('- '+title+' | '+action for title,action in chunk)
            previous = chunk[-1][1] if chunk else previous
            allocated.append('\n'.join(lines))
    if len(allocated) != usable:
        raise SceneStateError('Python 槽位未能覆蓋完整來源時間軸。')

    slot_events = list(allocated)
    if len(slot_events) < len(segments):
        slot_events.append('SOURCE SONG SHORT TAIL — continuation ONLY.\n'
                           'The previous full interval established the decisive outcome. '
                           'Sustain and develop its immediate visual consequence, never '
                           'replay the decisive event or introduce a new finale.\n'
                           'Previously established: '+previous)
    filmed_events = _inject_actor_state(slot_events, fixed, chapters)
    rows = []
    for seg, source_event, event in zip(segments, slot_events, filmed_events):
        rows.append({
            'index': seg['index'], 'mode': mode_for(source_event, req),
            'handoff_version': 1,
            'event': normalize_mv_prompt(event, count),
        })
    plan = {
        'version': 6,
        'engine': 'python_owned_slots_v1',
        'source_timing': 'explicit_markdown' if timed is not None else 'legacy_ordered',
        'shared_setup': fixed,
        'segments': rows,
        'visual_verified': False,
        'ending_contract': contract,
        'project_scope': req.get('project_scope', 'full'),
    }
    plan['content_sha256'] = digest(plan)
    plan['input_sha256'] = fingerprint
    atomic_json(path, plan)
    return plan
