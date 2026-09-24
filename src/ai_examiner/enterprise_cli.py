from __future__ import annotations

import argparse
import json

from .db import SessionLocal, init_db
from .enterprise_constants import (
    LEGACY_ORGANIZATION_ID,
    LOCAL_IDENTITY_ISSUER,
)
from .services.enterprise_identity import (
    EnterpriseIdentityError,
    bootstrap_owner,
    serialize_membership,
    serialize_organization,
    serialize_principal,
)


def _bootstrap_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotently bootstrap the first owner membership for an AI Examiner "
            "organization. No password or provider token is stored."
        )
    )
    parser.add_argument("--issuer", default=LOCAL_IDENTITY_ISSUER)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--display-name", default=None)
    parser.add_argument("--email", default=None)
    parser.add_argument(
        "--organization-id",
        default=LEGACY_ORGANIZATION_ID,
        help="Existing organization ID; defaults to the deterministic legacy workspace.",
    )
    return parser


def bootstrap_admin() -> None:
    args = _bootstrap_parser().parse_args()
    init_db()
    try:
        with SessionLocal() as db:
            organization, principal, membership = bootstrap_owner(
                db,
                issuer=args.issuer,
                subject=args.subject,
                display_name=args.display_name,
                email=args.email,
                organization_id=args.organization_id,
            )
    except EnterpriseIdentityError as exc:
        raise SystemExit(str(exc)) from exc

    print(
        json.dumps(
            {
                "organization": serialize_organization(organization),
                "principal": serialize_principal(principal),
                "membership": serialize_membership(membership),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _limits_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Set an organization's model admission limits from the server shell. "
            "Use it for single-organization pilots that run without the OIDC "
            "administration API. Omitted options keep their current values."
        )
    )
    parser.add_argument("--organization-id", default=LEGACY_ORGANIZATION_ID)
    parser.add_argument("--max-concurrent-calls", type=int)
    parser.add_argument("--organization-requests-per-minute", type=int)
    parser.add_argument("--principal-requests-per-minute", type=int)
    parser.add_argument("--organization-tokens-per-minute", type=int)
    parser.add_argument("--monthly-budget-usd", type=float)
    parser.add_argument("--per-session-budget-usd", type=float)
    parser.add_argument("--per-request-budget-usd", type=float)
    return parser


LIMIT_FIELDS = (
    "max_concurrent_calls",
    "organization_requests_per_minute",
    "principal_requests_per_minute",
    "organization_tokens_per_minute",
    "monthly_budget_usd",
    "per_session_budget_usd",
    "per_request_budget_usd",
)


def set_model_limits(argv: list[str] | None = None) -> dict:
    from .services import model_governance
    from .services.tenancy import tenant_context

    args = _limits_parser().parse_args(argv)
    changes = {
        field: getattr(args, field)
        for field in LIMIT_FIELDS
        if getattr(args, field) is not None
    }
    for field, value in changes.items():
        if value <= 0:
            raise SystemExit(f"--{field.replace('_', '-')} must be positive")
    init_db()
    with SessionLocal() as db:
        with tenant_context(db, organization_id=args.organization_id, principal_id=None):
            policy = model_governance.ensure_model_policy(db, args.organization_id)
            for field, value in changes.items():
                setattr(policy, field, value)
            if changes:
                policy.version = int(policy.version or 1) + 1
                policy.policy_digest = model_governance._effective_policy_digest(policy)
            db.commit()
            current = {field: getattr(policy, field) for field in LIMIT_FIELDS}
    result = {"organization_id": args.organization_id, "changed": sorted(changes), **current}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def run_set_model_limits() -> None:
    set_model_limits()


if __name__ == "__main__":
    bootstrap_admin()

