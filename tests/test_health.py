def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["provider"] == "mock"
    assert data["provider_ready"] is True

def test_blueprint_has_independent_model_selector(client):
    page = client.get("/")
    script = client.get("/static/app.js")

    assert page.status_code == 200
    assert 'id="blueprintProfile"' in page.text
    assert script.status_code == 200
    assert 'const profile = $("blueprintProfile").value;' in script.text
    assert 'profiles[0] || "mock:heuristic-v2"' not in script.text
