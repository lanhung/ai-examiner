const api = require('../../lib/api');
Page({
  data:{busy:false, consent:false, error:'',checking:false,loginAvailable:false,registrationMode:'',serviceStatus:'正在连接服务'},
  onLoad() { if (wx.getStorageSync(api.TOKEN)) {wx.redirectTo({url:'/pages/work/index'});return;} this.checkService(); },
  async checkService() {
    if(this.data.checking)return;
    this.setData({checking:true,error:'',loginAvailable:false,registrationMode:'',serviceStatus:'正在连接服务'});
    try {
      const status=await api.request('/api/v1/wechat/status','GET',undefined,{auth:false});
      const account=typeof wx.getAccountInfoSync==='function'?wx.getAccountInfoSync():null;
      const appId=account && account.miniProgram && account.miniProgram.appId;
      const mismatch=appId && status.app_id && appId!==status.app_id;
      const messages={ready:'微信登录配置就绪',disabled:'服务已连接，微信登录尚未启用',missing_credentials:'服务已连接，微信登录凭据尚未配置'};
      this.setData({loginAvailable:status.login_available===true && !mismatch,registrationMode:['personal','approval'].includes(status.registration_mode)?status.registration_mode:'',serviceStatus:mismatch?'小程序 AppID 与服务器配置不一致':messages[status.state]||'登录状态未知'});
    } catch(e) {this.setData({serviceStatus:e.status===404?'服务器尚未部署微信接入接口':'暂时无法连接服务',error:e.message});}
    finally {this.setData({checking:false});}
  },
  consent(e) { this.setData({consent:e.detail.value.includes('yes')}); },
  async login() {
    if (this.data.busy || !this.data.consent || !this.data.loginAvailable) return;
    this.setData({busy:true, error:''});
    try {
      const code = await new Promise((resolve,reject) => wx.login({success:r=>r.code?resolve(r.code):reject(new Error('微信未返回登录凭证')),fail:()=>reject(new Error('微信登录失败'))}));
      const result = await api.request('/api/v1/wechat/login','POST',{code},{auth:false});
      if (!result.access_token || !result.access_token.startsWith('wxmp_')) throw new Error('登录响应无效');
      wx.setStorageSync(api.TOKEN,result.access_token);
      wx.redirectTo({url:'/pages/work/index'});
    } catch(e) {this.setData({error:e.message});}
    finally {this.setData({busy:false});}
  }
});
