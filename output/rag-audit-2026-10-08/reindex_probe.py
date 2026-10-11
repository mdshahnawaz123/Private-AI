import os,sys,json,sqlite3,shutil,collections,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent;os.chdir(ROOT);sys.path.insert(0,str(ROOT))
inv=json.loads((OUT/'inventory.json').read_text());doc=inv['document'];project=doc['project_name'];data=OUT/'reindex-data-second';data.mkdir(exist_ok=True)
src=sqlite3.connect('file:'+str(ROOT/'data/expo.db')+'?mode=ro',uri=True);dst=sqlite3.connect(data/'expo.db');src.backup(dst);dst.close();src.close()
idx=data/'faiss_index'/project;idx.mkdir(parents=True,exist_ok=True)
for name in ('index.faiss','index.pkl','generation.json'):shutil.copy2(ROOT/'data/faiss_index'/project/name,idx/name)
os.environ['EXPO_DATA_DIR']=str(data);os.environ['EXPO_DATABASE_URL']='sqlite:///'+str(data/'expo.db')
for name in ('HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE'):os.environ[name]='1'
import main
meta=json.loads((OUT/'stored-extraction.json').read_text(encoding='utf-8'))
def measure():
    vs=main.get_vectorstore(project);documents=[d for d in vs.docstore._dict.values() if d.metadata.get('source')==doc['filename']]
    counts=collections.Counter(d.page_content for d in documents)
    return {'total':vs.index.ntotal,'source_chunks':len(documents),'duplicate_content_extra':sum(n-1 for n in counts.values()),'content_counts':dict(counts),'uuids':[key for key,d in vs.docstore._dict.items() if d.metadata.get('source')==doc['filename']]}
before=measure();runs=[]
for attempt in (1,2):
    try:
        written=main.index_structured(project,meta,doc['filename'],doc['folder_id']);after=measure()
        runs.append({'run':attempt,'written':written,'after':after});print('REINDEX',attempt,written,after['total'],after['source_chunks'],flush=True)
    except Exception as exc:
        runs.append({'run':attempt,'error':repr(exc),'after':measure(),'disk_previous_manifest_restored':json.loads((idx/'generation.json').read_text())==inv['index']['manifest']});print('REINDEX ERROR',repr(exc),flush=True);break
result={'before':before,'runs':runs,'same_count_both_runs':len(runs)==2 and runs[0]['after']['source_chunks']==runs[1]['after']['source_chunks'],'same_content_both_runs':len(runs)==2 and runs[0]['after']['content_counts']==runs[1]['after']['content_counts'],'old_uuid_intersection_second_run':len(set(runs[0]['after']['uuids']) & set(runs[1]['after']['uuids'])) if len(runs)==2 else None,'production_index_unchanged':{name:hashlib.sha256((ROOT/'data/faiss_index'/project/name).read_bytes()).hexdigest()==digest for name,digest in inv['index']['manifest']['sha256'].items()}}
(OUT/'reindex-results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
