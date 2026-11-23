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
                     'describe these outfits in subject_definitions):')
        lines += [f'{role}: {outfit}' for role, outfit in current.items()]
    for at, role, outfit in during:
        lines.append(f'OUTFIT CHANGE INSIDE THIS CLIP at {at:.2f}s: {role} → {outfit}')
    return '\n'.join(lines) + ('\n' if lines else '')


# ---------------------------------------------------------------------------
# 當段入鏡名單：劇本每段寫「入鏡：小語、男主角」。沒入鏡的參考角色不能被 9B 定義成
# Subject、也不能出現在鏡頭裡，否則 H3 會把牠和別的角色揉在一起（例如香蕉兔的腳
# 長到小語身上）。上一段尾幀 <Picture 1> 也不能被綁成角色。

_CAST_LINE = re.compile(r'(?:^|[｜\n])\s*(?:[-*•・]\s*)?【?入鏡】?\s*[：:]?\s*(?<=[：:】])\s*([^｜\n]+)')
_REF_NAME = re.compile(r'<Picture (\d+)>\s*[=＝]\s*([^\s=＝，,。；;（(]+)')


def onscreen_cast(event):
    match = _CAST_LINE.search(event or '')
    if not match:
        return []
    # 「猴哥不入鏡」這種寫法是在說誰不在，不能當成入鏡名單。
    return [name for name in re.split(r'[、,，/／;；\s]+|和|與|及', match[1].strip())
            if name and not re.search(r'不入鏡|不出場|不在場|沒入鏡|缺席', name)]


def reference_names(fixed):
    """<Picture 2> = 男主角 = S1 → {2: '男主角'}（已經是連接後的編號）。"""
    names = {}
    for number, name in _REF_NAME.findall(fixed or ''):
        names.setdefault(int(number), name)
    return names


# 場景圖不是演員：不在「入鏡」名單裡很正常，不能因此把場景圖藏起來或叫 9B 別提它
# （實測 b43d9e4edec4：舞台、擂台圖被扣下，9B 只好自己腦補新場景）。
_SCENE_HEADING = re.compile(r'^\s*(?:[■#【\[]|─|━)?\s*[^\n]{0,6}(?:場景|場地|背景|環境|地點)')
_SCENE_WORDS = re.compile(r'舞台|擂台|場景|場地|背景|環境|房間|客廳|臥室|教室|廚房|食堂|餐廳|街|公寓|海邊|沙灘|'
                          r'公園|森林|城市|室內|室外|stage|ring|room|scene|background|location|street', re.I)


def scene_pictures(fixed):
    """設定裡的場景參考圖編號：寫在「場景」標題底下，或名稱本身就是地點。"""
    scenes, in_scene = set(), False
    for line in (fixed or '').splitlines():
        if re.match(r'\s*(?:[■#【]|─{3,}|━{3,})', line):
            in_scene = bool(_SCENE_HEADING.match(line)) and '隔離' not in line
        for number, name in _REF_NAME.findall(line):
            if in_scene or _SCENE_WORDS.search(name):
                scenes.add(int(number))
    return scenes


def cast_references(fixed):
    """只留演員的參考圖（排除場景圖），用來判斷誰沒入鏡。"""
    scenes = scene_pictures(fixed)
    return {n: name for n, name in reference_names(fixed).items() if n not in scenes}


def _listed(name, cast):
    return any(name in actor or actor in name for actor in cast)


def _present(name, cast, event):
    """入鏡名單有列，或這段通告單內文有提到（例如「桌上的蕉彌公仔」）都算在場。"""
    body = '\n'.join(line for line in _CAST_LINE.sub('', event or '').splitlines()
                     if not re.match(r'\s*(?:ALREADY ESTABLISHED|PREVIOUS CLIP ENDED)', line))
    return _listed(name, cast) or name in body


def cast_note(event, fixed):
    cast = onscreen_cast(event)
    if not cast:
        return ''
    absent = [f'{name} (<Picture {n}>)' for n, name in sorted(cast_references(fixed).items())
              if not _present(name, cast, event)]
    note = 'ON-SCREEN IN THIS CLIP: ' + '、'.join(cast) + '.'
    if absent:
        note += (' NOT IN THIS CLIP: ' + '、'.join(absent) + ' — do not define them as subjects, do not mention '
                 'them in any shot, and never merge their features into another actor or prop.')
    return note


def cast_errors(prompt, event, fixed, tail):
    if 'subject_definitions:' not in prompt:
        return []
    definitions = prompt.split('subject_definitions:', 1)[1].split('summary:', 1)[0]
    errors = []
    actor_on_frame = [line for line in definitions.splitlines()
                      if re.search(r'<Subject \d+>[^\n]*<Picture 1>(?!\d)', line)
                      and not re.search(r'environment|room|setting|location|background|workshop|studio|park|'
                                        r'interior|scene|場景|環境|房間', line, re.I)]
    if tail and actor_on_frame:
        errors.append('[ERROR][Cast] <Picture 1> is the previous clip\'s frame, not a character reference. '
                      'Bind each actor to their own reference picture listed in the fixed settings.')
    cast = onscreen_cast(event)
    if cast:
        for number, name in sorted(cast_references(fixed).items()):
            if not _present(name, cast, event) and re.search(rf'<Picture {number}>(?!\d)', definitions):
                errors.append(f'[ERROR][Cast] {name} (<Picture {number}>) is not on screen in this clip. '
                              'Remove that subject entirely and keep it out of every shot.')
    return errors


def absent_pictures(event, fixed):
    """這段沒入鏡的參考圖編號（已是連接後的編號）。沒有入鏡行時不判斷，回傳空集合。"""
    cast = onscreen_cast(event)
    if not cast:
        return set()
    return {n for n, name in cast_references(fixed).items() if not _present(name, cast, event)}
