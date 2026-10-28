const {test}=require('node:test');
const assert=require('node:assert/strict');
const {createRealtime}=require('../apps/wechat/miniprogram/lib/realtime');
const tick=()=>new Promise(r=>setImmediate(r));
function fixture(options={}) {
  const events={},sent=[],sends=[],states=[],texts=[],started=[],nodes=[],pending=new Map();let count=0;
  const timers={setTimeout(fn,ms){pending.set(++count,{fn,ms});return count;},clearTimeout(id){pending.delete(id);}};
  const callbacks={};const recorder={};
  for(const name of ['Start','Stop','Error','FrameRecorded']) {
    recorder['on'+name]=fn=>callbacks[name]=fn;
    recorder['off'+name]=fn=>{if(callbacks[name]===fn)delete callbacks[name];};
  }
  recorder.start=opts=>{started.push(opts);if(!options.delayStart)callbacks.Start();};
  recorder.stop=()=>{if(callbacks.Stop)callbacks.Stop({});};
  const socket={onOpen:fn=>events.open=fn,onMessage:fn=>events.message=fn,onClose:fn=>events.close=fn,
    onError:fn=>events.error=fn,close(){sent.push('closed');},send(opts){sends.push(opts);sent.push(JSON.parse(opts.data));
      if(opts.success&&!options.delaySend)opts.success();}};
  const audio={currentTime:0,destination:{},resume:async()=>{},close(){audio.closed=true;},
    createBuffer(ch,n,rate){assert.equal(ch,1);assert.equal(rate,24000);return {duration:n/rate,getChannelData:()=>new Float32Array(n)};},
    createBufferSource(){const node={connect(){},disconnect(){},start(){node.started=true;},stop(){node.stopped=true;}};nodes.push(node);return node;}};
  const wx={getRecorderManager:()=>recorder,createWebAudioContext:()=>audio,
    showModal:opts=>opts.success({confirm:options.consent!==false}),authorize:opts=>opts.success(),
    requirePrivacyAuthorize:opts=>opts.success(),
    arrayBufferToBase64:buffer=>Buffer.from(buffer).toString('base64'),
    base64ToArrayBuffer:text=>{const b=Buffer.from(text,'base64');return b.buffer.slice(b.byteOffset,b.byteOffset+b.length);}};
  const api={request:async()=>({question_key:'a'.repeat(64),realtime:{available:options.available!==false}}),connectVoice:()=>socket};
  const rt=createRealtime({wx,api,endpoint:()=>'/api/v1/wechat/voice/preview/id',timers,
    changed:value=>states.push(value),transcript:text=>texts.push(text)});
  const message=event=>events.message({data:JSON.stringify(event)});
  return {rt,events,sent,sends,states,texts,started,nodes,pending,callbacks,audio,message,api,wx};
}
async function connect(f) {await f.rt.start();f.events.open();f.message({type:'ready',seconds:180});}
test('native PCM streaming, playback, interruption and drafts only',async()=>{
  const f=fixture();await connect(f);
  assert.equal(f.started[0].format,'PCM');assert.equal(f.started[0].sampleRate,16000);
  f.callbacks.FrameRecorded({frameBuffer:new ArrayBuffer(4096)});
  assert.equal(f.sent[1].type,'input_audio_buffer.append');
  f.message({type:'response_started'});f.message({type:'audio',audio:'AAAAAA=='});
  assert.equal(f.nodes[0].started,true);f.message({type:'speech_started'});assert.equal(f.nodes[0].stopped,true);
  f.message({type:'audio',audio:'AAAAAA=='});assert.equal(f.nodes.length,1);
  f.message({type:'response_started'});f.message({type:'audio',audio:'AAAAAA=='});assert.equal(f.nodes.length,2);
  for(let i=0;i<2;i++)f.message({type:'transcript',role:'user',id:'u1',text:'My answer'});
  f.message({type:'transcript',role:'assistant',id:'a1',text:'Not an answer'});
  assert.deepEqual(f.texts,['My answer']);f.rt.cancel();assert.equal(f.audio.closed,true);
  assert.equal(f.states.at(-1).state,'idle');assert.equal(f.pending.size,0);
  f.message({type:'transcript',role:'user',id:'late',text:'ignored'});assert.equal(f.texts.length,1);
});
test('end waits for server confirmation and never resumes playback or auto-submits',async()=>{
  const f=fixture();await connect(f);f.rt.end();assert.equal(f.states.at(-1).state,'finishing');
  assert.equal([...f.pending.values()].some(x=>x.ms===4000),false);
  f.message({type:'response_started'});f.message({type:'audio',audio:'AAAAAA=='});
  assert.equal(f.nodes.length,0);
  f.message({type:'transcript',role:'user',id:'last',text:'Final text'});
  assert.ok(f.sent.some(x=>x.type==='finish'));
  f.message({type:'ended',message:'Transcription received'});
  assert.deepEqual(f.texts,['Final text']);assert.equal(f.states.at(-1).state,'idle');
  assert.equal(f.pending.size,0);
});
test('denied space and consent do not open microphone',async()=>{
  for(const opts of [{available:false},{consent:false}]){const f=fixture(opts);await f.rt.start();
    assert.equal(f.started.length,0);assert.equal(f.states.at(-1).state,'idle');f.rt.destroy();}
});
test('cancel during context request cannot resurrect recording',async()=>{
  const f=fixture();let resolve;f.api.request=()=>new Promise(r=>resolve=r);
  const promise=f.rt.start();f.rt.cancel();resolve({realtime:{available:true}});await promise;
  assert.equal(f.started.length,0);f.rt.destroy();
});
test('device without frames times out and releases microphone',async()=>{
  const f=fixture();await connect(f);[...f.pending.values()].find(x=>x.ms===5000).fn();
  assert.equal(f.states.at(-1).state,'idle');assert.match(f.states.at(-1).error,/PCM/);
  assert.equal(f.audio.closed,true);f.rt.destroy();
});
test('socket error and page destroy ignore late events',async()=>{
  const f=fixture();await connect(f);f.events.error();assert.equal(f.states.at(-1).state,'idle');
  f.rt.destroy();const n=f.states.length;f.events.close();await tick();assert.equal(f.states.length,n);
});

