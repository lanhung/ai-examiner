import asyncio
import json
from uuid import uuid4

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
import campus as c
from passwords import PasswordStore

H={"X-Campus-Request":"1"}
ID=str(uuid4())
DATA={"username":"acceptance","nickname":"验收账号","password":"Long-fixture-password-123","confirm_password":"Long-fixture-password-123"}


class Bridge:
    cookie_name="original_sid"
    def __init__(self):self.revoked=[]
    def issue(self,account):return "fixture-backend-token"
    def revoke(self,token):self.revoked.append(token)
    def workspace(self,token,role):
        if role=="teacher":raise HTTPException(403,"denied")
        return "own"


@pytest.fixture
def site(tmp_path):
    calls=[]
    def up(req):
        calls.append(req)
        if req.url.path=="/health":
            return httpx.Response(200,json={"provider":"qwen","provider_ready":True})
        assert req.headers.get("cookie")=="original_sid=fixture-backend-token"
        assert "authorization" not in req.headers
        return httpx.Response(200,json={"teacher":False,"principal_id":ID,"id":ID})
    for t in (c.sessions,c.limits):t.clear()
    client=TestClient(c.app,base_url=c.ORIGIN)
    remote=httpx.AsyncClient(transport=httpx.MockTransport(up))
    c.app.state.client=remote
    c.app.state.bridge=Bridge()
    c.app.state.passwords=PasswordStore(tmp_path/"accounts.sqlite3")
    yield client,calls
    client.close();asyncio.run(remote.aclose())


def login(client):
    assert client.post("/api/register",headers=H,json=DATA).status_code==201
    r=client.post("/api/login",headers=H,json={k:DATA[k] for k in ("username","password")})
    assert r.status_code==200
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=strict" in r.headers["set-cookie"]
    assert "fixture-backend-token" not in str(r.headers)+r.text
    return r


def test_public(site):
    client,calls=site
    assert client.get("/").status_code==200
    assert client.get("/api/me").json()["user"] is None
    assert len(client.get("/api/samples").json())==3
    assert client.get("/gateway/api/v1/school/exams").status_code==401
    assert client.post("/api/pair",headers=H).status_code in (404,405)
    assert not calls


def test_passwords_persist_and_are_not_plaintext(site):
    client,calls=site;login(client)
    store=c.app.state.passwords
    assert DATA["password"].encode() not in store.path.read_bytes()
    with store.connect() as db:
        r=db.execute("SELECT * FROM accounts").fetchone()
        assert r["salt"] and r["password_hash"]!=DATA["password"]
    new=PasswordStore(store.path)
    assert new.verify("ACCEPTANCE",DATA["password"])["username"]=="acceptance"
    assert client.post("/api/register",headers=H,json={**DATA,"username":"ACCEPTANCE"}).status_code==409


def test_origin_and_validation(site):
    client,_=site
    assert client.post("/api/register",json=DATA).status_code==403
    assert client.post("/api/register",json=DATA,headers={**H,"Origin":"https://foreign.example"}).status_code==403
    for p in ({**DATA,"password":"short"},{**DATA,"confirm_password":"Other-password-456"},{**DATA,"teacher":True},{**DATA,"username":"../admin"}):
        r=client.post("/api/register",headers=H,json=p)
        assert r.status_code==422 and DATA["password"] not in r.text


def test_login_logout_isolation(site):
    client,calls=site;login(client)
    assert client.get("/api/me").json()["user"]["username"]=="acceptance"
    assert client.get("/gateway/api/v1/school/exams").status_code==200
    other=TestClient(c.app,base_url=c.ORIGIN)
    assert other.get("/api/me").json()["user"] is None
    assert other.get("/gateway/api/projects").status_code==401
    assert client.post("/api/logout",headers=H).is_success
    assert c.app.state.bridge.revoked==["fixture-backend-token"]
    assert client.get("/gateway/api/projects").status_code==401
    other.close()


def test_wrong_password_and_rate_limit(site):
    client,_=site;login(client)
    for _ in range(11):
        assert client.post("/api/login",headers=H,json={"username":DATA["username"],"password":"bad"}).status_code==401
    assert client.post("/api/login",headers=H,json={"username":DATA["username"],"password":"bad"}).status_code==429


def test_restrictions(site):
    client,calls=site;login(client)
    assert client.get("/gateway/api/v1/organizations").status_code==404
    assert client.get("/gateway/api/projects?organization_id=other").status_code==422
    assert client.post("/gateway/api/v1/school/workspace/teacher",headers=H).status_code==403
    assert client.get("/gateway/api/projects",headers={"X-Campus-Role":"teacher"}).status_code==403
    key=str(uuid4())
    assert client.post("/gateway/api/projects/"+ID+"/blueprints/async",headers={**H,"X-AI-Examiner-Organization":"other","Idempotency-Key":key},json={"profile":"mock","document_id":ID}).status_code==200
    assert calls[-1].headers["X-AI-Examiner-Organization"]=="own"
    assert json.loads(calls[-1].content)["profile"]=="qwen:qwen-plus"


def test_school_contracts(site):
    client,calls=site;login(client)
    for suffix,body in [("/exams/"+ID+"/join",{"student_name":"例"}),("/attempts/"+ID+"/answers/async",{"position":0,"request_id":ID,"answer":"测试"})]:
        assert client.post("/gateway"+c.SCHOOL+suffix,headers=H,json=body).is_success
        assert calls[-1].url.path==c.SCHOOL+suffix and json.loads(calls[-1].content)==body
    assert "X-AI-Examiner-Organization" not in calls[-1].headers


def test_report_read_only_needs_the_authorized_workspace_not_model_health(site):
    client,calls=site;login(client)
    calls.clear()
    path=f"/api/sessions/{ID}/report"
    assert client.get("/gateway"+path,headers={"X-AI-Examiner-Organization":"other"}).is_success
    assert [r.url.path for r in calls]==[path]
    assert calls[0].headers["X-AI-Examiner-Organization"]=="own"
    assert client.get("/gateway"+path,headers={"X-Campus-Role":"teacher"}).status_code==403
    assert len(calls)==1


def test_expiry_and_disable(site):
    client,_=site;login(client)
    saved=next(iter(c.sessions.values()))
    old=saved["exp"]
    assert client.get("/gateway/api/projects").is_success and saved["exp"]>=old
    with c.app.state.passwords.connect() as db:db.execute("UPDATE accounts SET active=0")
    assert client.get("/gateway/api/projects").status_code==401
    assert not c.sessions


def test_idle_expiry(site):
    client,_=site;login(client)
    next(iter(c.sessions.values()))["exp"]=0
    assert client.get("/gateway/api/projects").status_code==401


def test_disabled_registration(site):
    client,_=site;c.app.state.bridge=None
    assert client.post("/api/register",headers=H,json=DATA).status_code==503
