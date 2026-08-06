from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "autodl-v09-staging-start.sh"


def test_autodl_v09_staging_start_tracks_required_services() -> None:
    content = SCRIPT.read_text(encoding="utf-8")

    assert ".env.oidc-staging" in content
    assert 'APP_PORT="${APP_PORT:-6006}"' in content
    assert 'OIDC_PORT="${TEST_OIDC_PORT:-6008}"' in content
    assert "redis-server --daemonize yes" in content
    assert "deploy/testing/oidc_test_issuer.py" in content
    assert '"$ROOT/deploy/autodl-start.sh"' in content
    assert "/ready" in content
    assert "sk-proj-" not in content
    assert "sk-ant-" not in content


def test_autodl_v09_staging_start_parses_when_bash_is_available() -> None:
    bash = shutil.which("bash")
    if bash is None and os.name == "nt":
        candidate = Path(r"C:\Program Files\Git\bin\bash.exe")
        bash = str(candidate) if candidate.exists() else None
    if bash is None:
        pytest.skip("bash is unavailable")

    subprocess.run([bash, "-n", str(SCRIPT)], check=True, cwd=ROOT)
