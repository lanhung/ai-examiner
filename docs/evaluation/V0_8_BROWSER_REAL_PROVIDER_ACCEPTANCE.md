# v0.8 Browser and Real-Provider Acceptance Report

Date: 2026-07-24  
Branch: `develop/v0.8.0`  
Application version: `0.8.0.dev0`  
Test endpoint: `http://127.0.0.1:8016/`

## 1. Scope

This acceptance run verifies the v0.8 industry-template platform through the
actual browser application and paid Qwen providers. Mock results are used only
by the deterministic regression suite; they are not treated as evidence for the
real-provider product experience.

The run covers:

- built-in template catalog, filtering, preview and validation;
- local draft creation, editing, compilation and lifecycle gates;
- immutable template selection and session snapshots;
- real `qwen-plus` blueprint generation and text examination;
- adaptive/fixed policy resolution and decision audit data;
- evidence-backed assessment and report rendering;
- real Qwen vision analysis of a Chinese logical page preview;
- provider, cost and latency telemetry;
- responsive browser rendering and static UI regressions.

This run does not authorize a v0.8 production release. Docker Compose and Vultr
rehearsal gates remain separate, and the assessment-calibration findings in
section 7 must be addressed before a stable tag.

## 2. Environment

| Item | Value |
|---|---|
| Operating system | Windows development workstation |
| Browser surface | Codex in-app browser |
| API | FastAPI on port 8016 |
| Data | Isolated v0.8 SQLite and evidence directories |
| Text provider | Qwen `qwen-plus` |
| Vision provider | Qwen vision-capable profile |
| Worker mode | Celery eager mode for local acceptance |
| Template | `academic.thesis_defense@1.2.0` |

Credentials, prompt payloads, uploaded documents and raw user data are excluded
from this report and from version control.

## 3. Results Summary

| Area | Result | Evidence |
|---|---|---|
| Template health | Pass | Initial seed: 9 built-in versions across 7 identities; after the local draft test: 10 versions across 8 identities; no health issues |
| Catalog and filters | Pass | All seven built-in identities rendered; high-risk filter isolated the technical interview template |
| Effective-policy preview | Pass | Fingerprint, strategy, question/follow-up limits and weighted dimensions rendered |
| Draft authoring | Pass | Created and edited `local.v08_browser_test@0.8.0-test` |
| Lifecycle gates | Pass | Candidate transition was blocked before compilation and allowed after compilation |
| Publish gate | Pass | Publishing remained disabled without required release evidence |
| Immutable session snapshot | Pass | Session fingerprint verification returned integrity `verified` |
| Real blueprint | Conditional | Six material-grounded questions generated, but end-to-end latency was about 382 seconds |
| Real text examination | Conditional | Session completed and report rendered, but open-answer scoring showed over-literal reference matching |
| Real visual analysis | Pass after fixes | Chinese content was read correctly and the final output used Simplified Chinese |
| Evidence/report UI | Pass | Score, risk, trajectories, objective evidence, source links and disclaimer rendered without overlap |
| Cost telemetry | Pass | Provider/model calls, tokens, estimated cost and p50/p95 latency were recorded |

## 4. Real Qwen Text Run

The browser flow created a project, uploaded `examples/sample_research.md`,
generated a six-question blueprint, completed the text examination and rendered
the final report.

Observed report values:

- overall score: `3.7976 / 5`;
- risk: `low`;
- main questions answered: `6`;
- template snapshot: `academic.thesis_defense@1.2.0`;
- template fingerprint integrity: `verified`;
- template resolution source: `explicit`.

Observed Qwen usage:

| Metric | Value |
|---|---:|
| Text calls | 14 |
| Input tokens | 31,374 |
| Output tokens | 16,667 |
| Estimated text cost | USD 0.008116 |
| Text latency p50 | 15,762 ms |
| Text latency p95 | 58,371 ms |
| Initial project total including vision | USD 0.010139 |

Normal answer turns usually took 15 to 28 seconds. The real blueprint request was
the largest usability problem: it took roughly 382 seconds while the browser
showed only a static status message.

## 5. Real Visual Run and Fixes

