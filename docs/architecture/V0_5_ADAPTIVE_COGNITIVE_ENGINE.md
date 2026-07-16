# v0.5 Adaptive Cognitive Engine

Status: Implemented in v0.5.0 RC1
Target release: v0.5.0
Stable base: v0.4.1

## 1. Objective

v0.5 changes the examination loop from a fixed question sequence into an evidence-backed adaptive process:

```text
Answer
  -> analyze answer evidence
  -> update concept state
  -> decide whether to follow up, hint, challenge or move on
  -> score remaining questions
  -> select the next best question and difficulty
  -> preserve the complete decision trail
```

The release is successful only if adaptive behavior is measurably better than the existing fixed order on a frozen evaluation set. A more complicated prompt is not sufficient.

## 2. Current baseline and gap

The v0.4.1 code already has:

- blueprint questions with type, difficulty, expected points, follow-ups and evidence;
- Answer Analyzer output with coverage, correctness, errors and missing points;
- deterministic Evaluator and Policy Controller;
- `ExamSession.mastery_state` JSON;
- transcript turns, evidence assets and Golden Dataset infrastructure.

The current gap is structural:

- `mastery_state` is keyed by question, not concept;
- it stores only the latest score, confidence and missing points;
- state updates are not append-only and cannot be audited independently;
- `current_question_index += 1` always selects the next question;
- difficulty is metadata rather than a controlled variable;
- fixed and adaptive strategies cannot be compared experimentally;
- reports cannot explain growth, uncertainty or misconception persistence.

## 3. Scope

### Included

- explicit knowledge units linked to blueprint questions;
- session and pseudonymous learner knowledge states;
- append-only evidence events;
- deterministic state aggregation;
- adaptive next-question selection;
- difficulty targeting;
- fixed/adaptive strategy switch;
- auditable decision records;
- knowledge and weakness maps in reports;
- evaluation harness comparing adaptive with fixed order;
- schema migrations and rollback documentation.

### Deferred

- full login, organizations and permissions;
- high-stakes automated decisions;
- reinforcement learning or a trained policy model;
- free-form knowledge graph database;
- emotion/personality inference;
- active voice interruption policy, which remains a v0.6 concern;
- full long-term personal memory and communication preferences, which remain v0.7.

## 4. Design principles

1. Evidence first: every state update must reference a turn, question and evaluation.
2. Rules own critical control: LLM output supplies observations, but deterministic code controls state transitions and hard constraints.
3. Uncertainty is explicit: mastery and confidence are separate.
4. No fake precision: scores are bounded estimates, not claims about an immutable human trait.
5. Fixed mode remains available for compatibility and as an experiment control.
6. The selector must explain why a question was selected and which alternatives were rejected.
7. Session-level cognition ships before a full identity system.
8. Text and voice share the same cognitive engine after transcript normalization.

## 5. Domain model

### 5.1 KnowledgeUnit

A concept or capability that can be tested by one or more questions.

```json
{
  "id": "ku_method_assumptions",
  "blueprint_id": "...",
  "name": "Method assumptions",
  "description": "Conditions required for the method to be valid",
  "importance": 0.9,
  "default_difficulty": 3,
  "prerequisite_ids": [],
  "misconception_catalog": [
    "treats correlation as causal identification"
  ],
  "source_evidence_asset_ids": ["..."]
}
```

Generation is part of blueprint preparation. Each question must reference at least one knowledge unit. A question may cover multiple units, but one unit is marked primary.

### 5.2 LearnerSubject

v0.5 has no authentication system. Cross-session state therefore uses an optional pseudonymous subject key rather than pretending that a secure user account exists.

```json
{
  "id": "...",
  "project_id": "...",
  "subject_key": "local-evaluation-001",
  "display_name": null,
  "metadata": {}
}
```

`subject_key` is optional. A session without it still receives session-level adaptive behavior.

### 5.3 KnowledgeState

Current aggregate for one subject/session and one knowledge unit.

```json
{
  "knowledge_unit_id": "ku_method_assumptions",
  "mastery": 0.58,
  "confidence": 0.71,
  "evidence_count": 3,
  "correct_evidence_count": 1,
  "misconceptions": [
    {
      "code": "correlation_as_causation",
      "status": "active",
      "evidence_event_ids": ["..."]
    }
  ],
  "last_tested_at": "2026-07-16T12:00:00Z"
}
```

### 5.4 KnowledgeEvidenceEvent

Append-only observation from a user answer. This is the source of truth for recomputing state.

Required fields:

- session, turn, question and knowledge unit IDs;
- normalized correctness, coverage and evidence quality;
- analyzer confidence;
- detected and resolved misconceptions;
- help level used before the answer;
- source type: text or voice transcript;
- algorithm version and timestamp.

