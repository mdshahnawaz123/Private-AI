import sys,json,hashlib,sqlite3,collections,pickle
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent;sys.path.insert(0,str(ROOT))
from intelligence.table_evidence import table_row_units
import extract,meta_parse
inv=json.loads((OUT/'inventory.json').read_text(encoding='utf-8'));doc=inv['document'];meta=json.loads((OUT/'stored-extraction.json').read_text(encoding='utf-8'))
chunks=json.loads((OUT/'actual-chunks.json').read_text(encoding='utf-8')); counts=collections.Counter(c['text'] for c in chunks)
duplicates=[{'count':n,'text':t} for t,n in counts.items() if n>1]
pages=meta['pages']; tables=pages[0]['tables'];units=table_row_units(tables)
combined,fresh=extract.extract_pdf(doc['path'],deep=False)
result={'same_source_duplicates':duplicates,'duplicate_uuid_count':len(chunks)-len({c['chunk_id'] for c in chunks}), 'states':dict(collections.Counter(c['metadata']['evidence_state'] for c in chunks)), 'table_row_units':len(units),'native_table_matches_current_extractor':fresh['pages'][0]['tables']==tables,'native_text_matches_current_extractor':fresh['pages'][0]['text']==pages[0]['text'],'fresh_geometry_table_count':fresh['pages'][0]['table_count'],'printed_revision_in_table':'3','filename_metadata':meta_parse.parse_drawing_meta(doc['filename']),'ocr_status':pages[0].get('page_ocr_status'),'inspection':pages[0].get('inspection',{}).get('annotations',[]),'section_count':'NOT STORED; Table titles exist inside row text','database_counts':{k:len(v['rows']) for k,v in inv.items() if isinstance(v,dict) and 'rows' in v},'source_hash_mismatch_chunks':sum(c['metadata'].get('source_sha256')!=inv['sha256'] for c in chunks),'old_index_generations':[]}
idx=ROOT/'data/faiss_index'/doc['project_name']; result['current_manifest_hashes_match']={name:hashlib.sha256((idx/name).read_bytes()).hexdigest()==digest for name,digest in inv['index']['manifest']['sha256'].items()}
for directory in sorted(idx.parent.glob(doc['project_name']+'.previous-*')):
    with (directory/'index.pkl').open('rb') as f:store,mapping=pickle.load(f)
    old=[d for d in store._dict.values() if d.metadata.get('source')==doc['filename']]
    result['old_index_generations'].append({'directory':directory.name,'source_chunks':len(old),'active':False,'current_source_text_equal':collections.Counter(d.page_content for d in old)==counts})
conn=sqlite3.connect('file:'+str(ROOT/'data/ingestion-jobs.sqlite3')+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row
result['jobs']=[{k:v for k,v in dict(row).items() if k not in ('payload',)} for row in conn.execute('SELECT * FROM jobs WHERE source=?',(str(Path(doc['path']).resolve()),))]
selected=[]
for term in ('FAR Allowed','Plot Area','GFA Allowed','GFA Proposed','BUA Proposed','Podium:','Towers:','804','5th Floor','CONSULTANTS'):
    matches=[c for c in chunks if term.lower() in c['text'].lower()]
    matches.sort(key=lambda c:(c['metadata']['evidence_state']!='INTERPRETED',not c['text'].startswith('[TABLE ROW]')))
    selected.append({'term':term,'count':len(matches),'chunks':matches[:3]})
(OUT/'storage-findings.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
(OUT/'selected-chunks.json').write_text(json.dumps(selected,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('same_source_duplicates','jobs','old_index_generations')},indent=2,ensure_ascii=False))
