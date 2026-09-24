const {ORG}=require('./api');
const PREFIX='aiex.wx.progress.';
function key(){
  const me=getApp().globalData.me, org=wx.getStorageSync(ORG);
  if(!me || !me.principal || !org) throw new Error('请重新登录并选择空间');
  return PREFIX + me.principal.id + '.' + org;
}
function read(){return wx.getStorageSync(key()) || {};}
function save(data){
  const next={...read()};
  for(const field of ['projectId','documentId','jobId','sessionId','profile','pending','beforeSend','uploadUncertain']) {
    if(Object.prototype.hasOwnProperty.call(data,field)) next[field]=data[field];
  }
  wx.setStorageSync(key(),next);
}
function reset(){wx.removeStorageSync(key());}
module.exports={read,save,reset};
