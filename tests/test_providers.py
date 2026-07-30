def test_provider_registry_exposes_ready_state(client):
    response = client.get("/api/providers")
    assert response.status_code == 200
    providers = response.json()
    by_id = {item["id"]: item for item in providers}
    assert by_id["mock:heuristic-v2"]["ready"] is True
    assert "openai:gpt-5.4-mini" in by_id
    assert "anthropic:claude-sonnet-5" in by_id
    assert "gemini:gemini-3.5-flash" in by_id
    assert by_id["qwen:qwen-plus"]["ready"] is True
    assert by_id["qwen:qwen3-vl-plus"]["supports_vision"] is True
    assert "ollama:qwen2.5:14b" in by_id
    assert "ollama:qwen2.5:7b" in by_id
    assert "ollama:llama3.2:3b" in by_id


def test_qwen_provider_uses_text_and_visual_models(tmp_path):
    import httpx

    from ai_examiner.providers.qwen_provider import QwenProvider

    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"summary":"ok"}'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
        )

    provider = QwenProvider(
        "test-key",
        "qwen-plus",
        base_url="https://example.test/v1",
        visual_model="qwen3-vl-plus",
    )
    provider.client.close()
    provider.client = httpx.Client(
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handler),
    )

    text_result = provider.complete_json(
        agent="planner",
        instructions="Return a summary.",
        payload={"document_text": "untrusted"},
        schema_hint={"summary": "string"},
    )
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake-png")
    image_result = provider.complete_json_with_images(
        agent="visual_evidence",
        instructions="Inspect the page.",
        payload={"page_number": 1},
        image_paths=[image_path],
        schema_hint={"summary": "string"},
    )

    assert text_result.model == "qwen-plus"
    assert text_result.data == {"summary": "ok"}
    assert text_result.input_tokens == 11
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert requests[0]["enable_thinking"] is False
    assert image_result.model == "qwen3-vl-plus"
    assert requests[1]["model"] == "qwen3-vl-plus"
    image_content = requests[1]["messages"][1]["content"][1]
    assert image_content["type"] == "image_url"
    assert image_content["image_url"]["url"].startswith("data:image/png;base64,")


def test_qwen_provider_can_enable_thinking():
    import httpx

    from ai_examiner.providers.qwen_provider import QwenProvider

    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"summary":"ok"}'}}],
                "usage": {},
            },
        )

    provider = QwenProvider(
        "test-key",
        "qwen-plus",
        base_url="https://example.test/v1",
        visual_model="qwen3-vl-plus",
        enable_thinking=True,
    )
    provider.client.close()
    provider.client = httpx.Client(
        base_url="https://example.test/v1",
        transport=httpx.MockTransport(handler),
    )
    provider.complete_json(
        agent="planner",
        instructions="Return a summary.",
        payload={"document_text": "untrusted"},
        schema_hint={"summary": "string"},
    )

    assert requests[0]["enable_thinking"] is True
