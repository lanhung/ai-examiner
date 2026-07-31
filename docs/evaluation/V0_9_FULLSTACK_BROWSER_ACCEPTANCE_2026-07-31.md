# v0.9 Full-stack Browser Acceptance

Date: 2026-07-31

## Scope

The deployed AutoDL build was exercised through the public HTTPS workbench and
enterprise console. The run covered real browser interactions, real Qwen model
calls, backend authorization checks and the local automated regression suite.

## Runtime baseline

- Application: `0.9.0.dev0`
- Text model: `qwen-plus`
- Visual model: `qwen3-vl-plus`
- Authentication mode: disabled development identity
- Storage: local streaming backend
- Database tenancy isolation: PostgreSQL RLS disabled in this staging profile
- OpenAPI paths: 117

This profile is suitable for controlled evaluation. It is not the production
enterprise security profile.

## Browser workflows

### Main workbench

Passed:

- created a project;
- uploaded and parsed a non-sensitive Markdown research fixture;
- loaded page-level evidence;
- bound the thesis-defense scenario template;
- generated a six-question blueprint with real Qwen Plus;
- completed Qwen3-VL visual review;
- started a text defense;
- received a low score and relevant follow-up for an unsupported claim;
- received a high score for a grounded answer;
- displayed evidence and cognitive selection reasons;
- rendered the workbench at a 390 x 844 mobile viewport without overlap.

### Scenario templates

All seven built-in templates passed API validation and compilation:

- grant review;
- thesis defense;
- course oral assessment;
- technical interview;
- product-knowledge assessment;
- sales-objection practice;
- project review.

The templates produce materially different assessment, assistance, question,
reporting and safety policies. Thesis defense defaults to fixed question order;
the other six tested templates default to adaptive selection.

### Enterprise console

Passed:

- development identity and active organization display;
- organization-scoped overview metrics;
- member and role inventory;
- model policy and budget display;
- audit event display;
- retention policy, legal hold and data-request display;
- human-review queue display;
- mobile layout at 390 x 844.

The mobile console remains usable, but the top navigation and organization
selector require horizontal scrolling or truncate long identifiers.

## Backend and security

Passed:

- anonymous enterprise membership request returned `401`;
- unknown principal returned `403`;
- active owner returned `200`;
- denied and successful access attempts were both written to the digest-chained
  audit log;
- all seven template validation and compilation endpoints passed;
- static JavaScript syntax checks passed;
- Ruff passed;
- the full Python suite completed 327 assertions successfully before the fixes
  in this report.

The Windows test runner emitted Proactor event-loop access-violation messages
after the successful pytest summary. This did not change the test exit code, but
process teardown remains a local Windows reliability concern.

## Real-model observations

### Qwen Plus

The generated blueprint was grounded in the uploaded material and included
questions about contribution, methodology, evidence quality and limitations.
Answer analysis correctly penalized unsupported causal claims and generated a
targeted follow-up.

### Qwen3-VL Plus

Visual analysis identified missing standard deviations, test statistics,
confidence intervals, inter-rater reliability, randomization details and
transfer-test validity. The call used the configured real provider, not Mock.

## Defects found and remediation

### Fixed: template strategy mismatch

The UI allowed adaptive selection, but template-bound requests sent an empty
override map. The thesis template therefore executed its fixed default while the
control still displayed adaptive.

The workbench now sends allowed question-strategy overrides to blueprint and
session resolution. Voice-provider selection is also included in the voice
template override.

### Fixed: response body consumed twice

The realtime SDP path read the Fetch response body during error handling and
then attempted to read it again for the successful remote description. Fetch
response bodies are one-shot streams, producing:

`Failed to execute 'text' on 'Response': body stream already read`

The response is now read exactly once and reused.

### Fixed: unbounded voice connection state

Microphone acquisition and SDP negotiation could leave the UI indefinitely in
the connecting state. Both stages now have bounded timeouts, cleanup and
actionable retry messages.

### Fixed: internal memory configuration message

When long-term memory is not configured, the UI no longer exposes the internal
`MEMORY_IDENTITY_SECRET` environment variable. It reports that the administrator
has not enabled the optional feature and clarifies that normal defense workflows
remain available.

## Deployment actions

For long-term memory on the AutoDL staging deployment, configure a stable,
server-only random value:

```bash
printf '\nMEMORY_IDENTITY_SECRET=%s\n' "$(openssl rand -hex 32)" >> .env
```

Do this only once and preserve the value across upgrades. Changing it breaks the
link between existing opaque learner identities and their future sessions.

After pulling this patch, rebuild the application so the `qa4` static asset
version is served:

```bash
docker compose down --remove-orphans
git pull --ff-only
docker compose up -d --build --remove-orphans
```

## Remaining release risks

- AutoDL staging is intentionally running without OIDC and PostgreSQL RLS.
- Browser microphone and speaker quality still depend on the physical device,
  browser permission state and upstream realtime service.
- Enterprise mobile navigation should be redesigned before general release.
- Provider health currently indicates configured availability; it is not a live
  end-to-end connectivity probe for every listed model.
- A production release still needs OIDC, RLS, backup/restore and recovery drills
  in the target deployment profile.

## QA4 deployed rerun

Commit `0e102bb` was fast-forward deployed to the AutoDL staging worktree and
port 6006 was restarted with the repository's guarded direct-process scripts.
The public workbench then loaded `app.js?v=0.9.0-qa4` and
`styles.css?v=0.9.0-qa4`.

The deployed rerun confirmed:

- a real Qwen Plus blueprint completed with six grounded questions;
- the same planner call took about 141 seconds, materially slower than the
  previous 48-second observation but still completed within its lease;
- a template-bound session persisted `question_strategy=adaptive`;
- after a successful answer, the next question reason codes were
  `required_objective_coverage`, `importance`, and `uncertainty`, not
  `fixed_order`;
- Qwen Realtime created an adaptive voice session and the public WebSocket
  received `session.created` without an upstream error;
- long-term memory became available after a stable server-only identity secret
  was generated on the AutoDL host;
- identity creation, subject linking, settings, memory-center read, asynchronous
  export and asynchronous deletion all completed successfully.

The Codex in-app browser could read and inspect the deployed page, but its own
analytics requests repeatedly timed out before click and fill operations were
delivered. Server access logs confirmed that those interrupted attempts emitted
no application POST request. This browser-control failure is therefore recorded
separately from AI Examiner behavior. Physical microphone and speaker acceptance
still requires an uninterrupted interactive browser run.
