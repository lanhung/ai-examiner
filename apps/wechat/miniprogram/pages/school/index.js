const api = require('../../lib/api');
const school = require('../../lib/school');
Page({
  data:{busy:false,error:'',teacher:false,mode:'student',exams:[],offset:0,more:false,principalId:''},
  onShow(){this.load(false);},
  async load(append=false){
    if(this.data.busy)return;
    this.setData({busy:true,error:''});
    try {
      const me=await api.request('/api/v1/me');getApp().globalData.me=me;
      const identity=await school.request('/me');
      const mode=identity.teacher?this.data.mode:'student';
      this.setData({teacher:identity.teacher,mode,principalId:identity.principal_id});
      this.teacherOrg=identity.teacher_organization_id;
      const offset=append?this.data.exams.length:0;
      const rows=await school.request(`${mode==='teacher'?'/teacher':''}/exams?offset=${offset}`);
      this.setData({exams:[...(append?this.data.exams:[]),...rows.map(school.label)],more:rows.length===50});
    }catch(e){this.setData({error:e.message});}finally{this.setData({busy:false});}
  },
  mode(e){if(this.data.busy)return;const mode=e.currentTarget.dataset.mode;if(mode==='teacher'&&!this.data.teacher)return;this.setData({mode,exams:[]});this.load();},
  refresh(){this.load(false);},
  more(){this.load(true);},
  open(e){wx.navigateTo({url:`/pages/exam/index?id=${encodeURIComponent(e.currentTarget.dataset.id)}&teacher=${this.data.mode==='teacher'?1:0}`});},
  prepare(){if(!this.data.teacher)return;wx.setStorageSync(api.ORG,this.teacherOrg);wx.navigateTo({url:'/pages/work/index?teacher=1'});},
  personal(){wx.navigateTo({url:'/pages/work/index'});},
  async logout(){try{await api.request('/api/v1/wechat/logout','POST');api.clear();wx.reLaunch({url:'/pages/login/index'});}catch(e){this.setData({error:e.message});}}
});
