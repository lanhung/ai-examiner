# Question Language and Source-Rule Investigation

Date: 2026-10-26. Application version remains 0.9.

## Reported symptoms and evidence

- The phone screenshot shows a main question asking how two methodological
  constraints support research validity. The phrases concern limiting follow-ups
  and not providing standard answers in hints.
- A narrowly scoped, read-only check confirmed both phrases exist in the uploaded
  source document. The displayed turn, session, blueprint and document refer to
  the same project/tenant. This screenshot is not evidence of prompt leakage.
  Do not blacklist these phrases: they can be legitimate research content.
- Separate conversation metadata confirmed English-heavy assistant questions in a
  Chinese session. The affected older sessions did not have a language snapshot.
- The reported source-rule question and the earliest English-heavy turn predate
  the isolated concurrency run. No evidence found attributes these symptoms to
  concurrent test data. This is a scoped trace, not a complete isolation audit.
- No document bodies, credentials, or complete private conversations are included
  in this report. The screenshot was inspected at the user's request.

## Root cause and changes

1. Answer Analyzer previously received no explicit response-language contract.
   Its English instructions could produce English follow-up candidates even when
   the active question was Chinese. Both initial analysis and normalization repair
   now carry the requested language; evidence quotes and enum keys stay unchanged.
2. Policy Controller previously displayed candidates without a language check.
   It now uses a valid analyzer candidate, otherwise a valid blueprint follow-up,
   otherwise a localized evidence question. This adds no translation-model call.
3. The selected fallback is recorded in the policy decision. Rendering and the
   next answer's active-question assessment use that same question, avoiding a
   mismatch between what the learner sees and what gets scored.
4. New sessions snapshot the blueprint/project language. Legacy sessions resolve
   language from their config, blueprint, then project. Original history is not
   rewritten. Transcript assessment receives the same language.
5. Planner used to accept an entire blueprint if any Chinese appeared in its
   title, summary or questions. It now checks each question and follow-up. Original
   paper titles, filenames, source quotes and technical terms remain permitted.
   Existing bounded repair behavior is retained.
6. Planner and Analyzer prompts distinguish source facts from operating rules.
   Questions may discuss a rule present in the research material, but should not
   invent source facts from assistance/scoring instructions. This prompt safeguard
   is not a claim that all future prompt leakage is impossible.

Prompt revisions: `session-planner-v08-scenario-native-v9-language` and
`answer-analyzer-v5-session-language`. No application-version increment, model
switch, permissions change, budget increase or data migration.

## Verification

Local regression command (isolated database and deterministic test providers):

```powershell
.venv/Scripts/python.exe -m pytest tests/test_question_language.py tests/test_assessment_contract.py tests/test_policy.py tests/test_planner_wording_repair.py tests/test_blueprint_model_output.py tests/test_template_conversation_policy_v08.py tests/test_template_session_binding_v08.py tests/test_school_exams.py tests/test_realtime_voice_v04.py -q -o addopts= --tb=short
```

Result: **122 passed**. Ruff passed. Existing Starlette and Alembic deprecation
warnings remain. Coverage includes old sessions, persisted follow-up text,
mixed-language source material, all seven template wording-repair fixtures,
school assessment and transcript evaluation.

Deployment: reviewed the seven-file diff against a freshly downloaded server
baseline; checked pre-deploy hashes; backed up source; checked idle background
jobs; gracefully restarted API and worker preserving their environment. All
seven deployed hashes matched. `/health` and `/ready` returned HTTP 200.

Post-deploy real-model probe: **qwen-plus**, synthetic question/answer only,
existing tenant governance and budget, no fallback provider. An English history
message was deliberately included with a Chinese active question. All three raw
follow-up candidates were Chinese; Policy selected `ASK_FOLLOWUP` from `analyzer`
without a language fallback. Example: asking why keyword rules may fail across
courses, referring to their single-course source.

Measured analyzer time: **22.58 seconds**, **2 structured-output calls** (initial
analysis plus the existing normalization-repair path), 2,489 input tokens and 984
output tokens. No translation call was added. Usage was recorded. This small
backend probe is not phone/UI end-to-end acceptance, a concurrency test, or a p95
latency claim. No new Planner generation job was needed for this probe.

## Limits and retest

- The Chinese-language check is a lightweight heuristic, not a semantic language
  classifier. It permits technical terms and does not validate question quality.
- If the analyzer's candidate is rejected, a generic/blueprint question may be less
  specific; `policy_audit.followup_source` and
  `rejected_followup_language_count` expose that fallback for review.
- Historic English messages remain unchanged. Existing blueprint main questions
  are not automatically translated or rewritten; regenerate an old blueprint if
  its main questions themselves are wrong-language.
- Continue a Chinese session with a short or incomplete answer and confirm the
  next follow-up is Chinese. Include an English source excerpt and terminology to
  ensure neither is altered. Device-level confirmation remains separate from
  backend and API tests.
