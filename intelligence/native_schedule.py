"""Exact native-text schedule rows; no guessed geometry, units or values."""
import hashlib
import json
import re
from pathlib import Path


def native_schedule_answer(question, documents):
    # The viewer prefixes its question with the focused filename. Project and
    # drawing identifiers in that filename are source selectors, not row tags.
    for doc in documents:
        question = re.sub(re.escape(doc['filename']), '', question, flags=re.I)
    tags = set(re.findall(r'\b[A-Za-z]{1,5}\d{2,5}\b', question.upper()))
    if len(tags) != 1 or not all(word in question.lower() for word in ('width', 'length', 'depth')):
        return None
    if re.search(r'\b(compare|difference|sum|calculate|approved|latest|current)\b', question, re.I):
        return None
    tag = next(iter(tags))
    requested_pages = {int(p) for p in re.findall(r'\bpage\s+(\d+)\b', question, re.I)}
    facts = []
    for doc in documents:
        try:
            meta = json.loads(Path(doc['path'] + '.index.json').read_text(encoding='utf-8'))
            if meta.get('truncated') or meta.get('processing_complete') is False:
                continue
            # An exact shortcut requires current source identity.
            with open(doc['path'], 'rb') as source:
                if hashlib.file_digest(source, 'sha256').hexdigest() != meta.get('source_sha256'):
                    continue
        except (OSError, ValueError, KeyError):
            continue
        for page in meta.get('pages', []):
            if requested_pages and page['page'] not in requested_pages:
                continue
            text = page.get('text', '')
            if not re.search(r'ALL DIMENSIONS ARE IN MILLIMETERS', text, re.I):
                continue
            # Bounded contiguous header + rows only. Presence of a number
            # somewhere else on the page cannot establish a relationship.
            pattern = r'(?im)^TYPE\s*\nWIDTH\s*\nLENGTH\s*\nDEPTH\s*\n((?:[A-Z]{1,5}\d{2,5}\s*\n\d+(?:\.\d+)?\s*\n\d+(?:\.\d+)?\s*\n\d+(?:\.\d+)?\s*\n?)+)'
            for table in re.findall(pattern, text):
                rows = re.findall(r'([A-Z]{1,5}\d{2,5})\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)', table, re.I)
                for row in rows:
                    if row[0].upper() == tag:
                        facts.append((doc['filename'], page['page'], row[1:]))
    if not facts or len({f[2] for f in facts}) != 1:
        return None
    lines = [f'**{tag} — schedule dimensions**',
             *[f'- **{label}:** {value} mm' for label, value in zip(('Width', 'Length', 'Depth'), facts[0][2])],
             '\nDrawing dimensions are in mm unless noted otherwise. These are schedule values; construction approval is not established.']
    sources = []
    for filename, page, _ in dict.fromkeys(facts):
        lines.append(f'[SOURCE: {filename} | PAGE {page}]')
        sources.append({'source': filename, 'page': page})
    return {'status': 'SUCCESS', 'answer': '\n'.join(lines), 'sources': sources}
