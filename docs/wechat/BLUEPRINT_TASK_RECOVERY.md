# Blueprint Task Recovery

## Incident: 2026-10-23

Two mini-program blueprint requests submitted at 09:57 and 13:14 (Asia/Shanghai)
were still marked `running` after worker heartbeats and execution leases expired.
The request origin and account suffix were verified without reading paper content.
The available worker log starts at 13:17, but does not establish the exact cause
of either interruption. Do not attribute the incident to the phone or model alone.

## Behavior

- An authorized blueprint status read settles an expired `running` or `cancelling`
  lease. It does not dispatch work or call a model.
- An expired running blueprint becomes `failed`, with `worker_lease_expired`.
  A pending cancellation becomes `cancelled` instead.
- Compare-and-set checks protect concurrent heartbeats, completion and cancellation.
  The old worker token is invalidated; the transition is audited once.
- Broker redelivery of an expired blueprint does not repeat the paid handler.
- Existing documents, results and scores are not deleted. Retrying is explicit and
  can incur another model call; an interrupted call may already have incurred cost.
- Other job kinds retain their existing recovery policy. Queue delays and an expired
  worker lease are different conditions; elapsed generation time alone is not failure.
- Mini-program polling recognizes `dead_letter`, failure and cancellation, and
  unlocks material controls. Network errors retain the task ID, retry status reads
  twice, then pause for manual refresh. They never automatically submit a new job.

## Verification

Use an isolated local test database, never the live database even if its name
contains `test`:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_job_hardening_v09.py tests/test_blueprint_async.py -q
node --test tests/wechat_client.cjs tests/wechat_speech.cjs tests/wechat_realtime.cjs
```

These regression tests use deterministic provider stubs. They verify failure
handling and do not measure Qwen performance or certify real-phone behavior.

After deployment, reopen the workbench or refresh the saved task. An interrupted
task must stop waiting and preserve the uploaded material. Choose an existing
completed blueprint if available; request another generation only deliberately.

The server fix helps old clients recognize expired jobs as `failed`. The client
polling improvements require recompiling the development/preview package or
publishing an updated mini-program package. Application version stays unchanged.

## Deployment Verification

- 23 targeted backend tests passed; 80 mini-program client/speech tests passed.
- Ruff and `git diff --check` passed (Git emitted existing line-ending warnings).
- Deployed only the two reviewed server modules with preimage hash checks and
  rollback copies; API and worker restarted gracefully with their existing environments.
  `/health` and `/ready` returned 200, still using Qwen Plus and enforced PostgreSQL RLS.
- Under the existing application database role and each task's tenant/actor context,
  validated current authorization and settled only the two verified mobile requests.
  Both now return `failed / worker_lease_expired`, each has one audit event, and both
  source documents remain present. No model generation or grade update was invoked.
- Synced the workbench script to `D:\wechat\miniprogram\pages\work\index.js`
  after backing up the previous file; source hashes match.
- The updated message has not yet been verified on the user's physical phone.
  These fixes prevent indefinite waiting; they do not establish a generation speedup.
