# Blueprint Wait Recovery: 2026-10-27

## Scope and Diagnosis

The user reported that uploading `OceanBigData_book.pdf` succeeds, but generating
a defense blueprint waits without a visible result. This is not an upload-size
failure: the local file is 584,017 bytes, 23 pages and 23,497 extracted characters.
A local parser baseline took 1.688 seconds and produced 513 evidence assets.
This baseline excludes phone upload, network and model generation time.

Verified production job records (Asia/Shanghai):

| Attempt | Time | Outcome |
| --- | --- | --- |
| First | 09:48:06 to 09:50:35; 148.75 s | Model output validation failed after three bounded question-wording repairs; an independent two-part question remained. |
| Second | 09:51:22 to 09:53:42; 140.28 s | Completed with six questions. The result remained stored even though the phone did not display it. |

The completed job used qwen-plus: initial call 128,616 ms, followed by three
wording repairs. It consumed 6,242 output tokens across four model calls.
Logs establish backend outcomes, but do not establish which phone network or
lifecycle event caused the missing display. Treat lost receipt/polling as possible
failure paths addressed by regression tests, not a proven phone diagnosis.

## Changes

- `GET /api/projects/{project_id}/blueprint-task?document_id=...` finds the caller's
  most recent matching task. Optional `request_id` finds the exact idempotent receipt.
  Authorization verifies organization, project, document and creating principal.
  The read can reconcile an expired lease but cannot create work or call a model.
- Persist the request ID and pending state before submitting a generation request.
  After a network error, preserve uncertain state and reuse that ID for an explicit
  resubmission. Never automatically create another paid generation.
- Recover a saved task/result when the workbench reopens, including when the local
  task pointer was lost. Provide a visible recovery button and prevent a concurrent
  generation/recovery race. Keep changes to source/model locked while uncertain.
- Resume polling correctly after hiding/showing the page during an in-flight read.
  Display generation, language repair, question repair round and validation stages,
  elapsed waiting time, and terminal failures. These stages are not token progress.
- Planner prompt `session-planner-v08-scenario-native-v10-concise` limits redundant
  prose and repeated output structures, without reducing the six questions, full
  supplied material, model, assessment schema or validation rules.
- Display a warning when a blueprint's source matching has failed. Completion is
  not equivalent to accepted assessment quality. Matching itself is not a semantic
  grounding guarantee, and the existing checker has limited short-quote coverage.

## PDF Resource Boundaries

Parsing runs in an isolated child process with bounded parallelism, a rendering
pixel cap and explicit handling for encrypted PDFs. Configuration defaults:

```dotenv
MAX_PDF_PAGES=500
DOCUMENT_PARSE_TIMEOUT_SECONDS=180
```

These are resource protections, not a promise of support for every 500-page PDF.
The mini-program's 20 MB and backend's 50 MB upload limits are unchanged. Resumable
uploads and asynchronous ingestion are not included. Expanding true large-file
support still requires representative size/page tests, proxy limits and storage
capacity checks; it must not be claimed from this relatively small PDF alone.

## Real Model Verification

One bounded qwen-plus probe used the same stored material and existing governance.
It did not save/replace a blueprint, publish an exam or modify a grade.

| Measurement | Previous completed job | New probe |
| --- | --- | --- |
| Total elapsed | 140.28 s | 98.51 s |
| Model calls | 4 | 2 |
| Output tokens | 6,242 | 4,348 |
| Main questions | 6 | 6 |
| Wording repairs | 3 | 1 |

The new run reported generation at 0.48 s, question repair at 87.8 s and validation
at 98.49 s. Three source references still failed matching. Existing stored
blueprints were verified unchanged. A single non-randomized comparison suggests
lower output/repair cost, but does not establish stable speedup, a p95 latency,
phone responsiveness or adequate question/quotation quality.

## Tests and Deployment

- 76 focused backend tests passed in an isolated Linux SQLite test database;
  15 dependency deprecation warnings. Included recovery authorization, Planner
  repair, model output, PDF limits, async blueprint, upload and language tests.
- 99 mini-program client, speech and startup tests passed, including uncertain
  submission, idempotency, lost-pointer recovery, lifecycle polling races, errors,
  source-match warning and generation/recovery conflict.
- Targeted Ruff checks passed. Windows regression execution also reached success
  but emitted an asyncio Proactor teardown access-violation diagnostic; the clean
  Linux rerun is the backend acceptance evidence, not an unqualified Windows pass.
- Eight reviewed backend files were deployed with preimage hash checks and backup.
  API and worker restarted gracefully using their existing environments. Health
  and readiness returned HTTP 200. No keys, tenant memberships or exam data changed.
- WeChat DevTools was used to select the existing PDF and click the recovery
  button. Its stored summary, all six questions and enabled text-session entry
  were displayed. No new generation or student answer was submitted through UI.

## Phone Acceptance and Remaining Work

Server fixes are active, but client changes require a newly compiled preview or
development/release package. A local DevTools compile does not update a previously
installed phone package. In the new package, select the existing project/material,
use the selected material, then choose the blueprint recovery button. Do not upload
or generate again solely to retrieve the existing result.

Still pending: physical-phone verification after package refresh; repeated latency
measurements; further source-quote validation and representative genuinely large
PDF tests. Application version remains 0.9. No GitHub push is part of this fix.
