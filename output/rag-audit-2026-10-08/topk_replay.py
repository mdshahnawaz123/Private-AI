"""Replay production retrieval with measured vectors/reranker results cached only for identical inputs."""
from pathlib import Path
import json,copy
OUT=Path(__file__).parent
prefix=(OUT/'trace_pipeline.py').read_text(encoding='utf-8').split('async def run():',1)[0]
exec(compile(prefix,str(OUT/'trace_pipeline.py'),'exec'))
routes=json.loads((OUT/'route-traces.json').read_text(encoding='utf-8'))
captured={r['question']:r['rerank_calls'][0] for r in routes if r.get('rerank_calls')}
def cached_rerank(query,documents,top_k=8):
    known=captured[query]
    if known['input']!=documents or known['top_k']!=top_k:
        raise AssertionError('Replay inputs differ from measured production-route inference')
    result=copy.deepcopy(known['output'])
    ACTIVE['rerank_calls']=[{**copy.deepcopy(known),'inference_reused_from_actual_route':True,'identical_inputs_verified':True}]
    return result
reranker.rerank_with_fallback=cached_rerank
embed_query=vs._embed_query;query_vectors={}
def cached_embed(query):
    if query not in query_vectors:query_vectors[query]=embed_query(query)
    return query_vectors[query]
vs._embed_query=cached_embed
results=[]
for test in ground:
    q=test['question'];distances=vs.similarity_search_with_score(q,k=20)
    for k in (3,5,10):
        ACTIVE.clear()
        # Exact answers bypass retrieval. Probe their hypothetical fallback using
        # the unreranked list only and mark it as such, never fabricate a model score.
        has_rerank=q in captured
        if not has_rerank:
            reranker.rerank_with_fallback=lambda query,documents,top_k=8:documents[:top_k]
        else:reranker.rerank_with_fallback=cached_rerank
        sources,context=orig_retrieve(PROJECT,q,k,USER)
        results.append({'id':test['id'],'question':q,'requested_k':k,'document_filter':'project + ready + folder permission; no focused-source filter','sources':sources,'context':context,'vector_distance_results':[describe(d,float(score)) for d,score in distances],'rerank_mode':'identical measured inference reused' if has_rerank else 'NOT MEASURED: deterministic exact route bypassed retrieval; hypothetical unreranked fallback',**copy.deepcopy(ACTIVE)})
    (OUT/'top-k-traces.json').write_text(json.dumps(results,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    print('TOPK '+str(test['id']),flush=True)
runtime['reranker']={'enabled':reranker.is_enabled(),'loaded_in_observed_route':all(r['rerank_calls'][0]['model_loaded'] for r in routes if r.get('rerank_calls')),'measured_calls':sum(bool(r.get('rerank_calls')) for r in routes)}
runtime['diagnostic_replay_note']='Production code unchanged. Exact identical reranker inputs reuse captured deterministic scores; query embeddings computed once per question. Exact-route hypothetical fallback is explicitly marked unreranked, not an actual reranker measurement.'
(OUT/'runtime.json').write_text(json.dumps(runtime,indent=2),encoding='utf-8')
