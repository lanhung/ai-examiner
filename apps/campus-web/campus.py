"""Password-authenticated browser gateway over the shared exam service."""
import hashlib
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pydantic import ConfigDict, model_validator
from starlette.concurrency import run_in_threadpool
from passwords import PasswordStore
from samples import SAMPLES

ROOT = Path(__file__).resolve().parent
ORIGIN = os.getenv("CAMPUS_ORIGIN", "http://127.0.0.1:8031").rstrip("/")
API = os.getenv("CAMPUS_UPSTREAM", "https://classic-merry-6705-8000.east3.casdao.com:2005").rstrip("/")
if urlsplit(API).scheme != "https" and urlsplit(API).hostname not in {"127.0.0.1","localhost"}:
    raise ValueError("Remote upstream requires HTTPS")
if urlsplit(ORIGIN).scheme != "https" and urlsplit(ORIGIN).hostname not in {"127.0.0.1","localhost"}:
    raise ValueError("Public browser origin requires HTTPS")
HTTPS = ORIGIN.startswith("https://")
SID = ("__Host-" if HTTPS else "")+"campus_sid"
PROFILE = "qwen:qwen-plus"
UUID = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
SCHOOL = "/api/v1/school"
sessions, limits = {}, {}


@asynccontextmanager
async def lifespan(app):
    app.state.passwords=PasswordStore(os.getenv("CAMPUS_ACCOUNTS_DB",str(ROOT/"var"/"accounts.sqlite3")))
    app.state.bridge=None
    if os.getenv("CAMPUS_IDENTITY_ENABLED")=="1":
        from identity_bridge import IdentityBridge
        app.state.bridge=IdentityBridge()
    async with httpx.AsyncClient(base_url=API, timeout=httpx.Timeout(95,connect=8),follow_redirects=False) as client:
        app.state.client=client
        yield


app=FastAPI(title="答辩学堂",lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)


@app.exception_handler(RequestValidationError)
async def invalid_request(req,exc):
    # Never return Pydantic's input field: it may contain a password.
    return JSONResponse({"detail":"请检查输入：用户名为 3–32 位字母、数字或下划线；新密码为 12–128 位，两次输入一致。"},status_code=422)


def sweep():
    now=time.monotonic()
    for table in (sessions,limits):
        for key in [k for k,v in table.items() if v["exp"]<=now]:
            del table[key]


def rate(req,action,limit):
    # Ignore arbitrary forwarded IPs. A trusted reverse proxy can supply the ASGI client.
    key=(req.client.host if req.client else "-",action)
    bucket=limits.setdefault(key,{"exp":time.monotonic()+60,"count":0})
    bucket["count"]+=1
    if bucket["count"]>limit:
        raise HTTPException(429,"操作太频繁，请稍后再试")


@app.middleware("http")
async def safety(req:Request,next_call):
    if req.url.path.startswith(("/api/","/gateway/")):
        sweep()
        if req.method not in {"GET","HEAD"} and (req.headers.get("x-campus-request")!="1" or
            req.headers.get("origin") not in {None,ORIGIN}):
            return JSONResponse({"detail":"请求来源无效"},status_code=403)
        if req.method not in {"GET","HEAD"} and req.headers.get("sec-fetch-site")=="cross-site":
            return JSONResponse({"detail":"请求来源无效"},status_code=403)
    res=await next_call(req)
    res.headers.update({"X-Content-Type-Options":"nosniff","Referrer-Policy":"no-referrer",
        "Content-Security-Policy":"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"})
    if req.url.path.startswith(("/api/","/gateway/")):
        res.headers["Cache-Control"]="no-store"
    return res


def cookie(res,name,value,age):
    res.set_cookie(name,value,max_age=age,httponly=True,secure=HTTPS,samesite="strict",path="/")


def session_key(req):
    return hashlib.sha256(req.cookies.get(SID,"").encode()).hexdigest()


def session(req):
    s=sessions.get(session_key(req))
    now=time.monotonic()
    if not s or s["exp"]<=now or s["absolute"]<=now or not req.app.state.passwords.active(s["account"]["id"]):
        sessions.pop(session_key(req),None)
        raise HTTPException(401,"登录已过期，请使用账号密码重新登录")
    s["exp"]=min(now+7200,s["absolute"])
    return s


