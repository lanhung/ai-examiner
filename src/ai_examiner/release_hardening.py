from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}\b")),
    ("anthropic_api_key", re.compile(r"\bsk-ant-(?:api\d{2}-)?[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b")),
    ("dashscope_api_key", re.compile(r"\bsk-[0-9a-fA-F]{32,64}\b")),
)

REQUIRED_EXTERNAL_EVIDENCE: tuple[tuple[str, str], ...] = (
    ("tenant_isolation", "tenant-isolation.json"),
    ("auth_token_matrix", "auth-token-matrix.json"),
    ("route_capability_coverage", "route-capability-coverage.json"),
    ("postgres_migration", "postgres-migration.json"),
    ("storage_contract", "storage-contract.json"),
    ("queue_idempotency", "queue-idempotency.json"),
    ("audit_redaction", "audit-redaction.json"),
    ("quota_model_policy", "quota-model-policy.json"),
    ("telemetry_redaction", "telemetry-redaction.json"),
    ("disaster_recovery", "disaster-recovery.json"),
    ("ai_regression", "ai-regression.json"),
    ("staging_observation", "staging-observation.json"),
    ("enterprise_ui_acceptance", "enterprise-ui-acceptance.json"),
)


@dataclass(frozen=True)
class GateCheck:
    id: str
    category: str
    status: str
    summary: str
    evidence: dict[str, Any]
    required_for_release: bool = True


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout.strip()


def tracked_files(repo_root: Path) -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    ).stdout
    return [
        repo_root / item.decode("utf-8", errors="surrogateescape")
        for item in output.split(b"\0")
        if item
    ]


def scan_tracked_secrets(repo_root: Path) -> GateCheck:
    findings: list[dict[str, str]] = []
    scanned = 0
    for path in tracked_files(repo_root):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            continue
        scanned += 1
        text = raw.decode("utf-8", errors="replace")
        for rule_id, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(
                    {
                        "path": path.relative_to(repo_root).as_posix(),
                        "rule_id": rule_id,
                    }
                )
    status = "passed" if not findings else "failed"
    return GateCheck(
        id="tracked_source_secret_scan",
        category="security",
        status=status,
        summary=(
            f"Scanned {scanned} tracked text files; "
            f"{len(findings)} potential provider secret(s) found."
        ),
        evidence={"scanned_files": scanned, "findings": findings},
    )


def _command_check(
    repo_root: Path,
    *,
    check_id: str,
    category: str,
    command: list[str],
) -> GateCheck:
    started = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GateCheck(
            id=check_id,
            category=category,
            status="failed",
            summary=f"Command could not complete: {type(exc).__name__}.",
            evidence={"command": command, "duration_ms": int((time.perf_counter() - started) * 1000)},
        )
    output = f"{result.stdout}\n{result.stderr}".strip()
    return GateCheck(
        id=check_id,
        category=category,
        status="passed" if result.returncode == 0 else "failed",
        summary=f"Command exited with status {result.returncode}.",
        evidence={
            "command": command,
            "return_code": result.returncode,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "output_sha256": _sha256_text(output),
        },
    )


def dependency_audit(repo_root: Path) -> GateCheck:
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-m", "pip_audit", "--format", "json"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    vulnerabilities: list[dict[str, str]] = []
    parse_error = False
    try:
        payload = json.loads(result.stdout or "{}")
        dependencies = payload.get("dependencies", []) if isinstance(payload, dict) else payload
        for dependency in dependencies:
            for vulnerability in dependency.get("vulns", []):
                vulnerabilities.append(
                    {
                        "package": str(dependency.get("name") or ""),
                        "id": str(vulnerability.get("id") or ""),
                        "fix_versions": ",".join(vulnerability.get("fix_versions") or []),
                    }
                )
    except (TypeError, ValueError):
        parse_error = True
    passed = result.returncode == 0 and not vulnerabilities and not parse_error
    return GateCheck(
        id="dependency_audit",
        category="security",
        status="passed" if passed else "failed",
        summary=(
            "No known dependency vulnerabilities found."
            if passed
            else f"Dependency audit found {len(vulnerabilities)} issue(s)."
        ),
        evidence={
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "return_code": result.returncode,
            "parse_error": parse_error,
            "vulnerabilities": vulnerabilities,
        },
    )


