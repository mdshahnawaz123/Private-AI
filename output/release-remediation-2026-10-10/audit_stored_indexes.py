"""Read-only manifest/source audit; no untrusted pickle deserialization."""
import sqlite3,json,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'output/remaining-release-checks-2026-10-10'
sys.path.insert(0,str(ROOT))
with sqlite3.connect('file:'+str(ROOT/'data/expo.db')+'?mode=ro',uri=True) as c:
    c.row_factory=sqlite3.Row
    rows=[dict(r) for r in c.execute('select p.name project,d.filename,d.path,d.status,d.chunks,d.deleted_at from documents d join projects p on d.project_id=p.id where d.deleted_at is null and p.deleted_at is null')]
    result={'database_integrity':c.execute('pragma integrity_check').fetchone()[0],
        'foreign_key_violations':len(c.execute('pragma foreign_key_check').fetchall()),
        'alembic_version':c.execute('select version_num from alembic_version').fetchone()[0],
        'documents':[],'indexes':[]}
for row in rows:
    if Path(row['filename']).suffix.lower() not in {'.pdf','.png','.jpg','.jpeg','.xlsx','.docx'}:continue
    entry={k:row[k] for k in ('project','filename','status','chunks')};issues=[]
    p=Path(row['path']);side=Path(str(p)+'.index.json')
    if not p.is_file():issues.append('SOURCE_MISSING')
    if side.is_file():
        try:
            meta=json.loads(side.read_text(encoding='utf-8'))
            if not meta.get('source_sha256'):issues.append('SOURCE_HASH_MISSING')
            elif p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()!=meta['source_sha256']:issues.append('SOURCE_HASH_MISMATCH')
            if row['status'] in ('ready','ready_with_warnings'):
                if meta.get('processing_complete') is not True:issues.append('READY_WITHOUT_COMPLETE_MARKER')
                if meta.get('truncated'):issues.append('READY_TRUNCATED')
            if row['filename'].lower().endswith('.pdf'):
                pages=meta.get('pages',[])
                entry['pages']=len(pages)
                entry['ocr_review_pages']=sum(str(p.get('page_ocr_status','')).endswith('REVIEW_REQUIRED') for p in pages)
                # Legacy defect signature from the independently audited sheet.
                from intelligence.table_evidence import table_row_units
                units=[u for page in pages for u in table_row_units(page.get('tables',''))]
                entry['native_table_rows']=len(units)
        except Exception as e:issues.append('SIDECAR_READ_ERROR:'+str(e))
    elif row['status'] in ('ready','ready_with_warnings'):issues.append('READY_WITHOUT_SIDECAR')
    entry['issues']=issues;result['documents'].append(entry)
for directory in (ROOT/'data/faiss_index').iterdir():
    if not directory.is_dir() or '.previous-' in directory.name or '.staging-' in directory.name:continue
    manifest=directory/'generation.json';entry={'project':directory.name,'issues':[]}
    try:
        data=json.loads(manifest.read_text())
        entry['chunks']=data.get('chunks');entry['embedding_model']=data.get('embedding_model')
        for name,digest in data['sha256'].items():
            if name not in ('index.faiss','index.pkl'):entry['issues'].append('INVALID_MANIFEST_FILENAME');continue
            p=directory/name
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:entry['issues'].append('INDEX_HASH_MISMATCH:'+name)
    except Exception as e:entry['issues'].append('MANIFEST_UNAVAILABLE:'+type(e).__name__)
    result['indexes'].append(entry)
(OUT/'stored-index-audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({'documents_checked':len(result['documents']),'documents_with_issues':sum(bool(d['issues']) for d in result['documents']),
    'indexes_checked':len(result['indexes']),'indexes_with_issues':sum(bool(d['issues']) for d in result['indexes']),
    'database_integrity':result['database_integrity'],'alembic_version':result['alembic_version']}))
