"""Keep geometry-derived table rows joined to header, title and entity context."""
import re


def table_row_units(markdown):
    title = ''
    header = []
    entity = ''
    output = []
    for line in markdown.splitlines():
        line = line.strip()
        if not line:
            title = ''
            header = []
            entity = ''
            continue
        if not line.startswith('|'):
            title = line
            header = []
            entity = ''
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        filled = [c for c in cells if c]
        if all(not c or re.fullmatch(r':?-+:?', c) for c in cells):
            continue
        for cell in cells:
            match = re.fullmatch(r'TOWER\s*\d+',cell,re.I)
            if match:
                entity = match.group(0)
        if len(filled)==1 and not re.search(r'\d|determined|confirmed',filled[0],re.I):
            title = filled[0]
            if re.fullmatch(r'TOTAL UNITS',filled[0],re.I):
                header = cells
            elif not filled[0].endswith(':') and not re.fullmatch(r'TOTAL PARKING BAYS REQUIRED',filled[0],re.I):
                header = []
            continue
        if cells and re.fullmatch(r'(?:Retail|F&B) Units:',cells[0],re.I):
            title = cells[0]
        if any(re.fullmatch(r'(?:LEVEL|ITEM|DESCRIPTION|REQUIRED|PROPOSED|NO\.|SQ\.M\.|SQ\.FT\.)',c,re.I)
               or re.search(r'\bFloor GFA\b',c,re.I) for c in cells):
            if any(re.search(r'\bFloor GFA\b',c,re.I) for c in cells):
                header = cells
                continue
            # Multirow headers are combined so units and parent labels survive.
            header = [(f'{header[i]} / {c}' if i<len(header) and header[i] and c and header[i]!=c
                       else c or (header[i] if i<len(header) else '')) for i,c in enumerate(cells)]
            continue
        if not header:
            header = cells
            continue
        if not any(re.search(r'\d|determined|confirmed',c,re.I) for c in cells):
            if any('TOTAL UNITS' in c.upper() or 'STANDARD BAYS' in c.upper() for c in cells):
                header = cells
            continue
        values = '; '.join(f'{header[i] if i<len(header) and header[i] else "Column "+str(i+1)}: {c}'
                           for i,c in enumerate(cells) if c)
        output.append(f'[TABLE ROW]\nTable: {title}\nEntity: {entity}\n{values}')
    return output
