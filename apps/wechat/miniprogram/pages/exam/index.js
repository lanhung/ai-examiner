const school = require('../../lib/school');
const api = require('../../lib/api');
Page({
  data:{id:'',teacher:false,busy:false,error:'',exam:null,preview:null,grades:[],more:false,name:'',number:'',consent:false},
  onLoad(options){this.setData({id:options.id,teacher:options.teacher==='1'});},
  onShow(){this.refresh();},
  async run(fn){if(this.data.busy)return;this.setData({busy:true,error:''});try{await fn();}catch(e){this.setData({error:e.message});if(wx.pageScrollTo)wx.pageScrollTo({scrollTop:0,duration:0});}finally{this.setData({busy:false});}},
  async refresh(){await this.run(async()=>{
    // Owner-only detail uses the teacher route, including after closing enrollment.
    const exam=await school.request(`${this.data.teacher?'/teacher':''}/exams/${this.data.id}`);
    this.setData({exam:school.label(exam)});
    if(this.data.teacher)await this.loadGrades(false);
    if(exam.is_owner){
      const preview=await school.request(`/teacher/exams/${this.data.id}/preview`);
      this.setData({preview:preview?school.label(preview):null});
    }else this.setData({preview:null});
  });},
  async loadGrades(append){
    const rows=await school.request(`/teacher/exams/${this.data.id}/grades?offset=${append?this.data.grades.length:0}`);
    this.setData({grades:[...(append?this.data.grades:[]),...rows.map(school.label)],more:rows.length===50});
  },
  more(){this.run(()=>this.loadGrades(true));},
  material(){this.run(()=>api.openDocument(`/api/v1/school/exams/${this.data.id}/material`,this.data.exam.material_name.split('.').pop().toLowerCase()));},
  field(e){this.setData({[e.currentTarget.dataset.field]:e.detail.value});},
  consent(e){this.setData({consent:e.detail.value.includes('yes')});},
  join(){this.run(async()=>{
    if(this.data.teacher||this.data.exam?.is_owner)throw new Error('这是你发布的考试，请使用教师试答');
    if(!this.data.name.trim()||!this.data.consent)throw new Error('请填写姓名并确认向教师提交答卷与成绩');
    const attempt=await school.request(`/exams/${this.data.id}/join`,'POST',{student_name:this.data.name.trim(),student_number:this.data.number.trim()});
    wx.navigateTo({url:`/pages/exam-answer/index?id=${attempt.id}`});
  });},
  preview(){return this.run(async()=>{
    if(!this.data.exam?.is_owner)throw new Error('仅发布教师可试答');
    const preview=await school.request(`/teacher/exams/${this.data.id}/preview`,'POST');
    wx.navigateTo({url:`/pages/exam-answer/index?id=${preview.id}&preview=1`});
  });},
  grade(e){wx.navigateTo({url:`/pages/exam-answer/index?id=${e.currentTarget.dataset.id}&teacher=1`});},
  close(){this.run(async()=>{
    const result=await new Promise(resolve=>wx.showModal({title:'关闭考试报名',content:'新学生将不能参加，已开始的答卷仍可完成。',success:resolve,fail:()=>resolve({confirm:false})}));
    if(result.confirm)this.setData({exam:school.label(await school.request(`/teacher/exams/${this.data.id}/close`,'POST'))});
  });}
});
