"""Select source pages without inventing page-one attribution or silent truncation."""
import json
import re


def _extract_drawing_structures(text):
    """Native text order alone cannot prove drawing geometry or selected stamps.

    Keep the original page evidence for guarded retrieval. Do not synthesize
    dimensions, relationships, sign-offs or dispositions from token presence.
    """
    return ''


def select_page_context(path, filename, query, budget=32000, max_chars_per_page=None):
    terms = set(re.findall(r'\w+', query.lower())) - {'the','a','an','is','what','of','and','in','to','for'}
    try:
        with open(path + '.index.json', encoding='utf-8') as handle:
            meta = json.load(handle)
        pages=[]
        for entry in meta.get('pages',[]):
            # Order matters once a page's content exceeds max_chars_per_page and
            # gets truncated below: put the MOST verifiable evidence first so it
            # survives, and the least reliable last so it's what gets cut.
            #   1. table_row_units() rows -- table_evidence.py's flattened
            #      "Entity: X ... Label (unit): value" strings. Compact and
            #      directly matchable by answer_guard.quantity_pairs(). A dense
            #      multi-table page (e.g. a per-level area schedule covering
            #      several towers) can produce dozens of these rows -- far more
            #      than max_chars_per_page alone -- so within this tier the rows
            #      are ranked by how many query terms their own text contains
            #      (an "Entity: TOWER 2" row sorts ahead of TOWER 1/3 rows for a
            #      "Tower 2" query) rather than kept in document order, so the
            #      truncation below cuts irrelevant rows, not the one the query
            #      actually needs.
            #   2. the raw markdown `tables` field -- still structured (pipe
            #      tables), human/model-readable, but header/value cells sit in
            #      different rows so quantity_pairs() can't pair them directly.
            #   3. the raw PyMuPDF `text` field -- on a dense multi-table page
            #      this is column-by-column reading-order text with headers and
            #      values from DIFFERENT columns interleaved; it can be large
            #      (observed 5200+ chars on an 8-table schedule page) and is the
            #      least reliable for exact figures, so it goes last. Before this
            #      reordering, `text` (jumbled, highest volume) came FIRST, so it
            #      alone could consume the entire max_chars_per_page cap and
            #      silently push the clean `tables` markdown and the even-cleaner
            #      table_row_units() rows out of the excerpt entirely -- on
            #      exactly the dense pages where verification needed them most
            #      (reproduced: page 4 of the C3085 area schedule, text field
            #      alone = 5200 chars, already over the 4000 cap, with the
            #      correct "Floor GFA (sqm): 34,950" TOWER 2 row 22000+ chars
            #      further into the string and therefore always truncated away).
            tbl=str(entry.get('tables') or '')
            rows_text=''
            if tbl:
                try:
                    from intelligence.table_evidence import table_row_units
                    rows=table_row_units(tbl)
                    if rows:
                        # Generic term overlap alone is not discriminating enough
                        # here: a query for "Tower 2" shares 'tower' and 'total'
                        # with every tower's own TOTAL row (table_row_units()
                        # labels the summary row "LEVEL: TOTAL"), so plain term
                        # counting put Tower 1's row ahead of Tower 2's. Pull out
                        # an explicit entity reference ("tower 2", "building 3",
                        # ...) from the query and score a row's own "Entity: X"
                        # line against it directly; a query asking for a "TOTAL"
                        # value is also boosted toward rows whose own LEVEL field
                        # is the summary row, not a per-level breakdown row.
                        entity_match=re.search(r'\b(tower|building|block)\s*0*(\d+)\b',query,re.I)
                        wants_total='total' in terms
                        def _score(row):
                            row_lower=row.lower()
                            s=sum(1 for t in terms if t in row_lower)
                            if entity_match:
                                phrase=f'entity: {entity_match.group(1).lower()} {entity_match.group(2)}'
                                if phrase in row_lower:
                                    s+=1000
                                elif re.search(r'entity:\s*(tower|building|block)\s*0*\d+',row_lower):
                                    s-=1000
                            if wants_total and re.search(r'level:\s*total\b',row_lower):
                                s+=100
                            return s
                        rows=sorted(rows,key=_score,reverse=True)
                        rows_text='\n'.join(rows)
                except Exception:
                    pass
            raw_text=str(entry.get('text') or '')
            structured_drawing=_extract_drawing_structures(raw_text)
            native_parts = [p for p in (structured_drawing, rows_text, tbl, raw_text) if p]
            native='\n\n'.join(native_parts)
            observation='\n'.join(str(entry.get(key) or '') for key in ('vision','inspection_text')).strip()
            if observation:native+='\n[UNVERIFIED EXTRACTION; REVIEW_REQUIRED]\n'+observation
            pages.append((entry['page'],native))
    except (OSError, ValueError, KeyError):
        pages = []
    if not pages:
        with open(path + '.extracted.txt', encoding='utf-8') as handle:
            raw = handle.read()
        parts = re.split(r'\[PAGE (\d+)\]', raw)
        pages = [(int(parts[i]), parts[i+1]) for i in range(1,len(parts)-1,2)]
        if not pages:
            pages = [(None, raw)]
    requested = {int(n) for n in re.findall(r'\bpage\s+(\d+)\b',query,re.I)}
    if requested:
        pages = [(page,text) for page,text in pages if page in requested]
    ranked = sorted(pages, key=lambda item:(item[0] in requested, sum(min(5,len(re.findall(r'\b'+re.escape(t)+r'\b',item[1].lower()))) for t in terms)), reverse=True)
    blocks, sources, used = [], [], 0
    single_page_doc = len(pages) <= 1
    effective_cap = None if (max_chars_per_page is None or max_chars_per_page <= 0 or single_page_doc) else max_chars_per_page
    for page, text in ranked:
        if not text.strip():
            continue
        room = budget - used
        if room <= 200:
            break
        page_room = min(room, effective_cap) if effective_cap is not None else room
        clipped = len(text) > page_room
        label = str(page) if page is not None else 'UNPAGINATED'
        block = f'[SOURCE: {filename} | PAGE {label}]\n{text[:page_room]}'
        if clipped:
            block += '\n[EXCERPT ENDS; REST OF THIS PAGE NOT INCLUDED]'
        blocks.append(block)
        sources.append({'source':filename,'page':page})
        used += len(block)
    return sources, '\n\n====\n\n'.join(blocks)
