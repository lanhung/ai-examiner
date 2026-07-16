
def _project_and_document(client):
    project = client.post("/api/projects", json={"name": "Golden 数据集测试"})
    assert project.status_code == 201
    project_id = project.json()["id"]
    material = (
        "本文提出一种面向科学问答的主动提问系统。系统将会话规划、回答分析、策略决策和证据评分拆分。"
        "实验对比单一提示词基线和状态机基线，结果显示结构化策略可以降低无意义追问。"
        "论文同时指出，当前实验只覆盖文本答辩，尚未验证实时语音、跨领域泛化和长期学习增益。"
    ) * 12
    uploaded = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": ("paper.txt", material.encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 201
    return project_id, uploaded.json()["id"]


def test_ai_golden_dataset_and_benchmark_flow(client):
    project_id, document_id = _project_and_document(client)
    generated = client.post(
        f"/api/projects/{project_id}/golden-datasets",
        json={
            "document_id": document_id,
            "profiles": ["mock:heuristic-v2"],
            "consensus_profile": "mock:heuristic-v2",
            "question_count": 6,
        },
    )
    assert generated.status_code == 201, generated.text
    dataset = generated.json()
    assert dataset["status"] == "ready"
    assert dataset["quality_metrics"]["grounded_rate"] == 1.0
    assert dataset["quality_metrics"]["annotation_completeness"] == 1.0
    assert len(dataset["data"]["cases"]) == 6
    assert all(len(case["synthetic_answers"]) == 4 for case in dataset["data"]["cases"])

    exported = client.get(f"/api/golden-datasets/{dataset['id']}/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/x-ndjson")
    assert len([line for line in exported.text.splitlines() if line]) == 6

    benchmarked = client.post(
        f"/api/golden-datasets/{dataset['id']}/benchmarks",
        json={
            "profiles": ["mock:heuristic-v2"],
            "case_limit": 2,
            "run_planner": True,
            "run_analyzer": True,
        },
    )
    assert benchmarked.status_code == 201, benchmarked.text
    run = benchmarked.json()
    assert run["status"] == "completed"
    assert run["summary"]["winner"] == "mock:heuristic-v2"
    assert run["results"][0]["planner"]["question_count"] >= 6
    assert run["results"][0]["analyzer"]["sample_count"] == 8
    assert 0 <= run["results"][0]["quality_score"] <= 100


def test_optional_expert_calibration_endpoint(client):
    project_id, document_id = _project_and_document(client)
    dataset = client.post(
        f"/api/projects/{project_id}/golden-datasets",
        json={"document_id": document_id, "question_count": 4},
    ).json()
    for case_id, score in [("Q1", 5), ("Q2", 4)]:
        rated = client.post(
            f"/api/golden-datasets/{dataset['id']}/ratings",
            json={
                "case_id": case_id,
                "rater": "expert-a",
                "relevance": score,
                "difficulty": score,
                "groundedness": score,
                "answer_quality": score,
                "notes": "校准样本",
            },
        )
        assert rated.status_code == 201

    agreement = client.get(f"/api/golden-datasets/{dataset['id']}/agreement")
    assert agreement.status_code == 200
    data = agreement.json()
    assert data["rating_count"] == 2
    assert data["rated_case_count"] == 2
    assert data["coverage"] == 0.5
