"""Python-owned chronological clip slots, with one native 9B filming call per clip.

No LLM runs here. Python owns decoded-audio segment boundaries, ordered source
actions, stable references, saved plans and short-tail continuity. It does not
infer narrative meaning from loudness or fabricate a complete story.
"""
import math
import re
from pathlib import Path

from banana_mv.core import map_image_mentions, normalize_mv_prompt
from banana_mv.director import MODES
from banana_mv.mv_scope import ending_contract
from banana_mv.scene_state import SceneStateError, atomic_json, digest


CHAPTER = re.compile(
    r'^\s*(?:第[一二三四五六七八九十百零〇\d]+幕|終幕|尾聲|'
    r'ACT\s+\d+|FINALE)\s*[|｜:：\-—]\s*(.+)$', re.I)
GLOBAL_RULES = re.compile(r'^\s*(?:全曲執行原則|GLOBAL\s+RULES|全曲固定原則)\s*$', re.I)
SENTENCES = re.compile(r'(?<=[。！？!?；;])\s*')


def split_source(prompt):
    """Return fixed references and chaptered plot in original user order.

    Headed source is split at original chapter boundaries. Unheaded source
    remains source material; only unambiguous image binding lines are fixed.
    Global rules after '全曲執行原則' remain fixed, never plotted as action.
    """
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
    actions = chapter['actions']
    size = len(actions)
    begin = (chapter_slot*size)//chapter_slots
    end = ((chapter_slot+1)*size)//chapter_slots
    local = actions[begin:end]
    if not local:
        anchor = actions[min(begin, size-1)]
        local = [
            'Develop one NEW visual consequence or character reaction within this '
            'ongoing moment, without replaying its trigger: '+anchor
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
    return '\n'.join(instructions), local[-1]


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
        saved = __import__('json').loads(path.read_text(encoding='utf-8'))
        if (saved.get('version') != 6 or saved.get('input_sha256') != fingerprint or
                saved.get('content_sha256') != digest({
                    k:v for k,v in saved.items()
                    if k not in ('content_sha256', 'input_sha256')})):
            raise SceneStateError('實驗版 Python 槽位與保存的丹方不一致；不覆蓋原始計畫。')
        return saved

    fixed, chapters = split_source(brief)
    fixed = normalize_mv_prompt(fixed, count) if fixed else ''
    short_tail = bool(contract.get('short_tail_seconds', 0)) and len(segments)>1
    usable = len(segments)-int(short_tail)
    counts = span_counts(chapters, usable)
    allocated = []
    previous = ''
    if counts is not None:
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

    rows = []
    for i, seg in enumerate(segments):
        if i < usable:
            event = allocated[i]
        else:
            event = ('SOURCE SONG SHORT TAIL — continuation ONLY.\n'
                     'The previous full interval established the decisive outcome. '
                     'Sustain and develop its immediate visual consequence, never '
                     'replay the decisive event or introduce a new finale.\n'
                     'Previously established: '+previous)
        rows.append({
            'index': seg['index'], 'mode': mode_for(event, req),
            'handoff_version': 1,
            'event': normalize_mv_prompt(event, count),
        })
    plan = {
        'version': 6,
        'engine': 'python_owned_slots_v1',
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
