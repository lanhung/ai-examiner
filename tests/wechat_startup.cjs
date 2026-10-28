const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../apps/wechat/miniprogram');

function startup(options = {}) {
  let definition;
  let imports = 0;
  const calls = [];
  const timers = new Map();
  const api = {TOKEN:'token', request:async (...args) => {
    calls.push(args);
    if(options.requestError)throw options.requestError;
    return options.status || {state:'ready', login_available:true, registration_mode:'personal'};
  }};
  const wx = {
    getStorageSync:() => {if(options.storageError)throw new Error('private storage detail');return options.token;},
    redirectTo:o => {calls.push(o);if(options.redirectError)o.fail({errMsg:'private route detail'});else if(!options.hang)o.success();},
    getAccountInfoSync:() => ({miniProgram:{appId:'test-app'}}),
  };
  const context = {Page:d => {definition=d;}, wx, Promise,
    require:() => {imports++;if(options.moduleError)throw new SyntaxError('private module detail');return api;},
    setTimeout:fn => {const id=timers.size+1;timers.set(id,fn);return id;},
    clearTimeout:id => timers.delete(id),
  };
  vm.runInNewContext(fs.readFileSync(path.join(root,'pages/login/index.js'),'utf8'), context);
  definition.data=JSON.parse(JSON.stringify(definition.data));
  definition.setData=function(patch){Object.assign(this.data,patch);};
  return {page:definition, calls, timers, imports:() => imports, wx, api};
}

test('login shell registers before loading business modules or making requests', () => {
  const h=startup({moduleError:true});
  assert(h.page);
  assert.equal(h.imports(),0);
  h.page.onLoad();
  assert.equal(h.imports(),0);
  assert.equal(h.calls.length,0);
});

test('module failure after first render is visible and retryable, not an uncaught startup exception', async () => {
  const h=startup({moduleError:true});
  h.page.onLoad();
  await h.page.onReady();
  assert.equal(h.page.data.startupCode,'MODULE_LOAD');
  assert.match(h.page.data.error,/加载失败/);
  assert(!h.page.data.error.includes('private'));
  assert.equal(h.calls.length,0);
  await h.page.startup();
  assert.equal(h.imports(),2);
});

test('stored login redirects only after ready; no token or account data enters page data', async () => {
  const h=startup({token:'wxmp_private'});
  h.page.onLoad();
  assert.equal(h.calls.length,0);
  await h.page.onReady();
  assert.equal(h.calls.length,1);
  assert.equal(h.calls[0].url,'/pages/school/index');
  assert(!JSON.stringify(h.page.data).includes('wxmp_private'));
  assert.equal(h.timers.size,0);
});

test('navigation failure is reported without deleting authentication or looping', async () => {
  const h=startup({token:'wxmp_private',redirectError:true});
  h.page.onLoad();
  await h.page.onReady();
  assert.equal(h.page.data.startupCode,'PAGE_OPEN');
  assert.match(h.page.data.error,/打开失败/);
  assert.equal(h.page.data.checking,false);
  assert.equal(h.calls.length,1);
  assert.equal(h.timers.size,0);
});

test('a missing native navigation callback is bounded and duplicate retries do not navigate twice', async () => {
  const h=startup({token:'wxmp_private',hang:true});
  h.page.onLoad();
  const pending=h.page.onReady();
  await h.page.startup();
  assert.equal(h.calls.length,1);
  for(const fn of h.timers.values())fn();
  await pending;
  assert.equal(h.page.data.startupCode,'PAGE_OPEN');
  assert.equal(h.page.data.checking,false);
});

test('storage failure is visible without erasing unrelated phone storage', async () => {
  const h=startup({storageError:true});
  h.page.onLoad();
  await h.page.onReady();
  assert.equal(h.page.data.startupCode,'LOCAL_STORAGE');
  assert.equal(h.calls.length,0);
});

test('no saved login checks service and renders an offline state', async () => {
  const h=startup({requestError:new Error('网络连接失败')});
  h.page.onLoad();
  await h.page.onReady();
  assert.equal(h.page.data.serviceStatus,'暂时无法连接服务');
  assert.equal(h.page.data.error,'网络连接失败');
  assert.equal(h.page.data.checking,false);
  assert.equal(h.page.data.loginAvailable,false);
});

test('unloading during startup cancels the route watchdog and ignores late callbacks', async () => {
  const h=startup({token:'wxmp_private',hang:true});
  h.page.onLoad();
  const pending=h.page.onReady();
  h.page.onUnload();
  const saved=JSON.stringify(h.page.data);
  h.calls[0].fail({});
  await pending;
  assert.equal(h.timers.size,0);
  assert.equal(JSON.stringify(h.page.data),saved);
});

test('login preserves consent, stores only a valid token, then uses guarded navigation', async () => {
  const h=startup();
  const writes=[];
  h.wx.login=o => o.success({code:'one-time-code'});
  h.wx.setStorageSync=(key,value) => writes.push({key,value});
  h.api.request=async (url,method,data,options) => {
    assert.equal(url,'/api/v1/wechat/login');
    assert.equal(method,'POST');
    assert.equal(data.code,'one-time-code');
    assert.equal(options.auth,false);
    return {access_token:'wxmp_private'};
  };
  h.page.setData({loginAvailable:true});
  await h.page.login();
  assert.equal(writes.length,0);
  h.page.setData({consent:true});
  await h.page.login();
  assert.deepEqual(writes,[{key:'token',value:'wxmp_private'}]);
  assert.equal(h.calls[0].url,'/pages/school/index');
  assert.equal(h.page.data.busy,false);
  assert(!JSON.stringify(h.page.data).includes('wxmp_private'));
});

test('bad login responses do not navigate or store a session', async () => {
  for(const result of [null,{}, {access_token:42},{access_token:'wrong-prefix'}]){
    const h=startup();
    h.wx.login=o => o.success({code:'code'});
    h.wx.setStorageSync=() => assert.fail('must not store invalid token');
    h.api.request=async () => result;
    h.page.setData({consent:true,loginAvailable:true});
    await h.page.login();
    assert.equal(h.page.data.error,'登录响应无效');
    assert.equal(h.page.data.busy,false);
    assert.equal(h.calls.length,0);
  }
});

test('preflight response after leaving login cannot change an unloaded page', async () => {
  const h=startup();
  let resolve;
  h.api.request=() => new Promise(r => {resolve=r;});
  const pending=h.page.checkService();
  await Promise.resolve();
  h.page.onUnload();
  const saved=JSON.stringify(h.page.data);
  resolve({state:'ready',login_available:true});
  await pending;
  assert.equal(JSON.stringify(h.page.data),saved);
});
