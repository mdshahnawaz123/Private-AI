"""Cell-by-cell OCR of ruled tables on pages without a usable text layer.

Full-page OCR (EasyOCR) misses short isolated values in table cells ("65",
"75", "50") and merges neighbouring cells, so table questions were answered
wrongly or withheld (2026-10-14 pipeline audit: Table 6 lost every Rw value,
Table 5 merged "Gymnasium Retail Pool"). PyMuPDF still finds the table GRID
from the drawn ruling lines even when the font encoding is broken, so each
cell is cropped (inside its borders), upscaled and OCR'd on its own, then the
grid is rebuilt in reading orientation. Results are cached per source hash.
"""
import json
import os
import subprocess
import sys

CACHE_VERSION = "tables-v1"


def _reading_grid(cells, rotation):
    """cells: [(ri, ci, rect, text)] in PDF space -> rows of text in reading order."""
    import fitz
    matrix = fitz.Matrix(1, 1).prerotate(rotation)
    swap = rotation in (90, 270)
    rows, cols = {}, {}
    for ri, ci, rect, _ in cells:
        center = fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2) * matrix
        rk, ck = (ci, ri) if swap else (ri, ci)
        rows.setdefault(rk, []).append(center.y)
        cols.setdefault(ck, []).append(center.x)
    row_order = sorted(rows, key=lambda k: sum(rows[k]) / len(rows[k]))
    col_order = sorted(cols, key=lambda k: sum(cols[k]) / len(cols[k]))
    rpos = {k: i for i, k in enumerate(row_order)}
    cpos = {k: i for i, k in enumerate(col_order)}
    grid = [[""] * len(col_order) for _ in row_order]
    for ri, ci, _, text in cells:
        rk, ck = (ci, ri) if swap else (ri, ci)
        grid[rpos[rk]][cpos[ck]] = text
    return grid


def _to_markdown(grid, caption):
    lines = [caption] if caption else []
    for i, row in enumerate(grid):
        lines.append("| " + " | ".join(c.replace("|", "/").strip() for c in row) + " |")
        if i == 0:
            lines.append("|" + "---|" * len(row))
    return "\n".join(lines)


_UNIT_RE = None


def _with_unit(value, header):
    """'75' under header 'For Specification Rw dB' -> '75 dB', so the value
    carries its unit like it would in running text (answers say "75 dB" and
    are checked against the source span). Only bare numbers/ranges get it."""
    import re
    global _UNIT_RE
    if _UNIT_RE is None:
        _UNIT_RE = re.compile(r"(?:\(|\b)(dB\(A\)|dBA|dB|mm|cm|kg/m2|kg/m3|kg/m²|kg/m³|m/s|m3/s|Hz|kHz|Pa|sec|s|%|m)\)?\s*$")
    if not re.fullmatch(r"[<>≤≥~]?\s*-?\d[\d.,]*(?:\s*[-–]\s*\d[\d.,]*)?(?:\s*\(-?\d[\d.,]*\))?", value):
        return value
    m = _UNIT_RE.search(header.strip())
    return f"{value} {m.group(1)}" if m else value


def _row_units(grid, caption, page):
    """Self-contained row evidence: header label beside every value."""
    if len(grid) < 2:
        return []
    import re
    top = [h.strip() for h in grid[0]]
    body = grid[1:]
    # Two-level header (e.g. "Sound Insulation Requirements, Rw (Ctr)" spanning
    # "Phase 1 Expansion" | "Final Phase Expansion"): a second row with no
    # numbers that fills columns the first row left blank.
    if len(grid) >= 3:
        second = [c.strip() for c in grid[1]]
        def _valueish(c):
            return bool(re.fullmatch(r"[\d\s.,()+\-%/<>=~]+(?:\s*(?:dB|mm|m|kg/m\S*|s|sec|Hz|NR\s*\d+))?", c)
                        or re.search(r"\d\s*(?:dB|mm|kg)", c) or re.match(r"NR\s*\d", c))
        sparse_top = sum(1 for t in top if t) <= len(top) / 2 and sum(1 for c in second if c) >= len(second) - 1
        if sparse_top or (any(second) and not any(_valueish(c) for c in second if c)
                and any(s and not t for s, t in zip(second, top))):
            combined = []
            for i, (t, sub) in enumerate(zip(top, second)):
                if not sub:
                    combined.append(t)
                    continue
                group = t
                if not group and sparse_top:
                    group = next((x for x in top if x), "")
                if not group:
                    for j in (i + 1, i - 1, i + 2, i - 2):
                        if 0 <= j < len(top) and top[j] and j < len(second) and second[j]:
                            group = top[j]
                            break
                combined.append(f"{group} - {sub}" if group and group != sub else sub)
            top, body = combined, grid[2:]
    header = [h or f"Column {i + 1}" for i, h in enumerate(top)]
    units = []
    # Vertically merged label cells (one "Location" spanning three rows) are
    # read once, in the first row; carry text labels down to the rows below
    # them so every row stays self-contained. Numeric cells are never carried.
    prev = None
    filled_body = []
    for row in body:
        row = list(row)
        if prev is not None and sum(1 for c in row if c.strip()) >= 2:
            for i, c in enumerate(row):
                if not c.strip() and i < len(prev) and prev[i].strip() \
                        and len(re.findall(r"[A-Za-z]", prev[i])) > 2 * len(re.findall(r"\d", prev[i])) \
                        and len(prev[i]) < 200:
                    row[i] = prev[i]
        filled_body.append(row)
        prev = row
    body = filled_body
    for row in body:
        filled = [c for c in row if c.strip()]
        if not filled:
            continue
        if len(filled) == 1 and len(filled[0]) > 60:
            units.append(f"[TABLE NOTE]\nTable: {caption or 'table on page %d' % page}\n{filled[0]}")
            continue
        pairs = "; ".join(f"{header[i]}: {_with_unit(c.strip(), header[i])}" for i, c in enumerate(row) if c.strip())
        units.append(f"[TABLE ROW]\nTable: {caption or 'table on page %d' % page}\n{pairs}")
    return units


