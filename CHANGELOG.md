# Changelog

## Unreleased - Review Correctness and Durable Receipts (2026-10-27)

- Bind exam publication retries to the exact blueprint, model and settings.
  Revalidate every selected source quote and page at publication; empty or
  invented short quotes no longer pass, and a cached passed flag is not trusted.
- Add durable personal-session operation receipts, turn-count reservations and
  lease-fenced result commits. Recover an uncertain submission by its request ID.
  Preserve drafts on failure and never automatically replay unknown model outcomes.
- Queue student and isolated teacher-preview grading. Preserve answers while
  waiting for governance admission, poll on page resume, and retain reviewable
  failures after a lost worker. Only confirmed pre-call capacity/rate denials retry.
- Add asynchronous document ingestion with source persistence, actor-scoped
  receipts, idempotent completion and explicit parsing retry without re-upload.
  Bound PDF/DOCX/PPTX parsing and parser-slot waits; validate Office archive limits.
- Preserve DOCX paragraph/table reading order; display parsed character counts,
  truncation warnings and logical-page limitations in the mini-program.
- Guard stale retry requests and duplicate-upload races. Keep legacy synchronous
  endpoints for compatibility; deploy API and workers before the updated mini-program.
- Keep application version 0.9.0. These changes are local and not deployed or
  pushed. See `docs/evaluation/PROJECT_REVIEW_2026-10-27.md` for regression evidence,
  deployment order and outstanding PostgreSQL/real-device/real-model acceptance.

## Unreleased - Blueprint Wait Recovery (2026-10-27)

- Trace the reported PDF wait to Planner wording validation and slow Qwen output,
  not upload size. Recover the existing six-question result through WeChat DevTools.
- Add a tenant-, project-, document- and principal-scoped blueprint task lookup.
  Preserve the request ID before submission, recover uncertain receipts without
  creating another paid job, and fix polling after page hide/show races.
- Show actual generation/wording-repair stages, elapsed time, terminal errors and
  failed source-match warnings. Prevent generation while recovery is in progress.
- Use concise Planner v10 output instructions without reducing question count or
  material input. A single real qwen-plus run took 98.51 seconds versus the previous
  completed job's 140.28 seconds; two calls versus four. This is not a latency SLA.
  Three source quotes still failed matching; semantic quality is not fully accepted.
- Bound PDF parsing in a child process with configurable timeout/page limits and
  a rendering pixel cap. Do not raise upload limits or introduce async ingestion.
- Pass 76 isolated Linux backend tests and 99 client/speech/startup tests. Deploy
  the reviewed backend changes with backups and healthy API/worker restart. Keep 0.9.
- See `docs/wechat/BLUEPRINT_WAIT_RECOVERY_2026-10-27.md` for evidence and limits.

## Unreleased - School Exam Admission and Grade Acceptance (2026-10-26)

- Reproduce a real PostgreSQL RLS failure when a student joins a published exam:
  `FOR UPDATE` requires permissions not granted by the student SELECT policy.
- Serialize PostgreSQL exam admission and closure with a transaction advisory
  lock, then re-read publication state without requesting student UPDATE rights.
  Preserve teacher-only mutation, tenant isolation and existing idempotency.
- Add three regression cases; pass all 18 school exam tests and Ruff. Deploy only
  the school API module with backup, hash checks and healthy API restart. Keep 0.9.
- Publish one synthetic exam through WeChat DevTools; a distinct temporary student
  completes it through authenticated HTTP with real qwen-plus (24.146 s model call).
  Verify the teacher UI displays the matching student, 98/100 and answer evidence.
- Close the test exam, retain its synthetic grade, and revoke both temporary test
  identities and sessions. This does not verify a second physical WeChat login.
- See `docs/wechat/EXAM_PUBLISH_ACCEPTANCE_2026-10-26.md` for scope and limitations.

## Unreleased - Question Language Guard (2026-10-26)

- Trace the reported method-rule question to matching uploaded source content;
  preserve legitimate source-based questions rather than stripping policy-like words.
- Snapshot session language, resolve it for old sessions, and pass it to answer
  analysis and transcript evaluation. Validate every Chinese blueprint question
  and follow-up, preserving source titles, quotes and technical terms.
- Reject wrong-language follow-up candidates before display; use a validated
  blueprint/localized fallback and persist that exact question for subsequent
  assessment. Record fallback provenance without an extra translation-model call.
- Pass 122 focused regression tests and Ruff; deploy seven backend files with
  reviewed diffs, hash guards, backup and healthy API/worker restart. Keep 0.9.
- Verify real qwen-plus with a synthetic Chinese question and English history:
  all three follow-ups are Chinese; 22.58 seconds including one normalization
  repair. This is a backend probe, not a phone latency guarantee.
- See `docs/wechat/QUESTION_LANGUAGE_2026-10-26.md` for evidence and limitations.

## Unreleased - Blueprint Retry Amplification Fix (2026-10-23)

- Trace a 726-character document's 363-second job to three task attempts and twelve
  Qwen Plus calls, not queue delay. Failed-attempt usage remains in the governance
  ledger even when the blueprint transaction rolls back.
- Mark exhausted local Planner repairs as non-retryable by the background queue;
  keep retries for transient provider failures and un-repaired output errors.
- Normalize only Chinese yes/no judgments followed by a bare request for reasons
  into a single reasoning question. Preserve context, polarity, evidence, answer
  points and knowledge units; leave independent or ambiguous probes to the model.
- Give bounded wording repairs the exact rejected field and prior patch, while
  preserving atomic validation and preventing unauthorized assessment-field changes.
- Record Planner prompt v8 without changing the 0.9 application version or model.
- Pass 78 focused regression/API/provider tests and Ruff. Final real Qwen Plus probes completed
  in 139.13 and 75.85 seconds; the slower run still needed a full structural repair.
  These are small synthetic Planner samples, not phone latency or a p95 guarantee.
- Deploy four modules with hash checks, backup, graceful restart and health/readiness
  checks. A deployed Celery task completed in 86 seconds plus 0.97 seconds queue time,
  with one delivery attempt and six questions. This does not include phone round trips.
  See `docs/wechat/BLUEPRINT_RETRY_AMPLIFICATION.md` for remaining quality limits.

## Unreleased - WeChat Phone Page Registration (2026-10-23)

- Read the Android device debugger: `rootCompPath=pages/login/index not found`,
  followed by `Component is not found in path "wx://not-found"`.
- Add missing page JSON configurations for login, school, work, exam and report.
  Keep required-component lazy injection and page-local speech declarations.
- Correct the route regression test: it previously checked only JS and WXML despite
  its title. Require valid page JSON and local component declarations on every route.
- Render the login shell before loading business modules or navigating; display
  bounded navigation/module/storage failures without exposing tokens or erasing data.
- Pass 102 client regressions and rebuild an official phone preview. The user confirms
  the Android page now renders after scanning the repaired package. Full feature/device
  acceptance and replacement of the uploaded development package remain separate steps.
- Keep application/client versions, backend, model selection and permissions unchanged.

## Unreleased - WeChat Recorder Stop Ownership (2026-10-23)

- Reproduce queued stop taps and cancel/re-record resetting the UI to idle before
  native recorder release. Ignore duplicate busy actions and keep cancellation
  in stopping until native Stop/Error confirms release.
- Reconcile wall-clock start/stop/duration deadlines on page show, including
  suspended background timers. Bound cross-page release waits and explicit retries.
