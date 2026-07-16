# v0.5 Adaptive Cognitive Engine Evaluation Plan

Status: Required release gate  
Control: v0.4.1 fixed question sequence  
Treatment: v0.5 adaptive-v1 policy

## 1. Evaluation question

The core question is not whether adaptive sessions feel more sophisticated. It is:

> Given the same document, time budget and learner answer profile, does the adaptive policy gather better evidence about important knowledge gaps with fewer irrelevant or repeated questions than the fixed policy?

## 2. Evaluation layers

### Engineering regression

- existing upload, blueprint, text session, voice session, report and dataset tests pass;
- fixed strategy produces v0.4-compatible behavior;
- schema migration preserves all existing rows;
- state rebuild is deterministic and idempotent;
- duplicate answer submission does not create duplicate evidence events;
- concurrent worker/API writes do not corrupt state.

### State correctness

- mastery remains in `[0, 1]`;
- confidence remains in `[0, 1]`;
- no state exists without supporting events;
- every event references a valid session, turn, question and knowledge unit;
- hints reduce independent evidence value;
- later contradictory evidence can reduce mastery;
- misconception resolution requires evidence, not only a correction message;
- rebuilding from events reproduces the stored aggregate.

### Selector behavior

- mastered topics have lower selection probability than weak important topics;
- active misconceptions are prioritized;
- prerequisites and question limits are respected;
- asked questions are not repeated without a revisit reason;
- selected difficulty is within one level of the controller target when candidates exist;
- candidate scores and rejection reasons are persisted;
- tie-breaking is deterministic under a fixed seed/config.

### Product behavior

- one user-facing main question per turn;
- follow-ups are tied to the previous answer;
- the system can explain why it asked the next question;
- fixed/adaptive choice is visible in session configuration;
- reports show evidence-backed concept states rather than only per-question scores.

## 3. Datasets

### Frozen Golden Dataset

Use at least five documents and a frozen dataset version per document. Each question must include:

- knowledge unit mapping;
- importance and difficulty;
- ideal, partial, misconception and evasive answers;
- expected next action;
- acceptable next knowledge units;
- source evidence.

### Synthetic learner profiles

Create deterministic answer trajectories:

1. uniformly strong;
2. uniformly weak;
3. strong recall but weak application;
4. one persistent high-confidence misconception;
5. uneven mastery across concepts;
6. evasive answers;
7. improves after a hint;
8. regresses under transfer questions.

### Adversarial cases

- prompt injection in an answer;
- confident unsupported claim;
- very long off-topic answer;
- answer that mentions all keywords with wrong causality;
- answer contradicting an earlier correct answer;
- missing or malformed knowledge mapping;
- no eligible next question;
- time budget expires during a misconception probe.

Every production bug becomes a regression case.

## 4. Primary metrics

### Relevant next-action rate

Fraction of decisions where the action and selected concept are in the expert/consensus acceptable set.

Target: `>= 0.85` on high-priority Golden cases.

### Important gap discovery

Weighted recall of seeded high-importance weak concepts detected before session end.

Target: adaptive improves by at least `10 percentage points` over fixed, with no material groundedness regression.

### Waste rate

Fraction of main questions that are redundant, already mastered, irrelevant or unsupported.

Target: `< 0.10` and lower than fixed.

### Misconception response rate

Fraction of seeded misconceptions that lead to challenge, clarification, targeted follow-up or concept-linked next question.

Target: `>= 0.85`.

### State calibration

Compare final mastery bands with the known synthetic learner state.

Report:

- mean absolute error;
- severe inversion rate;
- calibration by confidence band;
- evidence count per final state.

Initial target: mastery MAE `<= 0.15`, severe inversion `< 0.05`.

## 5. Secondary metrics

- knowledge unit coverage;
- average information-gain proxy per question;
- question repetition rate;
- average probes per misconception;
- difficulty transition rate;
- difficulty overshoot/undershoot;
- report evidence validity;
- policy decision reproducibility;
- LLM calls, latency and cost per session;
- text versus voice-transcript consistency.

Do not optimize only the aggregate score. Publish per-profile and per-question-type breakdowns.

## 6. Experiment protocol

For every frozen case:

1. Run the same answer simulator against `fixed` and `adaptive-v1`.
2. Keep blueprint, provider, prompts, question limit and time budget fixed.
3. Run deterministic rules with identical policy configuration.
4. Repeat stochastic model calls at least three times when they affect Analyzer output.
5. Record full turns, events, candidate scores, decisions, tokens, latency and cost.
6. Compare paired outcomes, not unrelated aggregate runs.

The benchmark artifact must record:

```json
{
  "git_commit": "...",
  "app_version": "0.5.0rc1",
  "dataset_ids": ["..."],
  "prompt_manifest": {},
  "model_profiles": [],
  "policy_version": "adaptive-v1",
  "policy_config": {},
  "random_seed": 42
}
```

## 7. Statistical reporting

- paired difference between adaptive and fixed;
- bootstrap 95% confidence intervals;
- per-document and per-profile results;
- failure counts with raw examples;
- cost and latency deltas;
- no claim of improvement when confidence intervals are inconclusive.

For early small samples, emphasize effect sizes and failure analysis rather than overstating significance.

## 8. Human calibration

AI-generated reference data reduces manual work but does not eliminate shared model bias. Before final release, sample at least 20 decisions across documents and learner profiles for blind review.

Reviewers rate:

- next question relevance;
- difficulty appropriateness;
- misconception handling;
- evidence grounding;
- fairness of the report conclusion.

Track AI-human disagreement and add systematic errors to the regression set.

## 9. Voice-specific checks

- finalized transcript maps to exactly one answer evidence event;
- partial transcripts do not update state;
- user interruption does not duplicate a turn;
- transcript correction produces a compensating event or clean pre-finalization update;
- adaptive question text and Realtime spoken question remain aligned;
- voice latency is measured separately from cognitive policy latency.

## 10. Migration and operations checks

On a copy of the deployed v0.4.1 database:

1. create backup;
2. run upgrade migration;
3. start API and worker;
4. open old projects, sessions and reports;
5. create fixed and adaptive sessions;
6. restart services and verify state persistence;
7. run downgrade or documented code rollback;
8. restore backup and verify health.

No release if migration loses turns, evidence, datasets or voice records.

## 11. Release thresholds

Required for `v0.5.0-rc.1`:

- all engineering tests pass;
- fixed mode has zero known critical regression;
- state rebuild is deterministic in 100% of test cases;
- evidence linkage completeness is 100%;
- relevant next-action rate `>= 0.80`;
- no secret or runtime data in Git.

Required for final `v0.5.0`:

- relevant next-action rate `>= 0.85` on priority cases;
- important gap discovery improves by at least 10 percentage points over fixed;
- waste rate `< 0.10`;
- misconception response rate `>= 0.85`;
- mastery MAE `<= 0.15` on synthetic known-state profiles;
- human sample reveals no unresolved systematic high-severity issue;
- staging migration, rollback and Docker deployment pass;
- changelog, API reference, architecture, migration and release notes are complete.

If adaptive quality misses thresholds, ship no adaptive default. Keep it behind an evaluation flag or postpone the release.
