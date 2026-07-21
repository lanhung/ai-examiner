# ADR-004: Evidence-bound and revocable long-term learner memory

Status: Proposed for v0.7 research  
Date: 2026-07-21

## Context

v0.5 introduced project-scoped pseudonymous learners, append-only
`KnowledgeEvidenceEvent` rows and rebuildable `KnowledgeState` aggregates. v0.6
kept that cognitive pipeline authoritative while improving conversation timing and
assessment stability.

The current implementation can reuse evidence across sessions in one project, but
it cannot safely answer several long-term questions:

- is the learner likely to retain a concept after time has passed;
- when should that concept be tested again;
- are two knowledge units from different projects the same concept;
- which interaction preferences were explicitly chosen or repeatedly confirmed;
- what memory is enabled, reviewable, exportable or deletable;
- how can a changed algorithm rebuild every long-term conclusion.

A single mutable `user_profile` JSON would make these problems difficult to audit.
Allowing an LLM to summarize every conversation into permanent memory would also
turn uncertain inferences into durable labels and retain more user content than the
product needs.

## Decision

v0.7 will use evidence-bound, category-limited and revocable long-term memory.

1. Existing append-only assessment evidence remains the source of truth for
   observed performance.
2. Cross-project learner identity is an opaque mapping, separate from login,
   organization and authorization work reserved for later enterprise versions.
3. Cross-project state uses canonical concepts with versioned, confidence-bearing
   mappings from project knowledge units.
4. Observed mastery and predicted retention are separate values. A prediction can
   never replace the last observed result.
5. Retention and retest calculations are deterministic, versioned and rebuildable.
   v0.7 begins with conservative defaults and shadow evaluation; it does not claim
   psychometric validity without longitudinal calibration.
6. Preferences are stored only when explicitly selected, explicitly confirmed, or
   repeatedly observed under a documented threshold. Inferred preferences expire
   and remain editable.
7. An LLM may propose a schema-bound memory candidate. A deterministic policy gate
   validates category, evidence, consent, confidence and retention before any
   durable record is created.
8. Raw audio, unrestricted conversation summaries, personality labels, emotion
   diagnoses and protected-trait inferences are not long-term memory categories.
9. The user can inspect, correct, export, disable and delete long-term memory.
   Correction is represented by superseding events; deletion performs a hard-delete
   workflow across source events, derived state and exports where required.
10. Derived aggregates are caches. Replaying non-deleted source evidence with the
    same algorithm version must reproduce them.

## Memory categories

Allowed v0.7 categories:

```text
concept_evidence       assessed performance tied to a canonical concept
misconception          evidence-bound misconception lifecycle
retest_outcome         result of a scheduled reassessment
explicit_preference    user-selected interaction or explanation preference
confirmed_preference   user-confirmed system proposal
concept_mapping        reviewed relation between a project unit and concept
memory_control         consent, disable, correction and deletion event
```

Disallowed categories:

```text
unrestricted_chat_summary
raw_audio_memory
personality_or_emotion_label
voice_or_accent_ability_inference
protected_trait_inference
unsupported_stable_strength_or_weakness_label
secret_or_credential
```

## Consequences

### Positive

- long-term recommendations remain traceable to exact sessions and answers;
- retention predictions can be evaluated independently from observed mastery;
- cross-project memory does not depend on fragile generated knowledge-unit codes;
- users retain meaningful control over persistent memory;
- algorithm updates can be replayed and compared;
- later PostgreSQL, authentication and organization work has a clearer boundary.

### Costs

- additional identity, concept, policy, event and aggregate tables;
- concept mapping requires abstention and review, not blind embedding similarity;
- deletion is more complex because both source evidence and derived caches exist;
- useful retention personalization requires repeated observations over time;
- early retest recommendations must run in shadow mode until calibrated.

## Rejected alternatives

### One mutable user-profile JSON

Rejected because provenance, correction, deletion, concurrency and replay are weak.

### Save an LLM summary after every session

Rejected because it retains excessive content, is difficult to correct and can
convert one model error into a permanent learner label.

### Reuse `KnowledgeUnit.code` as a global concept identifier

Rejected because current codes are blueprint-local and may be generated from broad
question types rather than stable domain concepts.

### Adopt FSRS or half-life regression as a production truth immediately

Rejected for v0.7 research. These approaches inform the experiment design, but the
project does not yet have enough repeated learner-concept outcomes to fit or validate
a personalized model. The first implementation must support baseline comparison and
later replacement without changing source evidence.

### Implement full accounts and multi-tenant authorization in v0.7

Rejected as scope expansion. v0.7 defines an opaque learner identity and memory
control boundary; full users, organizations, roles and SSO remain enterprise work.

## References

- Settles and Meeder, "A Trainable Spaced Repetition Model for Language Learning":
  https://aclanthology.org/P16-1174/
- Open Spaced Repetition, FSRS implementation and research resources:
  https://github.com/open-spaced-repetition/fsrs4anki
- NIST Privacy Framework 1.1 resources:
  https://www.nist.gov/privacy-framework/using-privacy-framework-11
