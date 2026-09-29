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
        vis = ""
        want_vision = bool(deep and vision_fn and render_dir) and (not smart or len(text) < min_chars)
        if want_vision:
            try:
                png = os.path.join(render_dir, "p%04d.png" % (i + 1))
                render_pdf_page(page, png)
                vis = (vision_fn(png) or "").strip()
                if vis:
                    vision_pages += 1
            except Exception:
                vis = ""
                vision_errors += 1
        pages.append({"page": i + 1, "text": text, "vision": vis,
                      "vision_used": bool(vis)})
        block = "[PAGE %d]\n%s" % (i + 1, text)
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
