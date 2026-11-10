"""Allocate once; let the native H3 rewriter shoot each isolated interval."""
import json
import re
import uuid
from pathlib import Path

from banana_mv.core import map_image_mentions, normalize_mv_prompt
from banana_mv.director import MODES
from banana_mv.lyrics_reference import excerpt
from banana_mv.mv_scope import clip_ending, ending_contract
from banana_mv.scene_state import SceneStateError, atomic_json, digest, rewrite_retry_count


# Match Toybox's native Ref2VA enhancement role, rather than treating the
# specialized rewriter as a general JSON-task executor. The official guide stays
# authoritative for shot prose and output structure; MV source-audio rules follow
# in the user message. No additional writer or fixed camera recipe is involved.
NATIVE_ENHANCER_SYSTEM = (
    "You enhance prompts for reference-conditioned video and audio generation (Ref2VA). "
    "Use explicit bindings for referenced actors and the fixed designs for original supporting actors; never reassign a role by appearance or picture order. "
    "Preserve intent and explicit constraints while developing visual details. Source-audio and optional effects rules below override sound examples in the guide. "
    "Follow the guide below and return only its six sections in order, "
    "with plain-text headers on separate lines and no Markdown fences.\n\n"
)

CREATIVE_DIRECTION = """ADAPTATION: FREE. Act as an inventive MV director, not a literal script formatter.
Proactively develop striking visual events, performance business, interactions,
reaction details and environmental changes that serve the supplied story spine.
Make these choices even when the user supplies no camera or montage instructions.
Treat descriptive staging and camera suggestions as material to reinterpret, unless
explicitly mandatory. Preserve reference identities, vocal roles, fixed geography,
required causal milestones, specified outcome and explicit hard constraints.
Choose genre-appropriate camera positions, perspective, movement and editorial
juxtapositions. Use performance, inserts, reactions and environment as meaningful
coverage; create rhythmic, parallel, contrast or action-matched montage where useful.
Set intensity from the selected level and actual music/story passage. Precision means
committing to executable choices, including bold ones, while keeping cause and effect
readable. Develop the current beat without borrowing later milestones or replaying it.
"""

FAITHFUL_DIRECTION = """ADAPTATION: FAITHFUL. Preserve the supplied events, action meanings, causal
links, participants, props, order and specified camera requests. Translate them into
concrete expressive photography and editing without adding new story events.
"""


def adaptation_direction(req):
    return CREATIVE_DIRECTION if req.get('story_plan',True) else FAITHFUL_DIRECTION


REFERENCE_PERFORMANCE = """IDENTITY AND PERFORMANCE: For a referenced actor, preserve the assigned
reference identity and current appearance. References are identity anchors, not a
closed cast list. When the user requests supporting roles without reference images,
create original distinct characters as authorized; missing reference images do NOT
mean those characters cannot exist. Never turn the singer, boxer or another referenced
actor into a requested guitarist, bassist, drummer or other original supporting role.
Only an explicit user restriction forbids additional cast. Preserve original supporting
characters using their fixed name/role, appearance, costume, instrument and stage position;
do not demand an uploaded image, borrow an existing actor's face, or invent <Picture N>.
Use independent <Subject N> definitions with descriptions, without a false picture binding.
In both FREE and FAITHFUL adaptation, interpret broad wording
such as 'keep/maintain the reference image unchanged', 'match the reference completely'
or 'preserve appearance' as identity and appearance continuity, not a performance lock.
A pictured blink, closed eyes, neutral face, gaze or resting pose is a momentary state;
direct eyes opening, expressions changing and the body performing as the event requires.
Only an explicit instruction to sustain a particular expression, eye state, gaze or
pose makes that state a performance constraint for its stated scope.
A reference expression sheet demonstrates the same identity
in different states; it is not an acting menu or a limit on emotional range.
Direct facial expression, gaze, jaw tension, head/neck movement and body response as
changing performances driven by the current event, vocal-role timing and musical
context, at the selected intensity. Show a concrete emotional progression rather
than holding a reference expression throughout. In an angry vocal peak, give anger
visible physical expression; in other passages, choose the performance they require.
Keep subject_definitions focused on stable identity and describe evolving performance
inside the shots. In retention_analysis, preserve identity without claiming the pictured
expression or pose must stay unchanged. Explicit user performance requirements prevail.
An actual first/last-frame anchor constrains that boundary frame, not the entire clip.
Keep lip movement compatible with the supplied audio; add no new vocal material.
"""


