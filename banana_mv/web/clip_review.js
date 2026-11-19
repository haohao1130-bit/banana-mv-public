// Keep video nodes and playback intact across status polls.
const clipView={job:null,rows:new Map(),jobData:null,locked:false,handled:null};
function clipIdle(){return !clipView.locked&&['done','error','cancelled','interrupted'].includes(clipView.jobData?.status);}
function continuous5070(job=clipView.jobData){
  return job?.request?.director_schema===6&&['chain','chain5'].includes(job?.request?.mode);
}
function obsoleteSuccessor(index){
  const restart=clipView.jobData?.continuation_restart;
  return continuous5070()&&!!restart&&index>restart.index;
}
function previousTakeForClip(index){
  if(index===0||!['chain','chain5'].includes(clipView.jobData?.request?.mode))return null;
  const prior=clipView.rows.get(index-1);
  const saved=clipView.jobData?.segments?.[index-1];
  // 5070 continuity follows the OFFICIAL version, never a merely
  // previewed dropdown candidate from the previous clip.
  if(continuous5070())return saved?.selected_take||'original';
  return prior?.select.value||saved?.pending_take||saved?.selected_take||'original';
}
function updateClipActions(){
  const continuous=continuous5070();
  let count=0;
  $('clip-legacy-toolbar').hidden=continuous;
  $('clip-review-help').textContent=continuous
    ?'5070 連續拍攝：緊急停爐後逐段重配 9B 丹方、回爐新版、按「選用此丹」，再從該段尾幀重拍後續。舊後段影片只能預覽備份，不可混入新時間線。'
    :'每段可重配 9B 丹方或貼完整 H3 提示詞回爐。獨立與舊模式可批次選丹、確認凝丹。';
  $('clip-chain-note').textContent=continuous
    ?'同一條時間線：選用新版後，必須從下一段重寫 9B 並接拍；不支援只換一段保留後續。'
    :'末幀接續：若保留舊後續，請檢查相鄰畫面是否一致。';
  for(const row of clipView.rows.values()){
    const obsolete=obsoleteSuccessor(row.index);
    row.checkLabel.hidden=continuous;
    row.correctionLabel.hidden=continuous;
    row.branchHint.hidden=!continuous||obsolete;
    row.check.disabled=continuous||clipView.locked;
    if(row.check.checked&&!continuous)count++;
    const official=continuous?row.segment.selected_take:
      (row.segment.pending_take||row.segment.selected_take);
    row.use.textContent=continuous?'正式採用此版本':'選用此丹';
    row.use.disabled=!clipIdle()||obsolete||!row.segment.preview||row.select.value===official;
    const differentTake=row.select.value&&row.select.value!==row.segment.selected_take;
    const restart=clipView.jobData?.continuation_restart;
    const adoptedRestart=restart?.index===row.index&&restart.take===row.select.value;
    const branchChoice=!!differentTake||adoptedRestart;
    const chain=['chain','chain5'].includes(clipView.jobData?.request?.mode);
    const hasNext=row.index+1<(clipView.jobData?.segments?.length||0);
    row.branchOnly.hidden=continuous||!branchChoice;
    row.branchOnly.disabled=continuous||!clipIdle()||!branchChoice;
    const selectedReady=(row.segment.takes||[]).some(t=>
      t.id===row.select.value&&t.status==='ready');
    const adopted=row.select.value===row.segment.selected_take
      &&selectedReady&&row.segment.status==='done';
    // 5070 asks for an explicit adoption. One official tail defines
    // the entire new lineage; an unadopted dropdown is only a preview.
    const cascadeReady=continuous
      ?adopted&&(row.select.value!=='original'||adoptedRestart)
      :branchChoice||adopted&&row.select.value!=='original';
    row.branchCascade.hidden=!cascadeReady||obsolete||!chain||(!continuous&&!hasNext);
    row.branchCascade.disabled=!clipIdle()||!cascadeReady||obsolete||!chain||(!continuous&&!hasNext);
    row.branchCascade.textContent=continuous
      ?(hasNext?`從本段尾幀續拍第 ${row.index+2} 段（9B 重寫）`:'合成正式新版全片')
      :'從新版尾幀重拍後續（9B 重寫）';
    row.rewriteButton.disabled=!clipIdle()||obsolete||!row.segment.director_plan
      ||row.segment.prompt_rewrite?.status==='running';
    const firstRender=row.segment.status!=='done'&&!(row.segment.takes||[]).length;
    const autoResume=firstRender&&['error','cancelled','interrupted'].includes(clipView.jobData?.status);
    row.renderButton.textContent=autoResume?'依此提示詞回爐並自動續跑':'依此提示詞回爐這一段';
    row.renderButton.disabled=!clipIdle()||obsolete
      ||(!row.segment.preview&&!firstRender)||!row.promptEditor.value.trim();
    row.correction.disabled=continuous||clipView.locked
      ||['retaking','assembling','refining_faces'].includes(clipView.jobData?.status);
  }
  const pending=Object.keys(clipView.jobData?.pending_takes||{}).length;
  $('clips-condense').disabled=continuous||!clipIdle()||!pending
    ||clipView.jobData?.segments?.some(s=>s.status!=='done');
  $('clips-condense').textContent=pending?`確認凝丹（${pending} 顆待採用）`:'確認凝丹';
  $('clips-all').disabled=continuous||clipView.locked||!clipView.rows.size;
  $('clips-clear').disabled=continuous||clipView.locked||!count;
  $('clips-retake').disabled=continuous||!clipIdle()||!count;
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
      const branchBar=document.createElement('div');branchBar.className='dan-toolbar';
      const branchOnly=document.createElement('button');branchOnly.type='button';branchOnly.className='secondary';branchOnly.textContent='僅改這段，保留後續';
      const branchCascade=document.createElement('button');branchCascade.type='button';branchCascade.textContent='從新版尾幀重拍後續（9B 重寫）';
      const note=document.createElement('p');note.className='muted';
      const branchHint=document.createElement('p');branchHint.className='muted';branchHint.textContent='回爐本段→正式採用→從本段尾幀重寫 9B 並續拍；後續舊版不參與新成片。';
      branchBar.append(branchOnly,branchCascade);
      version.append(select,use);card.append(label,video,version,branchBar,branchHint,note);$('clip-list').append(card);
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
      row={card,check,checkLabel:label,correctionLabel:fixLabel,branchHint,title,video,select,use,note,correction,segment,index:i,
        promptEditor,promptInfo,rewriteButton,renderButton,branchOnly,branchCascade,loadedVersion:null,editorLoaded:false};clipView.rows.set(i,row);
      check.onchange=updateClipActions;select.onchange=()=>showClipVersion(row);
      use.onclick=()=>adoptClip(row.index,row.select.value);
      branchOnly.onclick=()=>runClipAction('api/mv/continue-branch',{index:i,take:row.select.value,mode:'only'});
      branchCascade.onclick=()=>runClipAction('api/mv/continue-branch',{index:i,take:row.select.value,mode:'cascade'});
      promptEditor.oninput=()=>{row.userEdited=true;updateClipActions();};
      rewriteButton.onclick=()=>{
        const previous=previousTakeForClip(i);
        return runClipAction('api/mv/rewrite-clip',{index:i,...(previous?{previous_take:previous}:{})});
      };
      renderButton.onclick=()=>{
        const text=promptEditor.value.trim();
        if(!text){promptInfo.textContent='請先填寫或貼上本段完整 H3 提示詞。';return;}
        const firstRender=row.segment.status!=='done'&&!(row.segment.takes||[]).length;
        const autoResume=firstRender&&['error','cancelled','interrupted'].includes(clipView.jobData?.status);
        const previous=previousTakeForClip(i);
        const draft=row.segment.prompt_rewrite||{};
        if(previous&&draft.status==='ready'&&draft.previous_take&&draft.previous_take!==previous){
          promptInfo.textContent='上一段版本已變更；請重新按「重配丹方」，避免丹方首幀與影片首幀不一致。';return;
        }
        return runClipAction('api/mv/retake',{indices:[i],prompts:{[String(i)]:text},
          ...(previous?{previous_takes:{[String(i)]:previous}}:{}),
          ...(autoResume?{auto_resume:true}:{})});
      };
    }
    const desired=segment.pending_take||segment.selected_take||'original';const changed=(row.segment.pending_take||row.segment.selected_take)!==desired;
    if(continuous5070(job)&&row.segment.selected_take!==segment.selected_take){
      row.editorLoaded=false;row.loadedVersion=null;
    }
    row.segment=segment;
    const obsolete=continuous5070(job)&&job.continuation_restart&&i>job.continuation_restart.index;
    row.title.textContent=`第 ${i+1} 段 · ${segment.start.toFixed(2)}–${(segment.start+segment.seconds).toFixed(2)} 秒｜${obsolete?'舊時間線・待重新接拍':segment.status==='done'?'已生成':'等待生成'}`;
    row.video.hidden=!segment.preview;
    const draft=segment.prompt_rewrite||{};
    if(draft.status==='ready'&&typeof draft.text==='string'&&draft.version!==row.loadedVersion){
      row.promptEditor.value=draft.text;row.loadedVersion=draft.version;row.editorLoaded=true;
      row.lastSeenPrompt=segment.prompt;row.userEdited=false;
    }else if(!row.editorLoaded||(!row.userEdited&&segment.prompt&&row.lastSeenPrompt!==segment.prompt)){
      // The card may appear at 'preparing' before 9B submits its H3 prompt.
      // Refresh once it exists, without overwriting the user's live edits.
      row.promptEditor.value=draft.text||segment.prompt||'';
      row.loadedVersion=draft.version||null;row.editorLoaded=true;
      row.lastSeenPrompt=segment.prompt;row.userEdited=false;
    }
    row.promptInfo.textContent=obsolete?'這是舊時間線丹方／影片，僅供查看。請先從正式採用新版尾幀續拍。':
      draft.status==='running'?'9B 正在重配這一段丹方；目前文字與舊影片仍保留。':
      draft.status==='ready'?`9B 新丹方 V${draft.version} 已完成${draft.previous_take?' · 上段來源 Take：'+draft.previous_take:''}；可手動修改，再按「依此提示詞回爐」。`:
      draft.status==='error'?`9B 重配失敗：${draft.error}。可直接貼稿，不影響舊片。`:
      '可用 9B 重寫，或直接貼入你自己的 H3 提示詞；按回爐才會生新片。';
    const ready=(segment.takes||[]).filter(t=>t.status==='ready');
    const signature=ready.map(t=>t.id+':'+(t.id===segment.selected_take)+':'+(t.id===desired)).join('|');
    if(row.signature!==signature){
      const previous=row.select.value;row.select.replaceChildren();
      for(const [n,take] of ready.entries()){
        const option=document.createElement('option');option.value=take.id;
        option.textContent=`V${take.version||(n+1)}${take.id==='original'?' · 初煉':take.kind==='face_refine'?' · 修臉':' · 回爐'}`+(take.id===segment.selected_take?(continuous5070(job)?' · 正式採用':' · 目前成片'):'')+(!continuous5070(job)&&take.id===desired&&desired!==segment.selected_take?' · 待凝丹':'');row.select.append(option);
      }
      row.select.value=changed||!ready.some(t=>t.id===previous)?desired:previous;row.signature=signature;
    }
    showClipVersion(row);
  }
  $('clip-review').hidden=!clipView.rows.size;
  const batch=job.retake,stamp=batch&&JSON.stringify([job.resumed,batch.takes,batch.indices,batch.status]);
  if(batch?.status==='done'&&clipView.handled!==stamp){
    for(const i of batch.indices||[]){
      const row=clipView.rows.get(i);
      if(!row)continue;
      row.check.checked=false;
      const latest=(row.segment.takes||[]).find(t=>t.id===batch?.takes?.[String(i)]&&t.status==='ready');
      if(latest){row.select.value=latest.id;showClipVersion(row);}
    }
    clipView.handled=stamp;
  }
  if(batch?.status==='error'&&clipView.handled!==stamp){
    for(const [i,id] of Object.entries(batch.takes||{})){const row=clipView.rows.get(Number(i));if(row?.segment.takes.some(t=>t.id===id&&t.status==='ready'))row.check.checked=false;}
    clipView.handled=stamp;
  }
  const restart=job.continuation_restart;
  const continuous=continuous5070(job);
  const adoptedSource=[...clipView.rows.values()].find(row=>
    row.select.value===row.segment.selected_take
    &&row.select.value!=='original'&&row.segment.status==='done'
    &&['chain','chain5'].includes(job.request?.mode)
    &&row.index+1<job.segments.length);
  $('clip-review-status').textContent=continuous&&restart&&clipIdle()?
    `第 ${restart.index+1} 段新版已正式採用；後面全部是舊時間線。按本段「從本段尾幀續拍第 ${restart.from_index+1} 段」，9B 會重新寫下一段丹方。`:
    restart&&clipIdle()?
    `已正式採用第 ${restart.index+1} 段新版；按本段「從新版尾幀重拍後續」，或上方「繼續跑」，就會從第 ${restart.from_index+1} 段重新寫 9B 丹方並續拍。`:
    adoptedSource&&clipIdle()&&['error','cancelled','interrupted'].includes(job.status)?
    `第 ${adoptedSource.index+1} 段已選用正式新版；按本段「從新版尾幀重拍後續」，從第 ${adoptedSource.index+2} 段重新交給 9B 寫咒接拍。`:
    batch?.branch&&batch.status==='running'?(batch.branch.mode==='cascade'?'新版尾幀分支：後續重新拍攝與 9B 當段重寫中。':'單段替換分支：保留現有後續。'):
    batch?.branch&&batch.status==='done'?(job.status==='running'?'新版已採用，正在接著生成未完成段落。':'分支續跑完成；原版影片仍在版本紀錄中。'):
    batch?.status==='error'?`回爐未完成：${batch.error} 原版保留；可從版本選單挑選已完成新版。`+(continuous?' 採用後由新版尾幀續拍。':' 確認凝丹後更新成片。'):
    batch?.status==='cancelled'?'緊急停爐成功：目前未完成的候選已取消；舊片、先前完成的段落和候選都保留。可改丹方再回爐。':
    batch?.status==='done'&&batch.auto_resume?(job.status==='running'?
      '這段重配成功，已自動接著生成後續片段。':
      job.status==='done'?'回爐並續跑完成，完整 MV 已出爐。':
      batch.auto_resume_error?'這段成功，但續跑交接失敗：'+batch.auto_resume_error:
      '這段重配完成；可繼續檢查後續進度。'):
    batch?.status==='done'?(batch.operation==='condense'?'凝丹完成，已另存完整新版。':continuous?'本段回爐完成，請預覽新版、正式採用，再從新版尾幀接拍後續。':'回爐完成，請逐顆預覽、選用，再確認凝丹。'):job.status==='retaking'?`回爐中：已完成 ${batch?.completed||0}／${batch?.indices?.length||0} 顆；完成後只存候選，不自動合成。`:
    job.status==='assembling'?'正在重新合成所選丹藥…':clipIdle()?(continuous?'逐段重配丹方、回爐新版、正式採用，再從新版尾幀接拍。':'勾選需要重煉的丹藥，或選擇版本預覽與選用，再確認凝丹。'):'可先預覽；請待這爐完成或停止後再回爐。';
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
$('clips-condense').onclick=()=>{if(clipIdle()&&!continuous5070())return runClipAction('api/mv/condense',{revision:clipView.jobData.selection_revision});};
$('clips-all').onclick=()=>{if(clipView.locked)return;for(const row of clipView.rows.values())row.check.checked=true;updateClipActions();};
$('clips-clear').onclick=()=>{if(clipView.locked)return;for(const row of clipView.rows.values())row.check.checked=false;updateClipActions();};
$('clips-retake').onclick=()=>{
  if(!clipIdle()||continuous5070())return;
  const indices=[...clipView.rows].filter(([,row])=>row.check.checked).map(([i])=>i);
  const instructions=Object.fromEntries(indices.map(i=>[String(i),clipView.rows.get(i).correction.value.trim()]).filter(([,text])=>text));
  const fresh=!Object.keys(instructions).length&&[5,6].includes(clipView.jobData?.request?.director_schema)&&!!clipView.jobData?.request?.rewrite;
  if(indices.length){
    const parents=Object.fromEntries(indices.filter(i=>i>0&&!indices.includes(i-1))
      .map(i=>[String(i),previousTakeForClip(i)]).filter(([,take])=>take));
    return runClipAction('api/mv/retake',{indices,...(Object.keys(instructions).length?{instructions}:{}),
      ...(Object.keys(parents).length?{previous_takes:parents}:{}),
      ...(fresh?{rebuild_prompt:true}:{})});
  }
};
// Only resume an open page within the same server instance; restarts show a clean furnace.
void restoreActiveProjectOnSameServer();
