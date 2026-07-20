# v0.6 Assessment Stabilization API

## Report v2

`GET /api/sessions/{id}/report` adds question-level trajectories while retaining
the existing evidence and knowledge-map fields:

```json
{
  "report_version": "assessment-report-v2",
  "score_policy": "independent-main-answer-v1",
  "questions_answered": 6,
  "evaluated_turns": 10,
  "assessment_summary": {
    "independent_average": 3.53,
    "assisted_average": 4.97,
    "average_learning_gain": 1.43
  },
  "question_trajectories": [
    {
      "question_id": "Q2",
      "independent_score": 0.6,
      "final_assisted_score": 5.0,
      "followup_count": 1,
      "learning_gain": 4.4,
      "remaining_gaps": []
    }
  ]
}
```

Defense mode uses independent main-question scores for the overall score. Teaching
mode uses the documented `70% independent + 30% assisted` policy. Follow-up turns
remain visible as evidence but do not become additional main-question score units.

## Metrics

`GET /api/metrics` adds persisted normal-provider telemetry:

```json
{
  "latency_ms": {"samples": 11, "p50": 13475, "p95": 50372},
  "retries": 0,
  "json_repairs": 0
}
```

## Cost dashboard

Each `by_model` entry from `GET /api/costs` now includes `latency_ms`, `retries`
and `json_repairs` in addition to calls, tokens and estimated cost. Request payloads
and API keys are not stored in telemetry.

## Assessment contract

Provider labels are normalized at the Analyzer boundary into:

```text
supported
partially_supported
unsupported
insufficient
```

Known aliases remain auditable as `raw_correctness`. Unknown labels receive one
bounded correction attempt and then fail closed. Coverage is calculated by the
application from point-level `covered`, `partial`, `missing` and `contradicted`
decisions instead of accepting an unconstrained scalar from the provider.
