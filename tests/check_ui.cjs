// Exercise the real frontend script with a tiny DOM and mocked HTTP; no npm packages.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('banana_mv/web/index.html','utf8');
class Element{
  constructor(){this.children=[];this.value='';this.files=[];this.checked=false;this.style={};this.events={};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(key,value){this[key]=value;}
  addEventListener(name,fn){this.events[name]=fn;}
  focus(){this.focused=true;}
  showModal(){this.open=true;}
  close(){this.open=false;this.events.close?.();}
  getBoundingClientRect(){return {left:20,right:680,top:20,bottom:800};}
  select(){this.selected=true;}
}
const els=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
Object.assign(els.mode,{value:'independent'});els.aspect.value='16:9';els.width.value='1280';els.segment.value='10';els.director.value='performance';els.intensity.value='high';els.face_identity.checked=true;els.audio_analysis.checked=true;els.story_plan.checked=true;els.kitchen_attention.checked=true;els.motion_lora.checked=true;
const posts=[],uploads=[],resumes=[],copied=[];
const context=vm.createContext({document:{getElementById:id=>{assert(els[id],`Missing DOM element ${id}`);return els[id];},createElement:()=>new Element()},
  URL:{createObjectURL:file=>'blob:'+file.name,revokeObjectURL:()=>{}},localStorage:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}},
  setTimeout:()=>0,clearTimeout:()=>{},console,navigator:{clipboard:{writeText:async text=>{copied.push(text);}}},
  fetch:async(url,options)=>({ok:true,status:200,json:async()=>{
    if(url==='api/upload'){uploads.push(options.body.name);return {id:options.body.name};}
    if(url==='api/mv/start'){posts.push(JSON.parse(options.body));return {id:'abcd'};}
    if(url==='api/mv/projects')return [{id:'saved123',title:'雲端歌曲',completed:1,total:2,status:'interrupted'}];
    if(url==='api/mv/resume'){resumes.push(JSON.parse(options.body));return {id:'saved123'};}
    if(url==='api/mv/status?id=saved123')return {id:'saved123',title:'雲端歌曲',duration:180,seed:0,status:'interrupted',request:{mode:'independent',aspect:'9:16',segment_seconds:15,prompt:'saved story',face_identity:false},segments:[{start:0,seconds:15,status:'done'},{start:15,seconds:15}]};
    if(url==='api/mv/status?id=broken-plan')return {status:'error',error:'plan parse failed',error_stage:'planning_story',request:{director_version:2},segments:[{index:0,start:0,seconds:10,director_plan:{mode:'story',event:'x'.repeat(800)}}]};
    if(url==='status-error')return {status:'error',error:'bad media tag',segments:[]};
    return {status:'done',seed:42,segments:[]};
  }})});
