"""Persistent *planned* scene state; not a visual verifier or camera-continuity system."""
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from pathlib import Path
import uuid

VERSION = 1
STATUSES = {'worn','unfastened','partially_removed','removed','held','placed'}
OPERATIONS = {'update','remove','dress','acquire','drop','use','damage','restore','heal','move'}
GARMENT_EDGES = {
    'worn': {'unfastened','partially_removed','removed','held','placed'},
    'unfastened': {'worn','partially_removed','removed','held','placed'},
    'partially_removed': {'worn','removed','held','placed'},
    'removed': {'held','placed','worn'}, 'held': {'placed','removed','worn'},
    'placed': {'held','removed','worn'},
}
RULES = '''[BANANA_PERSISTENT_SCENE_STATE_V1]
The current clip inherits narrative and mutable appearance from scene_state_in.
Uploaded original references define identity, not the current wardrobe or mutable appearance.
Initial costumes apply only at the beginning of the full timeline; do not reset at a new clip,
cut, reference-image read or subject_definitions rewrite. The structured input overrides initial
costume/hairstyle descriptions in the whole-song brief and generic preserve-costume guidance.
Completed one-time events stay completed. Removed garments/objects stay removed unless an explicit
permitted new event restores them. Do not replay completed actions or consume reserved final events
in a non-final interval. A normal shot may end naturally without suspense or a whole-song ending.
Only plan this source-audio interval. State out is an intended plan, NOT an observed video result.
Keep free cinematography, independent clips, music-led edits and the user's vocal/scene restrictions.
No camera position, lens, shot count, cut formula, last-frame image or motion matching is required.
Only include mutable wardrobe fields for roles that need them; do not impose human clothes on mascots.
Describe current wardrobe/props/environment explicitly in clip_prompt. Put removed clothing in the
removed/placed context, never describe it as currently worn. Never insert initial-state resets.
Return structured event IDs and transitions; do not infer a state change merely from a camera cut.
[/BANANA_PERSISTENT_SCENE_STATE_V1]'''

INIT_SYSTEM = '''Initialize a structured state ledger for a complete music-video brief, not a clip prompt.
Return ONLY JSON: {"initial_state":{"character_states":{},"environment_states":{}},"events":[]}.
character_states maps stable subject IDs S1, S2, etc. to {"identity_reference":1 or null,
"hairstyle":"description","garments":{"coat":{"garment_id":"coat","garment_type":"coat",
"material":"...","color":"...","current_status":"worn","current_location":"S1"}},
"appearance_changes":[],"injuries":[],"held_props":[],"location":"scene_id"}.
identity_reference is the 1-based UPLOADED ORIGINAL image index, never a continuation keyframe index.
If original image 1 defines a character, bind its primary character to S1 to match the existing Face Lock.
In H3 clip prompts, stable S1 corresponds to <Subject 1>, S2 to <Subject 2>, and so on.
Use user/reference costumes initially unless the user overrides them. Declare each story-relevant garment
once with a stable ID; unrelated roles/mascots may have an empty garments object. Do not invent nudity,
wardrobe changes, injuries, props or destruction that the brief does not request.
environment_states maps stable scene IDs to {"active_location":"description","persistent_changes":[],
"damaged_objects":{},"prop_positions":{}}. Values of damaged_objects and prop_positions are strings.
events is 1–128 entries {"event_id":"E1","description":"specific event/visual consequence",
"repeatable":false,"reserved_final":false,"depends_on":[],"allowed_operations":["move","update"]}.
Use stable event IDs for one-time developments; break a multi-step change into distinct milestones.
Recurring performance can be repeatable; a one-time action is NOT repeatable just to fit clip count.
Allowed operation names: update, remove, dress, acquire, drop, use, damage, restore, heal, move.
Grant dress/restore/heal ONLY to events explicitly requested to restore a prior state. Removal never
implies redressing. Do not reserve all intermediate changes for the finale; reserved_final is only
for full-song final resolution/terminal actions. Dependencies must reference other event IDs without cycles.
Use the full brief, measured timeline, lyric references and existing event allocation as material.
Preserve user priority, identities and vocal/scene roles. No fixed cast, genre or camera setup.
Initial state and all event changes are planned, not visually verified.''' 

