const api = require('../../lib/api');
const progress = require('../../lib/progress');
Page({
  data:{busy:false,error:'',organizations:[],orgIndex:0,providers:[],providerIndex:0,projects:[],projectIndex:0,name:'',document:null,documents:[],documentIndex:0,uploadProgress:-1,uploadMessage:'',uploadUncertain:false,blueprint:null,job:null,sessionId:''},
  async onLoad() {await this.run(async()=>{
    const me=await api.request('/api/v1/me'); getApp().globalData.me=me;
    const organizations=me.organizations.filter(o=>o.status==='active');
    const old=wx.getStorageSync(api.ORG);
    const orgIndex=Math.max(0,organizations.findIndex(o=>o.id===old));
    this.setData({organizations,orgIndex});
    if(organizations.length) {wx.setStorageSync(api.ORG,organizations[orgIndex].id); await this.loadProjects();}
    const providers=(await api.request('/api/providers')).filter(p=>p.ready && p.provider!=='mock');
    this.setData({providers});
    if(organizations.length) await this.restore();
  });},
  onHide(){this.visible=false;clearTimeout(this.timer);},
  onUnload(){this.visible=false;clearTimeout(this.timer);},
  onShow(){this.visible=true;if(this.data.job && !this.data.blueprint) this.poll();},
  async restore(){
    const saved=progress.read(), index=this.data.projects.findIndex(p=>p.id===saved.projectId);
    if(index>=0)this.setData({projectIndex:index,uploadUncertain:!!saved.uploadUncertain,sessionId:saved.sessionId||'',providerIndex:Math.max(0,this.data.providers.findIndex(p=>p.id===saved.profile)),document:saved.documentId?{id:saved.documentId,filename:'已上传的论文'}:null,job:saved.jobId?{id:saved.jobId,status:'待刷新'}:null});
    await this.loadDocuments();
    if(saved.jobId)this.poll();
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
    const documents=await this.loadDocuments();
    if(this.data.uploadUncertain)this.setData({uploadMessage:documents && documents.length?'请选择列表中已保存的材料；不要重复上传。':'暂未查到材料，服务器可能仍在处理，请稍后再次刷新。'});
  });},
  document(e){
    if(this.data.busy||this.data.job)return;
    const documentIndex=Number(e.detail.value), document=this.data.documents[documentIndex];
    if(document)this.useDocument(document,documentIndex);
  },
  selectDocument(){this.document({detail:{value:this.data.documentIndex}});},
  useDocument(document,documentIndex=0){
    const project=this.data.projects[this.data.projectIndex];
    progress.save({projectId:project.id,documentId:document.id,jobId:null,sessionId:null,uploadUncertain:false});
    this.setData({document,documentIndex,blueprint:null,job:null,sessionId:'',error:'',uploadUncertain:false,uploadProgress:-1,uploadMessage:'材料已就绪'});
  },
  async organization(e){await this.run(async()=>{
    clearTimeout(this.timer);this.generation=(this.generation||0)+1;
    const orgIndex=Number(e.detail.value);wx.setStorageSync(api.ORG,this.data.organizations[orgIndex].id);
    this.setData({orgIndex,document:null,documents:[],uploadUncertain:false,uploadMessage:'',uploadProgress:-1,blueprint:null,job:null,projects:[],sessionId:''});await this.loadProjects();await this.restore();
  });},
  async project(e){await this.run(async()=>{clearTimeout(this.timer);this.generation=(this.generation||0)+1;progress.reset();this.setData({projectIndex:Number(e.detail.value),document:null,documents:[],uploadUncertain:false,uploadMessage:'',uploadProgress:-1,blueprint:null,job:null,sessionId:''});await this.loadDocuments();});},
  provider(e){this.setData({providerIndex:Number(e.detail.value)});},
  name(e){this.setData({name:e.detail.value});},
  async create(){await this.run(async()=>{
    const name=this.data.name.trim();if(name.length<2)throw new Error('项目名称至少两个字');
    const project=await api.request('/api/projects','POST',{name,domain:'research_defense',language:'zh-CN'});
    clearTimeout(this.timer);this.generation=(this.generation||0)+1;progress.reset();
    await this.loadProjects();this.setData({projectIndex:this.data.projects.findIndex(p=>p.id===project.id),name:'',document:null,documents:[],uploadUncertain:false,uploadMessage:'',uploadProgress:-1,blueprint:null,job:null,sessionId:''});
  });},
  async upload(){await this.run(async()=>{
    if(this.data.uploadUncertain)throw new Error('上次上传结果未确认，请先刷新已上传材料');
    const project=this.data.projects[this.data.projectIndex];if(!project)throw new Error('请先选择项目');
    const file=await new Promise((resolve,reject)=>wx.chooseMessageFile({count:1,type:'file',extension:['pdf','pptx','docx','txt','md'],success:r=>resolve(r.tempFiles[0]),fail:e=>reject(new Error(/cancel/i.test(e.errMsg||'')?'已取消选择文件':'无法选择文件，请检查微信隐私授权与文件访问权限'))}));
    if(!file || file.size>20*1024*1024)throw new Error('请选择不超过20MB的材料');
    if(/\.doc$/i.test(file.name||''))throw new Error('请在 Word 中将 .doc 另存为 .docx 后上传');
    progress.save({projectId:project.id,uploadUncertain:true});
    this.setData({uploadProgress:0,uploadMessage:'正在上传材料',uploadUncertain:true});
    try {
      const document=await api.upload(project.id,file.path,{filename:file.name,onProgress:r=>{
        const value=Math.max(0,Math.min(100,Number(r.progress)||0));
        this.setData({uploadProgress:value,uploadMessage:value>=100?'文件传输完成，服务器正在解析与保存证据':'正在上传材料'});
      }});
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
  async retryUpload(){
    if(this.data.busy)return;
    const result=await new Promise(resolve=>wx.showModal({title:'确认重新上传',content:'上次请求可能仍在处理。请先刷新并检查已上传材料，重新上传可能产生重复文件。',confirmText:'重新选择',success:resolve,fail:()=>resolve({confirm:false})}));
    if(!result.confirm)return;
    progress.save({uploadUncertain:false});this.setData({uploadUncertain:false});await this.upload();
  },
  async generate(){await this.run(async()=>{
    const p=this.data.projects[this.data.projectIndex], model=this.data.providers[this.data.providerIndex];
    if(!p || !model || !this.data.document || this.data.uploadUncertain)throw new Error('请先选择项目、模型并确认已上传材料');
    const job=await api.request(`/api/projects/${p.id}/blueprints/async`,'POST',{document_id:this.data.document.id,profile:model.id,mode:'defense'}, {headers:{'Idempotency-Key':`wx-${Date.now()}-${Math.random().toString(36).slice(2)}`}});
    progress.save({jobId:job.id,profile:model.id});this.setData({job});this.poll();
  });},
  async poll(){
    clearTimeout(this.timer);if(!this.visible||!this.data.job||this.polling)return;
    const generation=this.generation||0, id=this.data.job.id;this.polling=true;
    try {
      const job=await api.request(`/api/v1/jobs/${id}`);
      if(generation!==(this.generation||0)||id!==(this.data.job && this.data.job.id))return;
      this.setData({job});
      if(job.status==='completed')this.setData({blueprint:job.result.blueprint});
      else if(['failed','cancelled','canceled'].includes(job.status))this.setData({error:'蓝图任务未完成，请在网页任务中心查看失败详情。'});
      else if(this.visible)this.timer=setTimeout(()=>this.poll(),2500);
    }catch(e){this.setData({error:e.message});}finally{this.polling=false;}
  },
  refreshJob(){this.poll();},
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
