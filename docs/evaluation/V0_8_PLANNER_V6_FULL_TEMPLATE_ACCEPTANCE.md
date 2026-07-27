# v0.8 Planner v6 Full Template Acceptance

Date: 2026-07-27  
Branch: `develop/v0.8.0`  
Planner: `session-planner-v08-scenario-native-v6`

## Purpose

This evaluation replaces the v6 reciprocal smoke evidence with a complete,
balanced run for all seven reviewed templates. It also verifies the revised
open-answer assessment contract against real Qwen and OpenAI responses.

No Mock output is used as acceptance evidence.

## Method

Each template uses 30 unique frozen cases:

- 15 Chinese and 15 English cases;
- difficulty levels 2, 3 and 4, with 10 cases each;
- six cases each for excellent, partial, misconception, evasive and unsupported
  claim answers.

Each case is generated and judged in both provider directions:

```text
Qwen qwen-plus       -> production SessionPlanner generation
OpenAI gpt-5.4-mini  -> independent blind A/B judging

OpenAI gpt-5.4-mini  -> production SessionPlanner generation
Qwen qwen-plus       -> independent blind A/B judging
```

The judge receives anonymous baseline and scenario arms. Release evidence requires
30 unique cases, two judge providers, reciprocal cross-judging, production
`SessionPlanner` output and the current frozen-corpus fingerprint.

## Results

| Template | Gate | Relevance delta | 95% CI | High quality | Grounded | Single task | Unsafe |
|---|---|---:|---:|---:|---:|---:|---:|
| Grant review | Held | +0.250 | [0.091, 0.409] | 100.0% | 100% | 100% | 0% |
| Thesis defense | Held | -0.083 | [-0.233, 0.066] | 96.7% | 100% | 100% | 0% |
| Course oral | Held | +0.217 | [0.036, 0.398] | 96.7% | 100% | 100% | 0% |
| Technical interview | Held | +0.250 | [0.049, 0.451] | 93.3% | 100% | 100% | 0% |
| Product knowledge | Passed | +1.167 | [0.915, 1.418] | 100.0% | 100% | 100% | 0% |
| Sales objection | Passed | +1.733 | [1.458, 2.008] | 98.3% | 100% | 100% | 0% |
| Project review | Passed | +1.683 | [1.467, 1.899] | 100.0% | 100% | 100% | 0% |

Overall release-evidence status: **passed**.

The evaluator requires at least three templates to exceed a mean relevance
improvement of `0.5`; product knowledge, sales objection and project review pass.
The four held templates still meet grounding, single-task and safety requirements.
Their held status means that they are not sufficiently differentiated from the
academic thesis-defense baseline under this test, not that their questions are
unusable.

Thesis defense is expected to have the smallest separation because the compatibility
baseline is itself a thesis-defense template. Grant review, course oral and technical
interview need stronger scenario-native behavior before they can independently clear
the relevance-delta gate.

## Open-Answer Assessment Fix

`answer-analyzer-v3-defensible-alternatives` no longer treats expected points as
mandatory phrases or a uniquely required implementation.

The assessment contract now records:

- semantic equivalence;
- whether the functional criterion is satisfied;
- whether the answer explicitly conflicts with source evidence;
- whether a defensible alternative was accepted;
- over-specific, unsupported or ambiguous rubric issues;
- factual conflicts, logic failures, rubric mismatches and unverified claims as
  separate error classes.

For an open question that remains partially scored without an explicit source
conflict, a focused independent adjudication checks whether the answer is defensible.
The deterministic reconciliation layer grants full point credit when the adjudicator
accepts the answer, while preserving contradictions and vague answers.

Real-provider calibration used three cases in each provider:

| Case | Qwen | OpenAI |
|---|---|---|
| Semantic paraphrase | Supported, 100% coverage | Supported, 100% coverage |
| Defensible alternative | Supported, 100% coverage | Supported, 100% coverage |
| Explicit contradiction | Unsupported, 0% coverage | Unsupported, 0% coverage |

Result: **6/6 expected classifications**.

## Planner Defects Found and Fixed

The full run found three Chinese/English single-task boundary defects:

1. `研究设计` in declarative context was mistaken for a request verb before a
   final `是否` judgment question.
2. A quoted customer question mark was counted as a second examiner question.
3. An English `who ... and what ...?` prompt placed ownership and action in one
   turn but escaped the verb-based detector.

The detector now:

- scopes Chinese analysis from `是否`, `能否` and `会否`;
- ignores paired quoted content when counting active question marks;
- rejects two English interrogative tasks joined by `and`.

The affected project-review direction was regenerated from zero. Its final
single-main-question rate is 100%.

## Usage

Final accepted evidence contains:

| Metric | Value |
|---|---:|
| Complete reports | 14 |
| Unique frozen cases | 210 |
| Reciprocal case evaluations | 420 |
| Anonymous A/B arms judged | 840 |
| Provider calls | 924 |
| Input tokens | 1,953,498 |
| Output tokens | 630,175 |
| Aggregate provider latency | 8,677,259 ms |
| Estimated OpenAI cost | USD 2.0688 |
| Estimated Qwen cost | USD 0.2053 |
| Estimated total cost | USD 2.2742 |

Cost estimates use the repository model catalog prices dated 2026-07-10 for
OpenAI and 2026-07-16 for Qwen. Provider billing remains authoritative.

## Evidence

The committed aggregate evidence is:

```text
docs/evaluation/evidence/V0_8_PLANNER_V6_ALL7_RECIPROCAL_EVIDENCE.json
```

Raw checkpoints remain under `data/` and are intentionally excluded from Git
because they contain large generated artifacts.

## Remaining Work

1. Strengthen scenario-native behavior for grant review, course oral and technical
   interview until each independently exceeds the `+0.5` relevance threshold.
2. Keep thesis-defense interpretation tied to absolute quality because its baseline
   is already thesis-defense specific.
3. Add focused open-answer calibration cases for multi-point rubrics and answers
   that combine a valid alternative with an unrelated factual error.
4. Run the remaining Docker Compose and Vultr upgrade/rollback gates before a stable
   v0.8 tag.