test('old socket send failure cannot stop a new connection',async()=>{
  const f=fixture();await connect(f);const old=f.sends[0];
  f.rt.cancel();await connect(f);old.fail();
  assert.equal(f.states.at(-1).state,'connected');f.rt.destroy();
});

test('finish flushes queued frames before starting the transcript deadline',async()=>{
  const f=fixture({delaySend:true});await connect(f);
  f.callbacks.FrameRecorded({frameBuffer:new ArrayBuffer(4096)});
  f.callbacks.FrameRecorded({frameBuffer:new ArrayBuffer(4096)});
  f.rt.end();assert.ok(!f.sent.some(e=>e.type==='finish'));
  assert.ok(![...f.pending.values()].some(x=>x.ms===12000));
  f.sends[1].success();f.sends[2].success();
  assert.equal(f.sent.at(-1).type,'finish');
  const timeout=[...f.pending.values()].find(x=>x.ms===12000);assert.ok(timeout);
  timeout.fn();assert.match(f.states.at(-1).error,/转写.*超时/);
  assert.equal(f.states.at(-1).state,'idle');f.rt.destroy();
});

test('stalled upload while finishing is bounded and reports missing confirmation',async()=>{
  const f=fixture({delaySend:true});await connect(f);
  f.callbacks.FrameRecorded({frameBuffer:new ArrayBuffer(4096)});f.rt.end();
  [...f.pending.values()].find(x=>x.ms===8000).fn();
  assert.equal(f.states.at(-1).state,'idle');assert.match(f.states.at(-1).error,/发送超时/);f.rt.destroy();
});

test('empty PCM frame is ignored and malformed frames fail closed',async()=>{
  for(const frame of [new ArrayBuffer(3),new ArrayBuffer(65538),null]){
    const f=fixture();await connect(f);
    f.callbacks.FrameRecorded({frameBuffer:new ArrayBuffer(0)});
    assert.equal(f.sent.filter(e=>e.type==='input_audio_buffer.append').length,0);
    assert.doesNotThrow(()=>f.callbacks.FrameRecorded({frameBuffer:frame}));
    assert.equal(f.states.at(-1).state,'idle');assert.match(f.states.at(-1).error,/音频帧/);f.rt.destroy();
  }
});

test('recorder missing onStart cannot leave an indefinitely connected session',async()=>{
  const f=fixture({delayStart:true});await connect(f);
  [...f.pending.values()].find(x=>x.ms===5000).fn();
  assert.equal(f.states.at(-1).state,'idle');assert.match(f.states.at(-1).error,/录音启动超时/);f.rt.destroy();
});
