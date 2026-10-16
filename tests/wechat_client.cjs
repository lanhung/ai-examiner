const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../apps/wechat/miniprogram');

function harness() {
  const storage = new Map();
  const app={globalData:{me:{principal:{id:'p'}}}};
  const calls=[];
  const wx={
    getStorageSync:key=>storage.get(key), setStorageSync:(k,v)=>storage.set(k,v),
    removeStorageSync:k=>storage.delete(k), reLaunch:o=>calls.push(o),
    request:o=>{calls.push(o);o.success({statusCode:200,data:{ok:true}});},
    uploadFile:o=>{calls.push(o);o.success({statusCode:200,data:'{"id":"doc"}'});}
  };
  const module={exports:{}};
  const config={apiBase:'https://api.example.test'};
  vm.runInNewContext(fs.readFileSync(path.join(root,'lib/api.js'),'utf8'),{module,wx,getApp:()=>app,require:()=>config});
  return {api:module.exports,wx,storage,calls,app,config};
}
test('request pins origin, adds server-issued token and organization',async()=>{
  const h=harness();h.storage.set(h.api.TOKEN,'wxmp_test');h.storage.set(h.api.ORG,'org-a');
  await h.api.request('/api/projects');
  assert.equal(h.calls[0].url,'https://api.example.test/api/projects');
  assert.equal(h.calls[0].header.Authorization,'Bearer wxmp_test');
  assert.equal(h.calls[0].header['X-AI-Examiner-Organization'],'org-a');
});
test('refuses third-party, traversal and non-HTTPS URLs without a request',async()=>{
  const h=harness();h.storage.set(h.api.TOKEN,'wxmp_test');
  for(const p of ['https://evil.test/api/me','//evil.test/api/me','/api/../private']) await assert.rejects(h.api.request(p));
  h.config.apiBase='http://api.example.test';await assert.rejects(h.api.request('/api/projects'));
  assert.equal(h.calls.length,0);
});
test('login never attaches prior identity; upload decodes JSON exactly once',async()=>{
  const h=harness();h.storage.set(h.api.TOKEN,'wxmp_test');
  await h.api.request('/api/v1/wechat/login','POST',{code:'test'},{auth:false});
  assert.equal(h.calls[0].header.Authorization,undefined);
  const result=await h.api.upload('p','/tmp/file');assert.equal(result.id,'doc');
  assert.equal(h.calls[1].name,'file');
});
test('401 clears identity and redirects; 403 preserves session',async()=>{
  const h=harness();h.storage.set(h.api.TOKEN,'wxmp_test');h.storage.set(h.api.ORG,'org');
  h.wx.request=o=>o.success({statusCode:403,data:{detail:{message:'denied'}}});
  await assert.rejects(h.api.request('/api/projects'),/denied/);assert(h.storage.has(h.api.TOKEN));
  h.wx.request=o=>o.success({statusCode:401,data:{}});
  await assert.rejects(h.api.request('/api/projects'));assert.equal(h.storage.size,0);assert.equal(h.app.globalData.me,null);
  assert.equal(h.calls[0].url,'/pages/login/index');
});
test('network failures do not automatically retry a mutation',async()=>{
  const h=harness();h.storage.set(h.api.TOKEN,'wxmp_test');let count=0;
  h.wx.request=o=>{count++;o.fail({});};
  await assert.rejects(h.api.request('/api/sessions/x/answers','POST',{answer:'a'}),/不要重复提交/);
  assert.equal(count,1);
});
test('network failures classify domain, TLS and timeout without echoing raw details',async()=>{
  const h=harness();h.storage.set(h.api.TOKEN,'wxmp_test');
  for(const [errMsg,expected] of [
    ['request:fail url not in domain list',/合法域名/],
    ['request:fail ssl hand shake error',/证书/],
    ['request:fail timeout',/连接超时/],
  ]) {
    h.wx.request=o=>o.fail({errMsg});
    await assert.rejects(h.api.request('/api/projects'),expected);
  }
  h.wx.uploadFile=o=>o.fail({errMsg:'uploadFile:fail url not in domain list'});
  await assert.rejects(h.api.upload('p','/tmp/file'),/合法域名/);
  h.wx.request=o=>o.fail({errMsg:'unknown failure sensitive-token'});
  await assert.rejects(h.api.request('/api/projects'),e=>!e.message.includes('sensitive-token'));
  h.wx.request=o=>o.fail({errMsg:'request:fail timeout'});
  await assert.rejects(h.api.request('/api/sessions/x/answers','POST',{}),/不要重复提交/);
});

