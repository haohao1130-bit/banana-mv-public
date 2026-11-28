"""Route local activities, not lyrics, actor count, or whole-song genre.

The result selects optional director knowledge only, never a shot recipe
or an instruction to add an activity. No inference call.
"""
import re

# Specific activities outrank accompanying singing. A stage, beat, battle
# or a character's role alone is not evidence of dancing or fighting.
ACTIVITIES = {
    'dance': r'(?:舞蹈|跳舞|編舞|舞步|齊舞|群舞|領舞|流行舞|椅子舞|鋼管舞|熱舞)(?!的?(?:教室|工作室|學校|用品店|招牌|服|社團))|\bdanc(?:e|es|ing)\b(?!\s+(?:studio|school|classroom|sign|costume)\b)|\bchoreograph(?:y|ed|ic)\b|\bwaacking\b|\bvoguing\b|\bpopping\b|\block(?:ing)\b(?!\s+(?:the|a|an|his|her|their)\b)',
    'action': r'武打|打鬥|切磋|戰鬥|拳擊(?!手|選手|館|場|隊)|揮拳|出拳(?!擊)|拳腳|格鬥|格擋|搏鬥|攻防|交戰|\b(?:fight(?:ing|s)?|combat|boxing(?!\s+(?:gym|club|ring|gloves)\b)|martial arts|punch(?:es|ing)?|parry)\b',
    'band': r'樂團|吉他|鼓手|貝斯|彈琴|彈奏|敲鼓|演奏|\b(?:band|guitar(?:ist)?|drummer|bassist|instrumental performance|plays? the (?:drums|piano|guitar))\b',
    'chase': r'追逐|追趕|追捕|跑酷|飛車|逃跑|\b(?:chase|chasing|pursuit|parkour|flee(?:ing)?|pursu(?:e|es|ing))\b',
    'fantasy': r'魔法|法術|變身|召喚|施法|幻影|\b(?:magic|spell|transformation|summoning)\b',
    'horror': r'恐怖|驚悚|懸疑|詭異|\b(?:horror|suspense|haunted|eerie)\b',
    'comedy': r'搞笑|惡搞|爆笑|喜劇|一本正經胡說八道|\b(?:comedy|deadpan|comic gag)\b',
    'performance': r'演唱|唱歌|對唱|合唱|開唱|主唱|對嘴|饒舌|\b(?:sing(?:ing|s)?|sung|vocals?|lip[- ]?sync|rapp?ing|rap)\b',
}
_PATTERNS = {name: re.compile(pattern, re.I) for name, pattern in ACTIVITIES.items()}
_NEGATIVE = re.compile(r'(?:禁止|不要|不准|不需要|無需|沒有|不做|不再|停止|不|無)\s*(?:(?:任何|額外|進行|做|再)\s*)*\s*$|'
                       r'\b(?:no|not|never|without|avoid|exclude|do not|don.t)\s+(?:(?:any|more|do|perform)\s+)*$', re.I)


_ACTION_HEADER = re.compile(r'^Current interval actions[^:]*:', re.I)
_METADATA = re.compile(
    r'^\s*(?:ALREADY ESTABLISHED|Previously established|SOURCE SONG SHORT TAIL|'
    r'Source chapter:|Phase inside chapter:|【Python當前狀態|'
    r'Stage these actions|Carry resulting positions|USER-SPECIFIED SONG TIME|'
    r'PYTHON-OWNED|Constraints for THIS chapter only)', re.I)


def _activity_text(event):
    lines = str(event or '').splitlines()
    if lines and lines[0].startswith('CURRENT_ACTOR_STATE ('):
        # The generated wardrobe block precedes a blank line and the commission.
        lines = lines[lines.index('') + 1:] if '' in lines else []
    if any(_ACTION_HEADER.match(line) for line in lines):
        # Each timed chapter can supply its own action list in the same clip.
        bullets = []
        in_actions = False
        for line in lines:
            if _ACTION_HEADER.match(line):
                in_actions = True
            elif _METADATA.match(line):
                in_actions = False
            elif in_actions and line.strip():
                bullets.append(line.removeprefix('- '))
        return '\n'.join(bullets)
    return '\n'.join(line.split(' | ', 1)[-1] if line.startswith('- ') else line
                     for line in lines if not _METADATA.match(line))


def activity_signals(event):
    """Count positive activity clauses in the current commission."""
    scores, negative = {}, set()
    for clause in re.split(r'[，,。；;！!？?\n]|但是|而是|\bbut\b', _activity_text(event)):
        clause = re.sub(r'不要只|不只|不僅|not only', '', clause, flags=re.I)
        for mode, pattern in _PATTERNS.items():
            for match in pattern.finditer(clause):
                if _NEGATIVE.search(clause[:match.start()]):
                    negative.add(mode)
                else:
                    scores[mode] = scores.get(mode, 0) + 1
                    break
    return scores, negative - scores.keys()


def route_activity(event, requested='auto', fallback='story'):
    scores, excluded = activity_signals(event)
    if requested in (*ACTIVITIES, 'story') and requested not in excluded:
        return requested
    # Accompanying vocals never override a positively assigned specialist
    # activity. Choose among the specialist activities by local evidence.
    active = [mode for mode in ACTIVITIES if mode != 'performance' and scores.get(mode)]
    if active:
        return max(active, key=lambda mode: scores[mode])
    if scores.get('performance'):
        return 'performance'
    if fallback in (*ACTIVITIES, 'story') and fallback not in excluded:
        return fallback
    return 'story'


def select_mode(req, segment):
    """Use the same local classification for the writer and H3 workflow."""
    segment = segment or {}
    row = segment.get('director_plan') or {}
    planned = row.get('mode') or segment.get('director_mode') or 'story'
    if req.get('action_lora_scope') == 'segment' and planned in ('action', 'dance'):
        # A previously saved specialty alone is insufficient evidence to mount a LoRA.
        planned = 'story'
    return route_activity(row.get('event', ''), req.get('director', 'auto'), planned)
