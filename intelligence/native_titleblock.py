"""Read an explicitly labelled native PDF title field without LLM synthesis."""
import hashlib
import json
import re
from pathlib import Path


def native_title_answer(question, documents):
    if not re.search(r'\b(?:drawing title|title.*level.*zone)\b', question, re.I):
        return None
    if re.search(r'\b(project title|approved|latest|current|revision)\b', question, re.I):
        return None
    import fitz
    facts = []
    requested = {int(n) for n in re.findall(r'\bpage\s+(\d+)\b', question, re.I)}
    for doc in documents:
        if not doc['path'].lower().endswith('.pdf'):
            continue
        try:
            meta = json.loads(Path(doc['path'] + '.index.json').read_text(encoding='utf-8'))
            if meta.get('truncated') or meta.get('processing_complete') is False:
                continue
            with open(doc['path'], 'rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != meta.get('source_sha256'):
                    continue
            with fitz.open(doc['path']) as pdf:
                for index, page in enumerate(pdf):
                    if requested and index + 1 not in requested:
                        continue
                    blocks = page.get_text('blocks')
                    anchors = [b for b in blocks if b[4].strip().lower() == 'drawing title']
                    if len(anchors) != 1:
                        continue
                    anchor = anchors[0]
                    stops = [b[1] for b in blocks if abs(b[0] - anchor[0]) < 10 and b[1] > anchor[3]
                             and re.fullmatch(r'(?:Approved|Designed|Drawn|Checked|Drawing No|Scale(?: @.*)?|Revision No)', b[4].strip(), re.I)]
                    if not stops:
                        continue
                    bottom = min(stops)
                    if bottom - anchor[3] > 200:
                        continue
                    values = sorted([b for b in blocks if abs(b[0] - anchor[0]) < 10
                                     and b[1] >= anchor[3] and b[3] <= bottom], key=lambda b: (b[1], b[0]))
                    title = ' '.join(' '.join(b[4].split()) for b in values)
                    if title:
                        facts.append((doc['filename'], index + 1, title))
        except (OSError, ValueError, KeyError, RuntimeError):
            continue
    if not facts or len({f[2] for f in facts}) != 1:
        return None
    citations = '\n'.join(f'[SOURCE: {f[0]} | PAGE {f[1]}]' for f in dict.fromkeys(facts))
    return {'status': 'SUCCESS', 'answer': '**Drawing title:** ' + facts[0][2] + '\n\n' + citations,
            'sources': [{'source': f[0], 'page': f[1]} for f in dict.fromkeys(facts)]}
