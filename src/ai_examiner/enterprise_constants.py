from __future__ import annotations

LEGACY_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
LEGACY_ORGANIZATION_SLUG = "legacy"
LEGACY_ORGANIZATION_NAME = "Legacy workspace"
LOCAL_IDENTITY_ISSUER = "urn:ai-examiner:local"

ORGANIZATION_STATUSES = frozenset({"active", "suspended", "disabled"})
PRINCIPAL_STATUSES = frozenset({"pending", "active", "suspended", "disabled"})
MEMBERSHIP_STATUSES = frozenset({"invited", "active", "suspended", "revoked"})
ORGANIZATION_ROLES = frozenset(
    {
        "owner",
        "admin",
        "examiner",
        "template_author",
        "reviewer",
        "learner",
        "auditor",
    }
)

CAPABILITIES = frozenset(
    {
        "organization.read",
        "organization.update",
        "organization.delete",
        "member.read",
        "member.manage",
        "member.grant_owner",
        "service_account.read",
        "service_account.manage",
        "policy.read",
        "policy.manage",
        "audit.read",
        "usage.read",
        "retention.read",
        "retention.manage",
        "project.create",
        "project.read",
        "project.update",
        "project.delete",
        "document.create",
        "document.read",
        "document.delete",
        "blueprint.create",
        "blueprint.read",
        "session.create",
        "session.conduct",
        "session.read",
        "report.read",
        "dataset.manage",
        "benchmark.run",
        "expert_rating.create",
        "template.read",
        "template.author",
        "template.review",
        "template.publish",
        "template.bind",
        "prompt.read",
        "prompt.author",
        "prompt.activate",
        "learner.read",
        "learner.manage",
        "learner_memory.read_self",
        "learner_memory.manage_self",
        "learner_memory.admin",
        "retest.manage",
        "review_case.create",
        "review_case.review",
        "review_case.appeal",
        "job.read",
        "job.manage",
        "provider_health.read",
        "system_metrics.read",
        "system_backup.run",
    }
)

_ORGANIZATION_READ = {
    "organization.read",
    "template.read",
}
_WORK_READ = {
    "project.read",
    "document.read",
    "blueprint.read",
    "session.read",
    "report.read",
}

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "owner": CAPABILITIES,
    "admin": CAPABILITIES
    - {
        "organization.delete",
        "member.grant_owner",
        "system_backup.run",
    },
    "examiner": frozenset(
        _ORGANIZATION_READ
        | _WORK_READ
        | {
            "project.create",
            "project.update",
            "document.create",
            "document.delete",
            "blueprint.create",
            "session.create",
            "session.conduct",
            "dataset.manage",
            "benchmark.run",
            "expert_rating.create",
            "template.bind",
            "learner.read",
            "retest.manage",
            "job.read",
            "job.manage",
            "usage.read",
        }
    ),
    "template_author": frozenset(
        _ORGANIZATION_READ
        | _WORK_READ
        | {
            "template.author",
            "template.bind",
            "prompt.read",
            "prompt.author",
        }
    ),
    "reviewer": frozenset(
        _ORGANIZATION_READ
        | _WORK_READ
        | {
            "policy.read",
            "template.review",
            "prompt.read",
            "learner.read",
            "review_case.create",
            "review_case.review",
            "review_case.appeal",
        }
    ),
    "learner": frozenset(
        _ORGANIZATION_READ
        | {
            "learner_memory.read_self",
            "learner_memory.manage_self",
            "review_case.appeal",
        }
    ),
    "auditor": frozenset(
        _ORGANIZATION_READ
        | _WORK_READ
        | {
            "member.read",
            "service_account.read",
            "policy.read",
            "audit.read",
            "usage.read",
            "retention.read",
            "prompt.read",
            "learner.read",
            "job.read",
            "provider_health.read",
            "system_metrics.read",
        }
    ),
}

HIGH_RISK_CAPABILITIES = frozenset(
    {
        "organization.delete",
        "member.grant_owner",
        "service_account.manage",
        "template.publish",
        "retention.manage",
        "learner_memory.admin",
        "policy.manage",
        "system_backup.run",
    }
)

if set(ROLE_CAPABILITIES) != set(ORGANIZATION_ROLES):
    raise RuntimeError("Every organization role must have one capability bundle")
if any(
    not capabilities <= CAPABILITIES
    for capabilities in ROLE_CAPABILITIES.values()
):
    raise RuntimeError("Role capability bundle contains an unknown capability")
