const config = require('./endpoint');
Page({
  data:{code:'',busy:false,message:'',origin:config.origin},
  input(e){this.setData({code:e.detail.value.toUpperCase().replace(/\s/g,'').slice(0,8),message:''});},
  async approve(){
    if(this.data.busy||!/^[A-Z2-9]{8}$/.test(this.data.code))return;
    this.setData({busy:true,message:''});
    try{
      const ok=await new Promise((resolve,reject)=>wx.showModal({
        title:'登录自己的浏览器？',content:'仅在亲自打开下方网站并看到相同配对码时确认。浏览器将能以你的身份访问考试、材料和成绩。\n'+this.data.origin+'\n配对码：'+this.data.code,
        confirmText:'确认登录',success:r=>resolve(r.confirm),fail:reject}));
      if(!ok)return;
      const login=await new Promise((resolve,reject)=>wx.login({success:resolve,fail:reject}));
      if(!login.code)throw Error('微信未返回凭证');
      const r=await new Promise((resolve,reject)=>wx.request({url:config.origin+'/api/pair/approve',method:'POST',
        header:{'Content-Type':'application/json','X-Campus-Request':'1'},
        data:{code:this.data.code,login_code:login.code},timeout:20000,success:resolve,fail:reject}));
      if(r.statusCode!==200)throw Error(typeof r.data?.detail==='string'?r.data.detail:'登录未成功，请重新获取网页配对码');
      this.setData({message:'已确认，请返回浏览器。',code:''});
    }catch(e){this.setData({message:e.message||'无法连接，请检查网络和 request 合法域名'});}
    finally{this.setData({busy:false});}
  }
});
