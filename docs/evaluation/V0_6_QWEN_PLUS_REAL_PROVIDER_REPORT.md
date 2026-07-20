# v0.6 Qwen Plus Real-Provider Evaluation Report

## 1. Document purpose

This report records the first complete browser-based v0.6 text examination run that used
Alibaba DashScope `qwen-plus` for both blueprint generation and answer analysis. It turns the
observed failures into an implementation plan that Codex can execute and verify.

This is a development evaluation, not a release acceptance report. The source material was an
internal architecture decision record rather than an independently labelled academic paper.

## 中文执行摘要

本轮使用真实 `qwen-plus` 完成了蓝图生成、6 个主问题、5 次追问、知识状态更新和最终
报告，全程没有使用 Mock。调用共 12 次，输入 15,276 Token、输出 6,221 Token，估算费用
约 0.00343 美元。功能闭环可以运行，追问上下文修复有效，浏览器没有应用错误。

当前最严重的问题不是千问本身“评分严格”，而是确定的程序契约错误：千问返回
`correct / partially_correct`，系统评分和认知状态只认识
`supported / partially_supported`。未知标签在 Evaluator 中被当作 0.3，在认知状态中被
当作 0.1。因此，即使回答被千问判断为正确、覆盖率 100%、有证据，页面得分也被封顶在
约 3.4/5，知识掌握度也被错误压低。现有 2.98/5 总分、medium 风险和 38%-60% 知识掌握度
不能作为有效质量结论。

优化必须按以下顺序进行：

1. 建立唯一的正确性枚举、别名归一化和严格校验，禁止未知标签静默降级；
2. 让 Evaluator、Knowledge State 和 Benchmark 共用同一契约，并重建受影响的开发数据；
3. 将模型自由给出的 coverage 改为逐要点评价，再由程序确定性计算覆盖率；
4. 将“是否有证据”的布尔值拆成来源依据、推理质量和边界意识；
5. 报告按主问题聚合独立表现、追问后表现和学习增益，不再平均所有回答轮次；
6. 持久化模型延迟和重试信息，随后再优化 Prompt、上下文长度和输出上限；
7. 修复中文会话生成英文问题、完成后仍显示“正在协作”等交互问题。

结论：真实千问接入功能可用且成本低，但当前评分、知识状态和报告受到 P0 契约缺陷影响，
尚不能进入 v0.6 发布候选。应先完成本文 `WP-Q1`，再重复同一真实模型测试。

## 2. Test baseline

| Item | Value |
|---|---|
| Date | 2026-07-20 |
| Branch | `develop/v0.6.0` |
| Commit | `5618b55` |
| Application version | `0.6.0.dev0` |
| Browser endpoint | `http://127.0.0.1:8016/` |
| Blueprint provider | `qwen:qwen-plus` |
| Text examination provider | `qwen:qwen-plus` |
| Question strategy | `adaptive-v1` |
| Source document | `docs/decisions/ADR-003-REALTIME-CONVERSATION-CONTROL.md` |
| Parsed source | 3,122 characters, 1 logical page, 2 evidence assets |
| Generated blueprint | 7 main questions |
| Session limit | 6 main questions, at most 2 follow-ups per main question |

No Mock provider was used in blueprint generation, answer analysis, scoring inputs or report
generation during this run. Mock remained visible elsewhere in the page as an available offline
provider, but it was not selected for the tested workflow.

## 3. Observed results

### 3.1 Functional result

The following flow completed successfully:

```text
Create project
-> upload and parse ADR-003
-> generate a Qwen Plus blueprint
-> start an adaptive session
-> answer 6 main questions and 5 follow-ups
-> update knowledge state
-> generate an evidence-linked report
-> display provider cost
```

Confirmed working behavior:

- the selected provider remained `qwen-plus` throughout the tested flow;
- the adaptive selector chose six distinct main questions;
- follow-up answers were evaluated against the active follow-up text;
- the session continued after a follow-up limit instead of ending early;
- evidence cards linked the evaluated turns back to the source page;
- the final report included a knowledge map and improvement path;
- the browser produced no application error or warning logs;
- the session completed without malformed JSON or provider fallback.

### 3.2 Usage and cost

Database usage records for the project show:

| Metric | Result |
|---|---:|
| Provider calls | 12 |
| Planner calls | 1 |
| Answer Analyzer calls | 11 |
| Input tokens | 15,276 |
| Output tokens | 6,221 |
| Estimated total cost | USD 0.00342509 |
| Estimated planner cost | USD 0.00113020 |
| Estimated answer-analysis cost | USD 0.00229489 |

The cost is suitable for development-scale text evaluation. It does not yet include a Golden
Dataset benchmark, a second judge model, visual analysis or realtime audio.

### 3.3 Latency

Manual browser observations showed:

- blueprint generation took approximately 67 seconds;
- a typical answer-analysis round took approximately 16-17 seconds;
- the UI remained responsive while waiting, but the delay is too high for natural spoken dialog.

These measurements are provisional. `UsageEvent` currently records tokens and cost but does not
record latency for the normal planner/analyzer path, so p50, p95 and provider-network breakdowns
cannot yet be computed from persisted data.

### 3.4 Scoring result

The report produced:

| Metric | Result |
|---|---:|
| Evaluated answers | 11 |
| Overall score | 2.98 / 5 |
| Risk level | `medium` |
| High-score evidence | none |

The Analyzer output included six turns labelled `correct` with `coverage=1.0` and
`evidence_present=true`. Every one of those turns still received only `3.4/5`. This is a confirmed
software contract defect, not merely conservative model judgement.

## 4. Findings

### P0-1: Correctness labels drift between the provider and evaluator

**Status:** confirmed defect.

`AnswerAnalyzer` documents the canonical labels as:

```text
supported
partially_supported
unsupported
insufficient
```

The real Qwen response used:

```text
correct
partially_correct
```

`Evaluator` does not recognize these values and silently assigns the fallback correctness value
`0.3`. A nominally perfect Qwen result is therefore calculated as:

```text
(0.45 * 0.3 + 0.35 * 1.0 + 0.20 * 1.0) * 5 = 3.425
```

After rounding, the visible ceiling becomes `3.4/5`.

Affected modules:

- `src/ai_examiner/agents/analyzer.py`
- `src/ai_examiner/agents/evaluator.py`
- `src/ai_examiner/providers/schema_utils.py`

The compact schema hint uses a pipe-delimited string, but `hint_to_json_schema()` converts every
string to a generic JSON Schema string. It does not emit an `enum`, so the provider is not actually
constrained to the advertised values.

### P0-2: The same label drift corrupts the cognitive state

**Status:** confirmed defect with larger downstream impact.

`CognitiveStateService` uses the same canonical labels, but its unknown-label fallback is `0.10`,
not `0.30`. Consequently, a Qwen answer labelled `correct` is stored as if it had only 10%
correctness before coverage and evidence are combined.

This explains why the final knowledge map showed only 38%-60% mastery despite several complete,
well-reasoned answers. The defect affects:

- mastery updates;
- weakness ordering;
- next-question difficulty;
- cross-session learner state;
- report risk level and improvement path.

Historical evidence events created by the affected run remain auditable, but their derived state
must be rebuilt after label normalization is fixed.

### P1-1: The Analyzer can make high-confidence false-negative judgements

**Status:** observed; requires a labelled calibration set before changing thresholds.

Several detailed answers were judged `partially_correct` with confidence between 0.87 and 0.96.
Some generated errors were critiques of terminology rather than actual contradictions. One report
item claimed that `scoring` was not grounded even though ADR-003 explicitly contains a scoring
neutrality requirement.

Likely causes:

- expected points are treated too literally;
- the model is asked to produce a scalar coverage estimate without point-level decisions;
- `errors` mixes factual errors, missing detail, terminology differences and stylistic criticism;
- confidence is self-reported by the same model and is not calibrated;
- source evidence and acceptable external architectural reasoning are not separated.

### P1-2: Evidence quality is represented by one Boolean

**Status:** confirmed design limitation.

`evidence_present` becomes either `5.0` or `1.75` in the evaluator. This loses important
distinctions among:

- direct source grounding;
- correct reasoning without a quotation;
- a concrete implementation example;
- an unsupported assertion;
- a relevant but weak example.

An oral answer can demonstrate strong reasoning without quoting the source verbatim. The current
Boolean can therefore over-penalize valid explanations and produce abrupt score changes.

### P1-3: The overall report averages attempts instead of assessed questions

**Status:** confirmed design limitation.

The report calculates the arithmetic mean of all evaluated user turns. In this run, six main
questions and five follow-ups became eleven equally weighted score entries.

