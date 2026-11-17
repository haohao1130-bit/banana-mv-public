// Exercise the real frontend script with a tiny DOM and mocked HTTP; no npm packages.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync('banana_mv/web/index.html','utf8');
assert(html.indexOf('id="final-previews"')<html.indexOf('id="clip-review"'),
  'finished master and 1080P controls belong above the per-clip take list');
assert(html.indexOf('id="upscale-again"')<html.indexOf('id="upscale-preview"'),
  'upgrade action must be near the master, not at the end of the 1080P result panel');
assert.equal(html.split('id="upscale-again"').length,2,'exactly one working upgrade button');
assert(html.indexOf('id="recipe-review"')<html.indexOf('id="event-plan-details"'),
  'recipe confirmation and full cast review must sit above the event plan');
assert(html.indexOf('id="event-plan-details"')<html.indexOf('id="alchemy-title"'),
  'full commission details belong above the live furnace on both layouts');
assert(html.indexOf('id="alchemy-title"')<html.indexOf('id="stop"')
    &&html.indexOf('id="stop"')<html.indexOf('id="progress-summary"'),
  'safe stop-after-this-clip control must sit immediately beneath the furnace');
assert(html.indexOf('id="progress-summary"')<html.indexOf('id="clip-review"'),
  'clip-by-clip take review remains below the furnace progress');
assert(html.indexOf('id="rewritten-panel"')<html.indexOf('id="clip-review"'),
  'finished clips and H3 prompts belong above the final per-clip take review');
assert(!html.includes("insertAdjacentElement('afterend',recipe)"),
  'mobile viewport must not move approval below furnace progress');
assert(html.includes('#recipe-text{max-height:min(52vh,520px);overflow-y:auto'),
  'long 29-clip recipe scrolls internally without burying controls');
assert(html.includes('#event-plan-text{max-height:340px;overflow-y:auto'),
  'a 24-clip event list should scroll inside its own panel');
assert(html.includes('#status{max-height:340px;overflow-y:auto'),
  'a 24-clip progress log should not push take review off the page');

