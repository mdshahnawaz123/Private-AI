"""Bounded, read-only source coverage for questions that cannot use scalar shortcuts."""
import json
import re
from pathlib import Path


def needs_coverage(query):
    return bool(re.search(r'\b(not available|not provided|missing|absent|not included|not stated|unavailable)\b',query,re.I))


def focused_chunk_allowed(metadata, scope):
    """Filename alone is insufficient when a project has duplicate names in folders."""
    if scope is None:return True
    source=metadata.get('source')
    return source in scope and metadata.get('folder_id')==scope[source]


def inspect_coverage(documents, max_chars=48000):
    """Read each native page in the authorized source set; report gaps, never infer absence."""
    sources=[];blocks=[];used=0;complete=bool(documents);gaps=[]
    for doc in documents:
        try:
            meta=json.loads(Path(doc['path']+'.index.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):
            complete=False;gaps.append(doc['filename']+': extraction unavailable');continue
        pages=meta.get('pages',[])
        if not pages or meta.get('truncated') or meta.get('total_pages',len(pages))>len(pages):complete=False
        for page in pages:
            native=str(page.get('text','') or '').strip()
            tables=str(page.get('tables','') or '').strip()
            body=native+'\n'+tables
            if not native:
                complete=False;gaps.append(f"{doc['filename']} page {page.get('page')}: native coverage missing")
            block=f"[SOURCE: {doc['filename']} | PAGE {page.get('page')}]\n{body}"
            if used+len(block)>max_chars:
                complete=False;gaps.append('Source coverage exceeds this investigation budget');continue
            sources.append({'source':doc['filename'],'page':page.get('page')});blocks.append(block);used+=len(block)
    instruction=('COVERAGE INVESTIGATION: Read all supplied native page text and tables. '
                 'Answer the requested missing-information question, not merely a related named fact. '
                 'Distinguish what the source explicitly states from details not found in the inspected extraction. '
                 'Extracted-text coverage cannot establish that an image contains no additional information. '
                 'Preserve this uncertainty and do not certify engineering compliance. ')
    instruction+='Native extraction coverage '+('complete within budget.' if complete else 'INCOMPLETE: '+'; '.join(gaps))
    return sources,instruction+'\n\n'+'\n\n'.join(blocks),complete
