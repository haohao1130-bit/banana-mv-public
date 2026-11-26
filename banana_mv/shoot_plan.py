"""Allocate once; let the native H3 rewriter shoot each isolated interval."""
import json
import re
import uuid
from pathlib import Path

from banana_mv.commission_guard import role_pictures
from banana_mv.body_form import declared_body_forms
from banana_mv.core import map_image_mentions, normalize_mv_prompt
from banana_mv.director import MODES
from banana_mv.lyrics_reference import SUBJECT_VOCAL_PREFIX, clean_lyric_output, excerpt, vocal_timeline
from banana_mv.director_shoot import write_director_shoot_prompt
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
    "Writing tips from the official H3 skill (advice, not checks): "
    "open detailed_description with one or two sentences of concrete style; "
    "per shot, give composition, subject position, action and reaction, camera, and sound; "
    "write camera moves as natural English (push in, pull out, pan, truck, tilt, pedestal, arc, tracking, static, POV, roll, slight or strong shake), "
    "adding amplitude or speed whenever the energy calls for it; "
    "cut only for new information (subject, space, state, viewpoint or time), otherwise move the camera; "
    "when the commission gives separate time slots, give each slot its own [Shot N] at its time and never merge two slots into one shot; "
    "a match cut on action is a real cut: end the first shot before contact or completion, and finish the same motion in the next [Shot N] from a strongly contrasting angle; "
    "prefer concrete visual and audio detail over words like cinematic or beautiful; "
    "keep shot timing inside the clip duration; "
    "quote on-screen text in its original language; "
    "overall_soundscape: one to four sentences of ambience and physical sounds; "
    "non_diegetic_music: one to three sentences on instruments, tempo and dynamics, no mood words. "
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
links, participants, props and order. Follow camera requests where they work together,
and use the directing policy to resolve conflicts. Keep the assigned story events.
"""


# 9B 看圖會自己猜物種：原創吉祥物蕉彌被寫成兔子、生物、貓科（實測 c15e16581a5e 變成黃貓）。
# 9B 每段重看參考圖、重寫一次服裝，每段寫法不同，H3 跟著文字換衣服（實測 5a114b855bf1 小語四段四套）。
REFERENCE_IDENTITY = (
    'REFERENCE IDENTITY: never guess a species from a <Picture N>. Define referenced actors as name + <Picture N> + '
    '"costume as in <Picture N>" plus only words copied from the settings; never describe hair, clothes or '
    'accessories yourself.')


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


MARTIAL_ARTS_DIRECTION = """MARTIAL ARTS DIRECTION: Stage only the fight beats already in the current event.
For each exchange, show who initiates, what they attempt, how the other actor
responds, and how the visible outcome motivates the next beat. Frame both actors'
movement clearly and keep their positions continuous across cuts. Give each
exchange time to read. Preserve the scripted outcomes, cut times, cast, and SRT
singer assignments. Add no new fight beats.
"""


AUTO_FILMING = """Direct the visual sequence around the current action, performance and reactions.
Start with the first timed beat. Treat untimed cast, setting, carryover and
expression notes (入鏡, 場景, 承接, 表情) as context for the timed shots. Place cast
and visual details where they serve those beats. Give a timed opening priority
over any inferred establishing view. An attached opening frame anchors continuity
at the boundary. If the first beat calls for a cut, cut immediately after that
frame and carry the ongoing action across.
Choose coverage that makes this beat visually compelling and fluid, including
framing, cut timing and camera movement wherever the brief leaves them open.
A cut selects the next view. A movement cue applies within that new view.
When camera cues genuinely conflict or cannot play smoothly in the available time,
choose the framing, cut or move that makes the action readable, visually compelling
and fluid while giving the beat dramatic tension. Keep required events, their order
and timing, established continuity, and expressly locked camera constraints. Settle
on one executable approach and write it directly.
Use only the shot details that matter to the beat. Carry established appearance,
setting, lighting and sound forward, mentioning them again when they change or
serve the shot. Use the native guide's Shot labels and local cut times. The first
shot begins at zero without a timestamp. Each later shot starts at its cut time.
"""

DYNAMIC_EDITING = """Dynamic editing is enabled: actively design editorial coverage, not just camera
movement. Separate changes of storyline from changes of viewpoint within a scene.
For an energetic passage with several distinct action or performance accents, use
purposeful short-shot coverage within that scene as well as intercuts. A scene visit
is not automatically one shot. A numbered Shot may include motivated internal cuts, reverse angles or montage
transitions. Describe the new view clearly; do not require a fresh Shot number
for every editorial cut. Keep distinct compositions and continuing action.
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
turns each assigned beat into precise shots. Preserve requested parallel strands as meaningful recurring material across the MV.
Choose irregular intercuts from music and events, without a per-clip scene quota.
Extract shared SETUP from the user's fixed world, reference and vocal-role settings.
Keep their original wording and distinct locations; do not summarize or redesign them.
SETUP will be sent to every clip director as FIXED REFERENCE SETTINGS.
Include explicit name/role-to-<Picture N> bindings for every supplied actor and location,
fixed geography, vocal duties and invariant performance rules.
Keep the whole-work outcome in a separate STORY OUTCOME block, for upstream
allocation only. Winning, awards and final poses are plot events, never fixed
reference rules. Allocate them only to the CLIP that performs them.
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
Original fixed world, separate scene definitions, reference roles and singing assignments only.
=== STORY OUTCOME ===
Whole-work outcome for upstream allocation only; never repeat it in SETUP.
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
    task={'format':'isolated_shoot_briefs_v3',
          'brief':map_image_mentions(req.get('prompt',''),len(originals)),
          'adaptation':'FREE' if req.get('story_plan',True) else 'FAITHFUL',
          'style':req.get('director','auto'),'lyrics':req.get('lyrics',''),
          'intensity':req.get('intensity','high'),'dynamic_cuts':req.get('dynamic_cuts',True),
          'timeline':timeline,
          'ending_contract':contract}
    if req.get('shared_setup'):
        task['shared_setup']=map_image_mentions(req['shared_setup'],len(originals))
    complete_story=req.get('project_scope','full')=='full'
    fingerprint=digest(task)
    # Old schema-5 jobs did not fingerprint the two directing controls.
    old_task=dict(task,format='isolated_shoot_briefs_v1')
    legacy_fingerprints={digest(dict(task,format='isolated_shoot_briefs_v2')),digest(old_task),digest({k:v for k,v in old_task.items()
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
            setup=re.match(r'^===\s*SETUP\s*===\s*\n(.*?)(?=^===\s*(?:STORY OUTCOME\s*===|CLIP\s))',text,re.S|re.M)
            if not setup:raise SceneStateError('分段大綱缺少 SETUP 共用設定。')
            shared=_bound(req['shared_setup'] if req.get('shared_setup') else setup[1].strip(),len(originals))
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
            outcome=re.search(r'^===\s*STORY OUTCOME\s*===\s*\n(.*?)(?=^===\s*CLIP\s)',text,re.S|re.M)
            if outcome:plan['story_outcome']=outcome[1].strip()  # Upstream only.
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


def _fixed_reference_with_python_priority(fixed_setup, event):
    """Remove superseded opening-wardrobe facts, not reference identities.

    Only slots with a populated Python state take this path. Untracked
    appearance properties continue to fall back to the original reference.
    """
    match = re.search(
        r'(?s)^CURRENT_ACTOR_STATE[^\n]*\n(.*?)\nEXPECTED_ACTOR_STATE_AFTER_THIS_CLIP',
        event)
    if not match:
        return fixed_setup
    known = [line.strip() for line in match.group(1).splitlines()
             if re.match(r'^- (?:Torso|Bottom|Feet): ', line)]
    if not known:
        return fixed_setup
    # Bind identity to the reference, but never bind today's clothing to the
    # reference's historic opening wardrobe.
    fixed_setup = fixed_setup.replace(
        '與開場服裝依照參考圖片',
        '依照參考圖片；開場服裝僅是初始造型，不代表本段外觀')
    output = []
    opening = False
    for line in fixed_setup.splitlines():
        stripped = line.strip().lstrip('-* ').strip()
        opener = re.match(r'^(開場穿著|初始穿著|初始服裝|開場服裝)\s*[：:]\s*(.*)$',
                          stripped)
        if opener:
            opening = True
            output.append('初始服裝僅作歷史參考；本段已記錄的屬性由 Python 當前狀態決定。')
            inline = opener.group(2).strip()
            if inline and not any(inline in entry for entry in known):
                output.append(inline)
            continue
        if opening:
            if (not stripped or stripped.endswith(('：', ':')) or
                    stripped.startswith(('服裝依', '已卸除', '不重新', '人物', '整體',
                                         '故事', '演唱', '攝影', '後半段'))):
                opening = False
            elif any(stripped in entry for entry in known):
                # The Python-ledger category is known; discard the stale
                # reference outfit for this category. Other items stay.
                continue
        output.append(line)
    return '\n'.join(output)


def _local_event(event):
    # A continuity frame or explicit present state already carries the result.
    # Do not send previous actions or the source chapter title to the shot writer.
    return re.sub(
        r'(?m)^\s*(?:ALREADY ESTABLISHED;[^\n]*|Previously established:[^\n]*|Source chapter:[^\n]*|Phase inside chapter:[^\n]*)\n?',
        '', event,
    ).strip()


_LOCAL_BEAT = re.compile(
    r'^\s*(?:[-*]\s+)?(\d+(?:\.\d+)?)\s*(?:秒|s)?\s*[-–—－~～至]\s*'
    r'(\d+(?:\.\d+)?)\s*(?:秒|s)\s*(?:[:：]\s*(.*))?$', re.I,
)
_BEAT_NOTE = re.compile(
    r'^\s*(?:【(入鏡|場景|承接|交棒|[^】]{0,12}表情|H3\s*提示詞)】'
    r'\s*[:：]?|(入鏡|場景|承接|交棒|[^：:]{0,12}表情)\s*[:：])\s*(.*)$',
)


def _timed_shoot_event(event, duration):
    """Separate authored clip-local action windows from untimed setup notes."""
    beats, notes = [], []
    current = notes
    for line in event.splitlines():
        span = _LOCAL_BEAT.match(line)
        if span:
            start, end = map(float, span.groups()[:2])
            if not 0 <= start < end <= duration + 0.001 or (beats and start < beats[-1][1]):
                return event
            current = [span[3] or '']
            beats.append((start, end, current))
        elif note := _BEAT_NOTE.match(line):
            current = notes
            title = note[1] or note[2]
            if not re.fullmatch(r'H3\s*提示詞', title) or note[3]:
                label = ('OPENING STATE (already true)' if title == '承接' else
                         'ENDING STATE' if title == '交棒' else title)
                current.append(f'{label}: {note[3]}'.rstrip())
        else:
            current.append(line)
    if not beats or any(not any(line.strip() for line in lines) for _, _, lines in beats):
        return event
    rows = '\n\n'.join(
        '[{:.3f}–{:.3f}s] {}'.format(start, end, '\n'.join(lines).strip())
        for start, end, lines in beats
    )
    context = '\n'.join(notes).strip()
    return (
        'AUTHOR-TIMED ACTION WINDOWS (clip-local):\n'
        'Keep each action and any exact cue inside its assigned window. '
        'Choose camera coverage within those windows. A window does not require a cut. '
        'When the first window starts at zero, begin its action at zero.\n'
        + rows + ('\n\nUNTIMED CONTEXT (applies across the clip; never add an opening beat '
                  'from these notes or replay an already established action):\n' + context
                  if context else '')
    )


def _apply_source_performance(prompt, timeline, fixed_setup):
    # The same user-defined SRT identities drive both filming paths.
    bindings = role_pictures(fixed_setup)
    rows = []
    for cue in timeline:
        subjects = cue.get('subjects', [])
        assigned = ' and '.join(bindings.get(subject, subject) for subject in subjects)
        if not assigned:
            assigned = cue['voice']
        rows.append(f"{cue['clip_start']:.3f}–{cue['clip_end']:.3f}s: {assigned}.")
    policy = (
        'Use the original song from <Audio 1> unchanged (fully_copy). '
        'Use natural lip-sync where the scene calls for it. The following SRT hints identify '
        'which performer to show if filming lip-sync in a tagged interval. Follow the scene '
        'when no performer is tagged. <Audio 1> is the audible voice source. '
        'No spoken rendition, repeated line, new vocals or subtitles.\n' + '\n'.join(rows)
    )
    for field, replacement in (
        ('overall_soundscape', 'The supplied source song plays unchanged.'),
        ('non_diegetic_music', 'The supplied source song.'),
    ):
        pattern = rf'(?im)^{field}:[ \t]*[^\n]*(?:\n(?![a-z_]+:)[^\n]*)*'
        prompt, count = re.subn(pattern, lambda _: f'{field}:\n{replacement}\n', prompt)
        if not count:
            prompt += f'\n\n{field}:\n{replacement}'
    prompt = re.sub(r'(?im)^<Audio 1>:\s*(?:reference|partial(?:ly)?_copy)\b[^\n]*',
                    '<Audio 1>: fully_copy. Preserve the supplied source song.', prompt)
    description = re.search(r'(?im)^(?:detailed_description|integrated_multimodal_description):[ \t]*', prompt)
    if description:
        return prompt[:description.end()] + '\n' + policy + '\n' + prompt[description.end():]
    return prompt + '\n\ndetailed_description:\n' + policy



# Python retains every authored story route in its saved plan. Only invariant
# reference facts travel to the local camera model, including on resumed jobs.
_FIXED_FILMING_HEADINGS = frozenset((
    '共同設定', '共通設定', '共用設定', '固定設定', '全片設定',
    '角色設定', '人物設定', '人物介紹', '角色介紹', '角色與造型',
    '角色綁定', '世界觀', '場景設定', '固定場景', '故事背景',
    '背景設定', '整體風格', '視覺基調', '視覺風格',
    '攝影原則', '攝影語言測試', '演唱安排', '表演原則',
    '攝影與舞蹈', '演唱近拍', '舞蹈編排',
))
_STORY_FILMING_HEADINGS = frozenset((
    'MV 主題', '主題', '故事主題', '故事內容', '故事劇情',
    '劇情內容', '故事大綱', '劇情大綱', '劇本內容',
    '完整故事劇情', '劇情', '故事', '故事路線', '全片故事',
    '劇情連續性', '服裝連續性', '演唱與劇情安排',
     '最終導演意圖', '導演意圖', '故事主軸', '全片因果',
    '導演自由發揮', '導演執行重點', '執行重點',
    '特殊要求', '全曲執行原則', '全曲固定原則',
    'Story', 'Story spine', 'Storyline', 'Story synopsis',
    'Plot', 'Plot arc', 'Whole song story', 'Full story',
    'Ending', 'Finale', 'Resolution', 'Future events',
))
_FUTURE_FILMING = re.compile(
    r'前半段|後半段|中段|後段|末段|後面|最後|最終|結局|謝幕|尾聲|'
    r'第[一二三四五六七八九十\d]+[幕段]|隨著(?:歌曲|劇情|故事)|'
    r'逐步|依序|一路推進|回家|返回|回到|再回|重返|'
    r'→|->|⇒|'
    r'從.{0,90}(?:出發|開始).{0,100}(?:到|再|回)|'
    r'先.{0,75}(?:再|然後|接著)|'
    r'(?:接著|然後|隨後|之後).{0,75}(?:抵達|換上|脫下|去|回)|'
    r'\b(?:eventually|finally|ultimately|later|afterwards|final scene|'
    r'final shot|future concert|in the end|end of the (?:film|mv|story)|'
    r'the ending|the finale|whole[- ]song plot|story spine|plot arc)\b',
    re.I,
)
_NATIVE_SECTION = re.compile(r'^(0[1-9]|10)\s*[｜|]\s*([A-Z][A-Z\s\'-]+)$', re.I)
_NATIVE_STATIC_PROJECT = re.compile(
    r'^(?:Project|Format|Duration|Aspect Ratio|Visual Style|Resolution|Editing Style|Genre)\s*:',
    re.I,
)
_NATIVE_FUTURE = re.compile(
    r'\b(?:eventually|finally|ultimately|gradually|later|after the performance|'
    r'second half|ending|finale|becomes a concert)\b', re.I,
)
_STATIC_FILMING_FACT = re.compile(
    r'^(?:S[1-8]\s*[=:：]|<Picture \d+>|@圖片\d+|'
    r'角色|人物|男主|女主|歌手|主唱|演唱者|外貌|五官|髮型|'
    r'服裝|開場穿著|初始服裝|初始穿著|'
    r'全片只有|唯一|不得新增|禁止新增|不新增|'
    r'畫面風格|攝影風格|視覺風格|整體風格|'
    r'固定場景|固定背景|依 SRT|[\[]S[1-8])',
    re.I,
)


def _filming_reference_settings(fixed_setup):
    """Forward identity/style/world, never the future plot, from Python to 9B."""
    result = []
    section = 'fixed'  # Legacy unheaded setups include original supporting cast.
    for raw in fixed_setup.splitlines():
        line = re.sub(r'^\s*#{1,6}\s+', '', raw).strip().strip('* ').strip()
        title = line.rstrip('：:').strip()
        if title.startswith('【') and title.endswith('】'):
            title = title[1:-1].strip()
        # English director notes often use inline headings rather than ACT blocks.
        # An inline "Story spine: ... / Finale: ..." is a global plot, never
        # a reusable static actor fact for a per-clip 9B cinematographer.
        if re.match(
            r'(?i)^(?:story(?:\s+spine|\s+synopsis|\s+arc|\s+outline)?|'
            r'storyline|plot(?:\s+arc|\s+outline)?|whole[- ]song\s+story|'
            r'full\s+story|ending|finale|resolution|future\s+events)\s*[:：]',
            line,
        ):
            section = 'story'
            continue
        # Long-form English director packages embed the full future screenplay
        # before and after the ACTs. Only static project/cast facts go to 9B.
        native = _NATIVE_SECTION.match(title)
        if native:
            section = ('native_project' if native[1] == '01' else
                       'native_cast' if native[1] == '02' else 'story')
            continue
        if section == 'native_project':
            if _NATIVE_STATIC_PROJECT.match(line):
                result.append(raw)
            continue
        if section == 'native_cast':
            if _NATIVE_FUTURE.search(line):
                continue
            result.append(raw)
            continue
        # Author's concluding story explanation is useful for Python's plan,
        # never a current-shot instruction for the isolated 9B cameraman.
        if re.match(r'^[一二三四五六七八九十]+[、.．]\s*(?:最終導演意圖|結語)', title):
            section = 'story'
            continue
        if title in _FIXED_FILMING_HEADINGS:
            section = 'fixed'
            result.append(raw)
            continue
        if title in _STORY_FILMING_HEADINGS:
            section = 'story'
            continue
        # Inline story headings also contain future events, not reusable setup.
        inline_title = line.split('：', 1)[0].split(':', 1)[0].strip()
        if inline_title in _STORY_FILMING_HEADINGS:
            section = 'story'
            continue
        subfield = re.match(
            r'^(故事背景|背景設定|整體風格|場景設定|視覺風格|固定場景)\s*[：:]\s*(.*)$',
            line,
        )
        if subfield:
            section = 'fixed'
            if not _FUTURE_FILMING.search(subfield.group(2)):
                result.append(raw)
            continue
        if not line or _FUTURE_FILMING.search(line):
            continue
        binding = re.match(r'^S[1-8]\s*[=:：]\s*<Picture \d+>', line, re.I)
        if binding or section == 'fixed' or (
            section == 'unknown' and _STATIC_FILMING_FACT.match(line)
        ):
            result.append(raw)
    return '\n'.join(result).strip()


def write_shoot_prompt(cfg,req,segment,originals,tail,rewrite,progress=None):
    """The first and only shot-writing stage; it cannot see the full story."""
    row=segment['director_plan'];offset=int(bool(tail))
    if row.get('handoff_version')!=1:
        raise SceneStateError('舊大綱缺少獨立的當段拍攝委託；已保存影片與提示詞可沿用，但新寫稿需建立新任務重新分配。不能傳回完整設定補足。')
    def connected(text):
        # Only numbering changes for an actual keyframe. Never compact actor slots.
        return re.sub(r'<Picture (\d+)>',lambda m:f'<Picture {int(m[1])+offset}>',text)
    fixed_setup=segment.get('fixed_reference_settings','')
    # Read explicit singer mappings BEFORE stripping global SRT and future-story
    # sections; then forward only canonical, static role/image identities.
    source_singers=role_pictures(fixed_setup)
    event = _local_event(row['event'])
    vocals = vocal_timeline(excerpt(req, segment))
    context = {'ending': clip_ending(req, segment)}
    if vocals:
        context['authored_vocal_timeline'] = vocals
    fixed_setup = re.split(r'(?m)^===\s*STORY OUTCOME\s*===\s*$', fixed_setup, maxsplit=1)[0]
    fixed_setup = _fixed_reference_with_python_priority(fixed_setup, event)
    if not req.get('shared_setup'):
        # 沒有獨立的共同設定格時，才需要從劇本前言裡過濾掉故事大綱。
        fixed_setup = _filming_reference_settings(fixed_setup)
    # Stable anatomical facts are separate from clothing, camera and plot.
    # Store them on the clip for resume/debug and pass them unchanged to H3.
    body_form = declared_body_forms(fixed_setup)
    if body_form:
        segment['body_form'] = body_form
    else:
        segment.pop('body_form', None)
    present=role_pictures(fixed_setup)
    for role,picture in source_singers.items():
        if present.get(role)!=picture:
            fixed_setup += ('\n' if fixed_setup else '') + role + ' = ' + picture
    if fixed_setup:
        context['fixed_reference_settings'] = connected(fixed_setup)
    pictures = role_pictures(context.get('fixed_reference_settings', ''))
    wardrobe = {}  # 換裝改用 continuity.py 的通用換裝點；舊的海邊換裝規則已移除。
    shoot_event = _timed_shoot_event(event, float(segment['seconds']))

    # SRT-authored dual singers: Python owns singer timing, cast, wardrobe and
    # final H3 sections. 9B owns the number and timing of CAMERA cuts. Never
    # convert an SRT handoff into a compulsory new shot.
    # All other legacy and unscripted routes stay unchanged.
    if (req.get('director_schema') == 6 and len(originals) == 2
            and {'S1', 'S2'} <= set(pictures)
            and req.get('srt_cues')
            and any(SUBJECT_VOCAL_PREFIX.match(c.get('text','')) for c in req['srt_cues'])
            and all(set(cue.get('subjects', ())) <= {'S1', 'S2'} for cue in vocals)):
        refs = ([tail] if tail else []) + list(originals)
        segment['director_mode'] = row['mode']
        direction_policy = '\n\n'.join((
            adaptation_direction(req),
            REFERENCE_PERFORMANCE,
            AUTO_FILMING,
            DYNAMIC_EDITING if req.get('dynamic_cuts', True) else
                'EDITORIAL DIRECTION: Favor motivated continuous takes; '
                'use a camera cut whenever the event requires a new viewpoint '
                'or reaction. Keep dramatic changes and actor movement alive.',
            CLIP_INTENSITY[req.get('intensity', 'high')],
        ))
        if row['mode'] == 'action':
            direction_policy += '\n\n' + MARTIAL_ARTS_DIRECTION
        native = write_director_shoot_prompt(
            cfg, req, segment, event, fixed_setup, pictures, wardrobe, refs,
            _pictures(refs), rewrite, progress, direction_policy=direction_policy,
            body_form=body_form, shoot_event=shoot_event)
        native, removed = clean_lyric_output(
            native, dict(req, lyrics_reference_version=2))
        segment['lyric_reference_cleanup'] = {'removed_spans': removed}
        return native

    if req.get('lean_commission'):
        return _write_lean_prompt(cfg, req, segment, originals, tail, rewrite, progress,
                                  row, shoot_event, context, vocals, pictures, connected)

    if tail:
        if req.get('mode') == 'chain5':
            context['first_frame'] = (
                '<Picture 1> is the earliest of the five overlapping tail frames (F-4) '
                'from the previous clip, not its final frame and not another actor.'
            )
        else:
            context['first_frame']='<Picture 1> is the actual previous last frame, not another actor.'
    guide=Path(cfg['guides']['ref']).read_text(encoding='utf-8')
    system=NATIVE_ENHANCER_SYSTEM+guide
    continuation_note = (
        'CHAIN5 CONTINUATION: H3 receives a five-frame overlap preceding this clip. '
        'Continue its established action and physical consequences; advance the current '
        'event without replaying completed actions. Keep later cinematography flexible.\n'
        if tail and req.get('mode') == 'chain5' else ''
    )
    text=(f"Target video duration: {segment['seconds']:.6f} seconds.\n"
          f"Primary filming mode: {row['mode']}.\n"
          "Inspect the reference images labeled <Picture N> and use them according to the user's instructions.\n"
          "Choose shots that best express the original intent. "
          "Allocate shot durations and cut timing within the target duration according to content and pacing. "
          "Honor locked camera constraints and reference anchors. Resolve conflicting camera cues with the directing policy below.\n"
          + continuation_note
          + "Original prompt:\nCurrent clip script:\n"+connected(shoot_event)+"\n\n")
    text+="""Enhance this ONE clip script into the guide's final native H3 filming prompt,
focusing each shot on the visible action and the camera choices that serve it.
The current clip script alone assigns plot events. Fixed reference settings carry
identity and scene duties, never permission to perform a future ending. If old
fixed settings mention a whole-work outcome, perform it only when assigned here.
Opening conditions are already true; do not replay how they occurred. Preserve
current consequences while designing music-led coverage and internal cuts freely.
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
""" + REFERENCE_IDENTITY + """
Preserve current looks and props rather than resetting to
reference clothing.
All shot times are LOCAL and within the target duration; alignment
padding adds no story time. Continue actions across cuts, without replaying the event.
Use only connected pictures and <Audio 1>: fully_copy. The source audio is supplied to
H3, not heard by you. Use natural lip-sync where it suits the scene. <Audio 1> is the
only audible voice source. SRT singer tags guide the visible performer when covering
lip-sync. Describe mouth movement without adding an independent (Sx) voice or <d>
for lip-sync or silent gestures. Add no speech, lyrics, subtitles or replacement song.
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
    if vocals:
        text += ('\nUse authored_vocal_timeline as optional coverage guidance for '
                 'lip-sync permitted by the current scene. Resolve each SRT role using the explicit '
                 'user-defined cast bindings, never picture order or gender. If a binding is absent, '
                 'do not guess. Combined role tags identify the performers for a shared vocal cue. '
                 'Duet means both assigned voices. Harmony identifies backing vocals and '
                 'does not assign a lead singer or imply both leads sing. Untagged time '
                 'has no explicit voice assignment. Keep the original soundtrack.')
    else:
        text += ('\nFollow the current clip script for visible singing and lip-sync. '
                 'There is no explicit SRT singer assignment for this clip. Keep the original soundtrack.')

    if vocals and pictures:
        rows = []
        for cue in vocals:
            singer_roles = cue.get('subjects', [])
            named = ' + '.join(role+' = '+pictures.get(role, 'UNBOUND') for role in singer_roles)
            rows.append(f"{cue['clip_start']:.3f}–{cue['clip_end']:.3f}s: {named or 'UNASSIGNED'}")
        text += '\nCLIP-LOCAL SRT CAST HINTS FOR OPTIONAL LIP-SYNC:\n' + '\n'.join(rows)
        text += ('\nIf covering lip-sync in a tagged interval, show its assigned performer(s). '
                 'Camera coverage and other actors remain scene-led. Untagged intervals '
                 'follow the scene and original track.\n')
    if wardrobe:
        text += '\nCURRENT COSTUME AT THIS LOCATION (already changed, no repeat changing scene):\n'
        text += '\n'.join(role+' '+pictures.get(role, '')+': '+garment for role, garment in wardrobe.items())
        text += ('\nUse the referenced face and hairstyle, but replace prior clothing '
                 'in ALL subject_definitions, retention_analysis and shots. '
                 'This is current state, not an upcoming story event.\n')
    text+='\n'+AUTO_FILMING
    text+='\n'+(DYNAMIC_EDITING if req.get('dynamic_cuts',True) else
                'Prefer motivated longer takes. Reveal changes through blocking, reframing or camera movement; do not force short-shot clusters.')
    text+='\n'+CLIP_INTENSITY[req.get('intensity','high')]
    if row['mode'] == 'action':
        text += '\n' + MARTIAL_ARTS_DIRECTION
    if req.get('face_identity',True):text+='\nPreserve the assigned reference identities through motion and expressions.'
    text += '\n\nClip timing and audio context:\n' + json.dumps(context, ensure_ascii=False)
    refs=([tail] if tail else [])+list(originals)
    parts=[('text',text)]+_pictures(refs)
    attempts=parts;segment['director_mode']=row['mode']
    # 只有格式壞掉才重試，最多 2 次（舊的「修稿兩輪、重寫五次、最多 18 次」退稿機制已移除）。
    retry_limit = min(rewrite_retry_count(req), 2)
    max_attempts = retry_limit + 1
    for attempt in range(max_attempts):
        if progress:progress({'stage':'rewriting','clip_index':segment['index'],
                              'attempt':attempt+1,'max_attempts':max_attempts})
        segment['prompt_profile']={'source':'isolated_native_director','writer_calls':attempt+1,
                                   'contract_check_calls':0}
        call_cfg = cfg
        if attempt and cfg.get('rewriter', {}).get('thinking'):
            call_cfg = dict(cfg, rewriter=dict(cfg['rewriter'], thinking=False, max_length=8192))
        raw=rewrite(call_cfg,system,attempts,uuid.uuid4().hex[:8])
        try:
            prompt=normalize_mv_prompt(_text(raw),len(refs))
            if len(originals)>1 and not re.search(r'<Picture \d+>',prompt):
                raise SceneStateError('多圖拍攝稿缺少原始圖片綁定。')
            if vocals:
                # Preserve camera prose while discarding an explicit speech instruction.
                prompt = re.sub(
                    r'(?i)\b(?:he|she|they|<Subject \d+>|<Picture \d+>)\s+'
                    r'(?:says?|replies|speaks?|whispers?|recites?)\b[^.\n<]*'
                    r'(<d\b[^>]*>.*?</d\s*>)[.,]?',
                    r'\1', prompt,
                )
                prompt, removed = clean_lyric_output(prompt, dict(req, lyrics_reference_version=2))
                segment['lyric_reference_cleanup'] = {'removed_spans': removed}
                prompt = _apply_source_performance(prompt, vocals, context.get('fixed_reference_settings', ''))
            segment.pop('commission_guard_errors', None)
            return prompt
        except ValueError as error:
            if attempt >= retry_limit:
                raise SceneStateError('當段拍攝稿交稿失敗：'+str(error)) from error
            attempts=parts+[('text','Return only the current native H3 prompt. Fix connected-media delivery: '+str(error))]




# ---------------------------------------------------------------------------
# 精簡通告單：9B 是專門把「官方指南＋簡短描述」改寫成 H3 提示詞的模型，
# 塞 1700 字規則只會讓它反覆檢查、越想越糾結。這裡只給它這段需要的事實：
# 固定設定、目前服裝、上一段怎麼結束、這段的事件、聲音與結尾，其餘交給它拍。

LEAN_INTENSITY = {
    'normal': 'Natural, grounded camera and performance.',
    'high': 'Assertive, inventive commercial-MV photography: strong angles, depth, shaped light and purposeful movement.',
    'extreme': ('Explosive cinematic energy: bold angles, fast motivated movement and peak performance. '
                'The camera lives inside the action, not beside it: wide-lens extreme close-ups, POV, '
                'very low or overhead angles, fast arcs, whip pans, strong shake and brief slow motion; '
                'write camera moves with large amplitude at fast speed.'),
}
LEAN_MAX_REPAIRS = 2
_RUNAWAY = re.compile(r'((?:\S+\s+){1,3}?)\1{19,}')


def degenerate_draft(text):
    """只擋明顯壞掉的稿：同一兩個詞連續跳針十幾次。不評斷內容好壞。"""
    runaway = _RUNAWAY.search(text or '')
    if runaway:
        return f'Your draft got stuck repeating "{runaway[1].strip()}". Write each phrase once.'
    return None
LEAN_MAX_FRESH = 1


def lean_commission(req, segment, tail, row, shoot_event, context, vocals, pictures, connected):
    from banana_mv.continuity import END_STATE_REQUEST, cast_note, handoff_note, wardrobe_note
    seconds = float(segment['seconds'])
    parts = [f"Target video duration: {seconds:.3f} seconds. Primary filming mode: {row['mode']}."]
    fixed = context.get('fixed_reference_settings')
    if fixed:
        parts.append(fixed_settings_block(fixed))
        parts.append(REFERENCE_IDENTITY)
    cast = cast_note(row.get('event', ''), fixed or '')
    if cast:
        parts.append(cast)
    outfits = wardrobe_note('\n'.join(filter(None, (req.get('prompt', ''), segment.get('fixed_reference_settings', '')))),
                            float(segment.get('start', 0.0)), seconds)
    if outfits:
        parts.append(outfits.rstrip())
    if tail:
        if req.get('mode') == 'chain5' and segment.get('motion_frames'):
            parts.append("<Picture 1> is frame F-4 of the previous clip's last five frames, not another actor. "
                         'The four following motion frames are attached after the references; H3 receives the same '
                         'five frames as motion context. This clip continues that motion.')
        else:
            parts.append('<Picture 1> is the previous clip\'s ' + (
                'earliest overlapping tail frame (H3 also receives the following four frames)'
                if req.get('mode') == 'chain5' else 'last frame') + ', not another actor. This clip continues from it.')
    handoff = handoff_note(segment.get('previous_end_state'))
    if handoff:
        parts.append(handoff.rstrip())
    parts.append('THIS CLIP (the only events to perform; later story is not yours):\n' + connected(shoot_event))
    if vocals:
        from banana_mv.continuity import reference_names
        names = reference_names(fixed or '')
        def performer(role):
            picture = pictures.get(role)
            if not picture:
                return 'an unbound performer'
            number = int(re.search(r'\d+', picture)[0])
            return picture + (f' ({names[number]})' if number in names else '')
        rows = []
        for cue in vocals:
            named = ' + '.join(performer(role) for role in cue.get('subjects', []))
            rows.append(f"{cue['clip_start']:.2f}-{cue['clip_end']:.2f}s: {named or 'unassigned'}")
        parts.append('SRT SINGERS (show these performers when covering lip-sync):\n' + '\n'.join(rows))
    parts.append('<Audio 1> is the supplied song, kept unchanged (fully_copy); you have not heard it. '
                 'Add no new speech, lyrics or replacement music. Only the assigned vocalist may lip-sync; '
                 'everyone else keeps their mouth silent. If you use the guide\'s (Sx) speaker tags, only the singing '
                 'performer gets one; never tag a silent actor, and do not write lyrics as <d> lines.')
    ending_info = context.get('ending') or {}
    ending = ending_info.get('instruction')
    if ending:
        timing = ', '.join(f'{key}={float(ending_info[key]):g}s' for key in
                           ('resolve_start_by', 'settle_by', 'end_time', 'hold_seconds')
                           if isinstance(ending_info.get(key), (int, float)))
        parts.append('ENDING FOR THIS CLIP: ' + ending + (f' (clip-local times: {timing})' if timing else ''))
    if row['mode'] == 'action':
        parts.append(MARTIAL_ARTS_DIRECTION)
    from banana_mv.core import action_lora_brief
    if brief := action_lora_brief(req):
        parts.append(brief)
    parts.append('DIRECTION: ' + ('Free MV adaptation: invent striking staging, performance and montage that serve this beat.'
                                  if req.get('story_plan', True) else
                                  'Faithful: stage exactly the supplied events; camera choices are yours.')
                 + ' ' + LEAN_INTENSITY.get(req.get('intensity', 'high'), LEAN_INTENSITY['high'])
                 + (' Use motivated short shots and intercuts where the music has accents.'
                    if req.get('dynamic_cuts', True) else ' Prefer motivated longer takes.'))
    parts.append('PYTHON FILLS IN LATER (do not deliberate): overall_soundscape and non_diegetic_music are replaced '
                 'with the unchanged source song after you finish, so write each as one short line. Props and set '
                 'dressing (furniture, a desk furnace, screens, drinks) are described inside the shots and need no '
                 '<Subject> entry; give <Subject> entries only to the on-screen actors and, if useful, one environment.')
    parts.append("Write the guide's six native sections for this one clip.\n" + END_STATE_REQUEST)
    return '\n\n'.join(parts)


MOTION_FRAMES_NOTE = (
    'MOTION FRAMES: the next images continue <Picture 1> frame by frame (F-3, F-2, F-1, then F-0 = the '
    "previous clip's final frame). Compare <Picture 1> through F-0 to read what is still moving: the "
    'direction (as seen from the camera) and speed of every body movement and of the camera. Open this '
    'clip by continuing that real motion in the same direction. These frames are NOT <Picture N> '
    'references: never cite them, and never describe them as extra actors.'
)


def motion_frame_parts(paths):
    """末五幀模式下 F-3…F-0 四張動作格，縮小後接在參考圖之後，用獨立標籤。"""
    from PIL import Image, ImageOps
    frames = [Path(p) for p in paths or [] if Path(p).is_file()]
    if not frames:
        return []
    parts = [('text', MOTION_FRAMES_NOTE)]
    labels = ['F-3', 'F-2', 'F-1', 'F-0 (final frame)'][-len(frames):]
    for label, path in zip(labels, frames):
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert('RGB')
            im.thumbnail((512, 512))
            parts.extend([('text', f'Motion frame {label}:'), ('image', im.copy())])
    return parts


_SETUP_BINDING = re.compile(
    r'^(\s*)(<Picture\s*(\d+)>|@圖片\s*(\d+))\s*[=＝]\s*([^=＝\n]+?)\s*[=＝]\s*(S[1-8])\b', re.M)


def fixed_settings_block(fixed, subjects=False):
    """共同設定全文給 9B 看（精簡通告單與雙人自由攝影共用，兩條路徑資訊量一致）。

    subjects=True 是雙人自由攝影：人物由 Python 組 <Subject N>，所以綁定行改成
    「名字＝<Subject N>」，不讓 9B 看到 <Picture N>（接續段的 <Picture 1> 是上一段尾幀）。
    """
    names = {role.upper(): name.strip() for *_, name, role in _SETUP_BINDING.findall(fixed)}
    if subjects:
        fixed = _SETUP_BINDING.sub(lambda m: f'{m[1]}{m[5].strip()}＝<Subject {m[6][1]}>', fixed)
    # 使用者的「= S1」是給 Python 對 SRT 用的；官方指南的 (S1) 是「誰在說話」的標記。
    # 兩個 S1 撞名會讓 9B 把不唱歌的人標成 (S1)，所以給 9B 看的版本拿掉角色代號。
    shown = re.sub(r'\s*[=＝]\s*S[1-8]\b(?=\s*[，,。；;]|\s*$)', '', fixed, flags=re.M)
    # 內文的 S1/S2 換成綁定的名字：「面對S2的攻勢」→「面對小語的攻勢」，不能直接刪掉變成「面對的攻勢」。
    # 沒有綁定名字時沿用舊做法：「只有 S1 男主角」→「只有 男主角」。
    def named(m):
        name = names.get(m[1].upper(), '')
        return '' if name and m.string.startswith(name, m.end()) else name   # 「S1 男主角」不疊字
    shown = re.sub(r'(?<![A-Za-z<(])(S[1-8])\s*(?=[\u4e00-\u9fff])', named, shown)
    return 'FIXED REFERENCE SETTINGS (identities, voices, world; not a mandatory cast list):\n' + shown


def _write_lean_prompt(cfg, req, segment, originals, tail, rewrite, progress,
                       row, shoot_event, context, vocals, pictures, connected):
    from banana_mv.continuity import absent_pictures, cast_errors, split_end_state
    refs = ([tail] if tail else []) + list(originals)
    text = lean_commission(req, segment, tail, row, shoot_event, context, vocals, pictures, connected)
    system = NATIVE_ENHANCER_SYSTEM + Path(cfg['guides']['ref']).read_text(encoding='utf-8')
    motion = motion_frame_parts(segment.get('motion_frames')) if tail and req.get('mode') == 'chain5' else []
    segment['motion_frames_to_9b'] = sum(1 for kind, _ in motion if kind == 'image')
    # 沒入鏡的角色：圖片不給 9B 看，只留一行文字，其他人的 <Picture N> 編號不變。
    hidden = absent_pictures(row.get('event', ''), context.get('fixed_reference_settings', ''))
    pictures_parts = []
    for number, path in enumerate(refs, 1):
        if number in hidden:
            pictures_parts.append(('text', f'<Picture {number}>: not in this clip (image withheld; do not use it).'))
        else:
            image = _pictures([path])[1]          # ('image', 縮好的圖)；標籤用正確編號
            pictures_parts.extend([('text', f'<Picture {number}>:'), image])
    segment['withheld_pictures'] = sorted(hidden)
    base = [('text', text)] + pictures_parts + motion
    attempts = base
    segment['director_mode'] = row['mode']
    segment['commission_words'] = len(text.split())
    repairs = fresh = 0
    rejections = segment['writer_rejections'] = []   # 退稿原因留在專案裡
    total = (LEAN_MAX_FRESH + 1) * (LEAN_MAX_REPAIRS + 1)
    last_problem = None
    for attempt in range(total):
        if progress:
            progress({'stage': 'rewriting', 'clip_index': segment['index'], 'attempt': attempt + 1, 'max_attempts': total})
        segment['prompt_profile'] = {'source': 'lean_commission', 'writer_calls': attempt + 1, 'fresh_restarts': fresh}
        call_cfg = cfg
        if attempt and cfg.get('rewriter', {}).get('thinking'):
            # 修稿與重寫只處理格式或衝突，關掉 thinking 讓它快速交稿。
            call_cfg = dict(cfg, rewriter=dict(cfg['rewriter'], thinking=False, max_length=8192))
        raw = rewrite(call_cfg, system, attempts, uuid.uuid4().hex[:8])
        try:
            body, end_state = split_end_state(_text(raw))
            broken = degenerate_draft(body)
            if broken:
                raise SceneStateError(broken)
            prompt = normalize_mv_prompt(body, len(refs))
            if len(originals) > 1 and not re.search(r'<Picture \d+>', prompt):
                raise SceneStateError('多圖拍攝稿缺少原始圖片綁定。')
            if vocals:
                prompt, removed = clean_lyric_output(prompt, dict(req, lyrics_reference_version=2))
                segment['lyric_reference_cleanup'] = {'removed_spans': removed}
                prompt = _apply_source_performance(prompt, vocals, context.get('fixed_reference_settings', ''))
            problems = cast_errors(prompt, row.get('event', ''), context.get('fixed_reference_settings', ''), bool(tail))
            if problems and repairs < LEAN_MAX_REPAIRS:
                rejections.append({'call': attempt + 1, 'kind': 'repair', 'reason': ' | '.join(problems)[:500]})
                repairs += 1
                attempts = base + [('text', 'REPAIR THIS CLIP ONLY. Fix exactly these conflicts with the commission, '
                                    'keep everything else, and return all six sections plus END_STATE.\nCONFLICTS:\n'
                                    + '\n'.join(problems) + '\nPREVIOUS DRAFT:\n' + prompt)]
                continue
            # 修稿兩輪後仍有衝突：交出這版並標示，讓使用者在毛片室決定，不再無限重寫。
            if problems:
                segment['commission_guard_warnings'] = problems
            else:
                segment.pop('commission_guard_warnings', None)
            segment.pop('commission_guard_errors', None)
            if end_state:
                from banana_mv.continuity import name_subjects
                segment['end_state'] = name_subjects(end_state, prompt, context.get('fixed_reference_settings', ''))
            else:
                segment.pop('end_state', None)
            return prompt
        except ValueError as error:
            last_problem = error
            rejections.append({'call': attempt + 1, 'kind': 'format', 'reason': str(error)[:500]})
            if fresh >= LEAN_MAX_FRESH:
                break
            fresh += 1
            repairs = 0
            attempts = base + [('text', 'Return only the six native H3 sections plus END_STATE. Fix: ' + str(error))]
    raise SceneStateError(f'當段拍攝稿交稿失敗（已重寫 {fresh} 次）：{last_problem}')