- Quarantine timed-out recorder callbacks instead of assigning untagged late audio
  to a new recording. Restore text controls with a recovery message; never upload
  unconfirmed audio or retry a paid transcription automatically.
- Pass 91 client regressions, JS syntax checks and relevant WXML compilation.
  Back up and sync the two runtime files to D:\wechat; phone capture remains to
  be verified from a newly compiled preview. No backend/version/grade changes.

## Unreleased - Bounded Blueprint Wording Repair (2026-10-23)

- Keep Qwen Plus, the full source document and the existing initial planning prompt.
  Do not reduce question count, coverage or expected reasoning to save time.
- Batch wording-only repairs for all stacked questions/follow-ups in one compact
  response instead of regenerating the entire blueprint. Preserve answer points,
  quotes, pages, knowledge units and all already-valid wording.
- Validate patches atomically, reject extra fields/indices and retain the bounded
  repair budget and structural/language checks. Keep full repair for structural errors.
- Record Planner prompt revision v7 without changing the application version.
  Historical seven-template v6 acceptance evidence is not v7 acceptance evidence.
- Add seven-template contract tests and malformed-patch regression cases.
- Pass 89 local regressions. In the small synthetic Qwen Plus probe, observed
  Planner means fell from 151.43 to 83.64 seconds; this excludes queue/phone time.
  Deploy the single module with hash checks, backup and healthy API/worker restart.
  Document failed experiments and remaining quotation/semantic-quality findings in
  `docs/wechat/BLUEPRINT_GENERATION_PERFORMANCE.md`; do not claim full v7 acceptance.

## Unreleased - Interrupted Blueprint Recovery (2026-10-23)

- Settle expired blueprint worker leases on authorized status reads and duplicate
  deliveries; preserve source materials and require an explicit retry instead of
  silently repeating a paid model call. Fence late workers and audit each transition.
- Handle dead-letter and cancelled mini-program tasks, bound transient polling
  retries, preserve uncertain task IDs and block duplicate generation while pending.
- Add lease-race, tenant-isolation, terminal-state and polling regression coverage.
  Keep version numbers and scoring/model behavior unchanged.

## Unreleased - WeChat Component Lazy Injection (2026-10-23)

- Enable `lazyCodeLoading: requiredComponents` in the mini-program app configuration.
- Register the speech component only on personal and exam answer pages, not globally.
  Preserve microphone permission and existing speech behavior; keep versions unchanged.
- Check page-local component paths, required files and lazy injection in client regression tests.
- Re-scan code quality in WeChat DevTools: component lazy injection is marked passed.
- Reopen the project after a stale compiler-helper error during hot reload; verify
  the student hall, workbench and existing answer page render with speech controls.
  No model request or answer submission is part of this UI verification.

## Unreleased - WeChat Model Selector (2026-10-23)

- Remove OpenAI options from the personal and teacher mini-program model selector.
  Keep other ready real providers, web options and server configuration unchanged.
- Ignore cached OpenAI selections when restoring the picker, preserve session history,
  and disable model-dependent actions when no eligible provider is available.
- Add selector, restore and empty-provider regression coverage; keep versions unchanged.

## Unreleased - WeChat Synthetic Speech Upload Acceptance (2026-10-23)

- Verify a generated 6.41-second MP3 via native WeChat upload and real Qwen ASR:
  HTTP 200, exact transcript, editable draft filled, no answer submission or grade changes.
- Record the remaining DevTools recorder-format rejection (HTTP 422) separately;
  synthetic upload acceptance does not certify microphone capture or phone compatibility.
- Keep application version, production code, access rules and budgets unchanged.

## Unreleased - WeChat Recorder Callback Timeouts (2026-10-22)

- Reproduce a recorder stuck in stopping, followed by a persistent global recorder lock.
  Bound start/stop callbacks to five seconds and add a recording-duration watchdog.
  Timeout recovery discards unconfirmed audio and does not upload or submit answers.
- Guard cleanup and late stop callbacks so an old recording cannot remove a newer
  recording's listeners or apply a stale transcript. Preserve explicit user confirmation.
- Fix the observed `manager.offStart is not a function` failure with single native
  event dispatchers on runtimes without off methods. Repeated recordings do not
  accumulate listeners. Cancel only on changed component context and deduplicate busy events.
- Verify real Qwen TTS and ASR with synthetic speech through existing governance;
  distinguish this from microphone capture, audible playback and UI draft acceptance.
- User confirmed audible question playback in DevTools; real microphone transcription
  still requires a new acceptance attempt after the recorder compatibility fix.
- Sync the client fix to D:\wechat; keep server configuration, grades and version unchanged.

## Unreleased - Pause WeChat Realtime Entry (2026-10-22)

- Temporarily remove realtime voice controls and controller initialization from the shared
  mini-program component used by personal sessions, student answers and teacher previews.
- Preserve per-turn recording/transcription, question playback, editable drafts and explicit
  answer submission. Retain the realtime implementation for later acceptance testing.
- Keep web voice, server settings, model permissions, budgets, grades and version 0.9.0 unchanged.

## Unreleased - WeChat Voice Consent Dialog (2026-10-22)

- Fix the voice consent button exceeding WeChat's four-character limit, which prevented
  the modal from opening before microphone authorization. Use the four-character label.
- Distinguish consent modal, privacy authorization and microphone authorization failures;
  preserve bounded native error details instead of misreporting every failure as mic denial.
- Add native modal length validation to the speech test double and failure-path regressions.
  Keep application version 0.9.0 and all permissions, model settings and grades unchanged.

## Unreleased - WeChat Voice Finalization (2026-10-22)

- Ignore stale socket send failures after reconnect, validate and copy PCM frames,
  bound recorder startup and final upload, and keep playback stopped during finalization.
- Drain recorded frames before waiting for the last transcript. Replace the fixed four-second
  cutoff with bounded server confirmation and explicit unconfirmed/failure feedback.
  Reserve finalization time within the session lease; never submit answers automatically.
- Run the official DashScope 2.0.1 SDK against the approved snapshot using synthetic speech.
  Session configuration succeeds but no VAD, input transcript or automatic reply arrives in
  35 seconds. Restore the temporary policy rule and keep the live realtime feature disabled.
- Keep application version 0.9.0, the existing model configuration, budgets and grades unchanged.

## Verification - Qwen Realtime Snapshot (2026-10-22)

- With user approval, authorize inference for the exact dated snapshot in the supplied
  Beijing workspace, keeping all other provider authorization unchanged. Readback confirms it.
- Real output succeeds (468ms server-side first audio), but VAD/transcription and automatic
  second-turn acceptance remain unconfirmed after synthetic loopback, independent speech,
  manual commit and same-region endpoint comparisons. Do not enable realtime based on output alone.
- Restore the teacher organization's temporary exact model rule after each probe. Keep live
  model settings, budgets, members and grades unchanged. Record reproducible provider session IDs.
- Rerun 60 isolated backend tests, web voice lifecycle checks and six mini-program lifecycle tests.
  These checks use test doubles and are distinct from live model and real-device acceptance.

## Unreleased - Qwen Web Voice Isolation Fix (2026-10-22)

- Bind authenticated browser identity and validated organization membership before
  every Qwen WebSocket session lookup; enforce Origin and `session.conduct`, and
  recheck live access every five seconds without bypassing PostgreSQL RLS.
- Distinguish proxy connection from model initialization. Settle the connection
  ledger only after `session.updated`; fail unsuccessful initialization, sanitize
  provider errors, and stop microphone/playback on disconnect.
