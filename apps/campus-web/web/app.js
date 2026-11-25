'use strict';
const $=s=>document.querySelector(s), main=$('#content'),dlg=$('#dialog');
const E=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon=n=>'<img class="ico" alt="" src="/icons/'+n+'.svg">';
const button=(text,act,kind='secondary',sym='')=>'<button type="button" class="'+kind+'" data-act="'+act+'">'+(sym?icon(sym):'')+E(text)+'</button>';
const g='/gateway/api', school=g+'/v1/school', fixed='qwen:qwen-plus', uid=()=>crypto.randomUUID();
const labels={sample:'示例',published:'开放中',closed:'已关闭',active:'作答中',grading:'评分中',completed:'已完成',needs_review:'待复核',created:'待开始'};
const tag=v=>'<span class="pill '+(['grading','needs_review'].includes(v)?'amber':v==='closed'?'gray':'')+'">'+E(labels[v]||v)+'</span>';
const st={user:null,view:'hall',role:'student',items:[],sel:null,d:null,filter:'all',search:'',offset:0,more:false,answers:{},work:{},session:null,epoch:0};
let poll,flashTimer,screenKey='',screenHash='',resumeReport='';
const personalLink=(view,id,role)=>'#'+view+'/'+encodeURIComponent(id)+'/'+role;
const validReportAddress=(id,role)=>typeof id==='string'&&/^[a-zA-Z0-9_-]{1,80}$/.test(id)&&['student','teacher'].includes(role);
const failedJob=s=>['failed','dead_letter','cancelled','canceled'].includes(s);
const samePage=ep=>st.epoch===ep&&screenHash===location.hash;
const statusLine='<p id="task-status" class="task-status" role="status" aria-live="polite" aria-atomic="true"></p>';
function tell(text,kind=''){
 const el=$('#task-status');if(!el)return;
 if(el.textContent!==text)el.textContent=text;
 el.dataset.kind=kind;
}
// Keep live form controls, focus and selection when a receipt hasn't changed.
function part(selector,html){
 const el=$(selector);if(el._rendered!==html){el.innerHTML=html;el._rendered=html}
}
function pageError(e){
 clearTimeout(poll);st.current=null;st.session=null;
 main.innerHTML='<p class="alert">'+E(errorText(e))+'</p>'+button('重新读取','refresh','linkbtn');
}
function transient(e){return !e.status||e.status>=500||[408,429].includes(e.status)}
function later(ep,read,delay=2800){
 if(!samePage(ep))return;
 clearTimeout(poll);
 poll=setTimeout(async()=>{
  if(!samePage(ep))return;
  try{await read()}catch(e){
   if(!samePage(ep))return;
   if(!transient(e)){pageError(e);return}
   tell('暂时查不到进度，正在重试。不会重复提交。','notice');
   later(ep,read,Math.min(15000,delay*2));
  }
 },delay);
}
function flash(s){$('#toast').textContent=s;clearTimeout(flashTimer);flashTimer=setTimeout(()=>$('#toast').textContent='',7500)}
function errorText(e){return e.message||'操作未完成，请稍后重试'}
async function api(path,method='GET',data,headers={},signal){
 const actor=st.user,h={'X-Campus-Request':'1','X-Campus-Role':st.role,...headers};
 if(data!==undefined && !(data instanceof FormData)) h['Content-Type']='application/json';
 const r=await fetch(path,{method,headers:h,body:data===undefined?undefined:data instanceof FormData?data:JSON.stringify(data),cache:'no-store',credentials:'same-origin',signal});
 const raw=await r.text(); let v;try{v=JSON.parse(raw)}catch{v={}}
 if(!r.ok){if(r.status===401 && actor && actor===st.user){st.user=null;st.work={};st.answers={};st.current=null;st.session=null;st.items=[];if(st.view!=='report')location.hash='hall';setTimeout(route,0)}
 const detail=v.detail;const err=Error(typeof detail==='string'?detail:detail?.message||'请求未成功（'+r.status+'）');err.status=r.status;throw err}
 return v;
}
async function timedApi(path,method='GET',data,controller=new AbortController(),timeout=15000){
 const timer=setTimeout(()=>controller.abort(),timeout);
 try{return await api(path,method,data,{},controller.signal)}
 catch(e){if(e.name==='AbortError')throw Object.assign(Error('请求超时'),{status:408});throw e}
 finally{clearTimeout(timer)}
}
const navNames={hall:'考试大厅',records:'我的答卷',work:'个人答辩',teacher:'教师工作台'};
function frame(active){$('#nav').innerHTML=Object.entries(navNames).filter(([k])=>k!=='teacher'||st.user?.teacher).map(([k,v])=>'<a href="#'+k+'" class="'+(active===k?'on':'')+'" '+(active===k?'aria-current="page"':'')+'>'+v+'</a>').join('');
 $('#identity').innerHTML='<span class="avatar">'+icon('user-round')+'</span>'+(st.user?E(st.user.nickname||st.user.username||'我的账号'):'登录 / 注册')+icon('chevron-down')}
