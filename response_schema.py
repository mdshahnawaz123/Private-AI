"""
response_schema.py — Response Rendering Engine (backend half)
================================================================
Purely additive post-processing layer. Converts the plain-text answer
that the existing LLM pipeline (Qwen 4B chat / Qwen 32B vision) already
produces, plus the sources/context the existing retrieval pipeline
already computed, into the structured JSON contract consumed by the
frontend's trusted renderer (ui/response_renderer.js).

This module NEVER calls a model, NEVER changes retrieval/indexing, and
NEVER changes what text the user sees if no structure is detected —
a plain conversational answer still comes back with type
"simple_answer" and the frontend renders it exactly as before.

Nothing here can raise and break an in-flight stream: every public
function is wrapped so a failure degrades to a safe simple_answer
rather than breaking /ask_stream or /ask_model.
"""
from __future__ import annotations
import re
import os
import json
import html as _html
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# status / confidence vocab (must match the frontend's color tokens exactly)
# ---------------------------------------------------------------------------
STATUS_EXTRACTED = "EXTRACTED"
STATUS_VERIFIED = "VERIFIED"
STATUS_CALCULATED = "CALCULATED"
STATUS_PASS = "PASS"
STATUS_REVIEW = "REVIEW REQUIRED"
STATUS_WARNING = "WARNING"
STATUS_ERROR = "ERROR"
STATUS_NOT_FOUND = "NOT FOUND"

_NOT_FOUND_RX = re.compile(
    r"\b(i\s+(?:could\s+not|couldn'?t|cannot|can'?t|do\s+not|don'?t|did\s+not|didn'?t)\s+find|"
    r"no\s+(?:information|data|mention|record)\s+(?:of|about|on|regarding)|"
    r"not\s+(?:found|available|mentioned|present)\s+in\s+(?:the\s+)?(?:document|documents|project|uploaded\s+documents)|"
    r"unable\s+to\s+(?:locate|find))\b", re.I)

_ERROR_RX = re.compile(r"\b(error|failed|exception|could\s+not\s+process)\b", re.I)
_WARNING_RX = re.compile(r"\b(warning|discrepanc|mismatch|exceeds?|non[- ]compliant|violat|caution|inconsistent)\b", re.I)
_CALC_RX = re.compile(r"\b(calculat|computed|derived|=\s*[\d.,]+\s*[%a-zA-Z/²³]*\s*$)\b", re.I)

_CITE_RX = re.compile(r"\[SOURCE:\s*([^\]|]+?)\s*(?:\|\s*PAGE\s*([0-9]+))?\s*\]", re.I)

# Markdown pipe table: header row, separator row (---|---), 1+ data rows.
_TABLE_RX = re.compile(
    r"(?P<head>^\|.+\|\s*$)\n"
    r"(?P<sep>^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$)\n"
    r"(?P<body>(?:^\|.+\|\s*$\n?)+)",
    re.M,
)

# "Label: Value" / "Label = Value" style metric lines, e.g. "GFA / BUA: 60.62%"
_METRIC_RX = re.compile(
    r"^[*\-\s]*\*{0,2}([A-Za-z][A-Za-z0-9 /()._-]{2,40}?)\*{0,2}\s*[:=]\s*"
    r"([0-9][0-9,.]*\s*(?:%|sqm|sq\.?m|m2|m²|sqft|sq\.?ft|ft2|units?|nos?\.?)?)\s*$",
    re.M,
)


