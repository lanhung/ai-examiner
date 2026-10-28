const school = require('../../lib/school');
Page({
  data:{id:'',teacher:false,preview:false,busy:false,voiceBusy:false,error:'',attempt:null,answer:'',uncertain:false,score:'',note:''},
  onLoad(options){this.setData({id:options.id,teacher:options.preview!=='1'&&options.teacher==='1',preview:options.preview==='1'});this.refresh();},
  onShow(){this.visible=true;this.pollErrors=0;this.refresh();},
  onHide(){this.visible=false;clearTimeout(this.timer);},
  onUnload(){this.onHide();},
  schedule(){clearTimeout(this.timer);if(this.visible&&this.data.attempt&&this.data.attempt.status==='grading'&&(this.pollErrors||0)<3)this.timer=setTimeout(()=>this.refresh(),this.pollErrors?5000:2500);},
  endpoint(){return this.data.preview?`/teacher/previews/${this.data.id}`:`${this.data.teacher?'/teacher':''}/attempts/${this.data.id}`;},
  apply(attempt){this.setData({attempt:school.label(attempt)});},
  async run(fn){if(this.data.busy)return;this.setData({busy:true,error:''});try{await fn();}catch(e){this.setData({error:e.message});if(wx.pageScrollTo)wx.pageScrollTo({scrollTop:0,duration:0});}finally{this.setData({busy:false});}},
  async refresh(){await this.run(async()=>{
    let attempt;try{attempt=await school.request(this.endpoint());this.pollErrors=0;}catch(e){this.pollErrors=(this.pollErrors||0)+1;throw e;}this.apply(attempt);
    if(this.pending && attempt.position>this.pending.position){this.pending=null;this.setData({answer:'',uncertain:false});}
    if(attempt.status!=='active')this.setData({uncertain:false});
  });this.schedule();},
  field(e){this.setData({[e.currentTarget.dataset.field]:e.detail.value});},
  voiceBusy(e){this.setData({voiceBusy:e.detail.busy});},
  voiceText(e){
    if(this.data.teacher||this.data.busy||this.data.uncertain)return;
    const text=[this.data.answer,e.detail.text].filter(Boolean).join('\n');
    if(text.length>12000){this.setData({error:'回答超过字数限制，请先精简现有文字再录音'});return;}
    this.setData({answer:text});
  },
  submit(){if(this.data.voiceBusy)return;return this.run(async()=>{
    if(this.data.teacher||this.data.voiceBusy||this.data.uncertain||!this.data.attempt||this.data.attempt.status!=='active')return;
    const answer=this.data.answer.trim();if(!answer)throw new Error('请先填写回答');
    this.pending=this.pending||{request_id:school.id(),position:this.data.attempt.position,answer};
    try{this.apply(await school.request(this.endpoint()+'/answers/async','POST',this.pending));this.pending=null;this.setData({answer:'',uncertain:false});this.schedule();}
    catch(e){this.setData({uncertain:true});throw e;}
  });},
  retry(){if(this.data.busy||!this.pending||!this.data.attempt||this.data.attempt.status!=='active')return;this.setData({uncertain:false});this.submit();},
  review(){return this.run(async()=>{
    if(!this.data.score.trim()||!this.data.note.trim())throw new Error('请填写分数和复核理由');
    const score=Number(this.data.score);if(!Number.isFinite(score)||score<0||score>100)throw new Error('分数应为 0 到 100');
    this.apply(await school.request(this.endpoint()+'/review','POST',{score,note:this.data.note.trim(),version:this.data.attempt.review_version}));
    this.setData({score:'',note:''});
  });},
  reviewAnswer(){return this.run(async()=>{
    if(!this.data.score.trim()||this.data.note.trim().length<2)throw new Error('请填写分数和评分理由');
    const score=Number(this.data.score);if(!Number.isFinite(score)||score<0||score>5)throw new Error('单题分数应为 0 到 5');
    this.apply(await school.request(this.endpoint()+'/review-answer','POST',{score,note:this.data.note.trim(),request_id:this.data.attempt.pending_request_id}));
    this.setData({score:'',note:''});
  });}
});
