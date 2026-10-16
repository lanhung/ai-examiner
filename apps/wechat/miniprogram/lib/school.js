const api = require('./api');
const ROOT = '/api/v1/school';
function id() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.floor(Math.random() * 16);
    return (c === 'x' ? r : (r & 3) | 8).toString(16);
  });
}
const labels = {published:'开放中',closed:'已关闭报名',active:'作答中',grading:'评分中',needs_review:'待教师处理',completed:'已完成'};
function label(item) { return {...item, statusLabel:labels[item.status] || item.status}; }
module.exports = {ROOT, id, label, request:(path,method='GET',data)=>api.request(ROOT+path,method,data)};
