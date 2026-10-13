"""Report review observations without equating them to approved engineering facts."""
import json
import re
from pathlib import Path

def inspection_answer(question,documents):
    if not re.search(r'\b(annotations?|review comments?|approval status|document status|stamp|stamps)\b',question,re.I):return None
    requested_pages={int(x) for x in re.findall(r'\bpage\s+(\d+)\b',question,re.I)}
    facts=[];missing=[]
    for doc in documents:
        if doc.get('status','ready') not in ('ready','ready_with_warnings','verified','published'):continue
        if any(d['filename'].lower() in question.lower() for d in documents) and doc['filename'].lower() not in question.lower():continue
        try:
            meta=json.loads(Path(doc['path']+'.index.json').read_text(encoding='utf-8'))
            if meta.get('truncated') or meta.get('processing_complete') is False:continue
            if meta.get('source_sha256'):
                import hashlib
                with open(doc['path'],'rb') as handle:
                    if hashlib.file_digest(handle,'sha256').hexdigest()!=meta['source_sha256']:continue
        except (OSError,ValueError):continue
        for page in meta.get('pages',[]):
            if requested_pages and page['page'] not in requested_pages:continue
            # Preserve explicit native review comments even when they are PDF
            # page text rather than annotation objects. This reports the text,
            # without inferring a selected approval checkbox or authority.
            for comment in re.findall(r'(?m)^\d+\.\s+[^\n]*(?:approval|review|objection|coordination|RFI|setting out)[^\n]*',page.get('text',''),re.I):
                facts.append({'source':doc['filename'],'page':page['page'],
                    'annotation_id':None,'bbox':None,'content':comment.strip(),
                    'observed_stamp_text':'','internal_name':'',
                    'verification_state':'REVIEW_REQUIRED','relationship_state':'REVIEW_REQUIRED',
                    'revision':meta.get('revision')})
            if 'inspection' not in page:missing.append(doc['filename']);continue
            for annotation in page['inspection'].get('annotations',[]):
                content=annotation.get('content','').strip()
                appearance=annotation.get('appearance_text','').strip()
                if not content and annotation['type']!='Stamp':continue
                facts.append({'source':doc['filename'],'page':page['page'],
                    'annotation_id':annotation['id'],'bbox':annotation['bbox'],
                    'content':content,'observed_stamp_text':appearance,
                    'internal_name':annotation.get('internal_name',''),
                    'nearby_native_text':annotation.get('nearby_native_text',[]),
                    'verification_state':'REVIEW_REQUIRED',
                    'relationship_state':'REVIEW_REQUIRED','revision':meta.get('revision')})
    if not facts:
        return {'status':'NOT_FOUND','answer':'No extracted review annotations or visible stamp readings were found. This does not establish approval; visual review may still be required.',
            'sources':[],'facts':[],'warnings':['Inspection unavailable for some sources.'] if missing else []}
    lines=[]
    for fact in facts:
        values=[]
        if fact['content']:values.append('Review comment: '+fact['content'])
        if fact['observed_stamp_text']:values.append('Visible stamp OCR (unverified): '+fact['observed_stamp_text'])
        if fact['internal_name']:values.append('Internal annotation name: '+fact['internal_name']+' (not approval authority)')
        if not values:values.append('Stamp appearance unresolved')
        lines.append('- '+'; '.join(values).rstrip('.')+f". [SOURCE: {fact['source']} | PAGE {fact['page']}]")
    lines.append('REVIEW_REQUIRED: stamp readings and comment-to-object relationships are not independently verified. Conditional approval must retain its comments; document authority is not established by these observations.')
    return {'status':'SUCCESS','answer':'\n'.join(lines),'facts':facts,
        'sources':list({(f['source'],f['page']):{'source':f['source'],'page':f['page']} for f in facts}.values())}
