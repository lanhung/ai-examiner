# Blueprint Generation Performance

## Scope

2026-10-23: optimize Planner generation and repair latency without changing the
application version, model, document contents, scoring rules or tenant permissions.
The model remains `qwen:qwen-plus`. Prompt revision is
`session-planner-v08-scenario-native-v7` and is stored in newly generated blueprints.

This is a server-side change shared by the web and mini-program. It is separate
from the interrupted-job recovery fix described in `BLUEPRINT_TASK_RECOVERY.md`.
An old failed job is not automatically retried or converted into a new result.

## Bottleneck

The prior Planner could regenerate a complete blueprint up to three times when
even one question or follow-up contained multiple requests. Each retry repeated
the source document, all questions, answer points and knowledge units. JSON parse
retry counts do not include these separate business-rule repair calls.

One previously observed live job spent 105.60 seconds queued and 188.17 seconds
executing (293.77 seconds total). Its three Planner calls took 69.257, 59.382 and
59.393 seconds. This is diagnostic historical evidence, not a controlled baseline.

## Changes

- Keep the entire document in initial planning and structural repairs.
- Preserve the initial planning instructions and question budget unchanged.
- Collect all stacked main questions and follow-ups before requesting one patch.
- Send only affected question records plus scenario requirements for wording repair.
  Their original evidence and answer points remain available to the model.
- Accept only server-issued target IDs, replacement text and additional follow-ups.
  The server maps targets to invalid fields; it does not interpret arbitrary model paths.
  Preserve all other fields and already-valid wording exactly. Split secondary probes
  into follow-ups, with a combined bound of four additions per question.
- Validate the complete patch before replacing any data. Reject missing/duplicate
  indices, extra fields, changed valid wording, wrong language and repeated stacking.
- Preserve the three-repair ceiling. Structural errors still require full repair;
  malformed patches cannot silently bypass the original contract checks.
- Keep the existing governed provider path, usage accounting and budget enforcement.

## Local Verification

89 regression tests passed across Planner wording repair, provider contract probes,
template planning/relevance, assessment contracts, asynchronous blueprints,
lease recovery and Golden Benchmark. These are deterministic unit/integration tests,
not evidence of real-model quality or speed. Existing dependency deprecation
warnings remain; they are unrelated to the Planner change.

The new tests cover all seven built-in template contracts, protected evidence and
scoring fields, batch repair, atomic rejection and bounded retries.

```powershell
.venv\Scripts\python.exe -m pytest tests/test_planner_wording_repair.py tests/test_template_provider_probe_v08.py tests/test_template_planning_v08.py tests/test_blueprint_model_output.py tests/test_assessment_contract.py tests/test_template_relevance_v08.py tests/test_blueprint_async.py tests/test_job_hardening_v09.py tests/test_golden_benchmark.py -o addopts='' -q
```

## Real-Model Method

Use the same three-page synthetic thesis on adaptive questioning (see
`tests/fixtures/planner_speed_paper_zh.txt`), the academic
thesis-defense template, Chinese output, six questions, identical provider settings
and existing prompt overrides. The exploratory sequence was baseline, first candidate,
first candidate, baseline; two compact-prompt candidates followed, then two final
candidates with the original initial prompt restored. Final samples were not randomized.
Use the existing non-superuser PostgreSQL application role and
tenant context. Model governance must allow Qwen Plus; refuse fallback models.

Bound the probe to four runs, sixteen Planner calls and 65,000 cumulative reported
tokens before starting another call, in addition to normal quota enforcement.
Do not access student papers or write grades. Synthetic outputs are inspected for
grounding, correct source pages, coverage, single-issue questions and answer points.

## Results

Real Qwen Plus, not mock. All four rows below reached a completed blueprint:

| Variant | Planner seconds | Calls | Input tokens | Output tokens |
| --- | ---: | ---: | ---: | ---: |
| Baseline 1 | 172.263 | 3 | 11,672 | 7,721 |
| Baseline 2 | 130.592 | 2 | 7,415 | 5,882 |
| Final candidate 1 | 79.434 | 2 | 4,697 | 3,565 |
| Final candidate 2 | 87.837 | 4 | 10,004 | 3,889 |

Observed mean: 151.43 to 83.64 seconds (44.8% lower). This is descriptive evidence
from two runs per version, not a statistically established latency guarantee.
The final candidate's wording calls took 2.754 seconds in run 1, and 7.163, 8.229,
8.194 seconds in run 2. Run 2 needed three attempts because the first two patches
still contained stacked requests. The system rejected them instead of weakening validation.

Both final runs retained six questions, met configured objective coverage and passed
the existing single-request detector. Comparing initial generation to the repaired
result found zero changes in ID, type, difficulty, objective IDs, expected points,
source excerpt/page or knowledge units across both runs.

### Quality Findings and Unshipped Experiments

- The first question-level patch protocol failed in two exploratory runs (138.428
  and 93.599 seconds). It was not deployed. The final protocol patches only named
  invalid fields, with no need to reproduce already-valid prose.
- Concise-initial-output experiments completed in 68.476 and 113.222 seconds, but
  one missed objective coverage and the other had an answer-point count below the
  probe's three-point criterion. The compact initial prompt was withdrawn.
- Final run 1 failed exact source quotation and page-matching checks: three initial
  excerpts joined noncontiguous material with ellipses, including a cross-page excerpt.
  The initial result already had these excerpts; wording repair preserved them
  unchanged. Final run 2 passed both checks. Do not label all quality checks passed.
- Manual inspection also found overly assertive expected points and some repetitive
  follow-ups. These require separate grounding/rubric and semantic-quality evaluation;
  the current regex detector is not an expert judgment of question quality.
- Historical v6 full-template evaluation is not reused to certify v7 quality.

The shipped optimization is deliberately limited to wording repairs. It does not
relax or bypass the existing grounding/assessment path. Exact quote validation and
semantic deduplication remain quality follow-ups, not completed work in this patch.

## Deployment

- Deployed only `src/ai_examiner/agents/planner.py` to the existing AutoDL staging
  service after baseline hash validation, a backup and an idle-job check.
- Gracefully restarted API and Celery with their original arguments/environment.
  Rechecked for active jobs after stopping API intake; no in-flight generation was killed.
- `/health` and `/ready` returned HTTP 200; deployed source matches the local file hash.
- Configuration, model keys, budget policies, source documents and grades were not changed.
  No old failed job was automatically retried. Application version remains unchanged.
- This backend optimization requires no mini-program package update. It applies to
  new generation requests; it does not retroactively replace existing blueprints.
- No physical-phone end-to-end latency measurement was performed in this change.

## Limits

- This small paired probe is not a p95 benchmark or an expert grading study.
- It measures Planner wall time, not upload, queueing, polling or phone rendering.
- Do not compare this synthetic probe directly to the historical live job as an A/B test.
- Initial generation and structural repairs still require model latency.
- No Analyzer adjudication is disabled. Answer submission speed is not measured here.
- Seven-template v6 real-provider evidence remains historical. Full v7 scenario
  acceptance requires rerunning the frozen evaluation set; passing contract tests
  does not replace that evaluation.
- Large papers, upstream load and network latency can change the observed benefit.
