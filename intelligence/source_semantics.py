"""Explicit source dispositions; filename order is never approval authority."""
import re

STATES=('APPROVED','DRAFT','PROPOSED','SUPERSEDED','PENDING','TBC','EXISTING','CURRENT')

def explicit_states(text):
    matches=re.findall(r'(?im)^\s*(?:approval|document|issue)?\s*status\s*[:=]\s*([^\n;]+)',text or '')
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
    if re.search(r'\bapproved\s+with\s+comments\b',question,re.I):return 'APPROVED_WITH_COMMENTS'
    # Proposed/existing qualifiers are preserved in individual table rows.
    return next((s for s in ('APPROVED','CURRENT','DRAFT','SUPERSEDED','PENDING','TBC','EXISTING')
                 if re.search(r'\b'+s+r'\b'+(r'(?!\s+EV\b)' if s=='CURRENT' else ''),question,re.I)),None)

def supports_authority(states,requested):
    return states=={requested}