vm.runInContext(html.split('<script>')[1].split('</script>')[0],context);
const file=name=>({name,size:100,lastModified:1});
async function submit(){uploads.length=0;await els.form.onsubmit({preventDefault(){}});await vm.runInContext('poll()',context);return posts.at(-1);}
(async()=>{
  const originalPrompt=els.prompt.value;
  assert(!els['help-dialog'].open);els['open-help'].onclick();assert.equal(els['help-dialog'].open,true);
  els['help-dialog'].scrollTop=42;els['open-help'].onclick();assert.equal(els['help-dialog'].scrollTop,42);
  els['help-dialog'].events.click({target:els['help-dialog'],clientX:100,clientY:100});assert.equal(els['help-dialog'].open,true);
  els['help-dialog'].events.click({target:els['close-help'],clientX:0,clientY:0});assert.equal(els['help-dialog'].open,true);
  els['help-dialog'].events.click({target:els['help-dialog'],clientX:0,clientY:0});assert.equal(els['help-dialog'].open,false);assert(els['open-help'].focused);
  els['open-help'].onclick();assert.equal(els['help-dialog'].scrollTop,0);els['close-help'].onclick();assert.equal(els['help-dialog'].open,false);
  assert.equal(els.prompt.value,originalPrompt);assert.equal(posts.length,0);

  for(const [job,state] of [
    [{status:'analyzing_audio'},'planning'],[{status:'planning_story'},'planning'],
    [{status:'running',segments:[{status:'rewriting'}]},'planning'],
    [{status:'running',segments:[{status:'generating'}]},'working'],
    [{status:'assembling'},'assembling'],[{status:'done'},'done'],
    [{status:'error'},'error'],[{status:'cancelled'},'paused'],[{status:'interrupted'},'paused']
  ]){vm.runInContext(`renderFurnace(${JSON.stringify(job)})`,context);assert.equal(els.furnace['data-state'],state);}
  vm.runInContext("setFurnace('reconnecting','正在重新連線；不代表生成停止。')",context);
  assert.equal(els.furnace['data-state'],'reconnecting');assert(els['furnace-detail'].textContent.includes('不代表生成停止'));
  vm.runInContext("setFurnace('idle')",context);assert.equal(els['furnace-title'].textContent,'爐火待命');

  vm.runInContext("renderPrompts({id:'inspect',segments:[{prompt:'first\\nline'},{prompt:'second'}]})",context);assert.equal(els['rewritten-prompt'].value,'second');assert.equal(els['prompt-segment'].value,'1');assert.equal(els['copy-prompt'].disabled,false);
  els['prompt-segment'].value='0';els['prompt-segment'].onchange();assert.equal(els['rewritten-prompt'].value,'first\nline');await els['copy-prompt'].onclick();assert.equal(copied.at(-1),'first\nline');assert(els['copy-feedback'].textContent.includes('已複製'));
  vm.runInContext("renderPrompts({id:'inspect',segments:[{prompt:'first\\nline'},{prompt:'second'},{prompt:'third'}]})",context);assert.equal(els['prompt-segment'].value,'0');assert.equal(els['rewritten-prompt'].value,'first\nline');
  vm.runInContext("renderPrompts({id:'fresh',segments:[{}]})",context);assert.equal(els['rewritten-prompt'].value,'');assert.equal(els['copy-prompt'].disabled,true);assert(els['prompt-note'].textContent.includes('尚未完成'));
  vm.runInContext("renderPrompts({id:'fallback',segments:[{prompt:'manual copy'}]});navigator.clipboard=null",context);await els['copy-prompt'].onclick();assert.equal(els['rewritten-prompt'].selected,true);assert(els['copy-feedback'].textContent.includes('長按'));

  vm.runInContext("renderProgress({status:'running',segments:[{status:'generating'},{},{},{}]})",context);assert.equal(els.progress.value,0);assert.equal(els.progress.max,4);assert.equal(els['progress-label'].textContent,'整體完成 0／4 段（0%）');assert.equal(els['current-activity'].hidden,false);assert(els['activity-text'].textContent.includes('第 1／4 段 · 影片採樣中'));
  vm.runInContext("renderProgress({status:'running',segments:[{status:'done'},{status:'rewriting'},{},{}]})",context);assert.equal(els.progress.value,1);assert(els['progress-label'].textContent.includes('25%'));assert(els['activity-text'].textContent.includes('9B 改寫'));
  for(const [status,word] of [['analyzing_audio','分析整首音樂'],['planning_story','規劃全曲事件'],['assembling','合成原曲']]){vm.runInContext(`renderProgress({status:'${status}',segments:[{status:'done'}]})`,context);assert(els['activity-text'].textContent.includes(word));}
  for(const status of ['done','error','cancelled','interrupted']){vm.runInContext(`renderProgress({status:'${status}',segments:[]})`,context);assert.equal(els['current-activity'].hidden,true);assert.equal(els['activity-text'].textContent,'');assert(!els['progress-label'].textContent.includes('NaN'));}

  vm.runInContext("renderEventPlan({segments:[{index:0,director_plan:{mode:'story',event:'<b>plain text</b>'}}]})",context);assert.equal(els['event-plan-text'].textContent,'1. story\n<b>plain text</b>');assert.equal(els['event-plan-details'].hidden,false);assert.equal(vm.runInContext("eventPreview('x'.repeat(800)).length",context),101);
  els.prompt.value='original user prompt';await vm.runInContext("active='broken-plan';poll()",context);assert(els.status.textContent.startsWith('錯誤（planning_story）：plan parse failed'));assert(els.status.textContent.length<500);assert.equal(els.prompt.value,'original user prompt');assert(els['event-plan-text'].textContent.includes('x'.repeat(800)));
  const terminal=await vm.runInContext("api('status-error')",context);assert.equal(terminal.status,'error');assert.equal(terminal.error,'bad media tag');
  vm.runInContext('renderJobSeed({seed:0})',context);assert.equal(els['job-seed'].textContent,'本次 Seed：0');
  vm.runInContext('renderJobSeed({})',context);assert.equal(els['job-seed'].textContent,'本次 Seed：尚未取得');
  assert.equal(els['multi-panel'].hidden,true);
  els.image.files=[file('main.png')];els.image.onchange();els.song.files=[file('song.wav')];
  let req=await submit();assert.equal(req.story_plan,true);assert.equal(req.audio_analysis,true);assert.equal(req.realism_lora,undefined);assert.equal(req.realism_strength,undefined);assert.equal(req.face_identity,true);assert.equal(req.kitchen_attention,true);assert.equal(req.sparse_attention,false);assert.equal(req.motion_lora,true);assert.equal(req.width,1280);assert.equal(req.long_side,undefined);assert.equal(els['size-help'].textContent.includes('1280 × 720'),true);assert.equal(req.image_id,'main.png');assert.equal(req.image_ids,undefined);assert.equal(els['job-seed'].textContent,'本次 Seed：42');
  assert.deepEqual(uploads,['main.png','song.wav']);
  els.story_plan.checked=false;els.audio_analysis.checked=false;els.face_identity.checked=false;els.kitchen_attention.checked=false;els.sparse_attention.checked=true;els.motion_lora.checked=false;req=await submit();assert.equal(req.story_plan,false);assert.equal(req.audio_analysis,false);assert.equal(req.face_identity,false);assert.equal(req.kitchen_attention,false);assert.equal(req.sparse_attention,true);assert.equal(req.motion_lora,false);
  els['toggle-multiref'].onclick();assert.equal(els['multi-panel'].hidden,false);
  els['extra-images'].files=[file('side.png'),file('scene.png')];els['extra-images'].onchange();
  req=await submit();assert.deepEqual(req.image_ids,['main.png','side.png','scene.png']);
  els['toggle-multiref'].onclick();assert.equal(els['multi-panel'].hidden,true);
  req=await submit();assert.equal(req.image_ids,undefined);assert.deepEqual(uploads,['main.png','song.wav']);
  els['toggle-multiref'].onclick();req=await submit();assert.equal(req.image_ids.length,3);
  els.aspect.value='9:16';els.aspect.events.change();
  assert.equal(els.width.value,'720');assert(els['size-help'].textContent.includes('720 × 1280'));
  req=await submit();assert.equal(req.width,720);
  els.aspect.value='16:9';els.aspect.events.change();
  // Removing one extra renumbers the remaining card and the actual request together.
  els.previews.children[0].children[2].onclick();req=await submit();
  assert.deepEqual(req.image_ids,['main.png','scene.png']);
  assert(els.previews.children[0].children[1].textContent.startsWith('圖片2：'));
  // A tenth reference must be rejected without losing the existing selection.
  els['extra-images'].files=Array.from({length:8},(_,i)=>file(`extra${i}.png`));els['extra-images'].onchange();
  req=await submit();assert.equal(req.image_ids.length,2);
  await els['open-last'].onclick();assert.equal(els.kitchen_attention.checked,true);assert.equal(els.sparse_attention.checked,true);assert.equal(els['job-seed'].textContent,'本次 Seed：0');assert.equal(els.prompt.value,'saved story');assert.equal(els.aspect.value,'9:16');assert.equal(els.seed.value,'0');assert.equal(els.face_identity.checked,false);assert.equal(els['resume-project'].hidden,false);assert(els['project-summary'].textContent.includes('雲端歌曲'));
  assert.equal(els.audio_analysis.checked,false);assert.equal(els.story_plan.checked,false);
  vm.runInContext("renderAudioAnalysis({audio_analysis:{status:'ready',pulse:{bpm_estimate:120}},request:{audio_analysis:true}})",context);assert(els['audio-summary'].textContent.includes('120 BPM'));
  vm.runInContext("renderDirectorPlan({director_plan:{status:'ready'}})",context);assert(els['director-summary'].textContent.includes('全曲事件已分配'));
  await els['resume-project'].onclick();assert.deepEqual(resumes,[{id:'saved123'}]);
  console.log('UI checks passed: collapsed default, legacy single image, multi upload, toggle exclusion, retained selections, removal numbering and count limit.');
})().catch(e=>{console.error(e);process.exitCode=1;});
