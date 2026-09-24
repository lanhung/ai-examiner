const config = require('../config');
const TOKEN = 'aiex.wx.session';
const ORG = 'aiex.wx.organization';
function base() {
  const value = config.apiBase.replace(/\/$/, '');
  if (!/^https:\/\/[a-zA-Z0-9.-]+(?::\d+)?$/.test(value)) throw new Error('请先在 config.js 配置 HTTPS 服务地址');
  return value;
}
function url(path) {
  if (!/^\/api\/[a-zA-Z0-9_/?=&%.:-]+$/.test(path) || path.includes('..')) throw new Error('无效的接口路径');
  return base() + path;
}
function clear() {
  if(wx.getStorageInfoSync) {
    for(const key of wx.getStorageInfoSync().keys) if(key.startsWith('aiex.wx.progress.')) wx.removeStorageSync(key);
  }
  wx.removeStorageSync(TOKEN); wx.removeStorageSync(ORG);
  // Do not retain papers, answers, or transcripts in persistent client storage.
  getApp().globalData.me = null;
}
function headers(auth = true) {
  const h = {};
  if (auth) {
    const token = wx.getStorageSync(TOKEN);
    if (!token) throw new Error('请先登录');
    h.Authorization = 'Bearer ' + token;
    const org = wx.getStorageSync(ORG);
    if (org) h['X-AI-Examiner-Organization'] = org;
  }
  return h;
}
function decode(result) {
  let data = result.data;
  if (typeof data === 'string') {
    try { data = JSON.parse(data); } catch (_) { data = {}; }
  }
  if (result.statusCode >= 200 && result.statusCode < 300) return data;
  if (result.statusCode === 401) {
    clear(); wx.reLaunch({url:'/pages/login/index'});
  }
  const detail = data && (data.detail || data.error);
  const message = typeof detail === 'string' ? detail : (detail && detail.message);
  const error = new Error(message || `请求失败（${result.statusCode}）`);
  error.status = result.statusCode;
  throw error;
}
function networkError(error, fallback) {
  const message = String(error && error.errMsg || '');
  if (/url not in domain list|domain not allowed|不在.*合法域名/i.test(message)) {
    return new Error('服务域名未获微信允许，请配置 request 和 uploadFile 合法域名后重试');
  }
  if (/ssl|certificate|tls/i.test(message)) {
    return new Error('HTTPS 证书校验失败，请检查服务器证书与域名');
  }
  if (/timeout|timed out/i.test(message)) {
    return new Error('连接超时。' + fallback);
  }
  return new Error(fallback);
}
function request(path, method = 'GET', data, options = {}) {
  return new Promise((resolve, reject) => {
    let endpoint, header;
    try { endpoint=url(path); header={...headers(options.auth !== false), ...options.headers}; }
    catch(e) { reject(e); return; }
    wx.request({url:endpoint, method, data, header, timeout:60000,
      success:r => {try {resolve(decode(r));} catch(e) {reject(e);}},
      fail:e => reject(networkError(e, method === 'GET' ? '网络连接失败，请检查设备网络及服务域名配置' : '网络中断，操作结果尚未确认，请刷新状态，不要重复提交'))});
  });
}
function upload(projectId, filePath, options = {}) {
  return new Promise((resolve, reject) => {
    let endpoint, header;
    try {endpoint=url(`/api/projects/${projectId}/documents`); header=headers();}
    catch(e) {reject(e); return;}
    const task=wx.uploadFile({url:endpoint, header, filePath, name:'file', timeout:60000,
      formData:options.filename ? {original_filename:options.filename} : {},
      success:r => {try {
        const document=decode(r);
        if(!document.id) throw new Error('服务器未返回材料编号，请刷新已上传材料');
        resolve(document);
      } catch(e) {e.uncertain=!e.status || e.status>=500;reject(e);}},
      fail:e => {
        const error=networkError(e, '上传结果未确认，请刷新已上传材料，不要立即重复上传');
        error.uncertain=true;reject(error);
      }});
    if(task && task.onProgressUpdate && options.onProgress) task.onProgressUpdate(options.onProgress);
  });
}
module.exports = {request, upload, clear, url, decode, TOKEN, ORG};
