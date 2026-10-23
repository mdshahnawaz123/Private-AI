"""Charts and dashboards computed from the uploaded file itself.

The model never types the numbers in a chart. It only picks WHICH table and
WHICH columns (a tiny JSON choice, validated against the real column list);
the values are read and aggregated here, in code, from the same structured
tables the answer pipeline indexes. Works for Excel sheets and for tables in
PDFs (ruled tables found by PyMuPDF, or OCR'd cell tables on scanned pages).
"""
from __future__ import annotations

import json
import os
import re
import time

from services.office_extract import _NUM, _is_total, table_row_units, _sheet_grids_openpyxl, _sheet_grids_pandas

VIZ_Q = re.compile(r"\b(chart|graph|visuali[sz]\w*|dashboard|pie|donut|bar\s*chart|histogram|infographic|diagram it|show (?:it|this|me) visually)\b"
                   r"|(?:^|[.?!]\s*|\b(?:please|can you|could you|and)\s+)plot\b(?!\s+(?:no|number|area|size|id|ids)\b)"
                   r"|\bplot\s+(?:the|a|an|it|this|these|of|me)\b", re.I)
DASH_Q = re.compile(r"\bdashboard\b", re.I)
_ID_COL = re.compile(r"\b(id|no\.?|number|plot|code|ref|year|date|item|page|sheet no|s\.? ?no)\b", re.I)
_cache: dict = {}
_pairs_cache: dict = {}


def wants_chart(question: str) -> bool:
    return bool(VIZ_Q.search(question or ""))