AUTO_FILMING = """Direct the visual sequence first: decide what the viewer sees, how attention moves
between performance, action details, reactions and environment, and how those images
connect. Invent the coverage yourself from the current beat and adaptation policy;
the user need not supply a shot list. Select coverage before framing a visible singer
for readable lip sync. A whole event need not remain on the singer's face.
Then complete a concrete shooting decision for EVERY Shot before writing the final
prompt. Treat the following as required decision slots; choose their values freely
from the assigned events, references, genre and musical context:
1. TIME AND CONTINUITY: allocate the shot's local start and end within the clip.
Carry the preceding action state, positions, held objects and consequences forward,
including time off-screen. Budget readable actions and results, then ending holds.
2. SUBJECT AND ACTION: identify the visible subject and reference identity, the
attention or gesture target, the visible action progression and its end state.
3. CAMERA AND PERSPECTIVE: choose the camera's location relative to the subject,
height, viewing angle, shot size and perspective. Express lens effects concretely
when useful, such as spatial depth or compression; numerical focal lengths are optional.
4. COMPOSITION AND SPACE: place the subject in the frame with a clear scale; specify
foreground and background relationships, depth, gaze or movement direction and focus.
Describe the visible environment where an empty scene itself is the subject.
5. CAMERA MOVEMENT: choose a static camera or a specific movement. For movement,
state its direction, target, extent and speed; coordinate it with the visible action.
6. LIGHTING: choose scene-consistent light direction and quality, contrast and the
illuminated visual focus, at the selected photographic intensity.
Resolve every slot as an executable choice. A shot description states what is visible
and how it changes, rather than merely naming a cinematic technique.
Write these decisions naturally inside each Shot of detailed_description, using the
native guide's Shot labels and local cut times. The first shot begins at zero without
a timestamp; each later shot starts at its cut time, and the last ends at clip duration.
Keep the decision worksheet internal; deliver the existing native sections only.
Give adjacent shots independently chosen viewpoints and compositions serving their
attention shifts. Connect them through the same ongoing event and spatial relationships.
Develop compatible staging and performance freely within the assigned story;
primary_mode guides the passage without prescribing every shot's method.
"""

DYNAMIC_EDITING = """Dynamic editing is enabled: actively design editorial coverage, not just camera
movement. Separate changes of storyline from changes of viewpoint within a scene.
For an energetic passage with several distinct action or performance accents, use
purposeful short-shot coverage within that scene as well as intercuts. A scene visit
is not automatically one shot. Give each actual cut its own numbered Shot and local
cut time in detailed_description, with a distinct composition and continuing action.
Select viewpoints that reveal a meaningful subject, spatial relationship, action
turn, reaction, performance detail or visual accent; do not merely rename the same
framing. A push-in, pan or subject moving closer remains one shot, not an editorial cut.
Choose flexible lengths with no minimum duration or fixed shot quota. Keep contact,
response and vocal phrases readable across cuts. Specify the outgoing action state
and the next view's new visual focus so a cut advances the same ongoing event.
Honor explicit continuous-take requests and the assigned ending. Design each other
shot length from its visual function, rather than defaulting to sustained coverage.
"""

CLIP_INTENSITY = {
    'normal':'''PHOTOGRAPHIC INTENSITY: NATURAL. Use restrained, grounded performance,
observational framing, subtle movement and scene-motivated light. Still make complete,
precise filming decisions and use editorial coverage when dynamic editing is enabled.''',
    'high':'''PHOTOGRAPHIC INTENSITY: HIGH. Direct an assertive, visually inventive commercial MV.
Create strong camera placement, perspective, foreground/background depth, purposeful
movement and shaped lighting. Make the performance and its surrounding visual details
active and specific. When dynamic editing is enabled, construct varied viewpoints,
inserts, reactions and intercuts into a rhythmic sequence, including short shots
within the same event. Choose the combination creatively, not a rotating camera list.
Design moving views through an explicit starting composition, path, speed, extent and
ending composition; show the changing spatial relationships. Carry action and results
across cuts. Precise execution supports ambitious photography, not cautious staging.''',
    'extreme':"""PHOTOGRAPHIC INTENSITY: CINEMATIC BURST. Direct a bold, spectacular commercial MV.
Use the same precise execution required at HIGH intensity, with greater contrasts in
scale, perspective, proximity, camera travel, lighting and performance. Design visual
builds and decisive peaks from this passage's music, emotion, comedy, action or spectacle.
When dynamic editing is enabled, actively compose punchy within-scene shot clusters and
cross-scene montage, using visual connections and contrasts to intensify the sequence.
An ordinary task can become striking through its photography and editing. Create
specific visual ideas even when the user provides only the story spine. Design camera
paths from clear starting and ending compositions, including foreground passes and
background displacement where relevant. Commit to direction, extent and speed.
Keep important contact, reactions, vocal performance and causal results legible;
respect explicit continuous-take requests and the allocated ending. Photographic
intensity changes the filmmaking, not the assigned characters, vocal roles or outcome.
"""
}


