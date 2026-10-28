const api = require('../../lib/api');
const progress = require('../../lib/progress');
const school = require('../../lib/school');
Page({
  data:{busy:false,error:'',organizations:[],orgIndex:0,providers:[],providerIndex:0,projects:[],projectIndex:0,name:'',document:null,documents:[],documentIndex:0,uploadProgress:-1,uploadMessage:'',uploadUncertain:false,blueprint:null,job:null,sessionId:'',generationUncertain:false,recoveringBlueprint:false,jobStage:'',jobElapsed:'',jobNotice:''},
  async onLoad(options={}) {await this.run(async()=>{
    const me=await api.request('/api/v1/me'); getApp().globalData.me=me;
    let organizations=me.organizations.filter(o=>o.status==='active');
    if(options.teacher==='1'){
      const identity=await school.request('/me');
      if(!identity.teacher)throw new Error('教师身份未开通');
      organizations=organizations.filter(o=>o.id===identity.teacher_organization_id);
      this.setData({teacherMode:true,examTitle:'',teacherName:'',examInstructions:'',shareConfirmed:false,questionCount:'6'});
    }
    const old=wx.getStorageSync(api.ORG);
    const orgIndex=Math.max(0,organizations.findIndex(o=>o.id===old));
    this.setData({organizations,orgIndex});
    if(organizations.length) {wx.setStorageSync(api.ORG,organizations[orgIndex].id); await this.loadProjects();}
    const providers=(await api.request('/api/providers')).filter(p=>p.ready && p.provider!=='mock' && p.provider!=='openai');
    this.setData({providers,providerIndex:0});
    if(organizations.length) await this.restore();
  });},
  onHide(){this.visible=false;clearTimeout(this.timer);},
  onUnload(){this.visible=false;clearTimeout(this.timer);},
  onShow(){this.visible=true;this.pollErrors=0;if(this.data.job && !this.data.blueprint) this.poll();else if(this.data.uploadUncertain)this.recoverUpload();else if(this.data.generationUncertain)this.recoverBlueprint();},
  async restore(){
    const saved=progress.read(), index=this.data.projects.findIndex(p=>p.id===saved.projectId);
    if(index>=0)this.setData({projectIndex:index,uploadUncertain:!!saved.uploadUncertain,sessionId:saved.sessionId||'',providerIndex:Math.max(0,this.data.providers.findIndex(p=>p.id===saved.profile)),document:saved.documentId?{id:saved.documentId,filename:'已上传的论文'}:null,job:saved.jobId?{id:saved.jobId,status:'待刷新'}:null,generationUncertain:!!saved.blueprintPending&&!saved.jobId});
    await this.loadDocuments();
    if(index>=0 && saved.jobId)this.poll();
    else if(index>=0 && saved.uploadRequestId)await this.recoverUpload();
    else if(index>=0 && this.data.document)await this.recoverBlueprint();
  },
  async run(fn){if(this.data.busy)return;this.setData({busy:true,error:''});try{await fn();}catch(e){this.setData({error:e.message});}finally{this.setData({busy:false});}},
  async loadProjects(){this.setData({projects:await api.request('/api/projects'),projectIndex:0});},
  async loadDocuments(){
    const project=this.data.projects[this.data.projectIndex];if(!project)return;
    const generation=this.generation||0;
    const documents=await api.request(`/api/projects/${project.id}/documents`);
    if(generation!==(this.generation||0)||project.id!==(this.data.projects[this.data.projectIndex]||{}).id)return;
    const index=documents.findIndex(d=>this.data.document && d.id===this.data.document.id);
    this.setData({documents,documentIndex:Math.max(0,index)});
    if(index>=0)this.setData({document:documents[index]});
    return documents;
  },
  async refreshDocuments(){await this.run(async()=>{
    if(this.data.uploadUncertain&&progress.read().uploadRequestId){await this.recoverUpload();return;}
    const documents=await this.loadDocuments();
    if(this.data.uploadUncertain)this.setData({uploadMessage:documents && documents.length?'请选择列表中已保存的材料；不要重复上传。':'暂未查到材料，服务器可能仍在处理，请稍后再次刷新。'});
  });},
  document(e){
    if(this.data.busy||this.data.job||this.data.generationUncertain)return;
    const documentIndex=Number(e.detail.value), document=this.data.documents[documentIndex];
    if(document)this.useDocument(document,documentIndex);
  },
  selectDocument(){this.document({detail:{value:this.data.documentIndex}});},
  useDocument(document,documentIndex=0){
    this.publishRequest=null;
    const project=this.data.projects[this.data.projectIndex];
    progress.save({projectId:project.id,documentId:document.id,jobId:null,sessionId:null,uploadUncertain:false,uploadRequestId:null,blueprintRequestId:null,blueprintPending:false});
    this.setData({generationUncertain:false,jobNotice:''});
    this.setData({document,documentIndex,blueprint:null,job:null,sessionId:'',error:'',uploadUncertain:false,uploadProgress:-1,uploadMessage:'材料已就绪'});
  },
  async organization(e){await this.run(async()=>{
    clearTimeout(this.timer);this.generation=(this.generation||0)+1;
    const orgIndex=Number(e.detail.value);wx.setStorageSync(api.ORG,this.data.organizations[orgIndex].id);
    this.setData({generationUncertain:false,jobNotice:''});this.pollErrors=0;
    this.setData({orgIndex,document:null,documents:[],uploadUncertain:false,uploadMessage:'',uploadProgress:-1,blueprint:null,job:null,projects:[],sessionId:''});await this.loadProjects();await this.restore();
  });},
  async project(e){await this.run(async()=>{clearTimeout(this.timer);this.generation=(this.generation||0)+1;progress.reset();this.setData({projectIndex:Number(e.detail.value),document:null,documents:[],uploadUncertain:false,uploadMessage:'',uploadProgress:-1,blueprint:null,job:null,sessionId:'',generationUncertain:false,jobNotice:''});await this.loadDocuments();});},
  provider(e){if(!this.data.generationUncertain&&!this.data.job)this.setData({providerIndex:Number(e.detail.value)});},
  name(e){this.setData({name:e.detail.value});},
  async create(){await this.run(async()=>{
    const name=this.data.name.trim();if(name.length<2)throw new Error('项目名称至少两个字');
    const project=await api.request('/api/projects','POST',{name,domain:'research_defense',language:'zh-CN'});
    clearTimeout(this.timer);this.generation=(this.generation||0)+1;progress.reset();
    this.setData({generationUncertain:false,jobNotice:''});this.pollErrors=0;
    await this.loadProjects();this.setData({projectIndex:this.data.projects.findIndex(p=>p.id===project.id),name:'',document:null,documents:[],uploadUncertain:false,uploadMessage:'',uploadProgress:-1,blueprint:null,job:null,sessionId:''});
  });},
  async upload(){await this.run(async()=>{
    if(this.data.job||this.data.generationUncertain)throw new Error('请先确认当前蓝图任务结果');
    if(this.data.uploadUncertain)throw new Error('上次上传结果未确认，请先刷新已上传材料');
    const project=this.data.projects[this.data.projectIndex];if(!project)throw new Error('请先选择项目');
    const file=await new Promise((resolve,reject)=>wx.chooseMessageFile({count:1,type:'file',extension:['pdf','pptx','docx','txt','md'],success:r=>resolve(r.tempFiles[0]),fail:e=>reject(new Error(/cancel/i.test(e.errMsg||'')?'已取消选择文件':'无法选择文件，请检查微信隐私授权与文件访问权限'))}));
    if(!file || file.size>20*1024*1024)throw new Error('请选择不超过20MB的材料');
    if(/\.doc$/i.test(file.name||''))throw new Error('请在 Word 中将 .doc 另存为 .docx 后上传');
    const requestId=school.id();
    progress.save({projectId:project.id,uploadUncertain:true,uploadRequestId:requestId,jobId:null,documentId:null,sessionId:null,blueprintRequestId:null,blueprintPending:false});
    this.setData({uploadProgress:0,uploadMessage:'正在上传材料',uploadUncertain:true,blueprint:null,document:null,sessionId:''});
    try {
      const document=await api.upload(project.id,file.path,{filename:file.name,requestId,onProgress:r=>{
        const value=Math.max(0,Math.min(100,Number(r.progress)||0));
        this.setData({uploadProgress:value,uploadMessage:value>=100?'文件传输完成，服务器正在解析与保存证据':'正在上传材料'});
      }});
      if(document.kind==='document_ingestion'){
        progress.save({jobId:document.id});this.acceptJob(document);this.poll();return;
      }
      this.useDocument(document);
      this.setData({documents:[document,...this.data.documents.filter(d=>d.id!==document.id)]});
    }catch(e){
      const uncertain=!!e.uncertain;
      progress.save({uploadUncertain:uncertain});
      this.setData({uploadUncertain:uncertain,uploadMessage:uncertain?'结果未确认，请刷新已上传材料。服务器可能已保存成功。':'上传未完成',uploadProgress:-1});
      if(uncertain){try{await this.loadDocuments();}catch(_) { /* Keep the original upload error. */ }}
      throw e;
    }
  });},
  async recoverUpload(){
    const saved=progress.read(), project=this.data.projects[this.data.projectIndex];
    if(!project||!saved.uploadRequestId)return;
    const generation=this.generation||0;
    try{
      const {job}=await api.request(`/api/projects/${project.id}/document-task?request_id=${encodeURIComponent(saved.uploadRequestId)}`);
      if(generation!==(this.generation||0))return;
      if(job){progress.save({jobId:job.id});this.acceptJob(job);this.poll();}
      else this.setData({uploadMessage:'尚未找到上传回执，请稍后刷新；不要连续重复上传'});
    }catch(e){this.setData({error:e.message});}
  },
  async retryParsing(){await this.run(async()=>{
    const project=this.data.projects[this.data.projectIndex], saved=progress.read();
    if(!project||!saved.uploadRequestId||this.data.job)return;
    const job=await api.request(`/api/projects/${project.id}/document-task/${encodeURIComponent(saved.uploadRequestId)}/retry`,'POST');
    progress.save({jobId:job.id,uploadUncertain:true});this.acceptJob(job);this.poll();
  });},
  async retryUpload(){
    if(this.data.busy)return;
    const result=await new Promise(resolve=>wx.showModal({title:'确认重新上传',content:'上次请求可能仍在处理。请先刷新并检查已上传材料，重新上传可能产生重复文件。',confirmText:'重新选择',success:resolve,fail:()=>resolve({confirm:false})}));
    if(!result.confirm)return;
    progress.save({uploadUncertain:false});this.setData({uploadUncertain:false});await this.upload();
  },
  async generate(){await this.run(async()=>{
    if(this.recovering)throw new Error('正在找回蓝图结果，请稍候');
    if(this.data.job)throw new Error('已有蓝图任务，请先刷新任务状态，不要重复提交');
    const p=this.data.projects[this.data.projectIndex], model=this.data.providers[this.data.providerIndex];
    if(!p || !model || !this.data.document || this.data.uploadUncertain)throw new Error('请先选择项目、模型并确认已上传材料');
    const saved=progress.read();
    const key=this.data.generationUncertain?saved.blueprintRequestId:school.id();
    if(!key)throw new Error('任务编号缺失，请先找回蓝图结果');
    progress.save({projectId:p.id,documentId:this.data.document.id,jobId:null,profile:model.id,blueprintRequestId:key,blueprintPending:true});
    this.setData({generationUncertain:true,blueprint:null,jobNotice:'正在提交任务'});
    try{
      const job=await api.request(`/api/projects/${p.id}/blueprints/async`,'POST',{document_id:this.data.document.id,profile:model.id,mode:'defense'}, {headers:{'Idempotency-Key':key}});
      if(!job.id)throw new Error('服务器未返回任务编号');
      progress.save({jobId:job.id,blueprintPending:false});this.pollErrors=0;
      this.setData({generationUncertain:false});this.acceptJob(job);this.poll();
    }catch(e){
      // Keep the receipt key when the POST may have reached the server.
      if(e.status && e.status<500 && e.status!==408){
        progress.save({blueprintRequestId:null,blueprintPending:false});this.setData({generationUncertain:false});
      }
      this.setData({jobNotice:'提交结果待确认，请先找回结果，不要重新上传材料'});
      throw e;
    }
  });},
  async recoverBlueprint(){
    const p=this.data.projects[this.data.projectIndex], document=this.data.document;
    if(!p||!document||this.recovering)return;
    const generation=this.generation||0;this.recovering=true;this.setData({recoveringBlueprint:true});
    const saved=progress.read();
    const key=this.data.generationUncertain?saved.blueprintRequestId:null;
    try{
      const result=await api.request(`/api/projects/${p.id}/blueprint-task?document_id=${encodeURIComponent(document.id)}${key?'&request_id='+encodeURIComponent(key):''}`);
      if(generation!==(this.generation||0)||document.id!==(this.data.document||{}).id)return;
      if(result.job){
        progress.save({projectId:p.id,documentId:document.id,jobId:result.job.id,blueprintPending:false});
        this.setData({generationUncertain:false});this.pollErrors=0;
        this.acceptJob(result.job);if(this.data.job)this.poll();
      }else this.setData({jobNotice:this.data.generationUncertain?'尚未找到任务，可以用原编号重新确认提交，不会重复创建任务':'这份材料尚无你的蓝图任务'});
    }catch(e){
      if(generation===(this.generation||0)&&document.id===(this.data.document||{}).id)this.setData({error:e.message});
    }finally{this.recovering=false;this.setData({recoveringBlueprint:false});}
  },
  acceptJob(job){
    if(job.kind==='document_ingestion'){
      if(job.status==='completed'){
        const document=job.result&&job.result.document;
        if(!document)throw new Error('材料解析结果未返回，请刷新任务');
        this.useDocument(document);
        this.setData({documents:[document,...this.data.documents.filter(d=>d.id!==document.id)]});
      }else if(['failed','dead_letter','cancelled'].includes(job.status)){
        progress.save({jobId:null,uploadUncertain:false});
        this.setData({job:null,uploadUncertain:false,error:/[\u3400-\u9fff]/.test(job.message||'')?job.message:'材料解析未完成，原始文件已保存。请联系管理员凭回执检查，不要反复上传。',uploadMessage:'解析未完成'});
      }else this.setData({job,uploadUncertain:true,jobStage:job.status==='queued'?'等待解析材料':'正在解析材料并保存页面证据',jobElapsed:'',uploadMessage:'上传已保存，正在后台解析，可离开后找回'});
      return;
    }
    if(job.status==='completed' && (!job.result || !job.result.blueprint))throw new Error('蓝图结果未返回，请刷新任务状态，不要重复生成');
    const started=Date.parse(job.created_at||'');
    const seconds=Number.isFinite(started)?Math.max(0,Math.floor((Date.now()-started)/1000)):0;
    const state={queued:'等待处理',running:'正在生成',retry_scheduled:'等待重试',cancelling:'正在取消'};
    const message=/[\u3400-\u9fff]/.test(job.message||'')?job.message:(state[job.status]||'正在查询任务');
    this.setData({job,error:'',jobStage:message,jobElapsed:started?`${Math.floor(seconds/60)}分${seconds%60}秒`:'',jobNotice:seconds>=60?'模型仍在处理，完成后会自动显示结果；退出后可以找回':''});
    if(job.status==='completed'){
      this.setData({blueprint:job.result.blueprint,job:null,jobNotice:'蓝图已生成'});
      progress.save({blueprintPending:false});
    }else if(['failed','dead_letter','cancelled','canceled'].includes(job.status)){
      progress.save({jobId:null,blueprintRequestId:null,blueprintPending:false});
      const error=job.error==='worker_lease_expired'
        ?'蓝图生成已中断，服务器未自动重试。材料仍保留，重新生成会再次调用模型。'
        :job.error==='ModelOutputValidationError'?'模型生成的题目未通过校验。本次任务已结束，材料保留；重新生成会再次调用模型。'
        :job.status==='dead_letter'?'蓝图生成重试已耗尽。材料仍保留，请稍后手动重新生成。'
        :['cancelled','canceled'].includes(job.status)?'蓝图生成已取消，材料仍保留。'
        :'蓝图生成失败，材料仍保留。请稍后手动重新生成或联系管理员。';
      this.setData({job:null,error,jobNotice:''});
    }
  },
  async poll(){
    if(this.polling){this.pollAgain=true;return;}
    clearTimeout(this.timer);if(!this.visible||!this.data.job)return;
    const generation=this.generation||0, id=this.data.job.id;this.polling=true;
    try {
      const job=await api.request(`/api/v1/jobs/${id}`);
      if(generation!==(this.generation||0)||id!==(this.data.job && this.data.job.id))return;
      this.acceptJob({...job,id});
      this.pollErrors=0;
    }catch(e){
      if(generation===(this.generation||0)&&id===(this.data.job && this.data.job.id)){
        this.pollErrors=(this.pollErrors||0)+1;
        this.setData({error:`${e.message}。任务结果尚未确认，请勿重复生成。${this.pollErrors>=3?'自动查询已暂停，请点击刷新任务状态。':''}`});
      }
    }finally{
      this.polling=false;
      const resume=this.pollAgain;this.pollAgain=false;
      if(this.visible&&this.data.job&&(resume||this.pollErrors<3)){
        this.timer=setTimeout(()=>this.poll(),resume?0:this.pollErrors?5000:2500);
      }
    }
  },
  refreshJob(){this.pollErrors=0;this.poll();},
  examField(e){this.publishRequest=null;this.setData({[e.currentTarget.dataset.field]:e.detail.value});},
  share(e){this.setData({shareConfirmed:e.detail.value.includes('yes')});},
  async publish(){await this.run(async()=>{
    if(!this.data.teacherMode||!this.data.blueprint)throw new Error('请先准备考试蓝图');
    if(!this.data.shareConfirmed)throw new Error('请确认材料可向学生公开');
    const model=this.data.providers[this.data.providerIndex];
    if(!model)throw new Error('暂无可用模型，请联系管理员配置');
    const question_count=Number(this.data.questionCount);
    if(!Number.isInteger(question_count)||question_count<1||question_count>20)throw new Error('题数应为 1 到 20');
    if(!this.data.examTitle.trim()||!this.data.teacherName.trim())throw new Error('请填写考试名称和教师署名');
    const configuration={blueprint_id:this.data.blueprint.id,title:this.data.examTitle.trim(),teacher_name:this.data.teacherName.trim(),instructions:this.data.examInstructions.trim(),profile:model.id,question_count,share_material_confirmed:true};
    // Reuse an idempotency key only for the exact same publication snapshot.
    const signature=JSON.stringify(configuration);
    if(!this.publishRequest||this.publishSignature!==signature){
      this.publishSignature=signature;
      this.publishRequest={request_id:school.id(),...configuration};
    }
    const exam=await school.request('/teacher/exams','POST',this.publishRequest);
    wx.navigateTo({url:`/pages/exam/index?id=${exam.id}&teacher=1`});
  });},
  async start(){await this.run(async()=>{
    const p=this.data.projects[this.data.projectIndex],model=this.data.providers[this.data.providerIndex];
    if(!this.data.blueprint || !model)throw new Error('请先完成蓝图');
    const session=await api.request('/api/sessions','POST',{project_id:p.id,blueprint_id:this.data.blueprint.id,profile:model.id,question_limit:6,question_strategy:'adaptive'});
    progress.save({sessionId:session.id,pending:false,beforeSend:0});this.setData({sessionId:session.id});
    wx.navigateTo({url:`/pages/session/index?id=${encodeURIComponent(session.id)}`});
  });},
  resume(){if(this.data.sessionId)wx.navigateTo({url:`/pages/session/index?id=${encodeURIComponent(this.data.sessionId)}`});},
  async logout(){await this.run(async()=>{await api.request('/api/v1/wechat/logout','POST');api.clear();wx.reLaunch({url:'/pages/login/index'});});}
});
