"""Sequential source-key evaluation on the restarted live service."""
import datetime,hashlib,json,sqlite3,time,os
from pathlib import Path
import httpx
from jose import jwt
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'output/remaining-release-checks-2026-10-10-final'
old=ROOT/'output/rag-audit-2026-10-08';doc=json.loads((old/'inventory.json').read_text())['document']
questions=json.loads((old/'ground_truth.json').read_text(encoding='utf-8'))
if os.environ.get('RECHECK_IDS'):
    selected=set(os.environ['RECHECK_IDS'].split(','))
    questions=[q for q in questions if str(q['id']) in selected]
answer_file=OUT/os.environ.get('RECHECK_OUTPUT','live-final-answers.json')
assert hashlib.sha256(Path(doc['path']).read_bytes()).hexdigest()=='905a5d07c5b310110d7de330dd7ac7d37f695df7b760db8efd5cb64f9429878f'
with sqlite3.connect('file:'+str(ROOT/'data/expo.db')+'?mode=ro',uri=True) as conn:
    conn.row_factory=sqlite3.Row
    user=dict(conn.execute("select id,username,role,auth_version from users where username='admin' and is_active=1").fetchone())
token=jwt.encode({'sub':str(user['id']),'username':user['username'],'role':user['role'],'ver':user['auth_version'],
    'exp':datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1)},(ROOT/'data/secret.key').read_text().strip(),algorithm='HS256')
answers=[]
with httpx.Client(base_url='http://127.0.0.1:8090',headers={'Authorization':'Bearer '+token},timeout=180) as c:
    assert c.get('/health/ready').status_code==200
    for question in questions:
        start=time.monotonic()
        r=c.post('/ask_stream',json={'project':doc['project_name'],'focus_doc':'Documents/'+doc['filename'],
            'query':question['question'],'messages':[],'k':8})
        events=[json.loads(l[6:]) for l in r.text.splitlines() if l.startswith('data: ')]
        answer={**question,'http':r.status_code,'seconds':time.monotonic()-start,
            'answer':''.join(e.get('text','') for e in events if e.get('type')=='token'),'events':events}
        answers.append(answer);answer_file.write_text(json.dumps(answers,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({k:v for k,v in answer.items() if k in ('id','http','seconds','answer')},ensure_ascii=False),flush=True)