CLIP_SYSTEM = '''PERSISTENT STATE OUTPUT CONTRACT (overrides prose-only output format):
Return ONLY JSON: {"clip_prompt":"the complete H3 prompt text for THIS interval",
"planned_events":["E1"],"completed_events":["E1"],"state_transitions":[]}.
Keep the stable subject IDs and uploaded-image identity mapping from scene_state_in in subject_definitions.
Use event IDs from the provided catalog. planned_events is their execution order; completed_events is
only the subset completed in this clip. Unfinished events may continue later. Do not repeat completed
non-repeatable IDs. Every transition must cite its planned event_id and a permitted operation.
A garment transition is {"kind":"garment","subject_id":"S1","garment_id":"coat",
"from":"worn","to":"removed","current_location":"floor","event_id":"E1","operation":"remove"}.
Other character changes: {"kind":"character","subject_id":"S1","field":"location",
"from":"stage","to":"arena","event_id":"E1","operation":"move"}.
Mutable character fields: hairstyle (string), appearance_changes/injuries/held_props (string lists), location (string).
Environment changes: {"kind":"environment","scene_id":"arena","field":"damaged_objects",
"from":{},"to":{"table":"toppled"},"event_id":"E1","operation":"damage"}.
Environment fields: active_location (string), persistent_changes (string list), damaged_objects/prop_positions
(string maps). from must equal the current value, including earlier changes in this same response.
Do not change identity references, invent missing garment IDs, or reset state. A removed/held/placed garment
can become worn ONLY via a dress operation on an event explicitly authorized for dress.
The application computes canonical scene_state_out and remaining events from these deltas. Do not emit
or replace full snapshots, pending lists or timeline values. Keep clip_prompt compatible with the existing
H3 media tags and audio rules. Do not copy the whole-song outline or initial costumes into the clip.
On final clips, finish the reserved final events. Non-final clips may end their local shot without a finale.
''' + RULES


class SceneStateError(ValueError):
    pass


def parse_object(raw):
    if isinstance(raw,str):
        raw=re.sub(r'<think>.*?</think>','',raw,flags=re.S).strip()
        raw=re.sub(r'^```(?:json)?\s*|\s*```$','',raw).strip()
        try:raw=json.loads(raw)
        except ValueError as error:raise SceneStateError('狀態回傳不是有效 JSON。') from error
    if not isinstance(raw,dict):raise SceneStateError('狀態資料必須是 JSON 物件。')
    if len(json.dumps(raw,ensure_ascii=False))>180000:raise SceneStateError('狀態資料過大。')
    return raw


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def atomic_json(path,value):
    path=Path(path);temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def text(value):
    if not isinstance(value,str) or len(value)>2000:raise SceneStateError('狀態文字格式錯誤。')
    return value


def string_list(value):
    if not isinstance(value,list) or len(value)>256:raise SceneStateError('狀態清單格式錯誤。')
    if any(not isinstance(v,str) or len(v)>2000 for v in value):raise SceneStateError('狀態清單需為文字。')
    if len(value)!=len(set(value)):raise SceneStateError('狀態清單含重複值。')
    return value


def string_map(value):
    if not isinstance(value,dict) or len(value)>128:raise SceneStateError('狀態對照表格式錯誤。')
    for key,item in value.items():text(key);text(item)
    return value


def sync_outfit(character):
    character['current_outfit']=[key for key,g in character['garments'].items()
                                 if g['current_status'] in ('worn','unfastened','partially_removed')]
    character['removed_garments']=[key for key in character['garments'] if key not in character['current_outfit']]


@dataclass
class PersistentSceneState:
    character_states: dict
    environment_states: dict
    narrative_states: dict
    timeline: dict

    def to_dict(self):
        return asdict(self)


