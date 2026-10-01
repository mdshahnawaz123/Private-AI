"""
Deep document extraction -> combined text (for indexing) + structured JSON.

PDF : per page, embedded text (PyMuPDF) PLUS the page rendered to an image and
      read by the local vision model. Captures scanned/vector drawing sheets.
XLSX: sheets and rows.  DOCX: paragraphs and tables.
The structured dict is saved as <file>.index.json for fast reuse / inspection.
Heavy libs (fitz, openpyxl, docx) are imported lazily so this module always imports.
"""
import os
import json

def render_pdf_page(page, out_path, zoom=2.0):
    import fitz
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    pix.save(out_path)
    return out_path


def render_page_tiles(page, out_dir, page_no, zoom=3.0, max_dim=1500, overlap=0.08):
    """Render a page at high resolution, then split it into tiles no larger than
    max_dim on a side (with slight overlap). Giant dense sheets exceed the vision
    model's max input resolution; tiling keeps small text legible. Returns a list
    of tile image paths. Falls back to a single full render if PIL is unavailable
    or the page is already small enough."""
    import fitz, os, math
    os.makedirs(out_dir, exist_ok=True)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    full = os.path.join(out_dir, "p%04d_full.png" % page_no)
    pix.save(full)
    try:
        from PIL import Image
        im = Image.open(full); W, H = im.size
        cols = max(1, math.ceil(W / float(max_dim)))
        rows = max(1, math.ceil(H / float(max_dim)))
        if cols == 1 and rows == 1:
            return [full]
        tw = W / cols; th = H / rows
        ox = tw * overlap; oy = th * overlap
        paths = []
        for r in range(rows):
            for c in range(cols):
                l = max(0, int(c * tw - ox)); t = max(0, int(r * th - oy))
                rr = min(W, int((c + 1) * tw + ox)); bb = min(H, int((r + 1) * th + oy))
                crop = im.crop((l, t, rr, bb))
                tp = os.path.join(out_dir, "p%04d_r%dc%d.png" % (page_no, r, c))
                crop.save(tp); paths.append(tp)
        return paths
    except Exception:
        return [full]

def _md_table(rows):
    rows = [[("" if c is None else str(c)).replace("\n", " ").replace("|", "/").strip() for c in r] for r in rows]
    rows = [r for r in rows if any(x for x in r)]
    if len(rows) < 2:
        return ""
    ncol = max(len(r) for r in rows)
    rows = [(r + [""] * ncol)[:ncol] for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * ncol) + " |"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def extract_tables_geometry(page):
    """Fast, CPU-only table extraction from the PDF's own text-layer geometry.
    Uses PyMuPDF's built-in table finder (v1.23+). For each table, grabs the
    heading text just above it so tables with identical column headers (e.g. the
    several '... AREA BREAKDOWN' tables) stay distinguishable. Returns a Markdown
    string (title + pipe table per table), or '' if none / unsupported."""
    import fitz
    blocks = []
    try:
        finders = []
        try:
            finders.append(page.find_tables())
        except TypeError:
            finders.append(page.find_tables(strategy="lines"))
        # also try a text-based pass to catch borderless tables
        try:
            finders.append(page.find_tables(strategy="text"))
        except Exception:
            pass
        seen_bbox = []
        for finder in finders:
            for t in (getattr(finder, "tables", None) or []):
                try:
                    bbox = tuple(round(v, 1) for v in t.bbox)
                except Exception:
                    bbox = None
                if bbox and any(abs(bbox[0]-b[0]) < 3 and abs(bbox[1]-b[1]) < 3 for b in seen_bbox):
                    continue
                if bbox:
                    seen_bbox.append(bbox)
                try:
                    md = _md_table(t.extract())
                except Exception:
                    md = ""
                if not md:
                    continue
                title = ""
                try:
                    if bbox:
                        band = fitz.Rect(bbox[0] - 2, max(0, bbox[1] - 38), bbox[2] + 2, bbox[1] - 1)
                        title = " ".join(page.get_textbox(band).split())[:70]
                except Exception:
                    title = ""
                blocks.append((title + "\n" + md) if title else md)
    except Exception:
        return ""
    return "\n\n".join(blocks)


