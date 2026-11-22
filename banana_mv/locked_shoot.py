"""Python-locked vocal shot schedule and native Ref2VA assembly for 5070."""
import copy
import re
import uuid

from banana_mv.commission_guard import role_pictures, scene_wardrobe_schedule
from banana_mv.direction_contract import validate_h3_sections
from banana_mv.lyrics_reference import excerpt, vocal_timeline
from banana_mv.scene_state import SceneStateError, rewrite_retry_count

SHOT = re.compile(r'(?im)^\s*\[Shot\s+(\d+)\]\s*')
STAMP = re.compile(r'^\s*(?:At\s+)?\d\d:\d\d(?:\.\d{1,3})?[,;:]?\s*', re.I)
# Recognize explicit *positive* singer actions without mistaking spectators.
VOCAL_ACTION = re.compile(
    r'(?i)(?<!\w)(?P<actor><Subject\s+[12]>|S[12]|he|she|him|her|both|they|the\s+two)'
    r'(?!\w)(?:\s*\(S[12]\))?'
    r'(?P<link>(?:\s+(?:is|are|was|were|has|have|been|begins?|starts?|'
    r'started|continues?|continuing|keeps?|kept|still|visibly|clearly|'
    r'softly|loudly|to|shown|seen|performs?|delivers?)){0,5}\s+)'
    r'(?P<verb>sing(?:s|ing)?|raps|rapping|speaks?|speaking|recites?|reciting|'
    r'chants?|chanting|spoken\s+delivery|lip[ -]?sync(?:s|ing)?|'
    r'mouth\s+(?:moves|moving))\b'
)
PROPS = re.compile(r'泳圈|毛巾|車鑰匙|鑰匙|外出包|背包|吉他|手機|主機|螢幕', re.I)
SYSTEM = (
    'You are the MiniMax H3 Ref2VA cinematic prompt rewriter. '
    'Use the familiar SIX native Ref2VA sections: subject_definitions, summary, '
    'retention_analysis, detailed_description, overall_soundscape, '
    'non_diegetic_music. Only invent the visual shot bodies inside '
    'detailed_description; Python supplies the other fixed fields. '
    'Do not alter the supplied shot boundaries, identity or SRT singer authority. '
    'Use natural lip-sync where it fits the scene. SRT tags guide which performer to show. '
    'Never switch performers or invent a duet; silent characters may react. '
    'Python owns exact singer timing and identity. Use only <Subject 1> and '
    '<Subject 2> for the two actors; never use <Picture N> in shot prose. '
    'Keep the assigned shot count and story events. Develop detailed framing, '
    'spatial continuity, light, lens perspective, expressions, body actions, '
    'causal responses and camera movements. No future or previous story events. '
    'Reference-image clothing is subordinate to CURRENT WARDROBE.'
)

REPAIR_SYSTEM = (
    'You are the MiniMax H3 Ref2VA prompt rewriter EDITING ONE SHOT. '
    'Respond in the native six-section Ref2VA format shown in the user request. '
    'Copy the provided fixed sections without inventing content. '
    'In detailed_description, output exactly ONE corrected [Shot N] body, '
    'using that shot number and no other shot. Keep its original cinematic '
    'action and camera; fix only the listed costume/cast problem. '
    'Use tagged SRT cast hints if showing lip-sync. No explanations, apologies or JSON.'
)

def clip_screen_cast_rule(event):
    """Use an explicit per-clip on-screen list, not SRT singer presence."""
    visible = re.search(r'(?:^|[｜\n])\s*入鏡[：:]\s*([^｜\n]+)', event)
    if not visible:
        return ''
    blocked = re.search(r'(?:^|[｜\n])\s*不入鏡[：:]\s*([^｜\n]+)', event)
    early = re.search(r'(?:^|[｜\n])\s*(S[12]\s*在[^｜\n]*?之前不入鏡)', event)
    rules = ['CURRENT ON-SCREEN CAST (visual permission, not vocal roles): '
             + visible[1].strip() + '.']
    if blocked:
        rules.append('MUST STAY OFF SCREEN: ' + blocked[1].strip()
                     + '. No background, silhouette, reflection, edge-of-frame '
                     'presence, or reaction shots.')
    if early:
        rules.append('FIRST APPEARANCE GATE: ' + early[1].strip()
                     + '. Do not show the character before this exact time.')
    rules.append('Only the declared on-screen cast may appear in this clip. '
                 'An SRT-silent character is NOT necessarily present. '
                 'Uploaded pictures do NOT imply every person is on screen.')
    return '\n'.join(rules)


