# AI Examiner v0.9.0 RC2

RC2 closes enterprise-staging integration gaps discovered after RC1 promotion.
The principal changes are PostgreSQL RLS-safe organization discovery, full tenant
context propagation from the main workbench, capability enforcement on workbench
APIs, recoverable real-Qwen Planner execution and reboot-safe AutoDL orchestration.

It also closes the persisted-before-published Celery recovery window, defaults
dataset generation to the configured real provider, accepts whitespace-equivalent
grounding evidence and requires pypdf 6.15.0 or newer after the RC2 dependency
audit identified two malicious-PDF resource-exhaustion advisories.

RC2 is a controlled-staging candidate. The `v0.9.0-rc.2` tag is created only after
local regression, PostgreSQL RLS, public OIDC/S3/Qwen workflow, browser and restart
recovery gates pass against the same commit.

## Acceptance snapshot

```text
Automated tests              351 passed
Dependency audit             no known vulnerabilities
Alembic head                 20260810_0017
Authorization metadata       48 routes / complete
PostgreSQL RLS               48 policies / 41 protected tables / passed
Public workbench             OIDC + S3 + Celery + Qwen Plus passed
Grounded Planner output      2 questions / passed
Queue latency                33.3 ms
End-to-end Planner latency   15.6 seconds
Browser workbench            organization + Qwen defaults + 7 templates passed
Template health              ok (7 templates / 9 versions / 7 prompts)
```

The immutable tag remains pending until the committed-source release gate is run
from the RC2 commit.
