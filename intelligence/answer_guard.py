"""Deterministic publication checks, not a claim of semantic verification.

Reject unknown citations and numeric values absent from the cited page excerpts.
The model output is withheld until these checks complete; generated prose still
requires engineering review even when the mechanical checks pass.
"""
import re
from decimal import Decimal, InvalidOperation


MARKER=re.compile(r'\[SOURCE:\s*(.*?)\s*\|\s*PAGE\s+(\d+|UNPAGINATED)\s*\]',re.I)
NUMBER=re.compile(r'(?<![\w])[-+]?\d[\d,]*(?:\.\d+)?(?![\w])')


def numbers(text):
    result=set()
    text=MARKER.sub('',text)
    # Markdown list indices are presentation, not engineering values.
    text=re.sub(r'(?m)^\s*\d+[.)]\s+','',text)
    for match in NUMBER.finditer(text):
        try:result.add(Decimal(match.group().replace(',','')))
        except InvalidOperation:pass
    return result


_UNITS=r'kg/m3|kg/m³|kN/m2|kN/m²|N/mm2|N/mm²|m3/h|m³/h|m3/s|m³/s|L/s|L/min|L/h|gpm|cfm|square metres|square meters|square feet|sq\.?\s*ft|sq\.?\s*m|sqm|sqft|MPa|kPa|Pa|psi|bar|MW|kW|W|kVA|VA|kV|V|mA|A|Hz|dB|°C|°F|kNm|Nm|kN|N|kg|mm|cm|m²|m2|m³|m3|m|%'
_UNIT_ALIASES={'m2':'sqm','m²':'sqm','sq m':'sqm','sq.m':'sqm','square metres':'sqm','square meters':'sqm',
         'sq ft':'sqft','sq.ft':'sqft','square feet':'sqft','m³':'m3','m³/h':'m3/h','m³/s':'m3/s','kg/m³':'kg/m3'}


def _normalize_unit(unit):
    # Case-sensitive SI prefixes must not collapse milli into mega.
    if unit in ('mPa','mW'):return 'milli'+unit[1:].lower()
    unit=re.sub(r'\s+',' ',unit).lower().strip()
    return _UNIT_ALIASES.get(unit,unit)


def quantity_pairs(text):
    """Keep an explicitly written engineering value attached to its unit.

    Two source conventions are both in play here: prose states a value as
    "34,950 sqm" (unit after the number), while this app's own structured
    table rows (intelligence/table_evidence.py) serialize it the other way
    round, as "Floor GFA (sqm): 34,950" (unit, in parentheses, before the
    number). Only matching the first form meant any answer that paraphrased
    a structured-table figure into ordinary prose ("...GFA is 34,950 sqm")
    got flagged 'Value/unit pair absent from cited page excerpts' and
    withheld, even though the correct, cited number was right there in the
    excerpt -- just with its unit on the other side. Both directions are
    matched and normalized into the same (value, unit) pairs."""
    cleaned=MARKER.sub('',text)
    if re.search(r'(?m)^\s*\|',cleaned):
        from intelligence.table_evidence import table_row_units
        cleaned+='\n'+'\n'.join(table_row_units(cleaned))
    pattern_after=r'(?<![\w])([-+]?\d[\d,]*(?:\.\d+)?)(?:\s|\*)*(' + _UNITS + r')(?![A-Za-z0-9])'
    # Markdown pipe tables (the raw table geometry text.select_page_context
    # surfaces verbatim) put the unit-labeled header in one cell and the value
    # in the next: "| Floor BUA (sqm) | 121,085 |", not "(sqm): 121,085" --
    # a different separator than table_evidence.py's own colon-joined
    # 'Label (unit): value' serialization. Accept either.
    pattern_before=r'\((' + _UNITS + r')\)\s*[:|]\s*([-+]?\d[\d,]*(?:\.\d+)?)(?![A-Za-z0-9])'
    pairs=set()
    for match in re.finditer(pattern_after,cleaned,re.I):
        unit=_normalize_unit(match[2])
        try:pairs.add((Decimal(match[1].replace(',','')),unit))
        except InvalidOperation:pass
    for match in re.finditer(pattern_before,cleaned,re.I):
        unit=_normalize_unit(match[1])
        try:pairs.add((Decimal(match[2].replace(',','')),unit))
        except InvalidOperation:pass
    return pairs


def _excerpts_by_page(evidence):
    """Split `evidence` (the assembled retrieval context) into a dict keyed by
    (filename, page) -> that page's own excerpt text, stripping any
    OCR/vision observation tail (unverified, can't support a cited claim).
    Shared by publication_issues and auto_cite so both agree on exactly what
    a given cited page actually contains."""
    excerpts={}
    matches=list(MARKER.finditer(evidence))
    for index,match in enumerate(matches):
        key=(match.group(1).strip(),match.group(2).upper())
        body=evidence[match.end():matches[index+1].start() if index+1<len(matches) else len(evidence)]
        body=re.split(r'\[(?:UNVERIFIED[^\]]*|DRAWING/VISION)\]',body,maxsplit=1,flags=re.I)[0]
        excerpts[key]=excerpts.get(key,'')+'\n'+body
    return excerpts