function lead(k,title,sub,action=''){return '<div class="crumb">'+icon('library')+' 答辩学堂 <span>/</span> '+E(k)+'</div><div class="titlebar"><div><h1>'+E(title)+'</h1><p>'+E(sub)+'</p></div>'+action+'</div>'}
function empty(t){return '<div class="empty"><p>'+E(t)+'</p></div>'}
function modal(title,body){dlg.innerHTML='<div class="split"><h2 id="dialog-title">'+E(title)+'</h2><button type="button" class="iconbtn" title="关闭" aria-label="关闭" data-act="dismiss">'+icon('x')+'</button></div>'+body;if(!dlg.open)dlg.showModal()}
async function login(){
 if(st.user){modal('当前账号','<p class="reading">'+E(st.user.nickname||st.user.username)+'<br>账号：'+E(st.user.username)+'<br>'+(st.user.teacher?'教师身份已开通，可切换学生端。':'学生身份，个人材料独立保存。')+'</p><div class="actions mt">'+button('退出登录','logout')+'</div>');return}
 if(dlg.open)dlg.close();location.hash='login';
}
function authPage(register){
 main.innerHTML='<div class="auth-layout"><section class="auth-heading"><img src="/brand.svg" width="52" height="52" alt=""><h1>'+ (register?'创建你的账号':'欢迎回来')+'</h1><p>答辩学堂 · AI Examiner</p><a class="linkbtn" href="#hall">'+icon('arrow-left')+'返回考试大厅</a></section>'+
 '<section class="auth-panel"><nav class="auth-tabs" aria-label="账号入口"><a href="#login" '+(!register?'aria-current="page"':'')+'>账号登录</a><a href="#register" '+(register?'aria-current="page"':'')+'>注册账号</a></nav>'+
 '<form id="authform" class="form"><label>用户名<input name="username" autocomplete="username" minlength="3" maxlength="32" pattern="[A-Za-z0-9_]+" autocapitalize="none" spellcheck="false" placeholder="3–32 位字母、数字或下划线" required></label>'+
 (register?'<label>显示名称<input name="nickname" autocomplete="nickname" maxlength="40" placeholder="你的姓名或昵称" required></label>':'')+
 '<label>密码<input type="password" name="password" autocomplete="'+(register?'new-password':'current-password')+'" minlength="'+(register?'12':'1')+'" maxlength="128" '+(register?'placeholder="至少 12 位，建议使用长密码"':'')+' required></label>'+
 (register?'<label>确认密码<input type="password" name="confirm_password" autocomplete="new-password" minlength="12" maxlength="128" required></label><p class="small">新账号默认是学生。教师权限由管理员开通；不会自动关联微信账号的历史数据。</p>':'')+
 '<p id="auth-error" class="alert" role="alert" hidden></p><div>'+button(register?'注册账号':'登录',register?'register-account':'login-account','primary','arrow-right')+'</div></form>'+
 (!register?'<p class="small mt">忘记密码请联系管理员核验后重置。</p>':'')+'</section></div>';
}
function metrics(a){return '<div class="stats">'+a.map(([n,t,i])=>'<div class="stat"><span class="sym">'+icon(i)+'</span><strong>'+E(n)+'</strong><small>'+E(t)+'</small></div>').join('')+'</div>'}
function listRows(){const t=st.view==='teacher';
 const filtered=st.items.filter(e=>(st.filter==='all'||(st.filter==='open'?e.status==='published'||e.status==='sample':!!e.attempt_id))&&[e.title,e.teacher_name,e.material_name].join(' ').toLowerCase().includes(st.search.toLowerCase()));
 $('#paperrows').innerHTML=(filtered.map(e=>'<button class="paper '+(st.sel===e.id?'selected':'')+'" data-act="select" data-id="'+E(e.id)+'" aria-pressed="'+(st.sel===e.id)+'"><div class="split"><span class="tag">'+E(e.subject||'论文答辩')+'</span>'+tag(e.attempt_status||e.status)+'</div><h3>'+E(e.title)+'</h3><div class="meta"><span>'+icon('user-round')+E(e.teacher_name)+'</span><span>'+icon('list-checks')+E(e.question_count)+' 道题</span></div></button>').join('')||empty(t?'暂无符合条件的考试':'没有符合条件的考试'))+(st.more?button('加载更多','more'):'');
}
function detail(){const e=st.d;
 if(!e)return empty('从列表中选择一场考试查看材料');
 const sample=e.status==='sample',t=st.view==='teacher',own=e.is_owner, a=st.items.find(x=>x.id===e.id);
 return '<section class="detail"><div class="split"><span class="label">材料速览</span>'+icon('book-open')+'</div><h2>'+E(e.title)+'</h2><p class="small">'+E(e.material_name)+'</p>'+
 (sample&&e.id==='sample-1'?'<figure><img src="/figure.svg" alt="线性插补与季节基线在三档缺测率下的平均绝对误差"><figcaption class="legend"><b class="lg1"></b>线性插补 <b class="lg2"></b>季节基线 · 合成数据</figcaption></figure>':'<div class="mt"></div>')+
 '<p class="intro">'+E((e.material_text||'暂无正文预览').slice(0,450))+'</p>'+(e.instructions?'<p class="mt">'+E(e.instructions)+'</p>':'')+'<div class="actions">'+
 (sample?button('查看示例题目','sample','primary','book-open'):t?button('答卷与成绩','grades','primary','file-check-2')+button('教师试答','preview'):a?.attempt_id?button('继续 / 查看答卷','resume','primary','arrow-right'):own?button('教师试答','preview','primary'):e.status==='published'?button('报名作答','join','primary','arrow-right'):'')+
 (!sample?button('材料全文','material','linkbtn'):'')+(t&&e.status==='published'?button('关闭报名','close-exam','linkbtn'):'')+'</div></section>'
}
async function selectExam(id,ep=st.epoch){
 st.sel=id;st.d=null;listRows();$('#paperdetail').innerHTML=empty('正在读取材料…');
 const e=!st.user?st.items.find(x=>x.id===id):await api(school+(st.view==='teacher'?'/teacher':'')+'/exams/'+id);
 if(st.epoch!==ep||st.sel!==id)return;st.d=e;$('#paperdetail').innerHTML=detail()
}
async function hall(ep){
 const t=st.view==='teacher';if(t&&!st.user?.teacher)throw Error('需要教师权限');
 const rows=st.user?await api(school+(t?'/teacher':'')+'/exams'):await api('/api/samples');
 if(ep!==st.epoch)return;st.items=rows;st.more=!!st.user&&rows.length===50;st.sel=rows.some(x=>x.id===st.sel)?st.sel:rows[0]?.id;
 const heading=t?'教师工作台':'考试大厅',subtitle=t?'准备考试材料，管理已发布的考试与学生答卷。':st.user?'已发布考试与小程序同步。':'公开教学示例 · 登录后查看小程序中的正式考试。';
 main.innerHTML=lead(t?'教师端':'学生端',heading,subtitle,t?'<div class="actions"><a class="secondary" href="#teacher-work">教师个人答辩</a>'+button('准备考试','prepare','primary','plus')+'</div>':'')+
 metrics(t?[[rows.length,'已载入考试','clipboard-list'],[rows.filter(e=>e.status==='published').length,'开放报名','book-open'],[rows.filter(e=>e.status==='closed').length,'已关闭','file-check-2']]:
 [[rows.length,st.user?'已载入考试':'教学案例','clipboard-list'],[st.user?rows.filter(e=>e.attempt_status==='active').length:rows.reduce((s,e)=>s+e.question_count,0),st.user?'正在作答':'示例题目','list-checks'],[st.user?rows.filter(e=>e.attempt_status==='completed').length:new Set(rows.map(e=>e.subject)).size,st.user?'已完成':'学科方向','layers']])+
 '<div class="columns"><section><div class="section-head split"><h2>'+(t?'我发布的考试':'考试列表')+'</h2>'+button('刷新','refresh','linkbtn','rotate-cw')+'</div><div class="tools"><div class="filters">'+[['all','全部'],['open','开放中'],...(!t&&st.user?[['joined','已参加']]:[])].map(([v,name])=>'<button data-act="filter" data-id="'+v+'" class="'+(st.filter===v?'active':'')+'">'+name+'</button>').join('')+'</div><label class="search">'+icon('search')+'<input id="search" aria-label="搜索考试" placeholder="搜索考试" value="'+E(st.search)+'"></label></div><div id="paperrows"></div></section><aside id="paperdetail"></aside></div>';
 listRows();$('#search').oninput=e=>{st.search=e.target.value;listRows()};if(st.sel)await selectExam(st.sel,ep);else $('#paperdetail').innerHTML=detail()
}
async function records(ep){
 const rows=[];let offset=0;
 while(true){const batch=await api(school+'/exams?offset='+offset);if(ep!==st.epoch)return;rows.push(...batch.filter(e=>e.attempt_id));if(batch.length<50)break;offset+=batch.length}
 main.innerHTML=lead('学生端','我的答卷','统一查看已报名的考试、作答进度和成绩。')+(rows.map(e=>'<div class="line"><div><h3>'+E(e.title)+'</h3><p class="small">'+E(e.teacher_name)+'</p></div>'+tag(e.attempt_status)+'<a class="secondary" href="#answer/'+E(e.attempt_id)+'">查看答卷</a></div>').join('')||empty('暂时没有已报名的考试'))
}
function pairLogin(section){return lead('个人空间',section,'登录后查看自己的材料和记录。')+'<div class="actions">'+button('账号登录','login','primary')+'<a class="secondary" href="#register">注册账号</a></div>'}
async function grades(ep,id){
 let rows=[],offset=0;while(true){let a=await api(school+'/teacher/exams/'+id+'/grades?offset='+offset);if(ep!==st.epoch)return;rows.push(...a);if(a.length<50)break;offset+=50}
 main.innerHTML=lead('教师端','答卷与成绩','正式答卷 '+rows.length+' 份，教师试答不计入成绩。')+(rows.map(r=>'<div class="line"><div><h3>'+E(r.student_name)+'</h3><small>'+E(r.student_number)+'</small></div>'+tag(r.status)+'<strong>'+E(r.final_score??'待出分')+'</strong><a class="secondary" href="#review/'+E(r.id)+'">查看 / 复核</a></div>').join('')||empty('暂未收到学生答卷'))
}
async function answerPage(ep,view,id){
 const base=school+(view==='preview'?'/teacher/previews/':view==='review'?'/teacher/attempts/':'/attempts/')+id;
 const a=await api(base);if(samePage(ep))showAttempt(ep,view,base,a);
}
function showAttempt(ep,view,base,a){
 st.current={a,base,view};const end=a.status==='completed',review=view==='review';
 if(!$('#attempt-progress'))main.innerHTML=lead(review?'教师复核':a.is_preview?'教师试答':'学生答卷',a.title,'')+
 '<div class="narrow"><progress id="attempt-progress" class="progress"></progress><div class="box"><div id="question"></div><div id="composer"></div>'+statusLine+'<div id="review-fields"></div></div><div id="answer-history"></div></div>';
 const progress=$('#attempt-progress');progress.max=a.question_count;progress.value=a.position;
 $('.titlebar p').textContent=a.student_name+' · 已回答 '+a.position+' / '+a.question_count+' 题';
 part('#question',tag(a.status)+(end?'<p class="mt"><b class="score">'+E(a.final_score)+'</b> / 100</p><p>'+E(a.review_note||'')+'</p>':a.question?'<h2 class="mt">'+E(a.question.text)+'</h2>':''));
 if(st.answers[a.id]?.position!==a.position||end||a.status==='needs_review')delete st.answers[a.id];
 const rec=st.answers[a.id],grading=a.status==='grading',busy=!!rec?.sending||grading;
 part('#composer',!review&&(a.status==='active'||(grading&&rec))?'<form id="answerform" data-position="'+a.position+'" class="form"><label>我的回答<textarea name="answer" maxlength="12000" rows="6" required></textarea></label><div>'+button('提交回答','submit-answer','primary','arrow-right')+'</div></form>':'');
 const input=$('#answerform textarea');
 if(input){if(rec&&input.value!==rec.answer)input.value=rec.answer;input.readOnly=busy||!!rec?.uncertain;$('#answerform button').disabled=busy}
 tell(rec?.sending?'正在提交回答…':grading?'回答已提交，正在评分…':rec?.uncertain?'尚未确认提交结果，可用原答案重试。':a.status==='needs_review'?'答案已保留，等待教师复核。':'',busy?'waiting':'');
 part('#review-fields',review&&(end||a.pending_request_id)?'<form id="reviewform" class="form mt"><p>'+E(a.pending_answer||'')+'</p><label>复核分数<input name="score" type="number" min="0" max="'+(end?'100':'5')+'" step="0.1" required></label><label>复核理由<textarea name="note" minlength="2" required></textarea></label><div>'+button('保存复核','review-score','primary')+'</div></form>':'');
 part('#answer-history',(a.answers||[]).map((h,i)=>'<section class="box"><h3>第 '+(i+1)+' 题 · '+E(h.question)+'</h3><p class="reading">'+E(h.answer)+'</p>'+(h.evaluation?.reasoning?'<p class="small mt">'+E(h.evaluation.reasoning)+'</p>':'')+'</section>').join(''));
 if(grading)later(ep,()=>answerPage(ep,view,a.id));
}
function remember(w){if(st.user&&st.work[w.role]===w)sessionStorage.setItem('campus-progress:'+st.user.principal_id+':'+w.role,JSON.stringify({project:w.p,document:w.d,job:w.job,session:w.session,blueprint:w.bp?.id,blueprintJob:w.bpJob,request:w.request,kind:w.kind,operation:w.operation,operationTurnCount:w.operation?w.opCount:undefined}))}
function workState(role){
 if(st.work[role])return st.work[role];
 let saved={};try{saved=JSON.parse(sessionStorage.getItem('campus-progress:'+st.user.principal_id+':'+role)||'{}')}catch{}
 return st.work[role]={role,p:saved.project,d:saved.document,job:saved.job,session:saved.session,request:saved.request,kind:saved.kind,operation:saved.operation,opCount:saved.operationTurnCount,bp:saved.blueprint?{id:saved.blueprint}:null,bpJob:saved.blueprintJob};
}
async function workspace(ep,prepare){
 const w=workState(st.role);
 const [ready,projects]=await Promise.all([api(school+'/workspace/'+w.role,'POST'),api(g+'/projects')]);
 if(!samePage(ep))return;
 const project=projects.some(x=>x.id===w.p)?w.p:projects[0]?.id;
 const docs=project?await api(g+'/projects/'+project+'/documents'):[];
 if(!samePage(ep))return;
 if((w.p&&w.p!==project)||(w.d&&!docs.some(x=>x.id===w.d)))Object.assign(w,{bp:null,bpJob:null,session:null,operation:null,job:null,request:null,jobStatus:''});
 Object.assign(w,{p:project,d:docs.some(x=>x.id===w.d)?w.d:docs[0]?.id,ready:ready.model_ready&&ready.profile===fixed,projects,docs,prep:prepare,loading:false});
 drawWork(w);
 if(w.sending)return;
 if(w.job||w.request){await readWorkJob(ep,w);return}
 // Restore authorized server output by receipt, not by storing paper text in the browser.
 if(w.bp&&!w.bp.data&&!w.bp.questions&&w.p&&w.d){
  const job=w.bpJob?await api(g+'/v1/jobs/'+w.bpJob):(await api(g+'/projects/'+w.p+'/blueprint-task?document_id='+encodeURIComponent(w.d))).job;
  if(!samePage(ep)||w.job||w.sending)return;
  const bp=job?.result?.blueprint;
  if(bp&&bp.id===w.bp?.id){w.bp=bp;w.bpJob=job.id;remember(w);drawWork(w)}
 }
}
function drawWork(w){
 const prepare=w.prep,busy=!!(w.loading||w.sending||w.job||(w.request&&!w.retry));
 if(!$('#project')){
  main.innerHTML=lead(prepare?'教师端':'个人空间',prepare?'准备考试':'个人答辩',prepare?'从教师空间选择材料，生成蓝图后发布。':'从自己的材料开始一场论文答辩。')+
  '<div class="columns"><section class="form"><label>项目<select id="project"></select></label><div>'+button('新建项目','new-project','secondary','plus')+'</div><label>论文材料<select id="doc"></select></label><label>上传材料（不超过 20 MB）<input id="file" type="file" accept=".pdf,.docx,.pptx,.txt,.md"></label><div class="actions">'+button('上传并解析','upload')+button('生成答辩蓝图','blueprint','primary')+'</div><div>'+statusLine+button('刷新任务','refresh-job','linkbtn','rotate-cw')+'</div><div id="model-notice"></div></section><aside class="detail"><span class="label">答辩蓝图</span><div id="blueprint-detail"></div></aside></div>';
  $('#project').onchange=e=>{Object.assign(w,{p:e.target.value,d:null,docs:[],bp:null,bpJob:null,session:null,operation:null,jobStatus:'',request:null,retry:false,loading:true});$('#file').value='';remember(w);drawWork(w);route()};
  $('#doc').onchange=e=>{Object.assign(w,{d:e.target.value,bp:null,bpJob:null,session:null,operation:null,jobStatus:'',request:null,retry:false});remember(w);drawWork(w)};
 }
 for(const [sel,items,field,value] of [['#project',w.projects,'name',w.p],['#doc',w.docs,'filename',w.d]]){
  part(sel,items.map(x=>'<option value="'+E(x.id)+'">'+E(x[field])+'</option>').join(''));
  if(value&&$(sel).value!==value)$(sel).value=value;
 }
 for(const name of ['#project','#doc','#file','[data-act="new-project"]','[data-act="upload"]','[data-act="blueprint"]'])$(name).disabled=busy;
 if(w.retry)$(w.kind==='upload'?'[data-act="blueprint"]':'[data-act="upload"]').disabled=true;
 part('#model-notice',w.ready?'':'<p class="alert">此空间未配置千问 Plus，暂不能生成蓝图或开始新答辩。</p>');
 part('#blueprint-detail','<h2>'+E(w.bp?.data?.title||w.bp?.title||(w.bp?'蓝图已就绪':'尚未生成'))+'</h2>'+
 (w.bp?.data?.questions||w.bp?.questions||[]).map((q,i)=>'<p class="intro">'+(i+1)+'. '+E(q.text)+'</p>').join('')+'<div class="actions">'+(w.bp?button(prepare?'发布考试':'开始个人答辩',prepare?'publish':'start-session','primary'):'')+(w.session&&!prepare?'<a class="secondary" href="#session/'+E(w.session)+'/'+w.role+'">继续答辩</a>':'')+'</div>');
 const use=$('#blueprint-detail button');if(use)use.disabled=!!(busy||w.request);
 const refresh=$('[data-act="refresh-job"]');refresh.hidden=!(w.job||w.request);refresh.disabled=!!w.sending;
 tell(w.jobStatus||'',busy?'waiting':'');
}
function acceptWorkJob(ep,w,job){
 w.job=job.id;w.retry=false;
 if(job.status==='completed'){
  const doc=job.result?.document,bp=job.result?.blueprint;
  if(doc){w.d=doc.id;w.bp=null;w.bpJob=null;w.session=null;if(!w.docs.some(d=>d.id===doc.id))w.docs.unshift(doc)}
  if(bp){w.bp=bp;w.bpJob=job.id;w.session=null}
  w.jobStatus=w.kind==='upload'?'材料解析完成。':'答辩蓝图已生成。';w.job=null;w.request=null;
 }else if(failedJob(job.status)){w.job=null;w.request=null;w.jobStatus='任务未完成，未重复提交。'}
 else w.jobStatus=w.kind==='upload'?'正在解析材料…':'正在生成答辩蓝图…';
 remember(w);drawWork(w);
 if(w.job)later(ep,()=>readWorkJob(ep,w));
}
async function readWorkJob(ep,w){
 if(w.sending||!samePage(ep))return;
 const key=w.request,id=w.job;
 const job=id?await api(g+'/v1/jobs/'+id):key?(await api(g+'/projects/'+w.p+'/'+(w.kind==='upload'?'document-task?':'blueprint-task?document_id='+encodeURIComponent(w.d)+'&')+'request_id='+encodeURIComponent(key))).job:null;
 if(!samePage(ep)||w.request!==key||w.job!==id)return;
 if(job){acceptWorkJob(ep,w,job);return}
 if(key){w.retry=true;w.jobStatus='未查到回执，可用同一请求重试。';drawWork(w)}
}
function settleTurn(w,s,job){
 if(w.session!==s.id)return;
 const completed=s.status==='completed',advanced=Number.isInteger(w.opCount)&&(s.turns||[]).length>w.opCount;
 if(!completed&&(!w.operation||s.state==='OPERATION_QUEUED'||(!advanced&&!failedJob(job?.status)&&!(job?.status==='completed'&&w.opCount==null))))return;
 const failed=!completed&&!advanced&&failedJob(job?.status);
 Object.assign(w,{operation:null,opCount:null,opPaused:false,opRetry:false,opNotice:failed?'本轮处理未完成，请核对回答后重试。':'',opDraft:failed?w.opDraft:null});
 remember(w);
}
async function sessionPage(ep,id,checks=0){
 const w=workState(st.role),s=await timedApi(g+'/sessions/'+id);if(!samePage(ep))return;
 settleTurn(w,s);
 showSession(w,s);
 if(s.status==='completed'||w.opPosting)return;
 if(w.session===id&&w.operation)later(ep,()=>readTurn(ep,w,id),350);
 else if(s.state==='OPERATION_QUEUED'){
  if(checks<24)later(ep,()=>sessionPage(ep,id,checks+1));
  else{tell('服务端仍在处理，可稍后查询进度。','notice');$('#turn-refresh').hidden=false}
 }
}
function showSession(w,s){
 st.session=s;
 if(!$('#session-turns'))main.innerHTML=lead('个人空间','个人答辩','')+'<div class="narrow"><div id="session-turns"></div><div id="turn-editor"></div>'+statusLine+'<div id="turn-refresh" hidden>'+button('查询最新进度','refresh-turn','linkbtn','rotate-cw')+'</div></div>';
 $('.titlebar p').textContent=labels[s.status]||s.status;
 const turns=s.turns||[],history=$('#session-turns');
 const rows=turns.map(t=>'<div class="box"><h3>'+E(t.role==='assistant'?'考官':'我的回答')+'</h3><p class="reading">'+E(t.content||t.text)+'</p></div>');
 const prev=history._rows||[];
 if(prev.length<=rows.length&&prev.every((r,i)=>r===rows[i])){if(prev.length<rows.length)history.insertAdjacentHTML('beforeend',rows.slice(prev.length).join(''))}
 else history.innerHTML=rows.join('');
 history._rows=rows;
 const end=s.status==='completed',op=w.session===s.id&&w.operation,busy=!end&&((!!op&&!w.opRetry)||s.state==='OPERATION_QUEUED'),draft=w.opDraft?.id===s.id?w.opDraft:null;
 part('#turn-editor',end?'<a class="primary" data-act="report" href="'+E(personalLink('report',s.id,w.role))+'">'+icon('file-check-2')+'查看报告</a>':!turns.length?button('请考官提问','begin-session','primary'):'<div class="form" data-turns="'+turns.length+'"><label>我的回答<textarea rows="5" id="session-answer" maxlength="20000"></textarea></label><div>'+button('提交回答','session-answer','primary')+'</div></div>');
 const input=$('#session-answer'),send=$('#turn-editor button');
 if(input){if(draft&&draft.count===turns.length&&!input.value)input.value=draft.answer;input.readOnly=busy}
 if(send&&s.status!=='completed')send.disabled=busy;
 $('#turn-refresh').hidden=!(op&&w.opPaused&&!end);
 tell(end?'':op&&w.opPaused?w.opNotice:busy?(w.opPosting?(turns.length?'正在提交回答…':'正在提交提问请求…'):(turns.length?'回答已提交，正在准备回应…':'正在生成考官提问…')):(w.session===s.id?w.opNotice||'':''),op&&w.opPaused?'notice':busy?'waiting':'');
}
async function readTurn(ep,w,id,check=1,posted){
 const key=w.operation,here=()=>samePage(ep)&&w.session===id&&w.operation===key&&st.session?.id===id;
 if(!key||w.opPosting||!here())return;
 let job=posted,s,absent=false;
 try{
  if(!job){({job}=await timedApi(g+'/sessions/'+id+'/operations/'+key));absent=job===null}
 }catch(e){if(!here())return;if(!transient(e))throw e}
 if(!here())return;
 // A worker can commit the last turn before its queue receipt becomes visible.
 if(!job||job.status==='completed'||failedJob(job.status)||check%4===0){
  try{s=await timedApi(g+'/sessions/'+id)}
  catch(e){if(!here())return;if(!transient(e))throw e}
  if(!here())return;
  if(s){settleTurn(w,s,job);showSession(w,s);if(!w.operation)return}
 }
 if(check>=(job?24:3)){
  w.opPaused=true;w.opRetry=absent&&!!s&&s.state!=='OPERATION_QUEUED';
  w.opNotice=w.opRetry?'对话尚未更新。可查询进度，或用同一请求重试原回答。':'处理结果尚未确认，可稍后查询进度。不会重复提交。';
  showSession(w,st.session);return;
 }
 later(ep,()=>readTurn(ep,w,id,check+1),job?2800:1200*check);
}
async function route(){
 const previousReport=activeReport;cancelReportRead();
 const ep=++st.epoch;clearTimeout(poll);const [v='hall',id,sessionRole]=location.hash.slice(1).split('/');const view=v||'hall';st.view=view;
 if(view==='session'||view==='report')st.role=sessionRole==='teacher'?'teacher':'student';
 if(view==='work'||view==='hall'||view==='records')st.role='student';if(['prepare','teacher','grades','review','teacher-work'].includes(view))st.role='teacher';
 document.body.classList.toggle('report-view',view==='report');
 document.title=view==='report'?'答辩报告 · 答辩学堂':'答辩学堂 · AI Examiner';
 if(!['report','login','register'].includes(view))resumeReport='';
 screenHash=location.hash;const key=JSON.stringify([st.user?.principal_id,st.role,view,id]);
 if(key!==screenKey){
  screenKey=key;st.current=null;st.session=null;
  const personal=st.role==='teacher'?'teacher':'work';
  frame(({answer:'records',review:'teacher',grades:'teacher',prepare:'teacher',session:personal,report:personal,'teacher-work':'teacher',preview:'teacher'})[view]||view);
  main.innerHTML='<p role="status">正在读取…</p>';
 }
 try{if(['login','register'].includes(view)){if(st.user){location.hash='hall';return}authPage(view==='register');return}
 if(view==='report'){
  if(!validReportAddress(id,sessionRole)){pageError(Error('报告地址无效，请从原答辩打开报告。'));return}
  if(!st.user){resumeReport=personalLink('report',id,st.role);main.innerHTML=pairLogin('答辩报告');return}
  await reportPage(ep,id);return;
 }
 if(!st.user && view!=='hall'){main.innerHTML=pairLogin(navNames[view]||'答辩工作台');return}
 if(['hall','teacher'].includes(view))await hall(ep);else if(view==='records')await records(ep);else if(['answer','preview','review'].includes(view))await answerPage(ep,view,id);else if(view==='grades')await grades(ep,id);else if(['work','teacher-work','prepare'].includes(view))await workspace(ep,view==='prepare');else if(view==='session'){
  await sessionPage(ep,id);
  if(samePage(ep)&&previousReport?.id===id&&previousReport.role===st.role)$('[data-act="report"]')?.focus();
 }else location.hash='hall'}
 catch(e){if(samePage(ep)){if(transient(e)&&$('#task-status')){tell('暂时无法更新，正在重试。','notice');later(ep,route,4500)}else pageError(e)}}
}
function formData(id){const f=$(id);if(!f.reportValidity())return null;return Object.fromEntries(new FormData(f))}
function formModal(title,form,act){modal(title,'<form class="form" id="modalform">'+form+'<div>'+button('确认',act,'primary')+'</div></form>')}
async function run(act,el){
 const e=st.d,w=st.work[st.role]||{},a=st.current?.a;
 const workOpen=()=>samePage(st.epoch)&&st.role===w.role&&st.work[w.role]===w&&!!$('#project');
 if(act==='login-account'||act==='register-account'){
  const p=formData('#authform');if(!p)return;
  $('#auth-error').hidden=true;
  if(act==='register-account'){
   if(p.password!==p.confirm_password)throw Error('两次输入的密码不一致');
   await api('/api/register','POST',p);location.hash='login';flash('注册成功，请使用新账号登录');return;
  }
  await api('/api/login','POST',p);
  st.user=(await api('/api/me')).user;
  if(!st.user)throw Error('登录会话未保存，请检查浏览器是否允许 Cookie');
  st.work={};st.answers={};st.items=[];st.sel=null;location.hash=resumeReport||'hall';resumeReport='';return;
 }
 if(act==='login')return login();if(act==='dismiss')return dlg.close();if(act==='refresh')return route();
 if(act==='refresh-turn'){const ep=st.epoch,id=st.session?.id;if(!id)return;
  clearTimeout(poll);if(w.session===id&&w.operation){w.opPaused=false;w.opRetry=false;showSession(w,st.session);later(ep,()=>readTurn(ep,w,id),0)}
  else return sessionPage(ep,id);return;
 }
 if(act==='refresh-job'){if(!w.sending){const ep=st.epoch;later(ep,()=>readWorkJob(ep,w),0)}return}
 if(act==='logout'){await api('/api/logout','POST');Object.keys(sessionStorage).filter(k=>k.startsWith('campus-progress:')).forEach(k=>sessionStorage.removeItem(k));location.replace(location.pathname);return}
 if(act==='select')return selectExam(el.dataset.id);
 if(act==='filter'){st.filter=el.dataset.id;document.querySelectorAll('.filters button').forEach(b=>b.classList.toggle('active',b===el));return listRows()}
 if(act==='more'){const next=await api(school+(st.view==='teacher'?'/teacher':'')+'/exams?offset='+st.items.length);st.items.push(...next);st.more=next.length===50;return listRows()}
 if(act==='sample'){modal('示例题目','<ol>'+e.questions.map(q=>'<li class="reading">'+E(q)+'</li>').join('')+'</ol>'+button('登录查看正式考试','login','primary'));return}
 if(act==='material'){modal('考试材料','<div class="reading">'+E(e.material_text)+'</div><div class="mt"><a class="secondary" download href="/api/material/'+E(e.id)+'">'+icon('download')+'下载原文件</a></div>');return}
 if(act==='prepare'){location.hash='prepare';return}
 if(act==='grades'){location.hash='grades/'+e.id;return}
 if(act==='resume'){location.hash='answer/'+st.items.find(x=>x.id===e.id).attempt_id;return}
 if(act==='join'){formModal('报名作答','<label>姓名<input name="student_name" maxlength="100" required></label><label>学号（选填）<input name="student_number" maxlength="100"></label><label class="check"><input type="checkbox" required>同意将答卷和成绩提交给发布教师</label>','confirm-join');return}
 if(act==='confirm-join'){const p=formData('#modalform');if(!p)return;const r=await api(school+'/exams/'+e.id+'/join','POST',p);dlg.close();location.hash='answer/'+r.id;return}
 if(act==='preview'){const r=await api(school+'/teacher/exams/'+e.id+'/preview','POST');location.hash='preview/'+r.id;return}
 if(act==='close-exam'){formModal('关闭报名','<p>新学生将不能参加，已有答卷仍可继续。</p>','confirm-close');return}
 if(act==='confirm-close'){await api(school+'/teacher/exams/'+e.id+'/close','POST');dlg.close();return route()}
 if(act==='submit-answer'){
  const p=formData('#answerform');if(!p||!p.answer.trim()||a.status!=='active')return;
  const {base,view}=st.current,rec=st.answers[a.id]||(st.answers[a.id]={request_id:uid(),position:a.position,answer:p.answer.trim()});
  if(rec.sending)return;rec.sending=true;
  const open=()=>samePage(st.epoch)&&st.current?.base===base&&st.answers[a.id]===rec;
  showAttempt(st.epoch,view,base,a);
  try{const ack=await api(base+'/answers/async','POST',{request_id:rec.request_id,position:rec.position,answer:rec.answer});
   rec.sending=false;rec.uncertain=false;if(open())showAttempt(st.epoch,view,base,ack);
  }catch(err){rec.sending=false;rec.uncertain=transient(err);
   if(open()){if(!rec.uncertain)delete st.answers[a.id];if([403,404].includes(err.status)){pageError(err);return}showAttempt(st.epoch,view,base,a);
    if(rec.uncertain||err.status===409){const ep=st.epoch;later(ep,()=>answerPage(ep,view,a.id),450)}
    if(!rec.uncertain)throw err;
   }
  }return;
 }
 if(act==='review-score'){const p=formData('#reviewform');if(!p)return;const {base,view}=st.current,end=a.status==='completed';await api(base+(end?'/review':'/review-answer'),'POST',{score:Number(p.score),note:p.note,...(end?{version:a.review_version}:{request_id:a.pending_request_id})});if(st.current?.base===base&&samePage(st.epoch))await answerPage(st.epoch,view,a.id);return}
 if(act==='new-project'){formModal('新建项目','<label>项目名称<input name="name" minlength="2" maxlength="100" required></label>','confirm-project');return}
 if(act==='confirm-project'){const p=formData('#modalform');if(!p)return;const r=await api(g+'/projects','POST',{name:p.name,domain:'research_defense',language:'zh-CN'});Object.assign(w,{p:r.id,d:null,docs:[],bp:null,bpJob:null,session:null,operation:null,job:null,request:null,retry:false,jobStatus:'',loading:true});remember(w);if(workOpen()){dlg.close();$('#file').value='';drawWork(w);return route()}return}
 if(['upload','blueprint'].includes(act)){
 if(!w.p||w.job||w.sending)throw Error('请先选择项目，或等待当前任务完成');
 if(w.request&&(w.kind!==act||!w.retry))throw Error('上次提交结果尚未确认，请先刷新任务，不会重复提交');
 const key=w.request||uid();let url,data,h={};
 if(act==='upload'){const file=$('#file').files[0];if(!file||file.size>20*1024*1024)throw Error('请选择不超过 20 MB 的论文文件');data=new FormData();data.append('file',file);data.append('original_filename',file.name);data.append('request_id',key);url='/documents/async'}
 else{if(!w.d||!w.ready)throw Error('请先选择材料并确认千问已就绪');url='/blueprints/async';data={document_id:w.d,profile:fixed,mode:'defense'};h={'Idempotency-Key':key}}
 Object.assign(w,{request:key,kind:act,sending:true,retry:false,jobStatus:act==='upload'?'正在上传材料…':'正在提交蓝图任务…'});remember(w);drawWork(w);
 try{const job=await api(g+'/projects/'+w.p+url,'POST',data,h);w.sending=false;
  if(w.request!==key)return;w.job=job.id;remember(w);if(workOpen())acceptWorkJob(st.epoch,w,job);
 }catch(err){w.sending=false;if(!transient(err))w.request=null;w.jobStatus=w.request?'正在确认提交结果…':errorText(err);remember(w);
  if(workOpen()){drawWork(w);if(w.request){const ep=st.epoch;later(ep,()=>readWorkJob(ep,w),450)}}
 }return}
 if(act==='publish'){formModal('发布正式考试','<label>考试标题<input name="title" minlength="2" maxlength="200" required></label><label>教师署名<input name="teacher_name" maxlength="100" required></label><label>题数<input type="number" name="question_count" min="1" max="20" value="1" required></label><label>考试说明<textarea name="instructions" maxlength="3000"></textarea></label><label class="check"><input type="checkbox" required>确认材料可供所有已登录学生查看</label>','confirm-publish');return}
 if(act==='confirm-publish'){const p=formData('#modalform');if(!p)return;const sig=JSON.stringify([w.bp.id,p]);if(w.pubSig!==sig){w.pubSig=sig;w.pubKey=uid()}await api(school+'/teacher/exams','POST',{...p,blueprint_id:w.bp.id,profile:fixed,question_count:Number(p.question_count),request_id:w.pubKey,share_material_confirmed:true});dlg.close();location.hash='teacher';return}
 if(act==='start-session'){const r=await api(g+'/sessions','POST',{project_id:w.p,blueprint_id:w.bp.id,profile:fixed,question_limit:6,question_strategy:'adaptive'});Object.assign(w,{session:r.id,operation:null,opCount:null,opPaused:false,opRetry:false,opDraft:null,opNotice:''});remember(w);if(workOpen())location.hash='session/'+r.id+'/'+w.role;return}
 if(act==='begin-session'||act==='session-answer'){
  const s=st.session,answer=$('#session-answer')?.value.trim()||'';if(act==='session-answer'&&!answer)throw Error('请填写回答');
  if((w.operation&&!w.opRetry)||w.opPosting||s.status==='completed'||s.state==='OPERATION_QUEUED')return;
  const count=s.turns.length,key=(w.session===s.id&&w.opRetry&&w.operation)||uid();
  Object.assign(w,{session:s.id,operation:key,opCount:count,opPosting:key,opDraft:{id:s.id,count,answer},opNotice:'',opPaused:false,opRetry:false});remember(w);showSession(w,s);
  const open=()=>samePage(st.epoch)&&st.session?.id===s.id&&st.role===w.role&&st.work[w.role]===w;
  let ack;
  try{ack=await timedApi(g+'/sessions/'+s.id+'/operations','POST',{request_id:key,operation:act==='begin-session'?'start':'answer',answer,expected_turn_count:count})}
  catch(err){if(w.operation!==key)return;
   if(!transient(err)&&err.status!==409){w.operation=null;w.opCount=null;w.opNotice=errorText(err);remember(w);
    if(open()&&[403,404].includes(err.status)){pageError(err);return}}
  }finally{if(w.opPosting===key)w.opPosting=false}
  if(open()){showSession(w,st.session);const ep=st.epoch;
   if(w.operation===key)later(ep,()=>readTurn(ep,w,s.id,1,ack?.status==='completed'||failedJob(ack?.status)?ack:null),350);
   else later(ep,()=>sessionPage(ep,s.id),350);
  }return;
 }
 if(act==='retry-report'&&isCurrentReport(activeReport))return reportPage(activeReport.epoch,activeReport.id);
 if(act==='print-report'&&isCurrentReport(activeReport)&&activeReport.data){window.print();return}
 if(act==='report-jump'&&isCurrentReport(activeReport)){document.getElementById(el.getAttribute('aria-controls'))?.focus();return}
 if(act==='report-next'||act==='report-prev'){
  if(isCurrentReport(activeReport)&&activeReport.data){activeReport.page+=act==='report-next'?1:-1;showEvidence(activeReport);$('#evidence-heading').focus()}
  return;
 }
}
let activeReport=null;
function cancelReportRead(){if(activeReport){activeReport.controller.abort();activeReport=null}}
function isCurrentReport(ctx){return !!ctx&&ctx===activeReport&&samePage(ctx.epoch)&&st.view==='report'&&st.role===ctx.role&&st.user===ctx.user}
const rowsOf=v=>Array.isArray(v)?v:[];
const reportHeading=(id,title,sym)=>'<h2 class="report-section-title" id="'+id+'" tabindex="-1">'+icon(sym)+E(title)+'</h2>';
function reportList(title,v,numbered=false){
 const rows=rowsOf(v).filter(x=>typeof x==='string'&&x.trim());
 const tag=numbered?'ol':'ul';
 return rows.length?'<div class="report-list"><h3>'+E(title)+'</h3><'+tag+'>'+rows.map(x=>'<li>'+E(x)+'</li>').join('')+'</'+tag+'></div>':'';
}
function reportMetrics(r){
 const max=r.max_score??5,scored=r.show_total_score!==false&&r.overall_score!=null;
 const score=scored?E(r.overall_score)+' <small>/ '+E(max)+'</small>':r.show_total_score===false?'不设总分':'暂无评分';
 const metric=(label,value,unit)=>'<div><dt>'+E(label)+'</dt><dd>'+(value==null?'未记录':E(value)+' <small>'+unit+'</small>')+'</dd></div>';
 return '<dl class="report-metrics" aria-label="答辩概览"><div class="report-total'+(scored?'':' qualitative')+'"><dt>综合评分</dt><dd>'+score+'</dd></div>'+
  metric('已答题目',r.questions_answered,'题')+metric('已评价轮次',r.evaluated_turns,'轮')+metric('作答证据',rowsOf(r.evidence).length,'条')+'</dl>';
}
function ratingRows(items,max){
 return '<dl class="report-ratings">'+items.map(x=>{
  const scored=x.evidence_count!==0&&Number.isFinite(x.score);
  const bar=scored&&max>0&&x.score>=0&&x.score<=max?'<meter aria-hidden="true" min="0" max="'+E(max)+'" value="'+E(x.score)+'"></meter>':'';
  return '<div><dt>'+E(x.title||x.name||x.id)+'</dt><dd>'+bar+'<span>'+(scored?E(x.score)+' / '+E(max):'未评价')+'</span></dd></div>';
 }).join('')+'</dl>';
}
function reportAssessment(r){
 const dimensions=rowsOf(r.dimension_scores),goals=rowsOf(r.objective_scores),units=rowsOf(r.knowledge_map),max=r.max_score??5;
 if(!(dimensions.length||goals.length||units.length))return '';
 const disclosure=(name,items,inside)=>items.length?'<details class="report-disclosure"><summary>'+name+' <span>('+items.length+')</span></summary>'+inside+'</details>':'';
 return '<section class="report-section">'+reportHeading('analysis-heading','评分分析','layers')+(dimensions.length?ratingRows(dimensions,max):'')+
  disclosure('考察目标',goals,ratingRows(goals,max))+disclosure('知识点表现',units,'<dl class="report-units">'+units.map(x=>'<div><dt>'+E(x.name||x.code)+'</dt><dd>'+E(({mastered:'已掌握',developing:'发展中',gap:'待加强'})[x.status]||'未评价')+'</dd></div>').join('')+'</dl>')+'</section>';
}
function evidenceItem(ctx,v,i){
 const question=ctx.questionNumbers.get(v.question_id),kind=({main:'主问题',followup:'追问'})[v.question_context];
 const label=question?'第 '+question+' 题'+(kind?' · '+kind:''):'作答摘录 '+(i+1);
 const source='材料出处'+(v.source_page!=null?' · 第 '+E(v.source_page)+' 页':'');
 return '<article class="report-excerpt"><div class="report-excerpt-head"><h3>'+E(label)+'</h3>'+(v.score!=null?'<span>'+E(v.score)+' 分</span>':'')+'</div>'+
  (v.quote?'<blockquote>'+E(v.quote)+'</blockquote>':'<p class="small">本轮未记录回答摘录。</p>')+
  (v.source_excerpt?'<details class="report-source"><summary>'+source+'</summary><p>'+E(v.source_excerpt)+'</p></details>':v.source_page!=null?'<p class="small">'+source+'</p>':'')+
  reportList('待补充',v.missing_points)+'</article>';
}
function showEvidence(ctx,printing=false){
 const items=rowsOf(ctx.data.evidence),size=5,limit=Math.max(1,Math.ceil(items.length/size));
 ctx.page=Math.min(limit-1,Math.max(0,ctx.page));
 const start=printing?0:ctx.page*size,end=printing?items.length:Math.min(start+size,items.length);
 $('#report-items').innerHTML=items.length?items.slice(start,end).map((v,i)=>evidenceItem(ctx,v,start+i)).join(''):'<p class="report-empty">本场没有可显示的作答证据。</p>';
 const pageButton=(name,act,sym,disabled)=>'<button type="button" class="iconbtn" data-act="'+act+'" title="'+name+'" aria-label="'+name+'"'+(disabled?' disabled':'')+'>'+icon(sym)+'</button>';
 $('#report-pager').innerHTML=!printing&&limit>1?'<span aria-live="polite">第 '+(ctx.page+1)+' / '+limit+' 页</span>'+pageButton('上一页','report-prev','arrow-left',ctx.page===0)+pageButton('下一页','report-next','arrow-right',ctx.page+1===limit):'';
}
function showReport(ctx){
 const r=ctx.data,display=(selector,value)=>{const el=$(selector);el.textContent=value||'';el.hidden=!value};
 display('#report-material',r.title);display('#report-template-name',r.template?.title);
 const feedback=reportList('表现亮点',r.strengths)+reportList('优先补足',r.priority_weaknesses||r.weaknesses);
 const plan=reportList('改进建议',r.recommended_actions||r.recommendations,true)+reportList('复测建议',r.improvement_path,true);
 const analysis=reportAssessment(r);
 const side=(feedback?'<section class="report-section">'+reportHeading('feedback-heading','答辩反馈','file-check-2')+feedback+'</section>':'')+
  (plan?'<section class="report-section">'+reportHeading('plan-heading','改进计划','list-checks')+plan+'</section>':'');
 const sections=[[analysis,'analysis-heading','评分分析'],[true,'evidence-heading','作答证据'],[feedback,'feedback-heading','答辩反馈'],[plan,'plan-heading','改进计划']].filter(([visible])=>visible);
 const jumps=sections.length>1?'<nav class="report-jumps" aria-label="报告章节">'+sections.map(([,id,title])=>'<button type="button" data-act="report-jump" aria-controls="'+id+'">'+title+'</button>').join('')+'</nav>':'';
 $('#report-body').innerHTML=reportMetrics(r)+(typeof r.summary==='string'&&r.summary?'<p class="report-summary">'+E(r.summary)+'</p>':'')+
  jumps+'<div class="report-spread'+(side?' has-aside':'')+'"><div>'+analysis+
  '<section id="report-evidence" class="report-section"><div class="report-evidence-title"><h2 class="report-section-title" id="evidence-heading" tabindex="-1">'+icon('book-open')+'作答证据</h2><div id="report-pager"></div></div><div id="report-items"></div></section>'+
  '</div>'+(side?'<aside aria-label="反馈与建议">'+side+'</aside>':'')+'</div>'+(r.disclaimer?'<footer class="report-note">'+E(r.disclaimer)+'</footer>':'');
 ctx.questionNumbers=new Map(rowsOf(r.question_trajectories).map((x,i)=>[x.question_id,i+1]).filter(([id])=>id));
 showEvidence(ctx);
 $('[data-act="print-report"]').hidden=false;
}
async function reportPage(epoch,id){
 cancelReportRead();
 const ctx={id,epoch,role:st.role,user:st.user,controller:new AbortController(),page:0};activeReport=ctx;
 main.replaceChildren($('#report-template').content.cloneNode(true));
 $('#report-back').href=personalLink('session',id,ctx.role);
 $('#report-heading').focus({preventScroll:true});window.scrollTo(0,0);
 const deadline=performance.now()+15000,read=path=>timedApi(path,'GET',undefined,ctx.controller,Math.max(1,deadline-performance.now()));
 const path=g+'/sessions/'+encodeURIComponent(id),body=$('#report-body');
 try{
  const result=await read(path+'/report');
  if(!isCurrentReport(ctx))return;
  const r=result?.report??result;
  if(!r||typeof r!=='object'||(!Array.isArray(r.evidence)&&r.overall_score===undefined&&typeof r.summary!=='string'))throw Error('报告数据不完整');
  // Legacy reports omit session_status. Deep links must not reveal a provisional score.
  const status=r.session_status??result.session_status??(await read(path)).status;
  if(!isCurrentReport(ctx))return;
  if(status!=='completed'){body.innerHTML='<p class="report-empty">'+(status?'答辩尚未结束，完成后即可查看报告。':'无法确认答辩状态，请返回原答辩核对。')+'</p>';return}
  ctx.data=r;showReport(ctx);
 }catch(e){
  if(!isCurrentReport(ctx))return;
  ctx.data=null;
  const denied=[403,404].includes(e.status);
  body.innerHTML='<p class="alert" role="alert">'+E(denied?'当前账号无法查看这份报告，或报告已不存在。':(e.status===408?'读取报告超时。':'未能读取报告：'+errorText(e))+' 无需重新提交回答。')+'</p>'+
   (denied?'':'<div class="mt">'+button('重新读取报告','retry-report','secondary','rotate-cw')+'</div>');
 }finally{if(isCurrentReport(ctx))body.setAttribute('aria-busy','false')}
}
// Print the whole authorized report without changing the reader's evidence page or fetching again.
window.addEventListener('beforeprint',()=>{
 const ctx=activeReport;if(!isCurrentReport(ctx)||!ctx.data||ctx.printing)return;
 ctx.printing={expanded:[...document.querySelectorAll('#report-items details')].map((el,i)=>el.open?i:-1).filter(i=>i>=0),
  closed:[...document.querySelectorAll('.report-disclosure:not([open])')]};
 showEvidence(ctx,true);document.querySelectorAll('.report-page details').forEach(el=>el.open=true);
});
window.addEventListener('afterprint',()=>{
 const ctx=activeReport;if(!isCurrentReport(ctx)||!ctx.printing)return;
 ctx.printing.closed.forEach(el=>el.open=false);showEvidence(ctx);
 const details=document.querySelectorAll('#report-items details');ctx.printing.expanded.forEach(i=>{if(details[i])details[i].open=true});ctx.printing=null;
});
const clicks=new WeakSet(),taskButtons=new Set(['submit-answer','begin-session','session-answer','upload','blueprint']);
document.addEventListener('click',async ev=>{const el=ev.target.closest('[data-act]');if(!el||el.matches('a[href]')||el.disabled||clicks.has(el))return;
 const managed=taskButtons.has(el.dataset.act),from=location.hash;clicks.add(el);if(!managed)el.disabled=true;
 try{await run(el.dataset.act,el)}catch(e){if(from!==location.hash)return;const s=errorText(e);if($('#auth-error')){$('#auth-error').textContent=s;$('#auth-error').hidden=false}else if(dlg.open){let p=dlg.querySelector('.action-error');if(!p){p=document.createElement('p');p.className='alert action-error';dlg.append(p)}p.textContent=s}else flash(s)}finally{clicks.delete(el);if(!managed)el.disabled=false}});
document.addEventListener('submit',ev=>{ev.preventDefault();ev.target.querySelector('[data-act]')?.click()});
$('#identity').dataset.act='login';
window.addEventListener('hashchange',()=>{st.filter='all';st.search='';if(dlg.open)dlg.close();route()});
(async()=>{try{st.user=(await api('/api/me')).user;await route()}catch(e){main.textContent=errorText(e)}})();
