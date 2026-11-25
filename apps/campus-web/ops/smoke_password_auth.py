"""Synthetic, non-billing acceptance. Disable only accounts created by this run."""
import getpass
from pathlib import Path

import paramiko

CODE=r'''
import hashlib,json,os,secrets,sqlite3,sys,time
from pathlib import Path
from uuid import uuid4,uuid5,NAMESPACE_URL
import httpx
BASE='http://127.0.0.1'
H={'X-Campus-Request':'1','Origin':'https://classic-merry-6705-80.east3.casdao.com:2005'}
dbpath='/var/lib/examiner-campus-web/accounts.sqlite3'
users=[]
clients=[]
def check(r,status,label):
 if r.status_code!=status:
  raise RuntimeError(label+': HTTP '+str(r.status_code))
 return r
try:
 for _ in range(2):
  username='accept_'+uuid4().hex[:16]
  password=secrets.token_urlsafe(24)
  client=httpx.Client(base_url=BASE,headers=H,timeout=25,follow_redirects=False)
  clients.append(client)
  check(client.post('/api/register',json={'username':username,'nickname':'Synthetic acceptance','password':password,'confirm_password':password}),201,'register')
  users.append(username)
  r=check(client.post('/api/login',json={'username':username,'password':password}),200,'login')
  assert all(k in r.headers['set-cookie'] for k in ('Secure','HttpOnly','SameSite=strict'))
  # Test transport is loopback HTTP; retain the production Secure cookie unchanged.
  client.headers['Cookie']='__Host-campus_sid='+r.cookies.get('__Host-campus_sid')
  me=check(client.get('/api/me'),200,'me').json()['user']
  assert me and me['username']==username and not me['teacher']
  check(client.get('/gateway/api/v1/school/exams'),200,'shared exam list')
  assert check(client.get('/gateway/api/projects'),200,'new private projects').json()==[]
  check(client.post('/gateway/api/v1/school/workspace/teacher'),403,'no teacher grant')
  check(client.get('/gateway/api/v1/organizations'),404,'no admin routes')
  work=check(client.post('/gateway/api/v1/school/workspace/student'),200,'personal workspace').json()
  assert work['profile']=='qwen:qwen-plus'
  client.own_org=work['organization_id']
  print('Registered, logged in, read shared exams; new personal projects empty; teacher/admin denied')
 assert clients[0].own_org!=clients[1].own_org
 for client in clients:
  check(client.post('/api/logout'),200,'logout')
  check(client.get('/gateway/api/projects'),401,'logged out')
 print('Distinct personal spaces; logout revocation verified; no model calls or exam writes')
finally:
 for client in clients:
  try:client.post('/api/logout')
  except Exception:pass
  client.close()
 ids=[]
 with sqlite3.connect(dbpath) as db:
  for name in users:
   row=db.execute('SELECT id FROM accounts WHERE username=?',(name,)).fetchone()
   if row:ids.append(row[0])
   db.execute('UPDATE accounts SET active=0 WHERE username=?',(name,))
 if ids:
  runtime=json.loads(Path('/etc/ai-examiner/runtime.json').read_text())
  for key in ('DATABASE_URL','AUTH_MODE','APP_ENV','DATABASE_SCHEMA_MANAGEMENT','POSTGRES_RLS_MODE','AUDIT_IP_HASH_KEY'):
   if key in runtime:os.environ[key]=str(runtime[key])
  for key in ('UPLOAD_DIR','EVIDENCE_DIR','EXPORT_DIR','BACKUP_DIR','STORAGE_LOCAL_ROOT','PROMPT_DIR'):
   os.environ[key]='/var/lib/examiner-campus-web/runtime/'+key.lower()
  del runtime
  sys.path.insert(0,'/opt/ai-examiner/src')
  from ai_examiner.db import SessionLocal
  from ai_examiner.models import Principal,BrowserAuthSession,utcnow
  from sqlalchemy import update
  with SessionLocal() as db:
   for aid in ids:
    pid=str(uuid5(NAMESPACE_URL,'campus:password:v1:'+aid))
    p=db.get(Principal,pid)
    if p is not None:
     assert p.issuer=='campus:password:v1' and p.subject==aid
     p.status='disabled'
     db.execute(update(BrowserAuthSession).where(BrowserAuthSession.principal_id==pid).values(revoked_at=utcnow()))
   db.commit()
 print('Synthetic credentials disabled:',len(ids))
'''

with paramiko.SSHClient() as ssh:
    ssh.load_host_keys(str(Path.home()/'.ssh/known_hosts'))
    ssh.connect('u3ssh.casdao.com',port=54653,username='root',password=getpass.getpass('SSH password: '),timeout=12,allow_agent=False,look_for_keys=False)
    stdin,out,err=ssh.exec_command('/opt/ai-examiner/.venv/bin/python -',timeout=180)
    stdin.write(CODE);stdin.channel.shutdown_write()
    print(out.read().decode())
    status=out.channel.recv_exit_status()
    if status:
        # Traceback excludes response bodies, credential values and configuration.
        print(err.read().decode()[-1800:])
    raise SystemExit(status)
