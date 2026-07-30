#!/usr/bin/env python3
"""Run destructive v0.9 HTTP acceptance against an isolated staging database."""

from __future__ import annotations

import argparse
import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx


class AcceptanceRun:
    def __init__(
        self,
        *,
        base_url: str,
        organization_id: str,
        identities: dict[str, str],
        trust_env: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.organization_id = organization_id
        self.identities = identities
        self.results: list[dict[str, Any]] = []
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=180,
            trust_env=trust_env,
        )

    def close(self) -> None:
        self.client.close()

    def headers(self, actor: str = "owner", **extra: str) -> dict[str, str]:
        return {
            "X-AI-Examiner-Organization": self.organization_id,
            "X-AI-Examiner-Principal": self.identities[actor],
            **extra,
        }

    def check(
        self,
        name: str,
        method: str,
        path: str,
        *,
        expected: int | tuple[int, ...] = 200,
        actor: str = "owner",
        headers_override: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        started = time.perf_counter()
        response = self.client.request(
            method,
            path,
            headers=(
                self.headers(actor)
                if headers_override is None
                else headers_override
            ),
            **kwargs,
        )
        expected_values = (expected,) if isinstance(expected, int) else expected
        passed = response.status_code in expected_values
        result = {
            "name": name,
            "status": "passed" if passed else "failed",
            "http_status": response.status_code,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
        self.results.append(result)
        if not passed:
            raise AssertionError(
                f"{name}: expected {expected_values}, got {response.status_code}: "
                f"{response.text[:500]}"
            )
        return response

    def assert_condition(self, name: str, condition: bool, detail: str) -> None:
        if not condition:
            self.results.append(
                {
                    "name": name,
                    "status": "failed",
                    "http_status": None,
                    "latency_ms": 0,
                }
            )
            raise AssertionError(f"{name}: {detail}")

    def wait_for_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 240,
        poll_seconds: float = 0.5,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        deadline = started + timeout_seconds
        last_payload: dict[str, Any] = {}
        while time.perf_counter() < deadline:
            response = self.client.get(
                f"/api/jobs/{job_id}",
                headers=self.headers(),
            )
            if response.status_code != 200:
                self.results.append(
                    {
                        "name": "real_qwen_planner_async_completion",
                        "status": "failed",
                        "http_status": response.status_code,
                        "latency_ms": round((time.perf_counter() - started) * 1000),
                    }
                )
                raise AssertionError(
                    "real_qwen_planner_async_completion: "
                    f"job poll returned {response.status_code}: "
                    f"{response.text[:500]}"
                )
            last_payload = response.json()
            if last_payload.get("status") in {
                "completed",
                "failed",
                "cancelled",
                "dead_letter",
            }:
                break
            time.sleep(poll_seconds)
        else:
            last_payload = {"status": "timeout", "id": job_id}

        passed = last_payload.get("status") == "completed"
        self.results.append(
            {
                "name": "real_qwen_planner_async_completion",
                "status": "passed" if passed else "failed",
                "http_status": 200 if passed else None,
                "latency_ms": round((time.perf_counter() - started) * 1000),
            }
        )
        if not passed:
            raise AssertionError(
                "real_qwen_planner_async_completion: "
                f"unexpected terminal job: {last_payload}"
            )
        return last_payload


def run_acceptance(run: AcceptanceRun) -> None:
    org = run.organization_id
    ids = run.identities

    run.check("health", "GET", "/health", headers_override={})
    ready = run.check("readiness", "GET", "/ready", headers_override={}).json()
    run.assert_condition("readiness_state", ready["status"] == "ready", str(ready))
    run.check("enterprise_ui", "GET", "/enterprise", headers_override={})
    run.check(
        "enterprise_js",
        "GET",
        "/static/enterprise.js?v=0.9.0-wp13",
        headers_override={},
    )
    run.check(
        "enterprise_css",
        "GET",
        "/static/enterprise.css?v=0.9.0-wp13",
        headers_override={},
    )
    run.check(
        "unauthenticated_capability_denial",
        "GET",
        "/api/v1/system/capabilities",
        headers_override={},
        expected=401,
    )
    context = run.check("owner_context", "GET", "/api/v1/context").json()
    run.assert_condition(
        "owner_context_role",
        context["role"] == "owner",
        f"unexpected context: {context}",
    )
    run.assert_condition(
        "observe_only_mode_visible",
        context["authorization_enforced"] is False
        and context["mode"] == "observe_only",
        f"unexpected context mode: {context}",
    )
    capabilities = run.check(
        "capability_registry",
        "GET",
        "/api/v1/system/capabilities",
    ).json()
    run.assert_condition(
        "capability_registry_populated",
        len(capabilities["capabilities"]) >= 10,
        "capability registry is unexpectedly small",
    )
    run.check("organization_read", "GET", f"/api/v1/organizations/{org}")
    run.check(
        "cross_membership_denial",
        "GET",
        f"/api/v1/organizations/{org}/memberships",
        actor="outsider",
        expected=404,
    )
    memberships = run.check(
        "membership_list",
        "GET",
        f"/api/v1/organizations/{org}/memberships",
    ).json()
    run.assert_condition(
        "owner_memberships_present",
        len(memberships["items"]) >= 2,
        "bootstrap owners are missing",
    )
    created = run.check(
        "membership_create",
        "POST",
        f"/api/v1/organizations/{org}/memberships",
        expected=201,
        json={
            "principal_id": ids["candidate"],
            "role": "reviewer",
            "status": "active",
        },
    )
    membership = created.json()
    patched = run.check(
        "membership_update",
        "PATCH",
        f"/api/v1/organizations/{org}/memberships/{membership['id']}",
        headers_override=run.headers(
            "owner",
            **{"If-Match": created.headers["etag"]},
        ),
        json={"role": "auditor"},
    )
    run.assert_condition(
        "membership_role_updated",
        patched.json()["role"] == "auditor",
        str(patched.json()),
    )
    run.check(
        "membership_revoke",
        "DELETE",
        f"/api/v1/organizations/{org}/memberships/{membership['id']}",
        headers_override=run.headers(
            "owner",
            **{"If-Match": patched.headers["etag"]},
        ),
    )

    run.check(
        "model_policy_read",
        "GET",
        f"/api/v1/organizations/{org}/model-policy",
    )
    policy = run.check(
        "model_policy_update",
        "PUT",
        f"/api/v1/organizations/{org}/model-policy",
        json={
            "allowed_profiles": [
                {
                    "provider": "qwen",
                    "model_pattern": "qwen-plus",
                    "tasks": [
                        "planner",
                        "analyzer",
                        "interviewer",
                        "reporter",
                    ],
                }
            ],
            "fallback_profiles": [],
            "external_provider_max_classification": "confidential",
            "fallback_mode": "deny",
            "provider_retention_allowed": False,
        },
    ).json()
    run.assert_condition(
        "qwen_policy_active",
        policy["allowed_profiles"][0]["provider"] == "qwen",
        str(policy),
    )
    quota = run.check(
        "quota_update",
        "PUT",
        f"/api/v1/organizations/{org}/quota",
        json={
            "quota_mode": "hard",
            "monthly_budget_usd": 100,
            "per_session_budget_usd": 10,
            "per_request_budget_usd": 2,
            "soft_limit_ratio": 0.8,
            "organization_requests_per_minute": 120,
            "principal_requests_per_minute": 30,
            "organization_tokens_per_minute": 500000,
            "max_concurrent_calls": 3,
        },
    ).json()
    run.assert_condition(
        "hard_quota_active",
        quota["quota_mode"] == "hard",
        str(quota),
    )

    project = run.check(
        "project_create",
        "POST",
        "/api/projects",
        expected=201,
        json={
            "name": "v0.9 acceptance evidence project",
            "domain": "research_defense",
            "language": "zh-CN",
            "data_classification": "confidential",
        },
    ).json()
    deletion_project = run.check(
        "deletion_project_create",
        "POST",
        "/api/projects",
        expected=201,
        json={
            "name": "v0.9 acceptance deletion project",
            "domain": "research_defense",
            "language": "zh-CN",
            "data_classification": "internal",
        },
    ).json()
    source = (
        "# Adaptive Examiner\n\n"
        "The system selects follow-up questions from evidence, current mastery, "
        "misconceptions, and remaining time. A strong answer must distinguish "
        "evidence from confidence and explain why the next question reduces "
        "uncertainty.\n"
    )
    document = run.check(
        "document_upload",
        "POST",
        f"/api/projects/{project['id']}/documents",
        expected=201,
        files={
            "file": (
                "acceptance.md",
                source.encode(),
                "text/markdown",
            )
        },
    ).json()
    run.check(
        "authorized_document_download",
        "GET",
        f"/api/v1/documents/{document['id']}/file",
    )
    evidence = run.check(
        "evidence_list",
        "GET",
        f"/api/documents/{document['id']}/evidence",
    ).json()
    run.assert_condition(
        "evidence_created",
        len(evidence["assets"]) >= 1,
        "the uploaded document has no evidence assets",
    )
    run.check(
        "authorized_evidence_download",
        "GET",
        f"/api/v1/evidence/{evidence['assets'][0]['id']}/file",
    )

    blueprint_payload = {
        "document_id": document["id"],
        "profile": "qwen:qwen-plus",
        "mode": "defense",
    }
    blueprint_job = run.check(
        "real_qwen_planner_async_enqueue",
        "POST",
        f"/api/projects/{project['id']}/blueprints/async",
        expected=202,
        headers_override=run.headers(
            "owner",
            **{"Idempotency-Key": "acceptance-blueprint-v09"},
        ),
        json=blueprint_payload,
    ).json()
    run.check(
        "health_during_async_blueprint",
        "GET",
        "/health",
        headers_override={},
    )
    completed_blueprint_job = run.wait_for_job(blueprint_job["id"])
    blueprint = completed_blueprint_job["result"]["blueprint"]
    duplicate_blueprint_job = run.check(
        "blueprint_async_idempotency",
        "POST",
        f"/api/projects/{project['id']}/blueprints/async",
        expected=202,
        headers_override=run.headers(
            "owner",
            **{"Idempotency-Key": "acceptance-blueprint-v09"},
        ),
        json=blueprint_payload,
    ).json()
    run.assert_condition(
        "blueprint_async_job_reused",
        duplicate_blueprint_job["id"] == blueprint_job["id"],
        (
            "duplicate async blueprint request created another job: "
            f"{blueprint_job['id']} != {duplicate_blueprint_job['id']}"
        ),
    )
    blueprint_data = blueprint.get("data") or {}
    run.assert_condition(
        "qwen_questions_created",
        bool(
            blueprint.get("questions")
            or blueprint.get("question_plan")
            or blueprint_data.get("questions")
            or blueprint_data.get("question_plan")
        ),
        f"no questions in blueprint: {list(blueprint)}",
    )
    usage = run.check(
        "usage_dashboard",
        "GET",
        f"/api/v1/organizations/{org}/usage",
    ).json()
    run.assert_condition(
        "usage_ledger_populated",
        usage.get("completed_calls", 0) >= 1,
        str(usage),
    )
    usage_export = run.check(
        "usage_export",
        "GET",
        f"/api/v1/organizations/{org}/usage/export",
    )
    run.assert_condition(
        "usage_export_format",
        usage_export.headers["content-type"].startswith(
            "application/x-ndjson"
        ),
        usage_export.headers["content-type"],
    )

    retention = run.check(
        "retention_policy_update",
        "PUT",
        f"/api/v1/organizations/{org}/retention-policy",
        json={
            "policy_mode": "monitor",
            "project_days": 730,
            "session_days": 365,
            "document_days": 365,
            "learner_memory_days": 365,
            "export_ttl_hours": 24,
            "deletion_grace_days": 0,
        },
    ).json()
    run.assert_condition(
        "retention_monitor_active",
        retention["policy_mode"] == "monitor",
        str(retention),
    )
    export = run.check(
        "organization_export",
        "POST",
        f"/api/v1/organizations/{org}/exports",
        expected=202,
        headers_override=run.headers(
            "owner",
            **{"Idempotency-Key": "acceptance-export-v09"},
        ),
        json={
            "scope_type": "project",
            "scope_id": project["id"],
            "include_objects": True,
        },
    ).json()
    run.assert_condition(
        "organization_export_completed",
        export["status"] == "completed" and bool(export["manifest_digest"]),
        str(export),
    )
    downloaded = run.check(
        "organization_export_download",
        "GET",
        export["download_url"],
    )
    run.assert_condition(
        "organization_export_zip_valid",
        zipfile.ZipFile(io.BytesIO(downloaded.content)).testzip() is None,
        "export ZIP integrity failed",
    )

    hold = run.check(
        "legal_hold_create",
        "POST",
        f"/api/v1/organizations/{org}/legal-holds",
        expected=201,
        actor="reviewer",
        json={
            "scope_type": "project",
            "scope_id": deletion_project["id"],
            "reason": "Acceptance test preservation hold",
        },
    ).json()
    request = run.check(
        "deletion_request_create",
        "POST",
        f"/api/v1/organizations/{org}/data-subject-requests",
        expected=202,
        headers_override=run.headers(
            "owner",
            **{"Idempotency-Key": "acceptance-delete-v09"},
        ),
        json={
            "request_type": "delete",
            "target_type": "project",
            "target_id": deletion_project["id"],
            "reason": "Acceptance test verified deletion",
        },
    ).json()
    run.check(
        "dual_control_denial",
        "POST",
        f"/api/v1/data-subject-requests/{request['id']}/approve",
        expected=409,
        headers_override=run.headers(
            "owner",
            **{"Idempotency-Key": "acceptance-self-approval"},
        ),
        json={
            "decision": "approved",
            "reason": "Self approval must be rejected",
        },
    )
    blocked = run.check(
        "legal_hold_blocks_deletion",
        "POST",
        f"/api/v1/data-subject-requests/{request['id']}/approve",
        actor="reviewer",
        headers_override=run.headers(
            "reviewer",
            **{"Idempotency-Key": "acceptance-review-approval"},
        ),
        json={
            "decision": "approved",
            "reason": "Independent acceptance reviewer approved deletion",
        },
    ).json()
    run.assert_condition(
        "deletion_blocked_by_hold",
        blocked["status"] == "blocked",
        str(blocked),
    )
    run.check(
        "legal_hold_release",
        "POST",
        f"/api/v1/legal-holds/{hold['id']}/release",
        actor="reviewer",
        json={"reason": "Acceptance preservation check completed"},
    )
    completed = run.check(
        "deletion_retry",
        "POST",
        f"/api/v1/data-subject-requests/{request['id']}/retry",
        actor="reviewer",
        headers_override=run.headers(
            "reviewer",
            **{"Idempotency-Key": "acceptance-delete-retry"},
        ),
    ).json()
    run.assert_condition(
        "verified_deletion_completed",
        completed["status"] == "completed"
        and completed["verification"]["verified"] is True,
        str(completed),
    )

    review_case = run.check(
        "review_case_create",
        "POST",
        f"/api/v1/organizations/{org}/review-cases",
        expected=201,
        json={
            "case_type": "assessment_appeal",
            "resource_type": "blueprint",
            "resource_id": blueprint["id"],
            "title": "Acceptance human review",
            "summary": "Verify that final decisions remain human controlled.",
            "evidence": [{"type": "blueprint", "id": blueprint["id"]}],
        },
    ).json()
    run.check(
        "review_case_assign",
        "POST",
        f"/api/v1/review-cases/{review_case['id']}/assign",
        json={"principal_id": ids["reviewer"]},
    )
    decided = run.check(
        "review_case_decision",
        "POST",
        f"/api/v1/review-cases/{review_case['id']}/decisions",
        actor="reviewer",
        json={
            "decision": "upheld",
            "reason": "Human reviewer confirmed the evidence chain",
        },
    ).json()
    run.assert_condition(
        "human_decision_recorded",
        decided["final_decision"] == "upheld",
        str(decided),
    )
    appealed = run.check(
        "review_case_appeal",
        "POST",
        f"/api/v1/review-cases/{review_case['id']}/appeals",
        json={
            "reason": "Acceptance appeal verifies append-only review history",
            "evidence": [{"type": "note", "value": "acceptance"}],
        },
    ).json()
    run.assert_condition(
        "appeal_recorded",
        appealed["status"] == "appealed",
        str(appealed),
    )

    jobs = run.check(
        "job_list",
        "GET",
        f"/api/v1/organizations/{org}/jobs",
    ).json()
    run.assert_condition(
        "job_history_present",
        len(jobs) >= 1,
        "job history is empty",
    )
    run.check(
        "job_recovery",
        "POST",
        f"/api/v1/organizations/{org}/jobs/recover",
        expected=202,
    )
    audit = run.check(
        "audit_list",
        "GET",
        f"/api/v1/organizations/{org}/audit-events",
    ).json()
    run.assert_condition(
        "audit_history_present",
        len(audit["items"]) >= 5,
        "audit history is unexpectedly small",
    )
    audit_export = run.check(
        "audit_export",
        "GET",
        f"/api/v1/organizations/{org}/audit-events/export",
    )
    run.assert_condition(
        "audit_export_format",
        audit_export.headers["content-type"].startswith(
            "application/x-ndjson"
        ),
        audit_export.headers["content-type"],
    )
    run.check(
        "template_health",
        "GET",
        "/api/templates/health",
        headers_override={},
    )
    voice = run.check(
        "voice_config",
        "GET",
        "/api/voice/config",
        headers_override={},
    ).json()
    run.assert_condition(
        "voice_provider_configured",
        voice["ready"] is True,
        str(voice),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run destructive v0.9 acceptance against an isolated staging "
            "database. Never point this at production data."
        )
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--organization-id", required=True)
    parser.add_argument("--identities", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--trust-env",
        action="store_true",
        help=(
            "Honor HTTP(S)_PROXY and NO_PROXY from the process environment. "
            "Disabled by default so localhost and private staging addresses "
            "cannot be redirected through a system proxy."
        ),
    )
    args = parser.parse_args()

    run = AcceptanceRun(
        base_url=args.base_url,
        organization_id=args.organization_id,
        identities=json.loads(args.identities.read_text(encoding="utf-8")),
        trust_env=args.trust_env,
    )
    status = "passed"
    error: str | None = None
    try:
        run_acceptance(run)
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
        if not run.results or run.results[-1]["status"] != "failed":
            run.results.append(
                {
                    "name": "unhandled_assertion",
                    "status": "failed",
                    "http_status": None,
                    "latency_ms": 0,
                }
            )
    finally:
        run.close()

    report = {
        "schema_version": "1.0",
        "status": status,
        "test_count": len(run.results),
        "passed": sum(item["status"] == "passed" for item in run.results),
        "failed": sum(item["status"] == "failed" for item in run.results),
        "error": error,
        "results": run.results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
