"""Send the scoped operator command over host-key-checked SSH, with no stored SSH password."""
import argparse
import getpass
import re
from pathlib import Path

import paramiko


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_]{3,32}", args.username):
        parser.error("Invalid username")
    code = Path(__file__).with_name("teacher_account.py").read_bytes()
    with paramiko.SSHClient() as ssh:
        ssh.load_host_keys(str(Path.home() / ".ssh/known_hosts"))
        ssh.connect("u3ssh.casdao.com", port=54653, username="root", password=getpass.getpass("SSH password: "),
                    timeout=12, allow_agent=False, look_for_keys=False)
        cmd = "/opt/ai-examiner/.venv/bin/python - " + args.username + (" --apply" if args.apply else "")
        stdin, out, err = ssh.exec_command(cmd, timeout=35)
        stdin.write(code)
        stdin.channel.shutdown_write()
        print(out.read().decode().strip())
        status = out.channel.recv_exit_status()
        if status:
            print(err.read().decode(errors="replace").strip()[-900:])
        raise SystemExit(status)


if __name__ == "__main__":
    main()