The first visual run exposed a preview defect rather than a model defect. The
logical Markdown preview selected DejaVu before a CJK font, so Chinese glyphs
became boxes. The vision model then described those boxes as visible redactions.

The following fixes were implemented:

1. prefer Noto CJK and platform CJK fonts before DejaVu;
2. install `fonts-noto-cjk` in the Docker image;
3. require all natural-language visual-analysis fields to match the document
   language;
4. display only the latest visual analysis per evidence asset while retaining
   the complete backend audit history.

After regenerating the page preview and rerunning the real vision request, the
model correctly read the Chinese material and returned a Chinese analysis.

## 6. Template Runtime Findings

The selected thesis-defense template compiled to a fixed-order question strategy.
The browser still exposed an adaptive selection control, but the immutable
template contract correctly overrode it and recorded `fixed_order` in the
selection audit.

This behavior is contract-safe, but the current UI can mislead a user into
believing their adaptive selection will take effect. The session setup should
either disable overridden controls or show the effective template value before
the session starts.

## 7. Blocking Quality Findings

### 7.1 P1: Open-answer assessment is too literal

Several materially defensible answers received low first-attempt scores because
the generated expected points encoded one exact implementation or wording:

- a semantically equivalent description of evidence/log comparison was marked
  missing;
- relevant evidence from another part of the supplied document was treated as a
  contradiction because the active source excerpt was too narrow;
- a nuanced governance answer was penalized for not repeating the planner's
  preferred boundary statement;
- a plausible safer architecture was penalized because it did not place a check
  at one preselected pipeline location;
- a follow-up required state names that were not defined by the source summary.

Required optimization:

- expected points for open, design, critical and transfer questions must score
  reasoning criteria rather than prescribe one solution;
- every factual expected point must be supported by the supplied source evidence;
- evaluators must accept defensible alternatives when assumptions and trade-offs
  are stated;
- `contradicted` must be reserved for actual incompatible claims, not additional
  relevant evidence or a missing phrase;
- unsupported follow-ups must be rejected or rewritten before presentation;
- add frozen real-answer cases covering semantic paraphrases, alternative
  architectures and evidence from multiple document sections.

### 7.2 P1: Blueprint latency and progress feedback

A roughly six-minute blueprint request is not acceptable for an interactive
product. The current page does not expose phase progress, retry state or a cancel
action.

Required optimization:

- move blueprint generation to a resumable background job;
- show planner phase, elapsed time, retry count and cancel/retry actions;
- bound provider timeouts and persist partial progress;
- reduce prompt/context size and measure planner-specific p50/p95 separately;
- avoid silently repeating an expensive full planning call when only contract
  repair is needed.

### 7.3 P2: Template-overridden controls are not obvious

Render the effective strategy, assistance and interruption values beside any
control overridden by the selected template. Disabled controls should explain
which immutable policy supplied the value.

### 7.4 P2: Local Python runtime shutdown fault

The full suite passed under the existing Anaconda Python 3.11.5 environment, but
that interpreter printed an access-violation message during async interpreter
shutdown. It did not change the test exit code and did not occur in application
requests.

The same source state was subsequently verified in an isolated CPython 3.12
environment matching the Docker target:

- 140 tests collected and passed;
- Ruff passed;
- Python `compileall` passed;
- browser JavaScript syntax check passed;
- no interpreter-shutdown access violation occurred.

The shutdown message is therefore classified as a local Anaconda 3.11.5 runtime
problem, not an application failure.

## 8. Release Decision

Status: **conditional development acceptance; stable release held**.

The v0.8 template platform, immutable contracts, browser studio, real Qwen text
flow and real visual flow are operational. The release remains held because:

1. assessment robustness for open answers is not yet calibrated;
2. blueprint latency and progress UX are outside an acceptable interactive range;
3. Docker Compose and Vultr rehearsals must pass on the final source state.

## 9. Next Verification

1. Add assessment fixtures for paraphrases and alternative defensible answers.
2. Optimize and instrument blueprint generation.
3. Repeat the same real Qwen browser case.
4. Run isolated Docker Compose rehearsal.
5. Deploy the release candidate to Vultr and execute backup, migration, health,
   restart and rollback checks.
6. Create a stable `v0.8.0` tag only after all held gates pass.
