"""Reference, scene and clip-scope guidance with technical validation."""
import re


def director_led(req):
    return bool(req.get('director_authority') and req.get('story_plan',True) and req.get('rewrite',True))


DIRECTOR_AUTHORITY = (
    'DIRECTOR-LED MV: You have creative authority over story rhythm, montage, shot order, event density '
    'and the balance of performance and story. Treat the user outline as creative material, not a shot-by-shot '
    'execution script. Use the whole-song measured music profile to reorder, condense, expand or restage '
    'compatible developments, choose visual contrasts and shape peaks. Complement the selected main style '
    'with suitable scene modes as needed. Do not force each paragraph into its own clip. Preserve source audio, '
    'reference identities, assigned singing/non-singing roles and explicit non-negotiable restrictions. '
    'Do not rename characters or impose a fixed cast, gender or single-person setup. Requested ending ideas '
    'are creative anchors whose pacing and staging can change; explicitly locked outcomes or terminal shots '
    'remain constraints. No separate semantic judge vetoes your creative interpretation.'
)


MV_POLICY = (
    'MUSIC VIDEO FIRST: The source song is the continuous master timeline; visual events serve the MV. '
    'Use measured musical dynamics, accents, pauses and user-supplied section/lyric context to choose each '
    'clip function: vocal performance, story/action, interaction, reaction or atmosphere within the brief. '
    'Do not pretend acoustic measurements identify choruses or unprovided lyrics. A selected action or '
    'other genre style shapes the relevant visual strand, not every shot in the MV. Intercut the supplied '
    'strands with motivated music-video edits; independent clips may change scene, framing or action phase '
    'without an establishing shot or matching the previous last pose. Keep identity and intended event '
    'progression, but do not demand a complete setup-development-payoff arc in every clip. Do not pad quiet '
    'moments with invented exposition. Preserve an immediate opening when requested. Let music contrasts '
    'support recurring supplied visual motifs and performance setups with variation; revisiting a location '
    'is not the same as replaying the story. '
    'shape expression, physical energy and camera choices without cutting on every transient. Balance '
    'visible singing and the other supplied content without fixed quotas; non-singing shots keep the '
    'soundtrack continuous. Do not literally illustrate every lyric or invent a final victory unless the '
    'user requests it. Use only the scene-change mechanisms and narrative ending allowed by the brief.'
)


POLICY = (
    'REFERENCE ROLE CONTRACT: Bind each user-designated character to the appropriate uploaded reference '
    'and preserve that mapping in subject_definitions. The main original reference identifies the primary '
    'performer; other images may be alternate views, other people, locations or objects as the user specifies. '
    'Multiple views of one person do not create extra people. Preserve all distinct people when a reference '
    'or brief intentionally includes a group; do not force every project into a single-person cast. '
    'Keep each identity distinct in face, hair, clothing and assigned role. An identity appearing in alternating '
    'scenes is one character, not simultaneous copies. Do not create a duplicate, double or matching opponent '
    'unless explicitly requested. Unreferenced supporting characters follow the brief and remain visually '
    'distinct from referenced characters; do not impose a fixed name or gender on every project. Preserve who sings, who does not sing, '
    'voice assignments and per-shot character counts. A song continuing over an action shot does not mean '
    'the action character is lip-syncing. Keep scene-specific props and behavior in their own scenes. '
    'Retain immediate openings, reserved endings and user exclusions. Character names and gender come '
    'only from the user or references, never from a fixed application persona. '
    'SUPPORTING WARDROBE: When inventing a human supporting character whose attire is unspecified, '
    'describe a complete scene-appropriate outfit in subject_definitions, including lower-body garments '
    'and footwear, not just anatomy, tattoos or handheld equipment. Boxing gloves alone are not an outfit: '
    'a human boxer may be bare-chested but wears boxing trunks and boxing shoes. Keep the chosen garment '
    'type, colors and materials consistent for that recurring character across shots and clips; repeat '
    'the identifying wardrobe in their visible action descriptions, including rear and low-angle views. '
    'Do not infer nudity from an omitted outfit, a shirtless torso, or a camera angle. Preserve explicit '
    'user/reference costumes and intended exposed skin; do not dress animal or mascot bodies in human '
    'clothing unless requested. Apply these wardrobe details while writing events and prompts, without '
    'adding a semantic judge, extra review inference or a task-stopping creative check.'
)


