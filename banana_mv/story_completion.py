"""Trace required story events to local scripts before approving a complete MV.

Evidence is a model's interpretation of text, not verification of generated video.
The program checks source quotes, coverage, local proof and ending placement.
"""
import copy
import json
import re
import uuid
from pathlib import Path
from banana_mv.scene_state import SceneStateError,atomic_json,digest,rewrite_retry_count

PHASES={'BEGINNING','DEVELOPMENT','RESOLUTION','FINAL_IMAGE'}
REQUIREMENTS_SYSTEM='''Read the ENTIRE supplied user story before allocating any time.
Extract the mandatory story backbone, explicitly required events, causal turns,
required resolution and final image. Do not stop after its first paragraphs.
Preserve parallel performance/story strands and required comedy beats. Optional
camera suggestions are not new plot milestones. Never replace a specified ending
with continuing action, a promise of a future finale, or a generic victory pose.
The selected COMPLETE STORY scope means this uploaded audio, even if cropped from
a longer song or ending during a chorus, is the whole available film duration.
Return faithful English event requirements, preserving original names and references.
Each SOURCE copies original sentences from user_brief proving the requirement.
You may select several original sentences in their original order and omit intervening
sentences; do not paraphrase, translate, reorder or invent quoted wording.
Prefer short source excerpts rather than copying a whole scene.
Use SOURCE: [INFERRED] only for a necessary unstated resolution/final image; if the
brief is empty, infer a simple opening/development/resolution from the requested style.
Include BEGINNING, DEVELOPMENT, RESOLUTION and FINAL_IMAGE; a continuous performance
may have a local progression and final visual resolution without inventing a new plot.
List each mandatory event separately, in causal order. A resolution may need multiple
milestones, such as decisive action, judgment, award and final joke. Preserve all.
Use only this plain text protocol (no JSON, analysis, shots, times or arbitrary quotas):
=== REQUIRE M0 BEGINNING ===
SOURCE: exact quote
EVENT: faithful English event
=== REQUIRE M1 DEVELOPMENT ===
SOURCE: exact quote
EVENT: faithful English event
=== REQUIRE M2 RESOLUTION ===
SOURCE: exact quote or [INFERRED]
EVENT: the actual outcome to finish
=== REQUIRE M3 FINAL_IMAGE ===
SOURCE: exact quote or [INFERRED]
EVENT: the specified final image, or a coherent inferred one if none specified
=== END ==='''

AUDIT_SYSTEM='''Check mandatory story-event coverage against the actual allocated CLIP scripts.
This is a fresh coverage check, not a creative rewrite or a check of declared intentions.
For EVERY requirement, decide whether a local script explicitly stages that event
or (for FINAL_IMAGE only) sustains its already-established result. A shared SETUP,
ending_contract, summary or promise to finish later is NOT evidence. Words such as
"toward the final blow-off", "keeps advancing", "ready for the next round", or
"resumes the match" do not prove a requested knockout, judgment, award or final joke.
All required phases and mandatory milestones must occur in causal order by the audio end.
Do not accept an event's mere mention, negation, rehearsal, anticipation or future tense
as an occurrence. No invented proof: copy a contiguous quote from its actual local script.
If a mandatory event spans clips, cite the clip where it is actually completed.
Use exactly one block per requirement, with its original M-id:
=== COVER M0 CLIP 0 ===
exact contiguous quote from that clip proving completion
=== MISSING M1 ===
what is absent or contradicted
=== END ===
Return only these blocks. Do not repair the story in this check.'''


def normalized(text):
    # Paragraph/newline layout is not story content, especially between CJK sentences.
    return re.sub(r'\s+','',text)


def source_fragments(quote,brief):
    source=normalized(brief)
    if normalized(quote) in source:return [quote.strip()]
    # Allow ordered extractive sentences and explicit ellipsis, but never fuzzy
    # words or semantic substitutions. Every retained fragment must occur verbatim.
    parts=[p.strip() for p in re.split(r'(?<=[。！？])|…+|\.{3,}',quote) if p.strip()]
    cursor=0
    for part in parts:
        token=normalized(part)
        if not token or not re.search(r'[\w\u3400-\u9fff]',token):return None
        offset=source.find(token,cursor)
        if offset<0:return None
        cursor=offset+len(token)
    return parts or None



def body(raw):
    if not isinstance(raw,str):raise SceneStateError('完整故事檢查未回傳文字。')
    raw=re.sub(r'<think>.*?</think>','',raw,flags=re.S).strip()
    if not re.search(r'^=== END ===\s*$',raw,re.M):raise SceneStateError('完整故事檢查交稿截斷，缺少 END。')
    return raw


def parse_requirements(raw,brief):
    text=body(raw);rows=[];seen=set()
    blocks=re.findall(r'^=== REQUIRE (M\d+) (BEGINNING|DEVELOPMENT|RESOLUTION|FINAL_IMAGE) ===\s*\n(.*?)(?=^=== )',text,re.S|re.M)
    for key,phase,content in blocks:
        match=re.fullmatch(r'SOURCE:\s*(.*?)\nEVENT:\s*(.+?)\s*',content,re.S)
        if not match or key in seen:raise SceneStateError('故事必要事件格式或編號重複。')
        quote,event=match.groups();quote=quote.strip();event=event.strip()
        if not quote or not event:raise SceneStateError('故事必要事件缺少來源或事件。')
        if quote=='[INFERRED]':
            if brief.strip() and phase not in ('RESOLUTION','FINAL_IMAGE'):
                raise SceneStateError('開場與發展需依使用者故事擷取，不得憑空增加必要事件。')
        elif not source_fragments(quote,brief):
            raise SceneStateError(f'{key} 的來源引文有無法對回原文的句子；僅接受原文擷取，不接受改寫或捏造。')
        seen.add(key);rows.append({'id':key,'phase':phase,'source':quote,'event':event})
    if not rows or len(rows)>64 or {r['phase'] for r in rows}!=PHASES:
        raise SceneStateError('完整故事需交齊開場、發展、解決與最後畫面的必要事件。')
    return rows


