# v0.8 Increment L: Frozen Scenario Relevance Corpus

## Delivered

- source-controlled compact corpus specification for all seven built-in scenarios;
- deterministic expansion to 210 cases;
- 30 cases per template with exact language, difficulty and answer-quality balance;
- objective and question-taxonomy validation against the latest immutable template;
- SHA-256 corpus fingerprint;
- blind-judge evidence contract and deterministic aggregation;
- rejection of Mock evidence, self-judging providers, stale fingerprints,
  incomplete fields and invalid scores;
- per-template relevance improvement, confidence interval, quality, grounding,
  single-question and safety metrics;
- release rule requiring at least three complete passing templates;
- CLI corpus export, report aggregation and held-gate enforcement;
- combined release-report ingestion through `--relevance-report`.

## Verification

```text
Frozen cases                    210
Built-in templates              7
Cases per template              30
Language distribution           15 zh-CN / 15 en
Difficulty distribution         10 each at levels 2, 3 and 4
Answer-quality distribution     6 each across 5 classes
Focused tests                   8 passed
Focused Ruff                    passed
```

## Evidence status

```text
Frozen corpus integrity         passed
Cross-provider blind judging    held
Docker Compose rehearsal        held
Vultr upgrade/rollback          held
```

No paid-model or Mock result is represented as scenario-quality evidence.

## Remote Docker finding

The configured SeetaCloud test instance exposes the Docker client but is itself a
restricted container. Starting `dockerd` fails while creating the Docker NAT
chain because the environment lacks host `iptables` permissions. The v0.8
isolated Compose rehearsal therefore cannot run on that instance. No existing
AI Examiner directory, data or container was changed.

A VM or bare-metal Docker host with a running daemon is still required for the
deployment gates.