This causes three problems:

1. A concept with two follow-ups has three times the weight of a concept answered immediately.
2. An initially weak answer and its successful recovery are both counted as independent exam items.
3. Examination mode and coaching mode cannot express different policies for assisted improvement.

The report should expose independent performance, assisted performance and learning gain rather
than collapsing every attempt into one average.

### P1-4: Report weaknesses are not evidence-qualified

**Status:** observed.

`ReportGenerator` concatenates every `missing_points` and `errors` item and places the first unique
strings into `priority_weaknesses`. It does not require:

- repeated occurrence;
- a supporting source excerpt;
- minimum confidence;
- validation against a later successful follow-up;
- distinction between a misconception and a missing detail.

As a result, superseded or questionable model critiques can become prominent report conclusions.

### P1-5: User-facing language is not reliably enforced

**Status:** observed.

The project language was `zh-CN`, but all Qwen-generated questions and follow-ups were English.
The answers and surrounding UI were Chinese. This is usable for bilingual testing but violates the
configured-language expectation.

### P1-6: Completion status text remains stale

**Status:** confirmed UI defect.

After the report is generated, the disabled answer area can still show:

```text
Answer Analyzer、Evaluator 和 Policy Controller 正在协作…
```

The session itself is correctly marked completed. `app.js` does not replace `answerHint` in the
completed branch.

### P2-1: Normal planner/analyzer latency is not persisted

**Status:** confirmed observability gap.

Without persisted latency, optimization cannot distinguish:

- provider queue time;
- connection and network time;
- server processing time;
- JSON repair retries;
- prompt-size effects;
- model generation time.

### P2-2: Current automated tests do not cover provider label drift

**Status:** confirmed test gap.

Mock returns the canonical labels, so existing tests pass while the real provider contract fails.
Tests need recorded real-provider-shaped fixtures, including valid JSON that uses unexpected but
semantically recognizable labels.

## 5. Optimization design

### 5.1 P0 stabilization: create one canonical assessment contract

Introduce a provider-independent contract, for example:

```python
class Correctness(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    INSUFFICIENT = "insufficient"
```

Normalize aliases at the model boundary:

```text
correct -> supported
fully_correct -> supported
partially_correct -> partially_supported
incorrect -> unsupported
not_answered -> insufficient
```

Required behavior:

- persist `raw_correctness` and `normalized_correctness` for audit;
- reject unknown labels after one structured-output correction attempt;
- never silently assign a scoring fallback for an unknown label;
- make Evaluator and CognitiveStateService consume the same enum and numeric mapping;
- add a rebuild command for affected knowledge states;
- leave immutable raw answer and Analyzer output evidence untouched.

Do not fix this only by adding two keys to `Evaluator`. That would leave the cognitive service,
benchmark labels and future providers vulnerable to the same drift.

### 5.2 Replace pipe-delimited schema hints with real enums

The structured-output schema must express categorical constraints. Recommended options, in order:

1. define Pydantic response models and generate JSON Schema from them;
2. extend the compact schema format with an explicit enum object;
3. retain post-response validation even when the provider claims strict schema support.

Example schema fragment:

```json
{
  "correctness": {
    "type": "string",
    "enum": [
      "supported",
      "partially_supported",
      "unsupported",
      "insufficient"
    ]
  }
}
```

### 5.3 Move from scalar coverage to point-level assessment

The model should classify each expected point instead of inventing a single coverage number:

```json
{
  "point_assessments": [
    {
      "point_id": "P1",
      "status": "covered|partial|missing|contradicted",
      "answer_quote": "...",
      "source_evidence_id": "...",
      "reason": "..."
    }
  ]
}
```

The application then computes weighted coverage deterministically. This improves auditability and
makes model disagreements diagnosable.

Recommended deterministic values:

```text
covered      1.00
partial      0.50
missing      0.00
contradicted 0.00 plus an explicit error flag
```

Weights should come from the rubric or blueprint, not from the answer model.

### 5.4 Separate correctness, grounding and reasoning

Replace `evidence_present` with independent dimensions:

```text
answer_correctness
expected_point_coverage
source_grounding
reasoning_quality
boundary_awareness
```

Each dimension must include an answer quote and a reason. The first revised weights should be
treated as a candidate policy and calibrated, not assumed correct. A reasonable starting candidate
for research-defense mode is:

```text
correctness       35%
point coverage    25%
source grounding  15%
reasoning quality 15%
boundary awareness 10%
```

### 5.5 Report question trajectories instead of averaging all attempts

Create a per-main-question trajectory:

```json
{
  "question_id": "Q4",
  "independent_score": 2.8,
  "final_assisted_score": 4.2,
  "followup_count": 2,
  "assistance_level": "followup",
  "learning_gain": 1.4,
  "remaining_gaps": []
}
```

Mode-specific aggregation:

- **exam mode:** overall score uses independent main-question answers; assisted performance is
  shown separately and does not replace the exam score;
- **coaching mode:** show independent score, assisted score and learning gain; use a documented
  weighted aggregate only if a single number is required;
- **discussion mode:** avoid a high-stakes overall score and emphasize evidence and open questions.

Resolved missing points must not remain in `priority_weaknesses` unless the final answer still lacks
them or the same issue occurs in another independent question.

### 5.6 Calibrate Qwen Plus with a frozen evaluation set

Create a small, high-signal calibration set before changing score thresholds:

```text
20 grounded questions
x 4 answer levels
= 80 labelled answer cases
```

Required answer levels:

- excellent;
- acceptable but incomplete;
- fluent misconception;
- evasive or unanswered.

At least 20 cases should specifically test semantic paraphrases that do not reuse expected-point
wording. Include Chinese questions, English questions and cross-language answers.

For each case, store:

- expected correctness class;
- acceptable coverage interval;
- required and optional points;
- forbidden factual errors;
- whether source citation is necessary;
- expected follow-up action;
- expert or adjudicated rationale.

Run the same frozen set against Qwen Plus and at least one independent judge. Do not let the tested
model be the sole author and sole judge of its own calibration set.

### 5.7 Latency instrumentation and reduction

First add measurements:

- `latency_ms` on normal `UsageEvent` records;
- optional `provider_connect_ms`, `first_token_ms`, `generation_ms` when available;
- `retry_count` and `json_repair_used`;
- input/output tokens per call;
- p50 and p95 by provider, model and agent.

Then optimize in this order:

1. cap Analyzer output to the compact assessment schema;
2. send only the active question, parent context and the minimum relevant history;
3. send evidence IDs and concise excerpts instead of redundant blueprint content;
4. lower Analyzer `max_tokens` from the generic 8,000 ceiling after measuring truncation risk;
5. add configurable fast/quality model routing without silent fallback;
6. use provider streaming only where it improves visible responsiveness without weakening the
   structured final decision;
7. keep deterministic evaluation local after the structured Analyzer result.

Target gates for text mode:

```text
Analyzer p50 <= 5 seconds
Analyzer p95 <= 10 seconds
Blueprint p95 <= 45 seconds for a 5,000-character document
Structured-output success >= 99%
Silent provider fallback = 0
```

Realtime voice requires stricter conversational timing and must not wait for this full Analyzer
call before performing media-layer barge-in.

### 5.8 Language enforcement

Planner and Interviewer contracts must explicitly require the configured session language for all
user-facing prose. Source quotations may retain their original language.

Add deterministic checks for:

- requested language represented in generated questions;
- no accidental provider-language switch between a main question and follow-up;
- bilingual mode only when explicitly configured.

### 5.9 UI completion state

When `result.completed` is true:

- replace the working hint with a clear completion message;
- keep the input and submit button disabled;
- surface report-generation failure separately from answer-analysis failure;
- scroll only after report content is available;
- add a retry action if report retrieval fails.

## 6. Implementation work packages

### WP-Q1: Canonical correctness contract

Priority: P0.

Deliverables:

- shared correctness enum and alias normalizer;
- strict structured-output validation;
- Evaluator and cognitive service use the shared mapping;
- recorded Qwen fixtures for `correct` and `partially_correct`;
- knowledge-state rebuild support;
- regression tests for perfect-answer scores.

Acceptance:

- `correct + coverage=1 + evidence=true` is no longer capped at 3.4;
- unknown labels cause a controlled validation error, never a silent fallback;
- Evaluator and cognitive event correctness values agree exactly;
- existing canonical Mock cases remain unchanged.

### WP-Q2: Point-level Analyzer v2

Priority: P1.

Deliverables:

- expected-point identifiers and optional weights;
- point-level coverage output with answer quotes;
- deterministic coverage calculation;
- separate grounding and reasoning dimensions;
- prompt registry version `answer_analyzer:v2`;
- v1/v2 benchmark comparison.

Acceptance:

- semantic paraphrase cases are not penalized for wording differences;
- every missing point has a point ID and reason;
- coverage can be reproduced from stored point assessments;
- false critical-error rate is below the frozen-set threshold.

### WP-Q3: Assessment trajectory and report v2

Priority: P1.

Deliverables:

- per-question attempt trajectories;
- independent, assisted and learning-gain metrics;
- resolved-gap suppression;
- evidence-qualified weakness ranking;
- report schema versioning and backward-compatible rendering.

Acceptance:

- six main questions always contribute six independent score units regardless of follow-up count;
- follow-up success is visible without inflating or duplicating the main score;
- every priority weakness links to a turn, answer quote and source/rubric point;
- report conclusions do not retain a gap that was resolved in the same trajectory.

### WP-Q4: Provider latency telemetry

Priority: P1 for voice readiness, P2 for text-only use.

Deliverables:

- database migration for usage latency and retry metadata;
- timed BaseAgent/provider calls;
- p50/p95 cost and latency API;
- browser latency display;
- Qwen Plus before/after benchmark.

Acceptance:

- 100% of paid planner/analyzer calls contain total latency;
- retries and repaired JSON are visible;
- dashboards distinguish planner and analyzer latency;
- no API key or request payload is written to telemetry.

### WP-Q5: Language and completion UI fixes

Priority: P1.

Deliverables:

- enforce session language in Planner and Interviewer;
- clear completed-state hint;
- report retry state;
- Chinese, English and bilingual browser tests.

Acceptance:

- a `zh-CN` session produces Chinese user-facing questions by default;
- completion never displays an active-analysis message;
- browser error logs remain empty in the successful flow.

## 7. Required test matrix

### 7.1 Unit tests

- every canonical correctness label;
- every supported alias;
- unknown-label rejection;
- evaluator/cognitive numeric mapping parity;
- point-level coverage calculation;
- report trajectory aggregation;
- resolved weakness removal;
- completed UI state.

### 7.2 Provider contract fixtures

- Qwen response using canonical labels;
- Qwen response using known aliases;
- Qwen response using an unknown label;
- malformed JSON followed by a valid repair response;
- high-confidence false-negative fixture;
- Chinese configured language with English source material.

### 7.3 Behavioral evaluation

Minimum release-candidate gates:

| Metric | Gate |
|---|---:|
| Correctness-label contract success | 100% |
| Excellent-answer severe under-score rate | < 5% |
| Fluent misconception severe over-score rate | < 5% |
| Coverage MAE | <= 0.15 |
| Critical-error precision | >= 0.85 |
| Follow-up relevance | >= 0.85 |
| Evidence-qualified report weaknesses | 100% |
| Structured-output success | >= 99% |

### 7.4 Real-provider browser regression

Repeat the same ADR-003 run with:

- `qwen-plus` blueprint and Analyzer;
- six main questions;
- at least three follow-ups;
- one deliberately excellent answer;
- one partial answer;
- one misconception;
- one evasive answer.

The run must record provider, model, prompt version, policy version, tokens, cost and latency.

## 8. Recommended execution order

```text
WP-Q1 canonical correctness contract
-> rebuild affected development knowledge states
-> repeat the real Qwen test
-> freeze the 80-case calibration set
-> WP-Q2 point-level Analyzer v2
-> WP-Q3 report trajectories
-> WP-Q4 latency telemetry and optimization
-> WP-Q5 language/UI completion fixes
-> full v0.5 regression plus v0.6 voice regression
```

Do not tune the visible score threshold before WP-Q1. The current scores are mathematically
corrupted by label drift, so threshold tuning would hide the defect rather than correct it.

## 9. Release decision

Current decision: **not ready for a v0.6 release candidate**.

The provider integration is functionally usable and inexpensive, and the adaptive follow-up fixes
are working. However, the correctness-label mismatch invalidates scores, knowledge states and parts
of the final report for real Qwen sessions. WP-Q1 is a blocking fix.

After WP-Q1, the same browser run should be repeated before broader v0.6 voice implementation is
used as evidence of assessment quality. Voice work may continue at the media/FSM layer, but no
release claim about cognitive accuracy should rely on the affected scoring pipeline.