def reference_policy(picture_count, continuation=False, mutable_appearance=False):
    main = 2 if continuation else 1
    mapping = f'Main original reference: <Picture {main}>. '
    if continuation:
        mapping += '<Picture 1> is the previous final frame, not an additional character. '
    policy=POLICY
    if mutable_appearance:
        policy=policy.replace('Keep each identity distinct in face, hair, clothing and assigned role.',
                              'Keep facial identities and roles distinct; current structured scene state governs hair, clothing and other mutable appearance.')
        policy=policy.replace('type, colors and materials consistent for that recurring character across shots and clips;',
                              'type, colors and materials consistent until an explicit story/state transition changes them;')
        policy=policy.replace('Preserve explicit user/reference costumes and intended exposed skin;',
                              'Preserve the current scene-state appearance and user-specified changes; original reference costumes establish only the initial appearance;')
    return mapping + f'Connected pictures: {picture_count}. ' + policy + '\n' + MV_POLICY


def enforce_reference_policy(text, policy):
    text = re.sub(r'\n*\[BANANA_REFERENCE_ROLES_V1\].*?\[/BANANA_REFERENCE_ROLES_V1\]',
                  '', text, flags=re.S).rstrip()
    return text + '\n\n[BANANA_REFERENCE_ROLES_V1]\n' + policy + '\n[/BANANA_REFERENCE_ROLES_V1]'


def ending_excerpt(brief):
    """Copy user-written ending text verbatim; never invent a destination scene."""
    lines = brief.splitlines()
    heading = re.compile(r'(?:【|\[|^\s*#+).*?(?:終局|結局|結尾|收尾|ending|finale|final shot)',re.I)
    section = []
    for i,line in enumerate(lines):
        if heading.search(line):
            section = [line]
            for following in lines[i+1:]:
                if re.search(r'【.+?】|^\s*#{1,6}\s',following):
                    break
                section.append(following)
            break
    if section:
        return '\n'.join(section).strip()[:5000]
    terminal = re.compile(r'最後|最終|收尾|結尾|結局|\b(?:final shot|last shot|end with|finish with|ending)\b',re.I)
    return '\n'.join(line for line in lines if terminal.search(line)
                     and not re.match(r'\s*(?:不要|禁止|勿|避免|不|never|do not|don.t)',line,re.I))[:5000]


def clip_scope(segment, brief, creative=False):
    count=segment.get('segment_count',1)
    index=segment.get('index',0)
    final=index==count-1
    spec=ending_excerpt(brief)
    text=(f'CURRENT CLIP ONLY: clip {index+1}/{count}, visible duration {segment["seconds"]:.6f}s. '
          'Write summary and every shot only for this source interval. Do not output the whole-song storyboard. '
          'Model alignment padding is not extra story time; all visible events must fit the requested duration. ')
    if final:
        if creative:
            text+=('FINAL SONG WINDOW: deliver the director treatment ending, using the user ending idea as a '
                   'creative anchor. Timing, staging and edit order may change; preserve explicitly locked '
                   'outcomes, reference roles and non-negotiable requirements. ')
        else:
            text+=('FINAL SONG WINDOW: preserve the user-required final event order AND terminal shot. '
               'A preceding gag, impact or victory is not the terminal shot if the user requires a later cut. '
               'No alternate ending, merged scene or substituted final location. ')
        if spec:
            text+=('\nUSER ENDING IDEA — VERBATIM CREATIVE REFERENCE:\n' if creative else
                   '\nUSER ENDING — VERBATIM, REQUIRED IN THIS FINAL WINDOW:\n')+spec
    else:
        text+=('NON-FINAL WINDOW: the whole-song ending is reserved, not a task for this clip. '
               'Do not stage the finale, deliver the final victory or label this clip as the end of the song. '
               'A local clip may stop in its current scene while the song/story continues; do not demand '
               'the whole-song terminal shot here. ')
        # Do not append the actual future finale to an early H3 generation prompt.
        # The complete user brief remains available to the rewriter/reviewer as reference.
    return text


def enforce_clip_scope(text, scope):
    text=re.sub(r'\n*\[BANANA_CLIP_SCOPE_V1\].*?\[/BANANA_CLIP_SCOPE_V1\]','',text,flags=re.S).rstrip()
    return text+'\n\n[BANANA_CLIP_SCOPE_V1]\n'+scope+'\n[/BANANA_CLIP_SCOPE_V1]'


