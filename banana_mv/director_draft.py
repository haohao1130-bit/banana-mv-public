"""Director-first drafting for arbitrary MV casts and reference assets.

The director declares only visible asset relationships that cannot be inferred
safely from a shot. Python packages the native H3 sections and original audio.
No extra inference, fixed cast count, or new quality gate.
"""
import re

from banana_mv.director_shoot import SHOT_DRAFT_SYSTEM

VERSION = '35b-generic-director-first-v1'
# Reuse the proven cinematic method, replacing only the dual-singer contract.
SYSTEM = SHOT_DRAFT_SYSTEM.split('DELIVERY:', 1)[0].replace(
    'Python supplies the authoritative cast,\nwardrobe, SRT windows, clip scope and final H3 packaging.',
    'The commission supplies cast, wardrobe, SRT windows and clip scope; Python packages H3.'
).replace(
    'Use the\nassigned subject labels rather than guessing character names.',
    'Use the user-authored identities and explicit picture bindings, not guessed names.'
).replace(
    'Choose shot count freely within the existing 12-shot interface, including an\nexpressive continuous take. Existing shot clocks allow at least 0.250s per shot.',
    'Choose the shot count and local cut times to serve the event, including an expressive continuous take.'
) + """
CAST AND ASSETS: Preserve explicit identities and reference roles. Any number
of performers supported by the connected media may appear, including original
supporting actors without photos. A picture may be a scene, prop, outfit,
identity reference or boundary frame; never assume every image is an actor.
Use stable <Subject N> labels within this clip. For each visible referenced
subject, bind its actual <Picture N>; for original characters use the authored
name and stable design without inventing a picture. A continuation frame is
not an identity reference. Include only subjects used in the current event.
Keep current wardrobe, body form and props; reference appearances are not
permission to reset mutable state. Preserve user-designated vocal roles.

DELIVERY: Write two plain-text sections: subject_definitions: (short visible
subject/asset bindings, one per line, with only useful stable facts) and
detailed_description: (the full finished English [Shot N] paragraphs).
The first shot starts at zero; subsequent cuts use [Shot N] At mm:ss.mmm.
Use actual connected labels and keep them consistent. The brief binding section
may be empty if the scene needs no named subjects. Python handles the summary,
retention and original audio fields. Do not write them or a separate analysis.
If the commission asks for END_STATE, append that brief handoff after the shots.
No new speech, quoted lyrics, subtitles or replacement audio.
"""

DELIVERY = (
    'Deliver short subject_definitions: and fully developed detailed_description: '
    'shot paragraphs only. Use connected pictures and stable subject labels. '
    'Original supporting actors need no image. Python assembles the other H3 fields.'
)

_HEADER = re.compile(
    r'(?im)^[ \t]*(?:\*\*)?(subject_definitions|summary|retention_analysis|'
    r'detailed_description|integrated_multimodal_description|overall_soundscape|'
    r'non_diegetic_music)(?:\*\*)?[ \t]*:[ \t]*(?:\*\*)?'
)
_LABEL = re.compile(r'(?im)^[ \t]*(<(?:Subject|Picture) \d+>)\s*')


def assemble(raw, continuation=False):
    """Package draft sections without rewriting the creative shot prose.

    Accept full native replies as well, for compatibility with retries/older
    model habits. Preserve supplied definitions; do not invent actors or
    bind subjects to pictures by index. Existing media checks still run.
    """
    marks = list(_HEADER.finditer(raw))
    sections = {}
    for i, mark in enumerate(marks):
        sections[mark[1].lower()] = raw[mark.end():marks[i+1].start() if i+1<len(marks) else len(raw)].strip()
    shots = sections.get('detailed_description') or sections.get('integrated_multimodal_description')
    if not shots and not marks and re.match(r'(?i)^\s*\[Shot\s+1\]', raw):
        shots = raw.strip()
    if not shots:
        raise ValueError('35B missing detailed_description shot prose.')
    definitions = sections.get('subject_definitions', '')
    # Source audio is deterministic; ignore any invented audio definition.
    definitions = '\n'.join(line for line in definitions.splitlines()
                            if not re.match(r'(?i)^\s*<Audio\s+\d+>', line)).strip()
    if continuation and not re.search(r'(?im)^\s*<Picture 1>\s', definitions):
        definitions += ('\n' if definitions else '') + '<Picture 1> is the preceding frame, not a new identity reference.'
    # Retention describes actual defined subjects/assets, not a hardcoded cast.
    retention = []
    for line in definitions.splitlines():
        m = _LABEL.match(line)
        if not m:
            continue
        label = m[1]
        if label.startswith('<Subject') and re.search(r'<Picture \d+>', line):
            retention.append(label + ': partially_preserved - retain the defined reference identity and role; current appearance and action follow the commission.')
        elif label.startswith('<Picture'):
            retention.append(label + ': fully_preserved - retain its assigned reference role.')
    definitions += ('\n' if definitions else '') + '<Audio 1> is the supplied original song, reused unchanged.'
    retention.append('<Audio 1>: fully_copy, including the original recorded vocals.')
    return '\n\n'.join((
        'subject_definitions:\n' + definitions,
        'summary:\n[reference generation + audio reuse] Film the current commissioned MV event with the defined subjects and reference roles; preserve the original song.',
        'retention_analysis:\n' + '\n'.join(retention),
        'detailed_description:\n' + shots,
        'overall_soundscape:\nThe supplied source song plays unchanged.',
        'non_diegetic_music:\nThe supplied source song.',
    ))
