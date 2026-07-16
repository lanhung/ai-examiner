def test_complete_text_exam_flow(client):
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
            "question_limit": 2,
            "max_followups_per_question": 0,
        },
    )
    assert created.status_code == 201
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

    report = client.get(f"/api/sessions/{session_id}/report")
    assert report.status_code == 200
    report_data = report.json()
    assert report_data["questions_answered"] == 2
    assert 0 <= report_data["overall_score"] <= 5
    assert report_data["evidence"]