def _strip_think(text: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>", "", text or "", flags=re.I).strip()


def _parse_md_table(block: str) -> Optional[Dict[str, Any]]:
    lines = [l for l in block.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        return None

    def split_row(l: str) -> List[str]:
        l = l.strip()
        if l.startswith("|"):
            l = l[1:]
        if l.endswith("|"):
            l = l[:-1]
        return [c.strip() for c in l.split("|")]

    header = split_row(lines[0])
    rows = [split_row(l) for l in lines[2:] if l.strip()]
    rows = [r for r in rows if any(c for c in r)]
    if not header or not rows:
        return None
    norm_rows = []
    for r in rows:
        if len(r) < len(header):
            r = r + [""] * (len(header) - len(r))
        elif len(r) > len(header):
            r = r[: len(header)]
        norm_rows.append(r)
    return {"columns": header, "rows": norm_rows}


def extract_tables(answer_text: str) -> List[Dict[str, Any]]:
    tables = []
    for m in _TABLE_RX.finditer(answer_text):
        block = m.group(0)
        parsed = _parse_md_table(block)
        if parsed:
            # try to use the line right above the table as a title
            start = m.start()
            prior = answer_text[:start].rstrip().splitlines()
            title = ""
            if prior:
                cand = prior[-1].strip(" *#:")
                if cand and len(cand) < 90 and not cand.startswith("|"):
                    title = cand
            tables.append({
                "title": title or f"Table {len(tables) + 1}",
                "columns": parsed["columns"],
                "rows": parsed["rows"],
            })
    return tables


def extract_metrics(answer_text: str, used_in_tables: str = "") -> List[Dict[str, Any]]:
    # Don't double-count numbers that are already inside a rendered table.
    text_wo_tables = _TABLE_RX.sub("", answer_text)
    metrics = []
    seen = set()
    for m in _METRIC_RX.finditer(text_wo_tables):
        label, value = m.group(1).strip(), m.group(2).strip()
        if not label or not value:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        status = STATUS_CALCULATED if _CALC_RX.search(label + " " + value) else STATUS_EXTRACTED
        metrics.append({
            "label": label,
            "value": value,
            "description": "",
            "status": status,
        })
        if len(metrics) >= 12:
            break
    return metrics


def extract_issues(answer_text: str) -> List[Dict[str, Any]]:
    issues = []
    for line in answer_text.splitlines():
        s = line.strip(" -*•\t")
        if not s or len(s) < 6:
            continue
        if _WARNING_RX.search(s):
            issues.append({"severity": STATUS_WARNING, "text": s})
        elif _ERROR_RX.search(s):
            issues.append({"severity": STATUS_ERROR, "text": s})
    return issues[:10]


def _basename(p: str) -> str:
    return str(p or "").replace("\\", "/").split("/")[-1]


def _confidence(sources: List[Dict[str, Any]], focus_doc_used: bool, is_not_found: bool) -> str:
    if is_not_found:
        return "low"
    if focus_doc_used:
        return "high"
    n = len(sources or [])
    if n >= 2:
        return "high"
    if n == 1:
        return "medium"
    return "low"


def build_sources(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for s in (sources or []):
        if not isinstance(s, dict):
            continue
        doc = s.get("filename") or s.get("source") or s.get("rel") or "document"
        base = _basename(doc)
        page = s.get("page")
        section = s.get("section") or s.get("table_name") or ""
        tile_id = s.get("tile_id") or (
            f"{os.path.splitext(base)[0]}-P{int(page):02d}" if isinstance(page, int) or
            (isinstance(page, str) and str(page).isdigit()) else None
        )
        out.append({
            "document": base,
            "rel": s.get("rel") or s.get("source") or base,
            "page": page,
            "section": section,
            "tile_id": tile_id,
            "bounding_box": s.get("bounding_box"),
            "revision": s.get("revision") or "",
        })
    return out


def classify_type(answer_text: str, tables: List[Dict], metrics: List[Dict],
                   issues: List[Dict], is_not_found: bool, has_sources: bool) -> str:
    if is_not_found:
        return "not_found"
    if any(i["severity"] == STATUS_ERROR for i in issues):
        return "error"
    if tables and not metrics and len(answer_text) < 400:
        return "table"
    if any(i["severity"] == STATUS_WARNING for i in issues):
        return "warning"
    if tables or metrics:
        return "document_analysis" if has_sources else "calculation" if metrics and not tables else "document_analysis"
    return "simple_answer"


def build_structured_response(
    query: str,
    answer_text: str,
    sources: List[Dict[str, Any]],
    *,
    title_hint: str = "",
    subtitle_hint: str = "",
    focus_doc_used: bool = False,
) -> Dict[str, Any]:
    """Pure, side-effect-free. Never raises — callers can rely on it always
    returning a usable dict, degrading to {"type": "simple_answer", ...}."""
    try:
        text = _strip_think(answer_text)
        text_clean = _CITE_RX.sub("", text).strip()
        is_not_found = bool(_NOT_FOUND_RX.search(text_clean)) and len(text_clean) < 600

        tables = extract_tables(text_clean)
        metrics = extract_metrics(text_clean)
        issues = extract_issues(text_clean)
        src_struct = build_sources(sources)

        rtype = classify_type(text_clean, tables, metrics, issues, is_not_found, bool(src_struct))

        # Pull a one-paragraph summary: first non-empty, non-table, non-header line(s).
        summary_lines = []
        for line in text_clean.splitlines():
            s = line.strip()
            if not s or s.startswith("|") or s.startswith("#"):
                continue
            summary_lines.append(s)
            if sum(len(x) for x in summary_lines) > 320:
                break
        summary = " ".join(summary_lines)[:500]

        if rtype == "simple_answer":
            return {
                "type": "simple_answer",
                "title": "",
                "subtitle": "",
                "summary": text_clean,
                "metrics": [],
                "tables": [],
                "calculations": [],
                "issues": [],
                "sources": src_struct,
                "confidence": _confidence(sources, focus_doc_used, False),
            }

        return {
            "type": rtype,
            "title": title_hint or (query[:80] if query else "Answer"),
            "subtitle": subtitle_hint,
            "summary": summary or text_clean[:280],
            "metrics": metrics,
            "tables": tables,
            "calculations": [],
            "issues": issues,
            "sources": src_struct,
            "confidence": _confidence(sources, focus_doc_used, is_not_found),
            "full_text": text_clean,
        }
    except Exception:
        return {
            "type": "simple_answer",
            "title": "", "subtitle": "",
            "summary": _strip_think(answer_text),
            "metrics": [], "tables": [], "calculations": [], "issues": [],
            "sources": build_sources(sources) if isinstance(sources, list) else [],
            "confidence": "medium",
        }
