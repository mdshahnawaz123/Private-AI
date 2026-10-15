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
_ID_COL = re.compile(r"\b(id|no\.?|number|plot|code|ref|year|date|item)\b", re.I)
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
        out.extend(found)
    return out


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
                    for k, tb in enumerate(page.find_tables().tables, 1):
                        grid = [[re.sub(r"\s+", " ", str(c or "")).strip() for c in row] for row in tb.extract()]
                        ocr_pages.setdefault(i, []).append(("", grid))
                except Exception:
                    continue
    except Exception:
        pass
    for page, items in sorted(ocr_pages.items(), key=lambda kv: (kv[0] is None, kv[0])):
        for cap, grid in items:
            found = []
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
    # One combined table per sheet when its sections share the same columns
    # (e.g. "Proposed Residential", "Proposed Commercial" ... blocks of one plot schedule).
    by_sheet = {}
    for t in tables:
        if t.get("sheet"):
            by_sheet.setdefault((t["sheet"], tuple(c.lower() for c in t["columns"])), []).append(t)
    for (sheet, _), group in by_sheet.items():
        if len(group) >= 2:
            tables.append({"title": "Sheet: %s | Table: all sections" % sheet, "columns": list(group[0]["columns"]),
                           "rows": [r for g in group for r in g["rows"]], "sheet": sheet, "page": sheet, "combined": True})
    _pairs_cache[key] = [p for t in found for p in (t.get("pairs") or [])]
    tables = _split_side_by_side(tables)
    for i, t in enumerate(tables):
        t["id"] = i
        t["serial"] = [j for j in range(len(t["columns"])) if _serial_col(t, j)]
        t["numeric"] = [j for j, c in enumerate(t["columns"]) if _numeric_col(t, j) and j not in t["serial"]]
    _cache[key] = tables
    return tables


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
    # 2) charts: summary tables first (few rows), then group-bys of detail tables
    order = sorted(tables, key=_importance)
    for t in order:
        if len(charts) >= max_charts:
            break
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
