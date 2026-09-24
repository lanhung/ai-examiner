"""Simulate a class of students taking one exam at the same time.

Against a local server with the mock model (free)::

    MOCK_PROVIDER_LATENCY_MS=3000 uvicorn ai_examiner.main:app --port 8000
    uv run python scripts/load_test_exam_window.py --base-url http://127.0.0.1:8000 \\
        --students 40 --publish

Against a deployment, reuse an exam a teacher already published (this calls the
real model for every answer and costs money)::

    uv run python scripts/load_test_exam_window.py --base-url https://exam.example.com \\
        --join-code ABC234 --students 10 --i-understand-this-costs-money

Exit status is non-zero when any student fails to finish or the p95 answer
latency exceeds --max-p95-seconds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time

import httpx

MATERIAL = (
    "本文提出一种面向科学计算的自适应代理方法。核心贡献包括状态建模、证据化评分和追问策略。"
    "实验比较了三种基线，并讨论了数据分布变化时的局限。"
) * 10
ANSWERS = [
    "核心问题是现有系统只会回答，不能持续诊断理解。因为缺少状态建模，所以追问不稳定。",
    "新增之处是将分析、策略和评分拆开，并用实验与三种基线比较验证。",
    "局限是数据分布变化时效果会下降，需要更多验证。",
    "补充：实验覆盖三种基线，并报告了误差范围。",
    "总结：证据化评分在多数场景更稳定，但仍需人工复核。",
]


async def publish(client: httpx.AsyncClient, question_limit: int) -> str:
    project = (await client.post("/api/projects", json={"name": "load test"})).json()
    document = (
        await client.post(
            f"/api/projects/{project['id']}/documents",
            files={"file": ("load.txt", MATERIAL.encode("utf-8"), "text/plain")},
        )
    ).json()
    blueprint = (
        await client.post(
            f"/api/projects/{project['id']}/blueprints",
            json={"document_id": document["id"]},
            timeout=600,
        )
    ).json()
    created = await client.post(
        "/api/assignments",
        json={
            "project_id": project["id"],
            "blueprint_id": blueprint["id"],
            "title": "负载测试",
            "mode": "exam",
            "max_attempts": 1,
            "require_learner_key": True,
            "session_settings": {"question_limit": question_limit},
        },
    )
    created.raise_for_status()
    return created.json()["join_code"]


async def student(
    client: httpx.AsyncClient,
    code: str,
    index: int,
    *,
    headers: dict,
    think_seconds: float,
) -> dict:
    outcome = {"student": index, "ok": False, "answers": 0, "latencies": [], "error": None}
    try:
        joined = await client.get(f"/api/join/{code}", headers=headers)
        joined.raise_for_status()
        created = await client.post(
            f"/api/join/{code}/attempts",
            json={"display_name": f"学生{index}", "learner_key": f"LOAD{index:04d}"},
            headers=headers,
        )
        created.raise_for_status()
        token = created.json()["attempt_token"]
        attempt_id = created.json()["attempt"]["id"]
        auth = {**headers, "X-AI-Examiner-Attempt-Token": token}
        started = await client.post(f"/api/attempts/{attempt_id}/start", headers=auth)
        started.raise_for_status()
        for turn in range(20):
            await asyncio.sleep(think_seconds)
            began = time.monotonic()
            answered = await client.post(
                f"/api/attempts/{attempt_id}/answers",
                json={"answer": ANSWERS[turn % len(ANSWERS)]},
                headers=auth,
            )
            outcome["latencies"].append(time.monotonic() - began)
            answered.raise_for_status()
            outcome["answers"] += 1
            if answered.json()["completed"]:
                break
        report = await client.get(f"/api/attempts/{attempt_id}/report", headers=auth)
        report.raise_for_status()
        outcome["ok"] = report.json()["status"] in {"submitted", "released"}
    except Exception as exc:  # noqa: BLE001 - reported per student
        detail = getattr(getattr(exc, "response", None), "text", "")
        outcome["error"] = f"{type(exc).__name__}: {exc} {detail[:200]}".strip()
    return outcome


async def main_async(args: argparse.Namespace) -> int:
    auth = (args.teacher_user, args.teacher_password) if args.teacher_user else None
    limits = httpx.Limits(max_connections=args.students + 10)
    async with httpx.AsyncClient(
        base_url=args.base_url, timeout=args.timeout, limits=limits, auth=auth
    ) as teacher:
        code = args.join_code or await publish(teacher, args.question_limit)
    headers = {"X-AI-Examiner-Organization": args.organization} if args.organization else {}
    started = time.monotonic()
    async with httpx.AsyncClient(
        base_url=args.base_url, timeout=args.timeout, limits=limits
    ) as client:
        results = await asyncio.gather(
            *(
                student(
                    client, code, index, headers=headers, think_seconds=args.think_seconds
                )
                for index in range(args.students)
            )
        )
    elapsed = time.monotonic() - started
    latencies = sorted(value for item in results for value in item["latencies"])
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)] if latencies else None
    summary = {
        "join_code": code,
        "students": args.students,
        "finished": sum(item["ok"] for item in results),
        "answers": sum(item["answers"] for item in results),
        "wall_seconds": round(elapsed, 1),
        "answer_latency_seconds": {
            "p50": round(statistics.median(latencies), 2) if latencies else None,
            "p95": round(p95, 2) if p95 is not None else None,
            "max": round(latencies[-1], 2) if latencies else None,
        },
        "errors": [item["error"] for item in results if item["error"]][:10],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    failed = summary["finished"] < args.students
    slow = p95 is not None and p95 > args.max_p95_seconds
    return 1 if failed or slow else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--students", type=int, default=40)
    parser.add_argument("--join-code")
    parser.add_argument("--publish", action="store_true",
                        help="create a project, blueprint and exam first (teacher API)")
    parser.add_argument("--question-limit", type=int, default=3)
    parser.add_argument("--think-seconds", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--max-p95-seconds", type=float, default=30.0)
    parser.add_argument("--organization")
    parser.add_argument("--teacher-user")
    parser.add_argument("--teacher-password")
    parser.add_argument("--i-understand-this-costs-money", action="store_true")
    args = parser.parse_args()
    local = args.base_url.startswith(("http://127.0.0.1", "http://localhost"))
    if not args.join_code and not args.publish:
        parser.error("pass --join-code or --publish")
    if not local and not args.i_understand_this_costs_money:
        parser.error("remote runs call the real model; add --i-understand-this-costs-money")
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
