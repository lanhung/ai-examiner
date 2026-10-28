const test=require('node:test');
const assert=require('node:assert/strict');
const {createSpeech}=require('../apps/wechat/miniprogram/lib/speech');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function deferred(){let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};}
function harness(){
  const calls=[],files=new Set(),states=[],texts=[],handlers={};
  const pending=new Map();let timerId=0,wallTime=0;
  const timers={setTimeout(fn,ms){pending.set(++timerId,{fn,ms});return timerId;},
    clearTimeout(id){pending.delete(id);}};
  const expire=ms=>{for(const [id,timer] of [...pending]){
    if(timer.ms===ms){pending.delete(id);timer.fn();}
  }};
  let audio, allow=true;
  const recorder={
    onStart:f=>handlers.start=f,offStart:()=>delete handlers.start,
    onStop:f=>handlers.stop=f,offStop:()=>delete handlers.stop,
    onError:f=>handlers.error=f,offError:()=>delete handlers.error,
    onInterruptionBegin:f=>handlers.interrupt=f,offInterruptionBegin:()=>delete handlers.interrupt,
    start:options=>{calls.push(['record',options]);handlers.start();},
    stop:()=>{calls.push(['stop']);return handlers.stop({tempFilePath:'/tmp/record.mp3',duration:3000});},
  };
  const wx={
    env:{USER_DATA_PATH:'/sandbox'},
    showModal:o=>{
      calls.push(['consent']);
      if(o.confirmText&&Array.from(o.confirmText).length>4){
        o.fail({errMsg:'showModal:fail confirmText length should not larger than 4 Chinese characters'});return;
      }
      o.success({confirm:allow});
    },
    requirePrivacyAuthorize:o=>o.success(),
    authorize:o=>{calls.push(['permission',o.scope]);o.success();},
    getRecorderManager:()=>recorder,
    getFileSystemManager:()=>({
      unlink:o=>{calls.push(['unlink',o.filePath]);files.delete(o.filePath);},
      writeFile:o=>{files.add(o.filePath);o.success();},
    }),
    createInnerAudioContext:()=>{
      audio={stop:()=>calls.push(['audio-stop']),destroy:()=>calls.push(['destroy']),
        play:()=>calls.push(['play']),onEnded:f=>audio.end=f,onError:f=>audio.error=f};
      return audio;
    },
  };
  const api={
    request:async(path,method,data)=>{
      calls.push(['request',path,method,data]);
      return path.endsWith('/context')?{available:true,question_key:'key'}:
        {audio_base64:'UklGRg==',format:'wav',segment:0,segments:1,question_key:'key'};
    },
    transcribe:async(path,file,key)=>{calls.push(['transcribe',path,file,key]);return {text:'spoken answer',question_key:key};},
  };
  const options={wx,api,timers,now:()=>wallTime,endpoint:()=>'/api/voice/attempt/id'};
  const speech=createSpeech({...options,changed:s=>states.push(s),transcript:t=>texts.push(t)});
  const nextPage=()=>{
    const states=[],texts=[];
    const speech=createSpeech({...options,changed:s=>states.push(s),transcript:t=>texts.push(t)});
    return {speech,states,texts};
  };
  return {speech,wx,api,recorder,handlers,calls,states,texts,files,pending,expire,nextPage,
    advance(ms){wallTime+=ms;},get audio(){return audio;},deny(){allow=false;}};
}
test('records only after consent, uses native MP3 and returns draft, never submits',async()=>{
  const h=harness();assert.equal(h.calls.length,0);
  await h.speech.record();
  assert.equal(h.states.at(-1).state,'recording');
  const options=h.calls.find(c=>c[0]==='record')[1];
  assert.equal(options.format,'mp3');assert.equal(options.duration,60000);
  assert.equal(options.sampleRate,16000);assert.equal(options.numberOfChannels,1);
  assert(h.calls.findIndex(c=>c[0]==='consent')<h.calls.findIndex(c=>c[0]==='record'));
  await h.speech.record();await tick();
  assert.deepEqual(h.texts,['spoken answer']);
  assert(h.calls.some(c=>c[0]==='unlink'&&c[1]==='/tmp/record.mp3'));
  assert(!h.calls.some(c=>JSON.stringify(c).includes('/answers')));
  h.speech.destroy();
});
test('consent rejection never records or calls provider',async()=>{
  const h=harness();h.deny();await h.speech.record();
  assert.equal(h.states.at(-1).state,'idle');
  assert(!h.calls.some(c=>['record','request','transcribe'].includes(c[0])));
  h.speech.destroy();
});
test('mic denial leaves text mode usable with clear error',async()=>{
  const h=harness();h.wx.authorize=o=>o.fail({});
  await h.speech.record();
  assert.match(h.states.at(-1).error,/麦克风授权未完成/);
  assert(!h.calls.some(c=>c[0]==='record'));h.speech.destroy();
});