function page(name, api, wx = {}, progress = {save:()=>{},read:()=>({}),reset:()=>{}}) {
  let definition;
  const app={globalData:{me:null}};
  vm.runInNewContext(fs.readFileSync(path.join(root,`pages/${name}/index.js`),'utf8'),{
    require:p=>p.includes('progress')?progress:p.includes('school')?{...api,id:()=> 'test-request-id',label:x=>x}:api, Page:d=>{definition=d;},wx,setTimeout,clearTimeout,
    getApp:()=>app,
  });
  definition.data=JSON.parse(JSON.stringify(definition.data));
  definition.setData=function(patch){Object.assign(this.data,patch);};
  return definition;
}

test('teacher can switch to student hall and back without changing identity or grants',async()=>{
  const calls=[],navigations=[];
  const p=page('school',{request:async(path,method='GET')=>{
    calls.push({path,method});
    if(path==='/api/v1/me')return {principal:{id:'teacher-account'}};
    if(path==='/me')return {principal_id:'teacher-account',teacher:true,teacher_organization_id:'teaching-org'};
    if(path==='/exams?offset=0')return [{id:'public-exam'}];
    if(path==='/teacher/exams?offset=0')return [{id:'owned-exam'}];
    throw new Error(`Unexpected request: ${path}`);
  }},{navigateTo:options=>navigations.push(options.url)});
  await p.load();
  assert.equal(p.data.mode,'student');assert.equal(p.data.teacher,true);
  for(const [mode,examId,teacherFlag] of [
    ['teacher','owned-exam',1],['student','public-exam',0],['teacher','owned-exam',1],
  ]) {
    p.mode({currentTarget:{dataset:{mode}}});
    assert.equal(p.data.exams.length,0);
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(p.data.error,'');assert.equal(p.data.mode,mode);
    assert.equal(p.data.teacher,true);assert.equal(p.data.principalId,'teacher-account');
    assert.equal(p.teacherOrg,'teaching-org');assert.equal(p.data.exams[0].id,examId);
    p.open({currentTarget:{dataset:{id:examId}}});
    assert.equal(navigations.at(-1),`/pages/exam/index?id=${examId}&teacher=${teacherFlag}`);
  }
  assert(calls.every(call=>call.method==='GET'));
  const wxml=fs.readFileSync(path.join(root,'pages/school/index.wxml'),'utf8');
  assert.match(wxml,/wx:if="\{\{teacher\}\}"/);
  for(const mode of ['student','teacher'])assert(wxml.includes(`data-mode="${mode}" bindtap="mode"`));
});

test('student cannot switch to teacher mode or prepare teacher materials',()=>{
  let requests=0,navigations=0;
  const p=page('school',{request:async()=>{requests++;}},{navigateTo:()=>{navigations++;}});
  p.mode({currentTarget:{dataset:{mode:'teacher'}}});p.prepare();
  assert.equal(p.data.mode,'student');assert.equal(requests,0);assert.equal(navigations,0);
});

test('revoked teacher returns to student hall when server identity refreshes',async()=>{
  const paths=[];
  const p=page('school',{request:async path=>{
    paths.push(path);
    if(path==='/api/v1/me')return {principal:{id:'account'}};
    if(path==='/me')return {principal_id:'account',teacher:false,teacher_organization_id:null};
    if(path==='/exams?offset=0')return [{id:'public-exam'}];
    throw new Error(`Unexpected request: ${path}`);
  }});
  p.setData({teacher:true,mode:'teacher',exams:[{id:'previous-teacher-list'}]});
  await p.load();
  assert.equal(p.data.error,'');assert.equal(p.data.teacher,false);assert.equal(p.data.mode,'student');
  assert.equal(p.data.exams[0].id,'public-exam');assert.equal(p.teacherOrg,null);
  assert(!paths.some(path=>path.startsWith('/teacher/')));
});

test('exam answer retry reuses request id, original text and question position',async()=>{
  const calls=[];
  const p=page('exam-answer',{request:async(path,method,data)=>{
    calls.push({path,method,data});
    if(calls.length===1)throw new Error('network timeout');
    return {status:'active',position:1,answers:[]};
  }});
  p.setData({id:'attempt',attempt:{status:'active',position:0},answer:'Original answer'});
  await p.submit();assert.equal(p.data.uncertain,true);
  await p.submit();assert.equal(calls.length,1);
  p.setData({answer:'Changed text',uncertain:false});await p.submit();
  assert.equal(calls[0].data.request_id,calls[1].data.request_id);
  assert.equal(calls[1].data.answer,'Original answer');
  assert.equal(calls[1].data.position,0);assert.equal(p.data.answer,'');
});

