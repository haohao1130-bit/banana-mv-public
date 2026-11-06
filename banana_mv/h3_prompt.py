"""Compile native Ref2VA structure around a visual writer's shot prose.

These are technical checks, not a semantic or rendered-video verifier.
"""
import re

from banana_mv.direction_contract import H3_SECTIONS, validate_h3_sections


VISUAL_WRITER_SYSTEM = """Write only English shot prose for THIS source interval, beginning [Shot 1].
No JSON, headings, six-section prompt, dialogue, lyrics, subtitles or sound directions.
Use <Subject N> for every character in appearance_start and no other Subject ID.
Its connected_reference and current appearance are authoritative; other pictures are
only the supplied places, objects or alternate views, never extra cast. An opening
frame is not identity authority. Preserve who acts, who receives it and the result.
Treat visual_task as the ENTIRE script for this clip. Turn only its current visible
action into camera shots with clear responses and consequences. Do not write a recap,
origin story or setup event from an earlier clip; do not add unscheduled transformations
or wardrobe changes. Starting wardrobe/identity is the present situation, not an action
to perform. Develop framing, light, movement and edits, not new plot milestones.
Keep distinct locations separate using full-frame edits unless split screen is requested.
Use current appearance throughout; if appearance_end differs, show that change once.
First shot: [Shot 1] with no timestamp. Later cuts: [Shot N] At MM:SS.mmm, ...,
numbered consecutively at increasing times strictly inside seconds, never padding.
Only the assigned vocalist lip-syncs; the source recording owns all words and timing.
Music measurements guide energy and timing, not new story content.
Obey ending_contract: continuing/excerpt leaves the larger story open. When resolving,
complete the allocated action and result by local_resolution_by if supplied; zero
means already completed, so show aftermath without replay. Arrive at closing_shot by
local_settle_by if supplied: describe the final pose, framing and light, and the motion
that reaches them in time. terminal_hold sustains it without a new event or scene.
Return only the visible shots, not instructions to another writer."""


def scoped_appearance(appearance):
    """Drop off-scene environments only when every visible actor has a known scene."""
    chars=appearance['characters'];env=appearance['environments']
    locations={c.get('location') for c in chars.values()}
    if chars and locations <= env.keys():
        return dict(appearance,environments={k:v for k,v in env.items() if k in locations})
    return appearance


def validate_shots(body, seconds, appearance, picture_count):
    body=body.strip()
    if not body.startswith('[Shot 1]') or re.search(
            r'```|<d>|\(S\d+\)|^\s*(?:'+'|'.join(H3_SECTIONS)+r')\s*:',body,re.M):
        raise ValueError('只回傳以 [Shot 1] 開始的鏡頭描述，不含六段標題、歌詞或說話標籤。')
    markers=list(re.finditer(r'\[Shot (\d+)\](?:\s*At (\d{2}):(\d{2})\.(\d{3}),?)?',body))
    if len(re.findall(r'\[Shot\b',body))!=len(markers):
        raise ValueError('鏡頭標記需使用 [Shot N]。')
    times=[]
    for i,m in enumerate(markers):
        if int(m[1])!=i+1 or (i==0 and m[2] is not None) or (i>0 and m[2] is None):
            raise ValueError('鏡頭需連號；第一鏡無時間，後續使用 At MM:SS.mmm。')
        time=0 if i==0 else int(m[2])*60+int(m[3])+int(m[4])/1000
        if i and (int(m[3])>=60 or not times[-1]<time<float(seconds)):
            raise ValueError('切鏡時間需遞增且小於當段可見秒數。')
        end=markers[i+1].start() if i+1<len(markers) else len(body)
        if not body[m.end():end].strip():raise ValueError('每個鏡頭需有畫面描述。')
        if re.match(r'\s*At\b',body[m.end():end]):
            raise ValueError('鏡頭時間格式需為 At MM:SS.mmm；第一鏡不加時間。')
        times.append(time)
    known={'<Subject '+sid[1:]+'>' for sid in appearance['characters']}
    used=set(re.findall(r'<Subject \d+>',body))
    if used!=known:
        raise ValueError('鏡頭 Subject 必須與當段入鏡角色一致：'+(', '.join(sorted(known)) or '無固定角色'))
    for kind,n in re.findall(r'<(Picture|Audio|Video) (\d+)>',body):
        if kind=='Video' or not 1<=int(n)<=(picture_count if kind=='Picture' else 1):
            raise ValueError('鏡頭引用未連接的媒體：'+kind+' '+n)
    return body,markers