test('privacy failure preserves wx errMsg without claiming microphone denial',async()=>{
  const h=harness();
  h.wx.requirePrivacyAuthorize=o=>o.fail({errMsg:'requirePrivacyAuthorize:fail privacy permission is not authorized'});
  await h.speech.record();
  assert.match(h.states.at(-1).error,/微信隐私授权未完成.*requirePrivacyAuthorize:fail/);
  assert(!h.calls.some(c=>['permission','record','request','transcribe'].includes(c[0])));
  h.speech.destroy();
});

test('authorize failure includes actual wx error instead of generic permission message',async()=>{
  const h=harness();h.wx.authorize=o=>o.fail({errMsg:'authorize:fail scope is not supported'});
  await h.speech.record();
  assert.match(h.states.at(-1).error,/麦克风授权未完成.*scope is not supported/);
  assert(!h.calls.some(c=>['record','request','transcribe'].includes(c[0])));
  h.speech.destroy();
});

test('confirmation window failure and missing authorize API are distinguishable',async()=>{
  const h=harness();h.wx.showModal=o=>o.fail({errMsg:'showModal:fail busy'});
  await h.speech.record();assert.match(h.states.at(-1).error,/语音确认窗口未打开.*busy/);
  h.wx.showModal=o=>o.success({confirm:true});delete h.wx.authorize;
  await h.speech.record();assert.match(h.states.at(-1).error,/麦克风授权未完成.*not supported/);
  assert(!h.calls.some(c=>c[0]==='record'));h.speech.destroy();
});
test('cancellation during permission never starts recorder',async()=>{
  const h=harness(), wait=deferred();
  h.wx.authorize=o=>wait.promise.then(o.success);
  const started=h.speech.record();await tick();h.speech.cancel();wait.resolve();
  await started;assert(!h.calls.some(c=>c[0]==='record'));h.speech.destroy();
});
test('cancellation while recording cleans temporary file and never uploads',async()=>{
  const h=harness();await h.speech.record();h.speech.cancel();await tick();
  assert(!h.calls.some(c=>c[0]==='transcribe'));assert.equal(h.texts.length,0);
  assert(h.calls.some(c=>c[0]==='unlink'));h.speech.destroy();
});

test('a queued second stop tap cannot reset the UI to idle while native stop is pending',async()=>{
  const h=harness();h.recorder.stop=()=>h.calls.push(['stop-pending']);
  await h.speech.record();await h.speech.record();await h.speech.record();
  const observed=h.states.at(-1);
  await h.handlers.stop({tempFilePath:'/tmp/record.mp3',duration:3000});
  h.speech.destroy();
  assert.equal(observed.state,'stopping');
  assert.equal(observed.error,'');
  assert.equal(h.calls.filter(c=>c[0]==='stop-pending').length,1);
});

