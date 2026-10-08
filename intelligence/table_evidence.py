"""Keep geometry-derived table rows joined to header, title and entity context."""
import re


# answer_guard.quantity_pairs() only recognizes a unit that is wrapped in
# parentheses immediately before its value ("Floor GFA (sqm): 34,950"), which
# is how most of this app's source tables spell a unit header. Some documents
# instead give the unit its own bare column header with no parentheses at all
# (e.g. "SQ.M." / "SQ.FT." as literal column text). Left as-is, a value under
# such a header is correctly paired with its label here but still invisible to
# quantity_pairs(), so a numerically-correct, correctly-cited answer still
# gets withheld as unverifiable. Wrap a label in parentheses when it is itself
# nothing but a recognized unit, so the emitted row matches the convention
# quantity_pairs() already expects.
_BARE_UNIT_RE = re.compile(
    r'^(?:kN/m2|kN/m²|N/mm2|N/mm²|square\s*metres|square\s*meters|square\s*feet|'
    r'sq\.?\s*ft\.?|sq\.?\s*m\.?|sqm|sqft|MPa|kPa|bar|mm|cm|m²|m2|%)$',
    re.I,
)


def _label_value(label, value):
    clean = label.rstrip('.').strip()
    if clean and _BARE_UNIT_RE.match(clean):
        return f'({clean}): {value}'
    return f'{label}: {value}'


def table_row_units(markdown):
    title = ''
    header = []
    col_titles = []
    entity = ''
    output = []

    def is_textual(c):
        return not re.search(r'\d|determined|confirmed', c, re.I)

    def forward_fill_titles(cells):
        out = [''] * len(cells)
        current = ''
        for i, c in enumerate(cells):
            if c:
                current = c
            out[i] = current
        return out

    def emit_row(cells):
        groups = {}
        order = []
        for i, c in enumerate(cells):
            if not c:
                continue
            label = header[i] if i < len(header) and header[i] else f'Column {i + 1}'
            grp_title = col_titles[i] if i < len(col_titles) and col_titles[i] else title
            if grp_title not in groups:
                groups[grp_title] = []
                order.append(grp_title)
            groups[grp_title].append(_label_value(label, c))
        for gt in order:
            values = '; '.join(groups[gt])
            output.append(f'[TABLE ROW]\nTable: {gt}\nEntity: {entity}\n{values}')

    for line in markdown.splitlines():
        line = line.strip()
        if not line:
            title = ''
            header = []
            col_titles = []
            entity = ''
            continue
        if not line.startswith('|'):
            title = line
            header = []
            col_titles = []
            entity = ''
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        filled = [c for c in cells if c]
        if all(not c or re.fullmatch(r':?-+:?', c) for c in cells):
            continue
        for cell in cells:
            match = re.fullmatch(r'TOWER\s*\d+', cell, re.I)
            if match:
                entity = match.group(0)

        if len(filled) == 1 and is_textual(filled[0]):
            title = filled[0]
            col_titles = []
            if re.fullmatch(r'TOTAL UNITS', filled[0], re.I):
                header = cells
            elif not filled[0].endswith(':') and not re.fullmatch(r'TOTAL PARKING BAYS REQUIRED', filled[0], re.I):
                header = []
            continue

        if cells and re.fullmatch(r'(?:Retail|F&B) Units:', cells[0], re.I):
            title = cells[0]

        header_pattern_hit = any(
            re.fullmatch(r'(?:LEVEL|ITEM|DESCRIPTION|REQUIRED|PROPOSED|NO\.|SQ\.M\.|SQ\.FT\.)', c, re.I)
            or re.search(r'\bFloor GFA\b', c, re.I) for c in cells
        )

        # Two or more side-by-side tables can land in one wide markdown row
        # (e.g. "AREA STATEMENT SUMMARY" next to "BUILT-UP AREA BREAKDOWN
        # (Per Level)"). Record which title owns which column so later rows
        # in this block are split back into their own per-section table
        # instead of being merged into a single, mislabeled row.
        if len(filled) >= 2 and all(is_textual(c) for c in filled) and not header_pattern_hit:
            col_titles = forward_fill_titles(cells)
            header = []
            continue

        if header_pattern_hit:
            if any(re.search(r'\bFloor GFA\b', c, re.I) for c in cells):
                header = cells
                continue
            # Multirow headers are combined so units and parent labels survive.
            header = [(f'{header[i]} / {c}' if i < len(header) and header[i] and c and header[i] != c
                       else c or (header[i] if i < len(header) else '')) for i, c in enumerate(cells)]
            continue

        # A self-contained "Label: | | Value" row (exactly one cell ending in
        # ':' plus at least one other filled cell) is a standalone data row,
        # not a header template -- even when no header has been seen yet in
        # this block. Emit it directly from its own cells so it never gets
        # wrongly adopted as `header` and cross-applied to the next rows
        # (the bug: "Date:" became the header, so "Document Revision No.:"
        # read its own label/value against "Date:"'s label/value instead of
        # its own). Only short-circuits when header is still empty, so
        # genuine multi-column rows under an already-established header
        # (e.g. Floor GFA rows with SQ.M./SQ.FT. columns) are unaffected.
        if not header:
            label_cells = [c for c in filled if c.endswith(':')]
            if len(label_cells) == 1 and len(filled) >= 2:
                label = label_cells[0]
                values = [c for c in filled if c != label]
                grp_title = title
                if col_titles:
                    idx = cells.index(label)
                    grp_title = col_titles[idx] if idx < len(col_titles) and col_titles[idx] else title
                output.append(f'[TABLE ROW]\nTable: {grp_title}\nEntity: {entity}\n{label} {"; ".join(values)}')
                continue

        if not header:
            header = cells
            continue

        if not any(re.search(r'\d|determined|confirmed', c, re.I) for c in cells):
            if any('TOTAL UNITS' in c.upper() or 'STANDARD BAYS' in c.upper() for c in cells):
                header = cells
            continue

        if col_titles:
            emit_row(cells)
        else:
            values = '; '.join(
                _label_value(header[i] if i < len(header) and header[i] else f'Column {i + 1}', c)
                for i, c in enumerate(cells) if c
            )
            output.append(f'[TABLE ROW]\nTable: {title}\nEntity: {entity}\n{values}')

    return output
