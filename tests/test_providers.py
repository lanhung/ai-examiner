def test_provider_registry_exposes_ready_state(client):
    response = client.get("/api/providers")
    assert response.status_code == 200
    providers = response.json()
    by_id = {item["id"]: item for item in providers}
    assert by_id["mock:heuristic-v2"]["ready"] is True
    assert "openai:gpt-5.4-mini" in by_id
    assert "anthropic:claude-sonnet-5" in by_id
    assert "gemini:gemini-3.5-flash" in by_id
    assert "ollama:qwen2.5:14b" in by_id
    assert "ollama:qwen2.5:7b" in by_id
    assert "ollama:llama3.2:3b" in by_id