test('cancel keeps recording controls busy until native stop confirms release',async()=>{
  const h=harness();h.recorder.stop=()=>{};
  await h.speech.record();h.speech.cancel();
  const observed=h.states.at(-1);
  await h.handlers.stop({tempFilePath:'/tmp/cancelled.mp3',duration:3000});
  assert.equal(h.states.at(-1).state,'idle');h.speech.destroy();
  assert.equal(observed.state,'stopping');
  assert.equal(h.texts.length,0);
});
test('late transcription after page hide or question change is discarded',async()=>{
  const h=harness(),wait=deferred();h.api.transcribe=()=>wait.promise;
  await h.speech.record();h.speech.record();await tick();
  assert.equal(h.states.at(-1).state,'transcribing');
  h.speech.cancel();wait.resolve({text:'stale answer',question_key:'key'});await tick();
  assert.equal(h.texts.length,0);assert.equal(h.states.at(-1).state,'idle');h.speech.destroy();
});
test('recorder interruption cancels rather than submitting partial audio',async()=>{
  const h=harness();await h.speech.record();h.handlers.interrupt();await tick();
  assert(!h.calls.some(c=>c[0]==='transcribe'));h.speech.destroy();
});
test('provider timeout preserves draft and does not retry paid operation',async()=>{
  const h=harness();let count=0;
  h.api.transcribe=async()=>{count++;throw new Error('timeout');};
  await h.speech.record();h.speech.record();await tick();
  assert.equal(count,1);assert.equal(h.texts.length,0);
  assert.equal(h.states.at(-1).error,'timeout');h.speech.destroy();
});
test('mismatched transcript key is never applied',async()=>{
  const h=harness();h.api.transcribe=async()=>({text:'other',question_key:'wrong'});
  await h.speech.record();h.speech.record();await tick();
  assert.equal(h.texts.length,0);assert.match(h.states.at(-1).error,/无效/);h.speech.destroy();
});
test('question speech stays on API, writes local WAV and cleans on end',async()=>{
  const h=harness();await h.speech.play();
  assert.equal(h.states.at(-1).state,'playing');assert.equal(h.files.size,1);
  assert(h.audio.src.startsWith('/sandbox/aiex-voice-'));
  h.audio.end();assert.equal(h.files.size,0);assert.equal(h.states.at(-1).state,'idle');
  h.speech.destroy();
});
test('starting answer stops playback before recording',async()=>{
  const h=harness();await h.speech.play();await h.speech.record();
  assert(h.calls.findIndex(c=>c[0]==='audio-stop')<h.calls.findIndex(c=>c[0]==='record'));
  assert.equal(h.files.size,0);h.speech.destroy();await tick();
});
test('late TTS response does not play after cancel',async()=>{
  const h=harness(),wait=deferred();
  const original=h.api.request;h.api.request=(path,...rest)=>path.endsWith('/speech')?wait.promise:original(path,...rest);
  const playing=h.speech.play();await tick();h.speech.cancel();
  wait.resolve({question_key:'key',format:'wav',audio_base64:'UklGRg==',segment:0,segments:1});
  await playing;assert.equal(h.files.size,0);assert(!h.calls.some(c=>c[0]==='play'));h.speech.destroy();
});
test('late events from stopped audio cannot stop a new playback',async()=>{
  const h=harness();await h.speech.play();const old=h.audio;
  h.speech.cancel();await h.speech.play();
  const stopped=h.calls.filter(c=>c[0]==='audio-stop').length;
  old.end();old.error();
  assert.equal(h.calls.filter(c=>c[0]==='audio-stop').length,stopped);
  assert.equal(h.states.at(-1).state,'playing');assert.equal(h.files.size,1);
  h.speech.destroy();
});
test('long questions play bounded segments in order',async()=>{
  const h=harness(),original=h.api.request;
  h.api.request=async(path,method,data)=>path.endsWith('/speech')?
    {question_key:'key',format:'wav',audio_base64:'UklGRg==',segment:data.segment,segments:2}:
    original(path,method,data);
  await h.speech.play();h.audio.end();await tick();
  assert.equal(h.calls.filter(c=>c[0]==='play').length,2);
  h.audio.end();assert.equal(h.states.at(-1).state,'idle');assert.equal(h.files.size,0);h.speech.destroy();
});
test('recording pending start is stopped on late start after disposal',async()=>{
  const h=harness();h.recorder.start=()=>{};
  await h.speech.record();h.speech.destroy();
  h.handlers.start();await tick();
  assert(!h.calls.some(c=>c[0]==='transcribe'));
  assert.equal(h.handlers.stop,undefined);
});
test('missing recorder stop callback releases busy state and permits another attempt',async()=>{
  const h=harness(),normalStop=h.recorder.stop;h.recorder.stop=()=>h.calls.push(['stop-pending']);
  await h.speech.record();const oldStop=h.handlers.stop;
  await h.speech.record();assert.equal(h.states.at(-1).state,'stopping');
  h.expire(5000);assert.equal(h.states.at(-1).state,'idle');
  assert.match(h.states.at(-1).error,/录音结束超时/);
  assert.equal(h.pending.size,0);assert.equal(h.handlers.stop,oldStop);
  h.recorder.stop=normalStop;await h.speech.record();
  const newStop=h.handlers.stop;
  await oldStop({tempFilePath:'/tmp/stale.mp3',duration:3000});
  assert.equal(h.handlers.stop,newStop);assert.equal(h.states.at(-1).state,'recording');
  assert(!h.calls.some(c=>c[0]==='transcribe'));
  await h.speech.record();await tick();assert.deepEqual(h.texts,['spoken answer']);
  h.speech.destroy();assert.equal(h.pending.size,0);
});

