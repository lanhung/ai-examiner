const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('src/ai_examiner/static/app.js', 'utf8');
const block = source.slice(source.indexOf('const evidencePreviewState ='), source.indexOf('async function pollJob('));
let requests = [];
let revoked = [];
let sequence = 0;
let response = {ok: true, blob: async () => new Blob(['png'], {type: 'image/png'})};
class TestURL extends URL {}
TestURL.createObjectURL = () => `blob:test-${++sequence}`;
TestURL.revokeObjectURL = url => revoked.push(url);
const context = vm.createContext({
  URL: TestURL, AbortController,
  window: {location: {origin: 'https://exam.test'}},
  fetch: async (url, options) => { requests.push({url, options}); return response; },
  $: () => ({replaceChildren() {}}),
});
vm.runInContext(block, context);
vm.runInContext('var state = {organizationId: "org-a"};', context);
vm.runInContext(source.slice(source.indexOf('function blueprintRequestKeyFor('), source.indexOf('$("generateBlueprint").onclick')), context);
const payload = {document_id: 'doc-a', profile: 'ollama:qwen2.5:14b', template_version_id: 'v1'};
const key = context.blueprintRequestKeyFor('project-a', payload);
assert.equal(context.blueprintRequestKeyFor('project-a', {...payload}), key);
for (const changed of [{...payload, profile: 'qwen:qwen-plus'}, {...payload, document_id: 'doc-b'}, {...payload, template_version_id: 'v2'}, {...payload, template_overrides: {question_limit: 3}}]) {
  assert.notEqual(context.blueprintRequestKeyFor('project-a', changed), key);
}
assert.notEqual(context.blueprintRequestKeyFor('project-b', payload), key);
context.state.organizationId = 'org-b';
assert.notEqual(context.blueprintRequestKeyFor('project-a', payload), key);
context.state.blueprintRequestKey = null;
assert.notEqual(context.blueprintRequestKeyFor('project-a', payload), key);
const asset = {file_url: '/api/evidence/page/file', authorized_file_url: '/api/v1/evidence/page/file'};
async function run(item = asset, organization = 'tenant-a', signal = new AbortController().signal, broken = false) {
  const image = {hidden: true, decode: async () => { if (broken) throw Error('decode failed'); }};
  const status = {};
  const ok = await context.loadEvidenceImage(item, image, status, organization, signal);
  return {ok, image, status};
}
(async () => {
  const success = await run();
  assert.equal(success.ok, true);
  assert.equal(success.image.hidden, false);
  assert.equal(requests[0].url, 'https://exam.test/api/v1/evidence/page/file');
  assert.equal(requests[0].options.headers['X-AI-Examiner-Organization'], 'tenant-a');
  assert.equal(requests[0].options.credentials, 'same-origin');
  assert.equal(requests[0].options.cache, 'no-store');
  context.clearEvidencePreviews();
  assert.ok(revoked.includes(success.image.src));
  await run(asset, null);
  assert.equal(requests.at(-1).url, 'https://exam.test/api/evidence/page/file');
  assert.equal(requests.at(-1).options.headers['X-AI-Examiner-Organization'], undefined);
  for (const [code, message] of [[401, '登录已过期'], [403, '没有查看'], [404, '不存在'], [500, 'HTTP 500']]) {
    response = {ok: false, status: code};
    const result = await run();
    assert.equal(result.ok, false);
    assert.ok(result.status.textContent.includes(message));
    assert.equal(result.image.hidden, true);
  }
  const before = requests.length;
  assert.equal((await run({})).ok, false);
  assert.equal((await run({file_url: 'https://foreign.test/file'})).ok, false);
  assert.equal(requests.length, before);
  response = {ok: true, blob: async () => new Blob(['login page'], {type: 'text/html'})};
  assert.equal((await run()).ok, false);
  response = {ok: true, blob: async () => new Blob(['png'], {type: 'image/png'})};
  const aborted = new AbortController();
  aborted.abort();
  const count = sequence;
  assert.equal((await run(asset, 'tenant-a', aborted.signal)).ok, false);
  assert.equal(sequence, count);
  const broken = await run(asset, 'tenant-a', undefined, true);
  assert.equal(broken.ok, false);
  assert.ok(revoked.includes(broken.image.src));
  context.clearEvidencePreviews();
  console.log('Evidence preview auth, failures, legacy mode and cleanup passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
