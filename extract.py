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

def _sanitize_pdf_text(raw: str) -> str:
    """Strip null bytes and non-printable control chars from PDF text.
    
    Some PDFs have broken ToUnicode CMap tables that produce \x00 and other
    control characters in the decoded text stream. These cause:
    - subprocess.run() to crash with "embedded null character" on Windows
    - Garbage data in the FAISS/BM25 search index
    - Broken JSON serialization
    """
    if not raw:
        return ""
    import re
    # Remove null bytes and C0 control chars except \t \n \r
    cleaned = raw.replace('\x00', '')
    # Also strip other C0 controls that indicate garbled decoding
    cleaned = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f]', '', cleaned)
    return cleaned

def render_pdf_page(page, out_path, zoom=2.0):
    import fitz
    from services.pdf_text_quality import page_text_rotation
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom).prerotate(page_text_rotation(page)))
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
    from services.pdf_text_quality import page_text_rotation
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom).prerotate(page_text_rotation(page)))
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
    several '... AREA BREAKDOWN' tables) stay distinguishable. Returns
    (markdown, table_count): a Markdown string (title + pipe table per table,
    '' if none / unsupported) and how many distinct tables were found on the
    page. table_count is also used by extract_pdf as a page-density signal:
    a page packed with many small side-by-side tables (an infographic-style
    "data sheet" rather than a normal report page) is exactly the layout where
    PyMuPDF's own text-reading order scrambles which number sits next to which
    label -- see DENSE_TABLE_VISION_FIX.md for the reproduced case."""
    import fitz
    blocks = []
    try:
        finders = []
        try:
            finders.append(page.find_tables())
        except TypeError:
            finders.append(page.find_tables(strategy="lines"))
        # also try a text-based pass to catch borderless tables
        # The text strategy can merge unrelated side-by-side tables into a huge
        # second grid. Use it only when line geometry found no tables.
        if not any(getattr(f, "tables", None) for f in finders):
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
        return "", 0
    return "\n\n".join(blocks), len(blocks)


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
            from services.pdf_text_quality import native_text_usable
            raw_text = page.get_text("text")
            damaged_native = bool(raw_text.strip()) and not native_text_usable(raw_text, min_chars=1)
            text = "" if damaged_native else _sanitize_pdf_text(raw_text).strip()
        except Exception:
            damaged_native = False
            text = ""
        try:
            geo, table_count = extract_tables_geometry(page)
        except Exception:
            geo, table_count = "", 0
        if damaged_native:
            geo, table_count = "", 0
        vis = ""
        # Vision only when the page has (almost) no text layer — a scan/rendering.
        # detect if page has significant embedded images (e.g. screenshot tables)
        has_large_image = False
        try:
            for img in page.get_images(full=True):
                if img[2] * img[3] > 50000:  # > 50k pixels
                    has_large_image = True
                    break
        except:
            pass

        # A page packed with many small, separate tables (a "project data sheet"
        # / infographic layout with dozens of side-by-side boxes, as opposed to
        # one or two normal tables on a report page) is the case where PyMuPDF's
        # native text-reading order scrambles label/value adjacency -- confirmed
        # on a real document where a value physically next to "FAR Allowed:" in
        # the text stream actually belonged to "FAR Proposed:" two lines down,
        # and a number got silently truncated (110,000.00 -> 10) next to
        # "GFA Allowed:". min_chars-based detection misses this entirely because
        # these pages have PLENTY of text -- just not in a trustworthy order.
        # Checked against real documents: normal report/schedule pages carry at
        # most ~1 table per page; this page alone carried 14. Vision reads the
        # rendered pixels, so it isn't fooled by text-stream ordering.
        is_dense_table_page = table_count >= 5
        want_vision = bool(deep and vision_fn and render_dir) and (
            not smart or len(text) < min_chars or has_large_image or is_dense_table_page)

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
        from services.pdf_inspection import inspect_page, inspection_text
        inspection = inspect_page(page)
        
        # Universal Drawing Engine analysis
        dwg_data = {}
        dwg_evidence = ""
        try:
            from engines.universal_drawing_engine import get_universal_drawing_engine
            dwg_engine = get_universal_drawing_engine()
            dwg_data = dwg_engine.parse_drawing_page(page)
            if dwg_data.get("is_drawing"):
                dwg_data['verification_state'] = 'REVIEW_REQUIRED'
                dwg_evidence = dwg_engine.format_as_evidence_block(dwg_data)
        except Exception:
            dwg_data = {}
            dwg_evidence = ""

        pages.append({"page": i + 1, "text": text, "tables": geo, "vision": vis,
                      "native_text_quality": "DAMAGED" if damaged_native else "AVAILABLE",
                      "inspection":inspection,"inspection_text":inspection_text(inspection),
                      "drawing_schema": dwg_data, "drawing_evidence": dwg_evidence,
                      "vision_used": bool(vis), "table_count": table_count,
                      "dense_table_page": is_dense_table_page})
        block = "[PAGE %d]\n%s" % (i + 1, text)
        if geo:
            block += "\n\n[TABLES]\n" + geo
        if vis:
            block += "\n[DRAWING/VISION]\n" + vis
        if dwg_evidence:
            block += "\n[UNVERIFIED EXTRACTION; REVIEW_REQUIRED]\n" + dwg_evidence
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
    import uuid
    temporary=sidecar_path+'.tmp-'+uuid.uuid4().hex
    try:
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
            f.flush();os.fsync(f.fileno())
        os.replace(temporary,sidecar_path)
        return True
    except Exception:
        return False
    finally:
        if os.path.isfile(temporary):os.unlink(temporary)
