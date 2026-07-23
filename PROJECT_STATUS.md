# AI Examiner v0.7.0 Release Candidate Status

## Current state

- Version: `0.7.0rc2`
- Branch: `develop/v0.7.0`
- Candidate tag: `v0.7.0-rc.2`
- Work packages: `WP-01` through `WP-12` complete
- Alembic head: `20260721_0005`
- Stable production line: unchanged

v0.7 completes the optional long-term learner intelligence lifecycle: opaque
identity, reviewed concepts, replayable retention, user-started retests, confirmed
preferences, memory center, correction, export, deletion, offline evaluation and
PostgreSQL readiness. Memory remains opt-in and does not alter text or realtime
examination behavior while disabled.

## Delivered capabilities

```text
WP-01  memory policy and opaque identity              complete
WP-02  reviewed canonical concept mapping             complete
WP-03  evidence-bound longitudinal event ledger       complete
WP-04  retention baselines and growth state           complete
WP-05  recommendation-only shadow retest planner      complete
WP-06  user-controlled retest lifecycle               complete
WP-07  confirmed preference registry                  complete
WP-08  responsive memory center                       complete
WP-09  correction, export and scoped deletion         complete
WP-10  deterministic longitudinal evaluation          complete
WP-11  PostgreSQL readiness and CI                    complete
WP-12  release hardening                              complete
```

The 300-pair concept-mapping activation gate remains held. Automatic retest
injection remains disabled. These held gates do not block this candidate because
neither behavior is active.

## Verification

```text
pytest                                      58 passed
ruff                                        passed
JavaScript syntax                           passed
git diff --check                            passed
SQLite upgrade -> downgrade -> re-upgrade   passed
PostgreSQL migration/domain CI              configured
Browser initialization                      passed
Dynamic API cache control                    no-store
Provider badge                              qwen / qwen-plus / 0.7.0rc2
Text model selector                         ready
Visual model selector                       qwen3-vl-plus ready
Memory center                               rendered and responsive
```

## Real-model acceptance

A non-Mock acceptance flow used `qwen:qwen-plus` through the running application:

```text
create project
-> upload 4,276-character Markdown material
-> generate seven-question blueprint with qwen-plus
-> create adaptive session
-> start first question
-> submit answer
-> analyze answer
-> choose GIVE_HINT for an insufficient answer
```

The recorded blueprint provider and model were `qwen` and `qwen-plus`. No API key
is stored in source control or release artifacts.

## Deployment verification

The candidate is running on the evaluation host at port `8016` from an isolated
Python 3.12 virtual environment. The host health endpoint reports
`0.7.0rc2`, `qwen-plus` and `provider_ready=true`.

The SeetaCloud evaluation host does not permit nested Docker image construction
(`unshare: operation not permitted`). Compose configuration is retained for a
normal Vultr host, but a full Docker build must be repeated on that target before
promoting this candidate to the stable production line.

## Release posture

- The candidate is suitable for staging and user acceptance testing.
- Do not merge it to `main` or create final tag `v0.7.0` until Vultr Compose,
  backup/restore and a small frozen-corpus longitudinal review pass.
- Tags are immutable. Candidate corrections use `v0.7.0-rc.2` or later.
