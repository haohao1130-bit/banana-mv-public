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
Object.assign(els.mode,{value:'independent'});els.aspect.value='16:9';els.resolution.value='720p';els.width.value='1280';els.segment.value='10';els.project_scope.value='full';els.rewrite_retries.value='3';els.director.value='performance';els.intensity.value='high';els.face_identity.checked=true;els.audio_analysis.checked=true;els.story_plan.checked=true;els.persistent_scene_state.checked=true;els.kitchen_attention.checked=true;els.motion_lora.checked=true;
const posts=[],uploads=[],resumes=[],copied=[],retakes=[],selections=[];let reviewJob;
const context=vm.createContext({document:{getElementById:id=>{assert(els[id],`Missing DOM element ${id}`);return els[id];},createElement:()=>new Element()},
  URL:{createObjectURL:file=>'blob:'+file.name,revokeObjectURL:()=>{}},localStorage:{getItem:()=>null,setItem:()=>{},removeItem:()=>{}},
  setTimeout:()=>0,clearTimeout:()=>{},console,navigator:{clipboard:{writeText:async text=>{copied.push(text);}}},
  fetch:async(url,options)=>({ok:true,status:200,json:async()=>{
    if(url==='api/upload'){uploads.push(options.body.name);return {id:options.body.name};}
    if(url==='api/mv/start'){posts.push(JSON.parse(options.body));return {id:'abcd'};}
    if(url==='api/mv/projects')return [{id:'saved123',title:'雲端歌曲',completed:1,total:2,status:'interrupted'}];
    if(url==='api/mv/resume'){resumes.push(JSON.parse(options.body));return {id:'saved123'};}
    if(url==='api/mv/retake'){retakes.push(JSON.parse(options.body));return {...reviewJob,status:'retaking'};}
    if(url==='api/mv/select-take'){selections.push(JSON.parse(options.body));return {...reviewJob,status:'assembling'};}
    if(url==='api/mv/status?id=review123')return reviewJob;
    if(url==='api/mv/status?id=low480')return {id:'low480',title:'L4 test',duration:10,status:'interrupted',request:{mode:'independent',aspect:'16:9',width:854},segments:[]};
    if(url==='api/mv/status?id=saved123')return {id:'saved123',title:'雲端歌曲',duration:180,seed:0,status:'interrupted',request:{mode:'independent',aspect:'9:16',segment_seconds:15,project_scope:'excerpt',prompt:'saved story',lyrics:'已存歌詞',srt_reference:'已存SRT',face_identity:false},segments:[{start:0,seconds:15,status:'done'},{start:15,seconds:15}]};
    if(url==='api/mv/status?id=broken-plan')return {status:'error',error:'plan parse failed',error_stage:'planning_story',request:{director_version:2},segments:[{index:0,start:0,seconds:10,director_plan:{mode:'story',event:'x'.repeat(800)}}]};
    if(url==='status-error')return {status:'error',error:'bad media tag',segments:[]};
    return {status:'done',seed:42,segments:[]};
  }})});
