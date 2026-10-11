"""Run the exact questions through the existing HTTP endpoint. No upload or code changes."""
import json,sys,sqlite3,time,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
import httpx
from jose import jwt
inv=json.loads((OUT/'inventory.json').read_text());doc=inv['document']
conn=sqlite3.connect('file:'+str(ROOT/'data/expo.db')+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row
user=dict(conn.execute("SELECT id,username,role,auth_version FROM users WHERE username='admin' AND is_active=1").fetchone())
secret=(ROOT/'data/secret.key').read_text().strip()
token=jwt.encode({'sub':str(user['id']),'username':user['username'],'role':user['role'],'ver':user['auth_version'],'exp':datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=2)},secret,algorithm='HS256')
results=[]
questions=json.loads((OUT/'ground_truth.json').read_text(encoding='utf-8'))
with httpx.Client(base_url='http://127.0.0.1:8090',headers={'Authorization':'Bearer '+token},timeout=240) as client:
    readiness=client.get('/health/ready')
    (OUT/'live-readiness.json').write_text(json.dumps(readiness.json(),indent=2))
    for q in questions:
        payload={'query':q['question'],'project':doc['project_name'],'focus_doc':'Documents/'+doc['filename'],'k':8,'messages':[]}
        started=time.monotonic()
        try:
            response=client.post('/ask_stream',json=payload)
            events=[]
            if response.status_code==200:
                for line in response.text.splitlines():
                    if line.startswith('data: '):events.append(json.loads(line[6:]))
            record={'id':q['id'],'question':q['question'],'request':payload,'http':response.status_code,'answer':''.join(e.get('text','') for e in events if e.get('type')=='token'),'events':events,'seconds':time.monotonic()-started}
            if response.status_code!=200:record['error_body']=response.text
        except Exception as e:record={'id':q['id'],'error':repr(e)}
        results.append(record)
        (OUT/'live-results.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({k:v for k,v in record.items() if k in ('id','http','answer','seconds','error')},ensure_ascii=False),flush=True)
