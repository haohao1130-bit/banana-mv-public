"""Clip-local 9B commission checks: explicit vocal conflicts and active wardrobe."""
import re


_ROLE_BIND = re.compile(r'(?im)^\s*(S[12])\s*[=:：]\s*(<Picture \d+>)')
_SUBJECT_LINE = re.compile(r'(?m)^\s*<Subject\s+(\d+)>\s+([^\n]+)')
_SHOT = re.compile(r'(?im)^\s*\[Shot\s+(\d+)\]')
_TIME = re.compile(r'(?i)\bAt\s+(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?')
_VOCAL = re.compile(r'(?i)\b(?:sings?|singing|lip[ -]?sync(?:s|ing)?|mouth\s+(?:moves|moving))\b')
_BEACH = re.compile(r'在海邊|到了海邊|海邊步道|海灘|沙灘|浪線|淺水|水花|海浪|海水|beach|shore|surf\s+line', re.I)
_OLD_S1 = re.compile(r'hoodie|cargo\s+(?:pants|trousers)|連帽外套|工裝長褲', re.I)
_OLD_S2 = re.compile(r'cardigan|camisole|denim\s+(?:mini\s*)?skirt|針織外套|牛仔裙|蕾絲背心', re.I)


def role_pictures(fixed_setup):
    """Use user-specified identities; never infer singers from picture order."""
    return {role.upper(): picture for role, picture in _ROLE_BIND.findall(fixed_setup)}


def _subject_roles(prompt, pictures):
    definition = prompt.split('subject_definitions:', 1)[-1].split('summary:', 1)[0]
    mapped = {}
    genders = {}
    for number, description in _SUBJECT_LINE.findall(definition):
        roles = set(re.findall(r'\bS[12]\b', description, re.I))
        bound = [role for role, picture in pictures.items() if picture in description]
        role = next(iter(roles), None) if len(roles) == 1 else (bound[0] if len(bound) == 1 else None)
        if role:
            role = role.upper()
            mapped[number] = role
            if re.search(r'\b(?:woman|female|girl)\b|女主', description, re.I):
                genders.setdefault('she', set()).add(role)
            if re.search(r'\b(?:man|male|boy)\b|男主', description, re.I):
                genders.setdefault('he', set()).add(role)
    return mapped, {key: next(iter(value)) for key, value in genders.items() if len(value) == 1}


def _shots(prompt, seconds):
    detail = re.split(r'(?im)^\s*detailed_description\s*:', prompt, maxsplit=1)
    if len(detail) != 2:
        return []
    body = re.split(r'(?im)^\s*(?:overall_soundscape|non_diegetic_music)\s*:', detail[1], maxsplit=1)[0]
    matches = list(_SHOT.finditer(body))
    result = []
    for index, match in enumerate(matches):
        content = body[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(body)]
        stamp = _TIME.search(content[:100])
        start = (int(stamp[1])*60 + int(stamp[2]) + int((stamp[3] or '0').ljust(3,'0'))/1000) if stamp else 0.0
        end = seconds if index + 1 == len(matches) else None
        result.append([int(match[1]), start, end, content])
    for i in range(len(result)-1):
        result[i][2] = result[i+1][1]
    return result


def _event_roles(text, mapped, genders):
    """Conservative positive singer attribution; reactions need not sing."""
    found = []
    matches = list(_VOCAL.finditer(text))
    for match in matches:
        before = text[max(0,match.start()-190):match.start()]
        if re.search(r'(?i)\b(?:not|never|stops?|without|no longer|doesn.t)\s+(?:\w+\s+){0,2}$', before):
            continue
        if re.search(r'(?i)\b(?:watches?|listens?\s+to|hears?)\s+(?:her|him|them)\s+$', before):
            continue
        duet = re.search(r'(?i)\b(?:both|together|the\s+two|duet)\s+(?:\w+\s+){0,3}$', before)
        if duet:
            found.append((match.start(), {'S1','S2'}, 'duet'))
            continue
        pronoun = re.search(r'(?i)\b(he|she)\s+(?:begins?\s+to\s+|starts?\s+to\s+|continues?\s+to\s+)?$', before)
        if pronoun and pronoun[1].lower() in genders:
            found.append((match.start(), {genders[pronoun[1].lower()]}, pronoun[1]))
            continue
        # Find the nearest explicit subject inside the same short action clause.
        mentions = list(re.finditer(r'<Subject\s+(\d+)>', before))
        if mentions:
            last = mentions[-1]
            if match.start() - (max(0,match.start()-190) + last.end()) < 130:
                role = mapped.get(last[1])
                if role:
                    found.append((match.start(), {role}, '<Subject '+last[1]+'>'))
                    continue
        role = re.search(r'(?i)\b(S[12])\s+(?:begins?\s+to\s+|starts?\s+to\s+)?$', before)
        if role:
            found.append((match.start(), {role[1].upper()}, role[1]))
    return found


def _overlap(start, end, role, cues):
    return sum(max(0, min(end, float(cue['clip_end'])) - max(start, float(cue['clip_start'])))
               for cue in cues if role in cue.get('subjects', []))


