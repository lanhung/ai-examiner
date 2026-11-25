"""Read-only authentication deployment preflight. Never prints configuration values."""
import getpass
import json
from pathlib import Path
import paramiko

with paramiko.SSHClient() as ssh:
    ssh.load_host_keys(str(Path.home()/".ssh/known_hosts"))
    ssh.connect("u3ssh.casdao.com",port=54653,username="root",password=getpass.getpass("SSH password: "),timeout=12,allow_agent=False,look_for_keys=False)
    code = """
import json,subprocess
from pathlib import Path
p=Path('/etc/ai-examiner/runtime.json')
v=json.loads(p.read_text())
print('Config key names:', sorted(v))
for p in [Path('/opt/ai-examiner/src'),Path('/opt/examiner-campus-web'),Path('/etc/supervisor/conf.d/examiner-campus-web.conf')]:
 print(str(p),p.exists(),oct(p.stat().st_mode & 0o777))
print(subprocess.check_output(['supervisorctl','status','examiner-campus-web','examiner-api'],text=True))
"""
    stdin,out,err=ssh.exec_command("python3 -",timeout=30)
    stdin.write(code);stdin.channel.shutdown_write()
    print(out.read().decode())
    if out.channel.recv_exit_status():raise RuntimeError("preflight failed")
