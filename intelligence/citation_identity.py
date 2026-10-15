"""Request-local citation handles; source identity is assigned by the server.

Handles do not verify claims. Resolved answers must still pass the existing
source/page, quantity, identifier and qualification gates on original evidence.
"""
import re
from intelligence.answer_guard import MARKER


def prepare_citations(context, sources):
    allowed={(str(s.get('source') or s.get('filename') or ''),
              str(s.get('page') if s.get('page') is not None else 'UNPAGINATED').upper())
             for s in sources if isinstance(s,dict)}
    identities={}
    reverse={}
    def replace(match):
        key=(match[1].strip(),match[2].upper())
        if key not in allowed:
            return match[0]
        if key not in reverse:
            handle='EVIDENCE_'+str(len(reverse)+1)
            reverse[key]=handle
            identities[(handle,key[1])]=key
        return f'[SOURCE: {reverse[key]} | PAGE {key[1]}]'
    return MARKER.sub(replace,context),identities


def resolve_citations(answer, identities):
    # Some local models prepend the literal word "Citation:" inside a marker.
    # Normalize only syntax; both the assigned handle and page must still match.
    handle_marker=re.compile(r'\[(?:Citation:\s*)?SOURCE:\s*(EVIDENCE_\d+)\s*\\?\|\s*PAGE\s+(\d+|UNPAGINATED|[^\]|\n]{1,80}?)\s*\]',re.I)
    def replace(match):
        key=(match[1].strip(),match[2].upper())
        target=identities.get(key)
        return f'[SOURCE: {target[0]} | PAGE {target[1]}]' if target else match[0]
    resolved=handle_marker.sub(replace,answer)
    return re.sub(r'\[Citation:\s*(\[SOURCE:\s*[^\[\]]+\|\s*PAGE\s+(?:\d+|UNPAGINATED|[^\]|\n]{1,80}?)\s*\])\]',r'\1',resolved,flags=re.I)


def append_source_qualifications(answer, context, sources):
    """Attach native source dispositions independently of generated prose."""
    from intelligence.answer_guard import _excerpts_by_page
    from intelligence.source_semantics import explicit_states, native_revision
    excerpts=_excerpts_by_page(context)
    allowed={(str(s.get('source') or s.get('filename') or ''),
              str(s.get('page') if s.get('page') is not None else 'UNPAGINATED').upper())
             for s in sources if isinstance(s,dict)}
    notes=[];seen=set()
    for match in MARKER.finditer(answer):
        key=(match[1].strip(),match[2].upper())
        if key in seen or key not in allowed:continue
        seen.add(key);body=excerpts.get(key,'')
        states=explicit_states(body)
        revision=native_revision({'pages':[{'text':body}]})
        labels=[]
        if revision:labels.append('Revision '+revision)
        if states!={'UNKNOWN'}:labels.append('status '+', '.join(sorted(states)))
        if labels:notes.append('; '.join(labels)+f' [SOURCE: {key[0]} | PAGE {key[1]}]')
    return answer+('\n\nSource qualifications: '+ ' / '.join(notes) if notes else '')
