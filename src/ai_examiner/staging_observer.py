from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def sample(client: httpx.Client, base_url: str) -> dict[str, Any]:
    started = time.perf_counter()
    health = client.get(f"{base_url.rstrip('/')}/health")
    ready = client.get(f"{base_url.rstrip('/')}/ready")
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    health_payload = health.json() if health.status_code == 200 else {}
    ready_payload = ready.json() if ready.status_code == 200 else {}
    authentication = (ready_payload.get("checks") or {}).get("authentication") or {}
    return {
        "timestamp": _utc_now(),
        "healthy": health.status_code == 200,
        "ready": ready.status_code == 200 and ready_payload.get("status") == "ready",
        "oidc_ready": authentication.get("ready") is True
        and authentication.get("mode") == "oidc",
        "version": health_payload.get("version"),
        "latency_ms": elapsed_ms,
    }


def observe(
    repo_root: Path,
    *,
    base_url: str,
    duration_hours: float,
    interval_seconds: float,
    output: Path,
    state_output: Path,
    open_release_blockers: int,
) -> dict[str, Any]:
    source_commit = _git(repo_root, "rev-parse", "HEAD")
    started_at = datetime.now(UTC)
    deadline = time.monotonic() + duration_hours * 3600
    samples: list[dict[str, Any]] = []
    with httpx.Client(timeout=15, follow_redirects=False) as client:
        while True:
            try:
                samples.append(sample(client, base_url))
            except (httpx.HTTPError, ValueError):
                samples.append(
                    {
                        "timestamp": _utc_now(),
                        "healthy": False,
                        "ready": False,
                        "oidc_ready": False,
                        "version": None,
                        "latency_ms": None,
                    }
                )
            state = {
                "schema_version": "1.0",
                "started_at": started_at.isoformat(),
                "updated_at": _utc_now(),
                "source_commit": source_commit,
                "target_sha256": hashlib.sha256(base_url.encode("utf-8")).hexdigest(),
                "requested_hours": duration_hours,
                "sample_count": len(samples),
                "failed_samples": sum(
                    not item["healthy"] or not item["ready"] for item in samples
                ),
                "oidc_ready_samples": sum(item["oidc_ready"] for item in samples),
            }
            state_output.parent.mkdir(parents=True, exist_ok=True)
            state_output.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            if time.monotonic() >= deadline:
                break
            time.sleep(min(interval_seconds, max(0.0, deadline - time.monotonic())))

    elapsed_hours = (datetime.now(UTC) - started_at).total_seconds() / 3600
    failed_samples = sum(not item["healthy"] or not item["ready"] for item in samples)
    oidc_verified = bool(samples) and all(item["oidc_ready"] for item in samples)
    tls_verified = base_url.lower().startswith("https://")
    passed = (
        elapsed_hours >= 24
        and failed_samples == 0
        and oidc_verified
        and tls_verified
        and open_release_blockers == 0
    )
    latencies = [item["latency_ms"] for item in samples if item["latency_ms"] is not None]
    payload = {
        "schema_version": "1.0",
        "generated_at": _utc_now(),
        "source_commit": source_commit,
        "status": "passed" if passed else "blocked",
        "observation_hours": round(elapsed_hours, 3),
        "sample_count": len(samples),
        "failed_samples": failed_samples,
        "availability_ratio": round((len(samples) - failed_samples) / max(len(samples), 1), 6),
        "maximum_health_latency_ms": max(latencies, default=0),
        "open_release_blockers": open_release_blockers,
        "tls_verified": tls_verified,
        "oidc_verified": oidc_verified,
        "target_sha256": hashlib.sha256(base_url.encode("utf-8")).hexdigest(),
        "contains_url": False,
        "contains_credentials": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Observe a v0.9 staging target for release promotion.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--duration-hours", type=float, default=24.0)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--open-release-blockers", type=int, default=0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/release-evidence/staging-observation.json"),
    )
    parser.add_argument(
        "--state-output",
        type=Path,
        default=Path("data/release-evidence/staging-observation-state.json"),
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo_root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else repo_root / args.output
    state_output = (
        args.state_output if args.state_output.is_absolute() else repo_root / args.state_output
    )
    payload = observe(
        repo_root,
        base_url=args.base_url,
        duration_hours=args.duration_hours,
        interval_seconds=args.interval_seconds,
        output=output,
        state_output=state_output,
        open_release_blockers=args.open_release_blockers,
    )
    print(json.dumps(payload, indent=2))
    if payload["status"] != "passed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