test('cancel with missing stop callback restores text mode but quarantines old audio',async()=>{
  const h=harness();h.recorder.stop=()=>{};
  await h.speech.record();h.speech.cancel();h.expire(5000);
  assert.equal(h.states.at(-1).state,'idle');assert.match(h.states.at(-1).error,/关闭小程序/);
  assert.equal(typeof h.handlers.stop,'function');
  await h.handlers.stop({tempFilePath:'/tmp/cancelled.mp3',duration:3000});
  const next=harness();await next.speech.record();
  assert.equal(next.states.at(-1).state,'recording');next.speech.destroy();
  h.speech.destroy();assert(!h.calls.some(c=>c[0]==='transcribe'));
});

test('WeChat recorder without off methods supports repeated recording without listener accumulation',async()=>{
  const h=harness(),listeners={},registrations={};
  for(const event of ['Start','Stop','Error','InterruptionBegin']){
    delete h.recorder['off'+event];
    h.recorder['on'+event]=callback=>{
      (listeners[event]??=[]).push(callback);
      registrations[event]=(registrations[event]||0)+1;
    };
  }
  h.recorder.start=()=>listeners.Start.forEach(callback=>callback());
  h.recorder.stop=()=>listeners.Stop.forEach(callback=>callback({tempFilePath:'/tmp/record.mp3',duration:3000}));
  for(let attempt=0;attempt<3;attempt++){
    await h.speech.record();assert.equal(h.states.at(-1).state,'recording');
    await h.speech.record();await tick();assert.equal(h.states.at(-1).state,'idle');
  }
  assert.equal(h.texts.length,3);
  assert.deepEqual(Object.values(registrations),[1,1,1,1]);
  h.speech.destroy();
  listeners.Stop.forEach(callback=>callback({tempFilePath:'/tmp/orphan.mp3',duration:3000}));
  assert.equal(h.texts.length,3);assert.equal(h.pending.size,0);
  assert(h.calls.some(call=>call[0]==='unlink'&&call[1]==='/tmp/orphan.mp3'));
});

