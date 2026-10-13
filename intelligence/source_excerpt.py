"""Conservative native-evidence fallback when generated prose fails validation.

Return an attributed quotation, never repair an invented model citation. Require
the requested identifier and property together in one native sentence. Multiple
different matching statements are a conflict, not a license to choose a value.
"""
import re
from intelligence.answer_guard import _excerpts_by_page, guarded_answer, quantity_pairs
from intelligence.source_semantics import explicit_states

PROPERTIES=re.compile(r'\b(?:pressure|width|length|height|diameter|thickness|capacity|temperature|load|voltage|power|flow|level|spacing)\b',re.I)
IDENTIFIER=re.compile(r'\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+\b')

_TABLE_STOP={'what','which','where','when','who','how','many','much','does','do','did','is','are','was','were',
    'the','a','an','for','of','in','on','at','to','and','or','me','my','this','that','please','tell','show',
    'give','send','provide','details','detail','information','info','answer','project','document','pdf','table',
    'schedule','all','full','breakdown','about','from','with','per'}
_TEXT_STOP=_TABLE_STOP-{'project','document','drawing','schedule','table','pdf'}


def _native_table_excerpt(question,evidence,sources):
    """Quote an exact native table row when generated prose fails validation.

    This is a retrieval fallback, not an answer synthesizer: only rows from the
    authorized cited pages are eligible, and ambiguous row matches are withheld.
    """
    from intelligence.table_evidence import table_row_units
    allowed={(str(s.get('source') or s.get('filename') or ''),
              str(s.get('page') if s.get('page') is not None else 'UNPAGINATED'))
             for s in sources if isinstance(s,dict)}
    query_terms={t.casefold() for t in re.findall(r'[A-Za-z0-9]+',question)
                 if t.casefold() not in _TABLE_STOP and len(t)>1}
    if len(query_terms)<2:return None
    rows=[]
    clipped_pages=set()
    for key,body in _excerpts_by_page(evidence).items():
        if key not in allowed:continue
        if '[EXCERPT ENDS; REST OF THIS PAGE NOT INCLUDED]' in body:
            clipped_pages.add(key)
        # Vision/OCR observations stay ineligible. Native PDF text and parsed
        # table fields precede this explicit unverified-observation boundary.
        native=body.split('[UNVERIFIED EXTRACTION; REVIEW_REQUIRED]',1)[0]
        if '[UNVERIFIED OCR]' in native or 'REVIEW_REQUIRED' in native:continue
        for row in table_row_units(native):
            fields={}
            for line in row.splitlines():
                if line.startswith('Table:'):
                    fields['table']=line.split(':',1)[1].strip()
            if not fields.get('table'):continue
            normalized=' '.join(re.findall(r'[a-z0-9]+',row.casefold()))
            row_terms=set(normalized.split())
            title_terms=set(re.findall(r'[a-z0-9]+',fields['table'].casefold()))
            rows.append({'key':key,'text':row,'terms':row_terms,'title':fields['table'],
                         'title_terms':title_terms})
    unique={(r['key'],re.sub(r'\s+',' ',r['text']).casefold()):r for r in rows}
    rows=list(unique.values())
    if not rows:return None
    # A question that names a table heading can safely request its rows. Do not
    # combine same-named tables from multiple pages or source documents.
    named=[r for r in rows if r['title_terms'] and r['title_terms'].issubset(query_terms)]
    if named:
        title_keys={(r['key'],r['title'].casefold()) for r in named}
        if len(title_keys)!=1:return None
        key,title=next(iter(title_keys))
        if key in clipped_pages:return None
        chosen=[r for r in rows if r['key']==key and r['title'].casefold()==title]
    else:
        scored=[(len(query_terms & r['terms']),r) for r in rows]
        best=max(score for score,_ in scored)
        if best<2:return None
        chosen=[r for score,r in scored if score==best]
        if len(chosen)!=1:return None
        # Exact drawing/equipment identifiers must occur in the selected row;
        # never transfer a value from a neighboring entity or page.
        tags={m[0].casefold() for m in IDENTIFIER.finditer(question) if re.search(r'\d',m[0])}
        if tags and not all(tag in chosen[0]['text'].casefold() for tag in tags):return None
    if len({r['key'] for r in chosen})!=1:return None
    filename,page=chosen[0]['key']
    citation=f'[SOURCE: {filename} | PAGE {page}]'
    answer='\n'.join(f'> {row["text"]} {citation}' for row in chosen)
    checked,issues=guarded_answer(answer,evidence,sources,question=question)
    return checked if not issues else None