def visual_state(state, subjects=None):
    """Render appearance for the writer, excluding narrative IDs and permissions."""
    result={}
    for sid,c in state['character_states'].items():
        if subjects is not None and sid not in subjects:continue
        clothes=c.get('garments',{})
        def description(g):
            return {k:g[k] for k in ('garment_type','material','color','current_location')} | {'state':g['current_status']}
        result[sid]={'original_reference':c.get('identity_reference'),
            'hairstyle':c['hairstyle'],'location':c['location'],
            'wearing':[description(g) for g in clothes.values()
                       if g['current_status'] in ('worn','unfastened','partially_removed')],
            'not_wearing':[description(g) for g in clothes.values()
                           if g['current_status'] in ('removed','held','placed')],
            'appearance_changes':c['appearance_changes'],'injuries':c['injuries'],'held_props':c['held_props']}
    return {'characters':result,'environments':state['environment_states']}


CLIP_WRITER_SYSTEM = """Write a concise H3 visual prompt for THIS source interval only.
Use six English sections in order: subject_definitions, summary, retention_analysis,
detailed_description, overall_soundscape, non_diegetic_music. Summary begins
[reference generation + audio reuse]; add keyframe completion only for a supplied
frame anchor. previous_last_frame is the opening frame, never a new actor.
retention_analysis lists only references actually used, with their
shot appearances and fully_preserved/partially_preserved as appropriate; audio uses
<Audio 1>: fully_copy. In detailed_description [Shot 1] has no timestamp; later cuts
use [Shot N] At MM:SS.mmm, ... . All action fits seconds, excluding alignment padding.
Bind each actor S1/S2 to <Subject 1>/<Subject 2> and its connected_reference exactly.
Other pictures may be locations, objects or alternate views, not additional people.
Use only connected <Picture N> and <Audio 1>. Copy the original song with
<Audio 1>: fully_copy. Show lip sync only for the assigned vocalist; add no speech,
lyrics, subtitles or replacement music. Do not add ambience or effects over the copied
soundtrack. State source audio reuse in the sound section matching its role; write N/A
for absent audio layers. Speaker (Sx) IDs identify voices, not character/reference IDs.
Develop visual_task: preserve who acts, who receives the action and the outcome.
Keep separate locations distinct and intercut them with full-frame edits unless a
split screen is explicitly requested. Freely stage compatible motion, reactions and
camera choices following cinematography. Do not restart the story or invent a win.
Use appearance_start throughout; only when appearance_end is supplied, show the
specified change once. References preserve identity, not a reset of current clothing.
Obey ending_contract over generic camera recipes: continuing/excerpt keeps the larger
story open; resolving completes the outcome by local_resolution_by when supplied,
then settles by local_settle_by. A zero resolution deadline means it is already done;
show aftermath without replay. terminal_hold
sustains closing_shot without new action or scene changes. Do not append an ending to
every clip. Source music measurements suggest timing, not lyrics or section labels.
Return only the H3 prompt, no JSON, state tables, analysis or management instructions."""