def singer_rows(a,b,cues):
    """Merge adjacent same-singer SRT cues, not per-subtitle vocal rows."""
    edges={a,b}
    for cue in cues:
        x=max(a,float(cue['clip_start']))
        y=min(b,float(cue['clip_end']))
        if y>x:edges.update((x,y))
    points=sorted(edges);intervals=[]
    for x,y in zip(points,points[1:]):
        if y-x<.001:continue
        roles=set()
        for cue in cues:
            if float(cue['clip_start'])<=x+.001 and float(cue['clip_end'])>=y-.001:
                roles.update(r for r in cue.get('subjects',()) if r in ('S1','S2'))
        who=tuple(sorted(roles))
        # Two independent SRT rows can overlap for milliseconds. This does
        # NOT turn them into an authored [S1+S2] duet.
        explicit_duet=any(
            set(cue.get('subjects',()))=={'S1','S2'}
            and float(cue['clip_start'])<=x+.001
            and float(cue['clip_end'])>=y-.001 for cue in cues
        )
        key=(who,explicit_duet)
        if intervals and intervals[-1][2]==key and abs(intervals[-1][1]-x)<.001:
            intervals[-1]=(intervals[-1][0],y,key)
        else:
            intervals.append((x,y,key))
    rows=[]
    for x,y,(who,explicit_duet) in intervals:
        if who==('S1',):
            v='If showing lip-sync, use <Subject 1> (SRT S1).'
        elif who==('S2',):
            v='If showing lip-sync, use <Subject 2> (SRT S2).'
        elif who==('S1','S2'):
            if explicit_duet:
                v='If showing the duet, <Subject 1> and <Subject 2> lip-sync together (SRT S1+S2).'
            else:
                v=('Independent S1 and S2 source vocals overlap. No authored duet; '
                   'each character follows their own source voice only.')
        else:
            v='No SRT cast hint; follow the scene for natural lip-sync and reactions.'
        rows.append(f'{x:.3f}–{y:.3f}s: '+v)
    return rows


def _global_vocal_rows(slots):
    """Consolidate adjacent matching vocal rows ACROSS visual shot boundaries."""
    spans=[]
    for shot in slots:
        for line in shot['rows']:
            m=re.match(r'^(\d+\.\d+)–(\d+\.\d+)s: (.+)$',line)
            if not m:
                raise ValueError('Unexpected shot vocal row: '+line)
            start,end,policy=float(m[1]),float(m[2]),m[3]
            if spans and abs(start-spans[-1][1])<.001 and policy==spans[-1][2]:
                spans[-1]=(spans[-1][0],end,policy)
            else:
                spans.append((start,end,policy))
    return [f'{a:.3f}–{b:.3f}s: {who}' for a,b,who in spans]

