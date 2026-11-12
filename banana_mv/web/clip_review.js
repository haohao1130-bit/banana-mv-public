// Keep video nodes and playback intact across status polls.
const clipView={job:null,rows:new Map(),jobData:null,locked:false,handled:null};
function clipIdle(){return !clipView.locked&&['done','error','cancelled','interrupted'].includes(clipView.jobData?.status);}
function updateClipActions(){
  let count=0;
  for(const row of clipView.rows.values()){
    row.check.disabled=clipView.locked;
    if(row.check.checked)count++;
    row.use.disabled=!clipIdle()||row.select.value===(row.segment.pending_take||row.segment.selected_take);
    row.correction.disabled=clipView.locked||['retaking','assembling'].includes(clipView.jobData?.status);
  }
  const pending=Object.keys(clipView.jobData?.pending_takes||{}).length;
  $('clips-condense').disabled=!clipIdle()||!pending||clipView.jobData?.segments?.some(s=>s.status!=='done');
  $('clips-condense').textContent=pending?`確認凝丹（${pending} 顆待採用）`:'確認凝丹';
  $('clips-all').disabled=clipView.locked||!clipView.rows.size;
  $('clips-clear').disabled=clipView.locked||!count;
  $('clips-retake').disabled=!clipIdle()||!count;
  $('clips-retake').textContent=count?`將所選 ${count} 顆丹藥回爐重煉`:'將所選丹藥回爐重煉';
}
function showClipVersion(row){
  const take=row.segment.takes.find(t=>t.id===row.select.value&&t.status==='ready');
  if(take&&row.url!==take.preview){row.url=take.preview;row.video.src=take.preview;}
  row.note.textContent=take?`V${take.version||1} · ${take.filename||''} · Seed：${take.seed}`+(take.correction?` · 局部修改：${take.correction}`:''):'';
  updateClipActions();
}
function renderClipPreviews(job){
  if(clipView.job!==job.id){clipView.job=job.id;clipView.rows.clear();clipView.handled=null;$('clip-list').replaceChildren();}
  clipView.jobData=job;
  $('clip-chain-note').hidden=!['chain','chain5'].includes(job.request?.mode);
  for(let i=0;i<(job.segments||[]).length;i++){
    const segment=job.segments[i];if(!segment.preview)continue;
    let row=clipView.rows.get(i);
    if(!row){
      const card=document.createElement('article');card.className='dan-card';
      const label=document.createElement('label'),check=document.createElement('input'),title=document.createElement('span');
      check.type='checkbox';label.append(check,title);
      const video=document.createElement('video');video.controls=true;video.muted=true;video.preload='none';video.playsInline=true;
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
      row={card,check,title,video,select,use,note,correction,segment,index:i};clipView.rows.set(i,row);
      check.onchange=updateClipActions;select.onchange=()=>showClipVersion(row);
      use.onclick=()=>adoptClip(row.index,row.select.value);
    }
    const desired=segment.pending_take||segment.selected_take;const changed=(row.segment.pending_take||row.segment.selected_take)!==desired;row.segment=segment;
    row.title.textContent=`第 ${i+1} 顆 · ${segment.start.toFixed(2)}–${(segment.start+segment.seconds).toFixed(2)} 秒｜此丹有異，建議回爐`;
    const ready=segment.takes.filter(t=>t.status==='ready');
    const signature=ready.map(t=>t.id+':'+(t.id===segment.selected_take)+':'+(t.id===desired)).join('|');
    if(row.signature!==signature){
      const previous=row.select.value;row.select.replaceChildren();
      for(const [n,take] of ready.entries()){
        const option=document.createElement('option');option.value=take.id;
        option.textContent=`V${take.version||(n+1)}${take.id==='original'?' · 初煉':' · 回爐'}`+(take.id===segment.selected_take?' · 目前成片':'')+(take.id===desired&&desired!==segment.selected_take?' · 待凝丹':'');row.select.append(option);
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
  if(indices.length)return runClipAction('api/mv/retake',{indices,...(Object.keys(instructions).length?{instructions}:{})});
};
if(active){busy(true);poll();}
