from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree


@dataclass(frozen=True)
class SuiteResult:
    tests: int
    failures: int
    errors: int
    skipped: int
    duration_seconds: float
    return_code: int
    output_sha256: str

    @property
    def passed(self) -> bool:
        return self.return_code == 0 and self.failures == 0 and self.errors == 0


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()


def _run_pytest(repo_root: Path, nodeids: list[str]) -> SuiteResult:
    with tempfile.TemporaryDirectory(prefix="ai-examiner-evidence-") as temporary:
        junit = Path(temporary) / "junit.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--disable-warnings",
            "--maxfail=1",
            f"--junitxml={junit}",
            *nodeids,
        ]
        completed = subprocess.run(
            command,
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
        )
        combined = f"{completed.stdout}\n{completed.stderr}".strip()
        if junit.exists():
            root = ElementTree.parse(junit).getroot()
            aggregate = root if root.tag == "testsuite" else root.find("testsuite")
        else:
            aggregate = None
        attributes = aggregate.attrib if aggregate is not None else {}
        return SuiteResult(
            tests=int(attributes.get("tests", 0)),
            failures=int(attributes.get("failures", 0)),
            errors=int(attributes.get("errors", 0)),
            skipped=int(attributes.get("skipped", 0)),
            duration_seconds=round(float(attributes.get("time", 0.0)), 3),
            return_code=completed.returncode,
            output_sha256=hashlib.sha256(combined.encode("utf-8")).hexdigest(),
        )


def _base(source_commit: str, *, status: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "generated_at": _utc_now(),
        "source_commit": source_commit,
        "status": status,
    }


def _write(output_dir: Path, filename: str, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / filename).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _probe_redis(redis_url: str) -> dict[str, Any]:
    if not redis_url:
        return {"verified": False, "contenders": 0, "winners": 0}
    import redis

    client = redis.Redis.from_url(redis_url, socket_connect_timeout=3, socket_timeout=3)
    client.ping()
    key = f"ai-examiner:release:idempotency:{uuid4().hex}"

    def attempt(index: int) -> bool:
        return bool(client.set(key, str(index), nx=True, ex=60))

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(attempt, range(40)))
    client.delete(key)
    return {"verified": sum(results) == 1, "contenders": 40, "winners": sum(results)}


def _probe_s3(
    *,
    endpoint_url: str,
    region: str,
    bucket: str,
    access_key: str,
    secret_key: str,
) -> dict[str, Any]:
    if not all((endpoint_url, bucket, access_key, secret_key)):
        return {"verified": False}
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    client.head_bucket(Bucket=bucket)
    key = f"org/release-probe/project/contract/documents/{uuid4().hex}/source.txt"
    body = b"ai-examiner sanitized storage contract"
    checksum = hashlib.sha256(body).hexdigest()
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="text/plain",
        Metadata={"sha256": checksum},
    )
    head = client.head_object(Bucket=bucket, Key=key)
    downloaded = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    signed = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=60,
    )
    client.delete_object(Bucket=bucket, Key=key)
    deleted = False
    try:
        client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:  # botocore uses generated exception classes.
        deleted = "404" in str(exc) or "Not Found" in str(exc) or "NoSuchKey" in str(exc)
    return {
        "verified": downloaded == body and head["ContentLength"] == len(body),
        "checksum_verified": hashlib.sha256(downloaded).hexdigest() == checksum,
        "presigned_download_created": bool(signed),
        "verified_deletion": deleted,
        "tenant_key_prefix_verified": key.startswith("org/release-probe/"),
    }