def plan_slots(seconds,cues,evidence=None,dynamic=True,scene_cuts=None):
    duration=round(float(seconds),3)
    if duration<=0:
        raise ValueError('片段長度必須為正值。')
    cuts=[0.0,duration]
    # Prefer source-authored vocal role changes to invented visual beat boundaries.
    change=sorted({round(float(cue[k]),3) for cue in cues for k in ('clip_start','clip_end')
                   if 0<float(cue[k])<duration})
    for t in change:
        left=tuple(sorted({r for c in cues if float(c['clip_start'])<t
                           and float(c['clip_end'])>=t for r in c.get('subjects',())}))
        right=tuple(sorted({r for c in cues if float(c['clip_start'])<=t
                            and float(c['clip_end'])>t for r in c.get('subjects',())}))
        if left!=right and t-max(x for x in cuts if x<t)>=1.1 and duration-t>=.65:
            cuts.append(t)
    # Film an authored location cut even without a singer handoff.
    for t in scene_cuts or ():
        t = round(float(t), 3)
        if .35 <= t <= duration - .35 and all(abs(t-c) >= .002 for c in cuts):
            cuts.append(t)
    cuts=sorted(set(cuts))
    music=(evidence or {}).get('music_structure',{}) if isinstance(evidence,dict) else {}
    downbeats=music.get('downbeats_s',()) if isinstance(music,dict) else ()
    if dynamic:
        for a,b in list(zip(cuts,cuts[1:])):
            if b-a>=3.6:
                available=[float(t) for t in downbeats if isinstance(t,(int,float)) and a+1.35<float(t)<b-1.35]
                if available:
                    cuts.append(round(min(available,key=lambda t:abs(t-(a+b)/2)),3))
                elif b-a>=4.8:
                    # Missing optional beat analysis must not force a whole 10s into one static shot.
                    cuts.append(round((a+b)/2,3))
    cuts=sorted(set(cuts))
    if len(cuts)>8:
        # A source-authored LOCATION change outranks optional musical inserts.
        # Never truncate the apartment cut merely because earlier downbeats
        # filled the maximum number of visual shots.
        required={round(float(t),3) for t in scene_cuts or ()}
        candidates=[t for t in cuts[1:-1] if .35<=t<=duration-.35]
        forced=[t for t in candidates if t in required][:6]
        optional=[t for t in candidates if t not in required and t>=1 and duration-t>=.8]
        cuts=[cuts[0]]+sorted(forced+optional[:max(0,6-len(forced))])+[duration]
    return [{'number':i+1,'start':a,'end':b,'rows':singer_rows(a,b,cues),
             'duet_authorized':any(
                 set(cue.get('subjects',()))=={'S1','S2'}
                 and float(cue['clip_start']) < b
                 and float(cue['clip_end']) > a for cue in cues),
             'allowed_singers':sorted({r for cue in cues
                 if float(cue['clip_start']) < b and float(cue['clip_end']) > a
                 for r in cue.get('subjects',()) if r in ('S1','S2')})}
            for i,(a,b) in enumerate(zip(cuts,cuts[1:]))]

def _extract(raw,slots,only=None):
    text=re.sub(r'<think>.*?</think>','',raw,flags=re.I|re.S)
    native_detail=bool(re.search(r'(?im)^\s*detailed_description\s*:',text))
    if re.search(r'(?im)^detailed_description:',text):
        text=re.split(r'(?im)^detailed_description:',text,maxsplit=1)[1]
        text=re.split(r'(?im)^(?:overall_soundscape|non_diegetic_music):',text,maxsplit=1)[0]
    found=list(SHOT.finditer(text));blocks={}
    for i,m in enumerate(found):
        n=int(m[1])
        block=STAMP.sub('',text[m.end():found[i+1].start() if i+1<len(found) else len(text)],count=1).strip()
        block=re.sub(r'(?ms)^\s*(?:overall_soundscape|non_diegetic_music):.*$','',block).strip()
        if not block or n in blocks:
            raise ValueError('9B 空鏡頭或重複鏡頭：'+str(n))
        blocks[n]=block
    # Native Ref2VA rewriters sometimes omit a redundant [Shot 1] on
    # a one-shot correction. The H3 detailed_description itself then
    # serves as the body for the single Python-owned slot.
    if not found and native_detail and text.strip() and (
            only is not None or len(slots)==1):
        # The official native format supplies detailed_description; a one-
        # shot response may contain prose without repeating [Shot 1].
        target=only if only is not None else slots[0]['number']
        blocks[target]=text.strip()
    expected={only} if only is not None else {s['number'] for s in slots}
    if set(blocks)!=expected:
        raise ValueError('9B 必須填寫這些指定鏡頭：'+repr(sorted(expected))+'；實際：'+repr(sorted(blocks)))
    return blocks

def _pronoun_roles(fixed):
    """Only explicit role and gender declarations authorize he/she mapping."""
    male=[];female=[]
    bound=role_pictures(fixed)
    for role,picture in bound.items():
        details=' '.join(line for line in fixed.splitlines()
                         if picture in line and re.search(r'\b'+role+r'\b',line,re.I))
        if re.search(r'\bmale\b|\bman\b|\bboy\b|男性|男主|男聲|男主唱',details,re.I):
            male.append(role)
        if re.search(r'\bfemale\b|\bwoman\b|\bgirl\b|女性|女主|女聲|女主唱',details,re.I):
            female.append(role)
    roles={}
    if len(male)==1:roles.update(he=male[0],him=male[0])
    if len(female)==1:roles.update(she=female[0],her=female[0])
    return roles

