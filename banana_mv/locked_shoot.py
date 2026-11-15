"""Python-locked vocal shot schedule and native Ref2VA assembly for 5070."""
import copy
import re
import uuid

from banana_mv.commission_guard import _BEACH, _OLD_S1, _OLD_S2
from banana_mv.direction_contract import validate_h3_sections
from banana_mv.lyrics_reference import excerpt, vocal_timeline
from banana_mv.scene_state import SceneStateError

SHOT = re.compile(r'(?im)^\s*\[Shot\s+(\d+)\]\s*')
STAMP = re.compile(r'^\s*(?:At\s+)?\d\d:\d\d(?:\.\d{1,3})?[,;:]?\s*', re.I)
# Recognize explicit *positive* singer actions without mistaking spectators.
VOCAL_ACTION = re.compile(
    r'(?i)(?<!\w)(?P<actor><Subject\s+[12]>|S[12]|he|she|him|her|both|they|the\s+two)'
    r'(?!\w)(?:\s*\(S[12]\))?'
    r'(?P<link>(?:\s+(?:is|are|was|were|has|have|been|begins?|starts?|'
    r'started|continues?|continuing|keeps?|kept|still|visibly|clearly|'
    r'softly|loudly|to|shown|seen)){0,5}\s+)'
    r'(?P<verb>sing(?:s|ing)?|lip[ -]?sync(?:s|ing)?|mouth\s+(?:moves|moving))\b'
)
PROPS = re.compile(r'泳圈|毛巾|車鑰匙|鑰匙|外出包|背包|吉他|手機|主機|螢幕', re.I)
SYSTEM = (
    'Fill Python-numbered [Shot N] slots with camera and acting details. '
    'Do not write shot timestamps, new lyrics, dialogue, sound effects, '
    'or six H3 sections. Natural singing and lip-sync are encouraged '
    'when that performer is authorized by the SRT schedule for this shot. '
    'Never switch performers or invent a duet; silent characters may react. '
    'Python owns exact singer timing and identity. Use only <Subject 1> and '
    '<Subject 2> for the two actors; never use <Picture N> in shot prose. '
    'Keep the assigned shot count and story events. Develop detailed framing, '
    'spatial continuity, light, lens perspective, expressions, body actions, '
    'causal responses and camera movements. No future or previous story events. '
    'Reference-image clothing is subordinate to CURRENT WARDROBE.'
)

def singer_rows(a,b,cues):
    edges={a,b}
    for cue in cues:
        x=max(a,float(cue['clip_start']))
        y=min(b,float(cue['clip_end']))
        if y>x:
            edges.update((x,y))
    points=sorted(edges)
    rows=[]
    for x,y in zip(points,points[1:]):
        if y-x<.001:
            continue
        roles=set()
        for cue in cues:
            if float(cue['clip_start'])<=x+.001 and float(cue['clip_end'])>=y-.001:
                roles.update(r for r in cue.get('subjects',()) if r in ('S1','S2'))
        who=tuple(sorted(roles))
        if who==('S1',):
            v='<Subject 1> (S1) ONLY lip-syncs; <Subject 2> is silent.'
        elif who==('S2',):
            v='<Subject 2> (S2) ONLY lip-syncs; <Subject 1> is silent.'
        elif who==('S1','S2'):
            v='<Subject 1> (S1) AND <Subject 2> (S2) lip-sync together.'
        else:
            v='No assigned visible lip-sync; use physical acting and reaction.'
        rows.append(f'{x:.3f}–{y:.3f}s: '+v)
    return rows

def plan_slots(seconds,cues,evidence=None,dynamic=True):
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
        cuts=[cuts[0]]+[t for t in cuts[1:-1] if t>=1 and duration-t>=.8][:6]+[duration]
    return [{'number':i+1,'start':a,'end':b,'rows':singer_rows(a,b,cues),
             'allowed_singers':sorted({r for cue in cues
                 if float(cue['clip_start']) < b and float(cue['clip_end']) > a
                 for r in cue.get('subjects',()) if r in ('S1','S2')})}
            for i,(a,b) in enumerate(zip(cuts,cuts[1:]))]

def _extract(raw,slots,only=None):
    text=re.sub(r'<think>.*?</think>','',raw,flags=re.I|re.S)
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
    expected={only} if only else {s['number'] for s in slots}
    if set(blocks)!=expected:
        raise ValueError('9B 必須填寫這些指定鏡頭：'+repr(sorted(expected))+'；實際：'+repr(sorted(blocks)))
    return blocks

