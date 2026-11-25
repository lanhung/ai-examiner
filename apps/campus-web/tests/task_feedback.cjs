// Real browser, deterministic delayed API receipts. Optionally verify public assets, never live APIs.
'use strict';
const {test,before,after}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const http=require('node:http');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../web');
const user={principal_id:'test-user',teacher:true,nickname:'合成教师'};
let server,browser,origin;
before(async()=>{
 server=http.createServer(async(req,res)=>{
  const name=new URL(req.url,'http://localhost').pathname.slice(1)||'index.html';
  const file=path.resolve(root,name);
  if(!file.startsWith(root+path.sep)){res.writeHead(404).end();return}
  try{const body=await fs.readFile(file);res.writeHead(200,{'content-type':({'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css','.svg':'image/svg+xml'})[path.extname(file)]||'application/octet-stream'}).end(body)}
  catch{res.writeHead(404).end()}
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));origin='http://127.0.0.1:'+server.address().port;
 if(process.env.CAMPUS_TEST_STATIC_ORIGIN){
  const publicSite=new URL(process.env.CAMPUS_TEST_STATIC_ORIGIN);
  assert.equal(publicSite.protocol,'https:');origin=publicSite.origin;
 }
 browser=await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL||(process.platform==='win32'?'msedge':undefined)});
});
after(async()=>{await browser?.close();if(server)await new Promise(r=>server.close(r))});

function gate(){let open;const promise=new Promise(r=>{open=r});return {promise,open}}
async function fixture(t,url,width,respond,me=()=>user){
 const ctx=await browser.newContext({viewport:{width,height:800},locale:'zh-CN',serviceWorkers:'block'});t.after(()=>ctx.close());
 const p=await ctx.newPage(),errors=[];p.on('pageerror',e=>errors.push(e.message));p.setDefaultTimeout(16500);
 const remote=!!process.env.CAMPUS_TEST_STATIC_ORIGIN,assets=new Map(),apiPath=/^\/(?:gateway\/api|api)\//;
 if(remote){
  p.setDefaultNavigationTimeout(45000);
  p.on('response',r=>{const name=new URL(r.url()).pathname;if(assets.has(name))assets.set(name,r.status())});
 }
 await p.route(remote?'**/*':/\/(?:gateway\/api|api)\//,async r=>{
  const req=r.request(),u=new URL(req.url()),pathname=u.pathname;
  if(remote){
   if(u.origin!==origin)return r.abort();
   if(!apiPath.test(pathname)){
    if(req.method()!=='GET'||!/^\/(?:index\.html|app\.js|style\.css|brand\.svg|figure\.svg|icons\/[a-z0-9-]+\.svg)?$/.test(pathname))return r.abort();
    assets.set(pathname,'pending');return r.continue();
   }
  }
  const result=pathname==='/api/me'?{user:me()}:await respond(pathname, req);
  if(result===undefined){errors.push('unhandled '+req.method()+' '+pathname);return r.fulfill({status:404,json:{}})}
  if(!p.isClosed())await r.fulfill({status:result.http||200,json:result.http?{detail:'合成测试响应'}:result}).catch(err=>{if(!p.isClosed())throw err});
 });
 try{await p.goto(origin+'/#'+url,{waitUntil:'domcontentloaded'})}
 catch(e){if(remote)t.diagnostic('Public static responses: '+JSON.stringify(Object.fromEntries(assets)));throw e}
 t.after(()=>assert.deepEqual(errors,[]));
 return p;
}
const action=(p,name)=>p.locator('[data-act="'+name+'"]');
async function track(p,selector){
 await p.locator(selector).waitFor();
 await p.evaluate(s=>{
  window.probe={node:document.querySelector(s),loaders:0,menu:document.querySelector('#nav a')};
  new MutationObserver(rs=>{for(const r of rs)for(const n of r.addedNodes)if(n.textContent.trim()==='正在读取…')window.probe.loaders++}).observe(document.querySelector('#content'),{childList:true,subtree:true});
 },selector);
}
async function stable(p,selector){
 assert.deepEqual(await p.evaluate(s=>[window.probe.loaders,window.probe.node===document.querySelector(s),window.probe.menu===document.querySelector('#nav a'),document.documentElement.scrollWidth<=innerWidth],selector),[0,true,true,true]);
}
async function until(fn){const end=Date.now()+18000;while(!fn()){if(Date.now()>end)throw Error('Expected receipt was not observed');await new Promise(r=>setTimeout(r,60))}}
const receipt=(id,status,result={})=>({id,status,result});
const attempt=(status='active',id='att')=>({id,title:'测试口试',student_name:'合成学员',status,position:status==='completed'?1:0,question_count:1,
 question:status==='completed'?null:{text:'为什么要保留独立测试集？'},answers:[],final_score:status==='completed'?81:null});

