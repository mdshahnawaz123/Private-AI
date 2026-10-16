"""Verified answer agent for the local model (plan -> tools -> answer -> verify -> retry).

Same working principle as Claude's agent loop, scaled to qwen3.5:9b:
  1. the model reads the question and decides which tool to call (Ollama native tool calling);
  2. tools return REAL evidence: document search, tables read from the file, sandboxed
     calculations, charts computed from cells, page images read by the vision model;
  3. the model drafts an answer from that evidence only;
  4. code verifies the draft: every number must appear in a tool result (or be a
     re-computed value), facts need citations, chart requests need a chart;
  5. on failure the model gets the exact problem back and tries again (max 2 repairs);
     if it still cannot verify, the answer says what could not be confirmed.
The model never supplies the numbers - tools do.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time

from loguru import logger

MAX_STEPS = int(os.getenv("EXPO_AGENT_MAX_STEPS", "7"))
MAX_REPAIRS = 2
TOOL_TEXT_LIMIT = 7000

SYSTEM = """You are Expo Design AI, a careful engineering document assistant working with TOOLS.
Work like this, every time:
1. Decide what the question needs. Use tools to get evidence - never answer facts or numbers from memory.
2. search_documents finds text, pages and table rows. For spreadsheets or big tables use list_tables then read_table.
3. For totals, averages, counts, max/min over a sheet use the aggregate tool (whole sheet, filtered by a column value).
   For other calculations (differences, ratios, percentages of rows) use run_python - never do arithmetic yourself.
   In run_python, filter on the column that holds the row names (often 'Description', not the ITEM number column); an empty result means you used the wrong column - check the column list. For areas, report SQ.M. first and SQ.FT. after it when both exist.
   If the document already states the value (e.g. "SITEWIDE FAR", "TOTAL GFA", a Total row), quote it - do not recompute it.
   Never add up ratios, percentages or FAR values across rows.
