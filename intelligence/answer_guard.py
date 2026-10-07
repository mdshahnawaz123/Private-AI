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


def quantity_pairs(text):
    """Keep an explicitly written engineering value attached to its unit."""
    aliases={'m2':'sqm','m²':'sqm','sq m':'sqm','sq.m':'sqm','square metres':'sqm','square meters':'sqm',
             'sq ft':'sqft','sq.ft':'sqft','square feet':'sqft'}
    pattern=r'(?<![\w])([-+]?\d[\d,]*(?:\.\d+)?)(?:\s|\*)*(kN/m2|kN/m²|N/mm2|N/mm²|square metres|square meters|square feet|sq\.?\s*ft|sq\.?\s*m|sqm|sqft|MPa|kPa|bar|mm|cm|m²|m2|m|%)(?![A-Za-z0-9])'
    pairs=set()
    for match in re.finditer(pattern,MARKER.sub('',text),re.I):
        unit=re.sub(r'\s+',' ',match[2]).lower().strip()
        unit=aliases.get(unit,unit)
        try:pairs.add((Decimal(match[1].replace(',','')),unit))
        except InvalidOperation:pass
    return pairs


def publication_issues(answer,evidence,sources):
    excerpts={}
    matches=list(MARKER.finditer(evidence))
    for index,match in enumerate(matches):
        key=(match.group(1).strip(),match.group(2).upper())
        body=evidence[match.end():matches[index+1].start() if index+1<len(matches) else len(evidence)]
        # OCR/model observations cannot support verified engineering claims.
        body=re.split(r'\[(?:UNVERIFIED[^\]]*|DRAWING/VISION)\]',body,maxsplit=1,flags=re.I)[0]
        excerpts[key]=excerpts.get(key,'')+'\n'+body
    allowed={(str(s.get('source') or s.get('filename') or ''),str(s.get('page') if s.get('page') is not None else 'UNPAGINATED')) for s in sources if isinstance(s,dict)}
    citations={(m.group(1).strip(),m.group(2).upper()) for m in MARKER.finditer(answer)}
    issues=[]
    if citations-allowed:issues.append('Citation outside retrieved sources')
    # Document identifiers contain digits but are not engineering quantities.
    # Exclude only exact filenames from the accessible retrieved source set;
    # numeric claims elsewhere still require their source/page citations.
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
    numeric=numbers(numeric_text)
    if numeric and not citations:issues.append('Numeric answer lacks exact source/page citations')
    supported=set()
    for key in citations:
        supported.update(numbers(excerpts.get(key,'')))
    if numeric-supported:issues.append('Numeric values absent from cited page excerpts')
    cited_text='\n'.join(excerpts.get(key,'') for key in citations)
    if re.search(r'(?<!not )(?<!un)\bapproved\b',numeric_text,re.I):
        from intelligence.source_semantics import explicit_states
        conditional=bool(re.search(r'\bapproved\s+with\s+comments\b',numeric_text,re.I))
        required='APPROVED_WITH_COMMENTS' if conditional else 'APPROVED'
        if explicit_states(cited_text)!={required}:
            issues.append('Approval assertion lacks explicit matching source authority')
    if quantity_pairs(numeric_text)-quantity_pairs(cited_text):
        issues.append('Value/unit pair absent from cited page excerpts')
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
    """Allow one bounded correction; every candidate passes the same checks."""
    published,issues=guarded_answer(answer,evidence,sources)
    if not issues:
        return published,[]
    try:
        candidate=repair(issues)
        if not isinstance(candidate,str) or not candidate.strip():
            return published,issues
        return guarded_answer(candidate,evidence,sources)
    except Exception:
        return published,issues
