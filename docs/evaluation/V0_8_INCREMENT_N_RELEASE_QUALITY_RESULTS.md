# v0.8 Increment N: Release Quality Results

## Scope

Increment N closes the real-provider scenario-relevance gate for the v0.8
industry template platform. It also hardens long-running evaluation so network
failures do not discard completed paid-model work.

## Engineering changes

- `SessionPlanner` now receives reviewed role and interaction-style behavior
  guidance, not only presentation identifiers.
- Scenario questions must remain recognizable after the visible role name is
  removed.
- Questions with multiple question marks or numbered subquestions trigger bounded
  semantic repair; secondary probes must move to `followups`.
- Contract repair permits up to three correction attempts before failing closed.
- Blind judges score role behavior operationally and evaluate
  `single_main_question` from the `question` field only.
- Relevance probes write an atomic checkpoint after every batch.
- `--resume` validates corpus, provider, generation path, template set, case count,
  and Planner prompt version before skipping completed case IDs.

The checkpoint path was exercised by a real Qwen read timeout. The first 35 cases
remained valid and the command resumed from case 36.

## Method

Release evidence uses:

```text
generation path     production SessionPlanner
corpus              v0.8-scenario-relevance-v1
cases               30 per template
languages           zh-CN and English
difficulty          2, 3, 4
answer classes      excellent, partial, misconception, evasive, unsupported_claim
directions          Qwen generation / OpenAI judge
                    OpenAI generation / Qwen judge
blinding            deterministic anonymous A/B arms
```

Only three templates are required to clear the v0.8 release-quality threshold.
No Mock output, self-judging, batched contract probe, or partial report is accepted.

## Final results

| Template | Relevance delta | 95% CI | High quality | Grounded | Single question | Unsafe |
|---|---:|---:|---:|---:|---:|---:|
| Product knowledge | +1.017 | [0.772, 1.261] | 98.3% | 100% | 100% | 0% |
| Sales objection | +1.500 | [1.186, 1.814] | 98.3% | 100% | 100% | 0% |
| Project review | +1.667 | [1.494, 1.839] | 100% | 100% | 100% | 0% |

All three templates have 30 unique cases, 60 reciprocal judge observations, two
independent judge providers, and complete cross-provider coverage.

```text
scenario_relevance_blind_judging = passed
templates_required              = 3
templates_passed                = 3
```

## Combined release evidence

The combined deterministic/provider/relevance report passes every software and AI
quality gate. Production promotion remains held only by:

```text
docker_compose_rehearsal
vultr_upgrade_and_rollback_rehearsal
```

The local Windows host has no Docker installation. The available SeetaCloud host
runs inside a restricted container where `dockerd` cannot create the required
iptables NAT chain. No active deployment or user data was modified while checking
that limitation.

## Verification

```text
pytest                         137 passed
ruff                           passed
JavaScript syntax              passed
frozen corpus                  210/210 valid
provider contract probes       Qwen 3/3, OpenAI 3/3
scenario relevance             3/3 templates passed
combined release evidence      held only on deployment rehearsal
```

The Windows interpreter may print the known AnyIO/Proactor shutdown access-violation
diagnostic after pytest completes. The test command exits with code 0.