test('exam refresh clears uncertain submission only after server advances',async()=>{
  let state={status:'active',position:0};
  const p=page('exam-answer',{request:async()=>state});
  p.pending={position:0,request_id:'r'};p.setData({id:'a',uncertain:true,answer:'Draft'});
  await p.refresh();assert.equal(p.data.uncertain,true);assert.equal(p.data.answer,'Draft');
  state={status:'active',position:1};await p.refresh();
  assert.equal(p.data.uncertain,false);assert.equal(p.data.answer,'');assert.equal(p.pending,null);
});

test('student exam page cannot submit using teacher view or while grading',async()=>{
  let calls=0;
  const p=page('exam-answer',{request:async()=>{calls++;}});
  p.setData({teacher:true,attempt:{status:'active',position:0},answer:'A'});await p.submit();
  p.setData({teacher:false,attempt:{status:'grading',position:0}});await p.submit();
  assert.equal(calls,0);
});

test('student consent and name required before joining an exam',async()=>{
  let calls=0;
  const p=page('exam',{request:async()=>{calls++;return {id:'a'};}},{navigateTo:()=>{}});
  p.setData({id:'exam'});p.join();await new Promise(r=>setImmediate(r));
  assert.equal(calls,0);p.setData({name:'Student',consent:true});p.join();
  await new Promise(r=>setImmediate(r));assert.equal(calls,1);
});

test('exam owner uses preview route instead of formal enrollment',async()=>{
  const calls=[],urls=[];
  const p=page('exam',{request:async(path,method)=>{calls.push({path,method});return {id:'preview-a'};}},
    {navigateTo:o=>urls.push(o.url)});
  p.setData({id:'exam',exam:{is_owner:true},name:'Teacher',consent:true});
  p.join();await new Promise(r=>setImmediate(r));assert.equal(calls.length,0);
  assert.match(p.data.error,/教师试答/);
  await p.preview();assert.equal(calls[0].path,'/teacher/exams/exam/preview');
  assert.equal(urls[0],'/pages/exam-answer/index?id=preview-a&preview=1');
  p.setData({exam:{is_owner:false}});await p.preview();assert.equal(calls.length,1);
  const wxml=fs.readFileSync(path.join(root,'pages/exam/index.wxml'),'utf8');
  assert(wxml.includes('wx:elif="{{!exam.is_owner}}"'));
  assert(wxml.includes('教师试答 · 不计入学生成绩'));
});

test('preview submits and retries in isolated teacher namespace',async()=>{
  const calls=[];
  const p=page('exam-answer',{request:async(path,method,data)=>{
    calls.push({path,method,data});
    if(method==='POST'&&calls.length===2)throw new Error('timeout');
    return {status:'active',position:0,is_preview:true,answers:[]};
  }});
  p.onLoad({id:'preview-a',preview:'1',teacher:'1'});await new Promise(r=>setImmediate(r));
  assert.equal(p.data.teacher,false);assert.equal(p.endpoint(),'/teacher/previews/preview-a');
  p.setData({answer:'Synthetic answer'});await p.submit();assert.equal(p.data.uncertain,true);
  p.retry();await new Promise(r=>setImmediate(r));
  assert(calls.every(c=>c.path.startsWith('/teacher/previews/')));
  assert.equal(calls[1].data.request_id,calls[2].data.request_id);
  assert.equal(calls[1].data.answer,calls[2].data.answer);
});

test('teacher refresh keeps preview result separate from formal grade list',async()=>{
  const p=page('exam',{request:async path=>{
    if(path==='/teacher/exams/e')return {id:'e',is_owner:true};
    if(path==='/teacher/exams/e/grades?offset=0')return [];
    if(path==='/teacher/exams/e/preview')return {id:'p',is_preview:true,final_score:88};
    throw new Error(path);
  }});
  p.setData({id:'e',teacher:true});await p.refresh();
  assert.equal(p.data.error,'');assert.equal(p.data.grades.length,0);
  assert.equal(p.data.preview.final_score,88);
});

