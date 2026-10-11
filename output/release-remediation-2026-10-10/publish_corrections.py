"""Refresh only the audited document's derived index, after a local backup."""
import os,sys,json,hashlib,sqlite3,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(os.environ.get('RELEASE_PUBLICATION_OUTPUT',str(Path(__file__).parent)))
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
inv=json.loads((ROOT/'output/rag-audit-2026-10-08/inventory.json').read_text());doc=inv['document']
backup=OUT/'before-publication';backup.mkdir(exist_ok=True)
with sqlite3.connect('file:'+str(ROOT/'data/expo.db')+'?mode=ro',uri=True) as original,sqlite3.connect(backup/'expo.db') as copy:
    original.backup(copy)
    assert copy.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
idx=ROOT/'data/faiss_index'/doc['project_name']
for name in ('index.faiss','index.pkl','generation.json'):shutil.copy2(idx/name,backup/name)
source=Path(doc['path']);digest=hashlib.sha256(source.read_bytes()).hexdigest()
assert digest==inv['sha256'],'Source changed; revalidate before publication'
meta=json.loads(Path(str(source)+'.index.json').read_text(encoding='utf-8'))
assert meta.get('source_sha256')==digest and meta.get('processing_complete') and not meta.get('truncated')
for key in ('HF_HUB_OFFLINE','TRANSFORMERS_OFFLINE','HF_DATASETS_OFFLINE'):os.environ[key]='1'
import main
from config import resolve_role
from urllib.parse import urlparse
assert urlparse(resolve_role('embed')['base_url']).hostname in ('localhost','127.0.0.1'),'Only local embeddings permitted'
count=main.index_structured(doc['project_name'],meta,doc['filename'],doc['folder_id'])
assert count>0
vs=main.get_vectorstore(doc['project_name'])
chunks=[d for d in vs.docstore._dict.values() if d.metadata.get('source')==doc['filename']]
assert len(chunks)==count
assert not any('Table: F&B Units:' in d.page_content and 'ITEM: TOTAL; NO.: 10' in d.page_content for d in chunks)
with sqlite3.connect(ROOT/'data/expo.db') as conn:
    conn.execute('UPDATE documents SET chunks=? WHERE id=?',(count,doc['id']));conn.commit()
report={'source_sha256':digest,'source_chunks':count,'project_vectors':vs.index.ntotal,
        'backup':str(backup),'mislabelled_combined_total_found':False}
(OUT/'publication.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('Corrected source chunks published:',count,flush=True)
