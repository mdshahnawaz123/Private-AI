"""Diagnostic observer: unchanged production route on isolated snapshot; no production edits."""
import os,sys,json,sqlite3,shutil,hashlib,time,asyncio,collections
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]; OUT=Path(__file__).parent
os.chdir(ROOT); sys.path.insert(0,str(ROOT))
INV=json.loads((OUT/'inventory.json').read_text()); DOC=INV['document']; PROJECT=DOC['project_name']
SNAP=OUT/'snapshot'; SNAP.mkdir(exist_ok=True)
source=sqlite3.connect('file:'+str(ROOT/'data/expo.db')+'?mode=ro',uri=True)
target=sqlite3.connect(SNAP/'expo.db'); source.backup(target); source.close()
for item in INV['source_documents']:
    old=Path(item['path']); new=SNAP/'docs'/PROJECT/'Documents'/old.name; new.parent.mkdir(parents=True,exist_ok=True)
    for suffix in ('','.index.json','.extracted.txt'):
        shutil.copy2(str(old)+suffix,str(new)+suffix)
    target.execute('UPDATE documents SET path=? WHERE id=?',(str(new),item['id']))
target.commit();target.close()
idx=SNAP/'faiss_index'/PROJECT; idx.mkdir(parents=True,exist_ok=True)
for name in ('index.faiss','index.pkl','generation.json'):shutil.copy2(ROOT/'data/faiss_index'/PROJECT/name,idx/name)
os.environ['EXPO_DATA_DIR']=str(SNAP); os.environ['EXPO_DATABASE_URL']='sqlite:///'+str(SNAP/'expo.db')
for name in ('HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','HF_DATASETS_OFFLINE'):os.environ[name]='1'
import main, db, extract, local_chat
from config import get_settings,resolve_role
from intelligence.reranker import get_reranker
from intelligence import answer_guard,exact_answers
s=get_settings()
fields=('embed_model','chat_model','vision_model','reranker_model','reranker_enabled','rerank_candidates','rerank_keep','retrieval_k','enable_hybrid_bm25','enable_metadata_prefilter','not_found_threshold','chunk_size','chunk_overlap','num_ctx','pdf_vision_all','enable_legacy_schedule_context')
runtime={'settings':{k:getattr(s,k) for k in fields},'roles':{r:resolve_role(r) for r in ('chat','embed','vision')},'python':sys.executable,'main_sha256':hashlib.sha256((ROOT/'main.py').read_bytes()).hexdigest(),'source_sha256':INV['sha256']}
user=db.get_user_by_username('admin'); USER={k:user[k] for k in ('id','username','role')}
request=SimpleNamespace(state=SimpleNamespace(user=USER),headers={},client=SimpleNamespace(host='127.0.0.1'))
vs=main.get_vectorstore(PROJECT); ids={(d.metadata.get('source'),d.metadata.get('page'),d.page_content):key for key,d in vs.docstore._dict.items()}
def describe(d,score=None):
    md=d.metadata
    return {'chunk_id':ids.get((md.get('source'),md.get('page'),d.page_content)),'document_id':next((it['id'] for it in INV['source_documents'] if it['filename']==md.get('source')),None),'document_id_method':'DB filename join, absent from chunk metadata','page':md.get('page'),'section':md.get('section'),'table_title_in_text':d.page_content.split('Table: ',1)[-1].splitlines()[0] if 'Table: ' in d.page_content else None,'similarity':score,'score_kind':'FAISS squared L2 distance; lower is closer' if score is not None else None,'metadata':md,'text':d.page_content}
ACTIVE={}
orig_search=vs.similarity_search
def observed_search(query,k=4,**kwargs):
    result=orig_search(query,k=k,**kwargs)
    ACTIVE.setdefault('vector_calls',[]).append({'query':query,'k':k,'results':[describe(d) for d in result]})
    return result
vs.similarity_search=observed_search
reranker=get_reranker(); orig_rerank=reranker.rerank_with_fallback
def observed_rerank(query,documents,top_k=8):
    result=orig_rerank(query,documents,top_k=top_k)
    ACTIVE.setdefault('rerank_calls',[]).append({'query':query,'top_k':top_k,'input':documents,'output':result,'model_loaded':reranker._model is not None})
    return result
