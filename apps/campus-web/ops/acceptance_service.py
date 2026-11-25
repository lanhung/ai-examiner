"""Private, disposable instance for the browser acceptance test; never run as the live site."""
import asyncio
import json
import logging
import os
import pwd
import secrets
import shutil
import socket
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
from uuid import uuid4


def seed_download(root, db, cfg, pid):
    """A manually authored fixture for download testing only, not a model result."""
    from ai_examiner.models import Blueprint, Document, Principal, Project
    from ai_examiner.school_api import PublishExam, publish_exam, teacher_scope
    p = db.get(Principal, pid)
    org = teacher_scope(db, p).organization_id
    content = cfg["download_fixture"]
    path = root / "synthetic-defense.txt"
    path.write_bytes(content.encode())
    project = Project(organization_id=org, name="Download fixture")
    db.add(project)
    db.flush()
    doc = Document(organization_id=org, project_id=project.id, filename=path.name, content_type="text/plain",
                   storage_path=str(path), content_text=content)
    db.add(doc)
    db.flush()
    bp = Blueprint(organization_id=org, project_id=project.id, document_id=doc.id, provider="fixture",
                   model="manual", data={"questions":[{"id":"Q1","type":"evidence","text":"样本来自哪里？",
                   "expected_points":["合成材料"], "source_excerpt":content}]})
    db.add(bp)
    db.commit()
    publish_exam(PublishExam(request_id=uuid4(), blueprint_id=bp.id,title="材料下载验收",teacher_name="验收教师",
                 profile="qwen:qwen-plus",question_count=1,share_material_confirmed=True),p,db)