ALLOCATION_SYSTEM = """Prepare a filmable music-video story across the given source intervals.
When audio_evidence.music_structure is present, its labels and beat/downbeat times
are fallible model predictions, not loudness guesses. Use section transitions to
build anticipation, contrast and a few motivated story/performance payoffs. Allocate
the main climax once where the music and requested story support it; do not replay
the finale in each chorus. Carry clip-local musical timing into each commission.
A solo label does not establish its instrument; labels never override vocal roles.
Write SETUP and CLIP story prose in English; retain original character names and reference tokens.
Apply the supplied adaptation policy while developing and allocating the story.
Build filmable events at the selected intensity; the native clip director later
turns each assigned beat into precise shots. Keep both parallel strands in each
normal-length interval when requested; each strand advances in its own fixed space.
Extract shared SETUP from the user's fixed world, reference and vocal-role settings.
Keep their original wording and distinct locations; do not summarize or redesign them.
SETUP will be sent to every clip director as FIXED REFERENCE SETTINGS.
Include explicit name/role-to-<Picture N> bindings for every supplied actor and location,
fixed geography, vocal duties and hard restrictions.
When the brief requests unreferenced supporting roles, CREATE their fixed designs in
SETUP before allocating clips: a stable name/role, distinctive appearance, costume,
instrument/prop and home position/location for each. Follow requested adult status
and other design constraints. Treat them as original cast, not missing assets.
A requested band must have distinct lead guitar, rhythm guitar, bass and drums when
those roles are requested; do not collapse them into vague background musicians.
Carry these fixed designs to their active local commissions. No fictional Picture IDs.
Do not put plot chronology,
future events, the specified story outcome or the final shot into SETUP.
Each local script must also identify its active actors by their bound <Picture N>.
The clip's current state takes precedence over reference clothing after a change.
Write each CLIP as a self-contained local shooting commission. Include only the
reference identities, relevant location facts, vocal duties and hard rules needed
for this interval, its opening state, visible events and required local end state.
Carry completed consequences as current facts, not their backstory. Include both
separate strands when assigned. Omit unused cast/locations and all later milestones,
plot summaries, ending previews and reasons that depend on future events.
The downstream director creatively stages and films this commission; it does not
redistribute the whole story or choose this interval's singers from quoted lyrics.
Use the supplied pictures for appearance, not a generic textual replacement of the asset.
Deliver self-contained interval scripts with concrete actions and interactions, not
plot summaries. Allocate by story and source timing, not mechanically by paragraph.
Keep original <Picture N> numbers.
Each brief states the actors actually present, their CURRENT look, location and props,
and ONLY this interval's events and necessary changes. Carry state, never a history recap.
Identity changes happen once in their assigned interval; subsequent briefs start in the
resulting identity. Shared SETUP contains no plot chronology, future events or finale.
Preserve the supplied backbone, causal order, explicit cue-bound events and outcome.
Distinguish explicit required milestones and hard restrictions from optional
staging suggestions. Carry the selected adaptation policy through all intervals.
Parallel performance and story strands may intercut; no singer quota, mandatory cast
attendance, shot list or complete dramatic arc per interval. Allocate a feasible amount
of action to each duration. Respect local_srt cue timing and each interval's ending.
Distribute the developed story across intervals, splitting a sequence when needed.
Allocate opening, development and resolution across the available time; do not finish
all events early and copy the finale to fill remaining slots. Each one-time event
occurs once; later intervals continue from its consequence. A short tail sustains or
completes the ending already underway, not another complete replay of the ending.
Do not shorten it into generic beats or add unrelated plot. Do not add shot lists;
retain special camera directions already supplied by the user with their events.
Use the timeline ending phases when allocating the specified outcome. A resolving
interval receives the actual local ending events, not a vague hint to end later.
If only a short residual tail remains, the preceding full interval must complete
the decisive action and establish the result; the tail continues that result.
Do not hide the ending from the interval assigned to perform it.
Use exactly these plain-text boundaries, every requested index, then END:
=== SETUP ===
Original fixed world, separate scene definitions, reference roles and singing assignments.
=== CLIP 0 action ===
Current situation and events for interval 0 only.
=== CLIP 1 story ===
Current situation and events for interval 1 only.
=== END ===
Use a supported primary mode in each CLIP header. No analysis or JSON."""


