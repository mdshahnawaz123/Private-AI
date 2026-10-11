import os, sys, json, sqlite3, hashlib, pickle
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
os.chdir(ROOT)
OUT.mkdir(parents=True,exist_ok=True)
conn=sqlite3.connect('file:'+str(ROOT/'data/expo.db')+'?mode=ro',uri=True)
conn.row_factory=sqlite3.Row
rows=[dict(r) for r in conn.execute("SELECT d.*,p.name project_name FROM documents d JOIN projects p ON d.project_id=p.id WHERE d.filename LIKE '%C3045%'")]
print(json.dumps(rows,indent=2,default=str))
doc=next(r for r in rows if r['filename']=='260610_C3045_2VA_PROJECT_DATA_SHEET_-_STAGE_4.pdf'); path=Path(doc['path'])
meta=json.loads(Path(str(path)+'.index.json').read_text(encoding='utf-8'))
(OUT/'stored-extraction.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf-8')
summary={'document':doc,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'metadata_keys':list(meta),'page_summaries':[{k:(len(v) if isinstance(v,str) else v) for k,v in p.items() if k in ('page','text','tables','vision','vision_used','table_count','dense_table_page')} for p in meta['pages']]}
for table in ('doc_meta','page_records','image_records','structured_records','schedule_rows','quantities'):
    cols=[r['name'] for r in conn.execute('PRAGMA table_info('+table+')')]
    candidates=[c for c in ('document_id','document_filename','filename','doc','source_doc') if c in cols]
    if candidates:
        key=candidates[0]; value=doc['id'] if key=='document_id' else doc['filename']
        clause=' AND project_id=?' if 'project_id' in cols else ''
        params=(value,doc['project_id']) if clause else (value,)
        data=[dict(r) for r in conn.execute('SELECT * FROM '+table+' WHERE '+key+'=?'+clause,params)]
        summary[table]={'columns':cols,'rows':data}
idx=ROOT/'data/faiss_index'/doc['project_name']
with (idx/'index.pkl').open('rb') as f: store,mapping=pickle.load(f)
chunks=[{'chunk_id':key,'metadata':d.metadata,'text':d.page_content} for key,d in store._dict.items() if d.metadata.get('source')==doc['filename']]
(OUT/'actual-chunks.json').write_text(json.dumps(chunks,indent=2,ensure_ascii=False),encoding='utf-8')
summary['index']={'path':str(idx),'manifest':json.loads((idx/'generation.json').read_text()) if (idx/'generation.json').exists() else None,'total_docstore':len(store._dict),'mapping_count':len(mapping),'source_chunks':len(chunks),'field_presence':{k:sum(k in c['metadata'] for c in chunks) for k in ('document_id','project_id','revision','page','section','table_id','chunk_id','content_hash','embedding_version','source_sha256','folder_id','evidence_state')}}
summary['source_documents']=[dict(r) for r in conn.execute('SELECT id,filename,status,chunks,path,folder_id FROM documents WHERE project_id=?',(doc['project_id'],))]
(OUT/'inventory.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
import fitz
pdf=fitz.open(path)
pdf[0].get_pixmap(matrix=fitz.Matrix(2,2)).save(str(OUT/'source-page-1.png'))
(OUT/'native-source-text.txt').write_text(pdf[0].get_text(),encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k in ('sha256','metadata_keys','page_summaries','index')},indent=2))
