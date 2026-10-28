// RecorderManager is application-wide. Only one recording owns its callbacks.
let recordingOwner = null;
let fileCounter = 0;
const recorderListeners = new WeakMap();
// WeChat RecorderManager does not provide offStart/offStop on every runtime.
// Keep one native listener per event when detaching is unavailable.
function listen(manager, event, callback, orphan) {
  const off = 'off' + event;
  if (typeof manager[off] === 'function') {
    manager['on' + event](callback);
    return () => {try {manager[off](callback);} catch (_) {}};
  }
  let slots = recorderListeners.get(manager);
  if (!slots) {slots = {}; recorderListeners.set(manager, slots);}
  if (!slots[event]) {
    const slot = {callback:null, orphan};
    manager['on' + event](result => (slot.callback || slot.orphan || (() => {}))(result));
    slots[event] = slot;
  }
  const slot = slots[event];
  slot.callback = callback;
  return () => {if (slot.callback === callback) slot.callback = null;};
}
function createSpeech({wx, api, endpoint, changed, transcript, timers={setTimeout,clearTimeout}, now=Date.now}) {
  let generation = 0, destroyed = false, consent = false, state = 'idle';
  let recording = null, audio = null, audioFile = null;
  let cancelWait = null;
  const recoveryMessage = '录音组件未确认结束，请点语音回答重试；仍失败请关闭小程序后重新打开，或使用文字回答';
  const emit = (next, error = '') => {
    state = next;
    if (!destroyed) changed({state:next, error});
  };
  const remove = file => {
    if (file) wx.getFileSystemManager().unlink({filePath:file, fail:()=>{}});
  };
  const stopAudio = () => {
    if (audio) {const old=audio; audio=null; old.stop(); old.destroy();}
    remove(audioFile); audioFile=null;
  };
  const current = ticket => !destroyed && ticket === generation;
  function cancel() {
    generation++;
    if(cancelWait)cancelWait();
    stopAudio();
    if (recording) {
      recording.cancelled = true;
      recording.cancelTicket = generation;
      emit('stopping');
      // If start is pending, onStart will stop it without uploading.
      if (recording.started) recording.stop();
      return;
    }
    emit('idle');
  }
  function resume() {
    if(destroyed)return;
    if(recordingOwner)recordingOwner.reconcile();
    if(recording && recording.timedOut)emit('idle',recoveryMessage);
  }
  function waitForRelease(owner) {
    if(owner.cleaned)return Promise.resolve(true);
    return new Promise(resolve=>{
      let timer, done=false;
      const finish=confirmed=>{
        if(done)return;done=true;
        timers.clearTimeout(timer);
        owner.waiters.delete(finish);
        if(cancelWait===abort)cancelWait=null;
        resolve(confirmed);
      };
      const abort=()=>finish(false);
      cancelWait=abort;
      owner.waiters.add(finish);
      timer=timers.setTimeout(abort,5000);
      if(owner.timedOut)owner.stop();
    });
  }
  const invoke = (name, options = {}) => new Promise((resolve, reject) => {
    const labels = {showModal:'语音确认窗口未打开',
      requirePrivacyAuthorize:'微信隐私授权未完成',authorize:'麦克风授权未完成'};
    const fail = error => {
      const detail = error && (error.errMsg || error.message);
      const reason = typeof detail === 'string' ? detail.replace(/[\r\n]/g, ' ').slice(0,180) : '';
      reject(new Error(`${labels[name] || '微信接口调用失败'}${reason ? `（${reason}）` : ''}`));
    };
    if (typeof wx[name] !== 'function') {fail({errMsg:`${name} is not supported`});return;}
    try {wx[name]({...options, success:resolve, fail});} catch(error) {fail(error);}
  });
  async function permission() {
    if (!consent) {
      const result = await invoke('showModal', {
        title:'使用语音问答',
        content:'录音将发送至服务器及阿里云千问进行转写；题目朗读也由千问合成。录音不进入成绩库，确认后的文字按答卷规则保存。',
        confirmText:'同意继续',
      });
      if (!result.confirm) throw new Error('已取消，可继续文字答题');
      consent = true;
    }
    if (wx.requirePrivacyAuthorize) await invoke('requirePrivacyAuthorize');
  }
  async function context(ticket) {
    const result = await api.request(endpoint() + '/context');
    if (!current(ticket)) return null;
    if (!result.available) throw new Error('语音尚未启用，请使用文字答题');
    return result;
  }
  async function record() {
    if (destroyed) return;
    resume();
    if (state === 'recording') {
      emit('stopping'); recording.stop(); return;
    }
    if(['authorizing','stopping','transcribing'].includes(state))return;
    const previous=recordingOwner;
    if(previous && !previous.cancelled && !previous.stopRequested) {
      emit('idle','麦克风正在另一段录音中使用，请先结束该录音');return;
    }
    cancel();
    const ticket = generation;
    if(previous && !previous.cleaned) {
      emit('stopping');
      const confirmed=await waitForRelease(previous);
      if(!current(ticket))return;
      if(!confirmed){emit('idle',recoveryMessage);return;}
    }
    emit('authorizing');
    try {
      await permission();
      if (!current(ticket)) return;
      await invoke('authorize', {scope:'scope.record'});
      if (!current(ticket)) return;
      const info = await context(ticket);
      if (!info) return;
      if (recordingOwner) throw new Error('麦克风正在使用，请稍后重试');
      const manager = wx.getRecorderManager();
      const owner = {manager, ticket, cancelled:false, started:false, cleaned:false,
        timedOut:false,stopRequested:false,waiters:new Set()};
      let startTimer,stopTimer,durationTimer;
      const startDeadline=now()+5000;
      let stopDeadline=0,durationDeadline=0;
      const detach = [];
      recording = recordingOwner = owner;
      const cleanup = () => {
        if(owner.cleaned)return;
        owner.cleaned=true;
        for(const timer of [startTimer,stopTimer,durationTimer])timers.clearTimeout(timer);
        if (recordingOwner === owner) recordingOwner = null;
        if (recording === owner) recording = null;
        for (const release of detach) release();
        for(const settle of [...owner.waiters])settle(true);
        if(current(owner.cancelTicket) && state==='stopping')emit('idle');
      };
      const expire = message => {
        if(owner.cleaned || owner.timedOut)return;
        owner.cancelled=true;
        owner.timedOut=true;
        for(const timer of [startTimer,stopTimer,durationTimer])timers.clearTimeout(timer);
        startTimer=stopTimer=durationTimer=undefined;
        // Native Stop events have no recording ID. Keep ownership until Stop/Error
        // confirms release so a delayed event cannot become the next answer.
        for(const settle of [...owner.waiters])settle(false);
        if(current(ticket) || current(owner.cancelTicket))emit('idle',message);
      };
      owner.stop = () => {
        if(owner.cleaned||stopTimer!==undefined)return;
        owner.stopRequested=true;
        owner.timedOut=false;
        timers.clearTimeout(durationTimer);
        stopDeadline=now()+5000;
        stopTimer=timers.setTimeout(()=>expire('录音结束超时。'+recoveryMessage),5000);
        try{manager.stop();}catch(_){expire('录音停止失败。'+recoveryMessage);}
      };
      owner.reconcile = () => {
        if(owner.cleaned || owner.timedOut)return;
        if(stopDeadline && now()>=stopDeadline)expire('录音结束超时。'+recoveryMessage);
        else if(!owner.started && now()>=startDeadline)expire('录音启动超时。'+recoveryMessage);
        else if(durationDeadline && now()>=durationDeadline){
          if(current(ticket))emit('stopping');
          owner.stop();
        }
      };
      const onStart = () => {
        if(owner.cleaned)return;
        timers.clearTimeout(startTimer);
        owner.started=true;
        if (!current(ticket) || owner.cancelled) {
          // A stop requested before native Start may not have stopped the mic.
          timers.clearTimeout(stopTimer);stopTimer=undefined;
          owner.stop();return;
        }
        emit('recording');
        durationDeadline=now()+65000;
        durationTimer=timers.setTimeout(()=>{
          if(owner.cleaned)return;
          if(current(ticket))emit('stopping');
          owner.stop();
        },65000);
      };
      const onError = () => {
        if(owner.cleaned)return;
        cleanup();
        if (current(ticket)) emit('idle','录音失败，请检查微信麦克风权限或改用文字');
      };
      const onInterrupt = () => {if(!owner.cleaned)cancel();};
      const onStop = async result => {
        if(owner.cleaned){remove(result && result.tempFilePath);return;}
        cleanup();
        const file = result && result.tempFilePath;
        try {
          if (!current(ticket) || owner.cancelled) return;
          if (!file || result.duration < 300) throw new Error('录音太短，请重新录音');
          emit('transcribing');
          const data = await api.transcribe(endpoint() + '/transcribe', file, info.question_key);
          if (!current(ticket)) return;
          if (data.question_key !== info.question_key || typeof data.text !== 'string' || !data.text.trim()) {
            throw new Error('识别结果无效，请重录');
          }
          transcript(data.text);
          emit('idle');
        } catch(e) {
          if (current(ticket)) emit('idle', e.message || '语音识别失败，请使用文字');
        } finally {remove(file);}
      };
      try {
        detach.push(listen(manager,'Start',onStart));
        detach.push(listen(manager,'Stop',onStop,result=>remove(result && result.tempFilePath)));
        detach.push(listen(manager,'Error',onError));
        if(manager.onInterruptionBegin)detach.push(listen(manager,'InterruptionBegin',onInterrupt));
        startTimer=timers.setTimeout(()=>expire('录音启动超时。'+recoveryMessage),5000);
        manager.start({duration:60000,sampleRate:16000,numberOfChannels:1,
          encodeBitRate:48000,format:'mp3'});
      } catch(e) {cleanup();throw e;}
    } catch(e) {
      if (current(ticket)) emit('idle', e.message || '语音启动失败，请重试或使用文字');
    }
  }
  async function play() {
    if (destroyed) return;
    resume();
    if(['authorizing','recording','stopping','transcribing','loading'].includes(state))return;
    if(recordingOwner){emit('idle',recoveryMessage);return;}
    cancel();
    const ticket=generation;
    emit('loading');
    try {
      await permission();
      if (!current(ticket)) return;
      const info=await context(ticket);
      if (!info) return;
      await segment(ticket, info, 0);
    } catch(e) {if(current(ticket))emit('idle',e.message || '朗读失败，请查看文字题目');}
  }
  async function segment(ticket, info, index) {
    if (!current(ticket)) return;
    emit('loading');
    const result=await api.request(endpoint()+'/speech','POST',{question_key:info.question_key,segment:index});
    if (!current(ticket)) return;
    if(result.question_key!==info.question_key || result.format!=='wav' ||
      typeof result.audio_base64!=='string' || !result.audio_base64 ||
      result.segment!==index || !Number.isInteger(result.segments) || result.segments<=index) {
      throw new Error('题目语音无效，请刷新题目');
    }
    const file=`${wx.env.USER_DATA_PATH}/aiex-voice-${Date.now()}-${++fileCounter}.wav`;
    await new Promise((resolve,reject)=>wx.getFileSystemManager().writeFile({
      filePath:file,data:result.audio_base64,encoding:'base64',success:resolve,
      fail:()=>reject(new Error('语音缓存失败，请检查设备空间')),
    }));
    if (!current(ticket)) {remove(file);return;}
    audioFile=file;
    const player=wx.createInnerAudioContext();
    audio=player;
    player.obeyMuteSwitch=false;
    player.onEnded(()=>{
      if (!current(ticket) || audio!==player) return;
      stopAudio();
      if(index+1<result.segments) {
        segment(ticket,info,index+1).catch(e=>{if(current(ticket))emit('idle',e.message || '朗读中断');});
      } else emit('idle');
    });
    player.onError(()=>{
      if (!current(ticket) || audio!==player) return;
      stopAudio();
      emit('idle','音频播放失败，可重新朗读或查看文字');
    });
    player.src=file;
    emit('playing');
    player.play();
  }
  return {record,play,cancel,resume,destroy(){cancel();destroyed=true;}};
}
module.exports={createSpeech};
