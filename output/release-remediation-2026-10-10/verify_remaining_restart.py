"""Restart verification against the persisted synthetic test environment only."""
import os,sys,time,json,datetime,subprocess,sqlite3,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'output/remaining-release-checks-2026-10-10-final';DATA=OUT/'data'
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
os.environ.update(EXPO_DATA_DIR=str(DATA),EXPO_DATABASE_URL='sqlite:///'+str(DATA/'expo.db'),EXPO_PORT='8092',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
import db,auth,httpx
from jose import jwt
user=db.get_user_by_username('admin')
token=jwt.encode({'sub':str(user['id']),'username':user['username'],'role':user['role'],'ver':user['auth_version'],
    'exp':datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(minutes=30)},auth.secret(),algorithm='HS256')
log=open(OUT/'restart-server.log','w',encoding='utf-8')
server=subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port','8092'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT)
try:
    with httpx.Client(base_url='http://127.0.0.1:8092',headers={'Authorization':'Bearer '+token},timeout=180) as c:
        for _ in range(90):
            try:
                if c.get('/health/ready').status_code==200:break
            except Exception:pass
            if server.poll() is not None:raise RuntimeError('Synthetic restart server exited')
            time.sleep(1)
        else:raise RuntimeError('Synthetic restart timeout')
        cases=[('SYNTH-A','What is the Plot Area?','Documents/native-a.pdf'),
            ('SYNTH-B','What is the Plot Area?','Documents/native-b.pdf'),
            ('SYNTH-A','What is the Plot Area of project SYNTH-B?',None),
            ('SYNTH-A','Is revision B approved for construction?','Documents/native-a.pdf'),
            ('SYNTH-A','What design pressure is specified for AHU-017?','Documents/native-a.pdf')]
        answers=[]
        for project,query,focus in cases:
            payload={'project':project,'query':query,'messages':[],'k':8}
            if focus:payload['focus_doc']=focus
            started=time.monotonic();r=c.post('/ask_stream',json=payload)
            events=[json.loads(l[6:]) for l in r.text.splitlines() if l.startswith('data: ')]
            record={'project':project,'question':query,'http':r.status_code,'seconds':time.monotonic()-started,
                'answer':''.join(e.get('text','') for e in events if e.get('type')=='token'),'events':events}
            answers.append(record);(OUT/'restart-answers.json').write_text(json.dumps(answers,indent=2),encoding='utf-8')
            print(json.dumps(record),flush=True)
        with sqlite3.connect(DATA/'expo.db') as conn:
            docs=conn.execute('select status,count(*) from documents group by status').fetchall()
            integrity=conn.execute('pragma integrity_check').fetchone()[0]
        result={'ready':True,'integrity':integrity,'documents':dict(docs),'source_hashes':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in
            ('main.py','intelligence/exact_answers.py','intelligence/table_evidence.py','intelligence/source_semantics.py','response_schema.py')}}
        (OUT/'restart.json').write_text(json.dumps(result,indent=2))
finally:
    server.terminate()
    try:server.wait(timeout=20)
    except subprocess.TimeoutExpired:server.kill();server.wait(timeout=10)
    log.close()