- Verify 87 web/auth tests, 32 mini-program speech/realtime tests, browser lifecycle
  unit checks, and an isolated FORCE-RLS PostgreSQL schema clone. Deploy five
  scoped files with backup; keep version 0.9.0 and all provider settings unchanged.
- The supplied Beijing workspace returns no exact undated model permission entry.
  Its dated realtime snapshot is listed as authorizable but `inference=false`.
  Do not enable or substitute that model without approval; see the realtime report.

## Unreleased - WeChat Qwen Realtime (2026-10-21)

- Add native 16 kHz PCM streaming and 24 kHz WebAudio playback through an authenticated
  WebSocket relay. Include interruption, final-transcript grace period and lifecycle cleanup.
- Keep exam submission explicit, teacher previews isolated, and model credentials server-only.
  Enforce question ownership, organization opt-in, model governance and bounded connection leases.
- Preserve turn-based speech and text as explicit alternatives. Product version stays 0.9.0.
- Requested `qwen3-omni-flash-realtime` currently fails the real provider probe with
  `Model not exist`; do not treat configuration or WebSocket handshake as model acceptance.
  See `docs/wechat/REALTIME_VOICE.md` before enabling production traffic.

## Unreleased - WeChat Turn-Based Voice (2026-10-20)

- Add native recording, editable ASR drafts and current-question TTS for personal sessions,
  student attempts and isolated teacher previews. Keep text submission and grading contracts.
- Bind speech to authorized resources and question fingerprints; enforce audio limits,
  model admission, conservative per-call budget estimates and sanitized provider errors.
- Stop recording/playback on cancellation or page changes; discard stale responses and
  clean temporary audio. Require explicit microphone/privacy consent.
- Keep voice disabled until server configuration and organization voice-model rules are
  approved. No database migration or product-version bump; not full-duplex realtime.

## Unreleased WeChat teacher exam preview - 2026-10-15

- Add owner-only, real-model teacher rehearsals in a separate table with forced
  PostgreSQL RLS (migration 0019); formal student grades and counts stay unchanged.
- Reuse grading, quota checks, idempotency and answer recovery; label previews and
  manually recovered scores explicitly, and hide self-enrollment forms.
- Preserve answers on HTTP quota failures instead of leaving them grading forever;
  failed stale calls cannot overwrite a newer submission.
- Keep backend version 0.9.0; a single-account preview is not a two-user acceptance.
- Verify 102 isolated backend tests and 31 client tests; complete a six-question
  real qwen-plus preview in WeChat Developer Tools, with formal grades still empty.
- Record deployment, RLS checks and remaining UI/acceptance limits in
  `docs/wechat/TEACHER_STUDENT_EXAMS.md`.

## Unreleased WeChat teacher/student exams - 2026-09-24

- Add a student exam hall and an explicitly authorized teacher view; existing
  personal workspaces and memberships remain unchanged.
- Publish immutable questions and material snapshots, share only published
  exams, accept one individually authorized attempt per student, and return
  original answers plus evidence-based AI grades to the publishing teacher.
- Add original-material preview, teacher grade review, failed-scoring recovery,
  idempotent submissions, scoped model usage and PostgreSQL RLS migration 0018.
- Preserve old grades and block source-project deletion before any file removal.
- Keep backend 0.9.0 and the mini-program in preview; no production exam claim.
- See `docs/wechat/TEACHER_STUDENT_EXAMS.md` for scope, rollout and limitations.

## WeChat preview snapshot - 2026-09-24

- Save the native mini-program, server-verified login, isolated personal spaces,
  upload recovery, deployment guidance and acceptance records on
  `feature/wechat-miniapp`; backend stays 0.9.0, client stays 0.1.0-preview.
- Include the shared session-lifetime and job-conflict handling used by the
  integration, with focused security and API regression tests.
- Verify 100 backend tests, 18 client tests and scoped Ruff checks before upload.
- Record the real qwen-plus UI acceptance and known scoring/report/recovery gaps;
  this snapshot is not a claim of production readiness or completed remediation.
- Exclude credentials, runtime data, local review artifacts and private tool settings.

## Unreleased WeChat personal spaces - 2026-09-22

- Add opt-in `WECHAT_REGISTRATION_MODE=personal`: a verified new or pending
  WeChat identity gets its own private organization and examiner membership.
  Default deployments retain manual approval; existing memberships are unchanged.
- Serialize first-login provisioning with PostgreSQL row locks and stable space
  IDs. Activation, membership, audit events and login session commit atomically;
  disabled accounts and revoked memberships are not reactivated.
- Add explicit tenant checks to document-list and document-evidence endpoints.
- Test isolated spaces, concurrent registration, rollback, cross-tenant access,
  and legacy approval. UI uses "space"; backend version remains 0.9.0.

## Unreleased mini-program upload recovery - 2026-09-22

- Move synchronous document parsing and storage off the ASGI event loop. Isolate
  PDF parsing in spawned processes because PyMuPDF is not thread-safe.
- Give each upload a private temporary directory, clean it on success or failure,
  and preserve original mini-program filenames through validated multipart data.
- Show native upload progress and distinguish transmission from server parsing.
- Add project-scoped uploaded-material discovery and explicit selection after an
  uncertain upload. Never automatically repeat a file upload; persist only the
  uncertainty flag and resource IDs, not document content or temporary file paths.
- Add Word upload, evidence, responsiveness, filename/size validation, WeChat
  recovery and cross-project stale-response regressions. Backend remains 0.9.0.


## Unreleased mini-program integration fix - 2026-09-21

- Fixed invalid escaped operators in native WXML conditions and removed an
  optional-chain expression incompatible with the imported developer-tool setup.
- Added a public, non-cacheable WeChat configuration status endpoint and client
  preflight checks for missing server credentials or mismatched AppID.
- Classified WeChat domain, TLS and timeout failures without exposing raw network
  details or retrying uncertain mutations.
- Added optional private wechat.env loading to the AutoDL startup script.
- Deployed the opt-in backend adapter to the existing AutoDL service. Real login
  remains blocked by missing AppSecret and the client domain allowlist; no
  real-device or real-model acceptance is claimed. Backend remains 0.9.0.

## Unreleased mini-program preview - 2026-09-10

- Added a native WeChat client under apps/wechat, independently versioned
  0.1.0-preview; backend version remains 0.9.0.
- Added opt-in server-verified WeChat login, pending-account approval with audit,
  revocable hashed sessions and a fail-closed Redis login admission limit.
- Reused tenant/RBAC-protected project, upload, asynchronous blueprint, text
  examination and report APIs. No client model keys or mock fallback.
- Added scoped progress pointers, timeout reconciliation, security/protocol tests
  and deployment guidance. AppID, developer-tools and real-device acceptance are
  still required; native voice and evidence preview are not part of this preview.

## Unreleased fix - 2026-09-07

- Removed training wording from built-in Chinese product display copy, including
  workbench defaults, template labels and report notices. Preserved immutable
  template sources, user text, scientific terminology and disclaimer restrictions.
- Removed the enterprise-edition suffix from the workbench heading and renamed
  the console labels to "控制器" without changing routes, permissions or version.
- Added a 120-minute server-enforced browser idle timeout and an explicit opt-in
  application-session policy (480-minute absolute limit). Bearer token validation
  remains unchanged; existing sessions are not extended.
- Bind blueprint request keys to organization, project, document, model and
  template parameters; preserve same-request retries and reset terminal failures.
