from __future__ import annotations

from pathlib import Path

ASSET_REVISION = "classic-refined-r2-20260904"


def test_workbench_restores_the_v09_classic_layout(client):
    page = client.get("/")
    stylesheet = client.get(f"/static/styles.css?rev={ASSET_REVISION}")

    assert page.status_code == 200
    assert stylesheet.status_code == 200
    html = page.text
    css = stylesheet.text
    assert html.index('id="templateStudio"') < html.index('class="panel setup"')
    assert html.index('class="panel voice-panel"') < html.index('class="panel conversation"')
    assert 'class="workspace-nav"' not in html
    assert 'class="workflow-advanced"' not in html
    assert 'id="textModeTab"' not in html
    assert 'id="voiceModeTab"' not in html
    assert "grid-template-columns: minmax(340px, 420px) minmax(0, 1fr);" in css
    assert ".panel { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 18px;" in css
    assert ".conversation { min-height: 500px; display: flex; flex-direction: column; }" in css
    assert ".voice-panel { min-height: 360px; }" in css
    assert "h1 { font-size: 40px; line-height: 1.15;" in css
    assert ".template-workspace" in css and "min-height: 400px;" in css
    assert ".header-actions { flex: 0 0 auto; width: 100%; justify-content: flex-start; }" in css


def test_enterprise_console_restores_the_v09_classic_layout(client):
    page = client.get("/enterprise")
    stylesheet = client.get(f"/static/enterprise.css?rev={ASSET_REVISION}")

    assert page.status_code == 200
    assert stylesheet.status_code == 200
    css = stylesheet.text
    assert ".app-shell { display: grid; grid-template-columns: 224px minmax(0, 1fr);" in css
    assert ".content { min-width: 0; padding: 24px clamp(16px, 3vw, 42px) 48px; }" in css
    assert ".metric { background: var(--surface); border: 1px solid var(--line); border-radius: 7px; padding: 14px 16px; min-height: 82px; }" in css
    assert ".detail-panel { min-height: 320px; }" in css
    assert ".empty-state { text-align: center; padding: 64px 20px; color: var(--muted); }" in css


def test_v095_session_layout_behavior_is_not_loaded(client):
    script = client.get(f"/static/app.js?rev={ASSET_REVISION}").text
    css = client.get(f"/static/styles.css?rev={ASSET_REVISION}").text

    assert "function setSessionMode(" not in script
    assert "session-panel-hidden" not in css
    assert "#providerBadge.status-ready" not in css
    assert '$("providerBadge").textContent = "请先登录后加载模型";' in script


def test_compact_design_document_is_preserved_as_history():
    root = Path(__file__).resolve().parents[1]
    design_system = root / "docs" / "design" / "UI_DESIGN_SYSTEM.md"

    assert design_system.is_file()
    text = design_system.read_text(encoding="utf-8")
    assert "Status: Historical reference" in text
    assert "current v0.9 build restores the accepted v0.9.0 interface" in text