def _pronoun_roles(fixed):
    """Read the explicitly described genders; never infer from picture order."""
    male=[];female=[]
    for line in fixed.splitlines():
        m=re.match(r'^\s*(S[12])\s*[=:：]\s*<Picture \d+>(.*)$',line,re.I)
        if not m:continue
        role,details=m[1].upper(),m[2]
        if re.search(r'\bmale\b|\bman\b|\bboy\b|男主|男聲|男主唱',details,re.I):
            male.append(role)
        if re.search(r'\bfemale\b|\bwoman\b|\bgirl\b|女主|女聲|女主唱',details,re.I):
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
        def correct(match):
            assigned=_vocal_role(match['actor'],pronouns)
            if not assigned or assigned <= allowed:return match[0]
            replacement=(match[0][:match.start('verb')-match.start()]
                         +_quiet_verb(match['verb']))
            audit.append({'shot':number,'from':match[0],'to':replacement,
                          'allowed_singers':sorted(allowed)})
            return replacement
        revised[number]=VOCAL_ACTION.sub(correct,revised[number])
    return revised,audit


def _errors(blocks,wardrobe):
    problems={}
    for n,body in blocks.items():
        bad=[]
        if re.search(r'<Picture\s+\d+>',body):
            bad.append('[ERROR][Cast] [Shot '+str(n)+'] use only <Subject 1>/<Subject 2> in acting prose.')
        if wardrobe:
            if 'S1' in wardrobe and _OLD_S1.search(body):
                bad.append('[ERROR][Wardrobe] [Shot '+str(n)+'] S1 must wear a short-sleeve top and shorts, not earlier apartment clothing.')
            if 'S2' in wardrobe and _OLD_S2.search(body):
                bad.append('[ERROR][Wardrobe] [Shot '+str(n)+'] S2 must wear a white tie-string bikini, not earlier apartment clothing.')
        if bad:
            problems[n]=bad
    return problems

def _cfg(cfg,temperature):
    c=dict(cfg);c['rewriter']=dict(cfg['rewriter'],temperature=temperature,thinking=False)
    return c

def _native(blocks,slots,pictures,wardrobe,tail,event,ref_count,fixed=''):
    scene='beach / shoreline' if _BEACH.search(event) else ('current apartment' if re.search(r'公寓|客廳|玄關|工作區|電腦桌|沙發',event) else 'the current assigned setting')
    definitions=[];retention=[]
    for role,n in (('S1',1),('S2',2)):
        ref=pictures[role]
        costume=wardrobe.get(role,'the current outfit in the assigned reference unless this event explicitly changes it')
        cast_line=next((line for line in fixed.splitlines() if re.match(r'^\s*'+role+r'\s*[=:：]',line,re.I)), '')
        gender=('male ' if re.search(r'男主|男聲|男主唱|male',cast_line,re.I) else
                'female ' if re.search(r'女主|女聲|女主唱|female',cast_line,re.I) else '')
        definitions.append(f'<Subject {n}> is the adult '+gender+f'lead {role} from {ref}; identity, face and hair are preserved. CURRENT CLOTHING: {costume}. Location: {scene}.')
        retention.append(f'<Subject {n}>: partially_preserved - identity from {ref}; current clothing is {costume}, overriding an obsolete outfit in reference images.')
    if tail:
        definitions.append('<Picture 1> is the preceding frame only, not a new actor or wardrobe reset.')
    retention.append('<Audio 1>: fully_copy, including the original recorded vocals.')
    film=[]
    for s in slots:
        n=s['number'];start=s['start']
        mark=f'[Shot {n}] ' if n==1 else f'[Shot {n}] At {int(start)//60:02d}:{start%60:06.3f}, '
        film.append(mark+' '.join(s['rows'])+' '+blocks[n])
    output='\n\n'.join((
        'subject_definitions:\n'+'\n'.join(definitions),
        'summary:\nThe current event unfolds in '+scene+' through photography and physical character interaction, following existing voices in the original track.',
        'retention_analysis:\n'+'\n'.join(retention),
        'detailed_description:\nUse the original song from <Audio 1> unchanged (fully_copy). Assigned SRT singer permissions below are authoritative. No added vocals, spoken dialogue, text overlays or subtitles.\n'+'\n'.join(film),
        'overall_soundscape:\nThe supplied source song plays unchanged.',
        'non_diegetic_music:\nThe supplied source song.'
    ))
    validate_h3_sections(output)
    if any(int(p)>ref_count for p in re.findall(r'<Picture (\d+)>',output)):
        raise SceneStateError('Python H3 定裝引用了未連接圖片。')
    return output