Events must never be silently edited. A correction creates a compensating event.

### 5.5 AdaptiveDecision

An auditable selector result.

```json
{
  "session_id": "...",
  "strategy": "adaptive",
  "action": "MOVE_ON",
  "selected_question_id": "Q7",
  "target_difficulty": 4,
  "reason_codes": ["active_misconception", "high_importance"],
  "candidate_scores": [
    {
      "question_id": "Q7",
      "total": 0.81,
      "knowledge_gap": 0.42,
      "uncertainty": 0.18,
      "importance": 0.18,
      "difficulty_fit": 0.08,
      "novelty": 0.05
    }
  ],
  "policy_version": "adaptive-v1"
}
```

## 6. Proposed database tables

```text
knowledge_units
question_knowledge_units
learner_subjects
knowledge_states
knowledge_evidence_events
adaptive_decisions
```

`ExamSession` additions:

```text
learner_subject_id nullable
question_strategy fixed|adaptive
policy_version
asked_question_ids JSON
```

Keep `mastery_state` during v0.5 for API compatibility. It becomes a read-through compatibility snapshot generated from the new tables and is not the canonical source of truth.

Schema changes require Alembic. `Base.metadata.create_all()` may continue for clean local installs, but production upgrades must run a migration. The migration must be additive and preserve all v0.4 data.

## 7. Knowledge State Updater

### 7.1 Input

- question-to-knowledge-unit weights;
- Analyzer result;
- Evaluator dimensions;
- answer and supporting quote;
- prior hints/follow-ups;
- current knowledge state.

### 7.2 Evidence value

For each linked knowledge unit, normalize a signal:

```text
answer_quality =
  0.45 * correctness
  + 0.35 * coverage
  + 0.20 * evidence_reasoning

assistance_penalty =
  0.00 direct answer
  0.10 after follow-up
  0.20 after hint
  0.30 after correction

observation = clamp(answer_quality - assistance_penalty, 0, 1)
```

Primary knowledge units receive weight `1.0`; secondary units use their configured relationship weight.

### 7.3 Aggregate update

Initial implementation uses a deterministic recency-weighted update:

```text
effective_weight = relation_weight * analyzer_confidence
new_mastery = weighted_mean(prior evidence, current observation)
confidence = 1 - exp(-evidence_weight_sum / confidence_scale)
```

Recent contradictory evidence must reduce mastery. Confidence may rise while mastery falls; the system becomes more certain that the user has a gap.

Do not let a single excellent answer produce mastery above `0.85`. Require at least two independent evidence events, including one application, analysis, counterexample or transfer question, for `mastery >= 0.85`.

### 7.4 Misconceptions

Analyzer errors are mapped to a controlled misconception code when possible. Free text is preserved separately. A misconception can be:

```text
suspected -> active -> challenged -> resolved
```

Resolution requires later contradictory evidence; it is not removed just because the user receives a correction.

## 8. Adaptive Question Selector

### 8.1 Hard constraints

Reject a candidate when:

- it has already been asked and is not an explicit revisit;
- its prerequisite is clearly untested and the question cannot diagnose the prerequisite;
- the remaining time is below the estimated answer time;
- its source evidence is unavailable;
- the session question limit has been reached;
- the same knowledge unit has exceeded its configured probe limit;
- the question violates the current mode's assistance policy.

### 8.2 Candidate score

Initial policy is deterministic and versioned:

```text
total =
  0.30 * knowledge_gap
  + 0.20 * uncertainty
  + 0.20 * importance
  + 0.15 * misconception_priority
  + 0.10 * difficulty_fit
  + 0.05 * novelty
```

Definitions:

- `knowledge_gap = 1 - mastery`;
- `uncertainty = 1 - confidence`;
- `importance` comes from the blueprint knowledge unit;
- `misconception_priority` is high for active misconceptions;
- `difficulty_fit` rewards questions close to target difficulty;
- `novelty` penalizes semantic and concept repetition.

Weights belong to a policy configuration, not hard-coded scattered constants. Record them with every decision.

### 8.3 Decision order

```text
Policy Controller chooses follow-up/hint/challenge/move/end
  -> if MOVE_ON and strategy=adaptive
       Adaptive Question Selector selects next question
     else if MOVE_ON and strategy=fixed
       current_question_index + 1
```

The selector must not generate user-facing wording. Interviewer owns presentation.

## 9. Difficulty Controller

Difficulty levels:

| Level | Cognitive demand | Typical form |
|---|---|---|
| 1 | Recall | Define or identify |
| 2 | Understanding | Explain in own words |
| 3 | Application | Apply to a concrete case |
| 4 | Analysis | Compare, justify, find limitations |
| 5 | Expert challenge | Counterexample, transfer, alternative design |