reranker.rerank_with_fallback=observed_rerank
orig_retrieve=main.retrieve_context
def observed_retrieve(*args,**kwargs):
    result=orig_retrieve(*args,**kwargs)
    ACTIVE['retrieved_sources'],ACTIVE['retrieved_context']=result
    return result
main.retrieve_context=observed_retrieve
orig_build=main.build_messages
def observed_build(req,ctx=''):
    result=orig_build(req,ctx)
    ACTIVE['final_context']=ctx
    ACTIVE['messages']=[{'type':m.type,'content':m.content} for m in result]
    return result
main.build_messages=observed_build
orig_stream=local_chat.LocalChatOllama.stream
def observed_stream(self,msgs):
    entry={'model':self.model,'num_ctx':self.num_ctx,'num_predict':self.num_predict,'messages':[{'type':m.type,'content':m.content} for m in msgs],'raw_answer':''}
    ACTIVE.setdefault('llm_calls',[]).append(entry)
    for chunk in orig_stream(self,msgs):
        entry['raw_answer']+=chunk.content;yield chunk
local_chat.LocalChatOllama.stream=observed_stream
orig_guard=answer_guard.guarded_answer_with_repair
def observed_guard(answer,evidence,sources,repair):
    ACTIVE['initial_guard_issues']=answer_guard.publication_issues(answer,evidence,sources)
    result=orig_guard(answer,evidence,sources,repair)
    ACTIVE['final_guard_issues']=result[1]
    return result
answer_guard.guarded_answer_with_repair=observed_guard
ground=json.loads((OUT/'ground_truth.json').read_text())
async def run():
    traces=[]
    for test in ground:
        ACTIVE.clear();started=time.monotonic()
        q=test['question']
        req=main.QueryRequest(query=q,project=PROJECT,focus_doc='Documents/'+DOC['filename'],k=8)
        try:
            result=await main.ask_stream(req,request)
            events=[]
            async for frame in result.body_iterator:
                if isinstance(frame,bytes):frame=frame.decode()
                for block in frame.split('\n\n'):
                    if block.startswith('data: '):events.append(json.loads(block[6:]))
            if result.background:await result.background()
            actual=''.join(e.get('text','') for e in events if e.get('type')=='token')
            trace={'id':test['id'],'question':q,'expected':test['expected'],'source_page':1,'section':test['section'],'request':req.model_dump(),'events':events,'actual':actual,'seconds':time.monotonic()-started,**dict(ACTIVE)}
            trace['query_classification']='DETERMINISTIC_EXACT' if not trace.get('llm_calls') else 'FOCUSED_DOCUMENT_RAG'
        except Exception as e:
            trace={'id':test['id'],'question':q,'error':repr(e),**dict(ACTIVE)}
        traces.append(trace)
        (OUT/'route-traces.json').write_text(json.dumps(traces,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
        print(json.dumps({'id':test['id'],'seconds':trace.get('seconds'),'path':trace.get('query_classification'),'answer':trace.get('actual'),'error':trace.get('error')},ensure_ascii=False),flush=True)
    tops=[]
    for test in ground:
        ACTIVE.clear();q=test['question']; distances=vs.similarity_search_with_score(q,k=20)
        score_map={(d.metadata.get('source'),d.page_content):float(score) for d,score in distances}
        for k in (3,5,10):
            ACTIVE.clear();sources,context=orig_retrieve(PROJECT,q,k,USER)
            rec={'id':test['id'],'question':q,'requested_k':k,'endpoint_effective_k':'max(8, request.k); direct retrieval probe below bypasses this clamp','sources':sources,'context':context,'vector_distance_results':[describe(d,float(score)) for d,score in distances],**dict(ACTIVE)}
            tops.append(rec)
        print('TOPK '+str(test['id']),flush=True)
    (OUT/'top-k-traces.json').write_text(json.dumps(tops,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    runtime['reranker']={'enabled':reranker.is_enabled(),'load_attempted':reranker._load_attempted,'loaded':reranker._model is not None}
    (OUT/'runtime.json').write_text(json.dumps(runtime,indent=2),encoding='utf-8')
asyncio.run(run())