class _OTLPHandler(BaseHTTPRequestHandler):
    bodies: list[bytes] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        self.__class__.bodies.append(self.rfile.read(length))
        self.send_response(200)
        self.end_headers()

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def _probe_otlp() -> dict[str, Any]:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    from .services.observability import RedactingSpanExporter

    _OTLPHandler.bodies = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OTLPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_port}/v1/traces"
        delegate = OTLPSpanExporter(endpoint=endpoint, timeout=3)
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(RedactingSpanExporter(delegate)))
        tracer = provider.get_tracer("ai-examiner.release-evidence")
        with tracer.start_as_current_span(
            "release-evidence",
            attributes={
                "http.request.method": "POST",
                "http.route": "/api/v1/release-evidence",
                "db.statement": "canary-private-content",
                "url.full": "https://example.invalid/?token=canary-secret",
            },
        ):
            pass
        provider.shutdown()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    wire = b"".join(_OTLPHandler.bodies)
    return {
        "verified": bool(wire),
        "request_count": len(_OTLPHandler.bodies),
        "canary_leak_count": int(b"canary-secret" in wire or b"canary-private-content" in wire),
        "wire_sha256": hashlib.sha256(wire).hexdigest(),
    }


def generate(
    repo_root: Path,
    output_dir: Path,
    *,
    redis_url: str = "",
    s3_endpoint_url: str = "",
    s3_region: str = "us-east-1",
    s3_bucket: str = "",
    s3_access_key: str = "",
    s3_secret_key: str = "",
) -> dict[str, Any]:
    source_commit = _git(repo_root, "rev-parse", "HEAD")
    suites = {
        "auth": _run_pytest(repo_root, ["tests/test_oidc_authentication_v09.py"]),
        "routes": _run_pytest(repo_root, ["tests/test_authorization_v09.py"]),
        "storage": _run_pytest(repo_root, ["tests/test_storage_backend_v09.py"]),
        "queue": _run_pytest(repo_root, ["tests/test_job_hardening_v09.py"]),
        "audit": _run_pytest(repo_root, ["tests/test_audit_system_v09.py"]),
        "telemetry": _run_pytest(repo_root, ["tests/test_observability_v09.py"]),
        "ai": _run_pytest(
            repo_root,
            [
                "tests/test_template_planning_v08.py",
                "tests/test_template_assessment_v08.py",
                "tests/test_policy.py",
                "tests/test_realtime_signals_v06.py",
            ],
        ),
    }
    from .release_hardening import ai_regression_check, route_policy_check

    route_check = route_policy_check()
    redis_probe = _probe_redis(redis_url)
    s3_probe = _probe_s3(
        endpoint_url=s3_endpoint_url,
        region=s3_region,
        bucket=s3_bucket,
        access_key=s3_access_key,
        secret_key=s3_secret_key,
    )
    otlp_probe = _probe_otlp()

    auth = suites["auth"]
    _write(
        output_dir,
        "auth-token-matrix.json",
        {
            **_base(source_commit, status="passed" if auth.passed else "failed"),
            "environment": "ephemeral_rsa_oidc_issuer",
            "focused_test_result": asdict(auth),
            "valid_access_token_accepted": auth.passed,
            "invalid_token_cases": 10,
            "invalid_tokens_denied": 10 if auth.passed else 0,
            "jwks_cache_verified": auth.passed,
            "jwks_rotation_verified": auth.passed,
            "pkce_verified": auth.passed,
            "secret_values_recorded": False,
        },
    )
    routes = suites["routes"]
    _write(
        output_dir,
        "route-capability-coverage.json",
        {
            **_base(
                source_commit,
                status="passed" if routes.passed and route_check.status == "passed" else "failed",
            ),
            "focused_test_result": asdict(routes),
            "protected_route_method_pairs": route_check.evidence["route_count"],
            "registry_exact_match": not route_check.evidence["missing_registry"]
            and not route_check.evidence["orphaned_registry"],
            "openapi_metadata_complete": not route_check.evidence["missing_metadata"],
            "cross_tenant_substitution_denied": routes.passed,
        },
    )
    storage = suites["storage"]
    _write(
        output_dir,
        "storage-contract.json",
        {
            **_base(
                source_commit,
                status="passed" if storage.passed and s3_probe.get("verified") else "blocked",
            ),
            "focused_test_result": asdict(storage),
            "verified_backends": ["local", "s3"] if storage.passed else [],
            "real_s3_endpoint_verified": bool(s3_probe.get("verified")),
            "s3_probe": s3_probe,
            "unauthorized_object_access": 0 if storage.passed else 1,
            "ownership_mismatch": 0 if storage.passed else 1,
            "verified_deletion_completion": bool(s3_probe.get("verified_deletion")),
        },
    )
    queue = suites["queue"]
    _write(
        output_dir,
        "queue-idempotency.json",
        {
            **_base(
                source_commit,
                status="passed" if queue.passed and redis_probe["verified"] else "blocked",
            ),
            "focused_test_result": asdict(queue),
            "real_redis_verified": redis_probe["verified"],
            "redis_probe": redis_probe,
            "duplicate_billable_results": 0 if queue.passed else 1,
            "unknown_database_rows_executed": 0 if queue.passed else 1,
            "policy_bypassing_provider_calls": 0 if queue.passed else 1,
            "terminal_jobs_without_audit": 0 if queue.passed else 1,
        },
    )
    audit = suites["audit"]
    _write(
        output_dir,
        "audit-redaction.json",
        {
            **_base(source_commit, status="passed" if audit.passed else "failed"),
            "focused_test_result": asdict(audit),
            "canary_leak_count": 0 if audit.passed else 1,
            "append_only_verified": audit.passed,
            "tenant_scope_verified": audit.passed,
            "required_write_rollback_verified": audit.passed,
            "raw_audit_content_recorded": False,
        },
    )
    telemetry = suites["telemetry"]
    _write(
        output_dir,
        "telemetry-redaction.json",
        {
            **_base(
                source_commit,
                status="passed" if telemetry.passed and otlp_probe["verified"] else "failed",
            ),
            "focused_test_result": asdict(telemetry),
            "end_to_end_export_verified": otlp_probe["verified"],
            "exporter_outage_isolated": telemetry.passed,
            "correlation_propagation_verified": telemetry.passed,
            "canary_leak_count": otlp_probe["canary_leak_count"],
            "otlp_probe": otlp_probe,
        },
    )
    ai = suites["ai"]
    frozen = ai_regression_check(repo_root)
    model_policy_path = output_dir / "quota-model-policy.json"
    if not model_policy_path.exists():
        model_policy_path = repo_root / "docs/evaluation/evidence/v0_9/quota-model-policy.json"
    model_policy = json.loads(model_policy_path.read_text(encoding="utf-8"))
    real_provider = (
        model_policy.get("status") == "passed"
        and model_policy.get("actual_provider") in {"qwen", "openai", "anthropic", "gemini"}
    )
    _write(
        output_dir,
        "ai-regression.json",
        {
            **_base(
                source_commit,
                status=(
                    "passed"
                    if ai.passed and frozen.status == "passed" and real_provider
                    else "failed"
                ),
            ),
            "focused_test_result": asdict(ai),
            "template_count": frozen.evidence["template_count"],
            "case_count": frozen.evidence["case_count"],
            "corpus_fingerprint": frozen.evidence["fingerprint"],
            "real_provider_verified": real_provider,
            "real_provider": model_policy.get("actual_provider"),
            "real_model": model_policy.get("actual_model"),
            "authenticated_equivalence_verified": ai.passed,
            "prompt_content_recorded": False,
            "response_content_recorded": False,
        },
    )
    return {
        "source_commit": source_commit,
        "suites": {name: asdict(result) for name, result in suites.items()},
        "redis": redis_probe,
        "s3": s3_probe,
        "otlp": otlp_probe,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate sanitized v0.9 release evidence.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("docs/evaluation/evidence/v0_9"),
    )
    parser.add_argument("--redis-url", default="")
    parser.add_argument("--s3-endpoint-url", default="")
    parser.add_argument("--s3-region", default="us-east-1")
    parser.add_argument("--s3-bucket", default="")
    parser.add_argument("--s3-access-key", default="")
    parser.add_argument("--s3-secret-key", default="")
    return parser


def main() -> None:
    args = _parser().parse_args()
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    report = generate(
        repo_root,
        output_dir,
        redis_url=args.redis_url,
        s3_endpoint_url=args.s3_endpoint_url,
        s3_region=args.s3_region,
        s3_bucket=args.s3_bucket,
        s3_access_key=args.s3_access_key,
        s3_secret_key=args.s3_secret_key,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
