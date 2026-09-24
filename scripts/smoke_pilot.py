"""Post-deploy smoke test for the classroom pilot profile.

Checks that the teacher surface is password-protected, the student surface is
public, and (with --full) that a teacher can publish an exam and a student can
finish it end to end through the real model.

    uv run python scripts/smoke_pilot.py --base-url https://exam.example.com \\
        --teacher-user teacher --teacher-password '...' --full

--full uses the real model once for a small question plan and about five
answers (a few cents with qwen-plus). The exam it creates is closed afterwards.
Exit status is non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import sys
import time

import httpx

MATERIAL = (
    "牛顿第二定律指出：物体加速度的大小跟它受到的合力成正比，跟它的质量成反比，"
    "加速度的方向跟合力的方向相同。其表达式为 F = ma。应用时要先确定研究对象，"
    "再进行受力分析求出合力。该定律适用于惯性参考系中的宏观、低速物体。"
) * 4
ANSWERS = [
    "加速度与合力成正比、与质量成反比，方向与合力相同，因为 F=ma。例如 2kg 木块受 6N 合力时加速度是 3m/s²。",
    "先确定研究对象，再做受力分析求合力，最后用 F=ma 求加速度。",
    "它只适用于惯性参考系中的宏观低速物体，接近光速时要用相对论。",
    "补充：合力和加速度都是矢量，需要按方向分解。",
    "总结：受力分析是关键。",
]


class Smoke:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}")
        if not ok:
            self.failures += 1
        return ok


def surface_checks(smoke: Smoke, client: httpx.Client, auth: tuple[str, str]) -> None:
    health = client.get("/health")
    smoke.check("health endpoint is public and OK", health.status_code == 200, str(health.status_code))
    if health.status_code == 200:
        body = health.json()
        smoke.check(
            "model provider is ready",
            bool(body.get("provider_ready")),
            f"{body.get('provider')}:{body.get('model')}",
        )
    for path in ("/", "/enterprise", "/api/assignments", "/api/projects", "/docs",
                 "/openapi.json", "/static/app.js", "/api/v1/me"):
        response = client.get(path)
        smoke.check(f"{path} requires the teacher password", response.status_code == 401,
                    str(response.status_code))
    for path in ("/x/ABC234", "/exam", "/static/exam.js"):
        response = client.get(path)
        smoke.check(f"{path} is public", response.status_code == 200, str(response.status_code))
    join = client.get("/api/join/ABC234")
    smoke.check("unknown join code returns 404", join.status_code == 404, str(join.status_code))
    teacher = client.get("/", auth=auth)
    smoke.check("teacher password opens the workbench", teacher.status_code == 200,
                str(teacher.status_code))
    wrong = client.get("/", auth=(auth[0], auth[1] + "-wrong"))
    smoke.check("wrong teacher password is rejected", wrong.status_code == 401,
                str(wrong.status_code))
    if client.base_url.scheme == "https":
        insecure = httpx.get(str(client.base_url.copy_with(scheme="http")) + "health",
                             follow_redirects=False, timeout=10)
        smoke.check("plain HTTP redirects to HTTPS", insecure.status_code in {301, 302, 308},
                    str(insecure.status_code))


def full_flow(smoke: Smoke, client: httpx.Client, auth: tuple[str, str]) -> None:
    project = client.post("/api/projects", json={"name": "上线冒烟测试", "data_classification": "public"},
                          auth=auth)
    if not smoke.check("teacher can create a project", project.status_code == 201, project.text[:200]):
        return
    project_id = project.json()["id"]
    document = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": ("smoke.txt", MATERIAL.encode("utf-8"), "text/plain")},
        auth=auth,
    )
    if not smoke.check("teacher can upload material", document.status_code == 201, document.text[:200]):
        return
    started = time.monotonic()
    blueprint = client.post(
        f"/api/projects/{project_id}/blueprints",
        json={"document_id": document.json()["id"]},
        auth=auth,
        timeout=600,
    )
    if not smoke.check("model generates questions", blueprint.status_code == 201,
                       f"{time.monotonic() - started:.1f}s {blueprint.text[:200]}"):
        return
    assignment = client.post(
        "/api/assignments",
        json={
            "project_id": project_id,
            "blueprint_id": blueprint.json()["id"],
            "title": "上线冒烟测试（可删除）",
            "mode": "practice",
            "session_settings": {"question_limit": 2, "max_followups_per_question": 1},
        },
        auth=auth,
    )
    if not smoke.check("teacher can publish an exam", assignment.status_code == 201,
                       assignment.text[:200]):
        return
    code = assignment.json()["join_code"]
    assignment_id = assignment.json()["id"]
    try:
        joined = client.post(
            f"/api/join/{code}/attempts",
            json={"display_name": "冒烟测试"},
            headers={"X-AI-Examiner-Principal": "00000000-0000-0000-0000-000000000099"},
        )
        if not smoke.check("anonymous student can join (spoofed principal ignored)",
                           joined.status_code == 201, joined.text[:200]):
            return
        token = joined.json()["attempt_token"]
        attempt_id = joined.json()["attempt"]["id"]
        headers = {"X-AI-Examiner-Attempt-Token": token}
        start = client.post(f"/api/attempts/{attempt_id}/start", headers=headers)
        smoke.check("student can start", start.status_code == 200, start.text[:200])
        smoke.check("attempt is private without its token",
                    client.get(f"/api/attempts/{attempt_id}").status_code == 404)
        latencies = []
        completed = False
        for answer in ANSWERS * 2:
            began = time.monotonic()
            response = client.post(f"/api/attempts/{attempt_id}/answers",
                                   json={"answer": answer}, headers=headers, timeout=180)
            latencies.append(time.monotonic() - began)
            if not smoke.check("student answer accepted", response.status_code == 200,
                               f"{latencies[-1]:.1f}s {response.text[:160]}"):
                return
            if response.json()["completed"]:
                completed = True
                break
        smoke.check("student finishes the exam", completed,
                    f"{len(latencies)} answers, slowest {max(latencies):.1f}s")
        report = client.get(f"/api/attempts/{attempt_id}/report", headers=headers, timeout=120)
        smoke.check("student sees a practice result",
                    report.status_code == 200 and report.json().get("results_available") is True,
                    report.text[:200])
        dashboard = client.get(f"/api/assignments/{assignment_id}/dashboard", auth=auth)
        smoke.check("teacher dashboard shows the submission",
                    dashboard.status_code == 200 and dashboard.json()["counts"]["submitted"] == 1)
    finally:
        client.patch(f"/api/assignments/{assignment_id}", json={"status": "closed"}, auth=auth)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--teacher-user", required=True)
    parser.add_argument("--teacher-password", required=True)
    parser.add_argument("--full", action="store_true",
                        help="also publish an exam and complete it as a student (uses the model)")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification (testing only)")
    args = parser.parse_args()
    smoke = Smoke()
    auth = (args.teacher_user, args.teacher_password)
    with httpx.Client(base_url=args.base_url.rstrip("/") + "/", timeout=60,
                      verify=not args.insecure) as client:
        surface_checks(smoke, client, auth)
        if args.full:
            full_flow(smoke, client, auth)
    print(f"\n{'ALL CHECKS PASSED' if not smoke.failures else f'{smoke.failures} CHECK(S) FAILED'}")
    sys.exit(1 if smoke.failures else 0)


if __name__ == "__main__":
    main()