async def upstream(req,method,path,token=None,headers=None,**kwargs):
    h={"Cookie":req.app.state.bridge.cookie_name+"="+token} if token else {}
    try:
        # Build each request without a shared client's ambient cookie jar.
        request=httpx.Request(method,API+path,headers={**h,**(headers or {})},**kwargs)
        r=await req.app.state.client.send(request)
    except httpx.HTTPError:
        raise HTTPException(502,"暂时无法连接答辩服务。写操作请先查询进度，不要重复提交。") from None
    if 300<=r.status_code<400:
        raise HTTPException(502,"服务地址返回了意外跳转")
    return r


@app.get("/api/me")
async def me(req:Request):
    if not sessions.get(session_key(req)):
        return {"user":None,"registration_available":req.app.state.bridge is not None}
    r=await upstream(req,"GET",SCHOOL+"/me",session(req)["token"])
    if r.status_code==401:
        sessions.pop(session_key(req),None)
        return {"user":None}
    if not r.is_success:
        raise HTTPException(r.status_code,"当前账号不能进入考试大厅")
    return {"user":{**r.json(),"username":session(req)["account"]["username"],
                    "nickname":session(req)["account"]["nickname"]}}


@app.get("/api/samples")
async def samples():
    return [{"id":f"sample-{i+1}","title":t,"subject":s,"teacher_name":a,"material_text":m,"material_name":t+".txt","question_count":len(q),"status":"sample","questions":q}
            for i,(t,s,a,m,q) in enumerate(SAMPLES)]


class Login(BaseModel):
    model_config=ConfigDict(extra="forbid")
    username:str=Field(min_length=3,max_length=32,pattern=r"^[A-Za-z0-9_]+$")
    password:str=Field(min_length=1,max_length=128)


class Registration(Login):
    nickname:str=Field(min_length=1,max_length=40)
    confirm_password:str=Field(min_length=12,max_length=128)

    @model_validator(mode="after")
    def valid_password(self):
        if len(self.password)<12 or not self.password.strip() or self.password!=self.confirm_password:
            raise ValueError("密码至少 12 位，且两次输入须一致")
        if not self.nickname.strip():
            raise ValueError("请填写显示名称")
        return self


def credentials_guard(req,username,kind):
    if req.app.state.bridge is None:
        raise HTTPException(503,"账号服务尚未配置，请访问已部署的网站")
    store=req.app.state.passwords
    store.check_rate(kind+"-ip",req.client.host if req.client else "-",50 if kind=="login" else 12)
    store.check_rate(kind+"-account",username.lower(),12 if kind=="login" else 4)
    return store


@app.post("/api/register",status_code=201)
def register(p:Registration,req:Request):
    store=credentials_guard(req,p.username,"register")
    store.register(p.username,p.nickname.strip(),p.password)
    return {"registered":True}


@app.post("/api/login")
def login(p:Login,req:Request,res:Response):
    store=credentials_guard(req,p.username,"login")
    account=store.verify(p.username,p.password)
    try:
        token=req.app.state.bridge.issue(account)
    except HTTPException:raise
    except Exception:
        raise HTTPException(503,"账号已保留，但空间服务暂时不可用，请稍后登录") from None
    old=sessions.pop(session_key(req),None)
    if old:
        req.app.state.bridge.revoke(old["token"])
    sid=secrets.token_urlsafe(32);now=time.monotonic()
    sessions[hashlib.sha256(sid.encode()).hexdigest()]={"token":token,"account":account,"exp":now+7200,"absolute":now+86400}
    cookie(res,SID,sid,86400)
    return {"ok":True}


@app.post("/api/logout")
async def logout(req:Request,res:Response):
    s=sessions.pop(session_key(req),None)
    cookie(res,SID,"",0)
    if s:
        await run_in_threadpool(req.app.state.bridge.revoke,s["token"])
    return {"ok":True}


@app.get("/api/material/{exam_id}")
async def material(exam_id:str,req:Request):
    s=session(req)
    if not re.fullmatch(UUID,exam_id):
        raise HTTPException(404,"材料不存在")
    request=httpx.Request("GET",API+SCHOOL+"/exams/"+exam_id+"/material",
                          headers={"Cookie":req.app.state.bridge.cookie_name+"="+s["token"]})
    try:
        r=await req.app.state.client.send(request,stream=True)
    except httpx.HTTPError:
        raise HTTPException(502,"材料服务暂时不可用") from None
    if r.status_code!=200:
        await r.aclose()
        raise HTTPException(r.status_code if r.status_code>=400 else 502,"无法下载此考试材料")
    cd=r.headers.get("content-disposition","attachment")
    return StreamingResponse(r.aiter_bytes(),media_type="application/octet-stream",
        headers={"Content-Disposition":cd if cd.lower().startswith("attachment") else "attachment"},
        background=BackgroundTask(r.aclose))