def _vocal_role(actor,pronouns):
    who=actor.lower().strip()
    m=re.fullmatch(r'<subject\s+([12])>',who)
    if m:return {'S'+m[1]}
    if who in ('s1','s2'):return {who.upper()}
    if who in ('both','they','the two'):return {'S1','S2'}
    return {pronouns[who]} if who in pronouns else set()


def _quiet_verb(verb):
    low=verb.lower()
    if low == 'spoken delivery':return 'quiet gestures'
    if low.endswith('ing'):return 'moving to the beat'
    if low.endswith('s'):return 'moves to the beat'
    return 'move to the beat'


def _repair_vocals(blocks,slots,fixed):
    """Fix only known WRONG singer verbs. Never rewrite a correct sung action.

    If a shot includes a singer handoff, the timed Python rows constrain the
    actual vocal subinterval. Unknown pronouns are not guessed.
    """
    pronouns=_pronoun_roles(fixed)
    revised=dict(blocks);audit=[]
    for slot in slots:
        number=slot['number'];allowed=set(slot['allowed_singers'])
        if not allowed:
            continue
        def correct(match):
            assigned=_vocal_role(match['actor'],pronouns)
            if not assigned:return match[0]
            if assigned <= allowed and not (
                assigned == {'S1','S2'} and not slot.get('duet_authorized')
            ):return match[0]
            replacement=(match[0][:match.start('verb')-match.start()]
                         +_quiet_verb(match['verb']))
            audit.append({'shot':number,'from':match[0],'to':replacement,
                          'allowed_singers':sorted(allowed)})
            return replacement
        revised[number]=VOCAL_ACTION.sub(correct,revised[number])
    return revised,audit


def _errors(blocks,wardrobe,scene_schedule=None,slots=None):
    problems={}
    for n,body in blocks.items():
        bad=[]
        if re.search(r'<Picture\s+\d+>',body):
            bad.append('[ERROR][Cast] [Shot '+str(n)+'] use only <Subject 1>/<Subject 2> in acting prose.')
        if bad:
            problems[n]=bad
    return problems

def _active_scene(schedule, time):
    return next((row for row in schedule
                 if row['start']-0.002 <= time < row['end']-0.002), None)

def _cfg(cfg,temperature):
    c=dict(cfg);c['rewriter']=dict(cfg['rewriter'],temperature=temperature,thinking=False)
    return c

def _native(blocks,slots,pictures,wardrobe,tail,event,ref_count,fixed='',scene_schedule=None,body_form=None):
    scene_schedule = scene_schedule or []
    body_form = body_form or {}
    cast_rule = clip_screen_cast_rule(event)
    scene='the current assigned setting'
    if scene_schedule:
        scene='the scheduled scenes in order'
    definitions=[];retention=[]
    for role,n in (('S1',1),('S2',2)):
        ref=pictures[role]
        costume=wardrobe.get(role,'the current outfit in the assigned reference unless this event explicitly changes it')
        if scene_schedule:
            costume='; '.join(
                f"{row['start']:.3f}–{row['end']:.3f}s: "
                + row['wardrobe'].get(role, costume)
                for row in scene_schedule)
        cast_line=next((line for line in fixed.splitlines() if re.match(r'^\s*'+role+r'\s*[=:：]',line,re.I)), '')
        gender=('male ' if re.search(r'男主|男聲|男主唱|male',cast_line,re.I) else
                'female ' if re.search(r'女主|女聲|女主唱|female',cast_line,re.I) else '')
        anatomy = (f' BODY FORM / ANATOMY (stable across shots and locations): '
                   f'{body_form[role]}. This is the character\'s body structure, '
                   'not clothing or an added prop.' if role in body_form else '')
        definitions.append(f'<Subject {n}> is the adult '+gender+
                           f'lead {role} from {ref}; identity, face and hair are preserved.'
                           + anatomy + f' CURRENT CLOTHING: {costume}. Location: {scene}.')
        retention.append(f'<Subject {n}>: partially_preserved - identity from {ref};'
                         + (f' preserve BODY FORM: {body_form[role]};' if role in body_form else '')
                         + f' current clothing is {costume}, overriding an obsolete outfit in reference images.')
    if tail:
        definitions.append('<Picture 1> is the preceding frame only, not a new actor or wardrobe reset.')
    retention.append('<Audio 1>: fully_copy, including the original recorded vocals.')
    film=[]
    for s in slots:
        n=s['number'];start=s['start']
        mark=f'[Shot {n}] ' if n==1 else f'[Shot {n}] At {int(start)//60:02d}:{start%60:06.3f}, '
        scene_row=_active_scene(scene_schedule,start) if scene_schedule else None
        if scene_row:
            # This is a starting condition at the shot cut, not a costume
            # change animation or an invitation for 9B to restage the beach.
            clothes='; '.join(
                f'<Subject {k}> already wears {scene_row["wardrobe"][role]}'
                for k,role in ((1,'S1'),(2,'S2')) if role in scene_row['wardrobe'])
            mark+=f"Scene: {scene_row['scene']}. "+(clothes+'. ' if clothes else '')
        film.append(mark+blocks[n])
    output='\n\n'.join((
        'subject_definitions:\n'+'\n'.join(definitions),
        'summary:\nThe current event unfolds in '+scene+' through photography and physical character interaction, following existing voices in the original track.' + ('\n' + cast_rule if cast_rule else ''),
        'retention_analysis:\n'+'\n'.join(retention),
        'detailed_description:\nUse the original song from <Audio 1> unchanged (fully_copy). '+
        'SRT CAST HINTS (only when showing lip-sync):\n'+
        '\n'.join(_global_vocal_rows(slots))+
        '\nNo added vocals, spoken dialogue, text overlays or subtitles.\n'+
        (cast_rule + '\n' if cast_rule else '')+
        '\n'.join(film),
        'overall_soundscape:\nThe supplied source song plays unchanged.',
        'non_diegetic_music:\nThe supplied source song.'
    ))
    validate_h3_sections(output)
    if any(int(p)>ref_count for p in re.findall(r'<Picture (\d+)>',output)):
        raise SceneStateError('Python H3 定裝引用了未連接圖片。')
    return output