- Return a structured HTTP 409 for job idempotency conflicts instead of HTTP 500.
- Fixed protected evidence thumbnails: image downloads now carry the active
  organization header and session credentials before being decoded as images.
- Show per-page failures instead of claiming that listed evidence has rendered.
  Bound download concurrency and release preview URLs on reload or organization change.
- Added preview authorization, error handling and cleanup regression tests.
- Retained application version 0.9.0; only the frontend cache revision changed.

## Unreleased interface revision - 2026-09-04

- Refined the restored classic workbench without changing its module order or
  interaction model: reduced header and panel whitespace, fixed desktop title
  wrapping, shortened idle surfaces and simplified the signed-out model state.
- Removed the inherited desktop flex basis from narrow-screen header actions so
  tablet and mobile layouts no longer reserve a large empty block above content.
- Restored the original v0.9.0 workbench and enterprise-console layout after
  user evaluation of the v0.9.1 through v0.9.5 interface experiments.
- Removed the later compact navigation, reordered workbench, widened setup rail,
  advanced-tool disclosure and segmented text/voice presentation.
- Preserved all current enterprise APIs, authentication, storage, audit, model
  governance, cognitive memory and assessment functionality.
- Added a classic-layout regression contract and a non-semantic static asset
  revision so browsers cannot retain the superseded interface.

## 0.9.5 - 2026-09-04

- Simplified the primary preparation flow to four required steps and moved
  Golden Dataset generation into a collapsed advanced-evaluation disclosure.
- Added an accessible segmented control for switching between text and voice
  examination without rendering both large session panels at once.
- Reworked narrow-screen header actions, provider state, voice settings, memory
  controls and preferences to use compact, balanced grids.
- Added semantic provider-state colors and replaced raw authentication errors
  with a concise login requirement in the workbench header.
- Preserved all existing workbench IDs, API contracts and examination behavior.

## 0.9.4 - 2026-09-04

- Widened the desktop preparation rail from a constrained 310-390px range to a
  stable 420-460px working width.
- Added explicit minimum widths for paired setup controls and balanced the text
  and voice session actions within the preparation rail.
- Moved the single-column transition to 1080px so compact desktops and tablets
  no longer squeeze the setup workflow beside the active work surface.
- Preserved all workbench DOM IDs, APIs, enterprise behavior and mobile touch
  targets while adding layout regression coverage.

## 0.9.3 - 2026-09-04

- Added a versioned UI design system for the workbench and enterprise console.
- Reduced passive header, navigation, panel, status, empty-state and module
  spacing while retaining usable form controls and mobile touch targets.
- Compacted evidence, conversation, voice, memory, template and evaluation
  surfaces without changing their DOM IDs or runtime contracts.
- Reduced enterprise sidebar, metric, table, record and content-area density
  while preserving OIDC, organization and capability behavior.

## 0.9.2 - 2026-08-17

- Reduced workbench grid gaps, panel padding and fixed empty-state heights.
- Compacted the header, sticky workflow navigation, voice surface and template
  studio while preserving control sizes and active-session capacity.
- Improved first-screen information density on desktop, tablet and mobile.
- Kept all enterprise APIs, database schemas and runtime behavior unchanged.

## 0.9.1 - 2026-08-11

- Reorganized the public workbench so project preparation, evidence review and
  live examination appear before template administration and evaluation tooling.
- Added a sticky workflow navigator with direct access to preparation, evidence,
  text, voice, memory and template surfaces.
- Rebuilt the shared visual system around denser operational spacing, clearer
  focus states, restrained surfaces and responsive layouts with no API changes.
- Refined the enterprise console navigation, metrics, tables, forms and mobile
  behavior while preserving every existing capability and DOM contract.

## 0.9.0 - 2026-08-11

- Promoted the accepted enterprise platform to the first final v0.9 release.
- Completed an independent RC2 observation against commit `bd6dc19`: 24 hours,
  1,440 HTTPS/OIDC samples, zero failures and 100% availability.
- Preserved immutable RC1 and RC2 tags and changed only release metadata, accepted
  evidence and static cache identifiers after RC2 acceptance.
- Made `main` the documented production deployment branch while retaining exact-tag
  deployment and rollback instructions.

## 0.9.0rc2 - 2026-08-10

- Published immutable tag `v0.9.0-rc.2` after the committed-source release gate
  passed 23 checks with no failures or blockers.
- Preserve executable Git modes for native AutoDL and PostgreSQL rehearsal scripts,
  with a regression test covering every tracked deployment shell script.
- Raised the pypdf floor to 6.15.0 to remediate CVE-2026-71852 and
  CVE-2026-71870 for untrusted PDF text extraction.
- Recover tenant-scoped queued jobs that were persisted but never received a
  Celery task identifier, with a bounded batch and configurable grace period.
- Default Golden Dataset generation to the configured healthy real provider;
  Mock is now only the fallback when no preferred provider is available.
- Normalize evidence whitespace before grounding checks so line wrapping does
  not reject an otherwise verbatim source excerpt.
- Seed immutable built-in templates and Prompt Registry data during native
  AutoDL enterprise startup, matching the enterprise Compose bootstrap contract.
- Added principal-scoped organization discovery policies so PostgreSQL FORCE RLS
  can bootstrap the authenticated user's organization switcher without exposing
  another principal's membership.
- Integrated the main examiner workbench with OIDC sessions, organization selection,
  tenant request headers and capability checks across legacy workbench routes.
- Increased the Qwen provider deadline to 240 seconds for recoverable Planner jobs
  while retaining immediate asynchronous enqueue and progress polling.
- Added a reusable real OIDC/S3/Qwen public-workbench verifier.
- Added reboot-safe AutoDL native orchestration for PostgreSQL, Redis, MinIO,
  OpenTelemetry, the staging OIDC issuer, Celery and the public API.
- Invalidated RC1 browser assets through RC2 versioned static URLs.

## 0.9.0rc1 - 2026-08-07

- Promoted the accepted enterprise platform to its first immutable release
  candidate after all 23 release checks passed.
- Recorded a continuous 24-hour HTTPS/OIDC staging observation with 1,441 samples,
  zero failed samples, 100% availability and 167 ms maximum health latency.
- Completed desktop/mobile OIDC browser acceptance, PostgreSQL RLS, S3-compatible
  storage, Redis idempotency, audit, quota, telemetry, disaster-recovery and
  real-Qwen governance evidence.
- Added reboot-safe AutoDL startup for the v0.9 application, Redis and the staging
  OIDC issuer while preserving the accepted deployment ports.
- Retained the final-production hold: RC1 is for controlled staging and must not be
  treated as the final `0.9.0` release.

## 0.9.0.dev0 - release evidence automation

- Added machine-generated OIDC, route capability, storage, queue, audit, telemetry
  and AI regression evidence with sanitized hashes and focused test counts.
- Added real Redis concurrency, S3-compatible object lifecycle and OTLP wire probes.
- Added an isolated host PostgreSQL/object restore rehearsal for environments without
  a Docker daemon.
- Added a strict 24-hour HTTPS/OIDC staging observer.
- Hardened the release gate so `status: passed` placeholder JSON cannot satisfy the
  v0.9 enterprise evidence contract.
- Added a localhost-only PKCE/JWKS staging OIDC issuer for repeatable browser and
  24-hour acceptance without depending on production identity data.

## v0.9.0 research - WP-14 release hardening

- Require `cryptography>=50.0.0` and refresh the lock file after the release
  dependency audit detected CVE-2026-69247 in 49.0.0.