def initial_state(raw,segments,picture_count):
    raw=parse_object(raw);source=raw.get('initial_state')
    if not isinstance(source,dict):raise SceneStateError('缺少 initial_state。')
    chars=deepcopy(source.get('character_states',{}));envs=deepcopy(source.get('environment_states',{}))
    if not isinstance(chars,dict) or not isinstance(envs,dict) or len(chars)>32 or len(envs)>32:
        raise SceneStateError('角色／場景狀態格式錯誤。')
    for key,c in chars.items():
        text(key)
        if not re.fullmatch(r'S[1-9]\d*',key):raise SceneStateError('角色 ID 需為穩定的 S1、S2 等格式。')
        if not isinstance(c,dict):raise SceneStateError('角色狀態格式錯誤。')
        ref=c.get('identity_reference')
        if ref is not None and (isinstance(ref,bool) or not isinstance(ref,int) or not 1<=ref<=picture_count):
            raise SceneStateError('角色引用了不存在的原始圖片。')
        allowed={'identity_reference','hairstyle','garments','appearance_changes','injuries','held_props','location'}
        if set(c)-allowed:raise SceneStateError('初始角色含未知狀態欄位。')
        c.setdefault('identity_reference',None)
        for f in ('hairstyle','location'):c[f]=text(c.get(f,''))
        for f in ('appearance_changes','injuries','held_props'):c[f]=string_list(c.get(f,[]))
        garments=c.setdefault('garments',{})
        if not isinstance(garments,dict) or len(garments)>64:raise SceneStateError('服裝清單格式錯誤。')
        for gid,g in garments.items():
            text(gid)
            if not isinstance(g,dict) or g.get('garment_id')!=gid or g.get('current_status') not in STATUSES:
                raise SceneStateError('衣物 ID 或狀態錯誤。')
            if set(g)!={'garment_id','garment_type','material','color','current_status','current_location'}:
                raise SceneStateError('衣物需有類型、材質、顏色、狀態與位置。')
            for value in g.values():text(value)
        sync_outfit(c)
    if any(c['identity_reference']==1 for c in chars.values()) and chars.get('S1',{}).get('identity_reference')!=1:
        raise SceneStateError('原始圖片1的主要角色需對應 S1，以沿用 Face Lock。')
    for key,e in envs.items():
        text(key)
        if not isinstance(e,dict) or set(e)-{'active_location','persistent_changes','damaged_objects','prop_positions'}:
            raise SceneStateError('場景狀態格式錯誤。')
        e['active_location']=text(e.get('active_location',''))
        e['persistent_changes']=string_list(e.get('persistent_changes',[]))
        for f in ('damaged_objects','prop_positions'):e[f]=string_map(e.get(f,{}))
    rows=raw.get('events')
    if not isinstance(rows,list) or not 1<=len(rows)<=128:raise SceneStateError('需有 1–128 個結構化事件。')
    catalog={}
    for row in rows:
        if not isinstance(row,dict):raise SceneStateError('事件格式錯誤。')
        eid=text(row.get('event_id'));description=text(row.get('description'))
        if not eid or not description or eid in catalog:raise SceneStateError('事件 ID／描述空白或重複。')
        for field in ('repeatable','reserved_final'):
            if not isinstance(row.get(field,False),bool):raise SceneStateError('事件旗標需為布林值。')
        ops=string_list(row.get('allowed_operations',[]));deps=string_list(row.get('depends_on',[]))
        if set(ops)-OPERATIONS:raise SceneStateError('事件操作代碼無效。')
        catalog[eid]={'description':description,'repeatable':row.get('repeatable',False),
                      'reserved_final':row.get('reserved_final',False),'depends_on':deps,'allowed_operations':ops}
    visiting=set();visited=set()
    def visit(eid):
        if eid not in catalog or eid in visiting:raise SceneStateError('事件依賴不存在或形成循環。')
        if eid in visited:return
        visiting.add(eid)
        for dep in catalog[eid]['depends_on']:visit(dep)
        visiting.remove(eid);visited.add(eid)
    for eid in catalog:visit(eid)
    total=segments[-1]['start']+segments[-1]['seconds']
    narrative={'completed_events':[],'current_event':None,
               'pending_events':[e for e in catalog if not catalog[e]['reserved_final']],
               'reserved_final_events':[e for e in catalog if catalog[e]['reserved_final']]}
    state=PersistentSceneState(chars,envs,narrative,{'current_clip_index':-1,'current_start_time':0,
           'current_end_time':0,'total_duration':total}).to_dict()
    return state,catalog


def clip_input(ledger,segment):
    index=segment['index'];commits=ledger['commits']
    if index>len(commits):raise SceneStateError('前段狀態尚未提交，不能跳過繼承。')
    if index and digest(commits[index-1]['scene_state_out'])!=commits[index-1]['output_sha256']:
        raise SceneStateError('前段帳本狀態校驗失敗。')
    state=deepcopy(ledger['initial_state'] if index==0 else commits[index-1]['scene_state_out'])
    previous=commits[index-1] if index else {}
    state['narrative_states']['previous_clip_events']=[{'event_id':eid,
        'description':ledger['event_catalog'][eid]['description'],
        'completed_in_previous_clip':eid in previous.get('completed_events',[])}
        for eid in previous.get('planned_events',[])]
    state['narrative_states']['previous_clip_transitions']=deepcopy(previous.get('state_transitions',[]))
    state['timeline'].update(current_clip_index=index,current_start_time=segment['start'],
                             current_end_time=segment['start']+segment['seconds'])
    return state