Initial target:

```text
mastery < 0.30 -> level 1-2
0.30-0.55      -> level 2-3
0.55-0.75      -> level 3-4
> 0.75         -> level 4-5
```

Active misconceptions may temporarily lower difficulty to isolate the faulty premise. Strong answers should increase difficulty by at most one level per independent evidence event. Two poor answers or an explicit request can reduce it.

## 10. API evolution

### Session creation

Add optional fields:

```json
{
  "question_strategy": "adaptive",
  "learner_subject_key": "local-evaluation-001",
  "policy_version": "adaptive-v1"
}
```

Default for existing clients remains `fixed` until adaptive acceptance gates pass. The UI may default new evaluation sessions to adaptive only after RC validation.

### Read APIs

```text
GET /api/sessions/{session_id}/knowledge-state
GET /api/sessions/{session_id}/adaptive-decisions
GET /api/subjects/{subject_id}/knowledge-state
GET /api/subjects/{subject_id}/learning-history
```

Responses must include evidence references and algorithm/policy versions.

### Administrative/debug API

```text
POST /api/sessions/{session_id}/knowledge-state/rebuild
```

This recomputes aggregate state from append-only events and is disabled or protected in future multi-user deployments.

## 11. Text and voice integration

The cognitive engine consumes normalized completed answers. Text answers already enter `ExamOrchestrator.submit_answer`. Voice answers must be finalized from transcript events before analysis.

v0.5 must not let the Realtime model independently mutate knowledge state. The durable Analyzer/Evaluator pipeline remains authoritative.

```text
Voice transcript finalization
  -> normalized answer turn
  -> Analyzer
  -> Evaluator
  -> Knowledge Evidence Event
  -> State Updater
  -> Policy and Selector
```

## 12. Reporting

Add three evidence-backed sections:

### Knowledge Map

- concept mastery and confidence;
- evidence count;
- last tested time;
- source questions and answer quotes.

### Weakness Map

- active misconceptions;
- missing reasoning steps;
- high-importance low-mastery concepts;
- confidence/mastery mismatch.

### Improvement Path

- ordered concepts to revisit;
- recommended question difficulty and type;
- suggested retest conditions;
- explicit evidence for each recommendation.

Do not turn these estimates into permanent labels such as intelligence, personality or employability.

## 13. Implementation sequence

### Milestone A: migrations and contracts

- introduce Alembic;
- add tables and Pydantic schemas;
- enrich blueprint question-to-concept mapping;
- preserve fixed mode and existing APIs.

### Milestone B: evidence and state

- implement event creation;
- implement deterministic state rebuild;
- add unit and property-style boundary tests;
- expose read APIs.

### Milestone C: adaptive policy

- implement difficulty target;
- implement candidate filtering/scoring;
- integrate with orchestrator behind `question_strategy`;
- persist decision records.

### Milestone D: experience and reports

- add fixed/adaptive controls;
- show why the next question was chosen in debug/evaluation view;
- add knowledge/weakness/improvement report sections;
- integrate finalized voice transcripts.

### Milestone E: evaluation and release

- freeze policy config and Golden Dataset version;
- compare fixed versus adaptive;
- run migration, rollback and deployment rehearsal;
- publish RC, collect real sessions, then publish final.

## 14. Compatibility and rollback

- Existing sessions remain `fixed` and readable.
- Existing `mastery_state` remains in API responses.
- New tables are additive in the first migration.
- If adaptive behavior fails, set `question_strategy=fixed`; no data deletion is required.
- Downgrade documentation must state which new tables remain unused after code rollback.
- Production backup is mandatory before migration.

## 15. Security and ethics

- Treat document, answer and model output as untrusted data.
- Never store API keys in state or decision records.
- Subject keys should be pseudonymous during v0.5 evaluation.
- Do not infer protected traits, personality, honesty or mental state.
- Reports are training aids, not sole evidence for academic, hiring or medical decisions.
- Preserve deletion capability for subject-linked events and aggregate states.

## 16. Definition of done

v0.5 is done only when:

- all state updates are traceable to evidence events;
- fixed mode passes the full v0.4 regression suite;
- adaptive mode never repeats a mastered question without an explicit revisit reason;
- wrong or incomplete answers prioritize a relevant follow-up or concept-linked question when one exists;
- difficulty changes are bounded and recorded;
- adaptive decisions can be replayed from stored inputs and policy version;
- Golden Dataset evaluation meets the thresholds in the v0.5 evaluation plan;
- migration and rollback rehearsals pass on a copy of the v0.4 database;
- text and finalized voice answers use the same authoritative state updater;
- documentation, changelog, version files and Docker deployment instructions are current.