vm.runInContext(html.split('<script>')[1].split('</script>')[0],context);
vm.runInContext(fs.readFileSync('banana_mv/web/clip_review.js','utf8'),context);
const file=name=>({name,size:100,lastModified:1});
async function submit(){uploads.length=0;await els.form.onsubmit({preventDefault(){}});await vm.runInContext('poll()',context);return posts.at(-1);}
(async()=>{
  vm.runInContext("renderProgress({status:'planning_state',segments:[{},{},{}]})",context);assert(els['activity-text'].textContent.includes('狀態'));
  vm.runInContext("renderOutputLocation({output_video:'/content/drive/MyDrive/BananaMV/videos/test.mp4'})",context);assert.equal(els['output-location'].hidden,false);assert(els['output-location'].textContent.includes('videos/test.mp4'));
  vm.runInContext("renderOutputLocation({export_error:'另存失敗，仍可下載'})",context);assert(els['output-location'].textContent.includes('仍可下載'));
  vm.runInContext("renderOutputLocation({})",context);assert.equal(els['output-location'].hidden,true);
  vm.runInContext("renderSceneSummary({scene_state_summary:{committed_clips:2},segments:[{},{},{}]});renderSceneDebug({scene_state_debug:{clip_index:1,scene_state_in:{},planned_events:['E1'],state_transitions:[],scene_state_out:{},visual_verified:false,clip_prompt:'do not duplicate'}})",context);assert(els['scene-state-summary'].textContent.includes('2／3'));assert.equal(els['scene-state-details'].hidden,false);assert(els['scene-state-debug'].textContent.includes('scene_state_in'));assert(!els['scene-state-debug'].textContent.includes('do not duplicate'));
  vm.runInContext("renderSceneDebug({});renderSceneSummary({})",context);assert.equal(els['scene-state-details'].hidden,true);assert.equal(els['scene-state-summary'].hidden,true);
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
  assert.equal(Object.keys(els).filter(id=>/^reference-slot-\d+$/.test(id)).length,9);assert(!/<input[^>]*\bmultiple\b/.test(html));
  const srt='1\n00:00:00,000 --> 00:00:03,000\n歌詞參考';
  els['srt-file'].files=[{name:'song.srt',size:100,text:async()=>srt}];await els['srt-file'].onchange();assert.equal(els['srt-reference'].value,srt);
  els.lyrics.value='全曲歌詞';
  els.image.files=[file('main.png')];els.image.onchange();els.song.files=[file('song.wav')];
  let req=await submit();assert.equal(req.project_scope,'full');assert.equal(req.rewrite_retries,3);assert.equal(req.lyrics,'全曲歌詞');assert.equal(req.srt_reference,srt);assert.equal(req.story_plan,true);assert.equal(req.persistent_scene_state,false);assert.equal(req.audio_analysis,true);assert.equal(req.realism_lora,undefined);assert.equal(req.realism_strength,undefined);assert.equal(req.face_identity,true);assert.equal(req.kitchen_attention,true);assert.equal(req.sparse_attention,false);assert.equal(req.motion_lora,true);assert.equal(req.width,1280);assert.equal(req.long_side,undefined);assert.equal(els['size-help'].textContent.includes('1280 × 720'),true);assert.equal(req.image_id,'main.png');assert.deepEqual(req.image_ids,['main.png']);assert.equal(els['job-seed'].textContent,'本次 Seed：42');
  assert.deepEqual(uploads,['main.png','song.wav']);
  els.project_scope.value='excerpt';els.story_plan.checked=false;els.audio_analysis.checked=false;els.face_identity.checked=false;els.kitchen_attention.checked=false;els.sparse_attention.checked=true;els.motion_lora.checked=false;req=await submit();assert.equal(req.project_scope,'excerpt');assert.equal(req.story_plan,false);assert.equal(req.audio_analysis,false);assert.equal(req.face_identity,false);assert.equal(req.kitchen_attention,false);assert.equal(req.sparse_attention,true);assert.equal(req.motion_lora,false);
  els['image-2'].files=[file('side.png')];els['image-2'].onchange();
  els['image-3'].files=[file('scene.png')];els['image-3'].onchange();
  req=await submit();assert.deepEqual(req.image_ids,['main.png','side.png','scene.png']);
  els['image-2'].files=[file('replacement.png')];els['image-2'].onchange();
  req=await submit();assert.deepEqual(req.image_ids,['main.png','replacement.png','scene.png']);
  assert.equal(els['image-name-3'].textContent,'scene.png');
  els.aspect.value='9:16';els.aspect.events.change();
  assert.equal(els.width.value,'720');assert(els['size-help'].textContent.includes('720 × 1280'));
  req=await submit();assert.equal(req.width,720);
  els.resolution.value='480p';els.resolution.events.change();
  assert.equal(els.width.value,'480');assert(els['size-help'].textContent.includes('480 × 854'));
  req=await submit();assert.equal(req.width,480);assert.equal(req.aspect,'9:16');
  for(const [aspect,width,label] of [['16:9',854,'854 × 480'],['4:5',480,'480 × 600'],['1:1',480,'480 × 480']]){
    els.aspect.value=aspect;els.aspect.events.change();req=await submit();
    assert.equal(req.width,width);assert(els['size-help'].textContent.includes(label));
  }
  els.resolution.value='720p';els.resolution.events.change();
  els.aspect.value='16:9';els.aspect.events.change();
  // Clear a fixed slot: no renumbering or uploads until that gap is filled.
  els['remove-image-2'].onclick();const beforeGap=posts.length;uploads.length=0;await els.form.onsubmit({preventDefault(){}});
  assert.equal(posts.length,beforeGap);assert.deepEqual(uploads,[]);
  assert.equal(els['image-name-3'].textContent,'scene.png');assert(els.status.textContent.includes('圖片2尚未選取'));
  els['image-2'].files=[file('actor2.png')];els['image-2'].onchange();
  req=await submit();assert.deepEqual(req.image_ids,['main.png','actor2.png','scene.png']);
  for(let n=4;n<=9;n++){els['image-'+n].files=[file(`slot${n}.png`)];els['image-'+n].onchange();}
  req=await submit();assert.equal(req.image_ids.length,9);assert.equal(req.image_ids[8],'slot9.png');
  els.mode.value='chain';els.mode.events.change();assert.equal(els['image-9'].disabled,true);
  const beforeChain=posts.length;uploads.length=0;await els.form.onsubmit({preventDefault(){}});assert.equal(posts.length,beforeChain);assert.deepEqual(uploads,[]);
  els['remove-image-9'].onclick();req=await submit();assert.equal(req.image_ids.length,8);
  assert.equal(req.image_ids[6],'slot7.png');assert.equal(req.image_ids[7],'slot8.png');
  els.mode.value='independent';els.mode.events.change();assert.equal(els['image-9'].disabled,false);
  // Clearing slot 1 also keeps every other binding in place.
  els['remove-image-1'].onclick();const beforeMissingFirst=posts.length;uploads.length=0;await els.form.onsubmit({preventDefault(){}});
  assert.equal(posts.length,beforeMissingFirst);assert.equal(els['image-name-2'].textContent,'actor2.png');
  els.image.files=[file('main.png')];els.image.onchange();
  await els['open-last'].onclick();assert.equal(els.project_scope.value,'excerpt');assert.equal(els.kitchen_attention.checked,true);assert.equal(els.sparse_attention.checked,true);assert.equal(els['job-seed'].textContent,'本次 Seed：0');assert.equal(els.prompt.value,'saved story');assert.equal(els.aspect.value,'9:16');assert.equal(els.seed.value,'0');assert.equal(els.face_identity.checked,false);assert.equal(els['resume-project'].hidden,false);assert(els['project-summary'].textContent.includes('雲端歌曲'));
  assert.equal(els.resolution.value,'720p');assert.equal(els.width.value,'720');
  assert.equal(els['srt-reference'].value,'已存SRT');assert.equal(els.lyrics.value,'已存歌詞');
  assert.equal(els.persistent_scene_state.checked,false);assert.equal(els.audio_analysis.checked,false);assert.equal(els.story_plan.checked,false);
  vm.runInContext("renderAudioAnalysis({audio_analysis:{status:'ready',pulse:{bpm_estimate:120}},request:{audio_analysis:true}})",context);assert(els['audio-summary'].textContent.includes('120 BPM'));
  vm.runInContext("renderDirectorPlan({director_plan:{status:'ready'}})",context);assert(els['director-summary'].textContent.includes('全曲故事、鏡頭與收尾已規劃'));
  let releaseRead;els['srt-file'].files=[{name:'slow.srt',size:100,text:()=>new Promise(resolve=>{releaseRead=resolve;})}];const pending=els['srt-file'].onchange();els['srt-reference'].value='手動文字';els['srt-reference'].oninput();releaseRead(srt);await pending;assert.equal(els['srt-reference'].value,'手動文字');
  els['srt-file'].files=[{name:'large.srt',size:300000}];await assert.rejects(els['srt-file'].onchange());els['srt-reference'].value='';els['srt-reference'].oninput();
  await els['resume-project'].onclick();assert.deepEqual(resumes,[{id:'saved123',rewrite_retries:3}]);
  vm.runInContext("renderRewriteAttempt({status:'running',rewrite_attempt:{stage:'rewriting',clip_index:1,attempt:2,max_attempts:4}})",context);assert(els['rewrite-status'].textContent.includes('第 2 / 4 次'));
  vm.runInContext("renderRewriteAttempt({status:'done'})",context);assert.equal(els['rewrite-status'].textContent,'');
  await vm.runInContext("openProject('low480')",context);assert.equal(els.project_scope.value,'full');assert.equal(els.resolution.value,'480p');assert.equal(els.width.value,'854');
  reviewJob={id:'review123',status:'done',seed:42,request:{mode:'chain'},segments:Array.from({length:4},(_,i)=>({index:i,start:i*10,seconds:10,status:'done',preview:`/clip-${i}`,selected_take:'original',takes:[{id:'original',status:'ready',seed:42+i,preview:`/clip-${i}-original`},{id:'abcdef123456',status:'ready',seed:900+i,preview:`/clip-${i}-new`}]}))};
  vm.runInContext(`active='review123';renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert.equal(els['clip-review'].hidden,false);assert.equal(els['clip-chain-note'].hidden,false);
  const rows=vm.runInContext('[...clipView.rows.values()]',context);
  assert.equal(rows.length,4);assert.equal(rows[0].video.muted,true);assert.equal(rows[0].video.preload,'none');
  rows[1].check.checked=true;rows[2].check.checked=true;rows[1].check.onchange();
  assert(els['clips-retake'].textContent.includes('2 顆'));assert.equal(els['clips-retake'].disabled,false);
  vm.runInContext(`renderClipPreviews(${JSON.stringify({...reviewJob,status:'running'})})`,context);
  assert.equal(els['clips-retake'].disabled,true);assert.equal(rows[1].check.disabled,false);
  assert.equal(els['clip-list'].children[1].children[1],rows[1].video);assert.equal(rows[1].check.checked,true);
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);await els['clips-retake'].onclick();
  assert.deepEqual(retakes,[{id:'review123',indices:[1,2]}]);
  rows[1].select.value='abcdef123456';rows[1].select.onchange();assert.equal(rows[1].video.src,'/clip-1-new');assert.equal(rows[1].use.disabled,false);
  await rows[1].use.onclick();assert.deepEqual(selections,[{id:'review123',index:1,take:'abcdef123456'}]);
  els['clips-all'].onclick();assert(rows.every(row=>row.check.checked));els['clips-clear'].onclick();assert(rows.every(row=>!row.check.checked));
  console.log('UI checks passed: nine visible single-file slots, fixed numbering, replacements, gaps blocked before upload, chain limits, prompt review and retakes.');
})().catch(e=>{console.error(e);process.exitCode=1;});

