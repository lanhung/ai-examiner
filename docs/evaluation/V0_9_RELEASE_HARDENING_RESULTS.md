# v0.9 WP-14 Release Hardening Results

Status: implementation complete; release promotion held pending external evidence.

## Implemented

- deterministic release-gate CLI;
- tracked-source provider-secret scan that never prints matched values;
- dependency vulnerability audit in CI;
- single Alembic-head verification;
- complete `/api/v1` route-policy metadata verification;
- frozen v0.8 Planner v6 evidence validation;
- JavaScript syntax, Ruff and full pytest orchestration;
- machine-readable external evidence contract;
- bounded real-provider governance probe;
- measured provider latency fallback when a Provider omits latency;
- GitHub Actions artifact upload;
- enterprise operator manual and RC promotion rules.

Commands:

```bash
uv run ai-examiner-verify-v09-release

uv run ai-examiner-probe-model-governance \
  --profile qwen:qwen-plus
```

## Security properties

The release artifacts contain:

- source commit and branch;
- pass/fail/blocked states;
- command and output digests;
- provider/model identity;
- Token counts, latency and estimated cost;
- policy version and digest.

They do not contain:

- API keys or bearer tokens;
- prompts or model responses;
- uploaded documents or transcript content;
- database credentials;
- presigned object URLs.

## Current promotion decision

The package remains `0.8.0.dev0` on `research/v0.9.0`. No `0.9.0rc1` tag is
authorized yet.

The following external gates must still produce accepted evidence:

- Vultr PostgreSQL/Redis/MinIO/observability deployment;
- institutional or test OIDC login and invalid-token staging matrix;
- desktop and mobile enterprise UI screenshots and workflow acceptance;
- 24-hour staging observation with zero open release blockers;
- isolated database and object recovery plus application rollback;
- bounded real Qwen or OpenAI governance call;
- consolidated tenant, storage, queue, audit and telemetry integration artifacts.

`ai-examiner-verify-v09-release --require-release-ready` is the authoritative
promotion decision. It exits with status 2 while these artifacts are absent.

## Local verification on 2026-07-29

```text
complete pytest suite                297 passed
complete deterministic gate          passed
dependency audit                     no known vulnerabilities
tracked-source provider-key scan     zero findings
Alembic heads                        1 (20260728_0016)
route-policy metadata                complete
Planner v6 frozen evidence           7 templates / 210 cases
release evidence                     1 passed / 12 blocked external artifacts
```

The bounded Qwen Plus governance probe passed:

```text
input Token                          126
output Token                         6
observed latency                     1,674 ms
estimated cost                       USD 0.00001565
provider/model ledger match          yes
prompt/response/key retained         no
```

The accepted probe is bound to source commit
`94cedb8c2dae4ff04ad4c2af51fd71de9e4fd5dd` and archived as
`docs/evaluation/evidence/v0_9/quota-model-policy.json`.
