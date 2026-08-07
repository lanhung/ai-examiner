from __future__ import annotations


def test_homepage_delivers_v08_template_studio(client):
    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "AI Examiner v0.9 候选版" in html
    assert 'id="templateStudio"' in html
    assert 'id="templateCatalogList"' in html
    assert 'id="templateDetail"' in html
    assert 'id="sessionTemplateSelect"' in html
    assert "/static/styles.css?v=0.9.0-rc1" in html
    assert "/static/app.js?v=0.9.0-rc1" in html


def test_template_editor_uses_contract_values_and_safe_transfer_endpoints(client):
    response = client.get("/static/app.js")

    assert response.status_code == 200
    javascript = response.text
    for timing in (
        "never",
        "after_independent_attempt",
        "after_followups",
        "session_end",
    ):
        assert f'value="{timing}"' in javascript
    assert 'value="immediate"' not in javascript
    assert 'api("/api/templates/import"' in javascript
    assert "/preview" in javascript
    assert "/diff/" in javascript


def test_selected_template_is_wired_into_blueprint_text_and_voice_requests(client):
    response = client.get("/static/app.js")

    assert response.status_code == 200
    javascript = response.text
    assert "function selectedTemplateRequest(" in javascript
    assert "template_version_id: state.selectedTemplateVersionId" in javascript
    assert "template_overrides: templateOverrides" in javascript
    assert "templateOverrides.question_strategy = selectedStrategy" in javascript
    assert "templateOverrides.voice_provider" in javascript
    assert javascript.count("...selectedTemplateRequest(") >= 3
    assert 'api("/api/sessions"' in javascript
    assert 'api("/api/voice/sessions"' in javascript


def test_voice_browser_flow_consumes_sdp_body_once_and_has_timeouts(client):
    javascript = client.get("/static/app.js").text

    assert "const raw = await response.text();" in javascript
    assert 'sdp: raw' in javascript
    assert "sdp: await response.text()" not in javascript
    assert "function getUserMediaWithTimeout(" in javascript
    assert "stream.getTracks().forEach((track) => track.stop())" in javascript
    assert "麦克风授权或设备启动超时" in javascript
    assert "实时语音协商超时" in javascript


def test_memory_configuration_error_is_user_friendly(client):
    javascript = client.get("/static/app.js").text

    assert 'includes("MEMORY_IDENTITY_SECRET")' in javascript
    assert "长期记忆尚未由管理员启用" in javascript


def test_visual_results_show_only_the_latest_analysis_per_evidence_asset(client):
    response = client.get("/static/app.js")

    assert response.status_code == 200
    javascript = response.text
    assert "function latestVisualAnalyses(items)" in javascript
    assert "latest.has(item.evidence_asset_id)" in javascript
    assert "latestVisualAnalyses(history)" in javascript
    assert "仅显示每页最新结果" in javascript