def vocal_errors(prompt, cues, pictures, seconds, has_srt=True):
    if not has_srt:
        return []
    mapped, genders = _subject_roles(prompt, pictures)
    problems = []
    for number, start, end, body in _shots(prompt, seconds):
        if end is None or end <= start:
            continue
        for at, roles, label in _event_roles(body, mapped, genders):
            # An event near the beginning of a shot is timed at the shot cut.
            immediate = at < 230
            for role in sorted(roles):
                start_ok = _overlap(start, min(end,start+0.18), role, cues) > 0.01
                sustained = _overlap(start, end, role, cues) >= min(0.45, (end-start)*0.35)
                if (immediate and start_ok) or (not immediate and sustained):
                    continue
                allowed = sorted({r for cue in cues
                                  if float(cue['clip_start']) < end and float(cue['clip_end']) > start
                                  for r in cue.get('subjects', [])})
                problems.append(
                    f'[ERROR][Vocal] [Shot {number}] at {start:.3f}s assigns {label} '
                    f'singing to {role}, but the clip-local SRT allows {allowed} '
                    f'for this action. Keep the camera, scene and silent reactions; '
                    'repair only the incorrectly assigned singing.'
                )
    return problems


def scene_is_beach(event):
    """Stage on the beach only when the CURRENT location is the beach."""
    direct=re.search(r'(?im)^\s*(?:-\s*(?:@\d+(?:\.\d+)?s\s*)?)?'
                     r'(?:場景|CURRENT_SCENE|LOCATION)\s*[：:]\s*(.+)$',event)
    if direct:
        return bool(_BEACH.search(direct.group(1)))
    chapter=re.search(r'(?im)^(?:Source chapter:|PYTHON-OWNED CURRENT EVENT — scene)\s*(.+)$',event)
    if chapter and re.search(r'到了海邊|海邊遊玩|沙灘|beach|shoreline',chapter.group(1),re.I):
        return True
    return bool(re.search(r'走到沙灘|走向沙灘|站在沙灘|沿著浪線|沿浪線|走進淺水|踩上細沙|走到海水邊|到了海邊',event))


def wardrobe_for_clip(event, fixed_setup):
    """Promote already-current beach wardrobe, without leaking later plot to 9B."""
    if not scene_is_beach(event):
        return {}
    combined = fixed_setup + '\n' + event
    result = {}
    if re.search(r'S1.{0,45}短袖.{0,25}短褲|S1.{0,45}short.sleeve.{0,25}shorts', combined, re.I):
        result['S1'] = 'short-sleeve top and shorts'
    if re.search(r'S2.{0,55}(?:純白.{0,15})?(?:細繩|綁帶).{0,15}比基尼|S2.{0,55}white.{0,25}(?:string|tie).{0,20}bikini', combined, re.I):
        result['S2'] = 'pure-white tie-string bikini'
    return result


def wardrobe_errors(prompt, expected, pictures):
    if not expected:
        return []
    mapped, _ = _subject_roles(prompt, pictures)
    definition = prompt.split('subject_definitions:',1)[-1].split('summary:',1)[0]
    retention = prompt.split('retention_analysis:',1)[-1].split('detailed_description:',1)[0]
    errors = []
    for role, label in expected.items():
        marker = _OLD_S1 if role == 'S1' and 'shorts' in label else _OLD_S2 if role == 'S2' and 'bikini' in label else None
        if marker is None:
            continue
        actor_lines = [line for part in (definition,retention) for line in part.splitlines()
                       if any(re.search(rf'^\s*<Subject\s+{number}>',line)
                              for number, actual in mapped.items() if actual == role)]
        if not actor_lines:
            errors.append(f'[ERROR][Wardrobe] {role}: missing actor definition for {label}.')
            continue
        stale = [line.strip()[:160] for line in actor_lines if marker.search(line)]
        if stale:
            errors.append(f'[ERROR][Wardrobe] {role}: previous-scene clothing remains in subject_definitions/retention_analysis ({stale[0]}). Current outfit MUST be {label}.')
        descriptor = '\n'.join(actor_lines).lower()
        if role == 'S1' and (not re.search(r'short.sleeve|t-shirt|短袖',descriptor,re.I)
                             or not re.search(r'\bshorts\b|短褲',descriptor,re.I)):
            errors.append('[ERROR][Wardrobe] S1: subject/retention must describe short-sleeve top AND shorts for the current beach scene.')
        if role == 'S2' and (not re.search(r'white|白色|純白',descriptor,re.I)
                             or not re.search(r'bikini|比基尼',descriptor,re.I)
                             or not re.search(r'tie|strap|string|綁帶|細繩',descriptor,re.I)):
            errors.append('[ERROR][Wardrobe] S2: current beach appearance requires a pure-white tie-string bikini.')
    return errors


def check_commission(prompt, cues, pictures, seconds, expected_wardrobe, has_srt):
    return vocal_errors(prompt, cues, pictures, seconds, has_srt) + wardrobe_errors(prompt, expected_wardrobe, pictures)
