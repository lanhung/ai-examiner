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

