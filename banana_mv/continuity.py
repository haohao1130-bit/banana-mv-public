"""跨段接續：9B 交稿時附的 END_STATE、下一段的接續鎖定，以及通用換裝點。

- END_STATE：9B 在 H3 提示詞最後多寫一段結束狀態（姿勢、進行中的動作與方向、
  鏡頭運動）。Python 把它剪下來，不送給 H3，存進這一段，交給下一段的 9B。
- 換裝點：使用者在劇本或共同設定寫【換裝 01:20】S2 → 純白綁帶比基尼，
  Python 依時間軸推算每段當下每個人穿什麼，取代過去寫死的海邊規則。
"""
import re

END_STATE_REQUEST = (
    'After the six sections, add one final block that H3 will NOT see, for the next clip\'s director:\n'
    'END_STATE:\n'
    'pose: <who is where, facing which way, what they hold, at the final frame>\n'
    'motion: <any action still in progress at the cut, with its direction AS SEEN FROM THE CAMERA '
    '(e.g. turning clockwise, moving screen-left to screen-right, rising) and speed; or "settled">\n'
    'camera: <camera movement still in progress at the cut, with direction (e.g. orbiting left to right, '
    'pushing in); or "static">\n'
    'mood: <current emotion / energy>'
)

_END_STATE = re.compile(r'(?ims)^[ \t]*(?:\*\*)?END_STATE(?:\*\*)?\s*:?\s*(.*)\Z')


def split_end_state(raw):
    """回傳 (給 H3 的提示詞, END_STATE 文字或 None)。END_STATE 一定放在最後。"""
    if not isinstance(raw, str):
        return raw, None
    match = _END_STATE.search(raw)
    if not match:
        return raw, None
    state = match[1].strip()
    state = re.sub(r'```\s*$', '', state).strip()
    return raw[:match.start()].rstrip(), (state[:1500] or None)


def handoff_note(previous_state, cut=False):
    """下一段通告單裡的「上一段怎麼結束」與方向鎖定。"""
    if not previous_state:
        return ''
    if cut:
        return ('PREVIOUS CLIP ENDED (for story continuity only; this clip opens with a cut, '
                'so motion direction is not locked):\n' + previous_state + '\n')
    return ('PREVIOUS CLIP ENDED AT THIS EXACT MOMENT (already happened; do not replay it):\n'
            + previous_state + '\n'
            'CONTINUITY LOCK: open by continuing any motion and camera movement listed above in the SAME '
            'direction and at a similar speed (directions are as seen from the camera). Only after that '
            'movement completes may it change. State this direction explicitly in the first shot.\n')


_CHANGE = re.compile(
    r'【\s*換裝\s*(?:(\d+)\s*[:：])?(\d+(?:\.\d+)?)\s*】\s*(S\d+)\s*(?:→|->|=>|＝|=|:|：)\s*([^\n【]+)')


def wardrobe_changes(text):
    """【換裝 01:20】S2 → 純白綁帶比基尼 → [(80.0, 'S2', '純白綁帶比基尼')]（依時間排序）。"""
    changes = []
    for minutes, seconds, role, outfit in _CHANGE.findall(text or ''):
        at = int(minutes or 0) * 60 + float(seconds)
        changes.append((at, role.upper(), outfit.strip().rstrip('。；;，,')))
    return sorted(changes, key=lambda row: row[0])


def current_wardrobe(changes, clip_start, clip_seconds):
    """這段開頭每個人穿什麼，以及這段之內才發生的換裝（給 9B 安排）。"""
    current, during = {}, []
    for at, role, outfit in changes:
        if at <= clip_start + 1e-3:
            current[role] = outfit
        elif at < clip_start + clip_seconds - 1e-3:
            during.append((round(at - clip_start, 3), role, outfit))
    return current, during


def wardrobe_note(text, clip_start, clip_seconds):
    current, during = current_wardrobe(wardrobe_changes(text), clip_start, clip_seconds)
    lines = []
    if current:
        lines.append('CURRENT OUTFITS (already changed before this clip; do not film the change, '
                     'describe these outfits in subject_definitions and every shot):')
        lines += [f'{role}: {outfit}' for role, outfit in current.items()]
    for at, role, outfit in during:
        lines.append(f'OUTFIT CHANGE INSIDE THIS CLIP at {at:.2f}s: {role} → {outfit}')
    return '\n'.join(lines) + ('\n' if lines else '')
