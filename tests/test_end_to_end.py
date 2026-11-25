def test_complete_text_exam_flow(client, monkeypatch):
    project = client.post("/api/projects", json={"name": "测试答辩"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    material = (
        "本文提出一种面向科学计算的自适应代理方法。核心贡献包括状态建模、证据化评分和追问策略。"
        "实验比较了三种基线，并讨论了数据分布变化时的局限。"
    ) * 10
    uploaded = client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": ("paper.txt", material.encode("utf-8"), "text/plain")},
    )
    assert uploaded.status_code == 201
    document_id = uploaded.json()["id"]

    planned = client.post(
        f"/api/projects/{project_id}/blueprints", params={"document_id": document_id}
    )
    assert planned.status_code == 201
    blueprint = planned.json()
    assert len(blueprint["data"]["questions"]) >= 6
    assert blueprint["provider"] == "mock"

    planned_with_profile = client.post(
        f"/api/projects/{project_id}/blueprints",
        json={"document_id": document_id, "profile": "mock:heuristic-v2"},
    )
    assert planned_with_profile.status_code == 201
    assert planned_with_profile.json()["provider"] == "mock"
    assert planned_with_profile.json()["model"] == "heuristic-v2"

    created = client.post(
        "/api/sessions",
        json={
            "project_id": project_id,
            "blueprint_id": blueprint["id"],
            "profile": "mock:heuristic-v2",
            "question_limit": 2,
            "max_followups_per_question": 0,
        },
    )
    assert created.status_code == 201
    assert created.json()["config"]["profile"] == "mock:heuristic-v2"
    session_id = created.json()["id"]

    started = client.post(f"/api/sessions/{session_id}/start")
    assert started.status_code == 200
    assert started.json()["turn"]["role"] == "assistant"

    answer1 = client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "answer": "核心问题是现有系统只会回答，不能持续诊断理解。因为缺少状态建模，所以追问不稳定，并且没有证据化评价。"
        },
    )
    assert answer1.status_code == 200
    assert answer1.json()["completed"] is False
    assert answer1.json()["evaluation"]["score"] > 0

    answer2 = client.post(
        f"/api/sessions/{session_id}/answers",
        json={
            "answer": "新增之处是将分析、策略和评分拆开，并用实验与基线比较验证，而不是只依靠一个长提示词。"
        },
    )
    assert answer2.status_code == 200
    assert answer2.json()["completed"] is True

    # Reading stored evidence must still work if model access has since been disabled.
    def no_provider(*args, **kwargs):
        raise AssertionError("Reading an existing report must not initialize a model")

    monkeypatch.setattr("ai_examiner.main.provider_or_503", no_provider)
    report = client.get(f"/api/sessions/{session_id}/report")
    assert report.status_code == 200
    report_data = report.json()
    assert report_data["questions_answered"] == 2
    assert 0 <= report_data["overall_score"] <= 5
    assert report_data["evidence"]
    assert report_data["report_version"] == "assessment-report-v3"
    assert report_data["template"]["slug"] == "academic.thesis_defense"
    assert report_data["template"]["fingerprint"].startswith("sha256:")
    assert report_data["objective_scores"]
    assert report_data["dimension_scores"]
    assert report_data["section_order"]
    assert all(
        item["dimension_assessments"] for item in report_data["evidence"]
    )
    assert report_data["questions_answered"] == 2
    assert report_data["evaluated_turns"] == 2

    metrics = client.get("/api/metrics").json()
    assert metrics["latency_ms"]["samples"] >= 3
    assert metrics["latency_ms"]["p50"] >= 1
    costs = client.get(f"/api/costs?project_id={project_id}").json()
    assert costs["by_model"]["mock:heuristic-v2"]["latency_ms"]["samples"] >= 3


def test_async_final_answer_replay_and_read_only_report(client):
    from uuid import uuid4

    project = client.post("/api/projects", json={"name": "回执验收"}).json()["id"]
    material = "本研究比较两种客流预测方法，以留出的测试周计算平均绝对误差；结果不能外推至节假日。" * 10
    doc = client.post(f"/api/projects/{project}/documents", files={
        "file": ("case.txt", material.encode(), "text/plain"),
    }).json()["id"]
    blueprint = client.post(f"/api/projects/{project}/blueprints", params={"document_id": doc}).json()["id"]
    session = client.post("/api/sessions", json={
        "project_id": project, "blueprint_id": blueprint, "question_limit": 1,
        "max_followups_per_question": 0, "allow_hints": False,
    }).json()["id"]
    path = f"/api/sessions/{session}"
    key = str(uuid4())
    started = client.post(path+"/operations", json={"operation": "start", "expected_turn_count": 0, "request_id": key})
    assert started.status_code == 202
    assert client.get(path+"/operations/"+key).json()["job"]["status"] == "completed"
    count = len(client.get(path).json()["turns"])
    answer = {"operation": "answer", "answer": "我们按时间留出相同的测试周，再比较两种方法的平均绝对误差，避免混用训练数据。结论仅适用于普通周，不能推断节假日同样有效。", "expected_turn_count": count, "request_id": str(uuid4())}
    ack = client.post(path+"/operations", json=answer)
    assert ack.status_code == 202
    receipt = client.get(path+"/operations/"+answer["request_id"]).json()["job"]
    assert receipt["id"] == ack.json()["id"] and receipt["status"] == "completed"
    assert client.post(path+"/operations", json=answer).json()["id"] == receipt["id"]
    assert client.get(path+"/operations/"+str(uuid4())).json() == {"job": None}
    completed = client.get(path).json()
    assert completed["status"] == "completed"
    assert sum(t["role"] == "user" for t in completed["turns"]) == 1
    report = client.get(path+"/report")
    assert report.status_code == 200 and report.json()["evaluated_turns"] == 1
    assert client.get(path+"/report").json() == report.json()
    assert client.get(path).json()["turns"] == completed["turns"]