# Exact, method-specific routes. No arbitrary backend URL, headers, admin API or tenant selector.
ROUTES={
"GET":[SCHOOL+r"/(?:teacher/)?exams",SCHOOL+rf"/(?:teacher/)?exams/{UUID}",SCHOOL+rf"/teacher/exams/{UUID}/(?:grades|preview)",SCHOOL+rf"/(?:attempts|teacher/(?:attempts|previews))/{UUID}",r"/api/projects",rf"/api/projects/{UUID}/documents",rf"/api/v1/jobs/{UUID}",rf"/api/sessions/{UUID}(?:/report)?",rf"/api/projects/{UUID}/(?:blueprint|document)-task",rf"/api/sessions/{UUID}/operations/{UUID}"],
"POST":[SCHOOL+r"/workspace/(?:student|teacher)",SCHOOL+"/teacher/exams",SCHOOL+rf"/exams/{UUID}/join",SCHOOL+rf"/teacher/exams/{UUID}/(?:preview|close)",SCHOOL+rf"/(?:attempts|teacher/previews)/{UUID}/answers/async",SCHOOL+rf"/teacher/attempts/{UUID}/review(?:-answer)?",r"/api/projects",rf"/api/projects/{UUID}/(?:documents|blueprints)/async",r"/api/sessions",rf"/api/sessions/{UUID}/operations"]}


@app.api_route("/gateway/{rest:path}",methods=["GET","POST"])
async def gateway(rest:str,req:Request):
    s=session(req); path="/"+rest
    if not any(re.fullmatch(p,path) for p in ROUTES[req.method]):
        raise HTTPException(404,"不支持的入口")
    params=dict(req.query_params)
    if params.keys()-{"offset","document_id","request_id"}:
        raise HTTPException(422,"无效查询")
    if path.startswith(SCHOOL+"/workspace/"):
        role=path.rsplit("/",1)[-1]
        org=await run_in_threadpool(req.app.state.bridge.workspace,s["token"],role)
        health=await upstream(req,"GET","/health")
        ready=health.is_success and health.json().get("provider")=="qwen" and health.json().get("provider_ready") is True
        return {"organization_id":org,"profile":PROFILE,"model_ready":ready}
    h={}; payload={}
    if req.method=="POST":
        kind=req.headers.get("content-type","")
        limit=21*1024**2 if path.endswith("/documents/async") else 100000
        buf=bytearray()
        async for chunk in req.stream():
            if len(buf)+len(chunk)>limit:
                raise HTTPException(413,"提交内容过大")
            buf.extend(chunk)
        if path.endswith("/documents/async"):
            if not kind.startswith("multipart/form-data;"):
                raise HTTPException(415,"需要表单文件")
            payload={"content":bytes(buf)}; h["Content-Type"]=kind
        elif buf:
            try:
                data=json.loads(buf)
                if not isinstance(data,dict): raise ValueError()
            except ValueError:
                raise HTTPException(422,"需要 JSON 对象") from None
            if path.endswith("/blueprints/async") or path in {"/api/sessions",SCHOOL+"/teacher/exams"}:
                data["profile"]=PROFILE
            payload={"json":data}
        ik=req.headers.get("idempotency-key")
        if ik and re.fullmatch(UUID,ik): h["Idempotency-Key"]=ik
    if not path.startswith(SCHOOL+"/"):
        role=req.headers.get("x-campus-role","student")
        if role not in {"teacher","student"}:
            raise HTTPException(422,"角色无效")
        h["X-AI-Examiner-Organization"]=await run_in_threadpool(req.app.state.bridge.workspace,s["token"],role)
    r=await upstream(req,req.method,path,s["token"],headers=h,params=params,**payload)
    if r.status_code==401: sessions.pop(session_key(req),None)
    if "application/json" not in r.headers.get("content-type",""):
        raise HTTPException(502,"答辩服务未返回有效数据，请刷新确认结果")
    return Response(r.content,status_code=r.status_code,media_type="application/json")


app.mount("/",StaticFiles(directory=ROOT/"web",html=True),name="campus")