def page_tables(path, digest, page_number, rotation, captions=(), timeout=240):
    """Return [{'caption','markdown','rows'}] for ruled tables on one page (cached)."""
    import fitz
    cache_dir = path + "_page_ocr"
    os.makedirs(cache_dir, exist_ok=True)
    cache = os.path.join(cache_dir, f"{digest}-{CACHE_VERSION}-r{rotation}-p{page_number}.json")
    if os.path.isfile(cache):
        with open(cache, encoding="utf-8") as handle:
            return json.load(handle)
    work = os.path.join(cache_dir, f"cells-p{page_number}")
    os.makedirs(work, exist_ok=True)
    jobs, layout = [], []
    with fitz.open(path) as document:
        page = document[page_number - 1]
        from services.pdf_text_quality import safe_find_tables
        _ft = safe_find_tables(page)
        tables = _ft.tables if _ft else []
        # Reading order of tables (left column top-to-bottom, then right), so
        # captions found in the OCR text ("Table 5 ...") line up with them.
        matrix = fitz.Matrix(1, 1).prerotate(rotation)
        frame = page.rect * matrix
        def _key(table):
            b = fitz.Rect(table.bbox)
            c = fitz.Point((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2) * matrix
            return (0 if c.x - frame.x0 < frame.width / 2 else 1, c.y)
        tables = sorted(tables, key=_key)
        for ti, table in enumerate(tables):
            entries = []
            for ri, row in enumerate(table.rows):
                for ci, cell in enumerate(row.cells):
                    if cell is None:
                        continue
                    rect = fitz.Rect(cell)
                    inner = fitz.Rect(rect.x0 + 1.5, rect.y0 + 1.5, rect.x1 - 1.5, rect.y1 - 1.5)
                    if inner.is_empty or inner.width < 3 or inner.height < 3:
                        continue
                    image = os.path.join(work, f"t{ti}_r{ri}_c{ci}.png")
                    page.get_pixmap(matrix=fitz.Matrix(4, 4).prerotate(rotation), clip=inner,
                                    alpha=False).save(image)
                    jobs.append(image)
                    entries.append((ri, ci, rect, image))
            # Table position in the full-page OCR image (same render matrix as
            # services.page_ocr) so full-page OCR boxes inside the table can be
            # dropped in favour of the cell-by-cell result.
            zoom = min(2.0, 2000 / max(page.rect.width, page.rect.height))
            ib = fitz.Rect(table.bbox) * fitz.Matrix(zoom, zoom).prerotate(rotation)
            shift = (page.rect * fitz.Matrix(zoom, zoom).prerotate(rotation)).tl
            layout.append((entries, [ib.x0 - shift.x, ib.y0 - shift.y, ib.x1 - shift.x, ib.y1 - shift.y]))
    if not jobs:
        result = []
    else:
        manifest = os.path.join(work, "manifest.json")
        output = os.path.join(work, "texts.json")
        with open(manifest, "w", encoding="utf-8") as handle:
            json.dump(jobs, handle)
        completed = subprocess.run([sys.executable, "-m", "services.table_cells", manifest, output],
                                   timeout=timeout, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError("Table cell OCR failed: " + completed.stderr[-500:])
        with open(output, encoding="utf-8") as handle:
            texts = json.load(handle)
        result = []
        for ti, (entries, image_bbox) in enumerate(layout):
            cells = [(ri, ci, rect, texts.get(image, "")) for ri, ci, rect, image in entries]
            if not cells:
                continue
            grid = _reading_grid(cells, rotation)
            if len(grid) < 2 or max(len(r) for r in grid) < 2:
                continue
            caption = captions[ti] if ti < len(captions) else ""
            result.append({"caption": caption, "markdown": _to_markdown(grid, caption), "image_bbox": image_bbox, "grid": grid,
                           "rows": _row_units(grid, caption, page_number)})
    temporary = cache + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    os.replace(temporary, cache)
    return result


if __name__ == "__main__":
    from engines.ocr_engine import get_ocr_engine
    manifest, output = sys.argv[1:]
    with open(manifest, encoding="utf-8") as handle:
        images = json.load(handle)
    engine = get_ocr_engine()
    texts = {}
    for image in images:
        try:
            texts[image] = " ".join(engine.recognize(image).full_text.split())
        except Exception:
            texts[image] = ""
    with open(output + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(texts, handle)
    os.replace(output + ".tmp", output)
