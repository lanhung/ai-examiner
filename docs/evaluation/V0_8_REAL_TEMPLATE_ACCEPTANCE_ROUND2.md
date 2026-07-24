# v0.8 Real Template Acceptance Round 2

Date: 2026-07-24  
Branch: `develop/v0.8.0`  
Planner: `session-planner-v08-scenario-native-v6`

## 1. Purpose

This round answers whether each reviewed v0.8 scenario template changes real
model behavior, rather than merely changing metadata or visible role labels.

The acceptance evidence uses the production `SessionPlanner` path, frozen
scenario material, anonymous baseline/scenario arms and independent cross-provider
judging. Mock output is not accepted as real-template evidence.

## 2. Provider Directions

The four templates without prior full real-provider coverage were tested in both
directions:

```text
Qwen qwen-plus       -> generation
OpenAI gpt-5.4-mini  -> blind judging

OpenAI gpt-5.4-mini  -> generation
Qwen qwen-plus       -> blind judging
```

Each direction used one frozen Chinese difficulty-2 case per template. This is a
reciprocal acceptance smoke test, not a replacement for the 30-case release gate.

The remaining three templates retain the existing 30-case reciprocal evidence
from v0.8 Increment N.

## 3. Current v6 Reciprocal Results

The values below are means across the two provider directions.

| Template | Relevance | Discrimination | Follow-up | Rubric fit | Report | Grounded | Single task | Unsafe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Grant review | 4.0 -> 4.5 | 3.5 -> 4.5 | 3.5 -> 4.5 | 3.5 -> 4.5 | 4.0 -> 4.5 | 100% | 100% | 0% |
| Thesis defense | 4.5 -> 4.5 | 4.5 -> 4.5 | 4.5 -> 4.5 | 4.5 -> 4.5 | 4.5 -> 4.5 | 100% | 100% | 0% |
| Course oral | 4.0 -> 4.0 | 3.5 -> 3.5 | 3.5 -> 4.0 | 4.0 -> 4.0 | 4.0 -> 4.5 | 100% | 100% | 0% |
| Technical interview | 2.5 -> 4.5 | 2.0 -> 5.0 | 3.0 -> 5.0 | 2.0 -> 5.0 | 3.0 -> 5.0 | 100% | 100% | 0% |

Interpretation:

- technical interview has the clearest behavioral separation from the generic
  oral-exam baseline;
- grant review improves scientific-value evidence, follow-up usefulness, rubric
  fit and report actionability;
- thesis defense matches the baseline because the compatibility baseline is
  already thesis-defense oriented;
- course oral improves clarity, follow-up and report behavior, but this tiny
  low-difficulty slice does not show a relevance or discrimination advantage.

## 4. Existing Full-Corpus Evidence

These results use 30 unique cases per template, reciprocal providers and 60 judge
observations per template. They were produced with the previous Planner prompt and
remain historical evidence only after the v6 Planner change.

| Template | Relevance delta | 95% CI | High quality | Grounded | Single question | Unsafe |
|---|---:|---:|---:|---:|---:|---:|
| Product knowledge | +1.017 | [0.772, 1.261] | 98.3% | 100% | 100% | 0% |
| Sales objection | +1.500 | [1.186, 1.814] | 98.3% | 100% | 100% | 0% |
| Project review | +1.667 | [1.494, 1.839] | 100% | 100% | 100% | 0% |

## 5. Real Defects Found

### 5.1 Semantic stacked questions

The prior contract rejected multiple question marks and numbered subquestions,
but real Qwen output could hide two tasks behind one question mark:

```text
说明……并判断……
说明……并明确……
```

Some follow-ups also combined a choice with a second explanation request.

Fix:

- detect connected Chinese and English request verbs;
- apply the single-task rule to follow-ups as well as main questions;
- trigger bounded Planner repair;
- update the Mock fixture that contained the same defect;
- add false-positive protection for declarative source context.

### 5.2 Repair-induced difficulty collapse

One repaired thesis-defense question became a page-location recall question and
received only `3/5` for discrimination.

Fix:

- require contract repair to preserve scenario objective, difficulty and
  reasoning demand;
- prohibit analytical questions from being reduced to page-location, term-recall
  or yes/no prompts unless the scenario explicitly calls for them.

### 5.3 False positive from source context

The first semantic detector treated the declarative phrase `材料说明……` as a user
request before the actual question `你应如何判断……`.

Fix:

- scope semantic detection to the final explicit request sentence;
- add regression coverage for Chinese declarative context.

The interrupted reciprocal probe resumed from its atomic 1/4 checkpoint and
completed without repeating the paid first case.

## 6. Final v6 Artifact Review

The final Qwen-generated main questions and follow-ups were checked by:

1. the deterministic single-task validator;
2. the independent OpenAI blind judge;
3. direct text inspection.

All eight current Qwen artifacts were:

- grounded in the frozen material;
- one main task per turn;
- free of prohibited or unsafe behavior;
- scored between `3/5` and `5/5` across quality dimensions.

The `3/5` course-oral discrimination score is retained as a real finding rather
than hidden by another repair.

## 7. Usage

The final v6 reciprocal smoke test used:

| Metric | Value |
|---|---:|
| Provider calls | 24 |
| Input tokens | 50,324 |
| Output tokens | 12,399 |
| Aggregate provider latency | 189,210 ms |

Intermediate pre-fix probes are excluded from these totals.

## 8. Release Impact

Status: **all seven templates now have real-provider evidence, but the stable
release gate remains held**.

Evidence depth is intentionally different:

- product knowledge, sales objection and project review: 30-case historical
  reciprocal evidence;
- grant review, thesis defense, course oral and technical interview: current v6
  reciprocal smoke evidence with two judge observations each.

Because Planner v6 changes runtime behavior, the previous 30-case v4 reports are
stale for a stable release. The full corpus must be regenerated under v6 before a
`v0.8.0` stable tag.

## 9. Next Actions

1. Expand grant review, thesis defense, course oral and technical interview to 30
   balanced cases each.
2. Rerun product knowledge, sales objection and project review under Planner v6.
3. Strengthen course-oral transfer and misconception questions at difficulties
   3 and 4.
4. Replace full-blueprint repair with local question repair to reduce latency and
   token cost.
5. Continue the separate open-answer assessment calibration described in
   `V0_8_BROWSER_REAL_PROVIDER_ACCEPTANCE.md`.
6. Run Docker Compose and Vultr migration, backup, restart and rollback gates.

