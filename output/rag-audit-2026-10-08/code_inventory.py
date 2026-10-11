import json,hashlib,ast,collections
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
files=['main.py','config.py','db.py','auth.py','extract.py','vision.py','local_chat.py','local_embed.py','meta_parse.py','services/jobs.py','services/ingestion.py','services/pipeline.py','services/page_ocr.py','services/pdf_inspection.py','services/vision_adapter.py','intelligence/retrieval.py','intelligence/reranker.py','intelligence/table_evidence.py','intelligence/page_context.py','intelligence/exact_answers.py','intelligence/answer_guard.py','intelligence/document_query.py','knowledge/extraction.py','ui/app.js']
inventory={}
for name in files:
    raw=(ROOT/name).read_bytes();info={'sha256':hashlib.sha256(raw).hexdigest()}
    if name.endswith('.py'):
        tree=ast.parse(raw.decode('utf-8-sig'))
        info['functions']={n.name:n.lineno for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
    inventory[name]=info
(OUT/'code-inventory.json').write_text(json.dumps(inventory,indent=2))
chunks=json.loads((OUT/'actual-chunks.json').read_text(encoding='utf-8'))
groups=collections.defaultdict(list)
for c in chunks:groups[(c['metadata']['source'],c['metadata']['page'],c['text'][:120])].append(c)
collisions=[v for v in groups.values() if len({c['text'] for c in v})>1]
(OUT/'rrf-key-collisions.json').write_text(json.dumps(collisions,indent=2,ensure_ascii=False),encoding='utf-8')
print('RRF distinct-text key collisions:',len(collisions))
