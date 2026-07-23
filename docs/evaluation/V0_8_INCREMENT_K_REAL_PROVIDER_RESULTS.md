# v0.8 Increment K Real Provider Contract Probe

## Scope

Increment K verifies that configured providers can generate blueprints under three
different compiled scenario contracts:

- `academic.thesis_defense@1.2.0`;
- `education.course_oral@1.0.0`;
- `engineering.technical_interview@1.0.0`.

The shared source was `examples/sample_research.md`, language `zh-CN`. No Mock
provider result is included.

## Qwen result

Profile: `qwen:qwen-plus`

```text
Template runs          3 passed / 3
Questions              6 per template
Coverage               met for all templates
Contract violations    0
Input tokens           4,121
Output tokens          7,962
Recorded latency       38.95 to 42.67 seconds per call
```

## Independent provider result

Profile: `openai:gpt-5.4-mini`

```text
Template runs          3 passed / 3
Questions              6 per template
Coverage               met for all templates
Contract violations    0
Input tokens           3,503
Output tokens          7,387
Recorded latency       18.52 to 20.25 seconds per call
```

## Reliability correction

An initial Qwen pilot returned the unregistered course-oral question type
`reasoning`. The strict contract correctly rejected it. The Planner now performs
one bounded full-blueprint repair request containing the immutable scenario
contract and violation reason. It does not coerce fields locally or widen the
allowlist. A second violation still fails the run.

The recorded acceptance run passed without contract violations.

## Combined release evidence

Attaching both probe reports to `ai-examiner-evaluate-templates` produces:

```text
Deterministic gates           passed
Provider contract samples     passed
Qwen sample gate              released
Independent provider gate     released
Scenario relevance            held
Docker Compose rehearsal      held
Vultr upgrade/rollback        held
```

## Limitations

This is a provider-access and compiled-contract probe. It does not establish that
one template is more relevant than the legacy thesis-defense configuration, does
not use blind judges, and does not authorize a v0.8 release candidate.

Generated JSON reports remain runtime artifacts under `data/` and are not committed
because they contain model output and usage records.
