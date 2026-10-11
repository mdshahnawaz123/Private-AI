"""Latest-code restart, adversarial source checks and trusted synthetic index audit."""
import os,sys,json,time,datetime,subprocess,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'output/release-closure-2026-10-10';DATA=OUT/'data'
os.chdir(ROOT);sys.path.insert(0,str(ROOT))
os.environ.update(EXPO_DATA_DIR=str(DATA),EXPO_DATABASE_URL='sqlite:///'+str(DATA/'expo.db'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
import main,db,auth,httpx
from jose import jwt
user=db.get_user_by_username('admin')
token=jwt.encode({'sub':str(user['id']),'username':user['username'],'role':user['role'],'ver':user.get('auth_version',0),
 'exp':datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1)},auth.secret(),algorithm='HS256')
log=open(OUT/'post-server.log','w',encoding='utf-8')
server=subprocess.Popen([sys.executable,'-m','uvicorn','main:app','--host','127.0.0.1','--port','8093'],cwd=ROOT,env=os.environ.copy(),stdout=log,stderr=subprocess.STDOUT)
answers=[]
try:
    with httpx.Client(base_url='http://127.0.0.1:8093',headers={'Authorization':'Bearer '+token},timeout=180) as c:
        for _ in range(100):
            try:
                if c.get('/health/ready').status_code==200:break
            except Exception:pass
            if server.poll() is not None:raise RuntimeError('Postcheck server exited')
            time.sleep(1)
        else:raise TimeoutError('Postcheck startup')
        for question,focus,expected in [
            ('What pressure is specified for PMP-483?','pump-spec.pdf','685 kPa'),
            ('What height is specified for TNK-719?','tank-note.pdf','8 m'),
            ('What pressure is specified for PMP-000?','pump-spec.pdf',None),
            ('Is revision C approved for construction?','pump-spec.pdf','DRAFT'),
            ('What pressure is specified for PMP-483 in project SYNTH-OTHER?','pump-spec.pdf',None),
            ('What pressure is specified for PMP-483?','scan-4-0.pdf',None)]:
            r=c.post('/ask_stream',json={'project':'SYNTH-CLOSURE','focus_doc':'Documents/'+focus,'query':question,'messages':[],'k':8})
            events=[json.loads(l[6:]) for l in r.text.splitlines() if l.startswith('data: ')]
            answer=''.join(e.get('text','') for e in events if e.get('type')=='token')
            passed=(expected in answer if expected else '685' not in answer) and r.status_code==200
            if expected=='685 kPa':passed=passed and 'Revision C' in answer and 'DRAFT' in answer
            if expected=='8 m':passed=passed and 'Revision C' in answer and 'TBC' in answer
            answers.append({'question':question,'focus':focus,'http':r.status_code,'answer':answer,'events':events,'pass':passed})
            (OUT/'post-answers.json').write_text(json.dumps(answers,indent=2),encoding='utf-8')
            print(json.dumps({'question':question,'pass':passed}),flush=True)
    vector=main.get_vectorstore('SYNTH-CLOSURE')
    keys=[(d.metadata.get('source'),d.metadata.get('folder_id'),d.metadata.get('page'),d.page_content) for d in vector.docstore._dict.values()]
    from collections import Counter
    result={'vectors':vector.index.ntotal,'duplicate_chunks':len(keys)-len(set(keys)),
            'source_chunks':dict(Counter(k[0] for k in keys))}
    with sqlite3.connect(DATA/'expo.db') as c:
        result['integrity']=c.execute('pragma integrity_check').fetchone()[0]
        result['foreign_key_violations']=len(c.execute('pragma foreign_key_check').fetchall())
    (OUT/'post-index.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
finally:
    server.terminate()
    try:server.wait(timeout=20)
    except subprocess.TimeoutExpired:server.kill();server.wait(timeout=10)
    log.close()