async def serve(root, cfg):
    import httpx
    import uvicorn
    import campus
    from ai_examiner import main as backend
    from ai_examiner.db import Base, SessionLocal, engine
    from ai_examiner.providers.qwen_provider import QwenProvider
    from ai_examiner.services.enterprise_identity import ensure_legacy_organization
    from ai_examiner.services.prompts import seed_prompt_registry
    from ai_examiner.services.templates import seed_builtin_templates
    from identity_bridge import IdentityBridge
    from passwords import PasswordStore
    from teacher_fixture import teacher_account

    if engine.dialect.name != "sqlite" or Path(engine.url.database).resolve().parent != root:
        raise RuntimeError("Refusing non-fixture database")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        ensure_legacy_organization(db)
        db.commit()
        seed_prompt_registry(db, root / "prompts")
        seed_builtin_templates(db)
    store = PasswordStore(str(root / "accounts.sqlite3"))
    store.register("accept_teacher", "验收教师", cfg["password"])
    account = store.verify("accept_teacher", cfg["password"])
    # Perform the same first-login provisioning as the website. The browser will
    # subsequently log in normally with its own independent session.
    bridge = IdentityBridge()
    bridge.revoke(bridge.issue(account))
    with SessionLocal() as db:
        assert teacher_account(db, account, apply=True)["separate_teacher_space"]
        if cfg["scope"] == "download":
            seed_download(root, db, cfg, bridge._ids(account)[0])

    calls = [0, 0, 0, 0]
    guard = Lock()
    chat = QwenProvider._chat

    def bounded(self, **kw):
        phase = "planner"
        if cfg["scope"] == "speed":
            try:
                request = json.loads(kw["messages"][1]["content"]).get("payload", {})
                if len(kw["messages"]) > 2:
                    phase = "json_repair"
                elif "wording_repair_targets" in request:
                    phase = "wording_repair"
                elif "invalid_language_result" in request:
                    phase = "language_repair"
                elif "invalid_result" in request:
                    phase = "contract_repair"
            except (IndexError, KeyError, TypeError, ValueError, AttributeError):
                phase = "unknown"
        with guard:
            if kw["model"] != "qwen-plus" or calls[0] >= min(8, cfg["max_calls"]):
                if cfg["scope"] == "speed":
                    print(f"MODEL blocked phase={phase} (test budget/model restriction)", flush=True)
                raise RuntimeError("Acceptance model budget exhausted")
            calls[0] += 1
            n = calls[0]
        start = time.monotonic()
        print(f"MODEL start {n} qwen-plus", flush=True)
        result = chat(self, **kw)
        with guard:
            calls[1] += 1
            calls[2] += result[1]
            calls[3] += result[2]
        print(f"MODEL success {n} qwen-plus {time.monotonic()-start:.1f}s", flush=True)
        if cfg["scope"] == "speed":
            try:
                raw = json.loads(result[0])
                questions = raw.get("questions") if isinstance(raw, dict) else None
            except ValueError:
                questions = None
            print("MODEL_METRICS " + json.dumps({
                "call": n, "phase": phase, "input_tokens": result[1], "output_tokens": result[2],
                "raw_questions": len(questions) if isinstance(questions, list) else None,
            }), flush=True)
        return result

    QwenProvider._chat = bounded
    original_lifespan = campus.app.router.lifespan_context

    @asynccontextmanager
    async def isolated_lifespan(app):
        async with backend.lifespan(backend.app), original_lifespan(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app)) as client:
                app.state.client = client
                yield

    campus.app.router.lifespan_context = isolated_lifespan

    @campus.app.middleware("http")
    async def private_listener(request, call_next):
        from starlette.responses import Response
        header_ok = secrets.compare_digest(request.headers.get("x-campus-acceptance", ""), cfg["tunnel_key"])
        cookie_ok = secrets.compare_digest(request.cookies.get("acceptance_gate", ""), cfg["tunnel_key"])
        if not header_ok and not cookie_ok:
            return Response(status_code=404)
        result = await call_next(request)
        # Browser download managers do not forward Playwright's extra request headers.
        # This gate is additional to (and cannot replace) the website's login cookie.
        if header_ok and not cookie_ok:
            result.set_cookie("acceptance_gate", cfg["tunnel_key"], httponly=True, samesite="strict", max_age=540)
        return result

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    server = uvicorn.Server(uvicorn.Config(campus.app, log_level="error", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        if task.done():
            await task
            raise RuntimeError("Fixture could not start")
        await asyncio.sleep(.05)
    print("READY " + str(sock.getsockname()[1]), flush=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    loop.add_reader(sys.stdin.fileno(), stop.set)
    try:
        await asyncio.wait_for(stop.wait(), timeout=540)
    except asyncio.TimeoutError:
        pass
    finally:
        loop.remove_reader(sys.stdin.fileno())
        server.should_exit = True
        await task
        sock.close()
        engine.dispose()
        print("USAGE " + json.dumps(dict(zip(("attempted","successful","input_tokens","output_tokens"), calls))), flush=True)


def main():
    cfg = json.loads(sys.stdin.buffer.readline())
    origin = cfg["origin"]
    if urlsplit(origin).hostname != "127.0.0.1":
        raise ValueError("Local test origin required")
    base = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if cfg["max_calls"]:
        settings = json.loads(Path("/etc/ai-examiner/runtime.json").read_text())
        key = settings["DASHSCOPE_API_KEY"]
        base = settings.get("DASHSCOPE_BASE_URL", base)
        del settings
    else:
        key = "fixture-no-network"
    dest = urlsplit(base)
    if dest.scheme != "https" or not (dest.hostname or "").endswith(".aliyuncs.com") or dest.username:
        raise ValueError("Refusing unexpected provider destination")
    os.chdir("/tmp")
    nobody = pwd.getpwnam("nobody")
    os.setgroups([])
    os.setgid(nobody.pw_gid)
    os.setuid(nobody.pw_uid)
    os.environ.clear()
    os.environ.update(PATH="/usr/local/bin:/usr/bin:/bin", LANG="C.UTF-8", PYTHONDONTWRITEBYTECODE="1")
    with tempfile.TemporaryDirectory(prefix="campus-acceptance-") as tmp:
        root = Path(tmp).resolve()
        os.chdir(root)
        source = Path("/opt/ai-examiner")
        if (source / "prompts").is_dir():
            shutil.copytree(source / "prompts", root / "prompts")
        else:
            (root / "prompts").mkdir()
        sys.path[:0] = ["/opt/examiner-campus-web", str(source / "src")]
        os.environ.update(APP_ENV="test", AUTH_MODE="oidc", DATABASE_SCHEMA_MANAGEMENT="external",
            DATABASE_URL="sqlite:///" + str(root / "test.sqlite3"), STORAGE_BACKEND="local",
            MODEL_PROVIDER="qwen", DASHSCOPE_API_KEY=key, DASHSCOPE_BASE_URL=base, QWEN_TEXT_MODEL="qwen-plus",
            QWEN_REQUEST_TIMEOUT_SECONDS="120", QWEN_ENABLE_THINKING="false", MAX_MODEL_RETRIES="0",
            MODEL_RATE_LIMIT_BACKEND="memory", CELERY_ALWAYS_EAGER="true", CELERY_BROKER_URL="memory://",
            CELERY_RESULT_BACKEND="cache+memory://", JOB_MAX_ATTEMPTS="1", AUDIT_IP_HASH_KEY=secrets.token_hex(32),
            MEMORY_IDENTITY_SECRET=secrets.token_hex(32), CAMPUS_ORIGIN=origin, CAMPUS_UPSTREAM="http://127.0.0.1:1",
            CAMPUS_IDENTITY_ENABLED="1", CAMPUS_ACCOUNTS_DB=str(root / "accounts.sqlite3"), HOME=str(root))
        logging.disable(logging.CRITICAL)
        asyncio.run(serve(root, cfg))
        os.chdir("/tmp")


if __name__ == "__main__":
    main()