def _num(v):
    s = str(v or "").replace(",", "").replace(" ", "")
    pct = s.endswith("%")
    s = s.rstrip("%")
    if not _NUM.match(s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- tables
def _excel_tables(path):
    try:
        sheets = list(_sheet_grids_openpyxl(path))
    except Exception:
        sheets = list(_sheet_grids_pandas(path))
    out = []
    for title, grid in sheets:
        if not any(any(r) for r in grid):
            continue
        width = max(len(r) for r in grid)
        grid = [list(r) + [""] * (width - len(r)) for r in grid]
        found = []
        table_row_units(grid, "Sheet: " + title, collect=found)
        for t in found:
            t["sheet"] = title
            t["page"] = title
        filled = sum(1 for r in grid if sum(1 for c in r if str(c or "").strip()) >= 2)
        def _bad_header(t):
            # A sheet title merged across the header ("MODEL REGISTER - ... (6)") instead of real column names.
            base = [re.sub(r"\s*\(\d+\)$", "", str(c)).strip().lower() for c in t.get("columns") or []]
            return len(base) >= 3 and len(set(base)) <= max(1, len(base) // 3)
        big = [t for t in found if len(t.get("rows") or []) >= 0.5 * filled]
        bad = [t for t in found if _bad_header(t)]
        if filled >= 12 and (not big or all(_bad_header(t) for t in big) or sum(len(t.get("rows") or []) for t in bad) >= 0.5 * filled):
            rec = _record_table(title, grid)
            if rec:
                found = [t for t in found if t not in big and t not in bad] + [rec]
        out.extend(found)
    return out


def _record_table(title, grid):
    """Registers, logs and lists (model register, issue log, transmittal): mostly text columns, so the
    numeric table reader skips them. Find the header row and keep every record so the dashboard can
    count rows by category (status, discipline, type...)."""
    cell = lambda v: re.sub(r"\s+", " ", str(v if v is not None else "")).strip()
    rows = [[cell(c) for c in r] for r in grid]
    for i, r in enumerate(rows[:40]):
        nonempty = [c for c in r if c]
        if len(nonempty) < 3 or sum(1 for c in nonempty if _num(c) is None) < 0.7 * len(nonempty):
            continue
        if len(set(nonempty)) < 0.8 * len(nonempty):
            continue  # a merged title spread across the row, not column names
        body = rows[i + 1:i + 6]
        if sum(1 for b in body if sum(1 for c in b if c) >= max(2, len(nonempty) // 2)) < 3:
            continue
        idx = [j for j, c in enumerate(r) if c]
        cols, seen = [], {}
        for j in idx:
            n = r[j]; seen[n] = seen.get(n, 0) + 1
            cols.append(n if seen[n] == 1 else "%s (%d)" % (n, seen[n]))
        data, blanks = [], 0
        for b in rows[i + 1:]:
            vals = [b[j] if j < len(b) else "" for j in idx]
            if sum(1 for v in vals if v) < 2:
                blanks += 1
                if blanks >= 3:
                    break
                continue
            blanks = 0
            data.append(vals)
        if len(data) >= 10:
            return {"title": "Sheet: %s | Table: %s" % (title, "records"), "columns": cols, "rows": data,
                    "sheet": title, "page": title, "records": True}
    return None


_COUNT_Q = re.compile(r"\b(number of|count|how many|records?|items?|entries|per|by)\b", re.I)


def _category_cols(t):
    """Columns worth counting by: 2-25 distinct values, mostly filled, not IDs or numbers."""
    n = len(t["rows"])
    out = []
    for j, c in enumerate(t["columns"]):
        if j in t.get("numeric", []) or j in t.get("serial", []):
            continue
        vals = [str(r[j]).strip() for r in t["rows"] if j < len(r) and str(r[j]).strip()]
        if len(vals) < 0.6 * n:
            continue
        k = len(set(vals))
        if 2 <= k <= 25 and k < 0.5 * len(vals) and not re.search(r"\b(name|description|title|remarks?|comments?)\b", c, re.I):
            out.append((k, j))
    return [j for _, j in sorted(out)]


def count_chart(t, x, question="", top_n=15):
    """Count of records per value of column x (values counted in code)."""
    from collections import Counter
    cnt = Counter(str(r[x]).strip() for r in t["rows"] if x < len(r) and str(r[x]).strip())
    if len(cnt) < 2:
        return None
    order = [k for k, _ in cnt.most_common(top_n)]
    col = re.sub(r"\s+", " ", t["columns"][x]).strip()
    pie = len(order) <= 8 and re.search(r"\b(pie|donut|share|percent|proportion|split)\b", question or "", re.I)
    src = t["title"].replace("Sheet: ", "")
    spec = {"chart_type": "pie" if pie else "bar", "title": ("Records by %s" % col)[:90], "units": "records",
            "subtitle": "Counted from %s - %d records%s" % (src, len(t["rows"]), " (top %d)" % top_n if len(cnt) > top_n else ""),
            "sources": [{"page": t.get("page"), "table": t["title"]}]}
    if pie:
        spec["data"] = [{"name": k, "value": cnt[k]} for k in order]
    else:
        spec["categories"] = order
        spec["series"] = [{"name": "Records", "data": [cnt[k] for k in order]}]
    from intelligence.visualization_schema import validate_chart_spec
    ok, clean, err = validate_chart_spec(spec)
    if not ok:
        return None
    clean["table_id"] = t["id"]
    return clean


def count_chart_for_question(question, doc_paths):
    """'Number of models by discipline', 'issues per status', 'how many drawings by type'."""
    if not _COUNT_Q.search(question or ""):
        return None
    qw = _words(question) - _GENERIC
    explicit = re.search(r"\b(number of|count|how many|records?|entries)\b", question or "", re.I)
    if not explicit:
        # "fire resistance by element" names a measure: chart that measure, do not count rows.
        for path in doc_paths:
            for t in tables_for(path):
                if any(_words(t["columns"][j]) & qw for j in t.get("numeric", [])):
                    return None
    best = None
    for path in doc_paths:
        for t in tables_for(path):
            if len(t["rows"]) < 5:
                continue
            for j in _category_cols(t):
                cw = _words(t["columns"][j])
                sc = len(cw & qw) * 3 + (1 if t.get("records") else 0) + min(len(t["rows"]), 500) / 1000
                if (cw & qw) and (best is None or sc > best[0]):
                    best = (sc, t, j, path)
    if not best:
        return None
    spec = count_chart(best[1], best[2], question)
    if spec:
        spec["sources"][0]["filename"] = os.path.basename(best[3])
    return spec


def _looks_like_data_header(cols):
    """A header row that is really a data row (e.g. 'Bicycle Parking | 353 RACKS')."""
    cells = [str(c or "") for c in cols]
    filler = sum(1 for c in cells if not c or re.match(r"^Column \d+$", c))
    nums = sum(1 for c in cells if re.search(r"\d", c))
    return nums >= 1 and (nums + filler) >= max(2, len(cells) - 1)


def _repair_headers(found):
    """When a table is split at a TOTAL row, the next block's first data row
    becomes its header. Re-attach it to the previous block's real headers."""
    for i in range(1, len(found)):
        prev, t = found[i - 1], found[i]
        if len(prev.get("columns") or []) != len(t.get("columns") or []):
            continue
        if not _looks_like_data_header(t["columns"]) or _looks_like_data_header(prev["columns"]):
            continue
        first = ["" if re.match(r"^Column \d+$", str(c or "")) else c for c in t["columns"]]
        t["rows"] = [first] + list(t.get("rows") or [])
        t["columns"] = list(prev["columns"])


def _fix_pdf_cell(c):
    """Repair PDF text-layer artefacts in a table cell: a decimal point or thousands comma printed
    on its own baseline ("78 5\n." -> 78.5, "29 725\n," -> 29,725, "5 0*\n." -> 5.0*) and words run
    together when the PDF has no space glyphs ("TypeOfMaterial" -> "Type Of Material")."""
    s = re.sub(r"\s+", " ", str(c or "")).strip()
    m = re.fullmatch(r"(\d+) (\d+)(\*?) ?([.,])", s)
    if m:
        return m.group(1) + m.group(4) + m.group(2) + m.group(3)
    if " " not in s and len(s) > 12 and re.search(r"[a-z][A-Z]", s):
        s = re.sub(r"(?<=[a-z])(?=[A-Z][a-z])|(?<=[a-z])(?=\()", " ", s)
    return s


def _pdf_tables(path):
    out = []
    meta = {}
    try:
        with open(path + ".index.json", encoding="utf-8") as fh:
            meta = json.load(fh)
    except Exception:
        pass
    ocr_pages = {}
    for pg in meta.get("pages") or []:
        for t in pg.get("ocr_tables") or []:
            grid = t.get("grid") if isinstance(t, dict) else None
            if grid:
                ocr_pages.setdefault(pg.get("page"), []).append((t.get("caption") or "", grid))
    try:
        import fitz
        with fitz.open(path) as doc:
            for i, page in enumerate(doc, 1):
                if i in ocr_pages:
                    continue
                try:
                    from services.pdf_text_quality import safe_find_tables
                    _ft = safe_find_tables(page)
                    for k, tb in enumerate(_ft.tables if _ft else [], 1):
                        grid = [[_fix_pdf_cell(c) for c in row] for row in tb.extract()]
                        ocr_pages.setdefault(i, []).append(("", grid))
                except Exception:
                    continue
    except Exception:
        pass
    for page, items in sorted(ocr_pages.items(), key=lambda kv: (kv[0] is None, kv[0])):
        for cap, grid in items:
            found = []
            two = _two_col_table(grid, page, cap)
            if two:
                out.append(two)
            table_row_units(grid, "Page %s" % page, cap, collect=found)
            _repair_headers(found)
            for t in found:
                t["page"] = page
                if cap and cap not in t["title"]:
                    t["title"] += " | " + cap
            out.extend(found)
    return out


def _split_side_by_side(tables):
    """Two tables printed next to each other come out as one wide grid
    ('AREA STATEMENT SUMMARY / ITEM ... BUILT-UP AREA BREAKDOWN (Per Level) / ITEM').
    Split at each later column that starts a new numbered table."""
    out = []
    for t in tables:
        cols = t.get("columns") or []
        cuts = [j for j in range(1, len(cols)) if " / " in cols[j] and _serial_col(t, j)
                and re.match(r"^(item|s\.?\s?no\.?|#)$", cols[j].split(" / ")[-1].strip(), re.I)]
        if not cuts:
            out.append(t)
            continue
        bounds = [0] + cuts + [len(cols)]
        for a, b in zip(bounds, bounds[1:]):
            sub_cols = list(cols[a:b])
            name = ""
            if a and " / " in sub_cols[0]:
                name, sub_cols[0] = sub_cols[0].rsplit(" / ", 1)
            sub_cols = ["Description" if re.match(r"^Column \d+$", c) and k and re.match(r"^(item|#)$", sub_cols[k - 1].split(" / ")[-1], re.I) else c
                        for k, c in enumerate(sub_cols)]
            rows = [list(r[a:b]) for r in t["rows"] if any(str(c).strip() for c in r[a:b])]
            if not rows:
                continue
            nt = dict(t)
            nt.update(columns=sub_cols, rows=rows)
            if name:
                nt["title"] = re.sub(r"Table: .*", "Table: " + name.strip(), t["title"]) if "Table: " in t["title"] else t["title"] + " | Table: " + name.strip()
            out.append(nt)
    return out


def tables_for(path):
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return []
    if key in _cache:
        return _cache[key]
    ext = os.path.splitext(path)[1].lower()
    found = _excel_tables(path) if ext in (".xlsx", ".xlsm", ".xls") else _pdf_tables(path) if ext == ".pdf" else []
    tables = [t for t in found if t.get("columns")]
    # One combined table per sheet when its sections share the sheet layout
    # (e.g. "Proposed Residential", "Proposed Commercial", "Proposed Mixed Use" blocks of one plot schedule).
    by_sheet = {}
    for t in tables:
        if t.get("sheet") and t.get("columns"):
            # Group by sheet and column count so sections with sub-headers are not dropped
            by_sheet.setdefault((t["sheet"], len(t["columns"])), []).append(t)
    for (sheet, _), group in by_sheet.items():
        if len(group) >= 2:
            # Pick canonical column headers with the most descriptive sub-headers
            best_table = max(group, key=lambda g: sum(1 for c in g.get("columns", []) if " / " in str(c)))
            cols = list(best_table["columns"])
            comb_rows = []
            seen_tuples = set()
            for g in group:
                for r in g.get("rows", []):
                    # Filter out accidental repeated headers inside section blocks
                    if any(str(r[k]).strip().lower() in ("plot no.", "plot no", "land use", "zone", "item") for k in range(min(4, len(r)))):
                        continue
                    if _is_total(r):
                        continue
                    r_tuple = tuple(str(x) for x in r)
                    if r_tuple in seen_tuples:
                        continue
                    seen_tuples.add(r_tuple)
                    comb_rows.append(r)
            tables.append({
                "title": "Sheet: %s | Table: all sections" % sheet,
                "columns": cols,
                "rows": comb_rows,
                "sheet": sheet,
                "page": sheet,
                "combined": True
            })
    _pairs_cache[key] = [p for t in found for p in (t.get("pairs") or [])]
    tables = _split_side_by_side(tables)
    _seen_rows[:] = [set(_fix_pdf_cell(r[0]) for r in t["rows"]) | set(str(r[0]) for r in t["rows"]) for t in tables if t.get("pairs_table")]
    tables = tables + _section_compare_tables(tables) + _pair_tables(_pairs_cache[key])
    for i, t in enumerate(tables):
        t["id"] = i
        t["serial"] = [j for j in range(len(t["columns"])) if _serial_col(t, j)]
        t["numeric"] = [j for j, c in enumerate(t["columns"]) if _numeric_col(t, j) and j not in t["serial"]]
    _cache[key] = tables
    return tables


def _clean_head(h):
    """'2 Uniform(kN/m )' -> 'Uniform (kN/m²)': a superscript 2 that the PDF placed before the text."""
    h = re.sub(r"\s+", " ", str(h or "")).strip()
    m = re.match(r"^([23])\s+(.*?)\(\s*(k?N/m|m|mm)\s*\)\s*$", h)
    if m:
        h = "%s (%s%s)" % (m.group(2).strip(), m.group(3), "²" if m.group(1) == "2" else "³")
    return re.sub(r"(?<=[a-z])(?=\()", " ", h)


def _two_col_table(grid, page, cap=""):
    """A label | value table (material densities, live loads, fire ratings) keeps its real header
    here; the generic reader turns 2-column tables into key/value pairs and loses it."""
    rows = [list(r) for r in grid if any(str(c or "").strip() for c in r)]
    if not rows:
        return None
    keep = [j for j in range(max(len(r) for r in rows)) if any(j < len(r) and str(r[j] or "").strip() for r in rows)]
    rows = [[str(r[j] if j < len(r) else "").strip() for j in keep] for r in rows]
    if len(keep) < 2:
        return None
    # header: last row before the first numeric value in column 2
    first = next((i for i, r in enumerate(rows) if _num(r[1].rstrip("*")) is not None and r[0]), None)
    if first is None or first == 0:
        return None
    head = rows[first - 1]
    if not head[0] or not head[1] or _num(head[1]) is not None:
        return None
    data = [r[:2] for r in rows[first:] if r[0] and _num(r[1].rstrip("*")) is not None]
    if len(data) < 2 or len(data) < 0.6 * len(rows[first:]):
        return None
    title_cap = cap or (rows[first - 2][0] if first >= 2 and rows[first - 2][0] and not rows[first - 2][1] else "")
    return {"title": "Page %s | Table: %s" % (page, title_cap or "%s by %s" % (_clean_head(head[1]), _clean_head(head[0]))),
            "columns": [_clean_head(head[0]), _clean_head(head[1])], "rows": [[k, v.rstrip("*")] for k, v in data], "page": page, "pairs_table": True}


_seen_rows = []


def _pair_tables(pairs):
    """Two-column tables (label | value) are stored as key/value pairs, so 'Material density by type',
    'Live load by occupancy' or 'Fire resistance by element' never became charts. Turn each run of 3+
    numeric pairs under the same heading into a small table; a preceding text/text pair is its header."""
    out, run, head, where = [], [], None, None
    def flush():
        if len(run) >= 2 and not any(set(r[0] for r in run) <= _covered for _covered in _seen_rows):
            cols = [_clean_head(h) for h in head] if head else ["Item", "Value"]
            cap = str(where or "")
            out.append({"title": cap + ("" if " | Table: " in cap else " | Table: %s by %s" % (cols[1], cols[0])),
                        "columns": cols, "rows": [list(r) for r in run], "page": cap.split(" | ")[0].replace("Page ", ""),
                        "pairs_table": True})
    for label, k, v in pairs:
        k, v = _fix_pdf_cell(k), _fix_pdf_cell(v)
        n = _num(str(v).rstrip("*"))
        if label != where:
            flush(); run, head, where = [], None, label
        if n is None:
            flush(); run = []
            head = (k, v) if (_num(k) is None and len(k) < 60 and len(v) < 60) else None
            continue
        run.append((k, str(v).rstrip("*")))
    flush()
    return out


def _section_compare_tables(tables):
    """Repeated per-section tables (TOWER 1..8, BLOCK A..D, BUILDING 01..) -> one comparison table with a
    row per section, taken from each section's TOTAL row (or the sum of its level rows when the PDF
    reader lost it). PDF readers split these tables into fragments (the TOTAL row ends up in a second
    'TOWER n' piece whose header is a data row), shift columns by one, and drop a heading that falls on
    the previous page - so columns are located by name and fragments are stitched by section."""
    norm = lambda c: re.sub(r"\s+", " ", str(c)).strip().lower()
    sec_re = re.compile(r"^(.*?)[\s\-_#]*(\d{1,3}|[A-Z])$")
    name_of = lambda t: str(t.get("title") or "").replace("Sheet: ", "").split(" | Table: ")[-1].strip() if " | Table: " in str(t.get("title") or "") else ""
    measure = lambda c: bool(re.search(r"\((sq ?m|sqm|m2|m²|sq ?ft|unit|units|no\.?|aed|usd|\$|kg|t|m3|m³)\)|\b(gfa|gia|nsa|nia|bua|area|units?|cost|amount|qty|quantity|count)\b", c, re.I)) \
        and not re.search(r"efficien|ratio|percent|%|level|storey|floor no", c.split(" / ")[-1] if "(" in c else c, re.I) and not re.match(r"^column \d+$", norm(c))
    stems = {}
    for t in tables:
        m = sec_re.match(name_of(t))
        if m and m.group(1).strip() and not re.match(r"^(page|section|table)$", m.group(1).strip(), re.I):
            stems.setdefault(m.group(1).strip().lower(), set()).add(m.group(2))
    out = []
    for kind, ids in stems.items():
        if len(ids) < 3:
            continue
        # main tables: header names at least 2 measures
        mains, order = {}, []
        heads = None
        for k, t in enumerate(tables):
            if t.get("combined") or t.get("records") or t.get("compare"):
                continue
            nm = name_of(t)
            m = sec_re.match(nm)
            is_sec = bool(m and m.group(1).strip().lower() == kind)
            meas = [c for c in t.get("columns") or [] if measure(c)]
            if is_sec and len(meas) >= 2 and nm.upper() not in mains:
                mains[nm.upper()] = [t]; order.append(nm.upper()); heads = heads or meas
            elif is_sec and nm.upper() in mains:
                mains[nm.upper()].append(t)            # continuation fragment (ROOF / TOTAL rows)
            elif not nm and heads and len([c for c in t.get("columns") or [] if c in heads]) >= 2 and len(t.get("rows") or []) >= 3:
                mains["?%d" % k] = [t]; order.append("?%d" % k)  # heading lost across a page break
        if len(order) < 3 or not heads:
            continue
        nums = sorted(int(x.split()[-1]) for x in order if not x.startswith("?") and x.split()[-1].isdigit())
        missing = sorted(set(range(1, (max(nums) if nums else 0) + 2)) - set(nums)) if nums else []
        rows = []
        for key in order:
            frags = mains[key]
            if key.startswith("?"):
                if not missing:
                    continue
                key = "%s %d" % (kind.upper(), missing.pop(0))
            main = frags[0]
            idx = {h: main["columns"].index(h) for h in heads if h in main["columns"]}
            cand = list(main["rows"])
            for f in frags[1:]:
                cand += [list(f["columns"])] + list(f["rows"])   # a fragment's 'header' is often a data row
            tot = next((r for r in cand if any(re.match(r"^(grand\s+)?total$", str(c).strip(), re.I) for c in r[:6])), None)
            vals = []
            for h in heads:
                j = idx.get(h)
                if j is None:
                    vals.append(None); continue
                v = _num(tot[j]) if tot is not None and j < len(tot) else None
                if v is None:
                    v = sum(_num(r[j]) or 0 for r in main["rows"] if j < len(r) and re.search(r"level|floor|ground|roof|basement|podium|^l\d", " ".join(str(c) for c in r[:6]), re.I))
                vals.append(v)
            rows.append([key] + ["%g" % round(v, 2) if v is not None else "" for v in vals])
        if len(rows) < 3:
            continue
        rows.sort(key=lambda r: int(r[0].split()[-1]) if r[0].split()[-1].isdigit() else 0)
        cols_out = [kind.title()] + heads
        unit_cols = [k for k, h in enumerate(heads, 1) if re.search(r"\(units?\)", h, re.I)]
        if len(unit_cols) >= 3:
            # many unit-type columns (1 Bed-A ... 3 Bed-D): add the per-section total, keep the area columns
            for r in rows:
                r.append("%g" % sum(_num(r[k]) or 0 for k in unit_cols))
            keep = [0] + [k for k in range(1, len(cols_out)) if k not in unit_cols]
            rows = [[r[k] for k in keep] + [r[-1]] for r in rows]
            cols_out = [cols_out[k] for k in keep] + ["Total units"]
        out.append({"title": "Comparison by %s (%d %ss)" % (kind, len(rows), kind),
                    "columns": cols_out, "rows": rows,
                    "page": tables[0].get("page"), "sheet": tables[0].get("sheet"), "compare": True})
    return out


def _serial_col(t, j):
    """Row-number columns (ITEM 1,2,3...) are labels, never measures or categories."""
    head = t["columns"][j].split(" / ")[-1].strip()
    vals = [str(r[j]).strip() for r in t["rows"] if j < len(r) and str(r[j]).strip()]
    ints = [int(v) for v in vals if v.isdigit()]
    if re.match(r"^(item|s\.?\s?no\.?|sr\.?\s?no\.?|sl\.?\s?no\.?|#)$", head, re.I) and len(ints) >= max(1, len(vals) // 2):
        return True
    if len(ints) < 3 or ints[0] not in (0, 1) or len(ints) < 0.5 * len(vals) or len(set(ints)) < 3:
        return False
    head_ok = bool(re.search(r"\b(item|no\.?|s\.?\s?no|sr|#)\s*$", t["columns"][j].strip(), re.I))
    if not (j == 0 or head_ok):
        return False
    return sum(1 for a, b in zip(ints, ints[1:]) if b - a == 1) >= 0.8 * (len(ints) - 1)


def _numeric_col(t, j):
    vals = [r[j] for r in t["rows"] if j < len(r) and r[j]]
    if len(t["rows"]) == 1 and vals:
        return _num(vals[0]) is not None
    if len(vals) < 2:
        return False
    if sum(1 for v in vals if re.match(r"^0\d{2,}$", str(v).strip())) >= 0.6 * len(vals):
        return False  # zero-padded codes ("0000001", "007") are identifiers, not quantities
    return sum(_num(v) is not None for v in vals) >= 0.7 * len(vals)


# ---------------------------------------------------------------- choosing
def _stem(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _words(s):
    return {_stem(w) for w in re.findall(r"[a-z0-9%]+", (s or "").lower()) if len(w) > 1 and w not in
            {"the", "of", "in", "and", "for", "by", "to", "a", "me", "show", "chart", "graph", "plot", "as", "on", "per", "all", "what", "is", "are", "with", "visual", "visualize", "visualise", "dashboard", "create", "make", "draw", "pie", "bar", "line", "sheet", "table"}}


_GENERIC = {"total", "sum", "value", "values", "amount", "number", "count", "data", "file", "this", "vs", "versus", "compare", "comparison"}


def _split_q(q):
    """(measure words, by-words) from '... <measure> by <dimension> ...'."""
    m = re.search(r"\b(?:by|per|across|for each|for every|grouped by)\s+([a-z0-9 &/-]{2,40}?)(?=\s+(?:as|in|for|from|on|with|chart|graph|plot|pie|bar|line)\b|[?.,]|$)", (q or "").lower())
    byw = _words(m.group(1)) if m else set()
    return _words(q) - byw, byw


def _by_col(t, byw):
    best, bj = 0, None
    for j, c in enumerate(t["columns"]):
        if j in t["numeric"]:
            continue
        o = len(_words(c.split(" / ")[-1]) & byw)
        if o > best:
            best, bj = o, j
    return bj


def _score(t, q, preferred_pages):
    qw = _words(q)
    tw = _words(t["title"] + " " + " ".join(t["columns"]))
    s = 3 * len(qw & tw) + 3 * len(qw & _words(t["title"].split("Table: ")[-1].replace("Sheet: ", "")))
    cells = " ".join(" ".join(r[:3]) for r in t["rows"][:200]).lower()
    s += sum(1 for w in qw if len(w) > 3 and w in cells)
    if str(t.get("page")) in preferred_pages:
        s += 4
    _mw, _byw = _split_q(q)
    if _byw:
        bj = _by_col(t, _byw)
        if bj is not None:
            d = len({r[bj] for r in t["rows"] if bj < len(r) and r[bj]})
            s += 8 if 2 <= d <= 25 else -8
        else:
            s -= 4
        named = [j for j in t["numeric"] if (_words(t["columns"][j]) & _mw) - _GENERIC]
        s += 4 if named else 0
    # "... by land use": a text column named in the question must actually vary in this table
    for j, c in enumerate(t["columns"]):
        if j in t["numeric"] or not (_words(c) & qw):
            continue
        d = len({r[j] for r in t["rows"] if j < len(r) and r[j]})
        s += 5 if 2 <= d <= 25 else -6 if d <= 1 else 0
    if t.get("combined"):
        s += 1
    s += min(len(t["rows"]), 30) / 30.0 + (1 if t["numeric"] else -5)
    return s


def _ollama_json(prompt, timeout=60):
    import httpx
    from config import get_settings
    url = os.getenv("EXPO_CHAT_OLLAMA_HOST") or getattr(get_settings(), "ollama_host", "http://127.0.0.1:11434")
    model = os.getenv("EXPO_VIZ_MODEL", "qwen3.5:9b")
    body = {"model": model, "stream": False, "format": "json", "options": {"temperature": 0},
            "messages": [{"role": "user", "content": prompt}]}
    if "qwen3" in model.lower():
        body["think"] = False
    r = httpx.post(url.rstrip("/") + "/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    return json.loads((r.json().get("message") or {}).get("content") or "{}")


def _ask_model_choice(question, shortlist):
    """The local model picks the table and columns (indexes only). Returns (table, choice) or (None, None)."""
    try:
        blocks = []
        for n, t in enumerate(shortlist):
            cols = "; ".join("%d=%s%s" % (j, c, "#" if j in t["numeric"] else "") for j, c in enumerate(t["columns"]))
            first = " | ".join(t["rows"][0][:8]) if t["rows"] else ""
            blocks.append("TABLE %d: %s (%d rows)\n  columns: %s\n  first row: %s" % (n, t["title"], len(t["rows"]), cols, first))
        prompt = ("Choose the table and columns to chart for the question. Columns marked # are numeric.\n\n%s\n\n"
                  "Question: %s\n\nReply with JSON only: {\"table\": <table number>, \"x\": <column index for the "
                  "categories>, \"y\": [<numeric column indexes to plot>], \"chart\": \"bar|line|pie|donut|stacked_bar\", "
                  "\"filter_col\": <column index or null>, \"filter_value\": <text or null>, \"title\": \"short chart title\"}"
                  % ("\n".join(blocks), question))
        choice = _ollama_json(prompt)
        k = int(choice.get("table", 0))
        if 0 <= k < len(shortlist):
            return shortlist[k], choice
    except Exception:
        pass
    return None, None


def _heuristic_choice(question, t):
    q = (question or "").lower()
    text_cols = [j for j in range(len(t["columns"])) if j not in t["numeric"] and j not in (t.get("serial") or [])] \
        or [j for j in range(len(t["columns"])) if j not in t["numeric"]]
    _mw, _byw = _split_q(question)
    x = _by_col(t, _byw) if _byw else None
    if x is None:
        x = next((j for j in text_cols if (_words(t["columns"][j]) & _words(q)) - _GENERIC
                  and 2 <= len({r[j] for r in t["rows"] if j < len(r) and r[j]}) <= 25), None)
    if x is None and text_cols:
        x = max(text_cols, key=lambda j: (2 <= len({r[j] for r in t["rows"] if j < len(r) and r[j]}) <= 40,
                                          -text_cols.index(j)))
    ys = [j for j in t["numeric"] if (_words(t["columns"][j]) & _mw) - _GENERIC and "%" not in t["columns"][j]]
    if not ys and re.search(r"\b(units?|count|how many|number of|quantity|qty|nos?)\b", q):
        ys = [j for j in t["numeric"] if re.match(r"^(no\.?|nos\.?|count|qty|quantity|number)$", t["columns"][j].split(" / ")[-1].strip(), re.I)][:1]
    if not ys:
        ys = [j for j in t["numeric"] if not _ID_COL.search(t["columns"][j]) and "%" not in t["columns"][j]][:1] or t["numeric"][:1]
    return {"x": x if x is not None else 0, "y": ys, "chart": None, "title": ""}


def _chart_type(question, n_cats, n_series, hint):
    q = (question or "").lower()
    if re.search(r"\bdonut|doughnut\b", q):
        return "donut"
    if re.search(r"\bpie\b|share|proportion|percentage|distribution|breakdown|split", q) and n_series == 1 and n_cats <= 12:
        return "pie"
    if re.search(r"\bline\b|trend|over time|timeline|progress", q):
        return "line"
    if re.search(r"\bstack", q) and n_series > 1:
        return "stacked_bar"
    if hint in ("bar", "line", "pie", "donut", "stacked_bar"):
        if hint in ("pie", "donut") and (n_series > 1 or n_cats > 12):
            return "bar"
        return hint
    return "bar"


def build_chart(t, question, choice=None, top_n=15):
    choice = choice or _heuristic_choice(question, t)
    ncol = len(t["columns"])
    try:
        x = int(choice.get("x"))
    except (TypeError, ValueError):
        x = _heuristic_choice(question, t)["x"]
    ys = [int(j) for j in (choice.get("y") or []) if str(j).lstrip("-").isdigit() and int(j) in t["numeric"]]
    if not (0 <= x < ncol) or not ys:
        h = _heuristic_choice(question, t)
        x, ys = h["x"], ys or h["y"]
    ys = [j for j in ys if j != x][:4]
    # Prefer numeric columns the question names ("total area") over the model's pick.
    qall = _split_q(question)[0]
    qw = qall - _GENERIC
    _last = lambda j: t["columns"][j].split(" / ")[-1]
    _ov = lambda j: (len(_words(_last(j)) & qw) + 0.5 * len(_words(t["columns"][j]) & qw)
                     + (0.75 if "total" in qall and "total" in _words(_last(j)) else 0))
    named = [j for j in t["numeric"] if j != x and len(_words(_last(j)) & qw) >= 1 and not _ID_COL.search(_last(j))]
    _mixed = len({_last(j).lower() for j in ys}) > 1
    if named and (_mixed or max(_ov(j) for j in named) > max([_ov(j) for j in ys] or [0])):
        b = max(named, key=_ov)
        full = [j for j in named if _words(_last(j)) - _GENERIC and (_words(_last(j)) - _GENERIC) <= qw]
        measures = list(dict.fromkeys(_last(j).lower() for j in sorted(full, key=_ov, reverse=True)))
        if len(measures) >= 2:
            # the question names two different measures ("population served and minimum site area")
            ys = [max([j for j in full if _last(j).lower() == m], key=_ov) for m in measures[:4]]
        else:
            # the same measure under other column groups ("DM requirement" vs "Developer proposed")
            ys = [b] + [j for j in named if j != b and _last(j).lower() == _last(b).lower() and _ov(j) >= _ov(b) - 1.5][:3]
    # Percent columns only when the question asks for percentages; otherwise plot the quantities.
    if not re.search(r"percent|%|ratio|rate", question or "", re.I):
        nonpct = [j for j in ys if "%" not in t["columns"][j] and not re.search(r"percent", t["columns"][j], re.I)]
        if not nonpct:
            alt = [j for j in t["numeric"] if j != x and "%" not in t["columns"][j] and not _ID_COL.search(t["columns"][j]) and not re.search(r"percent", t["columns"][j], re.I)]
            nonpct = alt[:1]
        ys = nonpct or ys
    if not ys:
        return None
    fcol, fval = choice.get("filter_col"), str(choice.get("filter_value") or "").strip().lower()
    rows = [r for r in t["rows"] if not _is_total(r)]
    if fval and str(fcol).isdigit() and int(fcol) < ncol:
        sub = [r for r in rows if fval in str(r[int(fcol)]).lower()]
        rows = sub or rows
    if len(rows) == 1 and len(ys) >= 1 and (len(t["numeric"]) >= 2):
        r = rows[0]
        cats = [t["columns"][j] for j in t["numeric"] if _num(r[j]) is not None]
        vals = [_num(r[j]) for j in t["numeric"] if _num(r[j]) is not None]
        ctype = _chart_type(question, len(cats), 1, choice.get("chart"))
        spec = {"chart_type": ctype, "title": (choice.get("title") or t["title"].split("Table: ")[-1])[:90],
                "subtitle": "Computed from " + t["title"].replace("Sheet: ", ""), "sources": [{"page": t.get("page"), "table": t["title"]}]}
        if ctype in ("pie", "donut"):
            spec["data"] = [{"name": c, "value": round(v, 4)} for c, v in zip(cats, vals)]
        else:
            spec["chart_type"] = "bar" if ctype == "stacked_bar" else ctype
            spec["categories"], spec["series"] = cats, [{"name": "Value", "data": [round(v, 4) for v in vals]}]
        from intelligence.visualization_schema import validate_chart_spec
        ok, clean, _ = validate_chart_spec(spec)
        if ok:
            clean["table_id"] = t["id"]
            return clean
    agg, order = {}, []
    for r in rows:
        key = str(r[x] if x < len(r) else "").strip()
        if not key:
            continue
        if key not in agg:
            agg[key] = [0.0] * len(ys)
            order.append(key)
        for k, j in enumerate(ys):
            v = _num(r[j] if j < len(r) else "")
            if v is not None:
                agg[key][k] += v
    if not order:
        return None
    ctype = _chart_type(question, len(order), len(ys), choice.get("chart"))
    _seq = sum(1 for k in order if re.search(r"floor|level|basement|podium|roof|tower|block|phase|month|year|week|day|q[1-4]\b", k, re.I))
    if _seq >= 0.6 * len(order) and len(order) <= 40:
        top_n = max(top_n, len(order))  # floors / levels / time: keep every row in document order
    if ctype != "line" and len(order) > top_n:
        keep = set(sorted(order, key=lambda k: -abs(agg[k][0]))[:top_n])
        order = [k for k in order if k in keep] if _seq >= 0.6 * len(order) else sorted(keep, key=lambda k: -abs(agg[k][0]))
    heads = [t["columns"][j] for j in ys]
    unit = ""
    m = re.search(r"\(([^)]{1,12})\)", heads[0])
    if m:
        unit = m.group(1)
    _short = lambda h: re.sub(r"\s+", " ", h.split(" / ")[-1]).strip().title() if h.split(" / ")[-1].isupper() else re.sub(r"\s+", " ", h.split(" / ")[-1]).strip()
    title = (choice.get("title") or "").strip() or ("%s by %s" % (" and ".join(dict.fromkeys(_short(h) for h in heads)), _short(t["columns"][x])))
    _bm = re.search(r"\b(?:by|per|across|for each)\s+([a-z][a-z \-]{1,25}?)(?=\s+(?:as|in|chart|graph|pie|bar)\b|[?.,]|$)", (question or "").lower())
    _dim = _bm.group(1).strip().title() if _bm else "Type"
    title = re.sub(r"\b(Column \d+|Description)\b", _dim, title)
    title = re.sub(r"^Sq\.?M\.?(?=\s)", "Area (sq m)", title)
    title = re.sub(r"^Sq\.?Ft\.?(?=\s)", "Area (sq ft)", title)
    title = re.sub(r"^No\.? by\b", "Count by", title)
    src = t["title"].replace("Sheet: ", "")
    spec = {"chart_type": ctype, "title": title[:90], "units": unit,
            "subtitle": "Computed from %s - %d rows%s" % (src, len(rows), " (top %d)" % top_n if len(agg) > len(order) else ""),
            "sources": [{"page": t.get("page"), "table": t["title"]}]}
    if ctype in ("pie", "donut"):
        spec["data"] = [{"name": k, "value": round(max(agg[k][0], 0), 4)} for k in order]
    else:
        spec["categories"] = order
        _last = [h.split(" / ")[-1] for h in heads]
        _names = _last if len(set(_last)) == len(_last) else [h.split(" / ")[0][:40] + " - " + h.split(" / ")[-1] for h in heads]
        spec["series"] = [{"name": _names[i], "data": [round(agg[k][i], 4) for k in order]} for i, h in enumerate(heads)]
    from intelligence.visualization_schema import validate_chart_spec
    ok, clean, err = validate_chart_spec(spec)
    if not ok:
        return None
    clean["table_id"] = t["id"]
    return clean


def chart_for_question(question, doc_paths, preferred_pages=(), use_model=True):
    """Best chart for the question across the given documents, or None."""
    counted = count_chart_for_question(question, doc_paths)
    if counted:
        return counted
    scored = []
    for path in doc_paths:
        for t in tables_for(path):
            t["_path"] = path
            scored.append((_score(t, question, {str(p) for p in preferred_pages}), t))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    shortlist = [t for _, t in scored[:6]]
    ok = lambda sp: sp is not None and len(sp.get("categories") or sp.get("data") or []) >= 2
    t, choice = _ask_model_choice(question, shortlist) if use_model else (None, None)
    spec = build_chart(t, question, choice) if t is not None else None
    if not ok(spec):
        spec = None
        for cand in shortlist:
            sp = build_chart(cand, question, None)
            if ok(sp):
                t, spec = cand, sp
                break
    if spec:
        # Honesty check: the chosen table must share at least one meaningful word with the question
        # (its title or columns); otherwise say no table fits instead of showing an unrelated chart.
        qw = {w for w in _words(question) - _GENERIC if len(w) > 2} - {"chart", "graph", "pie", "bar", "line", "show", "plot", "type", "by"}
        tw = _words(" ".join([t.get("title") or ""] + [str(c) for c in t.get("columns") or []]))
        if qw and not (qw & tw):
            return None
        spec["sources"][0]["filename"] = os.path.basename(t["_path"])
    return spec


# ---------------------------------------------------------------- dashboard
_KEY_COL = re.compile(r"total|gfa|area|qty|quantity|amount|cost|value|population|resident|units|budget|sum", re.I)


def _distinct(t, j):
    return len({r[j] for r in t["rows"] if j < len(r) and r[j]})


_CAT_COL = re.compile(r"land\s*use|use|zone|type|category|class|status|discipline|level|floor|phase|trade|sector|district|description|name", re.I)


def _unit_of(name):
    m = re.search(r"\(([^)]{1,12})\)", name)
    return m.group(1).lower().replace(" ", "") if m else ""


def _dash_choice(t):
    rows = [r for r in t["rows"] if not _is_total(r)]
    text_cols = [j for j in range(len(t["columns"])) if j not in t["numeric"] and j not in (t.get("serial") or [])] \
        or [j for j in range(len(t["columns"])) if j not in t["numeric"]]
    xs = [j for j in text_cols if 2 <= _distinct(t, j) <= 15]
    if not xs:
        return None
    pri = ["land use", "use", "type", "category", "class", "status", "discipline", "trade", "zone", "level", "floor", "phase", "sector", "district", "name", "description"]
    def _rank(j):
        n = t["columns"][j].lower()
        return next((i for i, w in enumerate(pri) if w in n), len(pri))
    xs.sort(key=lambda j: (_rank(j), j))
    x = xs[0]
    ys = []
    for j in t["numeric"]:
        name = t["columns"][j]
        if _ID_COL.search(name) or "%" in name:
            continue
        tot = sum(abs(_num(r[j]) or 0) for r in rows if j < len(r))
        if tot > 0:
            ys.append((0 if re.search(r"total", name, re.I) else 1 if _KEY_COL.search(name) else 2, j))
    ys = [j for _, j in sorted(ys)]
    if not ys:
        return None
    first = ys[0]
    pick = [first] + [j for j in ys[1:] if _unit_of(t["columns"][j]) and _unit_of(t["columns"][j]) == _unit_of(t["columns"][first])][:1]
    return {"x": x, "y": pick, "chart": None, "title": ""}


def _importance(t):
    n = len(t["rows"])
    if t.get("compare"):
        return -1
    if t.get("combined"):
        return 0
    if 5 <= n <= 40:
        return 1
    if n > 40:
        return 2
    return 3


def dashboard_for(path, max_charts=8):
    t0 = time.time()
    tables = tables_for(path)
    pairs = _pairs_cache.get((path, os.path.getmtime(path)), [])
    kpis, charts, previews, seen = [], [], [], set()
    colors_used = 0
    # 1) KPIs: labelled single values (key/value cells), then "Total" rows of summary tables
    for t in [t for t in tables if t.get("compare")][:1]:
        for j in t["numeric"][:3]:
            tot = sum(_num(r[j]) or 0 for r in t["rows"])
            kpis.append({"label": "Total %s (all %d %ss)" % (t["columns"][j], len(t["rows"]), t["columns"][0].lower()),
                         "value": round(tot, 2), "context": "Sum of the section totals", "count": len(t["rows"])})
    for label, k, v in pairs:
        n = _num(v)
        if n is not None and len(kpis) < 8:
            kpis.append({"label": k, "value": round(n, 4 if abs(n) < 100 else 2), "context": label.replace("Sheet: ", "").split(" | Table: ")[0], "count": 1})
    for t in tables:
        for r in t["rows"]:
            if _is_total(r) and len(kpis) < 8:
                for j in [j for j in t["numeric"] if "%" not in t["columns"][j] and not _ID_COL.search(t["columns"][j])][:2]:
                    n = _num(r[j]) if j < len(r) else None
                    if n:
                        kpis.append({"label": "%s - %s" % (t["columns"][j].split(" / ")[-1], t["title"].replace("Sheet: ", "").split(" | Table: ")[-1]),
                                     "value": round(n, 2), "context": t["title"], "count": 1})
    # 1b) section comparison (towers / blocks): one chart per key measure, and skip the per-section
    #     floor-by-floor charts, which are not what a schedule dashboard is for.
    cmp_t = [t for t in tables if t.get("compare")]
    for t in cmp_t[:1]:
        picks = [j for j in t["numeric"] if re.search(r"gfa|bua|units|cost|amount|total", t["columns"][j], re.I)][:3] or t["numeric"][:3]
        for j in picks:
            sp = build_chart(t, "", {"x": 0, "y": [j], "chart": "pie" if re.search(r"units", t["columns"][j], re.I) else "bar"})
            if sp:
                sp["title"] = "%s by %s" % (re.sub(r"\s*\((sqm|sq m|m2)\)", " (m²)", t["columns"][j]).strip(), t["columns"][0])
                sp["sources"][0]["filename"] = os.path.basename(path)
                charts.append(sp); seen.add(("cmp", j))
    if cmp_t:
        sec_names = {str(r[0]).strip().upper() for r in cmp_t[0]["rows"]}
        _heads = set(cmp_t[0]["columns"][1:3])
        tables = [t for t in tables if t.get("compare") or (
            str(t.get("title") or "").split(" | Table: ")[-1].strip().upper() not in sec_names
            and not _heads <= set(t.get("columns") or []))]
    # 2) charts: summary tables first (few rows), then group-bys of detail tables
    order = sorted(tables, key=_importance)
    for t in order:
        if len(charts) >= max_charts:
            break
        if t.get("compare") and cmp_t:
            continue  # its measures were charted in step 1b
        ch = _dash_choice(t)
        if not ch:
            continue
        sig = (t["columns"][ch["x"]].split(" / ")[-1].lower(), tuple(t["columns"][j].lower() for j in ch["y"]), t.get("sheet") or t.get("page"))
        if sig in seen:
            continue
        q = "share breakdown" if (len(ch["y"]) == 1 and colors_used % 2 == 0) else ""
        spec = build_chart(t, q, ch)
        if not spec or len(spec.get("categories") or spec.get("data") or []) < 3:
            continue
        seen.add(sig)
        colors_used += 1
        spec["sources"][0]["filename"] = os.path.basename(path)
        spec["subtitle"] = spec["subtitle"].replace("Computed from ", "")
        charts.append(spec)
    # 3) registers / logs: count records by category (status, discipline, type...)
    for t in sorted([t for t in tables if len(t["rows"]) >= 10 and (t.get("records") or not t.get("numeric"))],
                    key=lambda t: (not t.get("records"), -len(t["rows"]))):
        for j in _category_cols(t)[:4]:
            if len(charts) >= max_charts:
                break
            sp = count_chart(t, j, "share" if colors_used % 3 == 1 else "")
            if sp:
                colors_used += 1
                sp["sources"][0]["filename"] = os.path.basename(path)
                charts.append(sp)
    # Same chart title from different sections: name the section so they can be told apart.
    _orig = [c["title"] for c in charts]
    for c, _ot in zip(charts, _orig):
        if _orig.count(_ot) > 1:
            src = str((c.get("sources") or [{}])[0].get("table") or "").replace("Sheet: ", "")
            sheet, _, sec = src.partition(" | Table: ")
            tag = sec if sec and sec != "all sections" else sheet
            if tag and " - " in tag and len(set(tag.split(" - "))) == 1:
                tag = tag.split(" - ")[0]
            if tag and tag.lower() not in _ot.lower():
                c["title"] = (_ot + " - " + tag)[:90]
    _seen = {}
    for c in charts:
        _seen[c["title"]] = _seen.get(c["title"], 0) + 1
        if _seen[c["title"]] > 1:
            c["title"] = "%s (%d)" % (c["title"], _seen[c["title"]])
    for t in sorted([t for t in tables if not t.get("combined")], key=_importance)[:6]:
        previews.append({"title": t["title"], "columns": t["columns"], "rows": t["rows"][:12], "total_rows": len(t["rows"])})
    return {"filename": os.path.basename(path), "kpis": kpis[:8], "charts": charts, "tables": previews,
            "table_count": len(tables), "built_in_s": round(time.time() - t0, 2)}


def chart_summary(spec):
    """One plain sentence describing the chart from its own (computed) values."""
    if spec.get("data"):
        items = [(d["name"], d["value"]) for d in spec["data"]]
    else:
        items = list(zip(spec.get("categories") or [], (spec.get("series") or [{}])[0].get("data") or []))
    if not items:
        return ""
    total = sum(v for _, v in items) or 1
    hi = max(items, key=lambda kv: kv[1]); lo = min(items, key=lambda kv: kv[1])
    f = lambda v: "{:,.2f}".format(v).rstrip("0").rstrip(".")
    return ("%s: %d items. Largest %s (%s, %.1f%% of total); smallest %s (%s). Values computed directly from %s."
            % (spec.get("title"), len(items), hi[0], f(hi[1]), 100.0 * hi[1] / total, lo[0], f(lo[1]),
               spec.get("subtitle", "").replace("Computed from ", "")))


# ---------------------------------------------------------------- follow-up edits
EDIT_HINT = re.compile(r"\b(label|labels|value|values|number|numbers|percent|percentage|%|sort|order|top|largest|smallest|highest|lowest|"
                       r"pie|donut|doughnut|bar|line|stack|stacked|chart|graph|title|rename|legend|remove|exclude|without|only|"
                       r"change|convert|switch|instead|make it|show|hide|add|also|include|compare|filter|limit)\b", re.I)


def _apply_ops(spec, ops):
    spec = json.loads(json.dumps(spec))
    is_pie = spec.get("chart_type") in ("pie", "donut")
    if is_pie:
        cats = [d["name"] for d in spec["data"]]
        series = [{"name": spec.get("title") or "Value", "data": [d["value"] for d in spec["data"]]}]
    else:
        cats, series = list(spec.get("categories") or []), spec.get("series") or []
    rows = list(zip(cats, *[s["data"] for s in series])) if series else []
    low = lambda v: str(v).strip().lower()
    all_rows = list(rows)
    if ops.get("exclude"):
        ex = {low(v) for v in ops["exclude"]}
        rows = [r for r in rows if low(r[0]) not in ex and not any(e and e in low(r[0]) for e in ex)]
    if ops.get("only"):
        keep = {low(v) for v in ops["only"]}
        sel = [r for r in rows if low(r[0]) in keep or any(k and k in low(r[0]) for k in keep)]
        rows = sel or rows
    if not rows:   # a filter that removes everything is a misunderstanding, not an edit
        rows = all_rows
    if ops.get("sort") in ("asc", "desc"):
        rows.sort(key=lambda r: r[1], reverse=ops["sort"] == "desc")
    try:
        n = int(ops.get("top_n") or 0)
        if n > 0:
            rows = sorted(rows, key=lambda r: -r[1])[:n] if ops.get("sort") != "asc" else rows[:n]
    except (TypeError, ValueError):
        pass
    ctype = ops.get("chart_type") or spec.get("chart_type")
    if ctype not in ("bar", "line", "pie", "donut", "stacked_bar"):
        ctype = spec.get("chart_type")
    if ctype in ("pie", "donut") and len(series) > 1:
        ctype = "bar"
    if ctype == "stacked_bar" and len(series) < 2:
        ctype = "bar"
    out = {k: spec.get(k) for k in ("title", "subtitle", "units", "sources", "table_id")}
    out["chart_type"] = ctype
    if ops.get("title"):
        out["title"] = str(ops["title"])[:90]
    out["legend"] = spec.get("legend", True) if ops.get("legend") is None else bool(ops["legend"])
    out["percentage"] = spec.get("percentage", False) if ops.get("percentage") is None else bool(ops["percentage"])
    if ctype in ("pie", "donut"):
        out["data"] = [{"name": r[0], "value": max(0.0, float(r[1]))} for r in rows]
    else:
        out["categories"] = [r[0] for r in rows]
        out["series"] = [{"name": s["name"], "data": [float(r[i + 1]) for r in rows]} for i, s in enumerate(series)]
    from intelligence.visualization_schema import validate_chart_spec
    ok, clean, err = validate_chart_spec(out)
    if not ok:
        return None, err
    clean["table_id"] = spec.get("table_id")
    clean["colors"] = _colors_for(spec, clean, ops)
    sn = ops.get("show_names")
    clean["show_names"] = spec.get("show_names") if sn is None else bool(sn)
    sv = ops.get("show_values")
    clean["show_values"] = spec.get("show_values") if sv is None else bool(sv)
    return clean, None


PALETTE = ["#2f6bff", "#35d07f", "#8a6cff", "#f5b73d", "#31d0c5", "#f2585f", "#ff8d3b", "#60a5fa", "#a78bfa", "#34d399"]
NAMED = {"blue": "#2f6bff", "green": "#35d07f", "purple": "#8a6cff", "violet": "#8a6cff", "yellow": "#f5b73d", "amber": "#f5b73d",
         "gold": "#f5b73d", "teal": "#31d0c5", "cyan": "#31d0c5", "red": "#f2585f", "orange": "#ff8d3b", "pink": "#ec4899",
         "grey": "#94a3b8", "gray": "#94a3b8", "white": "#e8eef7", "black": "#1f2937", "brown": "#a16207", "navy": "#1e3a8a",
         "lime": "#84cc16", "magenta": "#d946ef", "light blue": "#60a5fa", "dark green": "#15803d", "dark blue": "#1e40af"}
_ALT_PALETTES = [["#0ea5e9", "#f97316", "#22c55e", "#e11d48", "#a855f7", "#eab308", "#14b8a6", "#64748b", "#f472b6", "#84cc16"],
                 ["#1e40af", "#15803d", "#b45309", "#9f1239", "#6d28d9", "#0f766e", "#c2410c", "#334155", "#a21caf", "#4d7c0f"]]


def _to_hex(c):
    c = str(c or "").strip().lower()
    if re.match(r"^#[0-9a-f]{6}$", c):
        return c
    return NAMED.get(c)


def _colors_for(old, new, ops):
    names = [d["name"] for d in new.get("data") or []] or [s["name"] for s in new.get("series") or []]
    old_names = [d["name"] for d in old.get("data") or []] or [s["name"] for s in old.get("series") or []]
    old_cols = old.get("colors") or [PALETTE[i % len(PALETTE)] for i in range(len(old_names))]
    by_name = {n: old_cols[i] for i, n in enumerate(old_names) if i < len(old_cols)}
    cols = [by_name.get(n, PALETTE[i % len(PALETTE)]) for i, n in enumerate(names)]
    if ops.get("palette_shift"):
        pal = _ALT_PALETTES[(int(ops["palette_shift"]) - 1) % len(_ALT_PALETTES)]
        cols = [pal[i % len(pal)] for i in range(len(names))]
    for key, val in (ops.get("colors") or {}).items():
        hexv = _to_hex(val)
        if not hexv:
            continue
        kc = _to_hex(key)
        for i, n in enumerate(names):
            if (kc and cols[i].lower() == kc.lower()) or str(key).strip().lower() in str(n).lower():
                cols[i] = hexv
    return cols


def _rule_ops(instr):
    q = (instr or "").lower()
    ops = {}
    _off = re.search(r"\b(hide|remove|delete|without|no|turn off|clear)\b.*\b(label|labels|value|values|number|numbers)\b", q)
    if re.search(r"label|value|number|amount|figure", q) and not _off:
        ops["show_values"] = True
    if _off:
        ops["show_values"] = False
        ops["_labels_only"] = True
    if re.search(r"\b(name|names|category|categories|item names)\b", q):
        ops["show_names"] = not re.search(r"\b(hide|remove|without|no)\b.*\bname", q)
        if ops["show_names"]:
            ops.setdefault("show_values", True)
    if re.search(r"percent|%", q):
        ops["percentage"] = True
        ops.setdefault("show_values", True)
    for t, pat in (("donut", r"donut|doughnut"), ("pie", r"\bpie\b"), ("line", r"\bline\b|trend"), ("stacked_bar", r"stack"), ("bar", r"\bbar\b|column")):
        if re.search(pat, q):
            ops["chart_type"] = t
            break
    if re.search(r"descending|largest first|highest first|sort", q):
        ops["sort"] = "asc" if re.search(r"ascending|smallest first|lowest first", q) else "desc"
    m = re.search(r"\btop\s+(\d{1,2})\b", q)
    if m:
        ops["top_n"] = int(m.group(1))
    if re.search(r"hide (the )?legend|no legend", q):
        ops["legend"] = False
    cn = "|".join(sorted(map(re.escape, NAMED), key=len, reverse=True))
    m = re.search(r"\b(?:change|make|turn|set)?\s*(?:the\s+)?(%s|[a-z0-9 &/-]{2,40}?)\s+(?:slice|bar|colou?r)?\s*(?:to|into|as|=)\s+(%s|#[0-9a-f]{6})\b" % (cn, cn), q)
    m2 = re.search(r"\b(?:make|colou?r|paint)\s+(?:the\s+)?([a-z0-9 &/-]{2,40}?)\s+(%s)\b" % cn, q)
    if m and re.search(r"colou?r|%s" % cn, q):
        ops["colors"] = {m.group(1).strip(): m.group(2)}
    elif m2:
        ops["colors"] = {m2.group(1).strip(): m2.group(2)}
    elif re.search(r"colou?r", q):
        ops["palette_shift"] = 1 if not re.search(r"dark|deep", q) else 2
    return ops


def edit_chart(spec, instruction, original_question="", doc_paths=(), use_model=True):
    """Agentic follow-up on the last chart: decide whether the message edits it, then
    apply the edit in code (values never typed by the model). Returns dict."""
    low = (instruction or "").lower().strip()
    if re.search(r"\b(draw\s+a|create\s+a|generate\s+a|make\s+a\s+new|another\s+chart|from\s+the|from\s+sheet|from\s+table)\b", low):
        return {"is_edit": False}
    if any(k in low for k in ("budget", "zoning", "population", "residential", "commercial", "hospitality", "land use", "gfa")):
        cur_title = (spec.get("title") or "").lower()
        if "community" in cur_title and "community" not in low:
            return {"is_edit": False}
    cats = [d["name"] for d in spec.get("data") or []] or list(spec.get("categories") or [])
    series = [s["name"] for s in spec.get("series") or []]
    ops = None
    if use_model:
        try:
            prompt = ("The user is looking at a chart and sent a follow-up message. Decide what to do.\n"
                      "Chart: type=%s; title=%s; items=%s; series=%s\nOriginal request: %s\nFollow-up: %s\n\n"
                      "Reply with JSON only: {\"is_edit\": true/false (false if the follow-up is a new, unrelated question), "
                      "\"needs_new_data\": true/false (true only if it asks for a different measure, column, sheet or grouping), "
                      "\"chart_type\": \"bar|line|pie|donut|stacked_bar\" or null, \"show_values\": true/false/null, "
                      "\"percentage\": true/false/null, \"sort\": \"asc|desc\" or null, \"top_n\": number or null, "
                      "\"exclude\": [item names] or [], \"only\": [item names] or [], \"title\": text or null, \"legend\": true/false/null, \"show_names\": true/false/null (item names written on the chart), "
                      "\"colors\": {\"<item name or current colour name>\": \"<new colour name or #hex>\"} or {}, \"palette_shift\": 1 or null (for 'change the colours'), "
                      "\"reply\": \"one short sentence saying what you changed\"}"
                      % (spec.get("chart_type"), spec.get("title"), "; ".join(map(str, cats[:30])), "; ".join(series),
                         original_question, instruction))
            ops = _ollama_json(prompt, timeout=45)
        except Exception:
            ops = None
    rule = _rule_ops(instruction)
    if not ops:
        if not rule:
            return {"is_edit": False}
        ops = dict(rule, is_edit=True)
    else:
        for k, v in rule.items():   # explicit words win over the model's reading
            if k in ("show_values", "show_names", "colors", "palette_shift") or ops.get(k) in (None, [], "", {}):
                ops[k] = v
        if rule.get("_labels_only"):
            # "remove the labels" is about the value labels, never about removing items
            ops["exclude"], ops["only"] = [], []
    if not ops.get("is_edit"):
        return {"is_edit": False}
    if ops.get("needs_new_data") and doc_paths:
        new_q = (original_question + " " + instruction).strip()
        sp = chart_for_question(new_q, list(doc_paths), use_model=use_model)
        if sp:
            sp, _ = _apply_ops(sp, {k: ops.get(k) for k in ("chart_type", "show_values", "percentage", "sort", "top_n", "legend", "title")})
            if sp:
                return {"is_edit": True, "spec": sp, "question": new_q,
                        "reply": ops.get("reply") or "Rebuilt the chart from the file for: " + new_q}
    sp, err = _apply_ops(spec, ops)
    if sp and ops.get("colors"):
        n_used = len(spec.get("data") or []) or len(spec.get("series") or [])
        old_cols = [c.lower() for c in (spec.get("colors") or PALETTE)][:max(1, n_used)]
        names = [str(d.get("name", "")).lower() for d in spec.get("data") or []] or [str(x).lower() for x in spec.get("categories") or []] + [str(x.get("name", "")).lower() for x in spec.get("series") or []]
        missing = [k for k in ops["colors"] if (_to_hex(k) and _to_hex(k).lower() not in old_cols) or (not _to_hex(k) and not any(str(k).lower() in n for n in names))]
        if missing:
            ops["reply"] = "There is no %s on this chart, so nothing was recoloured. Try naming an item, e.g. 'make Residential red'." % ", ".join(map(str, missing))
    if not sp:
        return {"is_edit": True, "error": "I could not apply that change to the chart. Try e.g. 'show values', 'make it a bar chart' or 'only top 5'."}
    return {"is_edit": True, "spec": sp, "question": original_question,
            "reply": ops.get("reply") or "Updated the chart."}