def migration_head_check(repo_root: Path) -> GateCheck:
    config = Config(str(repo_root / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = list(script.get_heads())
    return GateCheck(
        id="single_migration_head",
        category="database",
        status="passed" if len(heads) == 1 else "failed",
        summary=f"Found {len(heads)} Alembic migration head(s).",
        evidence={"heads": heads},
    )


def route_policy_check() -> GateCheck:
    from fastapi.routing import APIRoute

    from .main import app
    from .services.authorization import ROUTE_POLICIES, bind_and_validate_route_policies

    bind_and_validate_route_policies(app)

    discovered: set[tuple[str, str]] = set()
    missing_metadata: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith("/api/v1"):
            continue
        for method in route.methods:
            key = (method, route.path)
            discovered.add(key)
            if not (route.openapi_extra or {}).get("x-ai-examiner-policy"):
                missing_metadata.append(f"{method} {route.path}")
    missing_registry = sorted(
        f"{method} {path}" for method, path in discovered - set(ROUTE_POLICIES)
    )
    orphaned_registry = sorted(
        f"{method} {path}" for method, path in set(ROUTE_POLICIES) - discovered
    )
    passed = not missing_metadata and not missing_registry and not orphaned_registry
    return GateCheck(
        id="route_capability_registry",
        category="authorization",
        status="passed" if passed else "failed",
        summary=f"Validated {len(discovered)} protected API route-method pairs.",
        evidence={
            "route_count": len(discovered),
            "missing_metadata": sorted(missing_metadata),
            "missing_registry": missing_registry,
            "orphaned_registry": orphaned_registry,
        },
    )


def ai_regression_check(repo_root: Path) -> GateCheck:
    path = (
        repo_root
        / "docs"
        / "evaluation"
        / "evidence"
        / "V0_8_PLANNER_V6_ALL7_RECIPROCAL_EVIDENCE.json"
    )
    if not path.exists():
        return GateCheck(
            id="v08_ai_regression",
            category="ai_quality",
            status="failed",
            summary="Frozen Planner v6 evidence is missing.",
            evidence={"path": path.relative_to(repo_root).as_posix()},
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    status = str(payload.get("status") or "").lower()
    corpus = payload.get("corpus") or {}
    passed = status == "passed" and int(corpus.get("template_count") or 0) == 7
    return GateCheck(
        id="v08_ai_regression",
        category="ai_quality",
        status="passed" if passed else "failed",
        summary="Validated frozen seven-template Planner v6 evidence.",
        evidence={
            "path": path.relative_to(repo_root).as_posix(),
            "status": status,
            "template_count": corpus.get("template_count"),
            "case_count": corpus.get("case_count"),
            "fingerprint": corpus.get("fingerprint"),
        },
    )


def external_evidence_checks(repo_root: Path, evidence_dir: Path) -> list[GateCheck]:
    checks: list[GateCheck] = []
    for check_id, filename in REQUIRED_EXTERNAL_EVIDENCE:
        path = evidence_dir / filename
        relative = path.relative_to(repo_root).as_posix() if path.is_relative_to(repo_root) else str(path)
        if not path.exists():
            checks.append(
                GateCheck(
                    id=check_id,
                    category="staging_evidence",
                    status="blocked",
                    summary=f"Required release evidence is missing: {filename}.",
                    evidence={"path": relative},
                )
            )
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            checks.append(
                GateCheck(
                    id=check_id,
                    category="staging_evidence",
                    status="failed",
                    summary=f"Release evidence is not valid JSON: {filename}.",
                    evidence={"path": relative},
                )
            )
            continue
        evidence_status = str(payload.get("status") or "").lower()
        validation_errors = _evidence_validation_errors(check_id, payload)
        accepted = evidence_status == "passed" and not validation_errors
        checks.append(
            GateCheck(
                id=check_id,
                category="staging_evidence",
                status="passed" if accepted else "blocked",
                summary=(
                    f"Evidence {filename} passed schema and acceptance checks."
                    if accepted
                    else f"Evidence {filename} is not release-acceptable."
                ),
                evidence={
                    "path": relative,
                    "status": evidence_status,
                    "source_commit": payload.get("source_commit"),
                    "validation_errors": validation_errors,
                    "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                },
            )
        )
    return checks


def _evidence_validation_errors(
    check_id: str,
    payload: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not payload.get("generated_at"):
        errors.append("missing_generated_at")
    source_commit = str(payload.get("source_commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40,64}", source_commit):
        errors.append("invalid_source_commit")
    if check_id == "quota_model_policy":
        if payload.get("actual_provider") not in {
            "openai",
            "anthropic",
            "gemini",
            "qwen",
        }:
            errors.append("real_provider_required")
        if payload.get("ledger_status") != "completed":
            errors.append("completed_ledger_required")
        if payload.get("provider_result_matches_ledger") is not True:
            errors.append("provider_ledger_mismatch")
        if any(
            payload.get(field) is not False
            for field in (
                "prompt_content_recorded",
                "response_content_recorded",
                "api_key_recorded",
            )
        ):
            errors.append("sensitive_content_recorded")
    elif check_id == "disaster_recovery":
        if float(payload.get("rpo_seconds") or 1e20) > 86_400:
            errors.append("rpo_target_missed")
        if float(payload.get("rto_seconds") or 1e20) > 14_400:
            errors.append("rto_target_missed")
        if payload.get("object_restore_verified") is not True:
            errors.append("object_restore_not_verified")
        if payload.get("rollback_success") is not True:
            errors.append("rollback_not_verified")
    elif check_id == "staging_observation":
        if float(payload.get("observation_hours") or 0) < 24:
            errors.append("observation_period_too_short")
        if int(payload.get("open_release_blockers") or 0) != 0:
            errors.append("open_release_blockers")
        if payload.get("tls_verified") is not True:
            errors.append("tls_not_verified")
        if payload.get("oidc_verified") is not True:
            errors.append("oidc_not_verified")
    elif check_id == "enterprise_ui_acceptance":
        for field in (
            "desktop_passed",
            "mobile_passed",
            "oidc_login_passed",
            "stale_tenant_guard_passed",
        ):
            if payload.get(field) is not True:
                errors.append(f"{field}_required")
    return errors


def build_release_report(
    repo_root: Path,
    *,
    execute_commands: bool,
    evidence_dir: Path,
) -> dict[str, Any]:
    checks: list[GateCheck] = [
        scan_tracked_secrets(repo_root),
        migration_head_check(repo_root),
        route_policy_check(),
        ai_regression_check(repo_root),
    ]
    if execute_commands:
        checks.extend(
            [
                _command_check(
                    repo_root,
                    check_id="ruff",
                    category="engineering",
                    command=[sys.executable, "-m", "ruff", "check", "src", "tests"],
                ),
                _command_check(
                    repo_root,
                    check_id="pytest",
                    category="engineering",
                    command=[
                        sys.executable,
                        "-m",
                        "pytest",
                        "--cov=ai_examiner",
                        "--cov-report=term-missing",
                    ],
                ),
            ]
        )
        javascript = sorted(
            path for path in tracked_files(repo_root) if path.suffix == ".js"
        )
        if shutil.which("node"):
            for path in javascript:
                checks.append(
                    _command_check(
                        repo_root,
                        check_id=f"javascript_syntax:{path.relative_to(repo_root).as_posix()}",
                        category="engineering",
                        command=["node", "--check", str(path)],
                    )
                )
        else:
            checks.append(
                GateCheck(
                    id="javascript_syntax",
                    category="engineering",
                    status="failed",
                    summary="Node.js is unavailable; JavaScript syntax was not checked.",
                    evidence={"file_count": len(javascript)},
                )
            )
        checks.append(dependency_audit(repo_root))
    else:
        checks.append(
            GateCheck(
                id="command_checks",
                category="engineering",
                status="blocked",
                summary="Command checks were explicitly skipped.",
                evidence={},
            )
        )
    checks.extend(external_evidence_checks(repo_root, evidence_dir))
    deterministic = [
        check
        for check in checks
        if check.category != "staging_evidence"
    ]
    deterministic_ready = all(check.status == "passed" for check in deterministic)
    release_ready = deterministic_ready and all(check.status == "passed" for check in checks)
    status = "release_ready" if release_ready else (
        "deterministic_ready" if deterministic_ready else "failed"
    )
    return {
        "schema_version": "1.0",
        "generated_at": _utc_now(),
        "source_commit": _git(repo_root, "rev-parse", "HEAD"),
        "source_branch": _git(repo_root, "branch", "--show-current"),
        "package_version": _package_version(repo_root),
        "status": status,
        "deterministic_ready": deterministic_ready,
        "release_ready": release_ready,
        "summary": {
            "passed": sum(check.status == "passed" for check in checks),
            "failed": sum(check.status == "failed" for check in checks),
            "blocked": sum(check.status == "blocked" for check in checks),
        },
        "checks": [asdict(check) for check in checks],
        "security": {
            "contains_secret_values": False,
            "contains_model_content": False,
        },
    }


def _package_version(repo_root: Path) -> str:
    match = re.search(
        r'(?m)^version\s*=\s*"([^"]+)"',
        (repo_root / "pyproject.toml").read_text(encoding="utf-8"),
    )
    return match.group(1) if match else "unknown"


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic v0.9 release checks and evaluate promotion evidence."
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=Path("docs/evaluation/evidence/v0_9"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/release-evidence/v0_9-release-gate.json"),
    )
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--skip-command-checks", action="store_true")
    parser.add_argument("--require-release-ready", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo_root = args.repo_root.resolve()
    evidence_dir = args.evidence_dir
    if not evidence_dir.is_absolute():
        evidence_dir = repo_root / evidence_dir
    output = args.output
    if not output.is_absolute():
        output = repo_root / output
    if args.scan_only:
        check = scan_tracked_secrets(repo_root)
        report = {
            "schema_version": "1.0",
            "generated_at": _utc_now(),
            "source_commit": _git(repo_root, "rev-parse", "HEAD"),
            "status": check.status,
            "checks": [asdict(check)],
            "security": {
                "contains_secret_values": False,
                "contains_model_content": False,
            },
        }
        write_report(report, output)
        print(f"Tracked-source secret scan: {check.status}")
        print(f"Sanitized report: {output}")
        if check.status != "passed":
            raise SystemExit(1)
        return
    report = build_release_report(
        repo_root,
        execute_commands=not args.skip_command_checks,
        evidence_dir=evidence_dir,
    )
    write_report(report, output)
    print(
        f"v0.9 release gate: {report['status']} "
        f"(passed={report['summary']['passed']}, "
        f"failed={report['summary']['failed']}, "
        f"blocked={report['summary']['blocked']})"
    )
    print(f"Sanitized report: {output}")
    if report["status"] == "failed":
        raise SystemExit(1)
    if args.require_release_ready and not report["release_ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