for(const mode of ['answer','preview'])test(mode+': submission, polling and score keep the current page',async t=>{
 const base='/gateway/api/v1/school/'+(mode==='preview'?'teacher/previews/':'attempts/')+'att';
 const ack=gate();let posts=0,reads=0,done=false;
 const p=await fixture(t,mode+'/att',mode==='answer'?390:1440,async(path,req)=>{
  if(path===base+'/answers/async'){posts++;assert.equal(req.postDataJSON().answer,'独立测试集');await ack.promise;return attempt('grading')}
  if(path===base){reads++;if(posts&&reads===2&&mode==='answer')return {http:503};return attempt(done?'completed':posts?'grading':'active')}
 });
 await track(p,'#answerform textarea');
 await p.locator('#answerform textarea').fill('独立测试集');await action(p,'submit-answer').click();
 await p.locator('#task-status').filter({hasText:'正在提交回答'}).waitFor();
 assert.ok(await action(p,'submit-answer').isDisabled());
 ack.open();await p.locator('#task-status').filter({hasText:'正在评分'}).waitFor();
 if(mode==='answer')await p.locator('#task-status').filter({hasText:'不会重复提交'}).waitFor();
 await until(()=>reads>=3);
 await stable(p,'#answerform textarea');
 assert.equal(await p.locator('#answerform textarea').inputValue(),'独立测试集');
 assert.ok(await p.getByRole('heading',{name:'为什么要保留独立测试集？'}).isVisible());
 done=true;await p.locator('.score').filter({hasText:'81'}).waitFor();
 assert.equal(posts,1);assert.equal(await p.evaluate(()=>window.probe.loaders),0);
});

test('blueprint and upload poll only their receipt, retain the file, and restore the blueprint after reload',async t=>{
 let projects=0,docs=0,workspace=0,posts=0,reads=0,complete=false,uploadReads=0;
 const ack=gate(),bp={id:'bp',data:{title:'合成蓝图',questions:[{text:'为何采用盲评？'}]}};
 const p=await fixture(t,'prepare',1024,async(path,req)=>{
  if(path.endsWith('/workspace/teacher')){workspace++;return {model_ready:true,profile:'qwen:qwen-plus'}}
  if(path==='/gateway/api/projects'){projects++;return [{id:'p',name:'材料项目'}]}
  if(path.endsWith('/p/documents')){docs++;return [{id:'d',filename:'paper.txt'}]}
  if(path.endsWith('/p/blueprints/async')){posts++;assert.ok(req.headers()['idempotency-key']);await ack.promise;return receipt('j','queued')}
  if(path.endsWith('/jobs/j')){reads++;return receipt('j',complete?'completed':'running',complete?{blueprint:bp}:{})}
  if(path.endsWith('/p/documents/async'))return receipt('u','queued');
  if(path.endsWith('/jobs/u')){uploadReads++;return receipt('u','completed',{document:{id:'d2',filename:'new-paper.txt'}})}
 });
 await track(p,'#file');
 const file={name:'new-paper.txt',mimeType:'text/plain',buffer:Buffer.from('Synthetic evidence')};
 await p.locator('#file').setInputFiles(file);await action(p,'blueprint').click();
 await p.locator('#task-status').filter({hasText:'正在提交蓝图'}).waitFor();ack.open();
 await until(()=>reads>=2);await stable(p,'#file');
 assert.deepEqual([workspace,projects,docs,posts],[1,1,1,1]);
 assert.equal(await p.locator('#file').evaluate(el=>el.files[0].name),file.name);
 complete=true;await p.getByText('1. 为何采用盲评？',{exact:true}).waitFor();await stable(p,'#file');
 await p.reload();await p.getByText('1. 为何采用盲评？',{exact:true}).waitFor();
 assert.equal(posts,1);assert.doesNotMatch(await p.evaluate(()=>JSON.stringify(sessionStorage)),/为何采用盲评/);
 await track(p,'#file');await p.locator('#file').setInputFiles(file);await action(p,'upload').click();
 await p.locator('#task-status').filter({hasText:'材料解析完成'}).waitFor();
 assert.equal(await p.locator('#doc').inputValue(),'d2');assert.equal(uploadReads,1);
 await stable(p,'#file');
});

