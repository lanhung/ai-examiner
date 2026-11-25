"""Scoped, hash-guarded upgrade of the new campus site, with old site untouched."""
import getpass
import hashlib
import json
from pathlib import Path
import zipfile
import paramiko

ROOT=Path(__file__).resolve().parents[1]
DEST="/opt/examiner-campus-web"
PY="/opt/ai-examiner/.venv/bin/python"
CHANGED=["campus.py","serve_linux.py","web/app.js","web/style.css"]
ADDED=["passwords.py","identity_bridge.py"]

with zipfile.ZipFile(ROOT.parent/"output/examiner-campus-web-20261116.zip") as z:
    base={p:hashlib.sha256(z.read(p)).hexdigest() for p in CHANGED}
new={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in CHANGED+ADDED}
with paramiko.SSHClient() as ssh:
    ssh.load_host_keys(str(Path.home()/".ssh/known_hosts"))
    ssh.connect("u3ssh.casdao.com",port=54653,username="root",password=getpass.getpass("SSH password: "),timeout=12,allow_agent=False,look_for_keys=False)
    with ssh.open_sftp() as sftp:
        for name in CHANGED:
            with sftp.open(DEST+"/"+name,"rb") as f:
                if hashlib.sha256(f.read()).hexdigest()!=base[name]:
                    raise RuntimeError("Deployed file changed; stop: "+name)
        for name in ADDED:
            try:sftp.stat(DEST+"/"+name)
            except FileNotFoundError:pass
            else:raise RuntimeError("Already exists: "+name)
        for name in CHANGED+ADDED:
            sftp.put(str(ROOT/name),DEST+"/"+name+".auth-stage")
            sftp.chmod(DEST+"/"+name+".auth-stage",0o644)
    code="""
import hashlib,json,os,pwd,shutil,subprocess,time,urllib.request
from pathlib import Path
from datetime import datetime
root=Path('/opt/examiner-campus-web')
base=BASE
target=TARGET
for name,digest in target.items():
 p=root/(name+'.auth-stage')
 assert hashlib.sha256(p.read_bytes()).hexdigest()==digest
 if name in base:assert hashlib.sha256((root/name).read_bytes()).hexdigest()==base[name]
 else:assert not (root/name).exists()
 if name.endswith('.py'):compile(p.read_bytes(),name,'exec')
account=pwd.getpwnam('nobody')
storage=Path('/var/lib/examiner-campus-web')
storage.mkdir(mode=0o700,exist_ok=True)
os.chown(storage,account.pw_uid,account.pw_gid)
os.chmod(storage,0o700)
backup=Path('/var/backups')/('campus-password-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir(mode=0o700)
for name in base:
 (backup/name).parent.mkdir(parents=True,exist_ok=True)
 shutil.copy2(root/name,backup/name)
for name in target:os.replace(root/(name+'.auth-stage'),root/name)
try:
 subprocess.run(['supervisorctl','restart','examiner-campus-web'],check=True,timeout=35)
 for _ in range(20):
  try:
   with urllib.request.urlopen('http://127.0.0.1/api/me',timeout=3) as r:state=json.load(r)
   if state.get('registration_available') is True:break
  except Exception:pass
  time.sleep(1)
 else:raise RuntimeError('Account service not ready')
 with urllib.request.urlopen('http://127.0.0.1:8001/ready',timeout=4) as r:assert r.status==200
 print('Password service ready; original service ready; backup:',backup)
except Exception:
 for name in base:shutil.copy2(backup/name,root/name)
 subprocess.run(['supervisorctl','restart','examiner-campus-web'],check=True,timeout=35)
 raise
""".replace("BASE",repr(base)).replace("TARGET",repr(new))
    stdin,out,err=ssh.exec_command(PY+" -",timeout=100)
    stdin.write(code);stdin.channel.shutdown_write()
    print(out.read().decode())
    if out.channel.recv_exit_status():
        # No runtime environment or private configuration is printed.
        print(err.read().decode()[-1500:])
        raise SystemExit(1)
