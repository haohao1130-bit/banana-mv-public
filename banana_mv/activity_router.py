"""Route local activities, not lyrics, actor count, or whole-song genre.

The result selects optional director knowledge only, never a shot recipe
or an instruction to add an activity. No inference call.
"""
import re

# Specific activities outrank accompanying singing. A stage, beat, battle
# or a character's role alone is not evidence of dancing or fighting.
ACTIVITIES = {
    'dance': r'舞蹈|跳舞|編舞|舞步|齊舞|群舞|領舞|流行舞|椅子舞|鋼管舞|熱舞|\bdanc(?:e|es|ing|ers?)\b|\bchoreograph(?:y|ed|ic)\b|\bwaacking\b|\bvoguing\b|\bpopping\b|\block(?:ing)\b',
    'action': r'武打|打鬥|切磋|戰鬥|拳擊|揮拳|出拳|拳腳|格鬥|格擋|搏鬥|攻防|交戰|\b(?:fight(?:ing|s)?|combat|boxing|martial arts|punch(?:es|ing)?|parry)\b',
    'band': r'樂團|吉他|鼓手|貝斯|彈琴|彈奏|敲鼓|演奏|\b(?:band|guitar(?:ist)?|drummer|bassist|instrumental performance|plays? the (?:drums|piano|guitar))\b',
    'chase': r'追逐|追趕|追捕|跑酷|飛車|逃跑|\b(?:chase|chasing|pursuit|parkour|flee(?:ing)?|pursu(?:e|es|ing))\b',
    'fantasy': r'魔法|法術|變身|召喚|施法|幻影|\b(?:magic|spell|transformation|summoning)\b',
    'horror': r'恐怖|驚悚|懸疑|詭異|\b(?:horror|suspense|haunted|eerie)\b',
    'comedy': r'搞笑|惡搞|爆笑|喜劇|一本正經胡說八道|\b(?:comedy|deadpan|comic gag)\b',
    'performance': r'演唱|唱歌|對唱|合唱|開唱|主唱|對嘴|饒舌|\b(?:sing(?:ing|s)?|sung|vocals?|lip[- ]?sync|rapp?ing|rap)\b',
}
_PATTERNS = {name: re.compile(pattern, re.I) for name, pattern in ACTIVITIES.items()}
_NEGATIVE = re.compile(r'(?:禁止|不要|不准|不需要|無需|沒有|不做|不再|停止|不|無)\s*(?:任何|額外|進行|再)?\s*$|'
                       r'\b(?:no|not|never|without|avoid|exclude|do not|don.t)\s+(?:any\s+|more\s+)?$', re.I)


def activity_signals(event):
    """Count positive activity clauses; ignore already-established/future text."""
    event = str(event or '')
    # Python-owned interval notes above the action list are metadata, not acts.
    parts = re.split(r'(?im)^Current interval actions[^\n]*:\s*', event, maxsplit=1)
    if len(parts) == 2:
        event = parts[1]
    event = re.split(r'(?im)^Stage these actions with physical cause|^Carry resulting positions', event, maxsplit=1)[0]
    scores, negative = {}, set()
    for clause in re.split(r'[，,。；;！!？?\n]|但是|而是|\bbut\b', event):
        if re.match(r'^\s*(?:ALREADY ESTABLISHED|Previously established|SOURCE SONG SHORT TAIL)', clause, re.I):
            continue
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
