from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from .config import Settings, get_settings
from .db import Base
from .enterprise_constants import LEGACY_ORGANIZATION_ID
from .models import ModelUsageLedger
from .providers.factory import profile_ready
from .services.enterprise_identity import ensure_legacy_organization
from .services.model_governance import (
    GovernedModelProvider,
    MemoryModelRateLimiter,
    ensure_model_policy,
)


def _source_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run_probe(settings: Settings, *, profile: str) -> dict[str, Any]:
    if profile.startswith("mock:"):
        raise ValueError("The release governance probe requires a real provider profile")
    if not profile_ready(settings, profile):
        raise RuntimeError("The requested provider is not configured")

    with tempfile.TemporaryDirectory(prefix="ai-examiner-v09-probe-") as directory:
        database_path = Path(directory) / "probe.db"
        engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        try:
            Base.metadata.create_all(engine)
            probe_sessions = sessionmaker(
                bind=engine,
                autoflush=False,
                expire_on_commit=False,
            )
            with probe_sessions() as db:
                ensure_legacy_organization(db)
                policy = ensure_model_policy(db, LEGACY_ORGANIZATION_ID)
                db.commit()
                policy_version = policy.version
                policy_digest = policy.policy_digest

            provider = GovernedModelProvider(
                settings=settings,
                organization_id=LEGACY_ORGANIZATION_ID,
                principal_id=None,
                project_id=None,
                session_id=None,
                classification="internal",
                requested_profile=profile,
                session_factory=probe_sessions,
                rate_limiter=MemoryModelRateLimiter(),
            )
            result = provider.complete_json(
                agent="release_governance_probe",
                instructions=(
                    "Return a JSON object whose status field is exactly ok. "
                    "Do not include explanations."
                ),
                payload={"probe": "v0.9-model-policy"},
                schema_hint={"status": "string"},
            )
            with probe_sessions() as db:
                ledger = db.scalar(
                    select(ModelUsageLedger).order_by(
                        ModelUsageLedger.created_at.desc()
                    )
                )
                if ledger is None:
                    raise RuntimeError(
                        "The governed call did not create a usage ledger"
                    )
                return {
                    "schema_version": "1.0",
                    "generated_at": datetime.now(UTC).isoformat(),
                    "source_commit": _source_commit(),
                    "environment": "real_provider_governance_probe",
                    "status": "passed",
                    "requested_profile": profile,
                    "actual_provider": ledger.actual_provider,
                    "actual_model": ledger.actual_model,
                    "ledger_status": ledger.status,
                    "policy_version": policy_version,
                    "policy_digest": policy_digest,
                    "input_tokens": ledger.input_tokens,
                    "output_tokens": ledger.output_tokens,
                    "latency_ms": ledger.latency_ms,
                    "estimated_cost_usd": ledger.estimated_cost_usd,
                    "provider_result_matches_ledger": (
                        result.provider == ledger.actual_provider
                        and result.model == ledger.actual_model
                    ),
                    "prompt_content_recorded": False,
                    "response_content_recorded": False,
                    "api_key_recorded": False,
                }
        finally:
            engine.dispose()


def write_probe(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one bounded, sanitized real-provider v0.9 governance probe."
    )
    parser.add_argument("--profile", default="qwen:qwen-plus")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/release-evidence/quota-model-policy.json"),
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        report = run_probe(get_settings(), profile=args.profile)
    except Exception as exc:
        report = {
            "schema_version": "1.0",
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "failed",
            "requested_profile": args.profile,
            "failure_type": type(exc).__name__,
            "prompt_content_recorded": False,
            "response_content_recorded": False,
            "api_key_recorded": False,
        }
        write_probe(report, args.output)
        print(
            f"Model governance probe failed ({type(exc).__name__}); "
            "provider details were redacted."
        )
        raise SystemExit(1) from exc
    write_probe(report, args.output)
    print(
        "Model governance probe passed: "
        f"{report['actual_provider']}:{report['actual_model']}"
    )
    print(f"Sanitized report: {args.output}")


if __name__ == "__main__":
    main()
