"""Bounded HTTP capacity probe with isolated synthetic identities (not wx.login).

Run explicitly on the Linux deployment. Never print credentials or response bodies.
The API keeps its normal authentication, RLS, audit and model governance enabled.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import secrets
import sys
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

PAPER = """Synthetic paper: independent evaluation of a retrieval-assisted question system.
Abstract: We test whether retrieval improves evidence citation, not general intelligence.
Method: 120 synthetic questions are split into 80 development and 40 held-out questions.
The baseline and retrieval system use the same language model, prompts and decoding settings.
Development questions tune retrieval parameters; held-out answers never tune the model.
Two reviewers independently judge whether each citation supports the claim. Disagreements
are discussed, and both original judgments are retained. The unit of analysis is a question.
Results: baseline supports 26 of 40 citations; retrieval supports 32 of 40 citations.
The retrieval system adds 180 ms median latency in this small offline experiment.
An ablation removes retrieval while retaining the same generation configuration.
Limitations: one synthetic domain, small held-out set, no confidence interval and no causal
claim about educational outcomes. Future work includes independent domains and larger samples.
Conclusion: these results suggest better citation support on this test set, not universal
superiority. All numbers and content in this document are synthetic test fixtures.
"""
QUESTION = {
    "id": "capacity-q1", "text": "Why must the held-out set remain independent?",
    "type": "method", "difficulty": 2,
    "expected_points": ["Avoid tuning on the test set", "Measure unseen performance",
                        "Small samples limit generalization"],
    "source_excerpt": "held-out answers never tune the model", "source_page": 1,
    "followups": [],
}
ANSWER = ("The held-out questions must not tune retrieval parameters, because that leaks "
          "test information. An independent test estimates unseen performance. Forty "
          "synthetic questions remain a small sample and cannot prove generalization.")


def summarize(rows: list[dict], elapsed: float) -> dict:
    ordered = sorted(row["seconds"] for row in rows)

    def percentile(q):
        return round(ordered[max(0, math.ceil(len(ordered) * q) - 1)], 3) if ordered else None

    statuses = Counter(str(row["status"]) for row in rows)
    return {
        "requests": len(rows), "statuses": dict(statuses),
        "successful": sum(200 <= row["status"] < 300 for row in rows),
        "semantic_failures": sum(row.get("semantic_ok") is False for row in rows),
        "p50_seconds": percentile(.50), "p95_seconds": percentile(.95),
        "p99_seconds": percentile(.99), "max_seconds": max(ordered, default=0),
        "elapsed_seconds": round(elapsed, 3),
        "requests_per_second": round(len(rows) / elapsed, 3) if elapsed > 0 else 0,
    }


def resources() -> dict:
    result = {"monotonic": time.monotonic()}
    for name in ("cpu.max", "memory.max", "memory.current", "cpu.stat"):
        path = Path("/sys/fs/cgroup") / name
        if path.exists():
            result[name] = path.read_text().strip()
    return result


class Probe:
    def __init__(self, args):
        self.args = args
        self.run_id = "capacity-" + uuid4().hex[:12]
        self.org = str(uuid4())
        self.users = []
        self.tokens = []
        self.attempts = []
        self.jobs = []
        self.fixture_committed = False
        self.report = {"run_id": self.run_id, "organization_id": self.org,
                       "limits": {"users": args.users, "blueprint_jobs": 3 if args.real_models else 0,
                                  "real_answer_submissions": 3 if args.real_models else 0},
                       "wechat_login_tested": False, "phases": [], "resources": [resources()]}

    def save(self):
        self.args.output.write_text(json.dumps(self.report, indent=2, ensure_ascii=False), encoding="utf-8")

    def provision(self):
        from sqlalchemy import text

        from ai_examiner.config import get_settings
        from ai_examiner.db import SessionLocal
        from ai_examiner.models import (
            BrowserAuthSession,
            Document,
            ExamPaper,
            Organization,
            OrganizationMembership,
            Principal,
            Project,
            PublishedExam,
            SchoolAttempt,
            utcnow,
        )
        from ai_examiner.services.model_governance import ensure_model_policy, update_model_policy
        from ai_examiner.services.tenancy import set_tenant_context
        from ai_examiner.services.wechat import wechat_issuer
        settings = get_settings()
        if not settings.model_governance_enabled or settings.auth_mode != "oidc":
            raise RuntimeError("Normal authentication and model governance are required")
        with SessionLocal() as db:
            role = db.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
            if role.rolsuper or role.rolbypassrls:
                raise RuntimeError("Use the ordinary runtime database role, not a bypass role")
            set_tenant_context(db, organization_id=self.org, principal_id=None)
            db.add(Organization(id=self.org, slug=self.run_id,
                                display_name="[SYNTHETIC] concurrency acceptance"))
            db.flush()
            now = utcnow()
            for i in range(self.args.users + 1):
                principal = Principal(id=str(uuid4()), issuer=wechat_issuer(settings),
                                      subject=f"synthetic:{self.run_id}:{i}", status="active",
                                      display_name=f"[SYNTHETIC] capacity {i}")
                db.add(principal)
                db.flush()
                self.users.append(principal.id)
                token = "wxmp_" + secrets.token_urlsafe(48)
                self.tokens.append(token)
                db.add(BrowserAuthSession(principal_id=principal.id,
                    session_token_hash=hashlib.sha256(token.encode()).hexdigest(), scopes_json=[],
                    auth_time=now, expires_at=now + timedelta(minutes=30),
                    created_at=now, last_seen_at=now))
                db.add(OrganizationMembership(organization_id=self.org, principal_id=principal.id,
                                              role="examiner" if i == 0 else "learner"))
            set_tenant_context(db, organization_id=self.org, principal_id=self.users[0])
            policy = ensure_model_policy(db, self.org, principal_id=self.users[0])
            update_model_policy(db, policy, principal_id=self.users[0], values={
                "allowed_profiles_json": [{"provider": "qwen", "model_pattern": "qwen-plus", "tasks": ["*"]}],
                "fallback_profiles_json": [], "monthly_budget_usd": 2.0,
            })
            self.report["model_limits"] = {"max_concurrent_calls": policy.max_concurrent_calls,
                "organization_requests_per_minute": policy.organization_requests_per_minute,
                "monthly_budget_usd": policy.monthly_budget_usd}
            project = Project(id=str(uuid4()), organization_id=self.org,
                              name=f"[SYNTHETIC] {self.run_id}", data_classification="public")
            db.add(project)
            db.flush()
            doc = Document(id=str(uuid4()), organization_id=self.org, project_id=project.id,
                           filename="synthetic-capacity-paper.txt", content_type="text/plain",
                           content_text=PAPER, page_map=[{"page": 1, "text": PAPER}], char_count=len(PAPER))
            db.add(doc)
            db.flush()
            exam = PublishedExam(id=str(uuid4()), organization_id=self.org, teacher_id=self.users[0],
                                 publish_key=str(uuid4()), request_digest="0" * 64,
                                 title=f"[SYNTHETIC DO NOT JOIN] {self.run_id}", teacher_name="Capacity fixture",
                                 material_name=doc.filename, material_text=PAPER, question_count=1,
                                 status="closed")
            db.add(exam)
            db.flush()
            db.add(ExamPaper(exam_id=exam.id, organization_id=self.org, project_id=project.id,
                             document_id=doc.id, blueprint_id=str(uuid4()), questions=[QUESTION],
                             profile="qwen:qwen-plus"))
            for user in self.users[1:]:
                attempt = SchoolAttempt(id=str(uuid4()), organization_id=self.org, exam_id=exam.id,
                    teacher_id=self.users[0], student_id=user, student_name="Synthetic capacity student")
                db.add(attempt)
                self.attempts.append(attempt.id)
            db.commit()
            self.fixture_committed = True
            self.project, self.document, self.exam = project.id, doc.id, exam.id
            self.report["fixture"] = {"project_id": self.project, "document_id": self.document,
                                      "exam_id": self.exam, "exam_status": "closed"}
        self.save()

    def headers(self, index):
        return {"Authorization": "Bearer " + self.tokens[index],
                "X-AI-Examiner-Organization": self.org}

    async def request(self, client, method, path, index, *, payload=None, expected_id=None, timeout=20):
        import httpx
        start = time.monotonic()
        row = {"status": 0, "seconds": 0, "semantic_ok": None}
        data = None
        try:
            response = await client.request(method, path, headers=self.headers(index), json=payload, timeout=timeout)
            row["status"] = response.status_code
            if response.is_success:
                try:
                    data = response.json()
                    if expected_id:
                        row["semantic_ok"] = data.get("id") == expected_id
                except ValueError:
                    row["semantic_ok"] = False
        except httpx.HTTPError as exc:
            row["error_type"] = type(exc).__name__
        row["seconds"] = round(time.monotonic() - start, 4)
        return row, data

    async def health(self, client):
        result = await client.get("/health", timeout=5)
        if result.status_code != 200:
            raise RuntimeError("Health check failed; no more load will be submitted")

    async def reads(self, client, users, rounds=3, label="read"):
        rows = []
        start = time.monotonic()

        async def visit(i):
            paths = [("/api/v1/school/me", None), ("/api/v1/school/exams", None),
                     (f"/api/v1/school/attempts/{self.attempts[i-1]}", self.attempts[i-1])]
            for path, expected in paths:
                row, _ = await self.request(client, "GET", path, i, expected_id=expected)
                rows.append(row)

        for _ in range(rounds):
            await self.health(client)
            await asyncio.gather(*(visit(i) for i in range(1, users + 1)))
            bad = sum(r["status"] == 0 or r["status"] >= 500 or r["semantic_ok"] is False for r in rows)
            if bad or max(r["seconds"] for r in rows) > 15:
                break
            await asyncio.sleep(1)
        summary = {"name": label, "users": users, **summarize(rows, time.monotonic() - start)}
        self.report["phases"].append(summary)
        self.report["resources"].append(resources())
        self.save()
        print(json.dumps(summary), flush=True)
        if summary["successful"] != summary["requests"] or summary["semantic_failures"] or summary["max_seconds"] > 15:
            raise RuntimeError("Read circuit breaker: stop escalating load")

    async def paid(self, client):
        start = time.monotonic()
        graded = await asyncio.gather(*(self.request(client, "POST",
            f"/api/v1/school/attempts/{self.attempts[i-1]}/answers", i, timeout=65,
            payload={"request_id": str(uuid4()), "position": 0, "answer": ANSWER}) for i in range(1, 4)))
        self.report["phases"].append({"name": "qwen_plus_answers", "users": 3,
            **summarize([x[0] for x in graded], time.monotonic() - start),
            "result_statuses": [x[1].get("status") if isinstance(x[1], dict) else None for x in graded]})
        self.save()
        await self.health(client)
        if any(row["status"] != 200 for row, _ in graded):
            raise RuntimeError("Real answer phase failed; skip further paid generation")
        start = time.monotonic()
        # Exactly three jobs, distinct idempotency keys. Never auto-resubmit a timed-out POST.
        for i in range(3):
            response = await client.post(f"/api/projects/{self.project}/blueprints/async",
                headers={**self.headers(0), "Idempotency-Key": f"{self.run_id}-blueprint-{i}"},
                json={"document_id": self.document, "profile": "qwen:qwen-plus", "mode": "defense"}, timeout=20)
            if response.status_code != 202:
                self.report["blueprint_submit_status"] = response.status_code
                raise RuntimeError("Blueprint admission failed; no retry")
            self.jobs.append(response.json()["id"])
            self.report["jobs"] = self.jobs[:]
            self.save()
        await self.reads(client, self.args.users, rounds=2, label="read_while_blueprint_running")
        deadline = time.monotonic() + 600
        states = {}
        while time.monotonic() < deadline:
            for job in self.jobs:
                row, data = await self.request(client, "GET", f"/api/v1/jobs/{job}", 0)
                if row["status"] == 200:
                    states[job] = {k: data.get(k) for k in ("status", "progress", "attempt_count")}
            self.report["job_progress"] = states
            self.report["resources"].append(resources())
            self.save()
            if len(states) == 3 and all(x.get("status") in ("completed", "failed", "cancelled") for x in states.values()):
                break
            await self.health(client)
            await asyncio.sleep(5)
        self.report["blueprint_batch_seconds"] = round(time.monotonic() - start, 3)
        self.save()

    def collect(self):
        from sqlalchemy import select

        from ai_examiner.db import SessionLocal
        from ai_examiner.models import BackgroundJob, ModelUsageLedger, SchoolAttempt
        from ai_examiner.services.tenancy import set_tenant_context
        with SessionLocal() as db:
            set_tenant_context(db, organization_id=self.org, principal_id=self.users[0])
            self.report["job_details"] = [{
                "id": j.id, "status": j.status, "attempt_count": j.attempt_count,
                "created_at": str(j.created_at), "started_at": str(j.started_at),
                "completed_at": str(j.completed_at), "error_code": getattr(j, "error_code", None),
            } for j in db.scalars(select(BackgroundJob).where(BackgroundJob.id.in_(self.jobs)))]
            self.report["model_calls"] = [{k: getattr(x, k, None) for k in (
                "status", "task_type", "actual_model", "latency_ms", "input_tokens", "output_tokens",
                "actual_cost_usd", "estimated_cost_usd")}
                for x in db.scalars(select(ModelUsageLedger).where(ModelUsageLedger.organization_id == self.org))]
            self.report["answer_states"] = dict(Counter(db.scalars(select(SchoolAttempt.status).where(
                SchoolAttempt.id.in_(self.attempts)))))
        self.save()

    def cleanup(self):
        if not self.fixture_committed:
            return
        from sqlalchemy import update

        from ai_examiner.db import SessionLocal
        from ai_examiner.models import BrowserAuthSession, Organization, Principal, utcnow
        from ai_examiner.services.tenancy import set_tenant_context
        with SessionLocal() as db:
            set_tenant_context(db, organization_id=self.org, principal_id=self.users[0])
            db.execute(update(BrowserAuthSession).where(BrowserAuthSession.principal_id.in_(self.users)).values(revoked_at=utcnow()))
            db.execute(update(Principal).where(Principal.id.in_(self.users)).values(status="disabled", disabled_at=utcnow()))
            db.execute(update(Organization).where(Organization.id == self.org).values(status="disabled"))
            db.commit()
        self.tokens.clear()
        self.report["cleanup"] = {"credentials_revoked": True, "test_accounts_disabled": len(self.users),
                                  "test_organization_disabled": True, "closed_fixture_retained": True}
        self.save()

    async def run(self):
        import httpx
        try:
            self.provision()
            async with httpx.AsyncClient(base_url=self.args.base_url, follow_redirects=False,
                limits=httpx.Limits(max_connections=35, max_keepalive_connections=35)) as client:
                for users in (1, 5, 10, 20, 30):
                    if users <= self.args.users:
                        await self.reads(client, users)
                        await asyncio.sleep(2)
                # Verify one student cannot read a different synthetic student's answer sheet.
                denied, _ = await self.request(client, "GET", f"/api/v1/school/attempts/{self.attempts[1]}", 1)
                self.report["cross_student_read_status"] = denied["status"]
                if denied["status"] != 404:
                    raise RuntimeError("Cross-student isolation check failed")
                if self.args.real_models:
                    await self.paid(client)
        except Exception as exc:
            self.report["stopped"] = type(exc).__name__ + ": " + str(exc).split("\n")[0][:160]
            # Request/SQL errors can contain sensitive URLs or values; keep only the class.
            if not isinstance(exc, RuntimeError):
                self.report["stopped"] = type(exc).__name__
            import traceback
            self.report["error_frames"] = [
                {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(exc.__traceback__)[-5:]
            ]
        finally:
            try:
                if self.fixture_committed:
                    # Cancel only this run's outstanding jobs before revoking its credentials.
                    async with httpx.AsyncClient(base_url=self.args.base_url, follow_redirects=False) as client:
                        for job in self.jobs:
                            row, data = await self.request(client, "GET", f"/api/v1/jobs/{job}", 0)
                            if row["status"] == 200 and data.get("status") not in ("completed", "failed", "cancelled"):
                                cancel, _ = await self.request(client, "POST", f"/api/v1/jobs/{job}/cancel", 0,
                                                              payload={"reason": "Synthetic capacity probe finished"})
                                self.report.setdefault("cancellations", {})[job] = cancel["status"]
                    self.collect()
            finally:
                self.cleanup()
            self.report["finished"] = True
            self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--users", type=int, choices=(10, 20, 30), default=30)
    parser.add_argument("--real-models", action="store_true")
    parser.add_argument("--confirm-synthetic-fixtures", action="store_true")
    args = parser.parse_args()
    if not args.confirm_synthetic_fixtures:
        parser.error("Explicit permission to create isolated test accounts is required")
    from urllib.parse import urlsplit
    target = urlsplit(args.base_url)
    if target.path not in ("", "/") or target.username or target.password or target.query or target.fragment:
        parser.error("Base URL must be an origin without credentials")
    if target.scheme != "https" and not (target.scheme == "http" and target.hostname in ("127.0.0.1", "localhost")):
        parser.error("Use HTTPS or a loopback HTTP target")
    root = args.root.resolve()
    pid = int((root / "logs/uvicorn.pid").read_text())
    if Path(f"/proc/{pid}/cwd").resolve() != root:
        parser.error("Runtime PID does not belong to this project")
    for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            os.environ[key.decode()] = value.decode()
    os.chdir(root)
    sys.path.insert(0, str(root / "src"))
    args.output = args.output.resolve()
    if args.output.exists():
        parser.error("Refusing to overwrite an existing report")
    os.umask(0o077)
    asyncio.run(Probe(args).run())


if __name__ == "__main__":
    main()