def _native_output_template(slots,pictures,wardrobe,body_form=None):
    """Native Ref2VA six-section format that the 9B SFT was trained to write.

    Only shot visual bodies are creative; fixed fields in this example will be
    authored again by Python for the final H3 generation prompt.
    """
    body_form = body_form or {}
    rows=[
        'subject_definitions:',
        '<Subject 1> (S1): the same person as '+pictures['S1']+
        '; present outfit: '+wardrobe.get('S1','current established clothing')+'.',
        '<Subject 2> (S2): the same person as '+pictures['S2']+
        '; present outfit: '+wardrobe.get('S2','current established clothing')+'.',
        *(f'<Subject {n}> BODY FORM (stable anatomy): {body_form[role]}'
          for role,n in (('S1',1),('S2',2)) if role in body_form),
        '',
        'summary:',
        '[reference generation + audio reuse] Film the assigned current clip event.',
        '',
        'retention_analysis:',
        '<Subject 1>: partially_preserved - preserve facial identity; use current outfit.',
        '<Subject 2>: partially_preserved - preserve facial identity; use current outfit.',
        '<Audio 1>: fully_copy - the original song and its vocals stay unchanged.',
        '',
        'detailed_description:',
    ]
    for slot in slots:
        number=slot['number'];start=slot['start']
        prefix=(f'[Shot {number}] ' if number==1 else
                f'[Shot {number}] At {int(start)//60:02d}:{start%60:06.3f}, ')
        rows.append(prefix+'Write a concrete cinematic paragraph for the assigned action.')
    rows+=(
        '',
        'overall_soundscape:',
        'The supplied original song remains unchanged.',
        '',
        'non_diegetic_music:',
        'The supplied original song.',
    )
    return '\n'.join(rows)