test('personal dialogue reads receipts only while pending and appends the reply in place',async t=>{
 const turns=Array.from({length:11},(_,i)=>({role:i%2?'user':'assistant',content:'研究动机与方法，第 '+(i+1)+' 轮。'}));
 let posts=0,reads=0,transcripts=0,done=false;const ack=gate();
 const p=await fixture(t,'session/s/teacher',768,async(path,req)=>{
  if(path.endsWith('/sessions/s')){transcripts++;return {id:'s',status:'active',state:'LISTENING',turns:done?[...turns,{role:'user',content:'比较两种方法。'},{role:'assistant',content:'样本如何分组？'}]:turns}}
  if(path.endsWith('/operations')){posts++;assert.equal(req.postDataJSON().expected_turn_count,turns.length);await ack.promise;return receipt('turn-job','queued')}
  if(path.includes('/operations/')){reads++;return {job:receipt('turn-job',done?'completed':'running')}}
 });
 const firstTurn='#session-turns > .box:first-child';
 await track(p,firstTurn);await p.locator('#session-answer').fill('比较两种方法。');
 await action(p,'session-answer').click();assert.ok(await action(p,'session-answer').isDisabled());ack.open();
 await p.locator('#task-status').filter({hasText:'正在准备回应'}).waitFor();
 const position=await p.locator('#session-answer').evaluate(el=>{el.focus();el.setSelectionRange(1,3);return window.scrollY});
 assert.ok(position>0);
 await until(()=>reads>=2);assert.equal(transcripts,1);
 assert.equal(await p.locator('#session-answer').inputValue(),'比较两种方法。');
 assert.deepEqual(await p.locator('#session-answer').evaluate(el=>[window.scrollY,document.activeElement===el,el.selectionStart,el.selectionEnd]),[position,true,1,3]);
 await stable(p,firstTurn);
 done=true;await p.getByText('样本如何分组？',{exact:true}).waitFor();await stable(p,firstTurn);
 assert.equal(await p.locator('#session-answer').inputValue(),'');assert.deepEqual([posts,transcripts],[1,2]);
});

test('an unconfirmed school write is never automatically repeated and an explicit retry reuses the request ID',async t=>{
 let reads=0;const writes=[];
 const p=await fixture(t,'answer/att',390,async(path,req)=>{
  if(path.endsWith('/answers/async')){writes.push(req.postDataJSON());return writes.length===1?{http:504}:attempt('completed')}
  if(path.endsWith('/attempts/att')){reads++;return attempt()}
 });
 await track(p,'#answerform textarea');await p.locator('#answerform textarea').fill('保留这一份。');
 await action(p,'submit-answer').click();await until(()=>reads>=2);await stable(p,'#answerform textarea');
 assert.equal(writes.length,1);assert.equal(await p.locator('#answerform textarea').inputValue(),'保留这一份。');
 await action(p,'submit-answer').click();await p.locator('.score').filter({hasText:'81'}).waitFor();
 assert.equal(writes.length,2);assert.deepEqual(writes[1],writes[0]);
});

