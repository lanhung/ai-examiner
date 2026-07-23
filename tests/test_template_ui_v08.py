from __future__ import annotations


def test_homepage_delivers_v08_template_studio(client):
    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "AI Examiner v0.8 开发版" in html
    assert 'id="templateStudio"' in html
    assert 'id="templateCatalogList"' in html
    assert 'id="templateDetail"' in html
    assert 'id="sessionTemplateSelect"' in html
    assert "/static/styles.css?v=0.8.0-i1" in html
    assert "/static/app.js?v=0.8.0-i1" in html


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
    assert "function selectedTemplateRequest()" in javascript
    assert "template_version_id: state.selectedTemplateVersionId" in javascript
    assert "template_overrides: {}" in javascript
    assert javascript.count("...selectedTemplateRequest()") >= 3
    assert 'api("/api/sessions"' in javascript
    assert 'api("/api/voice/sessions"' in javascript
