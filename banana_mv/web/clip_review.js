// Keep video nodes and playback intact across status polls.
const clipView={job:null,rows:new Map(),jobData:null,locked:false,handled:null};
function clipIdle(){return !clipView.locked&&['done','error','cancelled','interrupted'].includes(clipView.jobData?.status);}
function updateClipActions(){
  let count=0;
  for(const row of clipView.rows.values()){
    row.check.disabled=clipView.locked;
    if(row.check.checked)count++;
    row.use.disabled=!clipIdle()||!row.segment.preview||row.select.value===(row.segment.pending_take||row.segment.selected_take);
    row.rewriteButton.disabled=!clipIdle()||!row.segment.director_plan||row.segment.prompt_rewrite?.status==='running';
    const firstRender=row.segment.status!=='done'&&!(row.segment.takes||[]).length;
    const autoResume=firstRender&&['error','cancelled','interrupted'].includes(clipView.jobData?.status);
    row.renderButton.textContent=autoResume?'依此提示詞回爐並自動續跑':'依此提示詞回爐這一段';
    row.renderButton.disabled=!clipIdle()||(!row.segment.preview&&!firstRender)||!row.promptEditor.value.trim();
    row.correction.disabled=clipView.locked||['retaking','assembling','refining_faces'].includes(clipView.jobData?.status);
  }
  const pending=Object.keys(clipView.jobData?.pending_takes||{}).length;
  $('clips-condense').disabled=!clipIdle()||!pending||clipView.jobData?.segments?.some(s=>s.status!=='done');
  $('clips-condense').textContent=pending?`確認凝丹（${pending} 顆待採用）`:'確認凝丹';
  $('clips-all').disabled=clipView.locked||!clipView.rows.size;
  $('clips-clear').disabled=clipView.locked||!count;
  $('clips-retake').disabled=!clipIdle()||!count;
  const hasNotes=[...clipView.rows.values()].some(row=>row.check.checked&&row.correction.value.trim());
  $('clips-retake').textContent=count?(hasNotes?`將所選 ${count} 顆丹藥局部修稿回爐`:`將所選 ${count} 顆丹藥重新分析並回爐`):'將所選丹藥回爐重煉';
}
function showClipVersion(row){
  const take=(row.segment.takes||[]).find(t=>t.id===row.select.value&&t.status==='ready');
  if(take&&row.url!==take.preview){row.url=take.preview;row.video.src=take.preview;}
  const format=take?.preview_kind==='raw'?'RAW 原始有聲預覽':'裁切版（無 RAW 音軌）';
  row.note.textContent=take?`V${take.version||1} · ${format} · ${take.preview_filename||take.filename||''} · Seed：${take.seed}`+(take.correction?` · 局部修改：${take.correction}`:'')+(take.preview_kind==='raw'&&clipView.jobData?.request?.mode==='chain5'?' · 接續模式 RAW 開頭含重疊影格，正式成片已裁切':''):(row.segment.preview?'':'這段尚無毛片，可貼完整新稿，直接初煉這一段。');
  updateClipActions();
}
function renderClipPreviews(job){
  if(clipView.job!==job.id){clipView.job=job.id;clipView.rows.clear();clipView.handled=null;$('clip-list').replaceChildren();}
  clipView.jobData=job;
  $('clip-chain-note').hidden=!['chain','chain5'].includes(job.request?.mode);
  for(let i=0;i<(job.segments||[]).length;i++){
    const segment=job.segments[i];if(!segment.preview&&!segment.director_plan&&!segment.prompt)continue;
    let row=clipView.rows.get(i);
    if(!row){
      const card=document.createElement('article');card.className='dan-card';
      const label=document.createElement('label'),check=document.createElement('input'),title=document.createElement('span');
      check.type='checkbox';label.append(check,title);
      const video=document.createElement('video');video.controls=true;video.muted=false;video.preload='none';video.playsInline=true;
      const version=document.createElement('div');version.className='dan-version';
      const select=document.createElement('select');select.setAttribute('aria-label',`第 ${i+1} 顆丹藥的版本`);
      const use=document.createElement('button');use.type='button';use.className='secondary';use.textContent='選用此丹';
      const note=document.createElement('p');note.className='muted';version.append(select,use);card.append(label,video,version,note);$('clip-list').append(card);
      const fixLabel=document.createElement('label');fixLabel.textContent='局部修改建議（選填）';
      const correction=document.createElement('textarea');correction.rows=3;correction.maxLength=3000;
      correction.setAttribute('aria-label',`第 ${i+1} 顆丹藥的局部修改建議`);
      correction.placeholder='例如：表情更憤怒；增加手部操作特寫；保留事件，只改這段拍法。';
      const help=document.createElement('p');help.className='muted';help.textContent='以已選用的待採用版修改；未選則用目前成片版。留空只換 Seed。填寫後勾選此段，9B 只修這段原稿。';
      try{correction.value=JSON.parse(localStorage.getItem('banana_mv_clip_fixes:'+job.id)||'{}')[i]||'';}catch{}
      correction.oninput=()=>{try{const key='banana_mv_clip_fixes:'+job.id;const saved=JSON.parse(localStorage.getItem(key)||'{}');saved[i]=correction.value;localStorage.setItem(key,JSON.stringify(saved));}catch{}};
      fixLabel.append(correction);card.append(fixLabel,help);
      const formula=document.createElement('div');formula.className='dan-prompt-workbench';
      const promptLabel=document.createElement('label');promptLabel.textContent='這段丹方／生成提示詞（可直接修改或貼上）';
      const promptEditor=document.createElement('textarea');promptEditor.rows=12;promptEditor.maxLength=50000;
      promptEditor.setAttribute('aria-label',`第 ${i+1} 段的可編輯 H3 提示詞`);
      promptEditor.placeholder='原本的 H3 六段式提示詞，或自行貼入完整新稿。';
      const promptInfo=document.createElement('p');promptInfo.className='muted';promptInfo.textContent='只改提示詞不會自動生成；確認後再按本段回爐。';
      const buttons=document.createElement('div');buttons.className='dan-toolbar';
      const rewriteButton=document.createElement('button');rewriteButton.type='button';rewriteButton.className='secondary';rewriteButton.textContent='重配丹方（9B 重寫）';
      const renderButton=document.createElement('button');renderButton.type='button';renderButton.textContent='依此提示詞回爐這一段';
      buttons.append(rewriteButton,renderButton);promptLabel.append(promptEditor);
      formula.append(promptLabel,promptInfo,buttons);card.append(formula);
      row={card,check,title,video,select,use,note,correction,segment,index:i,
        promptEditor,promptInfo,rewriteButton,renderButton,loadedVersion:null,editorLoaded:false};clipView.rows.set(i,row);
      check.onchange=updateClipActions;select.onchange=()=>showClipVersion(row);
      use.onclick=()=>adoptClip(row.index,row.select.value);
      promptEditor.oninput=updateClipActions;
      rewriteButton.onclick=()=>runClipAction('api/mv/rewrite-clip',{index:i});
      renderButton.onclick=()=>{
        const text=promptEditor.value.trim();
        if(!text){promptInfo.textContent='請先填寫或貼上本段完整 H3 提示詞。';return;}
        const firstRender=row.segment.status!=='done'&&!(row.segment.takes||[]).length;
        const autoResume=firstRender&&['error','cancelled','interrupted'].includes(clipView.jobData?.status);
        return runClipAction('api/mv/retake',{indices:[i],prompts:{[String(i)]:text},
          ...(autoResume?{auto_resume:true}:{})});
      };
    }
    const desired=segment.pending_take||segment.selected_take||'original';const changed=(row.segment.pending_take||row.segment.selected_take)!==desired;row.segment=segment;
    row.title.textContent=`第 ${i+1} 段 · ${segment.start.toFixed(2)}–${(segment.start+segment.seconds).toFixed(2)} 秒｜${segment.status==='done'?'已生成':'等待生成'}`;
    row.video.hidden=!segment.preview;
    const draft=segment.prompt_rewrite||{};
    if(draft.status==='ready'&&typeof draft.text==='string'&&draft.version!==row.loadedVersion){
      row.promptEditor.value=draft.text;row.loadedVersion=draft.version;row.editorLoaded=true;
    }else if(!row.editorLoaded){
      row.promptEditor.value=draft.text||segment.prompt||'';row.loadedVersion=draft.version||null;row.editorLoaded=true;
    }
    row.promptInfo.textContent=draft.status==='running'?'9B 正在重配這一段丹方；目前文字與舊影片仍保留。':
      draft.status==='ready'?`9B 新丹方 V${draft.version} 已完成；可手動修改，再按「依此提示詞回爐」。`:
      draft.status==='error'?`9B 重配失敗：${draft.error}。可直接貼稿，不影響舊片。`:
      '可用 9B 重寫，或直接貼入你自己的 H3 提示詞；按回爐才會生新片。';
    const ready=(segment.takes||[]).filter(t=>t.status==='ready');
    const signature=ready.map(t=>t.id+':'+(t.id===segment.selected_take)+':'+(t.id===desired)).join('|');
    if(row.signature!==signature){
      const previous=row.select.value;row.select.replaceChildren();
      for(const [n,take] of ready.entries()){
        const option=document.createElement('option');option.value=take.id;
        option.textContent=`V${take.version||(n+1)}${take.id==='original'?' · 初煉':take.kind==='face_refine'?' · 修臉':' · 回爐'}`+(take.id===segment.selected_take?' · 目前成片':'')+(take.id===desired&&desired!==segment.selected_take?' · 待凝丹':'');row.select.append(option);
      }
      row.select.value=changed||!ready.some(t=>t.id===previous)?desired:previous;row.signature=signature;
    }
    showClipVersion(row);
  }
  $('clip-review').hidden=!clipView.rows.size;
  const batch=job.retake,stamp=batch&&JSON.stringify([job.resumed,batch.takes,batch.indices,batch.status]);
  if(batch?.status==='done'&&clipView.handled!==stamp){for(const i of batch.indices||[])if(clipView.rows.has(i))clipView.rows.get(i).check.checked=false;clipView.handled=stamp;}
  if(batch?.status==='error'&&clipView.handled!==stamp){
    for(const [i,id] of Object.entries(batch.takes||{})){const row=clipView.rows.get(Number(i));if(row?.segment.takes.some(t=>t.id===id&&t.status==='ready'))row.check.checked=false;}
    clipView.handled=stamp;
  }
  $('clip-review-status').textContent=batch?.status==='error'?`回爐未完成：${batch.error} 原版保留；已完成新版可在版本選單預覽、選用；確認凝丹才更新成片。`:
    batch?.status==='cancelled'?'緊急停爐成功：目前未完成的候選已取消；舊片、先前完成的段落和候選都保留。可改丹方再回爐。':
    batch?.status==='done'&&batch.auto_resume?(job.status==='running'?
      '這段重配成功，已自動接著生成後續片段。':
      job.status==='done'?'回爐並續跑完成，完整 MV 已出爐。':
      batch.auto_resume_error?'這段成功，但續跑交接失敗：'+batch.auto_resume_error:
      '這段重配完成；可繼續檢查後續進度。'):
    batch?.status==='done'?(batch.operation==='condense'?'凝丹完成，已另存完整新版。':'回爐完成，請逐顆預覽、選用，再確認凝丹。'):job.status==='retaking'?`回爐中：已完成 ${batch?.completed||0}／${batch?.indices?.length||0} 顆；完成後只存候選，不自動合成。`:
    job.status==='assembling'?'正在重新合成所選丹藥…':clipIdle()?'勾選需要重煉的丹藥，或選擇版本預覽與選用，再確認凝丹。':'可先預覽；請待這爐完成或停止後再回爐。';
  updateClipActions();
}
async function runClipAction(path,body){
  clipView.locked=true;updateClipActions();busy(true);
  try{
    const job=await api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:active,...body})});
    renderClipPreviews(job);clearTimeout(timer);await poll();
  }catch(error){$('clip-review-status').textContent=error.message;busy(false);}
  finally{clipView.locked=false;updateClipActions();}
}
async function adoptClip(index,take){return runClipAction('api/mv/select-take',{index,take});}
$('clips-condense').onclick=()=>{if(clipIdle())return runClipAction('api/mv/condense',{revision:clipView.jobData.selection_revision});};
$('clips-all').onclick=()=>{if(clipView.locked)return;for(const row of clipView.rows.values())row.check.checked=true;updateClipActions();};
$('clips-clear').onclick=()=>{if(clipView.locked)return;for(const row of clipView.rows.values())row.check.checked=false;updateClipActions();};
$('clips-retake').onclick=()=>{
  if(!clipIdle())return;
  const indices=[...clipView.rows].filter(([,row])=>row.check.checked).map(([i])=>i);
  const instructions=Object.fromEntries(indices.map(i=>[String(i),clipView.rows.get(i).correction.value.trim()]).filter(([,text])=>text));
  const fresh=!Object.keys(instructions).length&&[5,6].includes(clipView.jobData?.request?.director_schema)&&!!clipView.jobData?.request?.rewrite;
  if(indices.length)return runClipAction('api/mv/retake',{indices,...(Object.keys(instructions).length?{instructions}:{}),...(fresh?{rebuild_prompt:true}:{})});
};
if(active){busy(true);poll();}
