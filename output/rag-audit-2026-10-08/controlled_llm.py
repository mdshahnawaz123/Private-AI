"""Correct-evidence-only local model diagnostic, not verified engineering output."""
import os,sys,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent;sys.path.insert(0,str(ROOT));os.chdir(ROOT)
os.environ['EXPO_DATA_DIR']=str(OUT/'controlled-data')
from dotenv import load_dotenv
load_dotenv()
from config import resolve_role
from local_chat import LocalChatOllama
from langchain_core.messages import SystemMessage,HumanMessage
ground=json.loads((OUT/'ground_truth.json').read_text(encoding='utf-8'))
meta=json.loads((OUT/'stored-extraction.json').read_text(encoding='utf-8'))
chunks=json.loads((OUT/'actual-chunks.json').read_text(encoding='utf-8'))
consultants=meta['pages'][0]['tables'].split('| CONSULTANTS',1)[1].split('\n\n',1)[0]
role=resolve_role('chat');llm=LocalChatOllama(model=role['model'],url=role['base_url'],temperature=0.1,num_predict=3072,keep_alive=0)
tests=(4,7,11,12,14,15,18,19,20);results=[]
for number in tests:
    test=ground[number-1]
    if number==15:evidence='CONSULTANTS'+consultants
    elif number==11:evidence='\n\n'.join(c['text'] for c in chunks if c['text'].startswith('[TABLE ROW]') and '5th Floor' in c['text'])
    elif number==12:evidence=next(c['text'] for c in chunks if c['text'].startswith('[TABLE ROW]') and '2BR-Type 2' in c['text'])
    else:evidence=test['evidence']
    prompt=f"DOCUMENT CONTEXT:\n[SOURCE: {meta['filename']} | PAGE 1]\n{evidence}\n\nUse only this evidence; do not infer missing fields. Preserve scope and units. Cite the source/page. Identify ambiguity. A numerical comparison is not overall compliance certification."
    messages=[SystemMessage(content=prompt),HumanMessage(content=test['question'])]
    started=time.monotonic()
    try:answer=''.join(c.content for c in llm.stream(messages));error=None
    except Exception as e:answer='';error=repr(e)
    results.append({'id':number,'question':test['question'],'model':role['model'],'evidence':evidence,'messages':[{'type':m.type,'content':m.content} for m in messages],'answer':answer,'error':error,'seconds':time.monotonic()-started})
    (OUT/'controlled-results.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'id':number,'answer':answer,'error':error},ensure_ascii=False),flush=True)
