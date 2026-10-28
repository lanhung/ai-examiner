// Native PCM only: never send credentials to the model provider or persist audio.
let recorderOwner=null;
function createRealtime({wx,api,endpoint,changed,transcript,assistant=()=>{},timers=globalThis}) {
  let state='idle',error='',generation=0,disposed=false,socket=null,recorder=null,context=null;
  let recording=false,stopping=false,nextTime=0,dropAudio=false,ready=false,receivedFrame=false;
  let queue=[],queuedBytes=0,sending=false,sources=new Set(),seen=new Set(),timeouts=[];
  let stopCallback=null,frameCallback=null,startCallback=null,errorCallback=null,interruptionCallback=null;
  let finishing=false,finishSent=false;
  const emit=(s,message=error)=>{state=s;error=message;if(!disposed)changed({state,error});};
  const later=(fn,ms)=>{const id=timers.setTimeout(fn,ms);timeouts.push(id);return id;};
  const valid=ticket=>ticket===generation&&!disposed;
  const send=event=>{
    const ticket=generation;
    try{if(socket)socket.send({data:JSON.stringify(event),
      fail:()=>{if(valid(ticket))fail('语音连接中断，请重新开始');}});}
    catch(_){if(valid(ticket))fail('语音连接中断，请重新开始');}
  };
  function silence() {
    for(const source of sources){try{source.stop();source.disconnect();}catch(_){}}
    sources.clear();nextTime=0;dropAudio=true;
  }
  function unbind() {
    if(!recorder)return;
    for(const [name,fn] of [['Stop',stopCallback],['Start',startCallback],['Error',errorCallback],
      ['FrameRecorded',frameCallback],['InterruptionBegin',interruptionCallback]]) {
      if(recorder['off'+name]&&fn)recorder['off'+name](fn);
    }
    recorder=null;recording=false;stopping=false;
    if(recorderOwner===owner)recorderOwner=null;
  }
  function cleanup(message='') {
    ++generation;ready=false;finishing=false;finishSent=false;queue=[];queuedBytes=0;sending=false;
    for(const id of timeouts)timers.clearTimeout(id);timeouts=[];
    if(socket){const old=socket;socket=null;try{old.close({code:1000});}catch(_){}}
    silence();if(context){try{context.close();}catch(_){}context=null;}
    if(recorder){stopping=true;emit('stopping',message);try{recorder.stop();}catch(_){unbind();emit('idle',message);}}
    else emit('idle',message);
  }
  function fail(message){cleanup(message);}
  function pump(ticket) {
    if(!valid(ticket)||sending||!socket)return;
    if(!queue.length){
      if(finishing&&!recorder&&!finishSent){
        finishSent=true;send({type:'finish'});
        // Start the transcript deadline only after all recorded frames have been sent.
        if(valid(ticket))later(()=>{if(valid(ticket)){
          send({type:'stop'});cleanup('最后一句转写等待超时，请核对草稿并补充未识别内容');
        }},12000);
      }
      return;
    }
    const frame=queue.shift();queuedBytes-=frame.byteLength;sending=true;
    try{socket.send({data:JSON.stringify({type:'input_audio_buffer.append',audio:wx.arrayBufferToBase64(frame)}),
      success:()=>{if(valid(ticket)){sending=false;pump(ticket);}},
      fail:()=>{if(valid(ticket))fail('音频发送失败，请检查网络');}});}
    catch(_){if(valid(ticket))fail('音频发送失败，请检查网络');}
  }
  function play(encoded,ticket) {
    if(dropAudio||!context)return;
    const bytes=wx.base64ToArrayBuffer(encoded);
    if(bytes.byteLength%2||bytes.byteLength>1048576)throw new Error('音频格式无效');
    const samples=new DataView(bytes),buffer=context.createBuffer(1,bytes.byteLength/2,24000);
    const channel=buffer.getChannelData(0);
    for(let i=0;i<channel.length;i++)channel[i]=samples.getInt16(i*2,true)/32768;
    if(nextTime-context.currentTime>30)throw new Error('音频播放积压，请使用耳机后重试');
    const source=context.createBufferSource();source.buffer=buffer;source.connect(context.destination);
    nextTime=Math.max(context.currentTime+0.02,nextTime);sources.add(source);
    source.onended=()=>{sources.delete(source);try{source.disconnect();}catch(_){};};
    if(valid(ticket)){source.start(nextTime);nextTime+=buffer.duration;}
  }
  function beginRecording(ticket) {
    if(recorderOwner&&recorderOwner!==owner)throw new Error('麦克风仍在使用，请稍后重试');
    recorder=wx.getRecorderManager();recorderOwner=owner;
    stopCallback=result=>{
      if(result&&result.tempFilePath&&wx.getFileSystemManager) {
        wx.getFileSystemManager().unlink({filePath:result.tempFilePath,fail:()=>{}});
      }
      unbind();if(!valid(ticket)){if(!disposed)emit('idle');}
      else if(finishing)pump(ticket);
      else cleanup('录音已停止，请确认草稿');
    };
    startCallback=()=>{recording=true;if(!valid(ticket)||stopping){recorder.stop();return;}
      emit('connected','');later(()=>{if(valid(ticket)&&!finishing&&!receivedFrame)fail('未收到 PCM 音频帧，请使用真机调试或录音答题');},5000);};
    errorCallback=()=>{unbind();if(valid(ticket))fail('此设备无法实时录制 PCM，请使用录音答题');else if(!disposed)emit('idle');};
    interruptionCallback=()=>{if(valid(ticket))fail('录音被系统中断，请重新开始');};
    frameCallback=event=>{
      if(!valid(ticket)||!ready)return;
      const frame=event&&event.frameBuffer;
      if(!(frame instanceof ArrayBuffer)||frame.byteLength%2||frame.byteLength>65536){
        fail('设备返回了无效音频帧，请使用录音答题');return;
      }
      if(!frame.byteLength)return;
      receivedFrame=true;queue.push(frame.slice(0));queuedBytes+=frame.byteLength;
      if(queuedBytes>256000){fail('网络过慢，实时语音已停止');return;}pump(ticket);
    };
    recorder.onStart(startCallback);recorder.onStop(stopCallback);recorder.onError(errorCallback);
    recorder.onFrameRecorded(frameCallback);
    if(recorder.onInterruptionBegin)recorder.onInterruptionBegin(interruptionCallback);
    recorder.start({format:'PCM',sampleRate:16000,numberOfChannels:1,frameSize:4,duration:240000,
      audioSource:'voice_communication'});
    later(()=>{if(valid(ticket)&&!finishing&&!recording)fail('录音启动超时，请检查麦克风权限后重试');},5000);
  }
  async function start() {
    if(disposed||state!=='idle')return;
    const ticket=++generation;emit('authorizing','');seen=new Set();receivedFrame=false;
    try {
      if(!wx.createWebAudioContext||!wx.getRecorderManager||!wx.getRecorderManager().onFrameRecorded) {
        throw new Error('微信版本不支持实时音频，请升级微信或使用录音答题');
      }
      const path=endpoint(),config=await api.request(path+'/context');
      if(!valid(ticket))return;
      if(!config.realtime||!config.realtime.available)throw new Error('此空间尚未启用实时语音');
      const consent=await new Promise((resolve,reject)=>wx.showModal({title:'实时语音答辩',
        content:'麦克风音频将经服务器发送给阿里云千问实时模型。转写会进入草稿，确认提交后才评分。是否开始？',
        success:resolve,fail:reject}));
      if(!valid(ticket))return;
      if(!consent.confirm){cleanup();return;}
      if(wx.requirePrivacyAuthorize)await new Promise((resolve,reject)=>wx.requirePrivacyAuthorize({success:resolve,fail:reject}));
      if(!valid(ticket))return;
      await new Promise((resolve,reject)=>wx.authorize({scope:'scope.record',success:resolve,fail:reject}));
      if(!valid(ticket))return;
      context=wx.createWebAudioContext();await context.resume();
      if(!valid(ticket))return;
      emit('connecting','');socket=api.connectVoice(path+'/realtime');
      socket.onOpen(()=>{if(valid(ticket))send({type:'start',question_key:config.question_key});});
      socket.onMessage(({data})=>{
        if(!valid(ticket))return;
        try {
          const event=JSON.parse(data);
          if(event.type==='ready'&&!ready){ready=true;dropAudio=false;beginRecording(ticket);
            later(()=>{if(valid(ticket))end();},event.seconds*1000);}
          else if(event.type==='response_started'&&!finishing){dropAudio=false;}
          else if(event.type==='audio'){play(event.audio,ticket);}
          else if(event.type==='speech_started'){silence();}
          else if(event.type==='transcript'){
            const key=event.role+':'+event.id;
            if(event.role==='user'&&!seen.has(key)){seen.add(key);transcript(event.text);}
            if(event.role==='assistant')assistant(event.text);
          } else if(event.type==='ended'){cleanup(event.message||'语音已结束，请确认草稿');}
          else if(event.type==='error'){fail(event.message||'实时语音服务暂不可用');}
        }catch(e){fail(e.message||'语音消息处理失败');}
      });
      socket.onError(()=>{if(valid(ticket))fail('WSS 连接失败，请检查 socket 合法域名及网络');});
      socket.onClose(()=>{if(valid(ticket))cleanup('语音连接已结束，请确认已收到的草稿');});
      later(()=>{if(valid(ticket)&&!ready)fail('实时语音连接超时');},25000);
    }catch(e){if(valid(ticket))fail(e.message||'麦克风授权未完成，请检查权限');}
  }
  function end() {
    if(state==='idle'||state==='finishing'||state==='stopping')return;
    if(!ready){cleanup();return;}
    const ticket=generation;finishing=true;emit('finishing','');silence();
    later(()=>{if(valid(ticket)&&!finishSent)fail('最后的音频发送超时，请核对草稿并重新录制遗漏内容');},8000);
    if(recorder){recording=false;try{recorder.stop();}catch(_){fail('录音结束失败，请核对草稿后重试');}}
    else pump(ticket);
  }
  const owner={start,end,cancel:()=>cleanup(),interrupt:()=>{silence();send({type:'interrupt'});},
    destroy:()=>{disposed=true;cleanup();}};
  return owner;
}
module.exports={createRealtime};
