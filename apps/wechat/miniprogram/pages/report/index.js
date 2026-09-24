const api=require('../../lib/api');
Page({data:{report:null,error:'',busy:false},onLoad(options){this.id=options.id;this.load();},async load(){
  if(this.data.busy)return;if(!/^[a-zA-Z0-9-]+$/.test(this.id||'')){this.setData({error:'报告地址无效'});return;}
  this.setData({busy:true,error:''});try{this.setData({report:await api.request(`/api/sessions/${this.id}/report`)});}catch(e){this.setData({error:e.message});}finally{this.setData({busy:false});}
}});