def reviewer_cfg(cfg):
    value=copy.deepcopy(cfg)
    if 'rewriter' in value:value['rewriter']['temperature']=.1
    return value


def requirements(cfg,brief,req,work,rewrite):
    identity={'version':1,'source_sha256':digest({'brief':brief,'style':req.get('director'),'scope':'full'})}
    path=Path(work)/'story_requirements.json'
    if path.is_file():
        saved=json.loads(path.read_text(encoding='utf-8'))
        if any(saved.get(k)!=v for k,v in identity.items()) or digest(saved['requirements'])!=saved.get('content_sha256'):
            raise SceneStateError('故事必要事件與來源不符，請建立新任務，未改寫舊計畫。')
        return saved['requirements']
    parts=[('text',json.dumps({'user_brief':brief,'style':req.get('director'),'scope':'complete_story_within_uploaded_audio'},ensure_ascii=False))]
    for attempt in range(rewrite_retry_count(req)+1):
        raw=rewrite(reviewer_cfg(cfg),REQUIREMENTS_SYSTEM,parts,uuid.uuid4().hex[:8])
        try:
            result=parse_requirements(raw,brief)
            atomic_json(path,dict(identity,requirements=result,content_sha256=digest(result)))
            return result
        except ValueError as error:
            atomic_json(Path(work)/f'requirements_attempt_{attempt:02d}.json',{'raw':raw,'error':str(error)})
            if attempt>=rewrite_retry_count(req):raise
            parts=parts[:1]+[('text','Correct source quoting and delivery only: '+str(error))]


def check_coverage(raw,required,rows,segments,contract):
    text=body(raw);expected={r['id']:r for r in required};proof={};missing=[]
    blocks=re.findall(r'^=== (COVER (M\d+) CLIP (\d+)|MISSING (M\d+)) ===\s*\n(.*?)(?=^=== )',text,re.S|re.M)
    for _,covered,index,absent,content in blocks:
        key=covered or absent
        if key not in expected or key in proof:raise SceneStateError('故事覆蓋檢查出現錯誤或重複事件編號。')
        if absent:
            proof[key]=None;missing.append(key+': '+content.strip());continue
        index=int(index)
        if not 0<=index<len(rows) or not content.strip() or normalized(content) not in normalized(rows[index]['event']):
            raise SceneStateError(f'{key} 缺少對應當段劇本的原文證據。')
        phase=expected[key]['phase']
        if phase=='RESOLUTION':
            nominal=max(s['seconds'] for s in segments)
            tiny=len(segments)>1 and segments[-1]['seconds']<nominal*.5
            if segments[index]['start']>=contract['settle_by'] or (tiny and index==len(segments)-1):
                raise SceneStateError(f'{key} 決定性結局排得太晚；零星尾段前的完整段落必須先完成收束。')
        proof[key]={'clip_index':index,'evidence':content.strip()}
    if set(proof)!=set(expected):raise SceneStateError('故事覆蓋檢查未逐項交齊，不能視為完整故事。')
    if missing:raise SceneStateError('完整故事漏演必要事件：'+'; '.join(missing))
    starts=[proof[r['id']]['clip_index'] for r in required if r['phase']=='BEGINNING']
    ends=[proof[r['id']]['clip_index'] for r in required if r['phase']=='RESOLUTION']
    finals=[proof[r['id']]['clip_index'] for r in required if r['phase']=='FINAL_IMAGE']
    developments=[proof[r['id']]['clip_index'] for r in required if r['phase']=='DEVELOPMENT']
    if min(ends)<min(starts) or max(ends)<max(developments) or min(finals)<max(ends):
        raise SceneStateError('起中尾順序錯誤：結局或最後畫面早於必要發展完成。')
    return {'status':'passed','kind':'model_text_coverage','requirements':required,'coverage':proof,
            'limitations':'Model-based textual interpretation; not proof of visual execution or perfect semantic coverage.'}


def audit(cfg,required,rows,segments,contract,work,rewrite,attempt):
    task={'requirements':required,'clips':rows,'source_intervals':[{k:s[k] for k in ('index','start','seconds')} for s in segments],'ending_contract':contract}
    raw=rewrite(reviewer_cfg(cfg),AUDIT_SYSTEM,[('text',json.dumps(task,ensure_ascii=False))],uuid.uuid4().hex[:8])
    try:
        result=check_coverage(raw,required,rows,segments,contract)
        atomic_json(Path(work)/f'completion_audit_{attempt:02d}.json',dict(result,raw=raw))
        return result
    except ValueError as error:
        atomic_json(Path(work)/f'completion_audit_{attempt:02d}.json',{'status':'failed','raw':raw,'error':str(error)})
        raise
