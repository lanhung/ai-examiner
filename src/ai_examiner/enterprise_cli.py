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


if __name__ == "__main__":
    bootstrap_admin()