test('missing recorder start and native auto-stop callbacks are bounded',async()=>{
  const h=harness(),normalStart=h.recorder.start;h.recorder.start=()=>{};h.recorder.stop=()=>{};
  await h.speech.record();h.expire(5000);
  assert.match(h.states.at(-1).error,/录音启动超时/);assert.equal(h.pending.size,0);
  h.handlers.start();
  await h.handlers.stop({tempFilePath:'/tmp/start-timeout.mp3',duration:3000});
  h.recorder.start=normalStart;await h.speech.record();h.expire(65000);
  assert.equal(h.states.at(-1).state,'stopping');h.expire(5000);
  assert.equal(h.states.at(-1).state,'idle');assert.equal(h.pending.size,0);
  await h.handlers.stop({tempFilePath:'/tmp/auto-stop-timeout.mp3',duration:3000});
  assert(!h.calls.some(c=>c[0]==='transcribe'));h.speech.destroy();
});

test('repeated taps during authorization or transcription do not restart recording',async()=>{
  const h=harness(),permission=deferred(),transcription=deferred();
  h.wx.authorize=o=>permission.promise.then(o.success);
  const first=h.speech.record();await tick();await h.speech.record();
  assert.equal(h.calls.filter(c=>c[0]==='consent').length,1);
  permission.resolve();await first;
  h.api.transcribe=()=>transcription.promise;
  await h.speech.record();await h.speech.record();await h.speech.play();
  assert.equal(h.states.at(-1).state,'transcribing');
  assert.equal(h.calls.filter(c=>c[0]==='record').length,1);
  transcription.resolve({text:'only one draft',question_key:'key'});await tick();
  assert.deepEqual(h.texts,['only one draft']);h.speech.destroy();
});

test('returning from background reconciles a suspended stop timer and safely retries',async()=>{
  const h=harness(),normalStop=h.recorder.stop;h.recorder.stop=()=>{};
  await h.speech.record();h.speech.cancel();h.advance(6000);h.speech.resume();
  assert.equal(h.states.at(-1).state,'idle');assert.match(h.states.at(-1).error,/未确认结束/);
  assert.equal(h.pending.size,0);assert.equal(h.texts.length,0);
  h.recorder.stop=normalStop;await h.speech.record();
  assert.equal(h.states.at(-1).state,'recording');
  assert(!h.calls.some(c=>c[0]==='transcribe'));
  await h.speech.record();await tick();assert.deepEqual(h.texts,['spoken answer']);
  h.speech.destroy();
});

test('returning from background bounds missing start and native duration events',async()=>{
  const h=harness(),normalStart=h.recorder.start;h.recorder.start=()=>{};
  await h.speech.record();h.advance(6000);h.speech.resume();
  assert.equal(h.states.at(-1).state,'idle');assert.match(h.states.at(-1).error,/未确认结束/);
  h.handlers.start();await tick();
  assert.equal(h.handlers.stop,undefined);assert.equal(h.texts.length,0);
  h.recorder.start=normalStart;await h.speech.record();h.advance(66000);h.speech.resume();
  await tick();assert.deepEqual(h.texts,['spoken answer']);h.speech.destroy();
});

test('another page waits for cancelled recording release and discards the old file',async()=>{
  const h=harness(),normalStop=h.recorder.stop;h.recorder.stop=()=>{};
  await h.speech.record();h.speech.destroy();const next=h.nextPage();
  const starting=next.speech.record();await tick();
  assert.equal(next.states.at(-1).state,'stopping');
  assert.equal(h.calls.filter(c=>c[0]==='record').length,1);
  await h.handlers.stop({tempFilePath:'/tmp/previous-page.mp3',duration:3000});
  await starting;assert.equal(next.states.at(-1).state,'recording');
  assert(!h.calls.some(c=>c[0]==='transcribe'));
  h.recorder.stop=normalStop;await next.speech.record();await tick();
  assert.deepEqual(next.texts,['spoken answer']);assert.deepEqual(h.texts,[]);
  next.speech.destroy();assert.equal(h.pending.size,0);
});