def _pictures(originals):
    from PIL import Image, ImageOps
    parts=[]
    for i,path in enumerate(originals,1):
        with Image.open(path) as im:
            im=ImageOps.exif_transpose(im).convert('RGB');im.thumbnail((768,768))
            parts.extend([('text',f'<Picture {i}>:'),('image',im.copy())])
    return parts


def _text(raw):
    if not isinstance(raw,str):raise SceneStateError('9B 需回傳文字。')
    text=re.sub(r'<think>.*?</think>','',raw,flags=re.S).strip()
    return re.sub(r'^```\w*\s*\n|\n```\s*$','',text).strip()


def _bound(text,count):
    return normalize_mv_prompt(map_image_mentions(text,count),count)


def _check_distinct_events(rows):
    # Catch copied long event blocks, not recurring short performance/ending holds.
    seen={}
    for row in rows:
        event=re.sub(r'^\s*Mode:[^\n]*\n', '', row['event'], flags=re.I)
        key=re.sub(r'\s+', '', event)
        if len(key)<200:
            continue
        if key in seen:
            raise SceneStateError(f"第 {row['index']+1} 段重複第 {seen[key]+1} 段的完整事件；請分配連續進展，勿複製事件填滿時長。")
        seen[key]=row['index']


def ensure_shoot_plan(cfg,req,segments,originals,work,rewrite):
    """Persist allocated scripts and fixed settings, without replanning per slot."""
    contract=ending_contract(req,segments[-1]['start']+segments[-1]['seconds'],segments)
    timeline=[]
    for seg in segments:
        timeline.append({k:seg[k] for k in ('index','start','seconds')} | {
            'local_srt':excerpt(req,seg),'audio_evidence':seg.get('audio_evidence',{}),
            'ending':clip_ending(req,dict(seg,direction_ending_contract=contract))})
    task={'format':'isolated_shoot_briefs_v2',
          'brief':map_image_mentions(req.get('prompt',''),len(originals)),
          'adaptation':'FREE' if req.get('story_plan',True) else 'FAITHFUL',
          'style':req.get('director','auto'),'lyrics':req.get('lyrics',''),
          'intensity':req.get('intensity','high'),'dynamic_cuts':req.get('dynamic_cuts',True),
          'timeline':timeline,
          'ending_contract':contract}
    complete_story=req.get('project_scope','full')=='full'
    fingerprint=digest(task)
    # Old schema-5 jobs did not fingerprint the two directing controls.
    old_task=dict(task,format='isolated_shoot_briefs_v1')
    legacy_fingerprints={digest(old_task),digest({k:v for k,v in old_task.items()
                               if k not in ('intensity','dynamic_cuts')})}
    path=Path(work)/'director_plan.json'
    if path.is_file():
        plan=json.loads(path.read_text(encoding='utf-8'))
        # Reuse intact plans saved by the removed v3 reviewer without rerunning it.
        saved_requirements=plan.get('story_completion',{}).get('requirements')
        if saved_requirements:
            legacy_fingerprints.add(digest(dict(task,format='complete_story_shoot_briefs_v3',
                required_story_events=saved_requirements,
                story_scope='Complete this entire story within the uploaded audio duration, even if it is cropped or ends during a chorus.')))
        if (plan.get('version')!=5 or plan.get('input_sha256') not in {fingerprint,*legacy_fingerprints} or
            digest({k:v for k,v in plan.items() if k not in ('content_sha256','input_sha256')})!=plan.get('content_sha256')):
            raise SceneStateError('分段拍攝大綱與專案不符或校驗失敗。')
        return plan
    parts=[('text',json.dumps(task,ensure_ascii=False))]+_pictures(originals)
    system=(ALLOCATION_SYSTEM+'\n'+adaptation_direction(req)+'\n'+REFERENCE_PERFORMANCE+'\n'+CLIP_INTENSITY[req.get('intensity','high')]+
            '\nApply this intensity to filmable event development; leave shot selection to the clip director.\nSupported modes: '+
            ', '.join(MODES)+f'. Deliver {len(segments)} CLIP blocks.')
    if complete_story:
        system+='\nCOMPLETE STORY SCOPE: Read the ENTIRE user brief before allocation. Budget opening, development, decisive resolution and final image over the ENTIRE available duration. Work backward from the mandatory ending, reserve enough room for it, then fit the middle. Compress optional staging rather than dropping required events or stopping at paragraph N. Musical section labels guide accents only; no outro is required to finish a story. For a very short tail, complete decisive events in the preceding full interval and sustain their result in the tail. If the complete request cannot fit, explicitly report that rather than delivering an incomplete story.'
    attempts=parts
    for attempt in range(rewrite_retry_count(req)+1):
        raw=rewrite(cfg,system,attempts,uuid.uuid4().hex[:8])
        try:
            from banana_mv.story_plan import direct_delivery
            text=_text(raw)
            setup=re.match(r'^===\s*SETUP\s*===\s*\n(.*?)(?=^===\s*CLIP\s)',text,re.S|re.M)
            if not setup:raise SceneStateError('分段大綱缺少 SETUP 共用設定。')
            shared=_bound(setup[1].strip(),len(originals))
            delivery=direct_delivery(text)
            rows=delivery.get('segments')
            if not isinstance(rows,list) or len(rows)!=len(segments):
                raise SceneStateError(f'需交齊 {len(segments)} 段拍攝大綱。')
            result=[]
            for seg,row in zip(segments,rows):
                if row.get('index')!=seg['index'] or row.get('mode') not in MODES:
                    raise SceneStateError('分段大綱順序或模式錯誤。')
                result.append({'index':seg['index'],'mode':row['mode'],'handoff_version':1,
                               'event':_bound(row['prompt'],len(originals))})
            _check_distinct_events(result)
            plan={'version':5,'shared_setup':shared,'segments':result,'visual_verified':False,
                  'ending_contract':task['ending_contract'],'project_scope':req.get('project_scope','full')}
            plan['content_sha256']=digest(plan);plan['input_sha256']=fingerprint
            atomic_json(path,plan)
            return plan
        except ValueError as error:
            atomic_json(Path(work)/f'director_attempt_{attempt:02d}.json',
                        {'raw_response':raw,'error':str(error)})
            if attempt>=rewrite_retry_count(req):
                raise SceneStateError('分段大綱交稿失敗：'+str(error)) from error
            attempts=parts+[('text','Deliver the original fixed settings in SETUP and ALL CLIP scripts, then END. '
                            'Keep the selected adaptation policy and photographic intensity while allocating the story backbone across the supplied intervals. '
                            'Do not copy a complete event sequence into later slots. No analysis. Delivery error: '+str(error))]


