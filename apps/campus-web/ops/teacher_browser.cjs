// Browser acceptance only against the throwaway loopback site created by casdao_acceptance.
'use strict';
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {createHash} = require('node:crypto');
const cfg = JSON.parse(fs.readFileSync(0, 'utf8'));
const origin = new URL(cfg.origin);
assert.equal(origin.hostname, '127.0.0.1');
assert.equal(origin.protocol, 'http:');
const exam = '合成水位研究 · 浏览器验收';
const material = [
  '合成研究：缺测率对水位插补误差的影响',
  '本研究使用模拟水位数据，不含任何真实测站或人员信息。将十二条时间序列按时间先后划为建模期和独立测试期。',
  '在测试期内分别遮盖百分之十、二十和三十的连续观测。用遮盖前保留的数值作为真值，比较线性插补和季节均值两种方法。',
  '在百分之十缺测时，两种方法的平均绝对误差分别为0.18米与0.26米；在百分之三十缺测时，分别为0.41米与0.39米。',
  '连续空档变长时，线性插补不能充分反映中间波动。所有参数仅在建模期选择；没有将测试期数据反馈给模型。',
  '研究局限是所有结果均来自合成序列；泛化到真实测站或极端洪水情景需要独立验证。'
].join('\n\n');
const answer = '我们按时间分开建模期与独立测试期，避免未来观测泄漏，再用被遮盖的真值计算平均绝对误差。在10%缺测时线性插补为0.18米、季节均值为0.26米；在30%时排序反转。合成样本不足以证明真实测站也有同样效果。';
const act = (p, name) => p.locator('[data-act="' + name + '"]');
const go = (p, hash) => p.goto(new URL('/#' + hash, origin).href);
const heading = (p, name) => p.getByRole('heading', {name, exact:true}).first().waitFor();
const fill = (p, name, value) => p.locator('[name="' + name + '"]').fill(value);
const pass = (name, detail) => console.log('PASS', name, detail ?? '');
let stage = 'launch';
const diag = [];
const issues = [];
const submissions={blueprint:0,answer:0};
function shortError(e) {
  return String(e.message || e.name).split('\n').slice(0,3).join(' ').replaceAll(cfg.password,'[redacted]').replaceAll(cfg.tunnel_key,'[redacted]').slice(0,320);
}
function monitor(p) {
  p.on('pageerror', e => diag.push('pageerror: ' + String(e.name)));
  p.on('request',r=>{
    if(r.method()!=='POST')return;
    const path=new URL(r.url()).pathname;
    if(path.endsWith('/blueprints/async'))submissions.blueprint++;
    if(path.endsWith('/answers/async'))submissions.answer++;
  });
  p.on('response', r => {
    const path = new URL(r.url()).pathname.replace(/[a-f\d-]{36}/ig, ':id');
    if(r.status() >= 400) diag.push(r.status() + ' ' + path);
  });
  p.setDefaultTimeout(22000);
}
async function watchTask(p,selector) {
  await p.locator(selector).waitFor();
  await p.evaluate(s=>{
    const anchor=document.querySelector(s);
    const probe={anchor,removed:false,loaders:0};
    probe.observer=new MutationObserver(records=>{
      for(const row of records){
        for(const node of row.removedNodes)if(node===anchor||node.contains(anchor))probe.removed=true;
        for(const node of row.addedNodes)if(node.textContent.trim()==='正在读取…')probe.loaders++;
      }
    });
    probe.observer.observe(document.querySelector('#content'),{childList:true,subtree:true});
    window.taskProbe=probe;
  },selector);
}
async function checkTask(p,selector){
  const result=await p.evaluate(s=>{
    const probe=window.taskProbe;probe.observer.disconnect();
    return {same:!probe.removed&&probe.anchor===document.querySelector(s),loaders:probe.loaders};
  },selector);
  assert.deepEqual(result,{same:true,loaders:0});
}
async function login(p, username) {
  await go(p, 'login');
  await fill(p, 'username', username);
  await fill(p, 'password', cfg.password);
  await act(p, 'login-account').click();
  await heading(p, '考试大厅');
  await p.locator('#identity').filter({hasNotText:'登录 / 注册'}).waitFor();
}
async function downloadOriginal(p, original) {
  const [file] = await Promise.all([p.waitForEvent('download',{timeout:12000}),p.getByRole('link',{name:'下载原文件'}).click()]);
  const failed=await file.failure();
  if(failed) throw new Error('Download failed: '+failed);
  const digest=x=>createHash('sha256').update(x).digest('hex');
  assert.equal(digest(fs.readFileSync(await file.path())),digest(Buffer.from(original)));
  pass('clicked browser download, original bytes match by SHA-256');
}
async function verifyLogout(p) {
  await p.locator('#identity').click(); await act(p,'logout').click();
  await p.locator('#identity').filter({hasText:'登录 / 注册'}).waitFor();
  await go(p,'records'); await p.locator('#content [data-act="login"]').waitFor();
  assert.equal(await p.locator('#content .score').count(),0);
  pass('logout, private records replaced by sign-in prompt');
}
async function compareBlueprints(p) {
  const documentId=await p.locator('#doc').inputValue();
  const norm=s=>s.normalize('NFKC').replace(/\s+/g,' ').trim();
  const sec=ms=>Number((ms/1000).toFixed(2));
  const checks=[];
  let previousJob;
  const sizes=cfg.speed_arm==='full'?[6]:cfg.speed_arm==='short'?[1]:[1,6];
  for(const size of sizes){
    assert.equal(await p.locator('#doc').inputValue(),documentId);
    // Only the short arm supplies an existing backend override; the control uses the shipped UI request.
    if(size===1) await p.route('**/blueprints/async',route=>{
      const body=route.request().postDataJSON();
      return route.continue({postData:JSON.stringify({...body,template_overrides:{question_limit:1}})});
    },{times:1});
    const before=submissions.blueprint;
    const start=performance.now();
    console.log('ARM start',size);
    const [terminal]=await Promise.all([
      p.waitForResponse(async res=>{
        const path=new URL(res.url()).pathname;
        const post=path.endsWith('/blueprints/async')&&res.request().method()==='POST';
        if(!post&&!path.includes('/api/v1/jobs/'))return false;
        if(!res.ok())return post;
        const j=await res.json().catch(()=>null);
        return j?.kind==='blueprint_generation'&&j.id!==previousJob&&
          ['completed','failed','dead_letter','cancelled','canceled'].includes(j.status);
      },{timeout:195000}),act(p,'blueprint').click()
    ]);
    assert.equal(terminal.ok(),true,'blueprint request HTTP '+terminal.status());
    const job=await terminal.json();
    if(job.status!=='completed'){
      const error=String(job.error||'').toLowerCase();
      console.log('BENCH_FAILED '+JSON.stringify({requested:size,seconds_to_terminal:sec(performance.now()-start),
        status:job.status,reason:job.terminal_reason,budget_error:error.includes('budget exhausted'),
        evidence_error:error.includes('grounding')||error.includes('source excerpt')}));
      throw new Error('Blueprint not publishable: '+job.status);
    }
    previousJob=job.id;
    const bp=job.result.blueprint, qs=bp.data.questions;
    await p.waitForFunction(n=>document.querySelectorAll('#blueprint-detail .intro').length===n&&
      document.querySelector('[data-act="publish"]:enabled'),qs.length);
    const ready=sec(performance.now()-start);
    const coverage=bp.template_plan?.coverage||bp.data.template_plan?.coverage||{};
    const result={requested:size,generated:qs.length,click_to_ready_s:ready,
      queue_s:job.started_at&&job.created_at?sec(Date.parse(job.started_at)-Date.parse(job.created_at)):null,
      verified_quotes:qs.filter(q=>Number(q.source_page)===1&&q.source_excerpt&&norm(material).includes(norm(q.source_excerpt))).length,
      rubric_counts:qs.map(q=>(q.expected_points||[]).filter(x=>typeof x==='string'&&x.trim()).length),
      chinese_questions:qs.filter(q=>/[\u3400-\u9fff]/u.test(q.text)).length,
      coverage:coverage.status,unmet:(coverage.unmet||[]).map(i=>i.objective_id),
      coverage_counts:coverage.counts,grounding:bp.grounding?.passed,model:bp.model};
    console.log('BENCH '+JSON.stringify(result));
    assert.equal(bp.model,'qwen-plus');assert.equal(submissions.blueprint-before,1);
    assert.equal(qs.length,size);assert.ok(result.rubric_counts.every(n=>n>0));
    checks.push(result.grounding===true&&result.verified_quotes===size&&result.chinese_questions===size);
    if(size===6)checks.push(coverage.status==='met');
    const title=exam+' · '+size;
    await act(p,'publish').click();
    for(const [k,v] of Object.entries({title,teacher_name:'验收教师',question_count:'1'}))await fill(p,k,v);
    await p.locator('#modalform [type="checkbox"]').check();
    const pubStart=performance.now();
    await act(p,'confirm-publish').click();await heading(p,'教师工作台');
    await p.locator('#paperrows').getByText(title,{exact:true}).waitFor();
    console.log('PUBLISH '+JSON.stringify({arm:size,published:1,click_to_list_s:sec(performance.now()-pubStart)}));
    if(size!==sizes.at(-1)){await act(p,'prepare').click();await heading(p,'准备考试');}
  }
  assert.ok(checks.every(Boolean),'See BENCH quality checks');
}
async function main() {
  const browser = await chromium.launch({headless:true, ...(cfg.browser_channel ? {channel:cfg.browser_channel} : {})});
  const ctx = () => browser.newContext({extraHTTPHeaders:{'X-Campus-Acceptance':cfg.tunnel_key},
    viewport:{width:1380,height:920}, locale:'zh-CN'});
  const t = await (await ctx()).newPage(), s = await (await ctx()).newPage();
  let active = t;
  monitor(t); monitor(s);
  try {
    stage = 'anonymous hall and student registration'; active = s;
    await go(s, 'hall'); await heading(s, '考试大厅');
    await act(s, 'sample').click(); await heading(s, '示例题目'); await act(s, 'dismiss').click();
    await go(s, 'register');
    for(const [k,v] of Object.entries({username:'accept_student',nickname:'验收学员',password:cfg.password,confirm_password:cfg.password}))
      await fill(s,k,v);
    await act(s, 'register-account').click();
    await heading(s, '欢迎回来'); await login(s, 'accept_student');
    assert.equal(await s.locator('#nav a[href="#teacher"]').count(),0);
    pass('anonymous sample, student registration/login, no teacher navigation');
    if(cfg.scope==='download') {
      stage='isolated download recheck';
      await s.locator('#paperdetail h2').filter({hasText:'材料下载验收'}).waitFor();
      await act(s,'material').click();
      await downloadOriginal(s,cfg.download_fixture);
      await act(s,'dismiss').click();
      stage='isolated logout recheck';
      await verifyLogout(s);
      assert.deepEqual(diag,[]);
      return;
    }
    stage = 'teacher login and role switch'; active = t;
    await login(t, 'accept_teacher'); await t.locator('#nav a[href="#teacher"]').click();
    await heading(t, '教师工作台'); await t.getByRole('link',{name:'考试大厅',exact:true}).click();
    await heading(t,'考试大厅'); await t.getByRole('link',{name:'教师工作台',exact:true}).click();
    await act(t,'prepare').click(); await heading(t,'准备考试');
    pass('teacher login, switch to student and return');
    stage = 'create project and upload material';
    await act(t,'new-project').click(); await fill(t,'name','合成水位缺测研究'); await act(t,'confirm-project').click();
    await t.locator('#project option:checked').filter({hasText:'合成水位缺测研究'}).waitFor({state:'attached'});
    await t.locator('#file').setInputFiles({name:'synthetic-defense.txt',mimeType:'text/plain',buffer:Buffer.from(material)});
    await act(t,'upload').click();
    await t.locator('#doc option:checked').filter({hasText:'synthetic-defense.txt'}).waitFor({state:'attached',timeout:90000});
    pass('project creation, material upload and async parsing');
    if(cfg.scope==='speed'){
      stage='short and default blueprint timings';await compareBlueprints(t);
      assert.deepEqual(diag,[]);return;
    }
    stage = 'qwen blueprint and refresh';
    await watchTask(t,'#file');const blueprintCount=submissions.blueprint;
    await act(t,'blueprint').click();
    await act(t,'publish').waitFor({timeout:160000});
    await checkTask(t,'#file');
    const questions=await t.locator('aside.detail .intro').allTextContents();assert.ok(questions.length>0);
    await t.reload(); await act(t,'publish').waitFor();
    await t.locator('aside.detail .intro').first().waitFor();
    assert.deepEqual(await t.locator('aside.detail .intro').allTextContents(), questions);
    assert.equal(submissions.blueprint-blueprintCount,1);
    pass('real Qwen blueprint, no full-page loader, identical questions after reload, one submission',questions.length);
    stage = 'publish';
    await act(t,'publish').click();
    for(const [k,v] of Object.entries({title:exam,teacher_name:'验收教师',question_count:'1',instructions:'仅用于临时库验收'})) await fill(t,k,v);
    await t.locator('#modalform [type="checkbox"]').check();
    await act(t,'confirm-publish').click(); await heading(t,'教师工作台');
    await t.locator('#paperdetail h2').filter({hasText:exam}).waitFor();
    pass('publish one-question exam');
    stage = 'student catalog and material'; active = s;
    await s.reload(); await heading(s,'考试大厅');
    await s.locator('#paperdetail h2').filter({hasText:exam}).waitFor();
    pass('student catalog shows newly published exam'); stage='material dialog';
    await act(s,'material').click(); await heading(s,'考试材料');
    assert.ok((await s.locator('#dialog .reading').innerText()).includes('0.18'));
    pass('student material preview contains source measurement'); stage='material download';
    try {
      await downloadOriginal(s,material);
    } catch(e) {
      issues.push(stage+': '+shortError(e)); console.log('ISSUE',issues.at(-1));
      const url=await s.getByRole('link',{name:'下载原文件'}).getAttribute('href');
      const res=await s.request.get(new URL(url,origin).href);
      console.log('DOWNLOAD-CHECK',res.status(),(await res.body()).equals(Buffer.from(material)));
    }
    await act(s,'dismiss').click();
    if(cfg.scope!=='feedback'){
      stage = 'teacher preview'; active = t;
      await act(t,'preview').click(); await fill(t,'answer',answer); await act(t,'submit-answer').click();
      await t.locator('.score').waitFor({timeout:110000});
      const previewScore = Number(await t.locator('.score').innerText());
      assert.ok(Number.isFinite(previewScore) && previewScore>=0 && previewScore<=100);
      await t.locator('#nav a[href="#teacher"]').click();
      pass('teacher trial graded',previewScore);
    }
    await act(t,'grades').click();
    await t.getByText('正式答卷 0 份，教师试答不计入成绩。',{exact:true}).waitFor();
    stage = 'student submits'; active = s;
    await act(s,'join').click(); await fill(s,'student_name','合成学员'); await fill(s,'student_number','TEST-001');
    await s.locator('#modalform [type="checkbox"]').check(); await act(s,'confirm-join').click();
    await fill(s,'answer',answer);await watchTask(s,'#attempt-progress');const answerCount=submissions.answer;
    await act(s,'submit-answer').click();
    await s.locator('.score').waitFor({timeout:110000});
    await checkTask(s,'#attempt-progress');assert.equal(submissions.answer-answerCount,1);
    const studentScore=Number(await s.locator('.score').innerText());
    assert.ok(studentScore>=0&&studentScore<=100&&Number.isFinite(studentScore));
    pass('real Qwen score, no full-page loader, one answer submission',studentScore);
    stage = 'teacher grade and review'; active=t;
    await t.reload(); await t.getByText('正式答卷 1 份，教师试答不计入成绩。',{exact:true}).waitFor();
    const row=t.locator('.line').filter({hasText:'TEST-001'});
    assert.equal(Number(await row.locator('strong').innerText()),studentScore);
    if(cfg.scope==='feedback'){
      assert.deepEqual(diag,[]);assert.deepEqual(issues,[]);
      pass('teacher received the same score, no browser errors');return;
    }
    await row.getByRole('link',{name:'查看 / 复核'}).click();
    await fill(t,'score','83.5'); await fill(t,'note','合成验收：需补充时段划分的依据。'); await act(t,'review-score').click();
    await t.locator('.score').filter({hasText:'83.5'}).waitFor();
    await s.locator('#nav a[href="#records"]').click(); await heading(s,'我的答卷');
    await s.getByRole('link',{name:'查看答卷'}).click(); await s.locator('.score').filter({hasText:'83.5'}).waitFor();
    assert.ok((await s.locator('#content').innerText()).includes('需补充时段划分的依据'));
    pass('same grade on both sides, teacher review score and note visible to student',83.5);
    stage='close admissions';
    await t.locator('#nav a[href="#teacher"]').click(); await act(t,'close-exam').click(); await act(t,'confirm-close').click();
    await t.locator('#paperrows .pill').filter({hasText:'已关闭'}).waitFor();
    await s.reload(); await s.locator('.score').filter({hasText:'83.5'}).waitFor();
    pass('close admissions, existing student retains result');
    stage='personal defense workspace';
    await t.getByRole('link',{name:'教师个人答辩'}).click(); await heading(t,'个人答辩');
    await act(t,'start-session').click(); await act(t,'begin-session').click();
    await t.locator('#session-answer').waitFor({timeout:90000}); await t.locator('#session-answer').fill(answer);
    await act(t,'session-answer').click();
    await t.getByRole('heading',{name:'我的回答',exact:true}).first().waitFor({timeout:100000});
    pass('personal defense, first question and first answer recorded');
    stage='logout'; active=s;
    await verifyLogout(s);
    assert.deepEqual(diag, []);
    pass('no browser script or HTTP errors during happy path');
    if(issues.length) throw new Error(issues.join('; '));
  } catch(e) {
    console.error('FAILED STAGE:',stage,shortError(e));
    console.error('Browser:',diag.slice(-8).join('; '));
    const visible=await active.locator('#content .alert, #toast, #dialog .action-error, [role="status"]').allTextContents().catch(()=>[]);
    console.error('Feedback:',visible.filter(Boolean).map(x=>x.slice(0,220)).join('; '));
    console.error('Location:',new URL(active.url()).hash.split('/')[0]);
    throw new Error('Browser acceptance stopped at: '+stage);
  } finally { await browser.close(); }
}
main().catch(e=>{console.error(e.message);process.exitCode=1});
