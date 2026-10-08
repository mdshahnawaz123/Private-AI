"""
AI Document Memory layer — Phase 1 (2026-10-08).

Additive, ingestion-time module: reads a whole document (its already-
extracted page text/tables/vision, no new extraction) with the REASONING_LLM
and writes a relationship-aware, evidence-linked `db.DocumentMemory` row per
discrete fact the model identifies.

Design doc: "Expo Design AI - Document Memory Layer - Architecture Proposal.md"
(project docs). Nothing in this module changes query-time behavior
(retrieve_context / select_page_context / answer_guard) -- that is Phase 2,
not built yet. This module is only ever called from process_document(), is
wrapped there in its own try/except, and is gated by both
config.enable_document_memory and an explicit filename allow-list
(config.document_memory_doc_allowlist) so Phase 1 runs for exactly the two
benchmark documents, never silently for anything else.

Nothing here is discarded on verification failure. A fact whose evidence_quote
does not verify is persisted with evidence_state="REVIEW_REQUIRED" and a
review_reason string -- never dropped.
"""
import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

# ── window construction ──────────────────────────────────────
WINDOW_CHARS = 7000
WINDOW_OVERLAP = 500


def _page_blob(page: Dict[str, Any]) -> str:
    """Same per-page rendering process_document() already uses to build
    `combined` (text + tables + vision), reused here so the model reads
    exactly what's on disk -- no new extraction."""
    parts = []
    for field in ("text", "tables", "vision"):
        val = str(page.get(field, "") or "").strip()
        if val:
            parts.append(val)
    body = "\n".join(parts)
    return f"[PAGE {page.get('page')}]\n{body}"


