# v0.7 Long-term Learner Intelligence Evaluation Plan

## 1. Purpose

This plan determines whether long-term memory improves future questioning without
leaking data, overstating certainty or creating durable unsupported labels.

A working CRUD page is not sufficient. Release evidence must cover replay,
identity isolation, concept mapping, retention calibration, retest usefulness,
preference validity and memory lifecycle operations.

## 2. Research questions

1. Can the same source events deterministically rebuild the same learner-concept
   state?
2. Can project knowledge units be mapped across documents without harmful concept
   merges?
3. Does a time-aware baseline predict later independent recall better than carrying
   the last score forward?
4. Does the retest planner choose more useful concepts than simple baselines?
5. Are stored preferences correct, current and explicitly controllable?
6. Can all memory be inspected, exported, corrected and deleted without affecting
   unrelated users or project records?

## 3. Evaluation layers

### 3.1 Deterministic domain tests

Assert:

- event import idempotency;
- exact replay equality for the same algorithm version;
- stable ordering under equal timestamps;
- correction and supersession behavior;
- no derived aggregate as an independent source of truth;
- observed and predicted values never overwrite one another;
- migration upgrade and downgrade preserve v0.6 data.

### 3.2 Identity isolation tests

Create at least three identities with overlapping concept names and assert:

- no state, preference, export or plan crosses identities;
- revoked links stop cross-project aggregation;
- an unlinked subject remains project-local;
- raw external references are not logged or returned;
- deletion of one identity changes no aggregate for another.

Required release result: zero cross-identity leakage in automated and adversarial
tests.

### 3.3 Concept mapping evaluation

Build a labeled set containing:

- exact equivalents with different wording;
- narrower and broader relations;
- related but non-equivalent concepts;
- same label with different domain meanings;
- insufficient-evidence cases;
- multilingual Chinese/English aliases.

Report:

```text
exact mapping precision / recall / F1
harmful merge rate
abstention precision
relation confusion matrix
performance by domain and language
```

Initial gate:

- accepted exact/narrower mapping precision >= 95%;
- harmful merge rate < 1% in the frozen set;
- all low-margin ambiguous cases abstain or require review;
- model proposals never activate themselves.

### 3.4 Retention evaluation

Compare versioned baselines:

```text
last_observation / no_decay
fixed_half_life
evidence_half_life
optional research implementation of HLR or FSRS-compatible prediction
```

Use only later independent attempts as outcomes. Hinted, corrected or same-turn
follow-up answers are not recall ground truth.

Metrics:

```text
Brier score
log loss with clipping
calibration error and reliability plot
absolute error by elapsed-time bucket
coverage of prediction confidence intervals
performance by evidence-count bucket
```

The first release may ship a conservative fixed baseline if personalized models do
not outperform it with confidence. No model name or literature result substitutes
for project-specific validation.

### 3.5 Retest planner evaluation

Offline ranking comparison:

```text
random
oldest_observation_first
lowest_mastery_first
lowest_predicted_retention_first
v0.7 policy
```

Measure:

- unresolved misconception recall at top K;
- later failure rate among selected concepts;
- prerequisite-order violations;
- exact question repetition;
- explanation/reason correctness;
- plan diversity and workload;
- accepted versus dismissed recommendations.

In a pilot, compare learning gain and delayed recall after retest. The planner starts
in shadow mode and cannot modify the live session until offline and pilot gates pass.

### 3.6 Preference evaluation

Fixtures include explicit choices, repeated behavior, contradiction, one-off
behavior and stale preferences.

Metrics:

```text
proposal precision
confirmation rate
incorrect active preference rate
expiry correctness
contradiction handling
score independence
```

Gates:

- explicit choice round-trips exactly;
- inferred candidates never become active without the configured confirmation;
- rejected and expired preferences stop influencing future sessions;
- preference values have zero path into assessment score calculation;
- disallowed personality/sensitive categories are rejected 100% in adversarial
  tests.

### 3.7 Memory lifecycle evaluation

For every allowed category:

```text
create -> inspect -> correct -> export -> disable -> delete -> rebuild
```

Assert:

- export coverage is 100% for active in-scope records;
- deleted content is absent from active DB rows, generated exports and rebuilt
  aggregates;
- unrelated project assessment evidence is preserved for scoped deletion;
- identity deletion removes links and all long-term state;
- failed deletion keeps writes blocked and is resumable;
- backup restoration follows the documented retention policy and does not
  silently reactivate deleted memory.

## 4. Datasets

### 4.1 Longitudinal synthetic corpus

Deterministic learner histories with known trajectories:

- stable mastery;
- gradual learning;
- delayed forgetting;
- misconception corrected after hints;
- apparent mastery from assisted answers only;
- contradictory assessments;
- long inactivity;
- cross-project equivalent concepts;
- ambiguous concept mappings.

This corpus drives CI without paid APIs.

### 4.2 Recorded project-session corpus

Sanitized v0.5/v0.6 event histories with project and subject IDs replaced. Raw
documents, API keys and unnecessary transcript content are excluded.

### 4.3 Concept mapping Golden set

At least 300 labeled pairs before active cross-project aggregation:

```text
100 exact/narrower
60 broader
60 related
50 same-name-different-meaning
30 insufficient evidence
```

Include at least two domains and Chinese/English examples.

### 4.4 Preference adversarial set

Attempts to store:

- personality and emotion labels;
- protected attributes;
- secrets and credentials;
- one-off frustration as a permanent preference;
- prompt-injected memory instructions;
- contradicted or expired preferences.

All must be rejected or remain inactive proposals.

### 4.5 Real longitudinal pilot

Minimum research target:

- 10 consenting test identities;
- 3 or more sessions per identity;
- 20 or more concepts with repeated independent attempts;
- at least two elapsed-time buckets;
- explicit memory review and deletion exercise.

This target is for calibration evidence, not a claim of statistical generality.

## 5. Primary release gates

| Gate | Required result |
|---|---|
| Replay reproducibility | 100% exact aggregate equality for same version |
| Event idempotency | Zero duplicate imports |
| Identity isolation | Zero cross-identity leakage |
| Mapping precision | >= 95% for accepted exact/narrower mappings |
| Harmful concept merge | < 1% in frozen mapping set |
| Mapping self-activation | Zero model proposals activated without gate/review |
| Observed/predicted separation | Zero contract violations |
| Retention quality | Beats or does not regress from no-decay baseline; otherwise remain shadow |
| Retest prerequisite violations | Zero in deterministic Golden cases |
| Preference score influence | Zero |
| Unsupported durable labels | Zero |
| Export coverage | 100% of active in-scope memory |
| Deletion coverage | 100% of requested active rows and derived caches |
| v0.5/v0.6 regression | Zero critical failures |

## 6. Shadow and rollout gates

### Gate A: Schema and replay

Additive migration, idempotent import, rebuild equality and deletion coverage pass.

### Gate B: Concept mapping shadow

Model/rule proposals are recorded but do not change cross-project state. Mapping
Golden-set precision and abstention gates pass.

### Gate C: Retention shadow

Predictions are computed and evaluated but are not shown as authoritative and do not
schedule questions.

### Gate D: Retest recommendation

Show proposed retests with reasons. The user starts them manually. Compare accepted,
dismissed and later-outcome data.

### Gate E: Confirmed preferences

Explicit and user-confirmed preferences may affect interaction. Inferred unconfirmed
preferences remain proposals.

### Gate F: Release candidate

Memory center, export, scoped deletion, backup policy, Docker upgrade and rollback
are verified on production-like copied data.

## 7. Human review protocol

- reviewers do not see the proposing model name;
- concept relations and usefulness are labeled separately;
- predicted retention is hidden when labeling actual recall;
- disagreement is adjudicated and reported;
- examples include uncertainty and abstention, not only easy positive matches;
- users review their own preference proposals and memory summaries in the pilot.

## 8. Security and privacy checks

- secret scanning of fixtures, exports and logs;
- prompt injection cannot create a memory category or identity link;
- external references are HMAC-hashed and never returned;
- export URLs expire;
- deletion jobs are authorization-ready even in the single-user evaluation build;
- operational metrics contain no answer text;
- raw audio is excluded from memory and export by design.

## 9. Release artifacts

The v0.7 release candidate must include:

- migration and rollback report;
- deterministic replay report;
- identity isolation test report;
- concept mapping confusion matrix and labeled-set hash;
- retention baseline comparison and calibration plots;
- retest planner baseline comparison;
- preference adversarial report;
- export/deletion completeness report;
- real-pilot limitations;
- model, prompt, policy and algorithm versions;
- Docker Compose upgrade, backup and restore evidence.

## 10. Research references

Half-life regression demonstrates one trainable approach to predicting recall, while
the open FSRS project models difficulty, stability and retrievability. v0.7 uses
these as candidate research baselines and keeps its source evidence model-neutral.

- https://aclanthology.org/P16-1174/
- https://github.com/open-spaced-repetition/fsrs4anki
- https://www.nist.gov/privacy-framework/frequently-asked-questions
