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


def source_excerpt(question, evidence, sources):
    if re.search(r'\b(?:calculate|sum|average|difference|convert|approved|approval|revision|current|latest|superseded)\b',question,re.I):
        return None
    tags={m[0].lower() for m in IDENTIFIER.finditer(question) if re.search(r'\d',m[0])}
    properties={m[0].lower() for m in PROPERTIES.finditer(question)}
    if not tags or not properties:return None
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
    if not candidates:return None
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