def _numeric_text(answer,sources):
    """`answer` with every retrieved document's filename/stem stripped out.
    Document identifiers contain digits but are not engineering quantities,
    so they'd otherwise pollute numbers()/quantity_pairs() scanning. Shared
    by publication_issues and auto_cite so both agree on exactly which
    numbers an answer is actually asserting."""
    numeric_text=answer
    for source in sources:
        if not isinstance(source,dict): continue
        identifier=str(source.get('filename') or source.get('source') or '')
        for name in (identifier,identifier.replace('\\','/').split('/')[-1]):
            if re.search(r'\.[a-z0-9]{1,10}$',name,re.I):
                numeric_text=re.sub(re.escape(name),'',numeric_text,flags=re.I)
                stem=name.rsplit('.',1)[0]
                if len(stem)>8 and re.search(r'\d',stem):
                    numeric_text=re.sub(re.escape(stem),'',numeric_text,flags=re.I)
    return numeric_text


def auto_cite(answer,evidence,sources):
    """Recover an answer the model got numerically right but forgot to cite.

    Observed live: the identical request sometimes comes back with a trailing
    [SOURCE: file | PAGE n] bracket and sometimes without one -- pure
    generation non-determinism, not a wrong answer. Losing zero citations
    cascades into every other publication check failing too (nothing is
    "supported" when nothing is cited), so one missing bracket discards an
    otherwise-correct, otherwise-verifiable answer.

    This does not invent a citation: a page only qualifies when its own
    retrieved excerpt, independently, already contains every bare number and
    every value+unit pair the answer asserts. If more than one retrieved
    page qualifies (ambiguous -- can't tell which one the model actually
    read) or none do (the answer isn't actually supported), this returns
    None and the normal refusal stands.
    """
    if MARKER.search(answer):
        return None
    numeric_text=_numeric_text(answer,sources)
    numeric=numbers(numeric_text)
    pairs=quantity_pairs(numeric_text)
    if not numeric and not pairs:
        return None
    excerpts=_excerpts_by_page(evidence)
    seen=set()
    candidates=[]
    for source in sources:
        if not isinstance(source,dict): continue
        key=(str(source.get('source') or source.get('filename') or ''),
             str(source.get('page') if source.get('page') is not None else 'UNPAGINATED'))
        if key in seen: continue
        seen.add(key)
        body=excerpts.get(key,'')
        if not body: continue
        if numeric-numbers(body): continue
        if pairs-quantity_pairs(body): continue
        candidates.append(key)
    if len(candidates)!=1:
        return None
    filename,page=candidates[0]
    return answer.rstrip()+f'\n\n[SOURCE: {filename} | PAGE {page}]'