def plan_clip(raw,state,catalog,segment):
    """Apply typed deltas and return canonical full snapshots; no rendered-video assertions."""
    raw=parse_object(raw)
    timeline=state['timeline']
    if (timeline['current_clip_index']!=segment['index'] or
        abs(timeline['current_start_time']-segment['start'])>1e-6 or
        abs(timeline['current_end_time']-segment['start']-segment['seconds'])>1e-6):
        raise SceneStateError('分段輸入狀態時間軸不符。')
    if not isinstance(raw.get('clip_prompt'),str) or not raw['clip_prompt'].strip():raise SceneStateError('缺少 clip_prompt。')
    planned=string_list(raw.get('planned_events',[]));done=string_list(raw.get('completed_events',[]))
    changes=raw.get('state_transitions',[])
    if not isinstance(changes,list) or len(changes)>128:raise SceneStateError('狀態變更需為清單。')
    out=deepcopy(state);n=out['narrative_states'];previous=set(n['completed_events'])
    is_final=segment['index']==segment['segment_count']-1
    available=set(previous)
    for eid in planned:
        if eid not in catalog:raise SceneStateError('規劃使用未知事件 ID。')
        event=catalog[eid]
        if eid in previous and not event['repeatable']:raise SceneStateError('已完成的一次性事件不得重播。')
        if event['reserved_final'] and not is_final:raise SceneStateError('非最終段不得消耗保留終局事件。')
        if set(event['depends_on'])-available:raise SceneStateError('事件的前置條件尚未完成。')
        if eid in done:available.add(eid)
    if set(done)-set(planned):raise SceneStateError('完成事件必須是本段規劃的事件。')
    for change in changes:
        if not isinstance(change,dict):raise SceneStateError('狀態變更格式錯誤。')
        eid=change.get('event_id');op=change.get('operation')
        if eid not in planned or op not in catalog[eid]['allowed_operations']:
            raise SceneStateError('狀態變更未綁定有權執行的本段事件。')
        kind=change.get('kind')
        if kind=='garment':
            char=out['character_states'].get(text(change.get('subject_id')),{})
            garment=char.get('garments',{}).get(text(change.get('garment_id')))
            if not garment:raise SceneStateError('狀態變更引用未知衣物。')
            before=garment['current_status'];after=change.get('to')
            if change.get('from')!=before:raise SceneStateError('衣物 from 與輸入狀態不符。')
            if after not in GARMENT_EDGES[before]:raise SceneStateError('衣物狀態轉換不合法。')
            if before in ('worn','unfastened','partially_removed') and after!='worn' and op!='remove':
                raise SceneStateError('移除衣物需要 remove 事件授權。')
            if before in ('removed','held','placed') and after!='worn':
                permitted={'held':{'acquire','remove'},'placed':{'drop','move'},'removed':{'drop','remove'}}
                if op not in permitted.get(after,set()):raise SceneStateError('衣物取放操作與狀態不符。')
            if after=='worn' and before!='unfastened' and op!='dress':
                raise SceneStateError('重新穿上必須由明確 dress 事件授權。')
            garment.update(current_status=after,current_location=text(change.get('current_location')))
            sync_outfit(char)
        elif kind in ('character','environment'):
            target=out['character_states'].get(text(change.get('subject_id'))) if kind=='character' else out['environment_states'].get(text(change.get('scene_id')))
            if target is None:raise SceneStateError('狀態變更引用未知角色／場景。')
            field=text(change.get('field'))
            fields=({'hairstyle':text,'appearance_changes':string_list,'injuries':string_list,'held_props':string_list,'location':text}
                    if kind=='character' else {'active_location':text,'persistent_changes':string_list,'damaged_objects':string_map,'prop_positions':string_map})
            if field not in fields:raise SceneStateError('不得改動身分或未知狀態欄位。')
            if target[field]!=change.get('from'):raise SceneStateError('狀態 from 與目前值不符。')
            value=deepcopy(fields[field](change.get('to')))
            if field in ('appearance_changes','injuries','persistent_changes') and set(target[field])-set(value):
                if op not in ('restore','heal'):raise SceneStateError('清除持續變化需明確 restore/heal 事件。')
            if field=='damaged_objects' and any(key not in value or (old!='intact' and value[key]=='intact') for key,old in target[field].items()):
                if op!='restore':raise SceneStateError('復原場景破壞需 restore 事件。')
            target[field]=value
        else:raise SceneStateError('未知狀態變更類型。')
    for eid in done:
        if eid not in n['completed_events']:n['completed_events'].append(eid)
    n['current_event']=next((e for e in reversed(planned) if e not in done),None)
    n['pending_events']=[e for e,v in catalog.items() if e not in n['completed_events'] and not v['reserved_final']]
    n['reserved_final_events']=[e for e,v in catalog.items() if e not in n['completed_events'] and v['reserved_final']]
    if is_final and n['reserved_final_events']:raise SceneStateError('最終段尚未完成保留終局事件。')
    # Reject any model-supplied snapshot which differs; never accept a silent replacement/reset.
    if 'scene_state_out' in raw and raw['scene_state_out']!=out:raise SceneStateError('scene_state_out 與結構化變更不符。')
    if 'pending_events' in raw and raw['pending_events']!=n['pending_events']:raise SceneStateError('pending_events 與事件進度不符。')
    return {'version':VERSION,'clip_index':segment['index'],'visual_verified':False,'status':'planned',
            'scene_state_in':deepcopy(state),'planned_events':planned,'state_transitions':deepcopy(changes),
            'completed_events':done,'pending_events':n['pending_events'], 'scene_state_out':out,
            'input_sha256':digest(state),'output_sha256':digest(out),'clip_prompt':raw['clip_prompt'].strip()}