- Revalidate the deployed research build with a 48-check isolated HTTP
  acceptance run using real Qwen Plus, native PostgreSQL 17 RLS verification,
  337 automated tests and a 160-request public endpoint probe.
- Add a repeatable native-host PostgreSQL/RLS acceptance command with a strict
  `_test` database-name guard and optional disposable database recreation.
- Verify the dedicated least-privilege application login across 100 concurrent
  tenant reads and a real cross-tenant write attempt in both CI and host acceptance.
- Detect Alembic/schema drift before policy inspection and report the missing tables
  instead of surfacing an opaque SQLAlchemy `NoSuchTableError`.
- Validate the complete migration chain, FORCE RLS policies, least-privilege
  runtime login and 20-worker tenant isolation on native PostgreSQL 17.10.
- Pass the complete 331-test suite on PostgreSQL 14.23 and PostgreSQL 17.10,
  and commit sanitized migration and tenant-isolation evidence.
- Isolate the test model-admission backend from deployment `.env` values so
  PostgreSQL and SQLite regression results are environment-independent.

- Advanced the implemented research branch package and visible UI identity to
  `0.9.0.dev0`; release-candidate promotion and tags remain held by the external
  enterprise evidence gate.
- Made the destructive direct-staging verifier fail early when its candidate
  principal was already consumed, preserving the intentionally terminal revoked
  membership state and directing reruns to a fresh isolated database.
- Clarified dependency-audit command failures so a transient audit outage is not
  misreported as a zero-vulnerability result, while keeping the release gate
  fail-closed.
- Added a clean-working-tree source-integrity gate so release evidence cannot bind
  uncommitted code to the previous Git commit.
- Added a machine-readable release gate for tests, lint, JavaScript, migrations,
  authorization metadata, dependency vulnerabilities, tracked-source secrets and
  frozen v0.8 AI evidence.
- Added a bounded real-provider governance probe that records only policy, provider,
  model, usage, latency and cost metadata.
- Added sanitized external evidence schemas, CI artifacts, draft RC notes and an
  enterprise operator manual.
- Preserved the research package version and held the RC tag until Vultr, OIDC,
  desktop/mobile UI, staging observation and recovery evidence are complete.
- Fixed Alembic configuration discovery for Wheel/direct-process deployments that
  start from the repository root.
- Removed the historical v0.4 path and port assumptions from the AutoDL/SeetaCloud
  startup script so each worktree starts its own virtual environment and configured
  port.
- Limited local Ollama startup and model waits to deployments that explicitly select
  `MODEL_PROVIDER=ollama`.
- Added an isolated direct-process staging acceptance runner covering enterprise
  identity, RBAC, local storage, real Qwen planning, governance, audit, jobs,
  retention, verified deletion, human review, templates and voice configuration.
- Made public model-policy task families (`planner`, `analyzer`, and `reporter`)
  authorize their corresponding runtime agent names.
- Moved interactive blueprint generation onto the durable background-job path with
  idempotent submission, progress polling, cooperative cancellation and result
  recovery while retaining the synchronous API for compatibility.
- Added a single-process background dispatcher for direct staging deployments and
  preserved worker failure details instead of misreporting eager task failures as
  queue outages.
- Added configurable Qwen thinking mode and defaulted interactive Qwen requests to
  non-thinking mode to reduce latency; quality-sensitive batch runs can opt in with
  `QWEN_ENABLE_THINKING=true`.
- Made the direct-staging verifier ignore ambient HTTP proxy settings by default,
  preventing localhost and private staging requests from being redirected through
  a system proxy; operators can explicitly opt in with `--trust-env`.
- Replaced the verifier's legacy synchronous Planner call with the real asynchronous
  blueprint path, including fast enqueue, health-during-work, terminal polling and
  duplicate-idempotency checks.

AI Examiner 的重要变更记录在此文件。版本号遵循 Semantic Versioning；开发版本使用 PEP 440 标识，例如 `0.5.0.dev0`。

## [Unreleased]

### Added

- Isolate immutable HTTP audit writes in a dedicated SQLAlchemy connection pool,
  preventing concurrent sensitive reads from deadlocking the business pool while
  their response-scoped sessions are still open.
- Reject text and voice sessions whose selected scenario template differs from
  the template used to generate the blueprint, and disable the browser start
  controls until a compatible blueprint is regenerated.
- Add browser-level connection timeouts and recovery messages for microphone
  acquisition and realtime SDP negotiation.
- Apply selectable template question-strategy and voice-provider overrides to
  the effective blueprint, text-session and voice-session policy.
- Translate missing long-term-memory server configuration into a user-facing
  availability message without exposing the internal environment-variable name.
- Make voice-session completion idempotent under concurrent browser retries,
  release SQLite write locks between governed transcript-analysis calls, and
  close the session with an auditable finalization error when post-processing
  cannot finish.
- Serialize per-session realtime event accounting with process stripes and
  PostgreSQL row locks so concurrent transcript callbacks cannot overwrite turn,
  interruption or error counters.
- Advance the main workbench static cache version after the voice concurrency
  fixes so deployed browsers revalidate the updated shutdown and event logic.
- Keep Uvicorn access and exception loggers enabled after startup Alembic
  migrations, restoring actionable request diagnostics on direct deployments.
- Preserve the intended blueprint-generation `502` when provider preparation
  fails instead of referencing a voice-only identifier from its error logger.
- Disable the voice end control as soon as shutdown starts and send a keepalive
  completion request when the page is closed.
- Add answer-to-question relevance scoring, deterministic cross-question answer
  reuse detection and auditable aggregate score caps.
- Require open-answer adjudication to be both defensible and functionally
  satisfied before promoting a rubric point to full coverage.
- Normalize compound model citations into individually verified verbatim evidence
  anchors, detect unexpected text-script artifacts and prevent datasets with
  failed quality gates from being frozen.
- Add an idempotent AutoDL stop script that validates the recorded PID before
  terminating Uvicorn, preventing stale application processes after deployment.
- Return a structured 502 error when the server cannot reach OpenAI Realtime,
  so the browser can distinguish infrastructure connectivity from media failure.
- Render structured realtime errors as readable code and message text instead
  of the JavaScript string `[object Object]`.
- Refresh the organization switcher with the authorized display name after
  developer-context resolution, avoiding clipped UUID labels on mobile.
- Hide the redundant organization field label below 430px so the accessible
  switcher has enough width for its selected organization name.
- Bind core workbench project, document and blueprint operations to an explicit
  organization capability context while retaining no-header local legacy mode.
- Add WP-13 enterprise administration UI with OIDC login state, safe organization
  switching, capability-gated members, model governance, audit, lifecycle and
  human-review workflows.
- Add organization display metadata to `/api/v1/me` and a tenant-scoped,
  filterable data-subject request list endpoint.
- Abort and invalidate organization-scoped browser requests on tenant changes,
  clear stale views and require explicit confirmation for high-risk operations.
- Add WP-12 recoverable enterprise Docker Compose with PostgreSQL, Redis, API,
  worker and Caddy plus optional private MinIO and observability overlays.
- Separate migration and runtime database credentials, force external schema
  management and verify the application login remains subject to RLS.
- Add consistent PostgreSQL/object backup manifests, guarded isolated restore,
  RPO/RTO evidence and non-destructive update/application rollback scripts.
- Add deterministic operations tests and a Linux Compose restart plus
  backup/restore rehearsal in GitHub Actions.