test('a delayed score cannot replace a different screen',async t=>{
 let reads=0;const waiting=gate();
 const p=await fixture(t,'answer/att',390,async path=>{
  if(path.endsWith('/attempts/att')){if(++reads===1)return attempt('grading');await waiting.promise;return attempt('completed')}
  if(path.endsWith('/school/exams'))return [];
 });
 await p.locator('#task-status').filter({hasText:'评分'}).waitFor();await until(()=>reads===2);
 await p.locator('#nav a[href="#records"]').click();await p.getByRole('heading',{name:'我的答卷'}).waitFor();
 const response=p.waitForResponse(r=>r.url().includes('/attempts/att'));waiting.open();await response;await p.waitForTimeout(120);
 assert.ok(await p.getByRole('heading',{name:'我的答卷'}).isVisible());assert.equal(await p.locator('.score').count(),0);
});

test('revoked access removes the protected question rather than retaining stale content',async t=>{
 let reads=0;
 const p=await fixture(t,'answer/att',1440,async path=>{
  if(path.endsWith('/attempts/att'))return ++reads===1?attempt('grading'):{http:403};
 });
 await p.getByRole('heading',{name:'为什么要保留独立测试集？'}).waitFor();
 await p.locator('#content .alert').waitFor();assert.equal(await p.getByText('为什么要保留独立测试集？',{exact:true}).count(),0);
});

const finalSession={id:'s',status:'completed',state:'COMPLETED',turns:[
 {role:'assistant',content:'评价标准是什么？'},{role:'user',content:'以误差为标准。'}
]};

test('missing receipt does not mask the committed last answer or block the report',async t=>{
 let writes=0,reports=0;const pending=gate();t.after(()=>pending.open());
 const p=await fixture(t,'session/s/student',390,async(path,req)=>{
  if(path.endsWith('/sessions/s'))return writes?finalSession:{...finalSession,status:'active',state:'LISTENING',turns:finalSession.turns.slice(0,1)};
  if(path.endsWith('/operations')){writes++;return {http:504}}
  if(path.includes('/operations/'))return {job:null};
  if(path.endsWith('/report')){reports++;assert.equal(req.method(),'GET');await pending.promise;return {session_status:'completed',overall_score:0,max_score:5,questions_answered:1,evaluated_turns:1,evidence:[{quote:'以误差为标准。'}]}}
 });
 await p.locator('#session-answer').fill('以误差为标准。');await action(p,'session-answer').click();
 await action(p,'report').waitFor();
 assert.doesNotMatch(await p.locator('#task-status').innerText(),/回执|重试|准备回应/);
 await action(p,'report').click();await until(()=>reports===1);
 assert.equal(new URL(p.url()).hash,'#report/s/student');
 assert.ok(await p.getByRole('heading',{level:1,name:'答辩报告'}).isVisible());assert.equal(await p.locator('dialog[open]').count(),0);
 assert.match(await p.locator('#report-body').innerText(),/正在读取/);
 pending.open();await p.locator('#report-body').getByText('0 / 5',{exact:true}).waitFor();
 assert.match(await p.locator('#report-body').innerText(),/以误差为标准/);
 assert.equal(writes,1);assert.equal(reports,1);
});

test('reopening a completed session discards even an old receipt with no turn count',async t=>{
 let polls=0;
 const p=await fixture(t,'session/s/teacher',768,async path=>{
  if(path.endsWith('/sessions/s'))return finalSession;
  if(path.includes('/operations/')){polls++;return {job:receipt('old','running')}}
 });
 await action(p,'report').waitFor();
 await p.evaluate(()=>sessionStorage.setItem('campus-progress:test-user:teacher',JSON.stringify({session:'s',operation:'old'})));
 await p.reload({waitUntil:'domcontentloaded'});await action(p,'report').waitFor();
 assert.ok(!JSON.parse(await p.evaluate(()=>sessionStorage.getItem('campus-progress:test-user:teacher'))).operation);
 await p.waitForTimeout(450);
 assert.equal(polls,0);assert.equal(await p.locator('#task-status').innerText(),'');
});

