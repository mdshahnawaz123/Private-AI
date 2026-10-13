"""Source quotations for arbitrary processed PDFs, with no filename rules.

The caller must provide permission-filtered documents. This reader does not
replace OCR review, general retrieval, or the final publication validator.
"""
import hashlib
import json
import re
from pathlib import Path


def native_pdf_answer(question, documents, budget=32000):
    from intelligence.claim_support import _source_stages
    from intelligence.source_excerpt import source_excerpt

    # Quoting a field cannot establish authority, perform arithmetic, or answer
    # a request for an exhaustive cross-document summary.
    if re.search(r"\b(?:approved|approval|current|latest|revision|calculate|sum|average|difference|convert|compare|all|every|summari[sz]e)\b", question, re.I):
        return None
    requested = {int(n) for n in re.findall(r"\bpage\s+(\d+)\b", question, re.I)}
    stage_question = bool(re.search(r"\b(?:design\s+stage|project\s+stage)\b", question, re.I))
    parts, sources, stages = [], [], []
    used = 0
    for doc in documents:
        if doc.get('status', 'ready') not in {'ready', 'ready_with_warnings', 'verified', 'published'}:
            continue
        path = Path(str(doc.get('path') or ''))
        if path.suffix.lower() != '.pdf':
            continue
        try:
            meta = json.loads(Path(str(path) + '.index.json').read_text(encoding='utf-8'))
            if meta.get('processing_complete') is not True or meta.get('truncated') or not meta.get('source_sha256'):
                continue
            with path.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            if digest != meta['source_sha256']:
                continue
            for page in meta.get('pages', []):
                number = page.get('page')
                if not isinstance(number, int) or number < 1 or (requested and number not in requested):
                    continue
                # Only native text and geometric tables are eligible here.
                # OCR/vision observations never become native evidence.
                stage_values = _source_stages(str(page.get('text') or '')) if stage_question else set()
                if stage_question and not stage_values:
                    continue
                fields = ('text',) if stage_question else ('tables', 'text')
                native = '\n\n'.join(str(page.get(field) or '') for field in fields)
                if not native.strip():
                    continue
                if re.search(r'REVIEW_REQUIRED|UNVERIFIED', native):
                    continue
                source = {'source': doc['filename'], 'page': number}
                block = f"[SOURCE: {source['source']} | PAGE {number}]\n{native}"
                used += len(block)
                if used > budget:
                    # Never silently select a subset and call it unambiguous.
                    # The existing bounded hybrid retriever handles this case.
                    return None
                parts.append(block)
                sources.append(source)
                if stage_question:
                    stages.extend((value, source) for value in stage_values)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    if not parts:
        return None
    if stage_question:
        values = {value for value, _ in stages}
        if len(values) != 1:
            return None
        value = next(iter(values))
        stage_sources = list({(s['source'], s['page']): s for _, s in stages}.values())
        citations = ' '.join(f"[SOURCE: {s['source']} | PAGE {s['page']}]" for s in stage_sources)
        # Case folding is only formatting; the final guard verifies this label
        # and complete value against the actual source, including qualifiers.
        answer = f"Design stage: {value} {citations}"
        return {'status': 'SUCCESS', 'answer': answer, 'sources': stage_sources,
                'method': 'NATIVE_SOURCE_FIELD'}
    answer = source_excerpt(question, '\n\n====\n\n'.join(parts), sources)
    if not answer:
        return None
    # Only return citations actually used by the quotation, not every searched
    # page. The route rebuilds their current source context before publication.
    from intelligence.answer_guard import MARKER
    cited = {(match.group(1).strip(), match.group(2)) for match in MARKER.finditer(answer)}
    selected = [s for s in sources if (s['source'], str(s['page'])) in cited]
    return {'status': 'SUCCESS', 'answer': answer, 'sources': selected,
            'method': 'NATIVE_SOURCE_QUOTATION'} if selected else None
