const api=require('../../lib/api');
const {createSpeech}=require('../../lib/speech');
const labels={idle:'',authorizing:'正在准备麦克风',recording:'正在录音 · 最长 60 秒',
  stopping:'正在结束录音',transcribing:'正在识别语音',loading:'正在准备题目语音',playing:'正在朗读题目'};
Component({
  properties:{endpoint:String,disabled:Boolean,revision:String},
  data:{state:'idle',status:'',error:''},
  observers:{
    'endpoint, revision, disabled':function(){
      const next=[this.properties.endpoint,this.properties.revision,this.properties.disabled];
      const previous=this.voiceContext;
      this.voiceContext=next;
      if(previous && next.some((value,index)=>value!==previous[index]) && this.speech)this.speech.cancel();
    }
  },
  lifetimes:{
    attached(){
      this.voiceContext=[this.properties.endpoint,this.properties.revision,this.properties.disabled];
      this.voiceBusy=false;
      this.speech=createSpeech({wx,api,endpoint:()=>this.properties.endpoint,
        changed:({state,error})=>{
          this.setData({state,error,status:labels[state]});
          const busy=['authorizing','recording','stopping','transcribing'].includes(state);
          if(busy!==this.voiceBusy){this.voiceBusy=busy;this.triggerEvent('busy',{busy});}
        },
        transcript:text=>this.triggerEvent('transcript',{text}),
      });
    },
    detached(){if(this.speech)this.speech.destroy();}
  },
  pageLifetimes:{
    hide(){if(this.speech)this.speech.cancel();},
    show(){if(this.speech)this.speech.resume();}
  },
  methods:{
    record(){if(!this.properties.disabled)this.speech.record();},
    play(){if(!this.properties.disabled)this.speech.play();},
    stop(){this.speech.cancel();},
    settings(){wx.openSetting({});}
  }
});