def build_windows(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Split the document's already-extracted pages into large, overlapping
    comprehension windows. Each window records the set of page numbers it
    spans, so every fact extracted from it can be tagged with the correct
    page (and the verification step can check the quote against the right
    page's own text, not just anywhere in the window)."""
    pages = [p for p in meta.get("pages", []) if any(
        str(p.get(f, "") or "").strip() for f in ("text", "tables", "vision")
    )]
    if not pages:
        return []

    windows = []
    cur_text = ""
    cur_pages: List[int] = []
    for page in pages:
        blob = _page_blob(page)
        pno = page.get("page")
        if cur_text and len(cur_text) + len(blob) > WINDOW_CHARS:
            windows.append({"text": cur_text, "pages": list(cur_pages)})
            # overlap: carry the tail of the previous window forward
            tail = cur_text[-WINDOW_OVERLAP:] if len(cur_text) > WINDOW_OVERLAP else cur_text
            cur_text = tail + "\n\n" + blob
            cur_pages = cur_pages[-1:] + [pno] if cur_pages else [pno]
        else:
            cur_text = (cur_text + "\n\n" + blob) if cur_text else blob
            cur_pages.append(pno)
    if cur_text:
        windows.append({"text": cur_text, "pages": list(cur_pages)})
    return windows


# ── extraction prompt ────────────────────────────────────────
_EXTRACTION_PROMPT = """You are reading one section of an engineering/BIM design document. \
Extract every discrete FACT that is explicitly stated in the text below -- a \
named property with a stated value, a defined term, a stated requirement or \
rule, a table row. Do not summarize, do not infer anything not explicitly \
stated, do not combine two separate facts into one.

Return ONLY a JSON array, no other text. Each element must have exactly these \
fields:

{{
  "property": "short name of the fact, e.g. 'Plot Area' or 'Minimum guard height'",
  "claim": "the fact as one full, human-readable sentence",
  "value": "the stated value as a string, '' if not a quantity",
  "unit": "the unit, '' if none",
  "page": <int page number this fact appears on, from the [PAGE n] markers below>,
  "section": "the narrative heading this falls under, '' if none, e.g. 'Means of Egress'",
  "table": "the table/schedule name this came from, '' if not from a table, e.g. 'AREA STATEMENT SUMMARY'",
  "entity": "the tower/building/zone this is scoped to, '' if document-wide",
  "parent_context": "a qualification or parent row this fact is nested under, '' if none, e.g. 'applies only where sprinklered' or 'sub-row of RESIDENTIAL UNIT BREAKDOWN > 2BR-Type 3'",
  "topic_tags": ["short","lowercase","tags"],
  "evidence_quote": "a VERBATIM copy-paste from the text below that supports this fact -- character for character, no paraphrasing",
  "confidence": "HIGH" | "MEDIUM" | "LOW"
}}

evidence_quote will be checked programmatically against the source text below \
and the fact will be flagged for review if it is not found verbatim, so copy \
it exactly rather than restating it.

TEXT:
{window_text}
"""


def _call_model(window_text: str, model_role: str = "REASONING_LLM") -> List[Dict[str, Any]]:
    from core.model_registry import get_registry
    provider = get_registry().get_provider(model_role)
    if provider is None:
        raise RuntimeError(f"No provider registered for role {model_role}")
    prompt = _EXTRACTION_PROMPT.format(window_text=window_text)
    raw = provider.chat([{"role": "user", "content": prompt}])
    return _parse_json_array(raw)


def _parse_json_array(raw: str) -> List[Dict[str, Any]]:
    raw = (raw or "").strip()
    # Models sometimes wrap the array in a code fence or add leading prose;
    # pull out the first top-level [...] block rather than failing outright.
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        logger.warning("document_memory: model returned no JSON array")
        return []
    try:
        data = json.loads(match.group(0))
    except Exception as e:
        logger.warning("document_memory: JSON parse failed: {}", e)
        return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


# ── verification ─────────────────────────────────────────────
_WS_RE = re.compile(r"\s+")


def _normalize(s: str) -> str:
    return _WS_RE.sub(" ", (s or "")).strip().lower()


def _page_text_map(meta: Dict[str, Any]) -> Dict[int, str]:
    out = {}
    for page in meta.get("pages", []):
        pno = page.get("page")
        if pno is None:
            continue
        out[pno] = _normalize(_page_blob(page))
    return out


def verify_fact(fact: Dict[str, Any], window_pages: List[int], page_text: Dict[int, str]):
    """Returns (evidence_state, resolved_page, review_reason)."""
    quote = _normalize(fact.get("evidence_quote", ""))
    if len(quote) < 8 or not fact.get("property"):
        return "REJECTED", fact.get("page"), "degenerate output: missing property or evidence_quote too short"

    claimed_page = fact.get("page")
    # Check the claimed page first (cheap, most common case).
    if claimed_page in page_text and quote in page_text[claimed_page]:
        return "VERIFIED", claimed_page, ""

    # Quote may genuinely be on a different page within the same window
    # (windows can span a page boundary) -- correct the bookkeeping rather
    # than treating this as a trust failure.
    for pno in window_pages:
        if pno in page_text and quote in page_text[pno]:
            return "VERIFIED", pno, ""

    return (
        "REVIEW_REQUIRED",
        claimed_page,
        f"evidence_quote not found verbatim on claimed page {claimed_page} "
        f"or elsewhere in window pages {window_pages}",
    )


# ── revision heuristic ───────────────────────────────────────
_REVISION_RE = re.compile(r"(?:Document\s+)?Revision\s*(?:No\.?)?\s*[:.]?\s*([A-Za-z0-9\-]+)", re.I)


def _guess_revision(meta: Dict[str, Any]) -> str:
    for page in meta.get("pages", [])[:3]:
        text = str(page.get("text", "") or "") + "\n" + str(page.get("tables", "") or "")
        m = _REVISION_RE.search(text)
        if m:
            return m.group(1).strip()
    return ""


# ── main entry point ─────────────────────────────────────────
def build_memory_for_document(project_id: int, document_id: int, filename: str,
                               meta: Dict[str, Any], source_sha256: str,
                               model_role: str = "REASONING_LLM") -> Dict[str, int]:
    """Build (or rebuild) DocumentMemory rows for one document. Call only
    from process_document(), after index_structured()/extract_structured_tables().
    Never raises -- any failure is logged and returns zero counts, so a
    memory-build problem degrades to "RAG-only for this document", exactly
    like every other optional ingestion stage in this pipeline.
    """
    import db

    counts = {"verified": 0, "review_required": 0, "rejected": 0, "windows": 0}
    try:
        windows = build_windows(meta)
        counts["windows"] = len(windows)
        if not windows:
            logger.warning("document_memory: no page text for {} -- nothing to build", filename)
            return counts

        page_text = _page_text_map(meta)
        revision = _guess_revision(meta)
        rows_to_insert = []

        for window in windows:
            try:
                facts = _call_model(window["text"], model_role=model_role)
            except Exception as e:
                logger.warning("document_memory: extraction pass failed for a window of {}: {}", filename, e)
                continue
            for fact in facts:
                state, resolved_page, reason = verify_fact(fact, window["pages"], page_text)
                row = db.DocumentMemory(
                    project_id=project_id,
                    document_id=document_id,
                    doc=filename,
                    revision=revision,
                    source_sha256=source_sha256,
                    page=resolved_page,
                    section=str(fact.get("section", "") or ""),
                    table=str(fact.get("table", "") or ""),
                    entity=str(fact.get("entity", "") or ""),
                    parent_context=str(fact.get("parent_context", "") or ""),
                    property=str(fact.get("property", "") or "")[:300],
                    claim=str(fact.get("claim", "") or ""),
                    value=str(fact.get("value", "") or "")[:200],
                    unit=str(fact.get("unit", "") or "")[:50],
                    topic_tags=fact.get("topic_tags") if isinstance(fact.get("topic_tags"), list) else [],
                    evidence_quote=str(fact.get("evidence_quote", "") or ""),
                    evidence_source="table_row" if fact.get("table") else "text",
                    evidence_state=state,
                    review_reason=reason,
                    confidence=str(fact.get("confidence", "HIGH") or "HIGH"),
                    built_by_model=model_role,
                )
                rows_to_insert.append(row)
                if state == "VERIFIED":
                    counts["verified"] += 1
                elif state == "REVIEW_REQUIRED":
                    counts["review_required"] += 1
                else:
                    counts["rejected"] += 1

        if not rows_to_insert:
            return counts

        db_session = db.SessionLocal()
        try:
            # One source version replaces its memory atomically (same pattern
            # as index_quantities): supersede rather than delete, so history
            # of what the AI previously "remembered" is kept, not destroyed.
            existing = db_session.query(db.DocumentMemory).filter_by(
                project_id=project_id, document_id=document_id
            ).filter(db.DocumentMemory.superseded_at.is_(None)).all()
            if existing:
                now = db._utcnow()
                for row in existing:
                    row.superseded_at = now
            db_session.add_all(rows_to_insert)
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise
        finally:
            db_session.close()

        logger.info(
            "document_memory: {} -- {} windows, {} verified, {} review_required, {} rejected",
            filename, counts["windows"], counts["verified"], counts["review_required"], counts["rejected"],
        )
        return counts
    except Exception as e:
        logger.warning("document_memory: build failed for {}: {}", filename, e)
        return counts


def is_allowlisted(filename: str) -> bool:
    from config import get_settings
    allowlist = get_settings().document_memory_doc_allowlist or []
    return filename in allowlist
