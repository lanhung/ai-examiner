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
  vm.runInNewContext(fs.readFileSync(path.join(root,`pages/${name}/index.js`),'utf8'),{
    require:p=>p.includes('progress')?progress:api, Page:d=>{definition=d;},wx,setTimeout,clearTimeout,
  });
  definition.data=JSON.parse(JSON.stringify(definition.data));
  definition.setData=function(patch){Object.assign(this.data,patch);};
  return definition;
}
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