def publication_issues(answer,evidence,sources):
    excerpts=_excerpts_by_page(evidence)
    allowed={(str(s.get('source') or s.get('filename') or ''),str(s.get('page') if s.get('page') is not None else 'UNPAGINATED')) for s in sources if isinstance(s,dict)}
    citations={(m.group(1).strip(),m.group(2).upper()) for m in MARKER.finditer(answer)}
    issues=[]
    if citations-allowed:issues.append('Citation outside retrieved sources')
    # Document identifiers contain digits but are not engineering quantities.
    # Exclude only exact filenames from the accessible retrieved source set;
    # numeric claims elsewhere still require their source/page citations.
    numeric_text=_numeric_text(answer,sources)
    numeric=numbers(numeric_text)
    if numeric and not citations:issues.append('Numeric answer lacks exact source/page citations')
    supported=set()
    for key in citations:
        supported.update(numbers(excerpts.get(key,'')))
    if numeric-supported:issues.append('Numeric values absent from cited page excerpts')
    cited_text='\n'.join(excerpts.get(key,'') for key in citations)
    # Only treat "approved" as a document/drawing/submission approval-status
    # assertion -- not generic technical usage like "approved equipment",
    # "code-approved design", or "approved for use" (e.g. a sprinkler system
    # answer) -- which explicit_states() could never match anyway, since it
    # only recognizes explicit "status:"/"approval status:"/"issue status:"
    # lines in the cited text. Require "approved" to appear near a
    # document/submission-authority context word before applying this check.
    _APPROVAL_CONTEXT=r'(?:design|document|drawing|submittal|submission|revision|stamp|stamped|review(?:ed)?|resubmit(?:tal)?|issue(?:d)?\s+for|shop\s+drawing)'
    if re.search(r'(?<!not )(?<!un)\bapproved\b',numeric_text,re.I) and re.search(
        r'(?:'+_APPROVAL_CONTEXT+r'[^.]{0,60}\bapproved\b|\bapproved\b[^.]{0,60}'+_APPROVAL_CONTEXT+r')',
        numeric_text,re.I,
    ) or re.search(r'^\s*approved(?:\s+with\s+comments)?\s*[.!\[]',numeric_text,re.I):
        from intelligence.source_semantics import explicit_states
        conditional=bool(re.search(r'\bapproved\s+with\s+comments\b',numeric_text,re.I))
        required='APPROVED_WITH_COMMENTS' if conditional else 'APPROVED'
        if explicit_states(cited_text)!={required}:
            issues.append('Approval assertion lacks explicit matching source authority')
    # Only flag a genuine value/unit CONFLICT -- the same numeric value tied
    # to a different unit in the cited excerpt than the answer states -- not
    # merely "this excerpt has no unit text next to the number at all".
    # Structured table rows surfaced verbatim (e.g. document_memory's
    # evidence_quote, or a raw pipe-table excerpt) often put the unit only
    # in a column header above the row ("ITEM | SQ.M. | SQ.FT." ... then,
    # several rows down, "Plot Area: | 39,681.19 | 427,124.36" with no unit
    # text anywhere near the value itself). Requiring textual adjacency in
    # that case rejected correct, already-numerically-verified answers
    # (numbers(numeric_text)-numbers(cited_text) above already confirms the
    # bare value is present) just for writing the unit in prose. Found via
    # the Phase 3 benchmark (2026-10-09): Plot Area, 1BR/2BR unit areas.
    answer_pairs=quantity_pairs(numeric_text)
    cited_pairs=quantity_pairs(cited_text)
    conflicting_pairs=answer_pairs-cited_pairs
    if conflicting_pairs:
        issues.append('Value/unit pair absent from cited page excerpts')
    # Native prose can explicitly associate a property/value with one entity.
    # A different entity's value elsewhere on the same page is not support.
    from intelligence.source_excerpt import PROPERTIES, IDENTIFIER
    for sentence in re.split(r'\n+|(?<=[.!?])\s+(?=[A-Z])',MARKER.sub('',numeric_text)):
        entities={m[0].lower() for m in IDENTIFIER.finditer(sentence) if re.search(r'\d',m[0])}
        properties={m[0].lower() for m in PROPERTIES.finditer(sentence)}
        pairs=quantity_pairs(sentence)
        if len(entities)!=1 or not properties or not pairs:continue
        entity=next(iter(entities));explicit=[]
        for line in re.split(r'\n+|(?<=[.!?])\s+(?=[A-Z])',cited_text):
            if not re.search(r'(?<![\w-])'+re.escape(entity)+r'(?![\w-])',line,re.I):continue
            if properties.issubset({m[0].lower() for m in PROPERTIES.finditer(line)}) and quantity_pairs(line):
                explicit.append(quantity_pairs(line))
        if explicit and any(pairs-supported for supported in explicit):
            issues.append('Entity/property quantity conflicts with explicit native evidence')
            break
    # Preserve mixed letter/number tags as complete identifiers, not just their
    # numeric suffixes (e.g. SYN-060 is different from SYNTH-060).
    tag_pattern=r'\b[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*\b'
    tags={m.group().lower() for m in re.finditer(tag_pattern,MARKER.sub('',numeric_text))
          if re.search(r'\d',m.group()) and m.group().lower() not in ('m2','m3','mm2','mm3','cm2','cm3','kn/m2')}
    for tag in tags:
        if not re.search(r'(?<![\w-])'+re.escape(tag)+r'(?![\w-])',cited_text,re.I):
            issues.append('Identifier absent from cited page excerpts')
            break
    return issues


def guarded_answer(answer,evidence,sources):
    issues=publication_issues(answer,evidence,sources)
    if issues:
        return ('I could not verify the generated answer against the retrieved source pages. '
                'Please review the listed sources or ask for a specific field and page.'),issues
    return answer,[]


def guarded_answer_with_repair(answer,evidence,sources,repair):
    """Allow one bounded correction, then one deterministic auto-citation
    attempt (see auto_cite) before giving up. Every candidate passes the
    same checks -- auto_cite never bypasses verification, it only supplies
    a citation bracket when one retrieved page already, provably, supports
    everything the answer claims."""
    published,issues=guarded_answer(answer,evidence,sources)
    if not issues:
        return published,[]
    candidate=answer
    try:
        repaired=repair(issues)
        if isinstance(repaired,str) and repaired.strip():
            candidate=repaired
            published,issues=guarded_answer(candidate,evidence,sources)
            if not issues:
                return published,[]
    except Exception:
        pass
    cited=auto_cite(candidate,evidence,sources)
    if cited:
        published2,issues2=guarded_answer(cited,evidence,sources)
        if not issues2:
            return published2,[]
    return published,issues
