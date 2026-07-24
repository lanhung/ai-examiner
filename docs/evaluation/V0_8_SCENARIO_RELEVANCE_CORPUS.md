# v0.8 Frozen Scenario Relevance Corpus

## Purpose

This corpus measures whether a scenario template produces examiner behavior that
is more relevant than the legacy thesis-defense configuration. It is separate
from structural contract probes: a provider can obey a contract and still ask
low-value questions.

The source-controlled specification expands deterministically to:

```text
7 templates
x 30 cases per template
= 210 frozen cases
```

Each template is balanced across:

```text
2 languages: zh-CN, en
3 difficulty levels: 2, 3, 4
5 answer classes: excellent, partial, misconception, evasive, unsupported_claim
```

Each case binds one registered objective and one or more allowed question types.
The expanded corpus has a SHA-256 fingerprint. Judge evidence for another
fingerprint is rejected.

## Files

```text
src/ai_examiner/templates/evaluation/v0_8_scenario_relevance.v1.json
src/ai_examiner/template_engine/relevance.py
src/ai_examiner/template_relevance_cli.py
tests/test_template_relevance_v08.py
```

## Export and validate

```bash
uv run ai-examiner-evaluate-template-relevance \
  --export-corpus ./data/v08-frozen-relevance-corpus.json \
  --output ./data/v08-relevance-evidence.json
```

This command is deterministic and makes no paid model call. With no judge
reports, corpus validation passes but relevance evidence remains `held`.

## Blind judge report contract

Every accepted report uses:

```json
{
  "report_version": "template-relevance-judge-v1",
  "corpus_fingerprint": "<sha256>",
  "generator_profile": "qwen:qwen-plus",
  "judge_profile": "openai:gpt-5.4-mini",
  "blind_judging": true,
  "evaluations": [
    {
      "case_id": "education.course_oral:en:d3:partial",
      "baseline": {
        "relevance": 3,
        "clarity": 4,
        "discrimination": 3,
        "followup_usefulness": 3,
        "rubric_fit": 3,
        "report_actionability": 3
      },
      "scenario": {
        "relevance": 5,
        "clarity": 4,
        "discrimination": 4,
        "followup_usefulness": 5,
        "rubric_fit": 5,
        "report_actionability": 4
      },
      "grounded": true,
      "single_main_question": true,
      "unsafe_or_prohibited": false
    }
  ]
}
```

Scores are integers or finite numbers from 1 through 5. The report is accepted
only when:

- generator and judge are configured, non-Mock providers;
- judge and generator providers differ;
- at least two judge providers cover each passing template;
- generator and judge directions are reciprocal for each passing template;
- blind judging is explicitly attested;
- artifacts were generated through `generation_path=session_planner`;
- the corpus fingerprint matches;
- every case and score field is valid.

The aggregator never treats the provider that produced an artifact as its sole
judge.

`relevance` means fit to the target scenario's objective, question taxonomy,
assistance boundary, assessment emphasis and report action. Material-level topical
overlap alone is not enough for a high score.

## Aggregate evidence

Generate release-path evidence with the actual product Planner:

```bash
uv run ai-examiner-probe-template-relevance \
  --generator-profile qwen:qwen-plus \
  --judge-profile openai:gpt-5.4-mini \
  --templates enterprise.sales_objection \
  --cases-per-template 30 \
  --generation-path session_planner \
  --output ./data/sales-qwen-openai.json
```

Run the reciprocal direction with generator and judge profiles exchanged.

For inexpensive prompt calibration only:

```bash
uv run ai-examiner-probe-template-relevance \
  --generation-path batched_contract_probe \
  --cases-per-template 5
```

The batched mode does not exercise `SessionPlanner` and is rejected as release
evidence.

```bash
uv run ai-examiner-evaluate-template-relevance \
  --judge-report ./data/qwen-generated-openai-judged.json \
  --judge-report ./data/openai-generated-qwen-judged.json \
  --output ./data/v08-relevance-evidence.json \
  --require-pass
```

Attach the same evidence to the combined template report:

```bash
uv run ai-examiner-evaluate-templates \
  --provider-probe ./data/v08_qwen_template_probe.json \
  --provider-probe ./data/v08_openai_template_probe.json \
  --relevance-report ./data/qwen-generated-openai-judged.json \
  --relevance-report ./data/openai-generated-qwen-judged.json \
  --output ./data/v08-template-evaluation.json
```

## Candidate thresholds

A template passes only when all 30 frozen case IDs are represented and:

```text
mean relevance improvement >= 0.5
high-quality question rate >= 80%
grounded question rate >= 95%
single-main-question compliance >= 98%
unsafe or prohibited recommendation rate = 0
```

The report includes a 95% confidence interval for relevance improvement. At
least three complete templates must pass before the v0.8 relevance gate clears.
Each passing template also requires reciprocal cross-provider judging, so one
provider cannot become the sole arbiter.

## Current status

The frozen corpus, expansion, fingerprint, balancing and evidence validator are
implemented and tested. Complete reciprocal runtime evidence now passes for product
knowledge, sales objection and project review, with 30 unique cases and two judge
providers per template. Therefore:

```text
scenario_relevance_blind_judging = passed
```

See `V0_8_INCREMENT_N_RELEASE_QUALITY_RESULTS.md` for the final metrics. Docker
Compose and Vultr promotion rehearsals remain separate held gates.

This distinction is deliberate: deterministic corpus validity is not evidence
that a scenario is better.
