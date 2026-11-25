"""Run the teacher/student browser journey in a private clone of the deployed application."""
import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import select
import socketserver
import subprocess
import sys
import threading
import time

import paramiko

OPS = Path(__file__).resolve().parent


class Forwarder(socketserver.ThreadingTCPServer):
    daemon_threads = True


class Forward(socketserver.BaseRequestHandler):
    def handle(self):
        channel = self.server.transport.open_channel("direct-tcpip",
            ("127.0.0.1", self.server.remote_port), self.client_address, timeout=6)
        try:
            while True:
                ready, _, _ = select.select([self.request, channel], [], [], 12)
                for origin in ready:
                    data = origin.recv(65536)
                    if not data:
                        return
                    (channel if origin is self.request else self.request).sendall(data)
        except (OSError, EOFError):
            pass
        finally:
            channel.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-modules", type=Path, help="installed Playwright package directory parent")
    parser.add_argument("--browser-channel", default="msedge")
    parser.add_argument("--max-calls", type=int, choices=range(0,9), default=8)
    parser.add_argument("--scope", choices=("full","download","feedback","speed"), default="full")
    parser.add_argument("--speed-arm", choices=("both","short","full"), default="both",
                        help="Select the original six-question flow or the one-question override for a speed run")
    args = parser.parse_args()
    limit = args.max_calls
    if args.scope == "download":
        limit = 0
    elif args.scope == "speed":
        limit = min(3, limit)
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    fixture = (OPS / "teacher_account.py").read_text(encoding="utf-8")
    source = ("import sys, types\nmod=types.ModuleType('teacher_fixture')\n"
              "sys.modules[mod.__name__]=mod\nexec("+repr(fixture)+",mod.__dict__)\n"
              + (OPS/"acceptance_service.py").read_text(encoding="utf-8")).encode()
    with Forwarder(("127.0.0.1", 0), Forward) as tunnel, paramiko.SSHClient() as ssh:
        cfg = {"origin":f"http://127.0.0.1:{tunnel.server_address[1]}", "password":secrets.token_urlsafe(26),
               "tunnel_key":secrets.token_urlsafe(32),"browser_channel":args.browser_channel,
               "scope":args.scope, "max_calls":limit, "speed_arm":args.speed_arm,
               "download_fixture":"这是一份人工编写的合成材料，仅用于复验学生端的附件下载，不代表真实研究结果。"}
        ssh.load_host_keys(str(Path.home()/".ssh/known_hosts"))
        ssh.connect("u3ssh.casdao.com",port=54653,username="root",password=getpass.getpass("SSH password: "),
                    look_for_keys=False,allow_agent=False,timeout=12)
        transport = ssh.get_transport()
        transport.set_keepalive(20)
        channel = transport.open_session(timeout=10)
        channel.set_combine_stderr(True)
        channel.exec_command("""/opt/ai-examiner/.venv/bin/python -Bu -c "import sys; b=sys.stdin.buffer; exec(compile(b.read(int(b.readline())), '<campus-test>', 'exec'))" """)
        stream=channel.makefile("rb")
        channel.sendall(str(len(source)).encode()+b"\n"+source+json.dumps(cfg).encode()+b"\n")
        channel.settimeout(65)
        while line := stream.readline():
            line=line.decode(errors="replace").strip()
            if line.startswith("READY "):
                tunnel.remote_port = int(line.split()[1])
                break
            print(line[:400])
        else:
            raise RuntimeError("Isolated service did not start")
        channel.settimeout(610)
        tunnel.transport = transport
        def output():
            try:
                for line in stream:
                    print(line.decode(errors="replace").strip()[:400])
            except (OSError, EOFError):
                pass
        logs=threading.Thread(target=output,daemon=True)
        logs.start()
        threading.Thread(target=tunnel.serve_forever,daemon=True).start()
        print("Isolated campus fixture ready. Opening fresh headless browser contexts.")
        env={**os.environ}
        if args.node_modules:
            env["NODE_PATH"]=str(args.node_modules.resolve())
        try:
            completed=subprocess.run(["node",str(OPS/"teacher_browser.cjs")],
                input=json.dumps(cfg).encode(),env=env,timeout=480)
        finally:
            channel.shutdown_write()
            tunnel.shutdown()
            logs.join(25)
            if not channel.exit_status_ready():
                until=time.monotonic()+5
                while not channel.exit_status_ready() and time.monotonic()<until:
                    time.sleep(.1)
            if not channel.exit_status_ready() or channel.recv_exit_status()!=0:
                raise RuntimeError("Isolated service shutdown not confirmed")
    return completed.returncode


if __name__=="__main__":
    raise SystemExit(main())