def state_context(state,catalog,continuation=False):
    return RULES+'\nSTRUCTURED SCENE INPUT (planned, not visually verified):\n'+json.dumps(
        {'scene_state_in':state,'event_catalog':catalog,
         'uploaded_original_to_connected_picture':{str(c['identity_reference']):f'<Picture {c["identity_reference"]+int(continuation)}>'
            for c in state['character_states'].values() if c['identity_reference'] is not None}},ensure_ascii=False)


def save_clip(work,record):
    path=Path(work)/f'{record["clip_index"]:02d}_scene_state.json'
    if path.is_file():
        old=read_json(path)
        if any(old.get(k)!=record.get(k) for k in ('input_sha256','output_sha256','clip_prompt')):
            atomic_json(path.with_name(path.stem+'_history_'+uuid.uuid4().hex[:8]+'.json'),old)
    atomic_json(path,record)


def restore_clip_input(work,index):
    """Recover the exact historical input of a clip, independent of the latest ledger state."""
    record=read_json(Path(work)/f'{index:02d}_scene_state.json')
    if record['input_sha256']!=digest(record['scene_state_in']):raise SceneStateError('分段輸入狀態校驗失敗。')
    return deepcopy(record['scene_state_in'])


def commit_clip(work,ledger,record):
    index=record['clip_index']
    expected=clip_input(ledger,{'index':index,'start':record['scene_state_in']['timeline']['current_start_time'],
                               'seconds':record['scene_state_in']['timeline']['current_end_time']-record['scene_state_in']['timeline']['current_start_time']})
    if digest(expected)!=record['input_sha256'] or digest(record['scene_state_out'])!=record['output_sha256']:
        raise SceneStateError('分段狀態鏈校驗失敗。')
    if index<len(ledger['commits']):
        if digest(ledger['commits'][index]['scene_state_out'])!=ledger['commits'][index]['output_sha256']:
            raise SceneStateError('已提交帳本校驗失敗。')
        if ledger['commits'][index]['output_sha256']!=record['output_sha256']:raise SceneStateError('已提交分段不能直接覆寫；需先回復輸入並使後段失效。')
        return
    if index!=len(ledger['commits']):raise SceneStateError('狀態提交次序錯誤。')
    record['status']='committed';save_clip(work,record)
    ledger['commits'].append({'clip_index':index,'input_sha256':record['input_sha256'],
                              'output_sha256':record['output_sha256'],'scene_state_out':deepcopy(record['scene_state_out']),
                              'planned_events':deepcopy(record['planned_events']),
                              'completed_events':deepcopy(record['completed_events']),
                              'state_transitions':deepcopy(record['state_transitions'])})
    atomic_json(Path(work)/'scene_state.json',ledger)