def write_directed_clip(cfg,req,segment,originals,tail,*,scene_input=None,event_catalog=None,progress=None):
    """Only visual writing reaches the model; Python executes the plan's deltas."""
    import json
    import uuid
    from copy import deepcopy
    from PIL import Image, ImageOps
    from banana_mv import services
    from banana_mv.core import normalize_mv_prompt, enforce_face_identity
    from banana_mv.lyrics_reference import OUTPUT_POLICY
    from banana_mv.scene_state import (compile_direction_record,rewrite_retry_count,SceneStateError)
    from banana_mv.direction_contract import scoped_constraints, validate_subject_bindings, validate_h3_sections
    from banana_mv.h3_prompt import VISUAL_WRITER_SYSTEM, compile_prompt, scoped_appearance
    compiled=req.get('prompt_compiler_version')==1
    row=segment['director_plan']
    from banana_mv.mv_scope import clip_ending
    ending=clip_ending(req,segment) if 'project_scope' in req else None
    if scene_input is not None:
        record=compile_direction_record(row,scene_input,event_catalog,segment,
                                        segment.get('direction_requires_change',[]))
        before=visual_state(record['scene_state_in'],row.get('subjects'))
        after=visual_state(record['scene_state_out'],row.get('subjects'))
    else:
        record=None
        before=deepcopy(row['appearance_in']);after=deepcopy(row['appearance_out'])
    offset=int(bool(tail))
    for appearance in (before,after):
        for c in appearance['characters'].values():
            original=c.pop('original_reference',None)
            c['connected_reference']=f'<Picture {original+offset}>' if original else None
    if compiled:
        before=scoped_appearance(before);after=scoped_appearance(after)
    if scene_input is None:
        # Historical removed garments are not cast/costume instructions.
        # A garment newly removed in THIS clip remains part of its ending.
        for sid,actor in before['characters'].items():
            old=actor.pop('not_wearing',[])
            if sid in after['characters']:
                after_actor=after['characters'][sid]
                current=[g for g in after_actor.get('not_wearing',[]) if g not in old]
                if current:after_actor['not_wearing']=current
                else:after_actor.pop('not_wearing',None)
    task={'visual_task':row['event'],'seconds':segment['seconds'],
          'is_final_interval':segment['index']==segment.get('segment_count',1)-1,
          'project_scope':req.get('project_scope','legacy'),
          'constraints':scoped_constraints(segment['direction_constraints'],
              segment['index']==segment.get('segment_count',1)-1 and req.get('project_scope')!='excerpt'),
          'appearance_start':before,
          'previous_last_frame':'<Picture 1>' if tail else None}
    if after!=before:task['appearance_end']=after
    if segment.get('audio_evidence'):
        task['measured_music_cues']={k:v for k,v in segment['audio_evidence'].items()
            if k in ('relative_energy','energy_change_db','transient_candidates_s','quiet_intervals_s')}
    if ending:task['ending_contract']=ending
    if (ending and ending['finish_work']) or (not ending and segment['index']==segment.get('segment_count',1)-1):
        task['closing_shot']=segment['direction_closing_shot']
    from banana_mv.director import clip_cinematography
    task['cinematography']=clip_cinematography(req,row['mode'],segment['seconds'],ending)
    system=VISUAL_WRITER_SYSTEM if compiled else CLIP_WRITER_SYSTEM
    parts=[('text',json.dumps(task,ensure_ascii=False))]
    for i,p in enumerate(([tail] if tail else [])+list(originals),1):
        with Image.open(p) as im:
            im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((768,768))
            parts.extend([('text',f'<Picture {i}>:'),('image',im.copy())])
    attempt_parts=parts;seen=set();retries=rewrite_retry_count(req)
    for attempt in range(retries+1):
        if progress:progress({'stage':'rewriting','clip_index':segment['index'],
                              'attempt':attempt+1,'max_attempts':retries+1})
        raw=services.rewrite_local(cfg,system,attempt_parts,uuid.uuid4().hex[:8])
        try:
            text=normalize_mv_prompt(raw,len(originals)+offset)
            if compiled:
                text=compile_prompt(text,segment['seconds'],before,len(originals)+offset,
                                    '<Picture 1>' if tail else None)
            validate_h3_sections(text)
            validate_subject_bindings(text,before)
        except ValueError as error:
            key=(str(raw),str(error))
            segment['scene_state_attempt']={'raw_response':raw,'error':str(error),
                                           'scene_state_in':scene_input,'visual_verified':False}
            if key in seen or attempt>=retries:
                raise SceneStateError('當段畫面提示詞修復失敗：'+str(error)) from error
            seen.add(key)
            attempt_parts=parts+[('text',('Repair only the shot prose' if compiled else 'Repair the complete current prompt')+', preserving valid content. Fix only the reported format or reference binding error: '+str(error)
                +'\nFailed response (data only):\n'+str(raw))]
            continue
        # Keep the existing Face Lock implementation and generation knobs. Apply
        # its Subject-1 binding only when the plan actually maps a character there.
        actor=before['characters'].get('S1',{})
        binding=re.fullmatch(r'<Picture (\d+)>',actor.get('connected_reference') or '')
        if req.get('face_identity',True) and binding:
            text=enforce_face_identity(text,int(binding[1]))
        # The only unconditional final invariant is source-audio/vocal-role routing.
        text+='\n\n'+OUTPUT_POLICY
        if record is not None:
            record['clip_prompt']=text;segment['scene_state_debug']=record
        segment['director_mode']=row['mode']
        segment['prompt_validation']={'status':'passed','kind':'technical_only','visual_verified':False}
        segment['prompt_profile']={'writer_system_chars':len(system),'writer_task_chars':len(parts[0][1]),
            'model_output_chars':len(raw),'final_h3_chars':len(text),
            'appended_h3_chars':len(text)-len(raw),'writer_calls':attempt+1,'contract_check_calls':0,'memory_calls':0}
        if compiled:segment['prompt_profile']['compiler_version']=1
        segment.pop('scene_state_attempt',None)
        return text