def _commission_text(req,segment,event,pictures,wardrobe,slots,continuity=False,scene_schedule=None):
    scene_schedule=scene_schedule or []
    """Give 9B the locked facts FIRST, this clip's action SECOND, craft LAST.

    Fixed world/setup prose and previous/future script never enter this packet.
    Picture references establish face/hairstyle; current clothing overrides
    clothing in those pictures only when this clip has an explicit outfit lock.
    """
    lines=[
        '=== 1. CURRENT CLIP HARD LOCKS — PYTHON AUTHORITY ===',
        f'CLIP DURATION: {float(segment["seconds"]):.3f}s (all times clip-local).',
        'CURRENT WARDROBE — use these exact present outfits where assigned:',
    ]
    for role,number in (('S1',1),('S2',2)):
        ref=pictures[role]
        if role in wardrobe:
            lines.append(
                f'<Subject {number}> ({role}): face and hairstyle from {ref} ONLY. '
                f'CURRENT OUTFIT: {wardrobe[role]}. '
                'This outfit overrides clothing visible in the reference photo.')
        else:
            lines.append(
                f'<Subject {number}> ({role}): face and hairstyle from {ref}. '
                'CURRENT OUTFIT: preserve the already-established outfit in this '
                'clip opening/current event; do not invent a costume change.')
    lines.extend((
        'SRT VOCAL WINDOWS — NOT CAMERA CUT POINTS:',
        *_global_vocal_rows(slots),
        'LOCKED SHOT SLOTS — preserve the numbered camera slots below.',
        'If showing lip-sync in a tagged window, choose the specified performer. Untagged moments follow the scene.',
    ))
    for slot in slots:
        lines.append(
            f'[Shot {slot["number"]}] {slot["start"]:.3f}–{slot["end"]:.3f}s')
        scene_row=_active_scene(scene_schedule,slot['start']) if scene_schedule else None
        if scene_row:
            lines.append('  SCENE LOCK: '+scene_row['scene']
                         +' — this scene starts here; do not reenact a costume change.')
            for role in ('S1','S2'):
                if role in scene_row['wardrobe']:
                    lines.append('  '+role+' CURRENT OUTFIT: '+scene_row['wardrobe'][role])
        lines.append('  OPTIONAL LIP-SYNC: use the cast hints above when useful.')
        lines.append('  FILL VISUALS: camera, expression, body movement, light and reactions.')
    lines.append('')
    lines.append('=== 2. CURRENT EVENT / ESTABLISHED OPENING STATE ===')
    if continuity:
        lines.append(
            'OPENING CONTINUITY: <Picture 1> supplies an actual prior temporal '
            'frame for pose, object placement, lighting and motion continuity. '
            'It is not a new performer or the source of current clothing. '
            'Continue the current action without narrating previous events.')
    else:
        lines.append(
            'OPENING CONTINUITY: start directly with the assigned current event; '
            'do not invent what happened in earlier clips.')
    lines.append('THIS CLIP EVENT (film its assigned actions, no future outcome):')
    lines.append(event)
    props=[x.strip()[2:] for x in event.splitlines()
           if x.strip().startswith('- ') and PROPS.search(x)]
    if props:
        lines.append('CURRENT PROPS / HANDLING (only established in this event):')
        lines.extend('- '+x for x in props)
    lines.extend((
        '',
        '=== 3. CINEMATOGRAPHY AND OUTPUT RULES ===',
        'Camera energy: '+str(req.get('intensity','high'))+'.',
        'Fill each assigned [Shot N] with specific camera placement, framing, '
        'moving subjects, light, reactions and physical cause/effect. '
        'Use natural lip-sync where appropriate and use tagged SRT to choose the visible performer.',
        'Use <Subject 1>/<Subject 2> for people in shot prose. '
        'The <Picture N> labels above identify reference assets, not actor actions.',
        'Keep the present scene, wardrobe and object state consistent. '
        'Do not repeat completed events, invent future scenes, swap the singer, '
        'create new dialogue/lyrics, or change any locked Shot boundary.',
        'Use the native six-section Ref2VA format below as your OUTPUT SHAPE. '
        'Keep fixed sections unchanged and WRITE ONLY the visual performance '
        'and camera inside each detailed_description shot. '
        'Do not copy the words WRITE THIS SHOT into the answer.',
    ))
    lines.extend((
        '',
        '=== NATIVE H3 REF2VA SIX-SECTION OUTPUT TEMPLATE ===',
        _native_output_template(slots,pictures,wardrobe),
    ))
    return '\n'.join(lines)