class Element{
  constructor(){this.children=[];this.value='';this.files=[];this.checked=false;this.style={};this.events={};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(key,value){this[key]=value;}
  getAttribute(key){return this[key]||null;}
  removeAttribute(key){delete this[key];}
  addEventListener(name,fn){this.events[name]=fn;}
  focus(){this.focused=true;}
  showModal(){this.open=true;}
  close(){this.open=false;this.events.close?.();}
  getBoundingClientRect(){return {left:20,right:680,top:20,bottom:800};}
  select(){this.selected=true;}
  setRangeText(text,start,end){this.value=this.value.slice(0,start)+text+this.value.slice(end);this.selectionStart=this.selectionEnd=start+text.length;}
  scrollIntoView(){this.scrolled=true;}
  insertAdjacentElement(position,child){child.insertPosition=position;return child;}
}
const els=Object.fromEntries([...html.matchAll(/\bid="([^"]+)"/g)].map(m=>[m[1],new Element()]));
Object.assign(els.mode,{value:'independent'});els.aspect.value='16:9';els.resolution.value='720p';els.width.value='1280';els.segment.value='10';els.project_scope.value='full';els.rewrite_retries.value='5';els.director.value='performance';els.intensity.value='high';els.face_identity.checked=true;els.audio_analysis.checked=true;els.music_structure.checked=true;els.rewrite.checked=true;els.persistent_scene_state.checked=true;els.kitchen_attention.checked=true;els.motion_lora.checked=true;
const posts=[],uploads=[],resumes=[],copied=[],retakes=[],selections=[],rewrites=[],branches=[];let reviewJob;const approvals=[];let recipeOpened=false;
let restartState={available:false,busy:false,reason:'5070 桌面管家尚未啟動'};
let serverInstance='mv-service-a',restartRequestInstance='mv-service-a',reloadCount=0;
const storage=new Map(),restartRequests=[];
const intervals=[];
const mobileViewport={matches:false,addEventListener(){}};
const context=vm.createContext({document:{getElementById:id=>{assert(els[id],`Missing DOM element ${id}`);return els[id];},createElement:()=>new Element()},
  URL:{createObjectURL:file=>'blob:'+file.name,revokeObjectURL:()=>{}},
  localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,v)=>storage.set(key,String(v)),removeItem:key=>storage.delete(key)},
  window:{confirm:()=>true,location:{reload:()=>{reloadCount++;}},matchMedia:()=>mobileViewport},
  setTimeout:(fn,ms)=>{if(ms===2000)fn();return 0;},clearTimeout:()=>{},setInterval:(fn,ms)=>{intervals.push({fn,ms});return intervals.length;},console,navigator:{clipboard:{writeText:async text=>{copied.push(text);}}},
  fetch:async(url,options)=>({ok:true,status:200,json:async()=>{
    if(url==='api/mv/restart-capability')return restartState;
    if(url==='api/health')return {service:'banana-mv',instance:serverInstance};
    if(url==='api/mv/restart'){restartRequests.push(JSON.parse(options.body));return {ok:true,instance:restartRequestInstance,restarting:true};}
    if(url==='api/upload'){uploads.push(options.body.name);return {id:options.body.name};}
    if(url==='api/mv/start'){const body=JSON.parse(options.body);posts.push(body);return {id:body.plan_review?'recipe123':'abcd'};}
    if(url==='api/mv/open-furnace'){approvals.push(JSON.parse(options.body));recipeOpened=true;return {id:'recipe123',status:'running'};}
    if(url==='api/mv/status?id=recipe123')return {id:'recipe123',title:'丹方',seed:0,duration:30,status:recipeOpened?'running':'plan_ready',plan_revision:'recipe-v1',plan_preview_setup:'<Picture 1> is the singer.',request:{plan_review:true,director_schema:5,rewrite:true},segments:[{index:0,start:0,seconds:15,director_plan:{mode:'story',event:'<Picture 1> performs <b>plain text</b>'}},{index:1,start:15,seconds:15,director_plan:{mode:'action',event:'The hero wins only here.'}}]};
    
    if(url==='api/mv/projects')return [{id:'saved123',title:'雲端歌曲',completed:1,total:2,status:'interrupted'}];
    if(url==='api/mv/resume'){resumes.push(JSON.parse(options.body));return {id:'saved123'};}
    if(url==='api/mv/rewrite-clip'){rewrites.push(JSON.parse(options.body));return {...reviewJob};}
    if(url==='api/mv/continue-branch'){branches.push(JSON.parse(options.body));return {...reviewJob,status:'assembling'};}
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
  // A missing V4 supervisor must never silently hide the restart control.
  await vm.runInContext('updateRestartControl()',context);
  assert.equal(els['restart-5070'].hidden,false);
  assert.equal(els['restart-5070'].disabled,true);
  assert(els['restart-5070'].textContent.includes('需 V4 管家'));
  assert(intervals.some(({ms})=>ms===5000),'supervisor capability is refreshed periodically');
  restartState={available:true,busy:false,reason:''};
  await vm.runInContext('updateRestartControl()',context);
  assert.equal(els['restart-5070'].disabled,false);
  assert.equal(els['restart-5070'].textContent,'↻ 重啟丹爐');
  restartState={available:true,busy:true,reason:'目前有任務正在執行'};
  await vm.runInContext('updateRestartControl()',context);
  assert.equal(els['restart-5070'].disabled,true);
  assert(els['restart-5070'].textContent.includes('任務中'));
  restartState={available:false,busy:false,reason:'5070 桌面管家尚未啟動'};
  await vm.runInContext('updateRestartControl()',context);
  assert.equal(els['restart-5070'].hidden,false);
  assert.equal(els['restart-5070'].disabled,true);

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

  // The AI handoff teaches user-facing controls, never transmits project
  // media or pretends an AI can directly press buttons in this browser.
  assert(html.includes('id="copy-ai-guide"'));
  assert(html.includes('5070 連續模式：重拍 V2 後怎麼接？'));
  await els['copy-ai-guide'].onclick();
  const aiGuide=copied.at(-1);
  for(const phrase of ['🍌 BANANAMV｜一鍵 AI 輔助新手教學',
                        'THE BANANA TAKE｜RTX 5070 本機版',
                        '一、你的工作範圍',
                        '二、新手開始',
                        '三、創作素材與圖片辨識',
                        '四、歌曲與音樂理解',
                        '五、故事導演',
                        '六、電影攝影與分鏡規劃',
                        '七、完整全咒的標準結構',
                        '八、BANANAMV 前端操作教學',
                        '九、生成結果檢查與回爐',
                        '十、續跑與影片版本管理',
                        '十一、AI 與使用者的合作規則',
                        '十二、新手最簡單的開始方式',
                        'AI 輸出完整 H3 控制詞',
                        '「依此提示詞回爐這一段」',
                        '「正式採用此版本」',
                        '「續跑未完成段落」',
                        '讓每個創意，都能拍成一部作品。']){
    assert(aiGuide.includes(phrase),'The new AI guide is missing '+phrase);
  }
  assert(aiGuide.includes('不負責：'));
  assert(aiGuide.includes('- 修改程式碼。'));
  assert(aiGuide.includes('- 維修 Python 或 CUDA。'));
  assert(aiGuide.includes('如果使用者要求 CODE BLOCK'));
  assert(/<select id="segment"><option value="5"[^>]*>[^<]*<\/option><option value="10" selected>/.test(html),'5070 default clip length must be 10 seconds');
  assert(/<select id="resolution"><option value="480p"[^>]*>[^<]*<\/option><option value="720p" selected>/.test(html),'5070 default render must be 720P');
  assert(html.includes('<input id="width" type="number" value="1280" readonly'),'16:9 initial width must match 720P');
  assert(els['ai-guide-copy-status'].textContent.includes('已複製'));
  assert.equal(els['ai-guide-fallback-box'].hidden,true);
  const originalClipboard=context.navigator.clipboard;
  context.navigator.clipboard=null;
  await els['copy-ai-guide'].onclick();
  assert.equal(els['ai-guide-fallback-box'].hidden,false);
  assert.equal(els['ai-guide-fallback'].value,aiGuide);
  assert.equal(els['ai-guide-fallback'].selected,true);
  assert(els['ai-guide-copy-status'].textContent.includes('自行複製'));
  context.navigator.clipboard=originalClipboard;

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
  vm.runInContext("renderProgress({status:'running',segments:[{status:'done'},{status:'rewriting'},{},{}]})",context);assert.equal(els.progress.value,1);assert(els['progress-label'].textContent.includes('25%'));assert(els['activity-text'].textContent.includes('9B 當段自動導演'));
  const continuation={status:'retaking',segments:Array.from({length:17},(_,i)=>({status:i<14?'done':'waiting'})),
    continuation_generation:{anchor_index:13,anchor_take:'abcdef123456',anchor_version:2,from_index:14,total:3},
    retake:{branch:{mode:'cascade',index:13,take:'abcdef123456'},completed:0,current:14,
      takes:{'14':'fedcbafedcba','15':'defabcdefabc','16':'ccddeeffaabb'}}};
  continuation.segments[14]={status:'rewriting',takes:[{id:'fedcbafedcba',status:'rewriting'}]};
  vm.runInContext(`renderProgress(${JSON.stringify(continuation)})`,context);
  assert.equal(els.progress.value,14,'new continuation begins with only the anchor and earlier clips done');
  assert(els['progress-label'].textContent.includes('第 14 段 V2 接續'));
  assert(els['progress-label'].textContent.includes('本次完成 0／3 段'));
  assert(els['activity-text'].textContent.includes('第 15／17 段 · 9B 重新編寫'));
  continuation.segments[14].status='generating';
  continuation.segments[14].takes[0].status='generating';
  vm.runInContext(`renderProgress(${JSON.stringify(continuation)})`,context);
  assert(els['activity-text'].textContent.includes('第 15／17 段 · H3 影片生成'));
  continuation.segments[14].status='done';continuation.segments[15].status='preparing';
  continuation.retake.completed=1;continuation.retake.current=15;
  vm.runInContext(`renderProgress(${JSON.stringify(continuation)})`,context);
  assert.equal(els.progress.value,15);
  assert(els['activity-text'].textContent.includes('第 16／17 段'));
  for(const [status,word] of [['analyzing_audio','分析整首音樂'],['planning_story','規劃全曲事件'],['assembling','合成原曲']]){vm.runInContext(`renderProgress({status:'${status}',segments:[{status:'done'}]})`,context);assert(els['activity-text'].textContent.includes(word));}
  for(const status of ['done','error','cancelled','interrupted']){vm.runInContext(`renderProgress({status:'${status}',segments:[]})`,context);assert.equal(els['current-activity'].hidden,true);assert.equal(els['activity-text'].textContent,'');assert(!els['progress-label'].textContent.includes('NaN'));}

  vm.runInContext("renderEventPlan({segments:[{index:0,director_plan:{mode:'story',event:'<b>plain text</b>'}}]})",context);assert.equal(els['event-plan-text'].textContent,'1. story\n<b>plain text</b>');assert.equal(els['event-plan-details'].hidden,false);assert.equal(vm.runInContext("eventPreview('x'.repeat(800)).length",context),101);
  assert.equal(els['event-plan-details'].open,true,'new event plans should be visible without extra click');
  els['event-plan-details'].open=false;
  vm.runInContext("renderEventPlan({id:'project-a',segments:[{index:0,director_plan:{mode:'story',event:'First event'}}]})",context);
  assert.equal(els['event-plan-details'].open,true,'new project should expand its event plan');
  els['event-plan-details'].open=false;
  vm.runInContext("renderEventPlan({id:'project-a',segments:[{index:0,director_plan:{mode:'story',event:'Updated event'}}]})",context);
  assert.equal(els['event-plan-details'].open,false,'polling must respect manual collapse');
  vm.runInContext("renderEventPlan({id:'next-project',segments:[{index:0,director_plan:{mode:'action',event:'Next event'}}]})",context);
  assert.equal(els['event-plan-details'].open,true,'opening another project expands its own events');
  vm.runInContext("renderEventPlan({request:{director_schema:8},segments:[{index:0,fixed_reference_settings:'<Picture 1> 是快遞員',director_plan:{mode:'action',event:'<Picture 2> 是機車'}}]})",context);
  assert.equal(els['event-plan-text'].textContent,'共同設定\n@圖片1 是快遞員\n\n1. action\n@圖片2 是機車');
  els.prompt.value='original user prompt';await vm.runInContext("active='broken-plan';poll()",context);assert(els.status.textContent.startsWith('錯誤（planning_story）：plan parse failed'));assert(els.status.textContent.length<500);assert.equal(els.prompt.value,'original user prompt');assert(els['event-plan-text'].textContent.includes('x'.repeat(800)));
  const terminal=await vm.runInContext("api('status-error')",context);assert.equal(terminal.status,'error');assert.equal(terminal.error,'bad media tag');
  vm.runInContext('renderJobSeed({seed:0})',context);assert.equal(els['job-seed'].textContent,'本次 Seed：0');
  vm.runInContext('renderJobSeed({})',context);assert.equal(els['job-seed'].textContent,'本次 Seed：尚未取得');
  assert.equal(Object.keys(els).filter(id=>/^reference-slot-\d+$/.test(id)).length,9);assert(!/<input[^>]*\bmultiple\b/.test(html));
  assert(html.includes('id="rewrite_retries" type="hidden" value="5"'));
  const srt='1\n00:00:00,000 --> 00:00:03,000\n歌詞參考';
  els['srt-file'].files=[{name:'song.srt',size:100,text:async()=>srt}];await els['srt-file'].onchange();assert.equal(els['srt-reference'].value,srt);
  els.lyrics.value='全曲歌詞';
  els.image.files=[file('main.png')];els.image.onchange();els.song.files=[file('song.wav')];
  let req=await submit();assert.equal(req.preview_zh,false);assert.equal(req.project_scope,'full');assert.equal(req.rewrite_retries,5);assert.equal(req.lyrics,'全曲歌詞');assert.equal(req.srt_reference,srt);assert.equal(req.story_plan,true);assert.equal(req.direct_script,false);assert.equal(req.persistent_scene_state,false);assert.equal(req.audio_analysis,true);assert.equal(req.music_structure,true);assert.equal(req.realism_lora,undefined);assert.equal(req.realism_strength,undefined);assert.equal(req.face_identity,true);assert.equal(req.kitchen_attention,true);assert.equal(req.sparse_attention,false);assert.equal(req.motion_lora,true);assert.equal(req.width,1280);assert.equal(req.long_side,undefined);assert.equal(els['size-help'].textContent.includes('1280 × 720'),true);assert.equal(req.image_id,'main.png');assert.deepEqual(req.image_ids,['main.png']);assert.equal(els['job-seed'].textContent,'本次 Seed：42');
  assert.deepEqual(uploads,['main.png','song.wav']);
  els.effects.files=[file('effects.wav')];req=await submit();assert.equal(req.effects_id,'effects.wav');assert(uploads.includes('effects.wav'));els.effects.files=[];
  els.project_scope.value='excerpt';els.rewrite.checked=false;els.audio_analysis.checked=false;els.music_structure.checked=false;els.face_identity.checked=false;els.kitchen_attention.checked=false;els.sparse_attention.checked=true;els.motion_lora.checked=false;req=await submit();assert.equal(req.project_scope,'excerpt');assert.equal(req.story_plan,false);assert.equal(req.direct_script,true);assert.equal(req.audio_analysis,false);assert.equal(req.face_identity,false);assert.equal(req.kitchen_attention,false);assert.equal(req.sparse_attention,true);assert.equal(req.motion_lora,false);
  els['image-2'].files=[file('side.png')];els['image-2'].onchange();
  els['image-3'].files=[file('scene.png')];els['image-3'].onchange();
  const typeMention=(text,caret=text.length)=>{els.prompt.value=text;els.prompt.selectionStart=els.prompt.selectionEnd=caret;els.prompt.events.input({isComposing:false});};
  typeMention('前文\n@ 後文',4);assert.equal(els['image-mentions'].hidden,false);assert.equal(els['image-mentions'].children.length,3);
  assert.equal(els['image-mentions'].children[2].children[0].src,'blob:scene.png');assert.equal(els['image-mentions'].children[2].children[1].children[0].textContent,'scene.png');
  let keptFocus=false;els['image-mentions'].children[2].onpointerdown({preventDefault(){keptFocus=true;}});assert(keptFocus);els['image-mentions'].children[2].onclick();
  assert.equal(els.prompt.value,'前文\n@圖片3 後文');assert.equal(els.prompt.selectionStart,7);assert.equal(els['image-mentions'].hidden,true);assert.equal(els.prompt['aria-expanded'],'false');
  typeMention('@');let prevented=false;els.prompt.events.keydown({key:'ArrowDown',preventDefault(){prevented=true;}});assert(prevented);assert.equal(els.prompt['aria-activedescendant'],'image-mention-2');
  els.prompt.events.keydown({key:'Enter',preventDefault(){}});assert.equal(els.prompt.value,'@圖片2 ');
  typeMention('讓@圖片3');assert.equal(els['image-mentions'].children.length,1);els['image-mentions'].children[0].onclick();assert.equal(els.prompt.value,'讓@圖片3 ');
  typeMention('@image2');assert.equal(els['image-mentions'].children[0].id,'image-mention-2');
  els.prompt.events.keydown({key:'Escape',preventDefault(){}});assert.equal(els['image-mentions'].hidden,true);
  typeMention('mail@example');assert.equal(els['image-mentions'].hidden,true);
  typeMention('@');els.prompt.events.compositionstart();assert.equal(els['image-mentions'].hidden,true);els.prompt.events.input({isComposing:true});assert.equal(els['image-mentions'].hidden,true);els.prompt.events.compositionend();assert.equal(els['image-mentions'].hidden,false);
  els.prompt.events.keydown({key:'Enter',isComposing:true});assert.equal(els.prompt.value,'@');els.prompt.events.blur();assert.equal(els['image-mentions'].hidden,true);
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
  typeMention('@');assert.deepEqual(els['image-mentions'].children.map(x=>x.id),['image-mention-1','image-mention-3']);
  typeMention('@圖片2');assert(els['image-mentions'].children[0].textContent.includes('沒有符合'));assert.equal(els.prompt['aria-activedescendant'],undefined);
  els['image-2'].files=[file('actor2.png')];els['image-2'].onchange();
  req=await submit();assert.deepEqual(req.image_ids,['main.png','actor2.png','scene.png']);
  for(let n=4;n<=9;n++){els['image-'+n].files=[file(`slot${n}.png`)];els['image-'+n].onchange();}
  req=await submit();assert.equal(req.image_ids.length,9);assert.equal(req.image_ids[8],'slot9.png');
  els.mode.value='chain';els.mode.events.change();assert.equal(els['image-9'].disabled,true);
  typeMention('@');assert.equal(els['image-mentions'].children.length,8);assert(!els['image-mentions'].children.some(x=>x.id==='image-mention-9'));
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
  typeMention('@');assert.equal(els['image-mentions'].children.length,1);assert.equal(els['image-mentions'].children[0].children[0].src,'api/mv/reference?id=saved123&image=0');els['image-mentions'].children[0].onclick();assert.equal(els.prompt.value,'@圖片1 ');
  assert.equal(els.persistent_scene_state.checked,false);assert.equal(els.audio_analysis.checked,false);
  vm.runInContext("renderAudioAnalysis({audio_analysis:{status:'ready',structure:{bpm:120,segments:[{start:0,end:10,label:'chorus'}]}},request:{audio_analysis:true}})",context);assert.equal(els['music-structure-details'].hidden,false);assert(els['music-structure-text'].textContent.includes('副歌（預測）'));
  vm.runInContext("renderAudioAnalysis({request:{}})",context);assert.equal(els['music-structure-details'].hidden,true);
  vm.runInContext("renderAudioAnalysis({audio_analysis:{status:'ready',pulse:{bpm_estimate:120}},request:{audio_analysis:true}})",context);assert(els['audio-summary'].textContent.includes('120 BPM'));
  vm.runInContext("renderDirectorPlan({director_plan:{status:'ready'}})",context);assert(els['director-summary'].textContent.includes('全曲故事、鏡頭與收尾已規劃'));
  let releaseRead;els['srt-file'].files=[{name:'slow.srt',size:100,text:()=>new Promise(resolve=>{releaseRead=resolve;})}];const pending=els['srt-file'].onchange();els['srt-reference'].value='手動文字';els['srt-reference'].oninput();releaseRead(srt);await pending;assert.equal(els['srt-reference'].value,'手動文字');
  els['srt-file'].files=[{name:'large.srt',size:300000}];await assert.rejects(els['srt-file'].onchange());els['srt-reference'].value='';els['srt-reference'].oninput();
  await els['resume-project'].onclick();assert.deepEqual(resumes,[{id:'saved123',rewrite_retries:5}]);
  vm.runInContext("renderRewriteAttempt({status:'running',rewrite_attempt:{stage:'rewriting',clip_index:1,attempt:2,max_attempts:4}})",context);assert(els['rewrite-status'].textContent.includes('第 2 / 4 次'));
  vm.runInContext("renderRewriteAttempt({status:'done'})",context);assert.equal(els['rewrite-status'].textContent,'');
  await vm.runInContext("openProject('low480')",context);assert.equal(els.project_scope.value,'full');assert.equal(els.resolution.value,'480p');assert.equal(els.width.value,'854');
  reviewJob={id:'review123',status:'done',seed:42,request:{mode:'chain'},segments:Array.from({length:4},(_,i)=>({index:i,start:i*10,seconds:10,status:'done',preview:`/clip-${i}`,selected_take:'original',takes:[{id:'original',status:'ready',seed:42+i,preview:`/clip-${i}-original`},{id:'abcdef123456',status:'ready',seed:900+i,preview:`/clip-${i}-new`}]}))};
  reviewJob.segments[1].director_plan={handoff_version:1,event:'Only this scene'};
  reviewJob.segments[1].prompt='subject_definitions:\\nOriginal H3 prompt';
  vm.runInContext(`active='review123';renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert.equal(els['clip-review'].hidden,false);assert.equal(els['clip-chain-note'].hidden,false);
  const rows=vm.runInContext('[...clipView.rows.values()]',context);
  assert.equal(rows.length,4);assert.equal(rows[0].video.muted,false);assert.equal(rows[0].video.preload,'none');
  reviewJob.segments[0].takes[0].preview_kind='raw';reviewJob.segments[0].takes[0].preview_filename='00_raw_v1.mp4';
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert(rows[0].note.textContent.includes('RAW 原始有聲預覽'));
  reviewJob.segments[0].takes[0].preview_kind='part';
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert(rows[0].note.textContent.includes('裁切版（無 RAW 音軌）'));
  rows[1].check.checked=true;rows[2].check.checked=true;rows[1].check.onchange();
  assert(els['clips-retake'].textContent.includes('2 顆'));assert.equal(els['clips-retake'].disabled,false);
  vm.runInContext(`renderClipPreviews(${JSON.stringify({...reviewJob,status:'running'})})`,context);
  assert.equal(els['clips-retake'].disabled,true);assert.equal(rows[1].check.disabled,false);
  assert.equal(els['clip-list'].children[1].children[1],rows[1].video);assert.equal(rows[1].check.checked,true);
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);await els['clips-retake'].onclick();
  assert.deepEqual(retakes,[{id:'review123',indices:[1,2],previous_takes:{'1':'original'}}]);
  rows[1].correction.value='只把手部操作拍清楚';rows[1].correction.oninput();
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert.equal(rows[1].correction.value,'只把手部操作拍清楚');
  assert.equal(els['clip-list'].children[1].children[1],rows[1].video);
  await els['clips-retake'].onclick();
  assert.deepEqual(retakes.at(-1),{id:'review123',indices:[1,2],instructions:{'1':'只把手部操作拍清楚'},previous_takes:{'1':'original'}});
  // New one-clip prompt workbench: do not queue H3 when asking 9B to recompose.
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert.equal(rows[1].rewriteButton.disabled,false);
  assert(rows[1].promptEditor.value.includes('Original H3 prompt'));
  await rows[1].rewriteButton.onclick();
  assert.deepEqual(rewrites,[{id:'review123',index:1,previous_take:'original'}]);
  assert.equal(retakes.length,2,'9B text rewrite does not queue a video retake');
  reviewJob.segments[1].prompt_rewrite={status:'ready',version:1,text:'subject_definitions:\n9B rewritten clip\nsummary:\nClip changed'};
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert(rows[1].promptEditor.value.includes('9B rewritten clip'));
  rows[1].promptEditor.value='subject_definitions:\nMy own custom revised clip';
  rows[1].promptEditor.oninput();
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert(rows[1].promptEditor.value.includes('My own custom revised clip'),'poll must not destroy manual edits');
  assert.equal(rows[1].renderButton.textContent,'依此提示詞回爐這一段');
  await rows[1].renderButton.onclick();
  assert.deepEqual(retakes.at(-1),{
    id:'review123',indices:[1],prompts:{'1':'subject_definitions:\nMy own custom revised clip'},previous_takes:{'1':'original'}
  });
  // A new previous Take is an explicit source for both 9B and H3.
  rows[0].select.value='abcdef123456';rows[0].select.onchange();
  await rows[1].rewriteButton.onclick();
  assert.deepEqual(rewrites.at(-1),{id:'review123',index:1,previous_take:'abcdef123456'});
  reviewJob.segments[1].prompt_rewrite={status:'ready',version:2,previous_take:'abcdef123456',
    text:'subject_definitions:\\nDraft based on newly rendered previous Take'};
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  await rows[1].renderButton.onclick();
  assert.deepEqual(retakes.at(-1),{
    id:'review123',indices:[1],
    prompts:{'1':'subject_definitions:\\nDraft based on newly rendered previous Take'},
    previous_takes:{'1':'abcdef123456'}
  });
  const retakeCount=retakes.length;
  rows[0].select.value='original';rows[0].select.onchange();
  await rows[1].renderButton.onclick();
  assert.equal(retakes.length,retakeCount,'stale rewritten prompt must not render against another previous Take');
  assert(rows[1].promptInfo.textContent.includes('上一段版本已變更'));
  vm.runInContext("renderFinalPreviews({current_master:2,segments:[{},{}],final_versions:[{version:2,download:'/master'},{version:3,reason:'face_refine',source_master:2,refined_clips:1,download:'/refined'}]})",context);
  assert.equal(els.video.src,'/master');assert.equal(els['refined-video'].src,'/refined');assert.match(els['refined-status'].textContent,/1／2/);

  vm.runInContext("renderFinalPreviews({video:'/master',status:'refining_faces',face_refine_progress:{stage:'clip',index:1,total:2}})",context);
  assert.match(els['refined-status'].textContent,/正在修臉第 2／2 段/);
  vm.runInContext("renderFinalPreviews({video:'/master',status:'refining_faces',face_refine_progress:{stage:'assembling'}})",context);
  assert.match(els['refined-status'].textContent,/正在合成/);
  vm.runInContext("renderFinalPreviews({video:'/master',status:'done',segments:[{face_refine_error:'測試原因'}]})",context);
  assert.match(els['refined-status'].textContent,/第 1 段：測試原因/);
  vm.runInContext('renderFinalPreviews({})',context);
  assert.equal(els['final-previews'].hidden,true);assert.equal(els['refined-video'].src,undefined);
  vm.runInContext("renderOutputLocation({final_video:'/job/final.mp4',current_master:2,final_versions:[{version:1,download:'/old-v1'},{version:2,download:'/new-v2'}]})",context);
  assert(els['output-location'].textContent.includes('/job/final.mp4'));
  assert.equal(els['master-list'].children.length,2);assert.equal(els['master-list'].children[0].href,'/old-v1');
  assert(els['master-list'].children[1].textContent.includes('目前版本'));
  vm.runInContext("renderOutputLocation({final_stale:true,video:'/old-master',final_video:'/job/final.mp4',current_master:2,final_versions:[{version:2,download:'/old-master'}],segments:[]})",context);
  assert.equal(els['final-previews'].hidden,true,'obsolete full MV cannot be shown as current');
  assert.equal(els['output-location'].hidden,true,'obsolete export path cannot be called the current result');
  assert(els['master-list'].children[0].textContent.includes('舊時間線備份'));
  rows[1].select.value='abcdef123456';rows[1].select.onchange();assert.equal(rows[1].video.src,'/clip-1-new');assert.equal(rows[1].use.disabled,false);
  await rows[1].use.onclick();assert.deepEqual(selections,[{id:'review123',index:1,take:'abcdef123456'}]);
  // A stopped project created by the old build can have a V2 that was
  // selected but not yet adopted; its adoption button must be enabled.
  reviewJob.status='cancelled';reviewJob.request.director_schema=6;
  reviewJob.segments[1].pending_take='abcdef123456';
  reviewJob.pending_takes={'1':'abcdef123456'};
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert.equal(rows[1].select.value,'abcdef123456');
  assert.equal(rows[1].use.disabled,false,'old pending V2 is not yet an official adopted take');
  assert.equal(els['clip-legacy-toolbar'].hidden,true,'the batch/condense UI is retired in 5070 chain');
  assert.equal(rows[1].branchOnly.hidden,true,'cannot replace one shot and keep obsolete successors');
  assert.equal(rows[1].checkLabel.hidden,true);
  assert.equal(rows[1].correctionLabel.hidden,true);
  assert.equal(els['clips-condense'].disabled,true);
  assert.equal(els['clips-retake'].disabled,true);
  delete reviewJob.pending_takes;
  delete reviewJob.segments[1].pending_take;
  // Emergency V2 adoption becomes official immediately; the SAME clip
  // still shows the restart button and starts from its next clip.
  reviewJob.status='cancelled';reviewJob.request.director_schema=6;
  reviewJob.segments[1].selected_take='abcdef123456';
  reviewJob.continuation_restart={index:1,take:'abcdef123456',from_index:2,rewrite_next_prompt:true};
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert.equal(rows[1].select.value,'abcdef123456');
  assert.equal(rows[1].branchCascade.hidden,false);
  assert.equal(rows[1].branchCascade.disabled,false);
  assert(rows[1].branchCascade.textContent.includes('第 3 段'));
  assert(rows[2].title.textContent.includes('舊時間線'));
  assert.equal(rows[2].use.disabled,true);
  assert.equal(rows[2].rewriteButton.disabled,true);
  assert.equal(rows[2].renderButton.disabled,true);
  vm.runInContext(`renderProgress(${JSON.stringify(reviewJob)})`,context);
  assert.equal(els.progress.value,2,'adopted V2 counts only valid shots before the old timeline');
  assert(els['progress-label'].textContent.includes('舊片失效'));
  await rows[1].branchCascade.onclick();
  assert.deepEqual(branches.at(-1),{
    id:'review123',index:1,take:'abcdef123456',mode:'cascade'
  });
  assert(els['resume-project'].textContent.includes('第 3 段接拍'));
  // Persisted V2 can have NO restart marker (old client / finished job).
  // It remains the authoritative tail for a newly requested cascade.
  delete reviewJob.continuation_restart;
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert.equal(rows[1].branchCascade.hidden,false,'official V2 must retain the continue button without a restart marker');
  assert.equal(rows[1].branchCascade.disabled,false);
  await rows[1].branchCascade.onclick();
  assert.deepEqual(branches.at(-1),{id:'review123',index:1,take:'abcdef123456',mode:'cascade'});
  reviewJob.status='done';
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert.equal(rows[1].branchCascade.hidden,false,'completed official V2 can still re-film its downstream');
  assert.equal(rows[1].branchCascade.disabled,false);
  reviewJob.segments[1].selected_take='original';
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  rows[1].select.value='abcdef123456';rows[1].select.onchange();
  assert.equal(rows[1].branchCascade.hidden,true,'unadopted candidate cannot start a new storyline');
  assert.equal(rows[1].use.disabled,false,'candidate must be adopted first');
  rows[1].select.value='original';rows[1].select.onchange();
  assert.equal(rows[1].branchCascade.hidden,true,'plain unmodified original has no new-tail restart');
  rows[1].select.value='abcdef123456';rows[1].select.onchange();
  reviewJob.status='done';
  reviewJob.segments[1].selected_take='original';
  delete reviewJob.continuation_restart;
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  reviewJob.segments[3].selected_take='abcdef123456';
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  assert.equal(rows[3].branchCascade.hidden,false,'last adopted clip must permit final reassembly');
  assert(rows[3].branchCascade.textContent.includes('合成正式新版全片'));
  reviewJob.segments[3].selected_take='original';
  vm.runInContext(`renderClipPreviews(${JSON.stringify(reviewJob)})`,context);
  els['clips-all'].onclick();assert(rows.every(row=>row.check.checked));els['clips-clear'].onclick();assert(rows.every(row=>!row.check.checked));
  // Even the failed/not-yet-generated clip has its own prompt workbench.
  const missing={id:'failed123',status:'error',request:{mode:'independent'},
    segments:[{index:0,start:0,seconds:10,status:'waiting',
      director_plan:{handoff_version:1,event:'A current event'},prompt:''}]};
  vm.runInContext(`renderClipPreviews(${JSON.stringify(missing)})`,context);
  const failedRow=vm.runInContext('clipView.rows.get(0)',context);
  assert(failedRow);assert.equal(failedRow.rewriteButton.disabled,false);
  assert.equal(failedRow.renderButton.disabled,true,'empty prompt cannot render');
  failedRow.promptEditor.value='subject_definitions:\nMy pasted manual prompt';
  failedRow.promptEditor.oninput();
  assert.equal(failedRow.renderButton.disabled,false,'complete pasted prompt can render first version');
  assert.equal(failedRow.renderButton.textContent,'依此提示詞回爐並自動續跑');
  vm.runInContext("active='failed123'",context);
  await failedRow.renderButton.onclick();
  assert.deepEqual(retakes.at(-1),{
    id:'failed123',indices:[0],
    prompts:{'0':'subject_definitions:\nMy pasted manual prompt'},
    auto_resume:true
  },'an unfinished clip must auto-continue after manual first render');

  // The same form submits either direct rendering or upstream-only planning.
  vm.runInContext('selectedImages.fill(null)',context);els.image.files=[file('review.png')];els.image.onchange();els.song.files=[file('review.wav')];els.rewrite.checked=true;
  await els.form.onsubmit({preventDefault(){},submitter:{id:'plan-first'}});await vm.runInContext('poll()',context);assert.equal(posts.at(-1).preview_zh,true);
  assert.equal(posts.at(-1).plan_review,true);assert.equal(approvals.length,0);
  assert.equal(els['recipe-review'].hidden,false);assert(els['recipe-text'].textContent.includes('15.00–30.00'));
  assert(els['recipe-text'].textContent.includes('@圖片1'));assert(els['recipe-text'].textContent.includes('<b>plain text</b>'));
  assert.equal(els.generate.disabled,false);assert.equal(els['plan-first'].disabled,false);assert.equal(els['approve-recipe'].disabled,false);
  assert.equal(els['mobile-furnace-start'].textContent,'丹方無誤，開爐','ready plan must replace direct generate');
  assert(html.includes('main>.card:nth-child(2){order:-1}'),'mobile saved projects must render before new MV setup');
  mobileViewport.matches=true;vm.runInContext('arrangeRecipe()',context);
  assert.equal(els['recipe-review'].insertPosition,undefined,'mobile recipe stays before the furnace without DOM reparenting');
  assert.equal(els['recipe-plan-details'].open,false,'full recipe should default closed on phone');
  vm.runInContext("renderEventPlan({id:'mobile-new-plan',segments:[{index:0,director_plan:{mode:'story',event:'A'}}]})",context);
  assert.equal(els['event-plan-details'].open,false,'event details should default closed on phone');
  const translatedRecipe={id:'recipe123',status:'plan_ready',plan_revision:'r1',plan_preview_setup:'English source setup',segments:[{index:0,start:0,seconds:10,director_plan:{event:'English source event'}}],plan_translation:{status:'ready',source_plan_revision:'r1',blocks:{setup:'中文共通設定','0':'中文事件 <Picture 2>'}}};
  els['recipe-language'].value='zh';context.translatedRecipe=translatedRecipe;vm.runInContext('renderRecipe(translatedRecipe)',context);assert(els['recipe-text'].textContent.includes('中文事件 @圖片2'));assert(els['recipe-language-status'].textContent.includes('僅供審閱'));
  els['recipe-language'].value='en';els['recipe-language'].onchange();assert(els['recipe-text'].textContent.includes('English source event'));assert(!els['recipe-text'].textContent.includes('中文事件'));
  els['recipe-language'].value='zh';translatedRecipe.plan_translation.source_plan_revision='stale';vm.runInContext('renderRecipe(translatedRecipe)',context);assert(els['recipe-text'].textContent.includes('English source event'));

  assert.equal(els.stop.hidden,true);assert.equal(els['resume-project'].hidden,true);assert.equal(els['current-activity'].hidden,true);
  await vm.runInContext("openProject('recipe123')",context);assert.equal(els['recipe-review'].hidden,false);assert.equal(approvals.length,0);
  const beforeApproval={posts:posts.length,uploads:uploads.length};
  await els['mobile-furnace-start'].onclick();
  assert.deepEqual(approvals,[{id:'recipe123',revision:'recipe-v1'}]);
  assert.equal(posts.length,beforeApproval.posts,'confirm must NOT create a new MV');
  assert.equal(uploads.length,beforeApproval.uploads,'confirm must NOT reupload song or references');
  assert.equal(els['recipe-review'].hidden,true);
  assert.equal(els['mobile-furnace-start'].textContent,'查看進度');
  await els['mobile-furnace-start'].onclick();
  assert.equal(els['progress-summary'].scrolled,true);
  assert.equal(posts.length,beforeApproval.posts,'progress link must NOT create a new MV');
  await els['approve-recipe'].onclick();assert.equal(approvals.length,1);
  mobileViewport.matches=false;vm.runInContext('arrangeRecipe()',context);
  assert.equal(els['recipe-review'].insertPosition,undefined,'desktop and mobile share the same review order');
  vm.runInContext('busy(false)',context);
  // The same browser/server instance may restore its selected project on F5.
  await vm.runInContext('restoreActiveProjectOnSameServer()',context);
  storage.set('banana_mv_job','saved123');
  await vm.runInContext('restoreActiveProjectOnSameServer()',context);
  assert.equal(vm.runInContext('active',context),'saved123');
  assert.equal(storage.get('banana_mv_job'),'saved123');
  assert.equal(storage.get('banana_mv_instance'),'mv-service-a');

  // A new service instance is a NEW furnace; the old project stays saved on
  // disk and remains explicitly openable, but must not appear by itself.
  serverInstance='mv-service-b';
  await vm.runInContext('restoreActiveProjectOnSameServer()',context);
  assert.equal(vm.runInContext('active',context),null);
  assert.equal(storage.has('banana_mv_job'),false);
  assert.equal(storage.get('banana_mv_instance'),'mv-service-b');
  await vm.runInContext("openProject('saved123')",context);
  assert.equal(storage.get('banana_mv_job'),'saved123');

  // The actual reboot button must clear remembered selection ONLY AFTER
  // server health confirms that a new instance is online.
  restartState={available:true,busy:false,reason:''};
  els['restart-5070'].disabled=false;
  restartRequestInstance='mv-service-b';
  serverInstance='mv-service-c';
  await els['restart-5070'].onclick();
  assert.deepEqual(restartRequests,[{confirm:'restart-5070'}]);
  assert.equal(reloadCount,1);
  assert.equal(storage.has('banana_mv_job'),false);
  assert.equal(storage.get('banana_mv_instance'),'mv-service-c');
  assert.equal(vm.runInContext('active',context),null);
    console.log('UI checks passed: image mentions with thumbnails, caret insertion, keyboard/IME, fixed slots, saved references, chain limits, prompt review and retakes.');
})().catch(e=>{console.error(e);process.exitCode=1;});



