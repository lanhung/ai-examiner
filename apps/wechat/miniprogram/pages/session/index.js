const api=require('../../lib/api');
const progress=require('../../lib/progress');
Page({
  data:{id:'',turns:[],status:'',answer:'',busy:false,error:'',uncertain:false},
  async onLoad(options){if(!/^[a-zA-Z0-9-]+$/.test(options.id||'')){this.setData({error:'会话地址无效'});return;}this.setData({id:options.id});const saved=progress.read();if(saved.sessionId===options.id){this.beforeSend=saved.beforeSend;this.setData({uncertain:!!saved.pending});}await this.refresh();},
  async refresh(){if(this.data.busy)return;this.setData({busy:true,error:''});try{
    const session=await api.request(`/api/sessions/${this.data.id}`);
    this.setData({turns:session.turns,status:session.status});
    // An ambiguous POST is not retried. Reconciliation needs a later server turn.
    if(this.data.uncertain && session.turns.length>this.beforeSend && session.turns[session.turns.length-1].role==='assistant'){this.setData({uncertain:false,answer:''});progress.save({pending:false});}
  }catch(e){this.setData({error:e.message});}finally{this.setData({busy:false});}},
  answer(e){this.setData({answer:e.detail.value});},
  async begin(){await this.send(`/api/sessions/${this.data.id}/start`);},
  async submit(){const answer=this.data.answer.trim();if(answer)await this.send(`/api/sessions/${this.data.id}/answers`,{answer});},
  async send(path,data){if(this.data.busy||this.data.uncertain)return;this.beforeSend=this.data.turns.length;this.setData({busy:true,error:''});
    try{progress.save({sessionId:this.data.id,pending:true,beforeSend:this.beforeSend});await api.request(path,'POST',data);progress.save({pending:false});this.setData({answer:''});}
    catch(e){const uncertain=!e.status || e.status>=500;this.setData({error:e.message,uncertain});if(!uncertain){try{progress.save({pending:false});}catch(_){/* Login may already be cleared. */}}}
    finally{this.setData({busy:false});}
    if(!this.data.error)await this.refresh();
  },
  report(){wx.navigateTo({url:`/pages/report/index?id=${encodeURIComponent(this.data.id)}`});}
});
