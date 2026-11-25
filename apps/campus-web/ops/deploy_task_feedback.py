"""Publish only the campus site's three static assets. No process or database changes."""
import argparse
import getpass
import hashlib
from pathlib import Path
from uuid import uuid4

import paramiko


ROOT = Path(__file__).resolve().parents[1] / "web"
SITE = "/opt/examiner-campus-web"
BASE = {
    "app.js": "3f3873707f6331b926316d6912c75167286d02e0ebdb26048ce2e3f36f1ea252",
    "style.css": "d7a45567a88fd36fbc22cc3e6efd6363183c5fd175be3b8ba658537d389d67c3",
    "index.html": "11fe90de2aaa8b2e613939c8b4560d13e0c2af213b672541504a8f1b6a552f0f",
}

INSTALL = """
import hashlib, os, shutil, urllib.request
from pathlib import Path
root = Path('/opt/examiner-campus-web/web')
backup = Path('/var/backups') / stage.name
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
for n in target:
    assert not (root/n).is_symlink() and digest(root/n) == base[n], 'Baseline changed: ' + n
    assert digest(stage/n) == target[n], 'Uploaded file mismatch: ' + n
backup.mkdir(mode=0o700)
for n in target: shutil.copy2(root/n, backup/n)
installed = []
try:
    for n in target:  # entry point last
        assert digest(root/n) == base[n], 'Concurrent update: ' + n
        os.chmod(stage/n, 0o644)
        os.replace(stage/n, root/n)
        installed.append(n)
    for n in target:
        with urllib.request.urlopen('http://127.0.0.1/' + n, timeout=8) as r:
            assert hashlib.sha256(r.read()).hexdigest() == target[n], 'HTTP verification failed: ' + n
    print('Static files verified. Backup:', backup)
except BaseException:
    for n in reversed(installed):
        if digest(root/n) == target[n]:
            shutil.copy2(backup/n, stage/n)
            os.replace(stage/n, root/n)
    raise
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    target = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in BASE}
    with paramiko.SSHClient() as ssh:
        ssh.load_host_keys(str(Path.home() / ".ssh/known_hosts"))
        ssh.connect("u3ssh.casdao.com", port=54653, username="root", password=getpass.getpass("SSH password: "),
                    timeout=12, allow_agent=False, look_for_keys=False)
        with ssh.open_sftp() as sftp:
            actual = {}
            for n in BASE:
                with sftp.open(f"{SITE}/web/{n}", "rb") as f:
                    actual[n] = hashlib.sha256(f.read()).hexdigest()
            if actual == target:
                print("Already deployed.")
                return
            if actual != BASE:
                raise SystemExit("Unexpected deployed version; no writes: " + ", ".join(n for n in BASE if actual[n] != BASE[n]))
            if not args.apply:
                print("Expected baseline confirmed. No writes.")
                return
            stage = SITE + "/campus-ui-" + uuid4().hex
            sftp.mkdir(stage, mode=0o700)
            try:
                for n in BASE:
                    sftp.put(str(ROOT / n), stage + "/" + n)
                stdin, out, err = ssh.exec_command("/opt/ai-examiner/.venv/bin/python -", timeout=40)
                stdin.write("from pathlib import Path\nstage=Path("+repr(stage)+")\nbase="+repr(BASE)+"\ntarget="+repr(target)+"\n"+INSTALL)
                stdin.channel.shutdown_write()
                print(out.read().decode().strip())
                if out.channel.recv_exit_status():
                    raise RuntimeError(err.read().decode(errors="replace")[-600:])
            finally:
                for n in BASE:
                    try:
                        sftp.remove(stage + "/" + n)
                    except FileNotFoundError:
                        pass
                sftp.rmdir(stage)


if __name__ == "__main__":
    main()