test('cancelling a new page while waiting never starts its microphone',async()=>{
  const h=harness();h.recorder.stop=()=>{};
  await h.speech.record();h.speech.destroy();const next=h.nextPage();
  const starting=next.speech.record();next.speech.cancel();
  await h.handlers.stop({tempFilePath:'/tmp/previous-page.mp3',duration:3000});await starting;
  assert.equal(h.calls.filter(c=>c[0]==='record').length,1);
  assert.equal(next.states.at(-1).state,'idle');assert.equal(h.pending.size,0);
  next.speech.destroy();
});

test('a hung recorder retry is bounded without releasing ownership or uploading uncertain audio',async()=>{
  const h=harness();h.recorder.stop=()=>{};
  await h.speech.record();await h.speech.record();h.expire(5000);
  const retry=h.speech.record();await tick();h.expire(5000);await retry;
  assert.equal(h.states.at(-1).state,'idle');assert.match(h.states.at(-1).error,/关闭小程序/);
  assert.equal(h.calls.filter(c=>c[0]==='record').length,1);
  assert.equal(h.pending.size,0);
  await h.speech.play();assert(!h.calls.some(c=>c[0]==='play'));
  await h.handlers.stop({tempFilePath:'/tmp/late-hung.mp3',duration:3000});
  assert(!h.calls.some(c=>c[0]==='transcribe'));h.speech.destroy();
});

test('no-off native Stop after timeout belongs to the old recording until confirmed',async()=>{
  const h=harness();
  for(const event of ['Start','Stop','Error','InterruptionBegin'])delete h.recorder['off'+event];
  const normalStop=h.recorder.stop;h.recorder.stop=()=>{};
  await h.speech.record();await h.speech.record();h.expire(5000);
  const dispatcher=h.handlers.stop,retry=h.speech.record();await tick();
  assert.equal(h.calls.filter(c=>c[0]==='record').length,1);
  await dispatcher({tempFilePath:'/tmp/old-native-event.mp3',duration:3000});await retry;
  assert.equal(h.states.at(-1).state,'recording');assert.equal(h.handlers.stop,dispatcher);
  assert(!h.calls.some(c=>c[0]==='transcribe'));
  h.recorder.stop=normalStop;await h.speech.record();await tick();
  assert.deepEqual(h.texts,['spoken answer']);h.speech.destroy();
});

test('late Start after a pre-start retry is explicitly stopped again',async()=>{
  const h=harness();h.recorder.start=()=>{};h.recorder.stop=()=>h.calls.push(['stop-pending']);
  await h.speech.record();h.expire(5000);const retry=h.speech.record();await tick();
  assert.equal(h.calls.filter(c=>c[0]==='stop-pending').length,1);
  h.handlers.start();assert.equal(h.calls.filter(c=>c[0]==='stop-pending').length,2);
  h.speech.cancel();await retry;
  await h.handlers.stop({tempFilePath:'/tmp/late-start.mp3',duration:3000});
  assert(!h.calls.some(c=>c[0]==='transcribe'));assert.equal(h.pending.size,0);h.speech.destroy();
});

test('an active recorder on another page is not stolen',async()=>{
  const h=harness();await h.speech.record();const next=h.nextPage();await next.speech.record();
  assert.match(next.states.at(-1).error,/另一段录音/);
  assert.equal(h.calls.filter(c=>c[0]==='record').length,1);
  assert(!h.calls.some(c=>c[0]==='stop'));next.speech.destroy();h.speech.destroy();
});

