const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/ai_examiner/static/app.js', 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));

function setup(organizationId = 'tenant-a') {
  const elements = new Map();
  const nodes = () => ({connect() {}, disconnect() {}});
  let closed = 0, stopped = 0;
  const stream = {getTracks: () => [{stop() { stopped++; }}], getAudioTracks: () => [{enabled: false}]};
  class AudioContext {
    constructor() { this.currentTime = 0; }
    async resume() {}
    async close() { closed++; }
    createMediaStreamSource() { return nodes(); }
    createScriptProcessor() { return nodes(); }
    createGain() { return {...nodes(), gain: {value: 1}}; }
  }
  class WebSocket {
    static OPEN = 1;
    constructor(url) { this.url = url; this.readyState = 1; }
    close() { this.readyState = 3; this.onclose?.(); }
    send() {}
    emit(type, extra = {}) { this.onmessage({data: JSON.stringify({type, ...extra})}); }
  }
  const state = {organizationId, voiceSessionId: 'voice-a', voiceStream: stream, blueprintId: 'bp-a'};
  const statuses = [];
  const context = vm.createContext({
    state, URL, WebSocket, setTimeout, clearTimeout, console,
    window: {AudioContext}, location: {protocol: 'https:', host: 'exam.test'},
    $: id => {
      if (!elements.has(id)) elements.set(id, {classList: {add() {}, remove() {}}});
      return elements.get(id);
    },
    setVoiceVisual() {}, setStatus: (...args) => statuses.push(args),
    handleRealtimeEvent() {}, stopQwenPlayback() {},
    api: async () => ({}), selectedVoiceProvider: () => ({ready: true}),
  });
  vm.runInContext(source.slice(source.indexOf('async function connectQwenVoice('), source.indexOf('async function connectVoice(')), context);
  vm.runInContext(source.slice(source.indexOf('async function endVoice('), source.indexOf('$("muteVoice").onclick')), context);
  return {context, state, stream, statuses, closed: () => closed, stopped: () => stopped};
}

(async () => {
  const app = setup('tenant / 中文');
  let resolved = false;
  const pending = app.context.connectQwenVoice({id: 'voice-a'}, app.stream).then(() => { resolved = true; });
  await tick();
  const socket = app.state.voiceSocket;
  const url = new URL(socket.url);
  assert.equal(url.searchParams.get('organization_id'), 'tenant / 中文');
  assert.equal(url.searchParams.has('token'), false);
  socket.onopen();
  socket.emit('session.created');
  await tick();
  assert.equal(resolved, false, 'Proxy/session.created must not mark the model ready');
  socket.emit('session.updated');
  await pending;
  assert.equal(resolved, true);
  socket.emit('error', {error: {message: 'Model not exist'}});
  await tick();
  assert.equal(app.state.voiceSocket, null);
  assert.equal(app.state.voiceStream, null);
  assert.equal(app.closed(), 1);
  assert.equal(app.stopped(), 1);
  assert.equal(app.statuses.at(-1)[1], 'Model not exist');

  for (const mode of ['close', 'error', 'model-error']) {
    const failed = setup(null);
    const connecting = failed.context.connectQwenVoice({id: 'voice-a'}, failed.stream);
    const rejection = assert.rejects(connecting);
    await tick();
    const connection = failed.state.voiceSocket;
    assert.equal(new URL(connection.url).search, '');
    if (mode === 'close') connection.close();
    if (mode === 'error') connection.onerror();
    if (mode === 'model-error') connection.emit('error', {error: {message: 'Model not exist'}});
    await rejection;
    await failed.context.endVoice('connection_failed');
    assert.equal(failed.stopped(), 1);
  }
  const failedStart = setup();
  failedStart.context.connectVoice = async () => { throw Error('Model not exist'); };
  await failedStart.context.$('startVoice').onclick();
  assert.equal(failedStart.statuses.at(-1)[1], 'Model not exist', 'Cleanup must not overwrite the error');
  console.log('Qwen browser: tenant URL, readiness, rejection, close/error cleanup and persistent error passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