def write_locked_shoot_prompt(cfg,req,segment,event,fixed,pictures,wardrobe,refs,images,rewrite,progress=None):
    cues=vocal_timeline(excerpt(req,segment))
    scene_schedule=scene_wardrobe_schedule(event,fixed,pictures,segment['seconds'])
    if scene_schedule:
        segment['scene_wardrobe_schedule']=scene_schedule
    else:
        segment.pop('scene_wardrobe_schedule',None)
    cuts=[row['start'] for row in scene_schedule[1:]]
    slots=plan_slots(segment['seconds'],cues,segment.get('audio_evidence'),
                     req.get('dynamic_cuts',True),scene_cuts=cuts)
    task=_commission_text(
        req,segment,event,pictures,wardrobe,slots,continuity=len(refs)>2,
        scene_schedule=scene_schedule)
    images_parts=images
    calls=0
    retry_limit=rewrite_retry_count(req)
    max_calls=(retry_limit+1)*(3+2*len(slots))
    def call(parts,t,system=SYSTEM):
        nonlocal calls
        calls+=1
        if progress:
            progress({'stage':'rewriting','clip_index':segment['index'],
                      'attempt':calls,'max_attempts':max_calls})
        return rewrite(_cfg(cfg,t),system,parts,uuid.uuid4().hex[:8])
    # Two focused repairs per draft; if the director still contradicts the
    # Python-locked shots, discard the rejected draft and ask 9B to reshoot
    # its prose from the SAME current-clip commission (never the whole song).
    for restart in range(retry_limit+1):
        blocks=None;why=''
        for attempt in range(3):
            prompt=task if not why else task+'\nFORMAT REMINDER: '+why+'\nReturn the exact native six-section Ref2VA structure, with every assigned [Shot N] in detailed_description.'
            try:
                blocks=_extract(call(images_parts+[('text',prompt)],.4 if attempt==0 else .15),slots)
                break
            except ValueError as error:
                why=str(error)
        if blocks is None:
            failure=SceneStateError('9B 無法填入 Python 鏡頭骨架：'+why)
            if restart<retry_limit:
                continue
            raise failure
        blocks,vocal_fixes=_repair_vocals(blocks,slots,fixed)
        failure=None
        for attempt in range(3):
            errors=_errors(blocks,wardrobe,scene_schedule,slots)
            if not errors:
                break
            segment['commission_guard_errors']=[msg for messages in errors.values() for msg in messages]
            if attempt>=2:
                failure=SceneStateError('9B 兩次局部修稿仍有衝突：'+' | '.join(segment['commission_guard_errors']))
                break
            for number,messages in errors.items():
                shot=slots[number-1]
                instruction=(
                    f'REPAIR ONE SHOT ONLY: [Shot {number}] '
                    f'({shot["start"]:.3f}–{shot["end"]:.3f}s, clip-local).\n'
                    'PYTHON-AUTHORIZED VOCALS:\n' + '\n'.join(shot['rows']) +
                    '\nCURRENT WARDROBE: ' + repr(wardrobe) +
                    '\nCONCRETE ERRORS TO FIX (no other edits):\n' +
                    '\n'.join(messages) +
                    '\nORIGINAL VISUAL PARAGRAPH TO EDIT:\n' + blocks[number] +
                    '\nKeep its camera framing, movement, staging, lighting and '
                    'valid singing. Fix only the specified error. '
                    'Copy the following H3 native SIX-SECTION structure and '
                    'replace only the detailed_description shot body. '
                    'Keep all other fixed fields and do not add other shots. '
                    'The answer must begin with subject_definitions:\n' +
                    _native_output_template([shot],pictures,wardrobe)
                )
                try:
                    blocks[number]=_extract(call([('text',instruction)],.15,REPAIR_SYSTEM),slots,only=number)[number]
                    blocks,new_fixes=_repair_vocals(blocks,slots,fixed)
                    vocal_fixes.extend(new_fixes)
                except ValueError as error:
                    failure=SceneStateError(f'9B 第 {number} 鏡修稿格式失敗：{error}')
                    break
            if failure is not None:
                break
        if failure is not None:
            if restart<retry_limit:
                continue
            raise SceneStateError(
                f'9B 自動重新起稿 {restart} 次後仍未通過：{failure}') from failure
        segment.pop('commission_guard_errors',None)
        segment['vocal_auto_corrections']=vocal_fixes
        segment['prompt_profile']={'source':'python_locked_srt_shots','writer_calls':calls,
                                   'contract_check_calls':1+attempt,'python_shot_count':len(slots),
                                   'vocal_auto_correction_count':len(vocal_fixes),
                                   'fresh_restarts':restart}
        return _native(blocks,slots,pictures,wardrobe,len(refs)>2,event,len(refs),fixed,scene_schedule)
