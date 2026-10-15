"""Treat full-page OCR as the page's text when the PDF has no usable text layer.

Before 2026-10-14 every OCR transcription was stored only inside the page's
'vision' observation and indexed as "[UNVERIFIED EXTRACTION; REVIEW_REQUIRED]".
answer_guard._excerpts_by_page() deliberately drops everything after an
UNVERIFIED marker, so for a PDF whose text layer is garbled (broken font
encoding) or missing (scan), NO page had any citable text and every factual
answer was withheld ("I could not verify the generated answer ...").

OCR of a printed page is a transcription, not a model's interpretation, so for
pages without a usable native layer it is promoted to the page text, labelled
"[OCR TEXT]" so answers can say where it came from. Vision-model descriptions
stay UNVERIFIED and still cannot support a cited claim.
"""

OCR_LABEL = "[OCR TEXT]"
_OCR_MARK = "[UNVERIFIED FULL-PAGE OCR]"


def page_ocr_primary(entry):
    """OCR text to use as this page's primary text, or ''."""
    native = str(entry.get("text") or "").strip()
    if native and entry.get("native_text_quality") != "DAMAGED":
        return ""
    ocr = entry.get("ocr") or {}
    if not isinstance(ocr, dict):
        return ""
    # Prefer column-aware reading order rebuilt from the OCR boxes, so an index
    # rebuild from a saved .index.json also gets it (services/ocr_layout.py).
    try:
        from services.ocr_layout import reading_order_text
        boxes = ocr.get("boxes") or []
        regions = [t.get("image_bbox") for t in (entry.get("ocr_tables") or []) if t.get("image_bbox")]
        if regions:
            def _outside(b):
                bb = b.get("bounding_box") or {}
                cx = bb.get("x", 0) + bb.get("w", 0) / 2
                cy = bb.get("y", 0) + bb.get("h", 0) / 2
                return not any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in regions)
            boxes = [b for b in boxes if _outside(b)]
        ordered = reading_order_text(boxes)
        if ordered and ordered.strip():
            return ordered.strip()
    except Exception:
        pass
    return str(ocr.get("text") or "").strip()


def vision_without_ocr(entry):
    """The page's vision observation with the OCR copy removed (it is indexed
    separately as primary text when page_ocr_primary() returns text)."""
    vision = str(entry.get("vision") or "")
    if page_ocr_primary(entry):
        raw = str((entry.get("ocr") or {}).get("text") or "").strip()
        vision = vision.replace(_OCR_MARK + "\n" + raw, "").replace(_OCR_MARK, "").strip()
    return vision


def _grid(table):
    if table.get("grid"):
        return table["grid"]
    rows = []
    for line in (table.get("markdown") or "").splitlines():
        line = line.strip()
        if line.startswith("|") and not set(line) <= set("|-: "):
            rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows


def _captioned_tables(entry):
    """Give each OCR'd table the "Table N ..." caption printed nearest to it.

    Captions sit just below (sometimes above) a table. Matching by position
    instead of by order matters: one missed caption would otherwise shift
    every following label (Table 7's rows were indexed as "Table 8")."""
    import re
    from services.table_cells import _to_markdown, _row_units
    tables = [dict(t) for t in (entry.get("ocr_tables") or [])]
    boxes = (entry.get("ocr") or {}).get("boxes") or []
    caps = []
    for b in boxes:
        text = str(b.get("text") or "").strip()
        bb = b.get("bounding_box") or {}
        if re.match(r"Table\s*\d+\b", text) and "y" in bb:
            caps.append((text, bb))
    used = set()
    for t in tables:
        t["caption"] = ""
        r = t.get("image_bbox")
        if not r:
            continue
        best, best_d = None, None
        for i, (text, bb) in enumerate(caps):
            if i in used:
                continue
            cx = bb["x"] + bb.get("w", 0) / 2
            if not (r[0] - 40 <= cx <= r[2] + 40 or r[0] - 40 <= bb["x"] <= r[2]):
                continue
            below = bb["y"] - r[3]
            above = r[1] - (bb["y"] + bb.get("h", 0))
            d = below if -10 <= below <= 80 else (above + 1000 if -10 <= above <= 60 else None)
            if d is not None and (best_d is None or d < best_d):
                best, best_d = i, d
        if best is not None:
            used.add(best)
            t["caption"] = caps[best][0]
    # Table images have no position in the page OCR; give them the page's
    # remaining unmatched "Table N" captions in order.
    for t in tables:
        if t.get("source") == "image" and not t.get("caption"):
            for i, (text, _) in enumerate(caps):
                if i not in used:
                    used.add(i)
                    t["caption"] = text
                    break
    for t in tables:
        grid = _grid(t)
        t["markdown"] = _to_markdown(grid, t["caption"])
        t["rows"] = _row_units(grid, t["caption"], entry.get("page") or 0)
    return tables


def ocr_table_units(entry):
    """Row-level evidence units ("[TABLE ROW] ... Header: value; ...") from
    cell-by-cell table OCR: ruled tables on pages whose text layer is unusable,
    and table IMAGES on any page."""
    has_ocr_page = bool(page_ocr_primary(entry))
    units = []
    for table in _captioned_tables(entry):
        if has_ocr_page or table.get("source") == "image":
            units.extend(table.get("rows") or [])
    return units


def ocr_tables_markdown(entry):
    return "\n\n".join(t.get("markdown", "") for t in _captioned_tables(entry) if t.get("markdown"))
