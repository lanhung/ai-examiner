"""Only bind the approved port as root; drop groups/UID before importing the app."""
import os
import pwd
import socket
import json
import sys
from pathlib import Path


if __name__ == "__main__":
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", int(os.environ["CAMPUS_PORT"])))
    # Read only identity configuration while privileged. Do not load provider or WeChat keys.
    runtime=json.loads(Path("/etc/ai-examiner/runtime.json").read_text())
    for key in ("DATABASE_URL","AUTH_MODE","APP_ENV","DATABASE_SCHEMA_MANAGEMENT",
                "POSTGRES_RLS_MODE","OIDC_SESSION_COOKIE_NAME","OIDC_SESSION_MAX_MINUTES",
                "OIDC_SESSION_IDLE_MINUTES","AUDIT_IP_HASH_KEY"):
        if key in runtime:os.environ[key]=str(runtime[key])
    del runtime
    os.environ["CAMPUS_IDENTITY_ENABLED"]="1"
    os.environ["CAMPUS_ACCOUNTS_DB"]="/var/lib/examiner-campus-web/accounts.sqlite3"
    # Shared settings create these folders on import; keep them out of the old project.
    for key in ("UPLOAD_DIR","EVIDENCE_DIR","EXPORT_DIR","BACKUP_DIR","STORAGE_LOCAL_ROOT","PROMPT_DIR"):
        os.environ[key]="/var/lib/examiner-campus-web/runtime/"+key.lower()
    sys.path.insert(0,"/opt/ai-examiner/src")
    os.umask(0o077)
    if os.geteuid()==0:
        account=pwd.getpwnam("nobody")
        os.setgroups([])
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    import uvicorn
    uvicorn.run("campus:app", fd=sock.fileno(), access_log=False, proxy_headers=False)