def extract_pdf(path, vision_fn=None, render_dir=None, deep=True, smart=True,
                min_chars=40, max_pages=1000, progress_cb=None):
    """Return (combined_text, meta).

    Text layer is always read (fast, no model). Vision runs per page only when
    it can add something:
      * smart=True (default): vision ONLY on image-only pages (text shorter than
        min_chars) -- e.g. renderings and drawing sheets. Text-rich report pages
        are indexed from their text layer alone. This keeps large reports fast
        and avoids hammering the local model server.
      * smart=False: vision on every page (legacy behaviour).
    Every vision call is isolated: a failure records an error for that page and
    processing continues -- one bad page never loses the whole document."""
    import fitz
    doc = fitz.open(path)
    total = doc.page_count
    if render_dir:
        os.makedirs(render_dir, exist_ok=True)
    pages, parts = [], []
    n = min(total, max_pages)
    vision_pages, vision_errors = 0, 0
    for i in range(n):
        page = doc[i]
        try:
            text = page.get_text("text").strip()
        except Exception:
            text = ""
        try:
            geo = extract_tables_geometry(page)
        except Exception:
            geo = ""
        vis = ""
        # Vision only when the page has (almost) no text layer — a scan/rendering.
        # Text-layer pages are handled fast & accurately by geometry tables above.
        want_vision = bool(deep and vision_fn and render_dir) and (not smart or len(text) < min_chars)
        if want_vision:
            try:
                import os as _os
                _tile_dim = int(_os.getenv("EXPO_VISION_TILE_DIM", "1500"))
                tiles = render_page_tiles(page, render_dir, i + 1, zoom=3.0, max_dim=_tile_dim)
                _parts = []
                for _ti, _tp in enumerate(tiles):
                    _vt = (vision_fn(_tp) or "").strip()
                    if _vt:
                        _parts.append(("[REGION %d/%d]\n%s" % (_ti + 1, len(tiles), _vt)) if len(tiles) > 1 else _vt)
                vis = "\n\n".join(_parts).strip()
                if vis:
                    vision_pages += 1
            except Exception:
                vis = ""
                vision_errors += 1
        pages.append({"page": i + 1, "text": text, "tables": geo, "vision": vis,
                      "vision_used": bool(vis)})
        block = "[PAGE %d]\n%s" % (i + 1, text)
        if geo:
            block += "\n\n[TABLES]\n" + geo
        if vis:
            block += "\n[DRAWING/VISION]\n" + vis
        parts.append(block)
        if progress_cb:
            try:
                progress_cb(i + 1, n)
            except Exception:
                pass
    doc.close()
    meta = {"type": "pdf", "page_count": n, "total_pages": total,
            "truncated": total > n, "smart": smart,
            "vision_pages": vision_pages, "vision_errors": vision_errors,
            "pages": pages}
    return "\n\n".join(parts), meta

def extract_excel(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheets, parts = [], []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if any(cells):
                rows.append(cells)
        sheets.append({"sheet": ws.title, "rows": rows})
        parts.append("[SHEET %s]\n%s" % (ws.title, "\n".join(" | ".join(r) for r in rows)))
    try:
        wb.close()
    except Exception:
        pass
    return "\n\n".join(parts), {"type": "excel", "sheets": sheets}

def extract_docx(path):
    import docx
    d = docx.Document(path)
    paras = [p.text for p in d.paragraphs if p.text and p.text.strip()]
    tables = []
    for t in d.tables:
        tables.append([[c.text for c in row.cells] for row in t.rows])
    parts = ["\n".join(paras)]
    for tbl in tables:
        parts.append("\n".join(" | ".join(r) for r in tbl))
    return "\n\n".join(parts), {"type": "docx", "paragraphs": paras, "tables": tables}

def save_json(sidecar_path, meta):
    try:
        with open(sidecar_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        return True
    except Exception:
        return False
