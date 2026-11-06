"""Allocate once; let the native H3 rewriter shoot each isolated interval."""
import json
import re
import uuid
from pathlib import Path

from banana_mv.core import map_image_mentions, normalize_mv_prompt
from banana_mv.director import MODES, INTENSITY, ORIGINAL_CUT_GUIDANCE
from banana_mv.lyrics_reference import excerpt
from banana_mv.mv_scope import clip_ending, ending_contract
from banana_mv.scene_state import SceneStateError, atomic_json, digest, rewrite_retry_count


# Match Toybox's native Ref2VA enhancement role, rather than treating the
# specialized rewriter as a general JSON-task executor. The official guide stays
# authoritative for shot prose and output structure; MV source-audio rules follow
# in the user message. No additional writer or fixed camera recipe is involved.
NATIVE_ENHANCER_SYSTEM = (
    "You enhance prompts for reference-conditioned video and audio generation (Ref2VA). "
    "Infer reference roles from the user's prompt and supplied media. "
    "Preserve intent and explicit constraints while adding relevant visual and sound details. "
    "Follow the guide below and return only its six sections in order, "
    "with plain-text headers on separate lines and no Markdown fences.\n\n"
)


ALLOCATION_SYSTEM = """Prepare a filmable music-video story across the given source intervals.
If the user supplies only a backbone, develop concrete actions along it. If the user
already supplies a detailed script, retain its actions, causal links and specified
ending and allocate it, rather than rewriting it. The native clip director later
decides HOW to film each assigned part.
Extract shared SETUP from the user's fixed world, reference and vocal-role settings.
Keep their original wording and distinct locations; do not summarize or redesign them.
Use the supplied pictures for appearance, not a generic textual replacement of the asset.
Deliver self-contained interval scripts with concrete actions and interactions, not
plot summaries. Allocate by story and source timing, not mechanically by paragraph.
Keep original <Picture N> numbers.
Each brief states the actors actually present, their CURRENT look, location and props,
and ONLY this interval's events and necessary changes. Carry state, never a history recap.
Identity changes happen once in their assigned interval; subsequent briefs start in the
resulting identity. Shared SETUP contains no plot chronology, future events or finale.
Preserve the supplied backbone, causal order, explicit cue-bound events and outcome.
Preserve essential supplied actions, recipients, props, outcomes and explicit special shots.
FREE may develop compatible action, interactions and parallel intercuts along the backbone;
FAITHFUL also preserves the supplied event order. Neither redesigns the fixed settings.
Parallel performance and story strands may intercut; no singer quota, mandatory cast
attendance, shot list or complete dramatic arc per interval. Allocate a feasible amount
of action to each duration. Respect local_srt cue timing and each interval's ending.
Distribute the developed story across intervals, splitting a sequence when needed.
Do not shorten it into generic beats or add unrelated plot. Do not add shot lists;
retain special camera directions already supplied by the user with their events.
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


def ensure_shoot_plan(cfg,req,segments,originals,work,rewrite):
    """Persist allocated scripts and fixed settings, without replanning per slot."""
    contract=ending_contract(req,segments[-1]['start']+segments[-1]['seconds'],segments)
    timeline=[]
    for seg in segments:
        timeline.append({k:seg[k] for k in ('index','start','seconds')} | {
            'local_srt':excerpt(req,seg),'audio_evidence':seg.get('audio_evidence',{}),
            'ending':clip_ending(req,dict(seg,direction_ending_contract=contract))})
    task={'format':'isolated_shoot_briefs_v1',
          'brief':map_image_mentions(req.get('prompt',''),len(originals)),
          'adaptation':'FREE' if req.get('story_plan',True) else 'FAITHFUL',
          'style':req.get('director','auto'),'lyrics':req.get('lyrics',''),
          'timeline':timeline,
          'ending_contract':contract}
    fingerprint=digest(task);path=Path(work)/'director_plan.json'
    if path.is_file():
        plan=json.loads(path.read_text(encoding='utf-8'))
        if (plan.get('version')!=5 or plan.get('input_sha256')!=fingerprint or
            digest({k:v for k,v in plan.items() if k not in ('content_sha256','input_sha256')})!=plan.get('content_sha256')):
            raise SceneStateError('分段拍攝大綱與專案不符或校驗失敗。')
        return plan
    parts=[('text',json.dumps(task,ensure_ascii=False))]+_pictures(originals)
    system=ALLOCATION_SYSTEM+'\nSupported modes: '+', '.join(MODES)+f'. Deliver {len(segments)} CLIP blocks.'
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
                result.append({'index':seg['index'],'mode':row['mode'],
                               'event':_bound(row['prompt'],len(originals))})
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
                            'No analysis. Delivery error: '+str(error))]


def write_shoot_prompt(cfg,req,segment,originals,tail,rewrite,progress=None):
    """The first and only shot-writing stage; it cannot see the full story."""
    row=segment['director_plan'];offset=int(bool(tail))
    def connected(text):
        # Only numbering changes for an actual keyframe. Never compact actor slots.
        return re.sub(r'<Picture (\d+)>',lambda m:f'<Picture {int(m[1])+offset}>',text)
    context={'seconds':segment['seconds'],'primary_mode':row['mode'],
          'local_srt':excerpt(req,segment),'audio_evidence':segment.get('audio_evidence',{}),
          'ending':clip_ending(req,segment)}
    if tail:context['first_frame']='<Picture 1> is the actual previous last frame, not another actor.'
    guide=Path(cfg['guides']['ref']).read_text(encoding='utf-8')
    system=NATIVE_ENHANCER_SYSTEM+guide
    text=(f"Target video duration: {segment['seconds']:.6f} seconds.\n"
          "Inspect the reference images labeled <Picture N> and use them according to the user's instructions.\n"
          "Choose shots that best express the original intent. "
          "Allocate shot durations and cut timing within the target duration according to content and pacing. "
          "Respect explicit shot requests, reference constraints and the guide's transition rules.\n"
          "Original prompt:\nShared world and reference roles:\n"+connected(segment['shoot_setup'])+
          "\n\nCurrent clip script:\n"+connected(row['event'])+"\n\n")
    text+="""Enhance this ONE clip script into the guide's final native H3 filming prompt,
including its per-shot composition, lighting, actions and camera movement.
The current clip script is complete for this interval, not a synopsis to expand
into other story chapters. Shared settings retain the user's locations and asset roles;
keep separate locations distinct, intercutting them rather than merging their sets or
placing their casts in one shared frame. Only actors needed by this script appear.
Use the actual reference appearance, not a generic version of its species or object type.
Preserve current looks and props rather than resetting to
reference clothing. Freely choose shots, staging and editing that express this script.
Identity references do not freeze pose, expression, gaze or camera view unless assigned
as frame anchors. All shot times are LOCAL and within the target duration; alignment
padding adds no story time. Continue actions across cuts, without replaying the event.
Use only connected pictures and <Audio 1>: fully_copy. The source audio is supplied to
H3, not heard by you. Only the assigned vocalist may lip-sync. Add no new speech,
lyrics, subtitles, sound layers or replacement song. Supplied SRT is timing evidence, not dialogue.
Follow this clip's ending; an ongoing clip needs no whole-work finale.
Return only the native filming prompt, no analysis, JSON or management instructions.
"""
    text+='\n'+(ORIGINAL_CUT_GUIDANCE if req.get('dynamic_cuts',True) else 'Prefer motivated longer takes.')
    text+='\n'+INTENSITY[req.get('intensity','high')]
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