test('an advanced transcript after reload unlocks the next question without storing or posting the answer',async t=>{
 let writes=0,polls=0;
 const p=await fixture(t,'session/s/student',1024,async(path,req)=>{
  if(req.method==='POST')writes++;
  if(path.endsWith('/sessions/s'))return {id:'s',status:'active',state:'LISTENING',turns:[...finalSession.turns,{role:'assistant',content:'还有什么局限？'}]};
  if(path.includes('/operations/')){polls++;return {job:null}}
 });
 await p.locator('#session-answer').waitFor();
 await p.evaluate(()=>sessionStorage.setItem('campus-progress:test-user:student',JSON.stringify({session:'s',operation:'old',operationTurnCount:1})));
 await p.reload({waitUntil:'domcontentloaded'});await p.getByText('还有什么局限？',{exact:true}).waitFor();
 assert.ok(await action(p,'session-answer').isEnabled());
 assert.ok(!JSON.parse(await p.evaluate(()=>sessionStorage.getItem('campus-progress:test-user:student'))).operation);
 assert.equal(polls,0);assert.equal(writes,0);
});

for(const queued of [true,false])test('missing receipt stops polling; queued='+queued,async t=>{
 const writes=[];let reads=0,done=false;
 const p=await fixture(t,'session/s/student',390,async(path,req)=>{
  if(path.endsWith('/sessions/s'))return done?finalSession:{...finalSession,status:'active',state:queued&&writes.length?'OPERATION_QUEUED':'LISTENING',turns:finalSession.turns.slice(0,1)};
  if(path.endsWith('/operations')){writes.push(req.postDataJSON());if(writes.length===2)done=true;return {http:504}}
  if(path.includes('/operations/')){reads++;return {job:null}}
 });
 await p.locator('#session-answer').fill('以误差为标准。');await action(p,'session-answer').click();
 await action(p,'refresh-turn').waitFor();
 assert.equal(reads,3);assert.equal(writes.length,1);
 assert.equal(await action(p,'session-answer').isDisabled(),queued);
 assert.doesNotMatch(await p.evaluate(()=>JSON.stringify(sessionStorage)),/以误差为标准/);
 await p.clock.install();await p.clock.fastForward(60000);assert.equal(reads,3);
 if(queued){done=true;await action(p,'refresh-turn').click()}
 else{await action(p,'session-answer').click();assert.deepEqual(writes[0],writes[1])}
 await action(p,'report').waitFor();assert.equal(writes.length,queued?1:2);
});

test('a slow report can be retried read-only; lengthy evidence is paged and respects a no-total rubric',async t=>{
 const delayed=gate();t.after(()=>delayed.open());let gets=0;
 const p=await fixture(t,'session/s/student',390,async(path,req)=>{
  if(path.endsWith('/sessions/s'))return finalSession;
  if(path.endsWith('/report')){
   gets++;assert.equal(req.method(),'GET');if(gets===1){await delayed.promise;return {summary:'过时结果'}}
   return {session_status:'completed',show_total_score:false,computed_overall_score:4.97,evidence:Array.from({length:16},(_,i)=>({quote:'合成摘录 #'+(i+1),source_excerpt:'A'.repeat(500)})),sections:[{data:'内部重复证据'}]};
  }
 });
 await action(p,'report').waitFor();await p.clock.install();
 await action(p,'report').click();await until(()=>gets===1);await p.clock.fastForward(16000);
 await p.getByRole('alert').filter({hasText:'超时'}).waitFor();
 await action(p,'retry-report').click();await p.locator('#report-evidence article').first().waitFor();
 delayed.open();
 assert.equal(await p.locator('#report-evidence article').count(),5);
 assert.doesNotMatch(await p.locator('#report-body').innerText(),/4\.97|内部重复证据|过时结果/);
 assert.ok(await p.locator('#report-body').evaluate(el=>el.scrollWidth<=el.clientWidth));
 await action(p,'report-next').click();await p.getByText('合成摘录 #6',{exact:true}).waitFor();
 await action(p,'report-prev').click();await p.getByText('合成摘录 #1',{exact:true}).waitFor();
 await p.getByRole('link',{name:'返回答辩',exact:true}).click();await action(p,'report').waitFor();
 assert.equal(new URL(p.url()).hash,'#session/s/student');assert.equal(gets,2);
});