test('original document download stays on authenticated API origin',async()=>{
  const h=harness();h.storage.set(h.api.TOKEN,'wxmp_test');
  h.wx.downloadFile=o=>{assert.equal(o.header.Authorization,'Bearer wxmp_test');assert(o.url.startsWith(h.config.apiBase));o.success({statusCode:200,tempFilePath:'/tmp/doc'});};
  h.wx.openDocument=o=>{assert.equal(o.fileType,'docx');assert.equal(o.showMenu,false);o.success({});};
  await h.api.openDocument('/api/v1/school/exams/e/material','docx');
  await assert.rejects(h.api.openDocument('/api/v1/school/exams/e/material','exe'));
});

test('completed blueprint unlocks teacher material controls',async()=>{
  const p=page('work',{request:async()=>({status:'completed',result:{blueprint:{id:'b'}}})});
  p.visible=true;p.setData({job:{id:'j'}});await p.poll();
  assert.equal(p.data.job,null);assert.equal(p.data.blueprint.id,'b');
});

test('stale blueprint errors do not pollute a different project',async()=>{
  let fail;
  const p=page('work',{request:()=>new Promise((_,reject)=>{fail=reject;})});
  p.visible=true;p.setData({job:{id:'old'}});const pending=p.poll();
  p.generation=1;p.setData({job:null});fail(new Error('old failure'));await pending;
  assert.equal(p.data.error,'');
});
test('uncertain answer blocks resubmit until a later assistant turn arrives',async()=>{
  let count=0;
  const p=page('session',{request:async()=>{count++;throw new Error('timeout');}});
  p.setData({id:'s',turns:[{role:'assistant'}],answer:'answer'});
  await p.submit();assert.equal(p.data.uncertain,true);
  await p.submit();assert.equal(count,1);
});

test('upload preserves original filename, reports progress and never retries',async()=>{
  const h=harness();h.storage.set(h.api.TOKEN,'wxmp_test');let count=0, progress=0;
  h.wx.uploadFile=o=>{count++;assert.equal(o.formData.original_filename,'defense.docx');return {onProgressUpdate:cb=>{cb({progress:100});o.fail({errMsg:'uploadFile:fail timeout'});}};};
  await assert.rejects(h.api.upload('p','/tmp/random',{filename:'defense.docx',onProgress:r=>{progress=r.progress;}}),e=>e.uncertain===true);
  assert.equal(count,1);assert.equal(progress,100);
  h.wx.uploadFile=o=>o.success({statusCode:503,data:'{}'});
  await assert.rejects(h.api.upload('p','/tmp/random'),e=>e.uncertain===true);
  h.wx.uploadFile=o=>o.success({statusCode:400,data:'{"detail":"invalid file"}'});
  await assert.rejects(h.api.upload('p','/tmp/random'),e=>e.uncertain===false);
});

test('timed out upload can recover an existing document without another POST',async()=>{
  let uploads=0, saved={};
  const doc={id:'d',filename:'defense.docx',page_count:1};
  const p=page('work',{
    upload:async()=>{uploads++;const e=new Error('timeout');e.uncertain=true;throw e;},
    request:async(path,method='GET')=>{assert.equal(method,'GET');return [doc];},
  },{chooseMessageFile:o=>o.success({tempFiles:[{path:'/tmp/f',name:'defense.docx',size:1024}]})},
  {save:d=>Object.assign(saved,d),read:()=>saved});
  p.setData({projects:[{id:'p'}]});
  await p.upload();assert.equal(p.data.uploadUncertain,true);assert.equal(saved.uploadUncertain,true);
  assert.equal(p.data.documents[0].id,'d');
  await p.upload();assert.equal(uploads,1);
  p.selectDocument();assert.equal(p.data.document.id,'d');assert.equal(p.data.uploadUncertain,false);
  assert.equal(saved.documentId,'d');assert.equal(saved.uploadUncertain,false);
});

test('empty reconciliation does not claim success or silently allow retry',async()=>{
  const p=page('work',{request:async()=>[]});
  p.setData({projects:[{id:'p'}],uploadUncertain:true});
  await p.refreshDocuments();assert.equal(p.data.uploadUncertain,true);
  assert.equal(p.data.document,null);assert.match(p.data.uploadMessage,/仍在处理/);
});

