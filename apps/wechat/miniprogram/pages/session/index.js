const api=require('../../lib/api');
const progress=require('../../lib/progress');
const school=require('../../lib/school');
Page({
  data:{id:'',turns:[],status:'',answer:'',busy:false,voiceBusy:false,error:'',uncertain:false,operationStatus:''},
  async onLoad(options){if(!/^[a-zA-Z0-9-]+$/.test(options.id||'')){this.setData({error:'会话地址无效'});return;}this.setData({id:options.id});const saved=progress.read();if(saved.sessionId===options.id){this.beforeSend=saved.beforeSend;this.operationRequestId=saved.operationRequestId;this.setData({uncertain:!!saved.pending});}await this.refresh();},
  onShow(){this.visible=true;this.pollErrors=0;if(this.data.id)this.refresh();},
  onHide(){this.visible=false;clearTimeout(this.timer);},
  onUnload(){this.onHide();},
  schedule(){clearTimeout(this.timer);if(this.visible&&this.data.uncertain&&(this.pollErrors||0)<3)this.timer=setTimeout(()=>this.refresh(),this.pollErrors?5000:2500);},
  clearPending(){this.operationRequestId=null;this.setData({uncertain:false,operationStatus:''});progress.save({pending:false,operationRequestId:null});},
  async refresh(){if(this.data.busy)return;this.setData({busy:true,error:''});try{
    if(this.operationRequestId){
      const {job}=await api.request(`/api/sessions/${this.data.id}/operations/${this.operationRequestId}`);
      if(job)this.setData({operationStatus:job.status});
      if(!job){this.clearPending();this.setData({error:'尚未收到提交，可以重新提交；系统会校验轮次，避免重复回答。'});}
      else if(['completed','failed','dead_letter','cancelled'].includes(job.status)){
        this.clearPending();
        if(job.status==='completed')this.setData({answer:''});
        else this.setData({error:'本次处理未完成，未自动重复调用模型。请核对记录后再提交。'});
      }
    }
    const session=await api.request(`/api/sessions/${this.data.id}`);
    this.setData({turns:session.turns,status:session.status});
    // Compatibility with receipts created by older clients.
    if(!this.operationRequestId && this.data.uncertain && session.turns.length>this.beforeSend && session.turns[session.turns.length-1].role==='assistant'){this.setData({uncertain:false,answer:''});progress.save({pending:false});}
    this.pollErrors=0;
  }catch(e){this.pollErrors=(this.pollErrors||0)+1;this.setData({error:e.message});}finally{this.setData({busy:false});this.schedule();}},
  answer(e){this.setData({answer:e.detail.value});},
  voiceBusy(e){this.setData({voiceBusy:e.detail.busy});},
  voiceText(e){
    if(this.data.busy||this.data.uncertain)return;
    const text=[this.data.answer,e.detail.text].filter(Boolean).join('\n');
    if(text.length>20000){this.setData({error:'回答超过字数限制，请先精简文字'});return;}
    this.setData({answer:text});
  },
  async begin(){await this.send('start');},
  async submit(){if(this.data.voiceBusy)return;const answer=this.data.answer.trim();if(answer)await this.send('answer',answer);},
  async send(operation,answer=''){if(this.data.busy||this.data.uncertain)return;this.beforeSend=this.data.turns.length;this.operationRequestId=school.id();this.setData({busy:true,error:'',uncertain:true});
    try{progress.save({sessionId:this.data.id,pending:true,beforeSend:this.beforeSend,operationRequestId:this.operationRequestId});const job=await api.request(`/api/sessions/${this.data.id}/operations`,'POST',{request_id:this.operationRequestId,operation,answer,expected_turn_count:this.beforeSend});this.setData({operationStatus:job.status});}
    catch(e){const uncertain=!e.status || e.status>=500 || e.status===408;this.setData({error:e.message,uncertain});if(!uncertain){try{this.clearPending();}catch(_){/* Login may already be cleared. */}}}
    finally{this.setData({busy:false});}
    if(!this.data.error)await this.refresh();else this.schedule();
  },
  report(){wx.navigateTo({url:`/pages/report/index?id=${encodeURIComponent(this.data.id)}`});}
});