def _native_text_excerpt(question,evidence,sources):
    """Quote one unambiguous native sentence when a PDF answer is in prose."""
    allowed={(str(s.get('source') or s.get('filename') or ''),
              str(s.get('page') if s.get('page') is not None else 'UNPAGINATED'))
             for s in sources if isinstance(s,dict)}
    query_terms={t.casefold() for t in re.findall(r'[A-Za-z0-9]+',question)
                 if t.casefold() not in _TEXT_STOP and len(t)>1}
    if len(query_terms)<2:return None
    tags={m[0].casefold() for m in IDENTIFIER.finditer(question) if re.search(r'\d',m[0])}
    properties={m[0].casefold() for m in PROPERTIES.finditer(question)}
    codes={m.group().casefold() for m in re.finditer(r'\b[A-Za-z]{2,}\s*\d{2,}\b', question)}
    threshold=max(2,(len(query_terms)+2)//3)
    candidates=[]
    for key,body in _excerpts_by_page(evidence).items():
        if key not in allowed or '[UNVERIFIED OCR]' in body or 'REVIEW_REQUIRED' in body:continue
        native=body.split('[UNVERIFIED EXTRACTION; REVIEW_REQUIRED]',1)[0]
        for sentence in re.split(r'\n+|(?<=[.!?])\s+(?=[A-Z])',native):
            sentence=sentence.strip()
            if not sentence or sentence.startswith('|') or '[TABLE ROW]' in sentence or len(sentence)>700:continue
            if re.search(r'\b(?:review\s+comments|shared\s+during\s+this\s+stage)\b', sentence, re.I):continue
            alpha=re.findall(r'[A-Za-z]+',sentence)
            if alpha and all(word.isupper() for word in alpha):continue
            normalized=sentence.casefold()
            if tags and not all(re.search(r'(?<![\w-])'+re.escape(tag)+r'(?![\w-])',sentence,re.I) for tag in tags):continue
            if properties and not properties.issubset({m[0].casefold() for m in PROPERTIES.finditer(sentence)}):continue
            if codes and not all(re.search(r'\b' + re.escape(c) + r'\b', normalized, re.I) for c in codes):continue
            words=set(re.findall(r'[a-z0-9]+',normalized))
            score=len(query_terms & words)
            if score>=threshold:candidates.append((score,sentence,key))
    if not candidates:return None
    best=max(row[0] for row in candidates)
    winners={(re.sub(r'\s+',' ',sentence).casefold(),key) for score,sentence,key in candidates if score==best}
    if len(winners)!=1:return None
    sentence,key=next(iter(winners))
    # Recover original casing after deduplication.
    original=next(sentence_text for score,sentence_text,candidate_key in candidates
                  if score==best and re.sub(r'\s+',' ',sentence_text).casefold()==sentence and candidate_key==key)
    filename,page=key
    answer=f'> {original} [SOURCE: {filename} | PAGE {page}]'
    checked,issues=guarded_answer(answer,evidence,sources,question=question)
    return checked if not issues else None


def source_excerpt(question, evidence, sources):
    if re.search(r'\b(?:calculate|sum|average|difference|convert|approved|approval|revision|current|latest|superseded)\b',question,re.I):
        return None
    tags={m[0].lower() for m in IDENTIFIER.finditer(question) if re.search(r'\d',m[0])}
    properties={m[0].lower() for m in PROPERTIES.finditer(question)}
    if not tags or not properties:
        return (_native_table_excerpt(question,evidence,sources)
                or _native_text_excerpt(question,evidence,sources))
    allowed={(str(s.get('source') or s.get('filename') or ''),
              str(s.get('page') if s.get('page') is not None else 'UNPAGINATED'))
             for s in sources if isinstance(s,dict)}
    candidates=[]
    for key,body in _excerpts_by_page(evidence).items():
        if key not in allowed:continue
        for sentence in re.split(r'\n+|(?<=[.!?])\s+(?=[A-Z])',body):
            sentence=sentence.strip()
            if not sentence or len(sentence)>650 or not quantity_pairs(sentence):continue
            if not all(re.search(r'(?<![\w-])'+re.escape(tag)+r'(?![\w-])',sentence,re.I) for tag in tags):continue
            if not properties.issubset({m[0].lower() for m in PROPERTIES.finditer(sentence)}):continue
            candidates.append((sentence,key,explicit_states(body)))
    if not candidates:
        return (_native_table_excerpt(question,evidence,sources)
                or _native_text_excerpt(question,evidence,sources))
    # Do not silently choose across contradictory values, wording or status.
    if len({(re.sub(r'\s+',' ',s).lower(),tuple(sorted(states))) for s,_,states in candidates})!=1:
        return None
    sentence,(filename,page),states=candidates[0]
    disposition=', '.join(sorted(states))
    answer=(f'The source states (verbatim):\n\n> {sentence}\n\n'
            f'[SOURCE: {filename} | PAGE {page}]\n\n'
            f'Source disposition: {disposition}. This excerpt does not establish engineering approval.')
    checked,issues=guarded_answer(answer,evidence,sources)
    return checked if not issues else None