test('components are injected on demand, scoped to answer pages and microphone is declared',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const root=path.resolve(__dirname,'../apps/wechat/miniprogram');
  const app=JSON.parse(fs.readFileSync(path.join(root,'app.json')));
  assert(app.permission['scope.record'].desc);
  assert.equal(app.lazyCodeLoading,'requiredComponents');
  assert.equal((app.usingComponents||{})['voice-answer'],undefined);
  const answerPages=['pages/session/index','pages/exam-answer/index'];
  for(const route of app.pages){
    const wxml=fs.readFileSync(path.join(root,route+'.wxml'),'utf8');
    const configPath=path.join(root,route+'.json');
    const config=fs.existsSync(configPath)?JSON.parse(fs.readFileSync(configPath,'utf8')):{};
    const component=(config.usingComponents||{})['voice-answer'];
    if(answerPages.includes(route)){
      assert.equal(component,'/components/voice-answer/index');
      const base=path.join(root,component);
      for(const ext of ['.js','.json','.wxml','.wxss'])assert(fs.existsSync(base+ext));
      assert.equal(JSON.parse(fs.readFileSync(base+'.json','utf8')).component,true);
      assert(wxml.includes('<voice-answer '));assert(wxml.includes('voiceBusy'));
    }else{
      assert.equal(component,undefined,route);
      assert(!wxml.includes('<voice-answer '),route);
    }
  }
});
test('shared voice component exposes only per-turn speech controls',()=>{
  const fs=require('node:fs'),path=require('node:path');
  const file=path.resolve(__dirname,'../apps/wechat/miniprogram/components/voice-answer/index.wxml');
  const template=fs.readFileSync(file,'utf8');
  assert(!/realtime|rtState|rtStatus|rtError|rtUtterance/.test(template));
  for(const action of ['play','record','stop','settings']){
    assert(template.includes(`bindtap="${action}"`));
  }
});

test('shared component initializes only speech and preserves draft and lifecycle handling',()=>{
  const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
  const file=path.resolve(__dirname,'../apps/wechat/miniprogram/components/voice-answer/index.js');
  const calls=[],events=[],speech={};
  for(const name of ['record','play','cancel','resume','destroy'])speech[name]=()=>calls.push(name);
  let component,options;
  vm.runInNewContext(fs.readFileSync(file,'utf8'),{
    wx:{},Component:value=>component=value,
    require:name=>{
      if(name==='../../lib/api')return {};
      if(name==='../../lib/speech')return {createSpeech:value=>{options=value;return speech;}};
      assert.fail(`Unexpected controller dependency: ${name}`);
    }
  });
  const instance={
    data:{...component.data},properties:{disabled:false,endpoint:'/voice/session/test'},
    setData(value){Object.assign(this.data,value);},
    triggerEvent(name,value){events.push({name,...value});}
  };
  component.lifetimes.attached.call(instance);
  assert.equal(instance.realtime,undefined);
  assert.equal(component.methods.realtimeStart,undefined);
  assert.equal(options.endpoint(),'/voice/session/test');
  component.methods.play.call(instance);component.methods.record.call(instance);
  instance.properties.disabled=true;
  component.methods.play.call(instance);component.methods.record.call(instance);
  assert.deepEqual(calls,['play','record']);
  options.changed({state:'recording',error:''});
  options.changed({state:'recording',error:''});
  instance.properties.disabled=false;
  component.observers['endpoint, revision, disabled'].call(instance);
  assert.deepEqual(calls,['play','record']);
  options.transcript('editable draft');
  options.changed({state:'idle',error:''});
  assert.deepEqual(events,[
    {name:'busy',busy:true},{name:'transcript',text:'editable draft'},{name:'busy',busy:false}
  ]);
  component.methods.stop.call(instance);
  instance.properties.revision='next';
  component.observers['endpoint, revision, disabled'].call(instance);
  component.pageLifetimes.hide.call(instance);
  component.pageLifetimes.show.call(instance);
  component.lifetimes.detached.call(instance);
  assert.deepEqual(calls,['play','record','cancel','cancel','cancel','resume','destroy']);
});

test('submitting during recording does not toggle busy and cancel the recording',()=>{
  const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
  const file=path.resolve(__dirname,'../apps/wechat/miniprogram/pages/exam-answer/index.js');
  let page;
  vm.runInNewContext(fs.readFileSync(file,'utf8'),{require:()=>({}),Page:value=>page=value});
  page.data={voiceBusy:true};
  page.run=()=>assert.fail('recording must be guarded before run changes parent state');
  page.submit();
});