test('cancelled report cannot reopen or paint another screen',async t=>{
 const pending=gate();t.after(()=>pending.open());let reports=0;
 const p=await fixture(t,'session/s/teacher',1440,async path=>{
  if(path.endsWith('/sessions/s'))return finalSession;
  if(path.endsWith('/report')){reports++;await pending.promise;return {summary:'旧会话私有报告'}}
  if(path.endsWith('/school/exams'))return [];
 });
 await action(p,'report').click();await until(()=>reports===1);
 await p.locator('#nav a[href="#records"]').click();
 await p.getByRole('heading',{name:'我的答卷'}).waitFor();pending.open();await p.waitForTimeout(150);
 assert.ok(!(await p.locator('#dialog').isVisible()));assert.doesNotMatch(await p.locator('body').textContent(),/旧会话私有报告/);
});

test('report is a reloadable teacher page with native back, forward and an explicit return',async t=>{
 const reads=[];
 const p=await fixture(t,'session/s/teacher',1024,(path,req)=>{
  assert.equal(req.method(),'GET');assert.equal(req.headers()['x-campus-role'],'teacher');reads.push(path);
  if(path.endsWith('/sessions/s'))return finalSession;
  if(path.endsWith('/s/report'))return {session_status:'completed',summary:'合成回顾',evidence:[]};
 });
 const link=p.getByRole('link',{name:'查看报告'});
 assert.equal(await link.getAttribute('href'),'#report/s/teacher');
 await link.click();await p.getByText('合成回顾',{exact:true}).waitFor();
 assert.equal(await p.title(),'答辩报告 · 答辩学堂');
 assert.equal(await p.locator('#nav [aria-current="page"]').getAttribute('href'),'#teacher');
 await p.goBack();await link.waitFor();assert.equal(new URL(p.url()).hash,'#session/s/teacher');
 await p.goForward();await p.getByText('合成回顾',{exact:true}).waitFor();
 await p.reload({waitUntil:'domcontentloaded'});await p.getByText('合成回顾',{exact:true}).waitFor();
 await p.getByRole('link',{name:'返回答辩',exact:true}).click();await link.waitFor();
 assert.equal(reads.filter(s=>s.endsWith('/report')).length,3);
 assert.equal(reads.filter(s=>s.endsWith('/sessions/s')).length,3);
 assert.equal(await p.locator('dialog[open]').count(),0);
 assert.doesNotMatch(await p.evaluate(()=>JSON.stringify(sessionStorage)),/合成回顾/);
});

test('private report link resumes after sign-in; a denied or unfinished report reveals no scores',async t=>{
 let logged=false,mode='denied',reports=0,checks=0;
 const p=await fixture(t,'report/s/student',390,(path,req)=>{
  if(path==='/api/login'){logged=true;return {}}
  assert.equal(req.method(),'GET');assert.equal(req.headers()['x-campus-role'],'student');
  if(path.endsWith('/s/report')){reports++;return mode==='denied'?{http:403}:{overall_score:4.999,summary:'未完成的私有评价'}}
  if(path.endsWith('/sessions/s')){checks++;return {id:'s',status:'active'}}
 },()=>logged?user:null);
 await p.getByRole('button',{name:'账号登录'}).click();assert.equal(reports,0);
 await p.getByLabel('用户名').fill('report_fixture');await p.getByLabel('密码',{exact:true}).fill('Synthetic-password');
 await p.getByRole('button',{name:'登录',exact:true}).click();
 await p.getByRole('alert').filter({hasText:'无法查看'}).waitFor();assert.equal(new URL(p.url()).hash,'#report/s/student');
 assert.equal(reports,1);assert.ok(await action(p,'print-report').isHidden());
 mode='active';await p.reload({waitUntil:'domcontentloaded'});await p.getByText(/答辩尚未结束/).waitFor();
 assert.equal(checks,1);assert.doesNotMatch(await p.locator('main').innerText(),/4\.999|未完成的私有评价/);
});

