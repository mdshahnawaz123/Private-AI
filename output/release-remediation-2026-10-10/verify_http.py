"""Source-bound live answer checks; no uploads, reindexing or configuration changes."""
import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import httpx
from jose import jwt

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
OLD = ROOT / 'output/rag-audit-2026-10-08'
inventory = json.loads((OLD/'inventory.json').read_text(encoding='utf-8'))
doc = inventory['document']
questions = [q for q in json.loads((OLD/'ground_truth.json').read_text(encoding='utf-8'))
             if q['id'] in (4,11,14,18,20)]
path = Path(doc['path'])
source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
if source_hash != '905a5d07c5b310110d7de330dd7ac7d37f695df7b760db8efd5cb64f9429878f':
    raise RuntimeError('Source changed: historical ground truth must be revalidated')
with sqlite3.connect('file:'+str(ROOT/'data/expo.db')+'?mode=ro',uri=True) as conn:
    conn.row_factory=sqlite3.Row
    user=dict(conn.execute("SELECT id,username,role,auth_version FROM users WHERE username='admin' AND is_active=1").fetchone())
token=jwt.encode({'sub':str(user['id']),'username':user['username'],'role':user['role'],
                  'ver':user['auth_version'],'exp':datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1)},
                 (ROOT/'data/secret.key').read_text().strip(),algorithm='HS256')
results=[]
with httpx.Client(base_url='http://127.0.0.1:8090',headers={'Authorization':'Bearer '+token},timeout=180) as client:
    ready=client.get('/health/ready')
    schema=client.get('/openapi.json')
    (OUT/'live-runtime.json').write_text(json.dumps({'source_sha256':source_hash,'readiness_http':ready.status_code,
        'readiness':ready.json(),'workspace_import_route_live':'/projects/{project}/agent/workspace-file' in schema.json().get('paths',{})},indent=2),encoding='utf-8')
    for q in questions:
        started=time.monotonic()
        payload={'project':doc['project_name'],'focus_doc':'Documents/'+doc['filename'],
                 'query':q['question'],'messages':[],'k':8}
        try:
            response=client.post('/ask_stream',json=payload)
            events=[]
            for line in response.text.splitlines():
                if line.startswith('data: '):events.append(json.loads(line[6:]))
            record={**q,'http':response.status_code,'seconds':round(time.monotonic()-started,2),
                    'answer':''.join(e.get('text','') for e in events if e.get('type')=='token'),
                    'events':events,'request':payload}
            if response.status_code!=200:record['error']=response.text[:1500]
        except Exception as exc:
            record={**q,'error':str(exc),'seconds':round(time.monotonic()-started,2)}
        results.append(record)
        (OUT/'live-results.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({k:v for k,v in record.items() if k in ('id','answer','http','seconds','error')},ensure_ascii=False),flush=True)
