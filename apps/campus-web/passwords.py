"""Website-only credentials. Business records remain in the shared backend."""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException


def hash_password(password, salt):
    return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=32768,r=8,p=1,maxmem=128*1024**2).hex()


class PasswordStore:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript("""
CREATE TABLE IF NOT EXISTS accounts (
 id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, nickname TEXT NOT NULL,
 salt TEXT NOT NULL, password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS limits (
 key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
""")
        if os.name=="posix":
            self.path.chmod(0o600)
        self.dummy_salt=secrets.token_hex(16)

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=10)
        c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def check_rate(self,scope,identifier,maximum,seconds=600):
        key=hashlib.sha256((scope+":"+identifier).encode()).hexdigest()
        now=time.time()
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM limits WHERE expires<=?",(now,))
            c.execute("INSERT INTO limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1",(key,now+seconds))
            count=c.execute("SELECT count FROM limits WHERE key=?",(key,)).fetchone()[0]
        if count>maximum:
            raise HTTPException(429,"尝试次数过多，请 10 分钟后再试")

    def register(self,username,nickname,password):
        salt=secrets.token_hex(16)
        digest=hash_password(password,salt)
        try:
            with self.connect() as c:
                c.execute("INSERT INTO accounts VALUES(?,?,?,?,?,1,?)",
                          (str(uuid4()),username.lower(),nickname,salt,digest,int(time.time())))
        except sqlite3.IntegrityError:
            raise HTTPException(409,"该用户名不可用，请更换或直接登录") from None
        with self.connect() as c:
            return dict(c.execute("SELECT id,username,nickname,active FROM accounts WHERE username=?",(username.lower(),)).fetchone())

    def verify(self,username,password):
        with self.connect() as c:
            row=c.execute("SELECT * FROM accounts WHERE username=?",(username.lower(),)).fetchone()
        digest=hash_password(password,row["salt"] if row else self.dummy_salt)
        if not row or not hmac.compare_digest(digest,row["password_hash"]) or not row["active"]:
            raise HTTPException(401,"用户名或密码不正确，或账号已停用")
        return {k:row[k] for k in ("id","username","nickname","active")}

    def active(self,account_id):
        with self.connect() as c:
            row=c.execute("SELECT active FROM accounts WHERE id=?",(account_id,)).fetchone()
        return bool(row and row[0])
