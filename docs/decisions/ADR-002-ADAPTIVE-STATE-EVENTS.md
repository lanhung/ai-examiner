# ADR-002: Append-only evidence for adaptive knowledge state

Status: Accepted for v0.5  
Date: 2026-07-16

## Context

The v0.4 `ExamSession.mastery_state` JSON stores only the latest per-question summary. It cannot explain how a concept estimate changed, reliably rebuild state after an algorithm update, or support an auditable adaptive selector.

## Decision

v0.5 will use append-only `KnowledgeEvidenceEvent` rows as the source of truth. `KnowledgeState` is a rebuildable aggregate. The existing `mastery_state` field remains as a compatibility snapshot during the transition.

Critical policy decisions remain deterministic and versioned. LLM analysis may contribute observations, but it cannot directly overwrite aggregate state or select a question without hard-constraint validation.

## Consequences

### Positive

- every mastery or misconception conclusion has traceable evidence;
- state can be recomputed when an updater is fixed;
- fixed and adaptive policies can be compared and replayed;
- report conclusions can cite exact answer turns;
- future PostgreSQL migration and multi-user audit become easier.

### Costs

- more database rows and migration work;
- event idempotency and correction semantics must be tested;
- deletion must cover both events and aggregates;
- compatibility code is required until legacy `mastery_state` is removed in a later major migration.

## Rejected alternatives

### Keep extending one JSON field

Rejected because history, concurrency, replay and evidence integrity remain weak.

### Let one LLM maintain the whole cognitive profile

Rejected because results are not deterministic, replayable or sufficiently constrained for evaluation.

### Introduce a graph database in v0.5

Rejected as unnecessary infrastructure. Relational tables plus explicit prerequisites are sufficient for the current scale.
