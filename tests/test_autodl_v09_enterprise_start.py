import subprocess
from pathlib import Path


def test_autodl_enterprise_start_restores_required_native_services():
    script = (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "autodl-v09-enterprise-start.sh"
    ).read_text(encoding="utf-8")

    assert "pg_ctlcluster 17 main start" in script
    assert 'bootstrap_database.py" seed-global-data' in script
    assert 'PROMPT_DIR="$ROOT/prompts"' in script
    assert "runuser -u postgres" in script
    assert "redis-server --daemonize yes" in script
    assert '"$TOOLS_ROOT/bin/minio" server' in script
    assert '"$TOOLS_ROOT/bin/otelcol-contrib"' in script
    assert "deploy/testing/oidc_test_issuer.py" in script
    assert "ai_examiner.jobs.celery_app worker" in script
    assert "uvicorn ai_examiner.main:app" in script
    assert 'wait_for_url "http://127.0.0.1:$APP_PORT/ready"' in script
    assert "source \"$PUBLIC_ENV\"" in script
    assert "source \"$MINIO_ENV\"" in script


def test_tracked_deployment_shell_scripts_are_executable():
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--stage",
            "deploy/*.sh",
            "deploy/enterprise/*.sh",
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )

    entries = [line for line in result.stdout.splitlines() if line.strip()]
    assert entries
    non_executable = [line for line in entries if not line.startswith("100755 ")]
    assert non_executable == []
