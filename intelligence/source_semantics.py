"""Explicit source dispositions; filename order is never approval authority."""
import re

STATES=('APPROVED','DRAFT','PROPOSED','SUPERSEDED','PENDING','TBC','EXISTING','CURRENT')

def explicit_states(text):
    # Title blocks use several explicit label orders. Recognize the label
    # variant without widening authority: only a value attached to a status
    # label can establish a disposition.
    matches=re.findall(
        r'(?im)(?:^|[.;]\s+)\s*(?:(?:approval|document|issue|drawing|revision|'
        r'submission|submittal|design|construction)\s+)?(?:status|code)\s*'
        r'(?:of\s+(?:the\s+)?(?:drawing|document|submission)\s*)?[:=]\s*([^\n;.]+)',
        text or '')
    code_matches = re.findall(r'(?im)\bCode\s+([A-Z])\s*[-—:]\s*([^\n;.]+)', text or '')
    for letter, desc in code_matches:
        matches.append(f'Code {letter} - {desc}')
    result=set()
    for value in matches:
        if re.search(r'\b(?:not|unapproved|no approval)\b',value,re.I):
            result.add('UNKNOWN');continue
        if re.search(r'\bapproved\s+with\s+comments\b',value,re.I):
            result.add('APPROVED_WITH_COMMENTS')
        for state in STATES:
            if state=='APPROVED' and re.search(r'\bapproved\s+with\s+comments\b',value,re.I):continue
            if re.search(r'\b'+state+r'\b',value,re.I):result.add(state)
    return result or {'UNKNOWN'}

def requested_authority(question):
    if re.search(r'\b(?:approved\s+with\s+comments|code\s+b)\b',question,re.I):return 'APPROVED_WITH_COMMENTS'
    # Proposed/existing qualifiers are preserved in individual table rows.
    return next((s for s in ('APPROVED','CURRENT','DRAFT','SUPERSEDED','PENDING','TBC','EXISTING')
                 if re.search(r'\b'+s+r'\b'+(r'(?!\s+EV\b)' if s=='CURRENT' else ''),question,re.I)),None)

def supports_authority(states,requested):
    return states=={requested}


def native_revision(meta, page=None):
    """A unique explicit native revision, never a filename or model inference."""
    revisions=set()
    for entry in meta.get('pages',[]):
        if page is not None and str(entry.get('page'))!=str(page):continue
        text=(str(entry.get('text') or '')+'\n'+str(entry.get('tables') or '')).replace('|',' ')
        for value in re.findall(r'\b(?:document\s+)?rev(?:ision)?\b\s*(?:no\.?|number)?\s*[:.|]*\s*([A-Za-z0-9-]+)',text,re.I):
            if value.upper() in {'NO','NUMBER','DESCRIPTION','DRAWING','S','TITLE'}:continue
            if re.fullmatch(r'(?:[A-Za-z]{1,3}|[A-Za-z0-9-]*\d[A-Za-z0-9-]*)',value):
                revisions.add(value.upper())
        for val in re.findall(r'(?im)^Rev(?:ision)?\b[^\n]*\n(?:[^\n]*\n){1,6}?([A-Z0-9]{1,4})\s*\n(?:FIRST\s+ISSUE|FOR\s+|ISSUED\s+)', text):
            if val.upper() not in {'NO','NUMBER','DESCRIPTION','DRAWING','S','TITLE'}:
                revisions.add(val.upper())
    return next(iter(revisions)) if len(revisions)==1 else None


def revision_for_source(path,page=None):
    import json,hashlib
    try:
        with open(str(path)+'.index.json',encoding='utf-8') as handle:meta=json.load(handle)
        if meta.get('source_sha256'):
            with open(path,'rb') as handle:
                if hashlib.file_digest(handle,'sha256').hexdigest()!=meta['source_sha256']:return None
        return native_revision(meta,page)
    except (OSError,ValueError,TypeError):return None


def requested_project_code(question):
    match=re.search(r'\bproject\s+(?:(?:code|id|number)\s*[:#]?\s*)?["\']?([A-Za-z]+\d[\w-]*|[A-Za-z]+(?:-[A-Za-z0-9]+)+)\b',question,re.I)
    return match.group(1).upper() if match else None


def native_project_codes(meta):
    # Prefer the table's explicit label/value relationship. Flattened PDF text
    # can separate cells (for example, "Project ID:\\n10" beside C3045),
    # creating a false project code if neighboring content is regex-matched.
    structured=set()
    for page in meta.get('pages',[]):
        for line in str(page.get('tables') or '').splitlines():
            if not line.lstrip().startswith('|'):
                continue
            cells=[cell.strip() for cell in line.strip().strip('|').split('|')]
            for index,cell in enumerate(cells):
                if not re.search(r'\bproject\s+(?:code|id|number)\b',cell,re.I):
                    continue
                inline=re.search(r'\bproject\s+(?:code|id|number)\b\s*[:=]?\s*([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\b',cell,re.I)
                if inline and inline.group(1).upper() not in {'CODE','ID','NUMBER'}:
                    structured.add(inline.group(1).upper())
                else:
                    for value in cells[index+1:]:
                        value=value.strip().strip(':')
                        if value and not re.fullmatch(r':?-+:?',value):
                            if re.fullmatch(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*',value):
                                structured.add(value.upper())
                            break
    if structured:
        return structured
    text='\n'.join(str(p.get('text') or '') for p in meta.get('pages',[]))
    return {value.upper() for value in re.findall(r'(?im)\bproject\s+(?:code|id|number)\s*[:=]\s*([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\b',text)}