test('standalone report layout, evidence and full print at desktop and phone widths',async t=>{
 const report={session_status:'completed',title:'城市公交短时客流预测：时间切分与节假日误差分析',
  template:{title:'学术论文答辩'},overall_score:3.8,max_score:5,questions_answered:4,evaluated_turns:6,
  dimension_scores:[{title:'研究问题',score:4.2,evidence_count:2},{title:'实验设计',score:3.8,evidence_count:3},{title:'结论与局限',score:3.4,evidence_count:1},{title:'可复现性',score:0,evidence_count:0}],
  objective_scores:[{title:'数据划分的合理性',score:4.1,evidence_count:1}],knowledge_map:[{name:'时间序列验证',status:'mastered'}],
  strengths:['明确区分了工作日与节假日的客流规律。'],priority_weaknesses:['还没有用分组误差支持节假日的结论。'],
  recommended_actions:['补充普通周和节假日的误差对照表。','解释基线方法在高峰时段失效的条件。'],improvement_path:['复测时间切分与数据泄漏的区别。'],
  question_trajectories:['a','b','c','d'].map(question_id=>({question_id})),
  evidence:Array.from({length:6},(_,i)=>({question_id:['a','a','b','c','c','d'][i],question_context:i===1||i===4?'followup':'main',score:i===0?0:4,
   quote:i===0?'我们按日期留出完整的一周作为测试集，不把同一天的客流拆到两边。':'第 '+(i+1)+' 条合成作答。',source_page:i+2,source_excerpt:'各组使用相同的测试周，以平均绝对误差比较模型。',missing_points:i===0?['说明节假日是否进入测试集。']:[]})),
  disclaimer:'本报告用于答辩练习，不作为正式学业评价。'};
 let gets=0;
 const p=await fixture(t,'report/s/teacher',1440,(path,req)=>{
  if(path.endsWith('/s/report')){gets++;assert.equal(req.method(),'GET');assert.equal(req.headers()['x-campus-role'],'teacher');return report}
 });
 await p.getByText(report.title,{exact:true}).waitFor();await p.locator('#report-evidence article').first().waitFor();
 assert.equal(await p.getByRole('button',{name:'打印报告'}).isVisible(),true);
 assert.match(await p.locator('.report-ratings>div').filter({hasText:'可复现性'}).innerText(),/未评价/);
 const out=process.env.CAMPUS_REPORT_QA_DIR;if(out)await fs.mkdir(out,{recursive:true});
 for(const width of [1440,1024,768,390,320]){
  await p.setViewportSize({width,height:width>768?900:844});
  const layout=await p.evaluate(()=>{const col=document.querySelector('.report-spread>div').getBoundingClientRect(),aside=document.querySelector('.report-spread aside').getBoundingClientRect();
   return {fits:document.documentElement.scrollWidth<=innerWidth,stacked:aside.top>=col.bottom-1,inPage:getComputedStyle(document.querySelector('#report-body')).maxHeight==='none'}});
  assert.deepEqual(layout,{fits:true,stacked:width<=760,inPage:true});
  if(out&&[1440,390].includes(width))await p.screenshot({path:path.join(out,'report-'+width+'.png'),animations:'disabled'});
 }
 await p.getByRole('navigation',{name:'报告章节'}).getByRole('button',{name:'改进计划'}).click();
 assert.equal(await p.evaluate(()=>document.activeElement.id),'plan-heading');assert.equal(new URL(p.url()).hash,'#report/s/teacher');
 await action(p,'report-next').click();await p.getByText('第 6 条合成作答。',{exact:true}).waitFor();
 await p.locator('.report-source summary').click();await p.locator('#report-items .report-source[open]').waitFor();
 await p.evaluate(()=>{window.printCapture={};addEventListener('beforeprint',()=>{window.printCapture.rows=document.querySelectorAll('#report-items article').length;window.printCapture.closed=document.querySelectorAll('.report-page details:not([open])').length});});
 const pdf=await p.pdf({format:'A4',...(out?{path:path.join(out,'sample-report.pdf')}:{})});assert.equal(pdf.subarray(0,5).toString(),'%PDF-');
 assert.deepEqual(await p.evaluate(()=>window.printCapture),{rows:6,closed:0});
 assert.equal(await p.locator('#report-items article').count(),1);assert.equal(await p.locator('#report-items details[open]').count(),1);
 assert.equal(await p.locator('.report-disclosure[open]').count(),0);assert.equal(gets,1);
});