def compile_prompt(body, seconds, appearance, picture_count, previous_frame=None):
    # H3's specialized rewriter may retain its trained six-field output shape.
    # Accept that envelope, but never let its metadata override compiled facts.
    if body.lstrip().startswith('subject_definitions:'):
        validate_h3_sections(body)
        body=re.search(r'^\s*detailed_description\s*:(.*?)^\s*overall_soundscape\s*:',
                       body,re.M|re.S)[1].strip()
    body,markers=validate_shots(body,seconds,appearance,picture_count)
    definitions=[];retained=[]
    for sid,c in appearance['characters'].items():
        label='<Subject '+sid[1:]+'>';ref=c.get('connected_reference')
        identity=f'the same individual shown in {ref}' if ref else 'the recurring character specified by the directed event'
        details=[]
        if c.get('location'):details.append('Location: '+c['location'])
        if c.get('hairstyle'):details.append('Hair: '+c['hairstyle'])
        for g in c.get('wearing',[]):
            details.append('Wearing: '+' '.join(str(g.get(k,'')) for k in ('color','material','garment_type','state')).strip())
        for g in c.get('not_wearing',[]):
            details.append('Not worn: '+' '.join(str(g.get(k,'')) for k in ('color','material','garment_type')).strip()+
                           '; '+str(g.get('state',''))+' at '+str(g.get('current_location','')))
        for key in ('appearance_changes','injuries','held_props'):
            if c.get(key):details.append(key.replace('_',' ')+': '+', '.join(c[key]))
        definitions.append(label+' is '+identity+'. '+'. '.join(details)+'.')
        shots=[f'[Shot {i+1}]' for i,m in enumerate(markers)
               if label in body[m.end():markers[i+1].start() if i+1<len(markers) else len(body)]]
        retained.append(label+' (appears in '+', '.join(shots)+'): partially_preserved - preserve identity; current appearance and directed changes govern clothing, pose and expression.')
    pictures=set(re.findall(r'<Picture \d+>',body))-{c.get('connected_reference') for c in appearance['characters'].values()}-{previous_frame}
    for picture in sorted(pictures):
        definitions.append(picture+' supplies only the directed setting, object or view; it does not create another character.')
        retained.append(picture+': partially_preserved - use only its directed visual role.')
    if previous_frame:
        definitions.append(previous_frame+' is the opening frame from the previous clip, not another actor or a reset of clothing.')
        retained.append(previous_frame+': partially_preserved - opening pose and composition only.')
    retained.append('<Audio 1>: fully_copy - preserve the complete supplied audio interval, voices, words, melody and timing.')
    values=[ '\n'.join(definitions) or 'N/A - no recurring character or visual reference is required by these shots.',
        '[reference generation + audio reuse'+(' + keyframe completion' if previous_frame else '')+'] The directed visual event unfolds during this source interval with the original recording.',
        '\n'.join(retained),body,
        '<Audio 1>: fully_copy. The supplied recording is the only soundtrack, including its existing voices, music and sounds. Add no dialogue, ambience or effects.',
        'N/A - use only the music already present in <Audio 1>; no replacement or additional score.']
    text='\n\n'.join(name+':\n'+value for name,value in zip(H3_SECTIONS,values))
    validate_h3_sections(text)
    return text