- Verify the Linux enterprise recovery process against PostgreSQL 17, including
  least-privilege roles, FORCE RLS, immutable audit controls, restart persistence,
  manifest validation and an isolated 27-second restore rehearsal.
- Add WP-11 failure-isolated OpenTelemetry instrumentation for FastAPI,
  SQLAlchemy, HTTPX and Celery with allowlist-based span redaction.
- Add backward-compatible worker task envelope v2 request and W3C trace
  correlation plus low-cardinality HTTP and job metrics.
- Add an optional Collector, Tempo, Prometheus, Grafana and Alertmanager
  Compose profile with provisioned dashboards and alert rules.
- Add telemetry privacy, endpoint validation, backend-outage and correlation
  regression tests.
- Add the v0.9 enterprise-platform research package covering organization tenancy,
  external OIDC identity, scoped service accounts, capability RBAC, PostgreSQL RLS,
  S3-compatible storage, tenant-aware jobs, audit, model governance, retention,
  OpenTelemetry, disaster recovery and a staged implementation backlog.
- Define the v0.9 API authorization contract, threat model, cross-tenant evaluation
  gates and restartable SQLite/file-to-PostgreSQL/object-storage migration strategy.
- Inventory every current model and API family by tenant ownership, required
  capability, resource resolver and migration invariant.
- Correct the PostgreSQL CI false-positive by allowing a guarded test-only database
  override and running the complete regression suite against PostgreSQL.
- Add an isolated Mock-only PostgreSQL Compose rehearsal, dedicated test image and
  Docker build-context exclusions for secrets, runtime data and generated archives.
- Add the v0.9 organization and principal foundation with deterministic legacy
  project ownership, external `(issuer, subject)` identity, unique memberships and
  bounded principal lifecycle.
- Add an idempotent first-owner bootstrap CLI and `/api/v1/context` observe-only
  organization context without prematurely enabling authentication or authorization.
- Add additive migration `20260727_0008` with legacy project backfill, guarded
  downgrade and SQLite/PostgreSQL verification.
- Add WP-03 OIDC discovery, bounded JWKS caching, strict access-token validation,
  Authorization Code + PKCE login, principal provisioning and revocable hashed
  browser sessions.
- Add `/api/v1/auth/login`, callback, logout and `/api/v1/me`, plus live `/ready`
  authentication checks and fail-closed production configuration validation.
- Add additive migration `20260727_0009` and an ephemeral-RSA invalid-token,
  key-rotation, PKCE, session, readiness and rollback test matrix.
- Add WP-04 centralized capability RBAC with reviewed role bundles, fail-closed
  organization membership resolution and cross-organization resource protection.
- Add complete `/api/v1` route policy registration with startup validation and
  generated `x-ai-examiner-policy` OpenAPI metadata.
- Add organization membership list/create/update/revoke APIs with strong ETags,
  bounded lifecycle transitions, owner-only owner mutation and last-owner protection.
- Replace the OIDC template-authoring compatibility seam with real author, reviewer
  and publisher capabilities while retaining disabled-mode deterministic tests.
- Add WP-05 direct organization ownership across project, learner, template, prompt,
  usage and background-job records with a two-phase legacy backfill.
- Add transaction-local SQLAlchemy tenant/principal context, tenant-aware Celery job
  dispatch and fail-closed worker resource loading.
- Add tenant-aware uniqueness, critical composite ownership constraints and forced
  PostgreSQL RLS policies for the restricted `ai_examiner_runtime` role.
- Add a PostgreSQL pre-pytest RLS proof covering missing context, context switching
  and cross-tenant writes, while retaining SQLite local-evaluation compatibility.
- Separate schema-management and runtime responsibilities: enforced RLS requires
  `DATABASE_SCHEMA_MANAGEMENT=external`, so API and worker startup cannot run DDL or
  global seed writes with the restricted runtime credential.
- Add WP-06 tenant object storage with one Local/S3-compatible backend contract,
  canonical organization-prefixed object keys and normalized `StoredObject`
  locators protected by PostgreSQL FORCE RLS.
- Route new document, evidence and memory-export writes through checksum-verified
  storage while retaining nullable legacy paths only for migration compatibility.
- Add authorized `/api/v1` document, evidence, highlighted evidence and memory
  export downloads with private streaming or bounded presigned redirects.
- Add restartable legacy-path migration, atomic checkpoints, source retention,
  missing-object reconciliation and a downgrade guard that prevents orphaning
  migrated objects.
- Add an optional private MinIO Compose profile, storage readiness checks and
  Local/S3 contract, resume, checksum, authorization and Alembic regression tests.
- Add WP-07 durable tenant-aware job delivery with strict persisted task envelopes,
  organization-scoped idempotency keys and atomic lease ownership.
- Recheck active organization, principal, membership and required capability in the
  worker before loading any protected resource.
- Add bounded transient retries, cooperative cancellation, terminal/dead-letter
  states, heartbeat renewal and expired-worker recovery.
- Add authorized enterprise job list, read, cancel, retry and recovery APIs that
  omit broker identifiers, lease owners and raw exception details.
- Add migration `20260728_0013` and deterministic duplicate-delivery,
  authorization-revocation, cancellation, recovery and migration tests.
- Add WP-08 append-only `AuditEvent` evidence with server request IDs, W3C trace
  correlation, keyed source-IP hashing and user-agent family reduction.
- Audit authentication, administrative, sensitive-read, authorization-denial and
  worker-terminal activity through the centralized route and job policy layers.
- Add tenant-scoped redacted audit list and bounded JSONL export APIs requiring
  `audit.read`.
- Add positive metadata allowlisting, secret/canary redaction, event digests and
  retention eligibility without a runtime deletion path.
- Add migration `20260728_0014` with SQLite mutation triggers and PostgreSQL
  runtime privilege revocation, FORCE RLS, native immutability trigger and a
  separate privileged aging role.
- Add deterministic audit rollback, leakage, isolation, correlation, immutability,
  API/export and migration tests, plus PostgreSQL runtime mutation verification.
- Add WP-09 organization model policy with provider/model/task allowlists,
  project data classification and fail-closed external-provider boundaries.
- Add durable quota reservations, immutable usage evidence, actual provider/model
  settlement and organization/project/task cost summaries.
- Add atomic Redis request, token and concurrency admission with hard/soft quotas,
  stable denial codes, bounded fallback and explicit fail-open behavior.
- Govern text, multimodal, dataset, benchmark and realtime voice connection paths
  before provider construction, with redacted policy/quota/usage APIs and export.
- Add migration `20260728_0015`, forced PostgreSQL tenant RLS, runtime DELETE
  revocation and deterministic governance, concurrency, voice and rollback tests.
- Add WP-10 versioned organization retention policies, scoped legal holds and
  fail-closed deletion blocking across both reviewed and legacy project paths.
- Add checksum-verified asynchronous organization/project/learner exports with
  immutable manifests, bounded lifetime, optional private object inclusion and
  authorization revalidation on every download.
- Add idempotent data-subject export/delete requests with independent human
  approval, legal-hold blocking, resumable jobs and relational/object convergence
  evidence.
- Add human review, assignment, decision and appeal cases backed by append-only
  events; model-authored evidence can open a case but cannot write a final decision.
- Add migration `20260728_0016`, PostgreSQL FORCE RLS/runtime privilege controls
  and deterministic lifecycle, dual-control, export, legal-hold, review and
  rollback tests.

