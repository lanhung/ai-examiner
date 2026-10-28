// Keep the entry shell independent of compiled business modules until it renders.
Page({
  data:{busy:false,consent:false,error:'',checking:false,loginAvailable:false,registrationMode:'',
    serviceStatus:'正在启动',startupCode:'',clientBuild:'20261023-startup1'},
  onLoad:function() {this.closed=false;},
  onReady:function() {return this.startup();},
  onUnload:function() {this.closed=true;if(this.finishNavigation)this.finishNavigation(false);},
  update:function(patch) {if(!this.closed)this.setData(patch);},
  startupError:function(code,message) {
    this.update({checking:false,busy:false,loginAvailable:false,startupCode:code,
      serviceStatus:'启动未完成',error:message});
  },
  loadApi:function() {
    try {if(!this.api)this.api=require('../../lib/api');return this.api;}
    catch(e) {this.startupError('MODULE_LOAD','程序加载失败，请重新打开最新预览版。');return null;}
  },
  startup:function() {
    if(this.data.checking||this.data.busy||this.closed)return;
    var api=this.loadApi();
    if(!api)return;
    this.update({startupCode:'',error:''});
    try {if(wx.getStorageSync(api.TOKEN))return this.openHome();}
    catch(e) {this.startupError('LOCAL_STORAGE','无法读取本机登录状态，请关闭小程序后重试。');return;}
    return this.checkService();
  },
  openHome:function() {
    var self=this;
    this.update({checking:true,startupCode:'',error:'',serviceStatus:'正在打开考试大厅'});
    return new Promise(function(resolve) {
      var settled=false;
      var timer;
      function finish(ok) {
        if(settled)return;
        settled=true;clearTimeout(timer);self.finishNavigation=null;
        if(!ok)self.startupError('PAGE_OPEN','考试大厅打开失败，请重试；材料和答卷不会被删除。');
        else self.update({checking:false});
        resolve();
      }
      self.finishNavigation=finish;
      timer=setTimeout(function(){finish(false);},5000);
      try {wx.redirectTo({url:'/pages/school/index',success:function(){finish(true);},fail:function(){finish(false);}});}
      catch(e) {finish(false);}
    });
  },
  checkService:function() {
    if(this.data.checking||this.closed)return;
    var api=this.loadApi();
    if(!api)return;
    var self=this;
    this.update({checking:true,error:'',startupCode:'',loginAvailable:false,registrationMode:'',serviceStatus:'正在连接服务'});
    return Promise.resolve().then(function() {
      return api.request('/api/v1/wechat/status','GET',undefined,{auth:false});
    }).then(function(status) {
      var account=typeof wx.getAccountInfoSync==='function'?wx.getAccountInfoSync():null;
      var appId=account && account.miniProgram && account.miniProgram.appId;
      var mismatch=appId && status.app_id && appId!==status.app_id;
      var messages={ready:'微信登录配置就绪',disabled:'服务已连接，微信登录尚未启用',missing_credentials:'服务已连接，微信登录凭据尚未配置'};
      self.update({checking:false,loginAvailable:status.login_available===true && !mismatch,
        registrationMode:['personal','approval'].indexOf(status.registration_mode)!==-1?status.registration_mode:'',
        serviceStatus:mismatch?'小程序 AppID 与服务器配置不一致':messages[status.state]||'登录状态未知'});
    }).catch(function(e) {
      self.update({checking:false,serviceStatus:e.status===404?'服务器尚未部署微信接入接口':'暂时无法连接服务',error:e.message});
    });
  },
  consent:function(e) {this.update({consent:e.detail.value.indexOf('yes')!==-1});},
  login:function() {
    if (this.data.busy || !this.data.consent || !this.data.loginAvailable) return;
    var api=this.loadApi();
    if(!api)return;
    var self=this;
    this.update({busy:true,error:''});
    return new Promise(function(resolve,reject) {
      wx.login({success:function(r){if(r.code)resolve(r.code);else reject(new Error('微信未返回登录凭证'));},
        fail:function(){reject(new Error('微信登录失败'));}});
    }).then(function(code) {
      if(self.closed)return;
      return api.request('/api/v1/wechat/login','POST',{code:code},{auth:false});
    }).then(function(result) {
      if(self.closed)return;
      if(!result || typeof result.access_token!=='string' || result.access_token.indexOf('wxmp_')!==0)throw new Error('登录响应无效');
      wx.setStorageSync(api.TOKEN,result.access_token);
      self.update({busy:false});
      return self.openHome();
    }).catch(function(e) {self.update({busy:false,error:e.message});});
  }
});