test('document list response cannot cross project boundaries after a switch',async()=>{
  let complete;
  const p=page('work',{request:()=>new Promise(resolve=>{complete=resolve;})});
  p.setData({projects:[{id:'a'},{id:'b'}]});
  const pending=p.loadDocuments();p.generation=1;p.setData({projectIndex:1});
  complete([{id:'private-a'}]);await pending;assert.equal(p.data.documents.length,0);
});

test('upload success clears stale session; known rejection permits corrected upload',async()=>{
  let saved={};
  const api={upload:async()=>({id:'new',filename:'paper.docx'})};
  const wx={chooseMessageFile:o=>o.success({tempFiles:[{path:'/tmp/f',name:'paper.docx',size:50}]})};
  const p=page('work',api,wx,{save:d=>Object.assign(saved,d),read:()=>saved});
  p.setData({projects:[{id:'p'}],sessionId:'old',blueprint:{id:'old'}});
  await p.upload();assert.equal(p.data.document.id,'new');assert.equal(p.data.sessionId,'');
  assert.equal(p.data.blueprint,null);assert.equal(saved.uploadUncertain,false);
  api.upload=async()=>{const e=new Error('invalid file');e.uncertain=false;throw e;};
  await p.upload();assert.equal(p.data.uploadUncertain,false);assert.equal(p.data.error,'invalid file');
});

test('resume restores uncertain upload and discovers server-saved materials',async()=>{
  const saved={projectId:'p',uploadUncertain:true};
  const p=page('work',{request:async()=>[{id:'d',filename:'paper.docx'}]}, {},{read:()=>saved});
  p.setData({projects:[{id:'p'}]});await p.restore();
  assert.equal(p.data.uploadUncertain,true);assert.equal(p.data.documents.length,1);
  assert.equal(p.data.document,null);
});
test('all page routes and JSON configs exist; no mock listed as fallback',()=>{
  const config=JSON.parse(fs.readFileSync(path.join(root,'app.json')));
  for(const route of config.pages){assert(fs.existsSync(path.join(root,route+'.js')));assert(fs.existsSync(path.join(root,route+'.wxml')));}
  const source=fs.readFileSync(path.join(root,'pages/work/index.js'),'utf8');
  assert(source.includes("p.provider!=='mock'"));
});
test('resume pointers are principal/org scoped and exclude answer content',()=>{
  const h=harness();h.storage.set(h.api.ORG,'org-a');
  const module={exports:{}};
  vm.runInNewContext(fs.readFileSync(path.join(root,'lib/progress.js'),'utf8'),{module,require:()=>h.api,wx:h.wx,getApp:()=>h.app});
  const progress=module.exports;
  progress.save({sessionId:'session-a',answer:'private answer',pending:true,beforeSend:3});
  assert.equal(progress.read().sessionId,'session-a');assert.equal(progress.read().answer,undefined);
  h.storage.set(h.api.ORG,'org-b');assert.equal(progress.read().sessionId,undefined);
  h.storage.set(h.api.ORG,'org-a');h.app.globalData.me.principal.id='other-person';
  assert.equal(progress.read().sessionId,undefined);
});
test('WXML conditions use operators, not HTML-escaped JavaScript',()=>{
  const config=JSON.parse(fs.readFileSync(path.join(root,'app.json')));
  for(const route of config.pages){
    const wxml=fs.readFileSync(path.join(root,route+'.wxml'),'utf8');
    assert(!/\{\{[^}]*&amp;/.test(wxml),route);
  }
});
test('login preflight refuses missing credentials and catches transport errors',async()=>{
  const p=page('login',{request:async()=>({state:'missing_credentials',login_available:false})});
  await p.checkService();assert.equal(p.data.loginAvailable,false);assert.match(p.data.serviceStatus,/凭据/);
  const failed=page('login',{request:async()=>{throw new Error('offline');}});
  await failed.checkService();assert.equal(failed.data.loginAvailable,false);assert.equal(failed.data.error,'offline');
});
test('registration hint follows server mode and clears on failed preflight',async()=>{
  const api={request:async()=>({state:'ready',login_available:true,registration_mode:'personal'})};
  const p=page('login',api);
  await p.checkService();assert.equal(p.data.registrationMode,'personal');
  api.request=async()=>({state:'ready',login_available:true,registration_mode:'approval'});
  await p.checkService();assert.equal(p.data.registrationMode,'approval');
  api.request=async()=>{throw new Error('offline');};
  await p.checkService();assert.equal(p.data.registrationMode,'');assert.equal(p.data.loginAvailable,false);
});
