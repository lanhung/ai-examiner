"""Run the complete v0.2 workflow without external API keys."""

import os
from pathlib import Path

os.environ.setdefault("MODEL_PROVIDER", "mock")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/smoke_ai_examiner.db")
os.environ.setdefault("UPLOAD_DIR", "./data/smoke_uploads")

from fastapi.testclient import TestClient  # noqa: E402

from ai_examiner.main import app  # noqa: E402


def main() -> None:
    sample = Path("examples/sample_research.md")
    with TestClient(app) as client:
        health = client.get("/health")
        health.raise_for_status()
        project = client.post("/api/projects", json={"name": "Smoke Test Project"}).json()
        with sample.open("rb") as handle:
            document = client.post(
                f"/api/projects/{project['id']}/documents",
                files={"file": (sample.name, handle, "text/markdown")},
            )
        document.raise_for_status()
        document_id = document.json()["id"]

        golden = client.post(
            f"/api/projects/{project['id']}/golden-datasets",
            json={
                "document_id": document_id,
                "profiles": ["mock:heuristic-v2"],
                "question_count": 6,
            },
        )
        golden.raise_for_status()
        dataset = golden.json()
        benchmark = client.post(
            f"/api/golden-datasets/{dataset['id']}/benchmarks",
            json={"profiles": ["mock:heuristic-v2"], "case_limit": 2},
        )
        benchmark.raise_for_status()

        blueprint = client.post(
            f"/api/projects/{project['id']}/blueprints",
            params={"document_id": document_id},
        )
        blueprint.raise_for_status()
        session = client.post(
            "/api/sessions",
            json={
                "project_id": project["id"],
                "blueprint_id": blueprint.json()["id"],
                "question_limit": 1,
                "max_followups_per_question": 0,
            },
        )
        session.raise_for_status()
        session_id = session.json()["id"]
        client.post(f"/api/sessions/{session_id}/start").raise_for_status()
        answer = client.post(
            f"/api/sessions/{session_id}/answers",
            json={
                "answer": "核心问题是普通聊天系统缺少持续知识状态诊断。"
                "因为所有行为由单一提示词控制时不稳定，所以需要状态机和独立评分证据。"
            },
        )
        answer.raise_for_status()
        report = client.get(f"/api/sessions/{session_id}/report")
        report.raise_for_status()
        result = report.json()
        print(
            "V0.2 SMOKE TEST PASSED | "
            f"provider={health.json()['provider']} | "
            f"golden_cases={dataset['quality_metrics']['case_count']} | "
            f"grounded={dataset['quality_metrics']['grounded_rate']} | "
            f"benchmark={benchmark.json()['summary']['winner']} | "
            f"exam_score={result['overall_score']}/5"
        )


if __name__ == "__main__":
    main()
