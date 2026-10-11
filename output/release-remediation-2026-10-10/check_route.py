import os,sys,json,sqlite3,shutil,asyncio,time,hashlib
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
inv=json.loads((ROOT/'output/rag-audit-2026-10-08/inventory.json').read_text())
doc=inv['document'];project=doc['project_name'];snap=OUT/'snapshot';snap.mkdir(exist_ok=True)
with sqlite3.connect('file:'+str(ROOT/'data/expo.db')+'?mode=ro',uri=True) as original,sqlite3.connect(snap/'expo.db') as target:
    original.backup(target)
    for item in inv['source_documents']:
        old=Path(item['path']);new=snap/'docs'/project/'Documents'/old.name;new.parent.mkdir(parents=True,exist_ok=True)
        for suffix in ('','.index.json','.extracted.txt'):shutil.copy2(str(old)+suffix,str(new)+suffix)
        target.execute('UPDATE documents SET path=? WHERE id=?',(str(new),item['id']))
    target.commit()
idx=snap/'faiss_index'/project;idx.mkdir(parents=True,exist_ok=True)
for name in ('index.faiss','index.pkl','generation.json'):shutil.copy2(ROOT/'data/faiss_index'/project/name,idx/name)
os.environ['EXPO_DATA_DIR']=str(snap);os.environ['EXPO_DATABASE_URL']='sqlite:///'+str(snap/'expo.db')
for key in ('HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','HF_DATASETS_OFFLINE'):os.environ[key]='1'
import main,db
from loguru import logger;logger.remove()
user=db.get_user_by_username('admin');request=SimpleNamespace(state=SimpleNamespace(user=user),headers={},client=SimpleNamespace(host='127.0.0.1'))
questions=json.loads((ROOT/'output/rag-audit-2026-10-08/ground_truth.json').read_text(encoding='utf-8'))
results=[]
selected={int(value) for value in sys.argv[1].split(',')} if len(sys.argv)>1 else {1,4,6,11,12,14,15,18,19,20}
output_name='final-route-results.json' if len(sys.argv)>1 else 'route-results.json'
(OUT/'verified-source-hashes.json').write_text(json.dumps({name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('main.py','intelligence/exact_answers.py','intelligence/table_evidence.py','intelligence/document_memory.py','intelligence/answer_guard.py','intelligence/document_investigation.py')},indent=2))
async def run():
    for q in questions:
        if q['id'] not in selected:continue
        started=time.monotonic();events=[]
        try:
            req=main.QueryRequest(project=project,focus_doc='Documents/'+doc['filename'],query=q['question'],messages=[],k=8)
            response=await main.ask_stream(req,request)
            async for block in response.body_iterator:
                block=block.decode() if isinstance(block,bytes) else block
                for line in block.splitlines():
                    if line.startswith('data: '):events.append(json.loads(line[6:]))
            record={**q,'answer':''.join(e.get('text','') for e in events if e.get('type')=='token'),
                    'events':events,'seconds':round(time.monotonic()-started,2)}
        except Exception as exc:record={**q,'error':repr(exc),'seconds':round(time.monotonic()-started,2)}
        results.append(record);(OUT/output_name).write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({k:v for k,v in record.items() if k in ('id','answer','error','seconds')},ensure_ascii=False),flush=True)
asyncio.run(run())