- Add complete Planner v6 reciprocal real-provider evidence for all seven built-in
  templates: 30 unique cases per template, 420 case evaluations and 840 anonymous
  A/B arms across Qwen and OpenAI.
- Add a focused open-answer adjudication path and structured semantic,
  functional-criterion, source-conflict, rubric-issue and error-classification
  evidence for defensible alternatives.
- Commit the compact aggregate Planner v6 evidence and full acceptance report while
  keeping large raw provider checkpoints outside Git.

- Add the v0.8 industry template platform research package covering immutable
  template versions, deterministic compilation, policy-bounded overrides, session
  snapshots, lifecycle APIs, behavioral evaluation and an implementation backlog.
- Start the v0.8 implementation line with a strict template contract, safe YAML/JSON
  parsing, semantic validation and deterministic compilation.
- Add the reviewed thesis-defense compatibility template, compact built-in catalog
  API, template health API and packaged-resource verification.
- Add immutable scenario-template persistence, lifecycle and authoring APIs,
  idempotent built-in seeding and additive Alembic migration `20260723_0006`.
- Add project default template bindings and optional text/voice session template
  selection with deterministic override precedence.
- Persist immutable effective template snapshots, compiler versions, overrides and
  SHA-256 fingerprints on exam sessions through migration `20260723_0007`.
- Add session-template inspection with fingerprint verification and preserve
  template-free compatibility for legacy teaching and interview requests.
- Add immutable `academic.thesis_defense@1.1.0` with bounded follow-up overrides
  while retaining the published `1.0.0` artifact.
- Add immutable `academic.thesis_defense@1.2.0` with assumption and critical
  reflection question types while retaining v1.0 and v1.1.
- Feed compiled objectives, allowed question types, coverage requirements,
  difficulty bounds and question limits into blueprint planning.
- Record objective mappings and explicit met/impossible coverage results on
  template-guided blueprints.
- Make adaptive selection honor the session snapshot's allowed types, difficulty
  bounds and unmet objective coverage, with the effective contract recorded in
  decision audit events.
- Add one effective conversation-policy contract shared by text, OpenAI Realtime
  and Qwen Realtime sessions.
- Authorize every text policy action against the template allowlist and record
  requested actions, effective actions and deterministic fallback reasons.
- Enforce template hint, correction and answer-disclosure boundaries in runtime
  configuration and realtime voice instructions.
- Require both template permission and user opt-in for proactive examiner
  interruption while preserving learner barge-in.
- Upgrade template validation through `template-validator-v3`, requiring every
  conversation policy to include a terminal `END` action and every assessment
  dimension to use a registered deterministic rubric.
- Add `template-assessment-v1` with exact weighted score recomputation, localized
  rubric anchors and answer/source evidence on every dimension score.
- Apply the immutable session snapshot's assessment scale, dimension weights,
  assisted-performance policy and aggregate policy to text and finalized voice
  answers.
- Add objective-weighted report aggregation, objective evidence, dimension
  evidence, template identity/fingerprint metadata and registered report sections.
- Support `no_total` coaching reports without exposing a total score while
  preserving deterministic internal diagnostics for adaptive selection.
- Resolve required disclaimers from a reviewed registry and keep interaction,
  preference, emotion and voice timing signals outside correctness scoring.
- Add six reviewed bilingual built-in scenarios for grant review, course oral
  practice, technical interview practice, product knowledge training, sales
  objection practice and project review facilitation.
- Give every built-in scenario distinct objectives, question taxonomy, difficulty,
  assistance, conversation, assessment, report, safety and presentation policies.
- Add behavior-signature tests requiring every intended-distinct scenario pair to
  differ in at least three runtime dimensions.
- Add explicit human-review, protected-trait, personality/emotion and automated
  employment/admission decision boundaries across the built-in catalog.
- Expand persisted built-in health checks to seven template identities and nine
  immutable versions.
- Add bounded YAML/JSON template import that always assigns local ownership,
  `draft` lifecycle and `local_draft` trust regardless of imported metadata.
- Add source-only JSON/YAML template export with explicit attachment, fingerprint
  and export-contract headers.
- Add deterministic semantic template diff grouped by behavioral policy section.
- Add stable transfer error contracts and an explicit local-authoring
  authorization dependency seam for the v0.9 identity and RBAC implementation.
- Add a responsive scenario-template library with category, risk and lifecycle
  filters, visible trust metadata and published-template session selection.
- Add a structured local-draft editor for objectives, questioning, assistance,
  assessment, report and safety policies, with advanced JSON kept optional.
- Add effective-policy preview, validation, compilation, clone, lifecycle,
  import/export and semantic-diff workflows to the browser application.
- Apply the selected published template consistently to blueprint generation,
  text sessions and realtime voice sessions.
- Add browser and static regression coverage for mobile layout, contract-safe
  correction timing and template request wiring.
- Add a deterministic v0.8 template evaluation runner and CLI covering validation,
  recompilation, platform invariants, 21-pair distinctness, override boundaries and
  local performance without paid-model calls.
- Keep real-provider relevance, Docker Compose and Vultr rehearsal gates explicitly
  held instead of allowing deterministic or Mock results to authorize release.
- Add a provider-contract probe for compiled scenario templates with actual model,
  token, latency, coverage and violation evidence but no credentials or prompts in
  its output.
- Add one bounded Planner repair attempt when a real provider returns a question
  type, difficulty or objective mapping outside the compiled template contract.
- Accept validated Qwen and independent-provider probe reports as evidence for only
  the corresponding provider gates; relevance, Compose and Vultr gates remain held.
- Allow Compose deployments to inject a separate environment file and host data
  directory while preserving `.env` and `./data` defaults.
- Add an isolated v0.8 Compose rehearsal for configuration, build, migration,
  health, template gates and SQLite backup inspection without touching the active
  project or using paid-model credentials.
- Add a fingerprinted frozen relevance corpus spanning all seven built-in
  scenarios, with 210 cases balanced across language, difficulty and answer
  quality.
- Add deterministic corpus validation plus cross-provider blind-judge evidence
  aggregation, confidence intervals and release thresholds for at least three
  complete scenarios.
- Reject Mock, self-judged, stale-fingerprint and incomplete relevance evidence
  instead of allowing structural provider probes to stand in for scenario quality.
- Add independent baseline/scenario generation, deterministic A/B blinding and
  reciprocal cross-provider judging for scenario relevance.
- Require release relevance artifacts to come from the production
  `SessionPlanner` path; keep batched contract generation as non-release
  calibration only.
- Feed scenario identity, presentation, assistance, assessment and report context
  into Planner generation so templates alter examiner behavior beyond taxonomy.
- Add reviewed role/style behavior guidance and require scenario-native questions
  that remain distinguishable without a visible role label.
- Detect stacked main questions, move secondary probes to follow-ups through bounded
  semantic repair, and fail closed after repeated contract violations.

### Changed

- Reconcile semantically equivalent and independently accepted defensible answers
  to full expected-point credit without promoting explicit source contradictions or
  vague answers.
- Refine the Planner v6 single-task validator so Chinese judgment markers and quoted
  customer questions are treated as context, while English `who ... and what ...`
  prompts are rejected as stacked tasks.
- Add atomic per-batch relevance checkpoints and metadata-safe `--resume`, verified
  by recovering a real Qwen timeout without losing completed cases.
- Complete reciprocal Qwen/OpenAI 30-case blind evaluation for product knowledge,
  sales objection and project review; all three pass relevance, quality, grounding,
  single-question and safety thresholds.

### Fixed