4. For "chart / graph / plot / pie / dashboard" requests call make_chart (it draws from the file's cells).
5. For figures, maps, drawings or colours use look_at_page.
6. Then write the final answer: short, direct, values with units exactly as in the tool results, and a citation
   after each fact in the form [SOURCE: <file> | PAGE <page or sheet>] copied from the tool results.
8. For CAD drawings (.dxf/.dwg), floor plans, layers, dimensions or requests to draft or inspect in CADCraft, use cad_inspect or cad_draft. For a built-in CADCraft sample call cad_inspect with drawing_name 'sample apartment' / 'sample core' / 'sample bracket'. Never describe a drawing you have not inspected.
Do not call the same tool with the same arguments twice. Use at most 5 tool calls.
You only answer from this project's documents: for jokes, general knowledge or other projects, say briefly that you can only answer from the uploaded project documents.
If asked to answer with only a number, reply with just the number and its citation.
Answer in plain, short sentences. No apologies, no description of your search process, no comments about verification."""

TOOLS = [
    {"type": "function", "function": {"name": "search_documents",
     "description": "Search the project's documents (PDF text, OCR text, table rows, sheet rows). Returns excerpts with [SOURCE: file | PAGE p] markers.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "what to look for"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "list_tables",
     "description": "List tables found in the project's Excel sheets and PDF pages (id, file, sheet/page, title, columns, row count). Optional keyword filter.",
     "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "read_table",
     "description": "Read rows of one table by id (from list_tables). Optional text filter keeps rows containing it.",
     "parameters": {"type": "object", "properties": {"table_id": {"type": "integer"}, "filter": {"type": "string"}, "max_rows": {"type": "integer"}},
                    "required": ["table_id"]}}},
    {"type": "function", "function": {"name": "run_python",
     "description": "Run a short pandas calculation on tables. Tables are DataFrames in T[<table_id>] with numbers already converted (percent cells as fractions). pd, math, statistics available. No imports. print() the result with labels.",
     "parameters": {"type": "object", "properties": {"table_ids": {"type": "array", "items": {"type": "integer"}}, "code": {"type": "string"}},
                    "required": ["table_ids", "code"]}}},
    {"type": "function", "function": {"name": "aggregate",
     "description": "Exact total/average/count/max/min of a numeric column over a WHOLE sheet or table, optionally filtered (e.g. sum of LAND AREA where LAND USE = Commercial in sheet AFTER). Computed by code - prefer this over run_python for totals.",
     "parameters": {"type": "object", "properties": {"op": {"type": "string", "enum": ["sum", "avg", "count", "max", "min"]},
        "column": {"type": "string"}, "where_column": {"type": "string"}, "where_value": {"type": "string"},
        "sheet": {"type": "string", "description": "sheet name (e.g. AFTER) or table_id"}}, "required": ["op", "column"]}}},
    {"type": "function", "function": {"name": "make_chart",
     "description": "Draw a chart from the file's cells. Describe it in words, e.g. 'pie chart of total GFA by land use in the AFTER sheet'.",
     "parameters": {"type": "object", "properties": {"request": {"type": "string"}}, "required": ["request"]}}},
    {"type": "function", "function": {"name": "look_at_page",
     "description": "Show one PDF page (or the uploaded image) to the vision model and ask a question about figures, maps, drawings, legends or colours.",
     "parameters": {"type": "object", "properties": {"file": {"type": "string"}, "page": {"type": "integer"}, "question": {"type": "string"}},
                    "required": ["question"]}}},
    {"type": "function", "function": {"name": "cad_inspect",
     "description": "Inspect a CAD drawing or CADCraft architectural model (.dxf, .dwg, apartment, core, bracket). Returns layers, dimensions, bounding extents, room names, and entity statistics.",
     "parameters": {"type": "object", "properties": {"drawing_name": {"type": "string", "description": "CAD filename or sample name (e.g. apartment, core, bracket)"}}}}},
    {"type": "function", "function": {"name": "cad_draft",
     "description": "Draft or redesign an architectural 2D CAD floor plan or column grid into CADCraft Studio. Saves the drawing into project Drawings and gives the user an interactive CADCraft opening button.",
     "parameters": {"type": "object", "properties": {
         "plan_type": {"type": "string", "enum": ["apartment", "core", "bracket"], "description": "Type of architectural plan to draft"},
         "filename": {"type": "string", "description": "Destination DXF filename, e.g. proposed_layout.dxf"},
         "title": {"type": "string", "description": "Human-readable drawing title"}
     }, "required": ["plan_type", "filename"]}}},
]

_NUM = re.compile(r"(?<![A-Za-z0-9_.])[-+]?\d[\d,]*(?:\.\d+)?%?")
_MARK = re.compile(r"\[(?:Citation:\s*)?SOURCE:[^\]]*\]", re.I)
# Figure questions (not charts: "plot 5211017" is a land plot, "chart" is a request for a chart).
_FIG = re.compile(r"\b(figure|fig\.|diagram|map|drawing|image|photo(?:graph)?|legend|colou?r(?:ed)?|shown in (?:blue|green|red))\b", re.I)
ABSTAIN = re.compile(r"could not find|not (?:in|contained in) the (?:uploaded )?documents", re.I)


def _nums(text):
    out = set()
    for m in _NUM.findall(_MARK.sub(" ", text or "")):
        s = m.replace(",", "").rstrip("%")
        try:
            v = float(s)
        except ValueError:
            continue
        out.add(round(v, 2))
    return out


def _supported(v, evidence_nums):
    if v in evidence_nums or abs(v) < 10 and float(v).is_integer():
        return True        # small whole numbers (counts, list numbering, "Table 6") are not checked
    for e in evidence_nums:
        if e and abs(v - e) <= max(0.011, abs(e) * 0.0005):
            return True
        if e and abs(v - e * 100) <= 0.06:          # 0.3706 shown as 37.06%
            return True
    return False



def _text_tool_calls(text):
    """Parse '<tool_call><function=name><parameter=k>v</parameter></function></tool_call>'
    or '<tool_call>{"name":..,"arguments":{..}}</tool_call>' blocks into Ollama tool_calls."""
    out = []
    for blk in re.findall(r"(?s)<tool_call>(.*?)(?:</tool_call>|$)", text or ""):
        m = re.search(r"<function=([\w\-]+)>", blk)
        if m:
            args = {}
            for k, v in re.findall(r"(?s)<parameter=([\w\-]+)>\s*(.*?)\s*</parameter>", blk):
                v = v.strip()
                if re.fullmatch(r"-?\d+", v):
                    v = int(v)
                args[k] = v
            out.append({"function": {"name": m.group(1), "arguments": args}})
            continue
        try:
            j = json.loads(blk.strip())
            out.append({"function": {"name": j.get("name"), "arguments": j.get("arguments") or j.get("parameters") or {}}})
        except Exception:
            pass
    return [c for c in out if c["function"].get("name")]

class Agent:
    def __init__(self, project, user, question, docs, retrieve_fn, chat_url, model, history=None):
        self.project, self.user, self.q = project, user, question
        self.docs = docs                       # accessible ready documents (dicts with filename, path)
        self.retrieve = retrieve_fn
        self.url, self.model = chat_url.rstrip("/"), model
        self.history = history or []
        self.evidence = []                     # text of every tool result
        self.sources = []                      # source dicts from search
        self.charts = []
        self.tables = None
        self.calls = set()
        self.trace = []
        self.read_rows = []                    # (columns, row) of every table row the agent has read

    # ------------------------------------------------------------ tools
    def _paths(self, exts=(".xlsx", ".xlsm", ".xls", ".pdf")):
        return [d["path"] for d in self.docs if str(d.get("path", "")).lower().endswith(exts) and os.path.isfile(d["path"])]

    def _all_tables(self):
        if self.tables is None:
            from services import dataviz
            self.tables = []
            for p in self._paths()[:6]:
                for t in dataviz.tables_for(p):
                    self.tables.append(dict(t, file=os.path.basename(p)))
            for i, t in enumerate(self.tables):
                t["gid"] = i
        return self.tables

    def t_search_documents(self, query=""):
        srcs, ctx = self.retrieve(query or self.q)
        for s in srcs or []:
            if isinstance(s, dict) and s not in self.sources:
                self.sources.append(s)
        return ctx or "(no results)"

    def t_list_tables(self, keyword=""):
        kw = (keyword or "").lower().split()
        rows = []
        for t in sorted(self._all_tables(), key=lambda t: not t.get("combined")):
            label = "%s %s" % (t["title"], " ".join(t["columns"]))
            if kw and not any(k in label.lower() for k in kw):
                continue
            rows.append("table_id=%d | %s | %s%s | %d rows | columns: %s" % (
                t["gid"], t["file"], t["title"].replace("Sheet: ", "sheet "), "  <-- WHOLE SHEET: use for totals/filters" if t.get("combined") else "",
                len(t["rows"]), "; ".join(t["columns"])[:400]))
        facts = []
        from services import dataviz
        for p in self._paths()[:6]:
            try:
                key = (p, os.path.getmtime(p))
                for label, k, v in dataviz._pairs_cache.get(key, []):
                    if not kw or any(x in (label + " " + k).lower() for x in kw):
                        facts.append("fact | [SOURCE: %s | PAGE %s] %s = %s" % (os.path.basename(p), label.replace("Sheet: ", "").split(" | ")[0], k, v))
            except OSError:
                pass
        out = "\n".join(rows[:30])
        if facts:
            out += "\n\nSingle labelled values (already final - quote them, do not recompute):\n" + "\n".join(facts[:30])
        return out or "(no tables match - try another keyword or none)"

    def t_read_table(self, table_id=0, filter="", max_rows=60):
        ts = self._all_tables()
        try:
            t = ts[int(table_id)]
        except (ValueError, IndexError, TypeError):
            return "ERROR: unknown table_id"
        rows = t["rows"]
        if filter:
            f = str(filter).lower()
            rows = [r for r in rows if any(f in str(c).lower() for c in r)] or rows
        rows = rows[: max(1, min(int(max_rows or 60), 120))]
        self.read_rows.extend((t["columns"], r) for r in rows)
        page = t.get("page")
        head = "[SOURCE: %s | PAGE %s] %s (%d of %d rows)" % (t["file"], page, t["title"], len(rows), len(t["rows"]))
        self.sources.append({"source": t["file"], "filename": t["file"], "page": page})
        return head + "\n" + " | ".join(t["columns"]) + "\n" + "\n".join(" | ".join(map(str, r)) for r in rows)

    def t_run_python(self, table_ids=None, code=""):
        ts = self._all_tables()
        job = {"code": code, "tables": {}}
        cites = []
        for tid in (table_ids or [])[:4]:
            try:
                t = ts[int(tid)]
            except (ValueError, IndexError, TypeError):
                return "ERROR: unknown table_id %s" % tid
            job["tables"][str(int(tid))] = {"title": t["title"], "columns": t["columns"], "rows": t["rows"]}
            cites.append("[SOURCE: %s | PAGE %s]" % (t["file"], t.get("page")))
            self.sources.append({"source": t["file"], "filename": t["file"], "page": t.get("page")})
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(job, fh)
        try:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            done = subprocess.run([sys.executable, "-m", "services.agent_sandbox", path], cwd=root,
                                  capture_output=True, text=True, timeout=25)
            out = (done.stdout or "").strip() or ("ERROR: " + (done.stderr or "")[-300:])
        except subprocess.TimeoutExpired:
            out = "ERROR: calculation took too long"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        return "Computed from " + ", ".join(cites) + ":\n" + out

    def _find_col(self, t, name):
        n = (name or "").strip().lower()
        if not n:
            return None
        cols = [c.lower() for c in t["columns"]]
        for j, c in enumerate(cols):
            if c == n or c.split(" / ")[-1] == n:
                return j
        for j, c in enumerate(cols):
            if n in c:
                return j
        return None

    def t_aggregate(self, op="sum", column="", where_column="", where_value="", sheet=""):
        from services.dataviz import _num, _is_total
        ts = self._all_tables()
        cands = []
        if str(sheet).strip().isdigit() and int(sheet) < len(ts):
            cands = [ts[int(sheet)]]
        else:
            sh = str(sheet or "").lower().strip()
            cands = [t for t in ts if (not sh or sh in str(t.get("page", "")).lower() or sh in t["title"].lower())]
            cands.sort(key=lambda t: (not t.get("combined"), -len(t["rows"])))
        for t in cands:
            j = self._find_col(t, column)
            if j is None or j not in t["numeric"]:
                continue
            wj = self._find_col(t, where_column) if where_column else None
            if where_column and wj is None:
                continue
            wv = str(where_value or "").strip().lower()
            vals = []
            for r in t["rows"]:
                if _is_total(r):
                    continue
                if wj is not None and wv and str(r[wj]).strip().lower() != wv:
                    continue
                v = _num(r[j]) if j < len(r) else None
                if v is not None:
                    vals.append(v)
            if not vals and wj is not None:
                continue
            res = {"sum": sum(vals), "avg": (sum(vals) / len(vals)) if vals else 0, "count": len(vals),
                   "max": max(vals) if vals else 0, "min": min(vals) if vals else 0}.get(op, sum(vals))
            self.sources.append({"source": t["file"], "filename": t["file"], "page": t.get("page")})
            unit = self._unit(t["columns"][j])
            return ("[SOURCE: %s | PAGE %s] %s of %s%s over %d rows%s = %s%s (computed by code from the whole table)"
                    % (t["file"], t.get("page"), op, t["columns"][j], (" where %s = %s" % (t["columns"][wj], where_value)) if wj is not None else "",
                       len(vals), "", ("%.2f" % res).rstrip("0").rstrip(".") if op != "count" else res, (" " + unit) if unit and op != "count" else ""))
        return "ERROR: no table has a numeric column '%s'%s - check list_tables" % (column, (" and column '%s'" % where_column) if where_column else "")

    @staticmethod
    def _unit(col):
        c = col.lower()
        m = re.search(r"\(([^)]{1,10})\)", col)
        if m:
            return m.group(1)
        if re.search(r"\b(area|gfa|bua|nsa)\b", c):
            return "m²"
        return ""

    def lookup_ids(self):
        """Exact rows for plot numbers / IDs named in the question (code, not the model)."""
        ids = re.findall(r"(?<![\d.])(\d{6,8}|[A-Z]{2}\.\d{2}\.[A-Z]\.\d{2})(?![\d.])", self.q)
        out = []
        for pid in ids[:3]:
            for t in self._all_tables():
                if t.get("combined"):
                    continue
                for r in t["rows"]:
                    if pid in [str(c).strip() for c in r]:
                        pairs = "; ".join("%s: %s%s" % (c, v, (" " + self._unit(c)) if self._unit(c) and re.match(r"^[\d.,]+$", str(v)) else "")
                                          for c, v in zip(t["columns"], r) if v)
                        out.append("[SOURCE: %s | PAGE %s] %s | %s" % (t["file"], t.get("page"), t["title"], pairs))
                        self.sources.append({"source": t["file"], "filename": t["file"], "page": t.get("page")})
        return "\n".join(out[:8])

    def list_matches(self):
        """'Which ... <value>' questions: every row in the named table holding that value (code)."""
        if not re.search(r"\b(which|list|all|every)\b", self.q, re.I):
            return ""
        vals = re.findall(r"(?<!table )(?<!figure )(?<!page )(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])", self.q.lower())
        if not vals:
            return ""
        val = vals[-1]
        tm = re.search(r"\btable\s*(\d+)", self.q, re.I)
        out = []
        for t in self._all_tables():
            if tm and not re.search(r"\btable\s*%s\b" % tm.group(1), t["title"], re.I):
                continue
            for r in t["rows"]:
                if any(re.match(r"^\s*%s(?![\d.])" % re.escape(val), str(c)) for c in r):
                    out.append("[SOURCE: %s | PAGE %s] %s" % (t["file"], t.get("page"), "; ".join("%s: %s" % (c, v) for c, v in zip(t["columns"], r) if v)))
                    self.read_rows.append((t["columns"], r))
        if not out:
            return ""
        return "COMPLETE list of rows containing %s (found by code - include ALL of them):\n" % val + "\n".join(out[:25])

    def auto_aggregate(self):
        """'total/average/number/largest <column> of <value> plots in <sheet>' -> computed by code up front."""
        q = self.q.lower()
        op = ("avg" if re.search(r"\baverage|\bmean", q) else "count" if re.search(r"\bhow many|\bnumber of|\bcount", q)
              else "max" if re.search(r"\blargest|\bhighest|\bmaximum|\bbiggest", q) else "min" if re.search(r"\bsmallest|\blowest|\bminimum", q)
              else "sum" if re.search(r"\btotal|\bsum\b|\bcombined|\boverall", q) else None)
        if not op:
            return ""
        best = None
        for t in self._all_tables():
            if not t.get("combined"):
                continue
            sheet = str(t.get("page") or "")
            if re.search(r"\b(after|before)\b", q) and sheet.lower() not in q:
                continue
            col = None
            for j in t["numeric"]:
                name = t["columns"][j].split(" / ")[-1].lower()
                full = t["columns"][j].lower()
                if name and (name in q or full in q):
                    if col is None or len(name) > len(t["columns"][col].split(" / ")[-1]):
                        col = j
            if col is None:
                continue
            where = None
            for j in range(len(t["columns"])):
                if j in t["numeric"]:
                    continue
                vals = {str(r[j]).strip() for r in t["rows"] if j < len(r) and r[j]}
                if not 2 <= len(vals) <= 40:
                    continue
                for v in sorted(vals, key=len, reverse=True):
                    if len(v) >= 3 and re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(v.lower()), q):
                        where = (t["columns"][j], v)
                        break
                if where:
                    break
            best = (t, col, where)
            break
        if not best:
            return ""
        t, col, where = best
        return self.t_aggregate(op, t["columns"][col], where[0] if where else "", where[1] if where else "", str(t["gid"]))

    def small_table_rows(self):
        """Rows of small summary tables whose label is named in the question (e.g. 'proposed commercial GFA')."""
        q = self.q.lower()
        out = []
        for t in self._all_tables():
            if t.get("combined") or len(t["rows"]) > 40:
                continue
            for r in t["rows"]:
                labels = [str(c) for c in r if c and not re.match(r"^[-\d.,%\s]+$", str(c))]
                if any(len(l) >= 4 and re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(l.lower()), q) for l in labels[:2]):
                    out.append("[SOURCE: %s | PAGE %s] %s | %s" % (t["file"], t.get("page"), t["title"],
                               "; ".join("%s: %s" % (c, v) for c, v in zip(t["columns"], r) if v)))
                    self.sources.append({"source": t["file"], "filename": t["file"], "page": t.get("page")})
        return "\n".join(out[:12])

    def t_make_chart(self, request=""):
        from services import dataviz
        spec = dataviz.chart_for_question(request or self.q, self._paths()[:3])
        if not spec:
            return "No chart could be built from the tables for that request."
        self.charts.append(spec)
        src = spec.get("sources", [{}])[0]
        return "Chart drawn and shown to the user. [SOURCE: %s | PAGE %s] %s" % (
            src.get("filename"), src.get("page"), dataviz.chart_summary(spec))

    def t_look_at_page(self, file="", page=None, question=""):
        from intelligence import page_vision as pv
        cand = [d for d in self.docs if file and os.path.basename(d["path"]).lower() == os.path.basename(file).lower()] or self.docs
        for d in cand[:3]:
            p = d["path"]
            if p.lower().endswith(".pdf"):
                pages = [int(page)] if page else pv.candidate_pages(p, self.sources, question or self.q)
                if not pages:
                    continue
                pg, ans = pv.answer_from_pages(question or self.q, p, pages)
                if ans:
                    return "[SOURCE: %s | PAGE %s] (read from the page image, not text-verified)\n%s" % (os.path.basename(p), pg, ans)
            elif pv and hasattr(pv, "answer_from_image") and re.search(r"\.(png|jpe?g|webp|bmp|tiff?)$", p, re.I):
                ans = pv.answer_from_image(question or self.q, p)
                if ans:
                    return "[SOURCE: %s | PAGE 1] (read from the image)\n%s" % (os.path.basename(p), ans)
        return "The page images did not show the answer."

    def t_cad_inspect(self, drawing_name=""):
        from services.cad_service import CadService
        target_name = (drawing_name or "").strip()
        low = target_name.lower()

        # Built-in CADCraft samples only when the user explicitly asks for a sample -
        # never as a stand-in for a project drawing.
        sample_id = None
        if low.startswith("sample") or "sample" in low.split() or "sample" in self.q.lower():
            for k, v in (("cadcraft", "sample_cadcraft_apartment"), ("apartment", "sample_cadcraft_apartment"),
                         ("core", "sample_structural_core"), ("grid", "sample_structural_core"),
                         ("bracket", "sample_mechanical_bracket"), ("2bed", "sample_apartment_plan")):
                if k in low:
                    sample_id = v
                    break
            if low.startswith("sample_") and low in ("sample_cadcraft_apartment", "sample_apartment_plan", "sample_structural_core", "sample_mechanical_bracket"):
                sample_id = low
        if sample_id:
            data = CadService.load_sample_drawing(sample_id)
            layers_summary = ", ".join(l["name"] for l in data.get("layers", []))
            ext = data.get("extents", {})
            dim_texts = [e.get("text", "") for e in data.get("entities", []) if e.get("type") == "DIMENSION"]
            room_names = [e.get("text", "") for e in data.get("entities", []) if e.get("type") == "TEXT"]
            res = (
                f"[SOURCE: CADCraft sample {data.get('title')} | CAD Model Space]\n"
                f"NOTE: this is a built-in CADCraft SAMPLE drawing, not a project document.\n"
                f"Drawing Title: {data.get('title')}\n"
                f"Extents: {ext.get('width', 0)} x {ext.get('height', 0)} mm\n"
                f"Total Entities: {data.get('entity_count')}\n"
                f"Layers: {layers_summary}\n"
            )
            if room_names:
                res += f"Spaces / Labels: {', '.join(room_names)}\n"
            if dim_texts:
                res += f"Key Dimensions: {', '.join(dim_texts[:8])}\n"
            res += f"\n[Open in CADCraft Studio](cadcraft:{sample_id})"
            return res

        # Only drawings this user may see (self.docs is already permission-filtered).
        cands = [d for d in self.docs if str(d.get("path", "")).lower().endswith((".dxf", ".dwg"))
                 and os.path.isfile(d.get("path", ""))]
        if target_name:
            cands = [d for d in cands if low in d.get("filename", "").lower()] or \
                    [d for d in cands if any(w in d.get("filename", "").lower() for w in re.findall(r"[a-z0-9]{3,}", low))]
        if not cands:
            return (f"No CAD drawing matching '{drawing_name}' was found among the drawings you can access in project "
                    f"'{self.project}'. (Built-in samples: apartment, core, bracket - ask for a 'sample' to see one.)")
        d = cands[0]
        fname = d.get("filename") or os.path.basename(d["path"])
        if fname.lower().endswith(".dwg"):
            try:
                from services.cad_api import _load_or_convert_dwg
                from engines.cad_engine import CadIntelligenceEngine
                data = _load_or_convert_dwg(CadIntelligenceEngine(), d["path"], fname)
            except Exception as e:
                return f"Could not read DWG {fname}: {e}"
            if data.get("dwg_fallback"):
                return f"{fname} is a DWG that could not be converted (ODA File Converter unavailable). Save it as DXF to inspect it."
        else:
            try:
                data = CadService.parse_dxf_stream(d["path"])
            except Exception as e:
                return f"Error reading CAD drawing {fname}: {e}"
        ext = data.get("extents", {}) or {}
        room_names = [e.get("text", "") for e in data.get("entities", []) if e.get("type") == "TEXT" and e.get("text")]
        dims = [e.get("text", "") for e in data.get("entities", []) if e.get("type") == "DIMENSION" and e.get("text")]
        res = (
            f"[SOURCE: {fname} | CAD Model Space]\n"
            f"File: {fname}\n"
            f"Extents: {float(ext.get('width', 0) or 0):.0f} x {float(ext.get('height', 0) or 0):.0f} drawing units\n"
            f"Entities: {data.get('entity_count')} ({', '.join(f'{k}:{v}' for k, v in (data.get('entity_types') or {}).items())})\n"
            f"Layers: {', '.join(l['name'] for l in data.get('layers', []))}\n"
        )
        if room_names:
            res += f"Labels: {', '.join(room_names[:40])}\n"
        if dims:
            res += f"Dimensions: {', '.join(dims[:20])}\n"
        res += f"\n[Open in CADCraft Studio](cadcraft:{fname})"
        self.sources.append({"source": fname, "filename": fname, "page": 1})
        return res

    def t_cad_draft(self, plan_type="apartment", filename="", title=""):
        from services.cad_service import CadService
        import db
        from config import get_settings
        settings = get_settings()
        role = (self.user or {}).get("role") if isinstance(self.user, dict) else getattr(self.user, "role", None)
        if role not in ("admin", "lead", "user"):
            return "You do not have permission to save drawings in this project."

        sample_id = "sample_cadcraft_apartment"
        pt = (plan_type or "").lower()
        if "core" in pt or "grid" in pt or "struct" in pt:
            sample_id = "sample_structural_core"
        elif "bracket" in pt or "mech" in pt:
            sample_id = "sample_mechanical_bracket"
        elif "2bed" in pt or "residential" in pt:
            sample_id = "sample_apartment_plan"
        elif "apartment" in pt or "master" in pt or "cadcraft" in pt:
            sample_id = "sample_cadcraft_apartment"
        data = CadService.load_sample_drawing(sample_id)

        base = os.path.basename((filename or "").replace("\\", "/"))
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or sample_id
        if not base.lower().endswith(".dxf"):
            base += ".dxf"
        target_dir = os.path.join(settings.data_dir, "docs", self.project, "Drawings")
        os.makedirs(target_dir, exist_ok=True)
        stem, n, out_filename = base[:-4], 2, base
        while os.path.exists(os.path.join(target_dir, out_filename)):   # never overwrite an existing drawing
            out_filename, n = "%s_%d.dxf" % (stem, n), n + 1
        file_path = os.path.join(target_dir, out_filename)
        if os.path.dirname(os.path.realpath(file_path)) != os.path.realpath(target_dir):
            return "Invalid drawing filename."

        draw_title = (title or "").strip() or data.get("title", "CADCraft Design")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(CadService.generate_dxf(data["entities"], data["layers"], title=draw_title))
        try:
            folders = db.list_folders(self.project)
            fo = next((x for x in folders if str(x.get("name", "")).lower() == "drawings"), None)
            fid = fo["id"] if fo else (lambda r: r["id"] if isinstance(r, dict) else int(r))(db.create_folder(self.project, "Drawings"))
            u_obj = self.user if (isinstance(self.user, dict) and "id" in self.user) else None
            if not u_obj:
                uname = (self.user or {}).get("username") if isinstance(self.user, dict) else "admin"
                u_obj = db.get_user_by_username(uname) or db.SYSTEM_USER
            db.record_document(project=self.project, filename=out_filename, path=file_path, chunks=0,
                               discipline="Architectural", status="ready", folder_id=fid, user=u_obj)
        except Exception as e:
            logger.warning("cad_draft: saved {} but could not register it: {}", out_filename, e)

        self.sources.append({"source": f"Drawings/{out_filename}", "filename": out_filename, "page": 1})
        return (
            f"Saved a CADCraft TEMPLATE drawing (built from the '{sample_id}' sample, not a custom design) as "
            f"Drawings/{out_filename}. Tell the user it is a starting template they can edit.\n"
            f"[SOURCE: Drawings/{out_filename} | CAD Model Space]\n"
            f"Drawing: {draw_title} ({data.get('entity_count')} entities, {len(data.get('layers', []))} layers).\n"
            f"[Open in CADCraft Studio](cadcraft:{out_filename})"
        )

    # ------------------------------------------------------------ model
    def _chat(self, messages, tools=True):
        import httpx
        body = {"model": self.model, "messages": messages, "stream": False, "think": False,
                "options": {"temperature": 0.1, "num_ctx": 16384}}
        if tools:
            body["tools"] = TOOLS
        r = httpx.post(self.url + "/api/chat", json=body, timeout=180)
        r.raise_for_status()
        return r.json().get("message") or {}

    def _verify(self, answer):
        issues = []
        if not answer.strip():
            return ["empty answer"]
        if ABSTAIN.search(answer):
            used = {t.get("tool") for t in self.trace if t.get("tool")}
            try:
                FIGURE_Q = _FIG
                if FIGURE_Q.search(self.q) and not ({"look_at_page", "cad_inspect", "cad_draft"} & used):
                    return ["before saying not found, call look_at_page - figures are often only visible in the page image"]
            except Exception:
                pass
            return []
        ev = _nums("\n".join(self.evidence))
        bad = sorted({v for v in _nums(answer) if not _supported(v, ev)})
        if bad:
            issues.append("these numbers are not in any tool result: %s - recompute them with run_python or remove them"
                          % ", ".join(("%g" % v) for v in bad[:8]))
        if re.search(r"\d", _MARK.sub("", answer)) and not _MARK.search(answer) and not self.charts:
            issues.append("add a [SOURCE: file | PAGE x] citation after each fact, copied from the tool results")
        from services.dataviz import wants_chart
        if wants_chart(self.q) and not re.search(r"flow\s*chart", self.q, re.I) and not self.charts:
            issues.append("the user asked for a chart - call make_chart")
        if not self.evidence:
            issues.append("you have not used any tool - get evidence first")
        ev_text = "\n".join(self.evidence)
        if re.search(r"\d\s*(ha|hectares?)\b", answer, re.I) and not re.search(r"\b(ha|hectare)", ev_text, re.I):
            issues.append("the unit 'ha' is not in the documents - area columns are in m² (square metres); fix the unit")
        used = {t.get("tool") for t in self.trace if t.get("tool")}
        try:
            FIGURE_Q = _FIG
            if FIGURE_Q.search(self.q) and not ({"look_at_page", "cad_inspect", "cad_draft"} & used):
                issues.append("the question is about a figure/drawing/colour - call look_at_page on the page that has it, then answer from what it sees")
        except Exception:
            pass
        # Completeness: "which ... require Rw 65" -> every read row holding that value must be in the answer.
        _vals = [v for v in re.findall(r"(?<!table )(?<!figure )(?<!page )(?<![\d.])(\d+(?:\.\d+)?)(?![\d.])", self.q.lower())]
        if re.search(r"\b(which|list|all|every)\b", self.q, re.I) and _vals and self.read_rows:
            val = _vals[-1]
            low = answer.lower()
            missing = []
            for cols, r in self.read_rows:
                if not any(re.match(r"^\s*%s(?![\d.])" % re.escape(val), str(c)) for c in r):
                    continue
                label = [str(c) for c in r if c and not re.match(r"^[-\d.,\s%()]+$", str(c)) and not str(c).startswith(val)][:2]
                if label and not all(l.lower()[:25] in low for l in label):
                    missing.append(" / ".join(label))
            missing = list(dict.fromkeys(missing))
            if missing:
                issues.append("the answer is missing these matching rows from the table: %s - list ALL of them" % "; ".join(missing[:8]))
        if re.search(r"\b(which|list|all|every)\b", self.q, re.I) and re.search(r"\btable\s*\d+|\brequire", self.q, re.I) \
                and "read_table" not in used and "list_tables" not in used:
            issues.append("this asks for every matching row - call list_tables (keyword from the question) and read_table, then list ALL matching rows")
        return issues

    def run(self):
        """Generator of events: ('status', text) ... ('final', dict)."""
        msgs = [{"role": "system", "content": SYSTEM}]
        for m in self.history[-4:]:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                msgs.append({"role": m["role"], "content": str(m["content"])[:1500]})
        names = ", ".join(sorted({d.get("filename") or os.path.basename(d["path"]) for d in self.docs})[:8])
        msgs.append({"role": "user", "content": "Documents in this project: %s\n\nQuestion: %s" % (names, self.q)})
        # Always start from the document search (cheap, anchors single facts like "sitewide FAR").
        yield ("status", "Searching documents")
        try:
            first = str(self.t_search_documents(self.q))[:TOOL_TEXT_LIMIT]
        except Exception as exc:
            first = "ERROR: %s" % exc
        self.evidence.append(first)
        self.calls.add("search_documents" + json.dumps({"query": self.q}, sort_keys=True))
        self.trace.append({"tool": "search_documents", "args": {"query": self.q}, "chars": len(first)})
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "search_documents", "arguments": {"query": self.q}}}]})
        msgs.append({"role": "tool", "content": first, "tool_name": "search_documents"})
        pre = []
        try:
            ids = self.lookup_ids()
            if ids:
                pre.append(("lookup_rows", "Exact rows for the IDs in the question:\n" + ids))
            agg = self.auto_aggregate()
            if agg and not agg.startswith("ERROR"):
                pre.append(("aggregate", agg + "\nThis is the exact answer for the requested total/average/count - use it, do not use section summaries."))
            st = self.small_table_rows()
            if st:
                pre.append(("summary_rows", "Rows of summary tables that match the question (values stated in the document - quote them):\n" + st))
            lm = self.list_matches()
            if lm:
                pre.append(("list_matches", lm))
            from services.dataviz import wants_chart
            if wants_chart(self.q) and not re.search(r"flow\s*chart", self.q, re.I):
                yield ("status", "Drawing the chart from the file")
                pre.append(("make_chart", self.t_make_chart(self.q)))
        except Exception as exc:
            pre.append(("prefetch", "ERROR: %s" % exc))
        for name, res in pre:
            res = str(res)[:TOOL_TEXT_LIMIT]
            self.evidence.append(res)
            self.trace.append({"tool": name, "args": {}, "chars": len(res)})
            msgs.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": {}}}]})
            msgs.append({"role": "tool", "content": res, "tool_name": name})
        repairs, steps, answer = 0, 0, ""
        t0 = time.time()
        while steps < MAX_STEPS + MAX_REPAIRS + 1:
            steps += 1
            force_answer = steps > MAX_STEPS
            msg = self._chat(msgs, tools=not force_answer)
            calls = msg.get("tool_calls") or []
            if not calls and "<tool_call>" in (msg.get("content") or ""):
                # Some models (e.g. TwIL/Granite GGUFs) print tool calls as text; parse them.
                calls = _text_tool_calls(msg.get("content") or "")
                msg["content"] = re.sub(r"(?s)<tool_call>.*?(</tool_call>|$)", "", msg.get("content") or "").strip()
            if calls and not force_answer:
                msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
                for c in calls[:3]:
                    fn = (c.get("function") or {})
                    name, args = fn.get("name", ""), fn.get("arguments") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except ValueError:
                            args = {}
                    key = name + json.dumps(args, sort_keys=True)
                    yield ("status", self._label(name, args))
                    if key in self.calls:
                        result = "You already ran this exact call - use its result above or try something different."
                    else:
                        self.calls.add(key)
                        fnc = getattr(self, "t_" + name, None)
                        try:
                            result = fnc(**args) if fnc else "ERROR: unknown tool " + name
                        except TypeError as exc:
                            result = "ERROR: bad arguments: %s" % exc
                        except Exception as exc:
                            result = "ERROR: %s" % str(exc)[:300]
                    result = str(result)[:TOOL_TEXT_LIMIT]
                    self.evidence.append(result)
                    self.trace.append({"tool": name, "args": args, "chars": len(result)})
                    msgs.append({"role": "tool", "content": result, "tool_name": name})
                continue
            answer = (msg.get("content") or "").strip()
            yield ("status", "Checking the answer against the evidence...")
            issues = self._verify(answer)
            self.trace.append({"verify": issues})
            if not issues:
                break
            if repairs >= MAX_REPAIRS:
                answer = self._unverified(answer, issues)
                break
            repairs += 1
            msgs.append({"role": "assistant", "content": answer})
            msgs.append({"role": "user", "content": "Verification failed: " + "; ".join(issues) +
                         ". Fix it using the tools, then give the corrected final answer."})
        yield ("final", {"answer": answer, "sources": self.sources, "charts": self.charts, "trace": self.trace,
                         "seconds": round(time.time() - t0, 1), "repairs": repairs})

    def _unverified(self, answer, issues):
        ev = _nums("\n".join(self.evidence))
        kept = []
        for line in answer.splitlines():
            if all(_supported(v, ev) for v in _nums(line)):
                kept.append(line)
        text = "\n".join(kept).strip()
        note = "\n\n_Some parts of the draft could not be verified against the documents and were removed._"
        return (text + note) if text else "I could not verify an answer to this from the uploaded documents."

    @staticmethod
    def _label(name, args):
        return {"search_documents": "Searching documents: %s" % str(args.get("query", ""))[:60],
                "list_tables": "Listing tables%s" % (": " + args["keyword"] if args.get("keyword") else ""),
                "read_table": "Reading table %s" % args.get("table_id"),
                "run_python": "Calculating from the table",
                "make_chart": "Drawing the chart from the file",
                "look_at_page": "Looking at the page image"}.get(name, "Working: " + name)
