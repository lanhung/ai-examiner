#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time

import httpx

MATERIAL = """The system uses retrieval-grounded generation. The evaluation compares
factual consistency, evidence coverage, latency, and cost. The main limitation is
that the current study uses one domain and cannot establish cross-domain
generalization. A follow-up study should use independent datasets and blinded
expert scoring."""


def verify(base_url: str, *, profile: str, timeout_seconds: int) -> dict[str, object]:
    started = time.perf_counter()
    with httpx.Client(follow_redirects=True, timeout=40, trust_env=False) as client:
        login = client.get(f"{base_url}/api/v1/auth/login")
        login.raise_for_status()
        me_response = client.get(f"{base_url}/api/v1/me")
        me_response.raise_for_status()
        me = me_response.json()
        organizations = me.get("organizations") or []
        if not organizations:
            raise RuntimeError("OIDC principal has no active organization")
        organization_id = organizations[0]["id"]
        headers = {"X-AI-Examiner-Organization": organization_id}

        project_response = client.post(
            f"{base_url}/api/projects",
            headers=headers,
            json={"name": "Release workbench tenant smoke"},
        )
        project_response.raise_for_status()
        project_id = project_response.json()["id"]

        upload_response = client.post(
            f"{base_url}/api/projects/{project_id}/documents",
            headers=headers,
            files={"file": ("release-workbench.txt", MATERIAL, "text/plain")},
        )
        upload_response.raise_for_status()
        document_id = upload_response.json()["id"]

        listing_response = client.get(
            f"{base_url}/api/projects/{project_id}/documents",
            headers=headers,
        )
        listing_response.raise_for_status()
        documents = listing_response.json()
        if not any(item["id"] == document_id for item in documents):
            raise RuntimeError("Tenant-scoped document was not visible after upload")

        enqueue_started = time.perf_counter()
        enqueue_response = client.post(
            f"{base_url}/api/projects/{project_id}/blueprints/async",
            headers={
                **headers,
                "Idempotency-Key": f"public-workbench-{project_id}",
            },
            json={
                "document_id": document_id,
                "profile": profile,
                "mode": "defense",
            },
        )
        enqueue_response.raise_for_status()
        enqueue_ms = round((time.perf_counter() - enqueue_started) * 1000, 1)
        job_id = enqueue_response.json()["id"]

        deadline = time.monotonic() + timeout_seconds
        terminal: dict[str, object] = {}
        while time.monotonic() < deadline:
            job_response = client.get(
                f"{base_url}/api/jobs/{job_id}",
                headers=headers,
            )
            job_response.raise_for_status()
            terminal = job_response.json()
            if terminal.get("status") in {
                "completed",
                "failed",
                "cancelled",
                "dead_letter",
            }:
                break
            time.sleep(3)
        else:
            raise RuntimeError("Blueprint job did not reach a terminal state")

        if terminal.get("status") != "completed":
            raise RuntimeError(
                f"Blueprint job ended as {terminal.get('status')}: {terminal.get('error')}"
            )
        result = terminal.get("result") or {}
        blueprint = result.get("blueprint") or {}
        questions = (blueprint.get("data") or {}).get("questions") or []
        if not questions:
            raise RuntimeError("Completed blueprint did not contain questions")
        grounding = blueprint.get("grounding") or {}
        if not grounding.get("passed"):
            raise RuntimeError(
                f"Completed blueprint failed grounding: {grounding.get('issues')}"
            )

        return {
            "status": "passed",
            "authentication_method": me.get("authentication", {}).get("method"),
            "organization_count": len(organizations),
            "document_visible": True,
            "enqueue_ms": enqueue_ms,
            "terminal_seconds": round(time.perf_counter() - started, 1),
            "provider": blueprint.get("provider"),
            "model": blueprint.get("model"),
            "question_count": len(questions),
            "grounding_passed": True,
            "project_id": project_id,
            "document_id": document_id,
            "job_id": job_id,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--profile", default="qwen:qwen-plus")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    result = verify(
        args.base_url.rstrip("/"),
        profile=args.profile,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
