"""Export a NEW DevTools project; the original is read-only, including its app.json."""
import argparse
import json
from pathlib import Path
import shutil
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]


def export(source:Path,dest:Path,origin:str):
    source=source.resolve();dest=dest.resolve()
    u=urlsplit(origin)
    if u.scheme!="https" or not u.hostname or u.username or u.password or u.path not in ("","/") or u.query or u.fragment:
        raise ValueError("Use the exact HTTPS website origin")
    if dest.exists() or source in dest.parents or dest in source.parents:
        raise ValueError("Choose a NEW directory outside the original mini-program")
    conf=json.loads((source/"project.config.json").read_text(encoding="utf-8-sig"))
    mini=(source/conf.get("miniprogramRoot","miniprogram")).resolve()
    if source not in mini.parents: raise ValueError("Unexpected mini-program root")
    manifest=json.loads((mini/"app.json").read_text(encoding="utf-8-sig"))
    route="pages/web-confirm/index"
    if route in manifest["pages"]:raise ValueError("Project already contains a companion")
    dest.mkdir(parents=True)
    target=dest/"miniprogram"
    shutil.copytree(mini,target,ignore=shutil.ignore_patterns(".env*", "*.log","*.pem", "*.key", ".git","node_modules"))
    conf.update(miniprogramRoot="miniprogram/",projectname="ai-examiner-campus-companion")
    (dest/"project.config.json").write_text(json.dumps(conf,ensure_ascii=False,indent=2),encoding="utf-8")
    manifest["pages"].append(route)
    (target/"app.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    entry=target/"pages/school/index.wxml"
    with entry.open("a",encoding="utf-8") as f:f.write('\n<navigator class="page" url="/pages/web-confirm/index"><button>网页登录</button></navigator>\n')
    page=target/"pages/web-confirm"
    shutil.copytree(ROOT/"companion",page)
    (page/"endpoint.js").write_text("module.exports = {origin:"+json.dumps(origin.rstrip("/"))+"};\n",encoding="utf-8")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("source",type=Path);p.add_argument("dest",type=Path);p.add_argument("origin")
    a=p.parse_args();export(a.source,a.dest,a.origin)
