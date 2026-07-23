# v0.8 Increment J Deterministic Evaluation Results

## Scope

Increment J adds one machine-readable entry point for the deterministic portion of
WP-12:

```bash
uv run ai-examiner-evaluate-templates \
  --output ./data/template-evaluation-report.json
```

The runner never calls a paid model.

## Recorded local run

```text
Report contract              template-evaluation-v1
Latest built-in scenarios    7
All packaged versions        9
Distinctness pairs           21
Override probes              112
Performance samples          30
Validation p95               11.494 ms
Compilation p95              11.501 ms
Deterministic gates          passed
Paid-model cost              USD 0.00
```

Timings describe this Windows development host and are not a production
performance claim.

## Gates covered

- structural and semantic validity of every latest built-in;
- deterministic recompilation and fingerprint equality;
- common safety, human-review, interruption and assessment invariants;
- pairwise scenario distinctness in at least three runtime dimensions, including
  conversation, assistance or assessment;
- accepted and rejected probes for locked, bounded, selectable and directional
  toggle overrides;
- local validation and compilation p50/p95.

## Held release evidence

Without attached provider-probe evidence, the report deliberately returns
`release_evidence.status = held` until these external gates are recorded:

- frozen-corpus scenario relevance;
- real `qwen-plus` sample;
- one independent real-provider sample;
- Docker Compose rehearsal;
- Vultr upgrade and rollback rehearsal.

`--require-release-evidence` exits with status 2 while any of these remain held.
This prevents deterministic fixtures or Mock output from being presented as
real-provider release acceptance.

Validated `template-provider-probe-v1` reports may be attached with repeatable
`--provider-probe` arguments. They can release only the Qwen and independent
provider contract-sample gates.
