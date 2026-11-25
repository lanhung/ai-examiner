"""Deploy a new service only; refuse occupied ports, existing directories/configs."""
import argparse
import getpass
import hashlib
from pathlib import Path

import paramiko

ROOT=Path(__file__).resolve().parents[1]
DEST="/opt/examiner-campus-web"
CONF="/etc/supervisor/conf.d/examiner-campus-web.conf"
PY="/opt/ai-examiner/.venv/bin/python"


def run(ssh,cmd):
    _,out,err=ssh.exec_command(cmd,timeout=30)
    text=out.read().decode()
    if out.channel.recv_exit_status():
        raise RuntimeError((err.read().decode() or text or "remote check failed")[:1200])
    return text.strip()


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--install",action="store_true")
    parser.add_argument("--port",type=int,choices=(80,6008),default=6008)
    args=parser.parse_args()
    port=str(args.port)
    public="https://classic-merry-6705-"+port+".east3.casdao.com:2005"
    with paramiko.SSHClient() as ssh:
        ssh.load_host_keys(str(Path.home()/".ssh/known_hosts"))
        ssh.connect("u3ssh.casdao.com",port=54653,username="root",password=getpass.getpass("SSH password: "),timeout=12,allow_agent=False,look_for_keys=False)
        print(run(ssh, "ss -ltnp '( sport = :6008 or sport = :80 )'"))
        print(run(ssh,"curl -fsS -o /dev/null -w 'Original API: %{http_code}' http://127.0.0.1:8001/ready"))
        if run(ssh,"ss -H -ltn 'sport = :"+port+"'"):
            print(port+" already in use; nothing installed.")
            raise SystemExit(2)
        run(ssh,"test ! -e "+DEST+" && test ! -e "+CONF+" && test -d /etc/supervisor/conf.d && id nobody && "+PY+" -c 'import fastapi,httpx,uvicorn'")
        print("Port and new paths free; dependencies available.")
        if args.install:
            files=[ROOT/p for p in ("campus.py","samples.py","serve_linux.py","passwords.py","identity_bridge.py")]+[f for f in (ROOT/"web").rglob("*") if f.is_file()]
            if not (ROOT/"web/app.js").is_file():
                raise RuntimeError("Incomplete source")
            run(ssh,"mkdir -m 755 "+DEST)
            run(ssh,"install -d -m 700 -o nobody -g nogroup /var/lib/examiner-campus-web")
            with ssh.open_sftp() as ftp:
                for folder in ["web","web/icons"]:
                    ftp.mkdir(DEST+"/"+folder,0o755)
                for f in files:
                    remote=DEST+"/"+f.relative_to(ROOT).as_posix()
                    ftp.put(str(f),remote)
                    with ftp.open(remote,"rb") as check:
                        assert hashlib.sha256(check.read()).digest()==hashlib.sha256(f.read_bytes()).digest()
                    ftp.chmod(remote,0o644)
                conf=("[program:examiner-campus-web]\ndirectory="+DEST+"\ncommand="+PY+" "+DEST+"/serve_linux.py\n"
                      "environment=CAMPUS_PORT=\""+port+"\",CAMPUS_ORIGIN=\""+public+"\",CAMPUS_UPSTREAM=\"http://127.0.0.1:8001\",PYTHONDONTWRITEBYTECODE=\"1\"\nautostart=true\nautorestart=true\nstartsecs=2\n")
                with ftp.open(CONF,"wx") as out:
                    out.write(conf)
            run(ssh,"supervisorctl reread && supervisorctl add examiner-campus-web")
            print(run(ssh,"supervisorctl status examiner-campus-web"))
