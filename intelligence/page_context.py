"""Select source pages without inventing page-one attribution or silent truncation."""
import json
import re


def select_page_context(path, filename, query, budget=16000):
    try:
        with open(path + '.index.json', encoding='utf-8') as handle:
            meta = json.load(handle)
        pages=[]
        for entry in meta.get('pages',[]):
            native='\n'.join(str(entry.get(key) or '') for key in ('text','tables'))
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
    terms = set(re.findall(r'\w+', query.lower())) - {'the','a','an','is','what','of','and','in','to','for'}
    requested = {int(n) for n in re.findall(r'\bpage\s+(\d+)\b',query,re.I)}
    if requested:
        pages = [(page,text) for page,text in pages if page in requested]
    ranked = sorted(pages, key=lambda item:(item[0] in requested, sum(min(5,len(re.findall(r'\b'+re.escape(t)+r'\b',item[1].lower()))) for t in terms)), reverse=True)
    blocks, sources, used = [], [], 0
    for page, text in ranked:
        if not text.strip():
            continue
        room = budget - used
        if room <= 200:
            break
        clipped = len(text) > room
        label = str(page) if page is not None else 'UNPAGINATED'
        block = f'[SOURCE: {filename} | PAGE {label}]\n{text[:room]}'
        if clipped:
            block += '\n[EXCERPT ENDS; REST OF THIS PAGE NOT INCLUDED]'
        blocks.append(block)
        sources.append({'source':filename,'page':page})
        used += len(block)
    return sources, '\n\n====\n\n'.join(blocks)