- Reject semantically stacked main questions and follow-ups even when a model
  hides multiple requests behind one question mark.
- Preserve analytical difficulty during Planner contract repair instead of
  collapsing a question into page-location or term recall.
- Scope stacked-request detection to the final explicit request so declarative
  source phrases do not trigger false positives.
- Replace the Mock planner's compound assumption question with single-task main
  and follow-up questions.
- Prefer CJK-capable fonts for logical document previews and install Noto CJK in
  the Docker image so Chinese evidence remains readable to users and vision models.
- Require visual-evidence output to follow the document language, including
  Simplified Chinese for `zh-CN` projects.
- Show only the newest visual-analysis result for each evidence asset in the
  browser while preserving the complete backend audit history.
- Ignore isolated runtime-data and alternate virtual-environment directories so
  local acceptance artifacts cannot enter release commits.

## [0.7.0-rc.2] - 2026-07-23

### Added

- Complete the v0.7 long-term learner lifecycle with user-started retests,
  registry-limited confirmed preferences, a responsive memory center, append-only
  corrections, short-lived JSON export and scoped asynchronous deletion.
- Add deterministic longitudinal evaluation reports with explicit held gates,
  sample counts and uncertainty, plus PostgreSQL migration/domain CI.

- Add the first v0.7 implementation foundation: HMAC-derived opaque learner
  identities, explicit memory controls, confirmed subject links, canonical concepts,
  reviewed knowledge-unit mappings and an idempotent evidence-bound memory ledger.
- Add replayable longitudinal concept states with observed/predicted separation,
  three deterministic retention baselines, growth series and recommendation-only
  shadow retest plans with explainable ranking.
- Add the v0.7 long-term learner intelligence research package covering revocable
  memory, opaque identity links, canonical concepts, retention baselines, shadow
  retest planning, confirmed preferences and lifecycle evaluation.
- Add frozen provider-neutral realtime signal and capability schemas for v0.6.
- Add deterministic OpenAI and Qwen event normalizers with provider-event
  idempotency.
- Add sanitized unknown-event signals instead of silently dropping new provider
  events.
- Add recorded OpenAI and Qwen event traces and replay contract tests.
- Add a provider-neutral assessment contract with correctness aliases, strict
  unknown-label rejection and point-level expected-answer decisions.
- Add assessment report v2 with independent, assisted and learning-gain
  trajectories per main question.
- Add persisted provider latency, retry and JSON-repair telemetry with p50/p95
  metrics and a reversible Alembic migration.

### Changed

- Complete the v0.7 release hardening pass with dynamic API `no-store` headers,
  versioned browser assets and a real `qwen-plus` adaptive-session acceptance run.
- Start the v0.6 development line as `0.6.0.dev0` without changing active voice
  behavior.
- Label the browser application consistently as the v0.6 development line.
- Compute answer coverage deterministically from point assessments and score
  correctness, grounding, reasoning and boundary awareness separately.
- Use independent main-question performance for defense-mode totals while
  preserving assisted performance as a separate diagnostic signal.

### Fixed

- Gate microphone uplink until the examiner's initial realtime response completes,
  preventing ambient input from racing the opening question on both OpenAI WebRTC
  and Qwen WebSocket sessions.
- Measure first-response latency from `response.create`, ignore empty user
  transcripts, and surface a bounded Qwen opening-response timeout.
- Evaluate follow-up answers against the active follow-up text instead of the
  parent main question.
- Continue adaptive sessions after the follow-up limit when remaining questions
  reference prerequisites that are outside the current blueprint graph.
- Isolate automated tests from real provider defaults in a developer `.env`.
- Normalize real Qwen labels such as `correct` and `partially_correct` instead of
  silently under-scoring them as unknown values.
- Enforce configured output language for generated blueprints with one bounded
  correction attempt.
- Clear the active-analysis hint after completion and version the browser script
  URL so deployments do not retain stale report rendering code.

## [0.5.0-rc.4] - 2026-07-16

### Added

- Add DashScope `qwen-plus` as a first-class text, structured-output and evaluation provider.
- Add DashScope `qwen3-vl-plus` for page, chart, table and formula visual review.
- Add an independent visual-model selector that only lists image-capable profiles.
- Record the actual visual model in usage and analysis audit data.

### Changed

- Share the server-side `DASHSCOPE_API_KEY` across Qwen text, vision and realtime voice without exposing it to the browser.

## [0.5.0-rc.3] - 2026-07-16

### Fixed

- Consume browser API response bodies exactly once so backend errors remain visible.
- Return an actionable JSON 503 when Redis/Celery cannot accept a background job.
- Support single-process visual-review testing with `CELERY_ALWAYS_EAGER=true`.

## [0.5.0-rc.2] - 2026-07-16

### Fixed

- Explicitly close SQLite backup connections so temporary snapshots can be removed on Windows.
- Read exported JSONL as UTF-8 in cross-platform CLI tests.
- Synchronize `uv.lock` with the Alembic dependency and release-candidate version.

## [0.5.0-rc.1] - 2026-07-16

### Added

- Alembic 迁移、Knowledge Unit、Question Mapping、Learner Subject、Knowledge State 和不可变 Evidence Event。
- Difficulty Controller、Adaptive Question Selector、跨会话状态继承和已问题目新颖度控制。
- 可审计的 Adaptive Decision，包含候选分、原因、策略权重和版本。
- `fixed` / `adaptive` 会话策略切换与确定性成对策略基准。
- Knowledge Map、Weakness Map、Improvement Path 以及知识点级回答证据。
- 自适应语音最终转录进入统一 Analyzer/Evaluator/Knowledge State 管线。

### Changed

- Docker 镜像包含 Alembic 配置和迁移文件。
- GitHub 更新脚本先拉取并构建，再短暂停服迁移和切换版本。
- UI 默认新评估会话使用自适应策略，旧 API 请求仍默认 `fixed`。

## [0.4.1] - 2026-07-16

### Added

- 蓝图生成可独立选择 OpenAI、Anthropic、Gemini 或 Ollama 模型。
- 文本答辩可独立选择模型，不再与蓝图生成模型绑定。
- AutoDL/Vultr Docker 部署持久化 Ollama 模型目录。

### Changed

- 将当前已部署、已验证的 v0.4 系列快照正式固化为可追溯版本。

## [0.4.0] - 2026-07-10

### Added

- OpenAI Realtime WebRTC 实时语音答辩。
- Semantic VAD、用户插话、实时字幕和按住说话模式。
- PDF/PPTX/DOCX 多模态证据、Golden Dataset 与 Benchmark。
- Redis/Celery 后台任务、Caddy HTTPS 和 Docker Compose 部署。

[Unreleased]: https://github.com/lanhung/ai-examiner/compare/v0.4.1...HEAD
[0.5.0-rc.4]: https://github.com/lanhung/ai-examiner/compare/v0.5.0-rc.3...v0.5.0-rc.4
[0.5.0-rc.3]: https://github.com/lanhung/ai-examiner/compare/v0.5.0-rc.2...v0.5.0-rc.3
[0.5.0-rc.2]: https://github.com/lanhung/ai-examiner/compare/v0.5.0-rc.1...v0.5.0-rc.2
[0.5.0-rc.1]: https://github.com/lanhung/ai-examiner/compare/v0.4.1...v0.5.0-rc.1
[0.4.1]: https://github.com/lanhung/ai-examiner/compare/9327580...v0.4.1
[0.4.0]: https://github.com/lanhung/ai-examiner/commit/9327580
