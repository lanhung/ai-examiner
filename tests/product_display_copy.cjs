const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/ai_examiner/static/app.js', 'utf8');
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf('function productDisplayCopy('), source.indexOf('function templateMode(')), context);
for (const title of ['论文答辩训练', '基金申请评审训练', '课程口试训练', '产品知识训练', '销售异议训练', '技术面试训练']) {
  const original = {'zh-CN': title, en: 'Training'};
  assert.ok(!context.localized(original).includes('训练'));
  assert.equal(original['zh-CN'], title);
}
assert.equal(context.localized({'zh-CN': '论文答辩训练'}), '论文答辩');
assert.equal(context.productDisplayCopy('训练集与模型训练过程'), '训练集与模型训练过程');
assert.equal(context.productDisplayCopy('用户自己写的训练记录'), '用户自己写的训练记录');
assert.equal(context.localized({en: 'Training'}), 'Training');
assert.equal(context.localized(null), '');
const notice = context.productDisplayCopy('本报告仅用于训练，不得用于自动作出招聘、晋升或解雇决定。');
assert.ok(!notice.includes('训练'));
assert.ok(notice.includes('不得用于自动作出招聘、晋升或解雇决定'));
const html = fs.readFileSync('src/ai_examiner/static/index.html', 'utf8');
assert.ok(!html.includes('训练'));
assert.ok(html.includes('value="我的论文答辩"'));
assert.ok(html.includes('app.js?rev=product-copy-20260907'));
console.log('Product display copy checks passed');