def write_shoot_prompt(cfg,req,segment,originals,tail,rewrite,progress=None):
    """The first and only shot-writing stage; it cannot see the full story."""
    row=segment['director_plan'];offset=int(bool(tail))
    if row.get('handoff_version')!=1:
        raise SceneStateError('舊大綱缺少獨立的當段拍攝委託；已保存影片與提示詞可沿用，但新寫稿需建立新任務重新分配。不能傳回完整設定補足。')
    def connected(text):
        # Only numbering changes for an actual keyframe. Never compact actor slots.
        return re.sub(r'<Picture (\d+)>',lambda m:f'<Picture {int(m[1])+offset}>',text)
    fixed_setup=segment.get('fixed_reference_settings','')
    context={'seconds':segment['seconds'],'primary_mode':row['mode'],
          'adaptation':'FREE' if req.get('story_plan',True) else 'FAITHFUL',
          'local_srt':excerpt(req,segment),'audio_evidence':segment.get('audio_evidence',{}),
          'ending':clip_ending(req,segment)}
    if fixed_setup:context['fixed_reference_settings']=connected(fixed_setup)
    if tail:context['first_frame']='<Picture 1> is the actual previous last frame, not another actor.'
    guide=Path(cfg['guides']['ref']).read_text(encoding='utf-8')
    system=NATIVE_ENHANCER_SYSTEM+guide
    text=(f"Target video duration: {segment['seconds']:.6f} seconds.\n"
          "Inspect the reference images labeled <Picture N> and use them according to the user's instructions.\n"
          "Choose shots that best express the original intent. "
          "Allocate shot durations and cut timing within the target duration according to content and pacing. "
          "Respect explicit shot requests, reference constraints and the guide's transition rules.\n"
          "Original prompt:\nCurrent clip script:\n"+connected(row['event'])+"\n\n")
    text+="""Enhance this ONE clip script into the guide's final native H3 filming prompt,
including its per-shot composition, lighting, actions and camera movement.
When audio_evidence.music_structure is supplied, use its predicted local section
changes and selected downbeats to motivate action payoffs, camera reveals and
performance highlights. Write their timing into the shots, not an analysis appendix.
Keep anticipation and contrast; do not cut on every beat. Labels can be wrong and
do not identify instruments or override vocal roles. Use loudness only as acoustic evidence.
Use the current clip's assigned beat and end state as the scope for visual development.
Apply the adaptation policy below within that local scope. The commission supplies
the needed current facts, opening state, events and local end state. Design compelling
performance, coverage and montage to realize it. Use its assigned locations and asset roles;
keep separate locations distinct, intercutting them rather than merging their sets or
placing their casts in one shared frame. Select cast and supporting coverage to serve
the current beat and adaptation policy, preserving fixed_reference_settings bindings.
These settings identify assets, not a mandatory cast list. Never turn the singer
into the challenger or substitute <Picture 1> for another named actor.
Do not infer an actor's role from its apparent species, outfit or upload position.
Local current-state changes override initial clothing/props while identity stays fixed.
Available reference images do not require unused characters or locations to appear.
Original supporting cast in fixed_reference_settings is equally available without a
reference image. Use the same fixed design and instrument whenever that role returns.
Do not reject it as "no such character", replace it with referenced cast, or omit a
requested featured solo/hero shot merely because the performer has no uploaded photo.
Use the actual reference appearance, not a generic version of its species or object type.
Preserve current looks and props rather than resetting to
reference clothing.
All shot times are LOCAL and within the target duration; alignment
padding adds no story time. Continue actions across cuts, without replaying the event.
Use only connected pictures and <Audio 1>: fully_copy. The source audio is supplied to
H3, not heard by you. Only the assigned vocalist may lip-sync. Add no new speech,
lyrics, subtitles or a replacement song. Supplied SRT is timing evidence, not dialogue.
Describe <Audio 1> only as the supplied unchanged source track; you have not heard it.
Do not claim it contains a whistle, crowd, instruments, low energy or silence unless
explicitly supported by the supplied evidence. Visible instruments are not heard evidence.
For source-only delivery, overall_soundscape states source audio unchanged; do not
invent an audible arena/stage ambience. non_diegetic_music identifies the supplied
music track, not N/A. Optional external effects are mixed separately, not generated
by this filming prompt. Their policy is sparse, event-motivated accents with music
and lead vocals dominant; no continuous crowd bed, repetitive effects or invented dialogue.
Keep microphone grip and free-hand gestures physically consistent.
Follow this clip's ending; an ongoing clip needs no whole-work finale.
Return only the native filming prompt, no analysis, JSON or management instructions.
"""
    text+='\n'+adaptation_direction(req)
    text+='\n'+REFERENCE_PERFORMANCE
    text+='\n'+AUTO_FILMING
    text+='\n'+(DYNAMIC_EDITING if req.get('dynamic_cuts',True) else
                'Prefer motivated longer takes. Reveal changes through blocking, reframing or camera movement; do not force short-shot clusters.')
    text+='\n'+CLIP_INTENSITY[req.get('intensity','high')]
    if req.get('face_identity',True):text+='\nPreserve the assigned reference identities through motion and expressions.'
    text+='\nWhen a permitted singer appears, prefer waist-up or closer for clear lip sync.'
    text+='\n\nClip timing and audio context:\n'+json.dumps(context,ensure_ascii=False)
    refs=([tail] if tail else [])+list(originals)
    parts=[('text',text)]+_pictures(refs)
    attempts=parts;segment['director_mode']=row['mode']
    for attempt in range(rewrite_retry_count(req)+1):
        if progress:progress({'stage':'rewriting','clip_index':segment['index'],
                              'attempt':attempt+1,'max_attempts':rewrite_retry_count(req)+1})
        segment['prompt_profile']={'source':'isolated_native_director','writer_calls':attempt+1,
                                   'contract_check_calls':0}
        raw=rewrite(cfg,system,attempts,uuid.uuid4().hex[:8])
        try:
            prompt=normalize_mv_prompt(_text(raw),len(refs))
            if len(originals)>1 and not re.search(r'<Picture \d+>',prompt):
                raise SceneStateError('多圖拍攝稿缺少原始圖片綁定。')
            return prompt
        except ValueError as error:
            if attempt>=rewrite_retry_count(req):
                raise SceneStateError('當段拍攝稿交稿失敗：'+str(error)) from error
            attempts=parts+[('text','Return only the current native H3 prompt. Fix connected-media delivery: '+str(error))]


