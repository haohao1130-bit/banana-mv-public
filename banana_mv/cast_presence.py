"""Clip-local actor visibility and media binding; never infer presence from SRT.

Uploaded assets are identities, not permission for every character to enter every
clip.  This deterministic adapter only uses the Python-assigned current EVENT.
Ambiguous/no-role events retain the original full cast to avoid false removals.
"""
import re

_PICTURE = re.compile(r'<Picture\s+(\d+)>', re.I)
_ROLE = re.compile(r'(?<!\w)S([12])(?!\w)', re.I)
_SOURCE_IMAGE = re.compile(r'^\s*(?:<Picture\s+(\d+)>|@(?:圖片|图片|image)\s*(\d+))\s*[=＝:：]\s*([^\n]+)', re.I)
_START_LOCAL = re.compile(r'^\s*-?\s*@(?P<time>\d+(?:\.\d+)?)s\b')
_START_ABS = re.compile(r'^\s*-?\s*(?P<clock>\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\s*[–—-]')
_ADMIN = re.compile(r'^(?:USER-SPECIFIED SONG TIME|PYTHON-OWNED|ALREADY ESTABLISHED|Previously established|Source chapter:|Phase inside chapter:|Current interval actions|Stage these actions|Carry resulting|CURRENT_ACTOR_STATE|EXPECTED_ACTOR_STATE|CURRENT_SCENE|Constraints for THIS chapter)', re.I)
_ROLE_BIND = re.compile(r'^\s*(S[12])\s*[=＝:：]', re.I)
_HEADING = re.compile(r'^\s*#{1,6}\s+')
_NEGATED = re.compile(r'(?:尚未|還沒|未曾|未|不會|不在|沒有).{0,5}(?:登場|出場|入鏡|現身|出現)|(?:登場|出場|入鏡|現身|出現).{0,5}(?:尚未|還沒|未)', re.I)


def _clock(value):
    parts = value.split(':')
    return float(parts[-1]) + (int(parts[-2]) * 60 if len(parts) >= 2 else 0) + (int(parts[-3]) * 3600 if len(parts) >= 3 else 0)


def _aliases(fixed, source_pictures):
    result = {role: [role, f'<Subject {role[-1]}>'] for role in source_pictures}
    images = {}
    for raw in fixed.splitlines():
        match = _SOURCE_IMAGE.match(raw)
        if not match:
            continue
        number = int(match[1] or match[2])
        value = match[3].strip()
        # A declaration such as '<Picture 1>＝蕉大師（S1）' is an identity
        # name; wardrobe details that follow it are not cast aliases.
        name = re.split(r'[（(，,；;。\s]', value, maxsplit=1)[0].strip()
        if name and len(name) <= 32:
            images[number] = name
    for role, picture in source_pictures.items():
        m = _PICTURE.fullmatch(picture)
        if m and int(m[1]) in images:
            result[role].append(images[int(m[1])])
        # Also support the common 'S1 = 姓名' convention.
        named = re.search(r'(?im)^\s*' + role + r'\s*[=＝:：]\s*([^\n<]+)', fixed)
        if named:
            name = re.split(r'[（(，,；;。\s]', named[1].strip(), maxsplit=1)[0]
            if name and len(name) <= 32:
                result[role].append(name)
    return result


def _mentions(line, aliases):
    found = set()
    for role, choices in aliases.items():
        for token in choices:
            if token == role:
                hit = re.search(r'(?<!\w)' + re.escape(token) + r'(?!\w)', line, re.I)
            else:
                hit = token in line
            if hit:
                # "S1 尚未登場" is not evidence that S1 is present.
                if not _NEGATED.search(line):
                    found.add(role)
                break
    return found


def clip_cast(event, fixed, source_pictures, clip_start, duration):
    """Return conservative cast + first-mention offsets from CURRENT event.

    No SRT/voice windows, global identity list, previous chapter, or future
    chapter can grant screen presence.
    """
    aliases = _aliases(fixed, source_pictures)
    first = {}
    for raw in event.splitlines():
        line = raw.strip()
        if not line or _ADMIN.match(line) or _HEADING.match(line):
            continue
        roles = _mentions(line, aliases)
        if not roles:
            continue
        time = _START_LOCAL.match(line)
        abs_time = _START_ABS.match(line) if not time else None
        offset = (float(time['time']) if time else
                  max(0., _clock(abs_time['clock']) - float(clip_start)) if abs_time
                  else 0.)
        offset = round(min(float(duration), offset), 3)
        for role in roles:
            first[role] = min(first.get(role, offset), offset)
    # Source events without uniquely identifiable actors are legacy briefs,
    # so do not discard either person's reference assets.
    explicit = bool(first)
    roles = tuple(role for role in source_pictures if role in first) if explicit else tuple(source_pictures)
    return {
        'roles': list(roles),
        'entry_local_s': {role: first[role] for role in roles if role in first},
        'source': 'current_clip_event' if explicit else 'unresolved_keep_all',
    }


def active_picture_indices(source_pictures, active_roles, original_count):
    """1-based source image indices, including non-actor scene/prop photos."""
    active_roles = set(active_roles)
    owners = {}
    for role, picture in source_pictures.items():
        match = _PICTURE.fullmatch(picture)
        if match:
            owners.setdefault(int(match[1]), set()).add(role)
    removed = {i for i, roles in owners.items() if roles.isdisjoint(active_roles)}
    return [i for i in range(1, original_count + 1) if i not in removed]


def remap_pictures(text, active_indices):
    mapping = {n: i for i, n in enumerate(active_indices, 1)}
    def substitute(match):
        old = int(match[1])
        return f'<Picture {mapping[old]}>' if old in mapping else match[0]
    return _PICTURE.sub(substitute, text)


def active_fixed_settings(fixed, source_pictures, active_roles, indices):
    """Remove non-present actor declarations BEFORE renumbering images."""
    active = set(active_roles)
    excluded = set(source_pictures) - active
    excluded_images = set()
    for role in excluded:
        match = _PICTURE.fullmatch(source_pictures[role])
        if match:
            excluded_images.add(int(match[1]))
    # Preserve a shared picture when another active role owns it.
    for role in active:
        match = _PICTURE.fullmatch(source_pictures[role]) if role in source_pictures else None
        if match:
            excluded_images.discard(int(match[1]))
    result = []
    skip_actor_block = False
    for raw in fixed.splitlines():
        plain = raw.strip()
        if _HEADING.match(plain):
            skip_actor_block = False
        role = _ROLE_BIND.match(plain)
        image = _SOURCE_IMAGE.match(plain)
        if role:
            skip_actor_block = role[1].upper() in excluded
        elif image:
            skip_actor_block = int(image[1] or image[2]) in excluded_images
        elif not plain:
            skip_actor_block = False
        if skip_actor_block:
            continue
        if any(re.search(r'(?<!\w)' + re.escape(r) + r'(?!\w)', plain, re.I) for r in excluded):
            continue
        if any(_PICTURE.search(plain) and int(m[1]) in excluded_images
               for m in _PICTURE.finditer(plain)):
            continue
        result.append(raw)
    return remap_pictures('\n'.join(result), indices)