def ensure_scene_state(cfg,req,segments,originals,work,rewrite):
    work=Path(work);path=work/'scene_state.json'
    fingerprint=digest({'request':req,'timeline':[{k:s[k] for k in ('index','start','seconds')} for s in segments]})
    if path.is_file():
        ledger=read_json(path)
        if ledger.get('version')!=VERSION or ledger.get('input_sha256')!=fingerprint:
            raise SceneStateError('已存跨段狀態與專案設定不符，不能混用。')
        if digest(ledger['initial_state'])!=ledger.get('initial_sha256') or digest(ledger['event_catalog'])!=ledger.get('events_sha256'):
            raise SceneStateError('跨段初始帳本校驗失敗。')
        return ledger
    from PIL import Image,ImageOps
    from banana_mv.story_plan import plan_input
    parts=[('text',plan_input(req,segments)+'\nCurrent event allocation:\n'+json.dumps(
        [s.get('director_plan',{}) for s in segments],ensure_ascii=False))]
    for index,path_image in enumerate(originals,1):
        with Image.open(path_image) as image:
            image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((768,768))
            parts.extend([('text',f'Uploaded original reference {index}:'),('image',image.copy())])
    for attempt in range(2):
        raw=rewrite(cfg,INIT_SYSTEM+'\n'+RULES,parts,uuid.uuid4().hex[:8])
        try:
            state,catalog=initial_state(raw,segments,len(originals));break
        except (SceneStateError,TypeError,KeyError) as error:
            if attempt:raise SceneStateError('9B 初始跨段狀態格式失敗：'+str(error)) from error
            parts.append(('text','Repair only the JSON/state schema: '+str(error)))
    ledger={'version':VERSION,'input_sha256':fingerprint,'visual_verified':False,
            'initial_state':state,'event_catalog':catalog,'initial_sha256':digest(state),
            'events_sha256':digest(catalog),'commits':[]}
    atomic_json(work/'scene_state.json',ledger)
    return ledger


def reconcile_history(job,work,ledger,is_valid):
    """Roll back a broken media prefix; keep source/debug files as history, never silently reset."""
    prefix=0
    for segment in job['segments']:
        index=segment['index']
        if index>=len(ledger['commits']):break
        path=Path(work)/f'{index:02d}_scene_state.json'
        if not path.is_file():raise SceneStateError('已提交分段缺少狀態快照。')
        record=read_json(path)
        if record['input_sha256']!=digest(clip_input(ledger,segment)) or record['output_sha256']!=digest(record['scene_state_out']):
            raise SceneStateError('已提交狀態快照校驗失敗。')
        if digest(ledger['commits'][index]['scene_state_out'])!=ledger['commits'][index]['output_sha256']:
            raise SceneStateError('已提交帳本校驗失敗。')
        if ledger['commits'][index]['output_sha256']!=record['output_sha256']:raise SceneStateError('狀態帳本與快照不符。')
        if segment.get('refresh_prompt') or segment.get('status')!='done' or not is_valid(segment):break
        prefix+=1
    if prefix<len(ledger['commits']):
        atomic_json(Path(work)/('scene_state_history_'+uuid.uuid4().hex[:8]+'.json'),ledger)
        ledger['commits']=ledger['commits'][:prefix]
        atomic_json(Path(work)/'scene_state.json',ledger)
        for segment in job['segments'][prefix:]:
            old_part=Path(work)/f'{segment["index"]:02d}_part.mp4'
            if old_part.is_file():
                old_part.rename(old_part.with_name(old_part.stem+'_history_'+uuid.uuid4().hex[:8]+'.mp4'))
            segment['status']='waiting';segment.pop('prompt_id',None)
            segment['refresh_prompt']=True
    return prefix


def final_context(record):
    """Only this clip's input/delta/output reaches H3; future event descriptions stay with 9B."""
    return RULES+'\nCURRENT CLIP PLANNED STATE (no visual verification):\n'+json.dumps({
        'scene_state_in':{k:v for k,v in record['scene_state_in'].items() if k!='narrative_states'},
        'planned_events':record['planned_events'],'state_transitions':record['state_transitions'],
        'scene_state_out':{k:v for k,v in record['scene_state_out'].items() if k!='narrative_states'}},ensure_ascii=False)


def cached_clip(work,ledger,segment):
    path=Path(work)/f'{segment["index"]:02d}_scene_state.json'
    if not path.is_file() or segment.get('refresh_prompt'):return None
    record=read_json(path)
    if record.get('input_sha256')!=digest(record['scene_state_in']):raise SceneStateError('快取輸入狀態校驗失敗。')
    if record.get('input_sha256')!=digest(clip_input(ledger,segment)):return None
    checked=plan_clip(record,record['scene_state_in'],ledger['event_catalog'],segment)
    if checked['output_sha256']!=record.get('output_sha256'):raise SceneStateError('快取狀態輸出不符。')
    return record