def _commission_text(req,segment,event,pictures,wardrobe,slots,continuity=False):
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
        'LOCKED SHOT SLOTS — preserve every Shot number and start/end time.',
        'Python has assigned the exact SRT vocalist in each subinterval. '
        'Only that vocalist lip-syncs; others may react silently.',
    ))
    for slot in slots:
        lines.append(
            f'[Shot {slot["number"]}] {slot["start"]:.3f}–{slot["end"]:.3f}s')
        lines.extend('  VOCAL LOCK: '+row for row in slot['rows'])
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
        'Natural lip-sync is welcome only for its Python-assigned SRT singer.',
        'Use <Subject 1>/<Subject 2> for people in shot prose. '
        'The <Picture N> labels above identify reference assets, not actor actions.',
        'Keep the present scene, wardrobe and object state consistent. '
        'Do not repeat completed events, invent future scenes, swap the singer, '
        'create new dialogue/lyrics, or change any locked Shot boundary.',
        'Return only the numbered [Shot N] visual bodies, one per locked slot. '
        'Python assembles the six native H3 sections, audio policy and exact '
        'sub-shot singer timing; do not write those sections yourself.',
    ))
    return '\n'.join(lines)


def write_locked_shoot_prompt(cfg,req,segment,event,fixed,pictures,wardrobe,refs,images,rewrite,progress=None):
    cues=vocal_timeline(excerpt(req,segment))
    slots=plan_slots(segment['seconds'],cues,segment.get('audio_evidence'),req.get('dynamic_cuts',True))
    task=_commission_text(
        req,segment,event,pictures,wardrobe,slots,continuity=len(refs)>2)
    images_parts=images
    calls=0
    def call(parts,t):
        nonlocal calls
        calls+=1
        if progress:
            progress({'stage':'rewriting','clip_index':segment['index'],'attempt':calls,'max_attempts':1+2*len(slots)})
        return rewrite(_cfg(cfg,t),SYSTEM,parts,uuid.uuid4().hex[:8])
    blocks=None;why=''
    for attempt in range(3):
        prompt=task if not why else task+'\nFORMAT REPAIR: '+why+'\nReturn every [Shot N] exactly once.'
        try:
            blocks=_extract(call([('text',prompt)]+images_parts,.4 if attempt==0 else .15),slots)
            break
        except ValueError as error:
            why=str(error)
    if blocks is None:
        raise SceneStateError('9B 無法填入 Python 鏡頭骨架：'+why)
    blocks,vocal_fixes=_repair_vocals(blocks,slots,fixed)
    for attempt in range(3):
        errors=_errors(blocks,wardrobe)
        if not errors:
            break
        segment['commission_guard_errors']=[msg for messages in errors.values() for msg in messages]
        if attempt>=2:
            raise SceneStateError('9B 兩次局部修稿仍有衝突：'+' | '.join(segment['commission_guard_errors']))
        for number,messages in errors.items():
            s=slots[number-1]
            instruction=(f'REPAIR ONLY [Shot {number}] within {s["start"]:.3f}–{s["end"]:.3f}s. '
                         'Any singing must use only the authorized performer in this shot. '
                         'Do not write any <Picture N> tags in acting prose. '
                         'Retain the camera, location and physical performance. '
                         'CURRENT WARDROBE: '+repr(wardrobe)+'\nERRORS:\n'+'\n'.join(messages)+
                         '\nPrevious body:\n'+blocks[number]+
                         f'\nOutput ONLY [Shot {number}] corrected visual body.')
            try:
                blocks[number]=_extract(call([('text',instruction)]+images_parts,.15),slots,only=number)[number]
                blocks,new_fixes=_repair_vocals(blocks,slots,fixed)
                vocal_fixes.extend(new_fixes)
            except ValueError as error:
                raise SceneStateError(f'9B 第 {number} 鏡修稿格式失敗：{error}') from error
    segment.pop('commission_guard_errors',None)
    segment['vocal_auto_corrections']=vocal_fixes
    segment['prompt_profile']={'source':'python_locked_srt_shots','writer_calls':calls,
                               'contract_check_calls':1+attempt,'python_shot_count':len(slots),
                               'vocal_auto_correction_count':len(vocal_fixes)}
    return _native(blocks,slots,pictures,wardrobe,len(refs)>2,event,len(refs),fixed)
