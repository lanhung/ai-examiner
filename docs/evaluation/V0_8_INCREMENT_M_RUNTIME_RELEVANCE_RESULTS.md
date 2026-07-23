# v0.8 Increment M: Runtime Scenario Relevance

## Purpose

Increment M connects the frozen relevance corpus to the actual product
`SessionPlanner` path and corrects a scenario-context omission discovered by real
Qwen/OpenAI testing.

## Method correction

The first probe generated both arms in one batched model request. This was useful
for cheap calibration but created cross-arm context contamination and did not
exercise the production Planner. It is no longer accepted as release evidence.

The release path now:

1. runs the baseline arm through `SessionPlanner`;
2. runs the scenario arm independently through `SessionPlanner`;
3. projects the frozen case objective and allowed taxonomy into the scenario arm;
4. randomizes A/B labels using the corpus fingerprint and case ID;
5. asks a different provider to score the anonymous arms;
6. unblinds only after the judge returns;
7. requires a reciprocal provider direction before a template can pass.

Reports must declare:

```json
{"generation_path": "session_planner"}
```

`batched_contract_probe` remains available for calibration but cannot clear a
release gate.

## Runtime defect found

The compiled template already contained:

- scenario identity and intended use;
- examiner role and interaction style;
- assistance and correction boundaries;
- assessment dimensions and weights;
- report sections and scoring presentation.

`SessionPlanner` previously received only objectives, allowed question types,
coverage, difficulty and question limit. Different scenarios therefore reached the
Planner as variations of one generic oral-examiner prompt.

Increment M now sends the full non-secret planning context and explicitly requires
scenario changes to alter behavior rather than just visible role text.

## Real provider evidence

Profiles:

```text
generator    qwen:qwen-plus
blind judge  openai:gpt-5.4-mini
```

### Before the Planner correction

Two real runtime sales-objection cases:

```text
mean relevance improvement      0.0
high-quality rate               100%
grounded rate                   100%
single-main-question rate       100%
unsafe rate                     0%
```

### After the Planner correction

The same two-case slice:

```text
mean relevance improvement      +1.5
95% confidence interval         [-1.44, 4.44]
high-quality rate               100%
grounded rate                   100%
single-main-question rate       100%
unsafe rate                     0%
provider calls                  5
input tokens                    8,921
output tokens                   3,220
```

The direction is encouraging, but the sample is intentionally too small to pass.
The confidence interval is wide and reciprocal judging is absent.

## Calibration finding

A prior 5-case low-difficulty sales sample suggested a `+2.4` relevance
improvement. Expanding the non-runtime calibration path to all 30 cases and
reciprocal judges reduced the mean to `+0.033`, with CI `[-0.090, 0.156]`.

This is evidence that the 30-case language/difficulty/answer-quality balance is
necessary. Tiny favorable slices must not authorize a release.

## Current gate

Held until:

- at least 30 runtime Planner cases are complete for a template;
- both Qwen-generated/OpenAI-judged and OpenAI-generated/Qwen-judged directions
  are present;
- all relevance, quality, grounding, single-question and safety thresholds pass;
- at least three templates pass this complete process.

Runtime reports are generated under `data/`, ignored by Git, and contain no API
keys or system prompts.
