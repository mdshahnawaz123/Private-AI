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
import os
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


def _split_oversized_blob(blob: str, pno) -> List[Dict[str, Any]]:
    """A single page can itself exceed WINDOW_CHARS (a dense data-sheet page
    with a full text layer + table markdown + a vision transcript routinely
    runs 40000+ chars combined) -- split it on paragraph/row boundaries into
    several same-page sub-windows with overlap, rather than handing the whole
    thing to the model in one shot (empirically: qwen3.5:9b given a ~45000
    char single prompt returned an almost-empty response -- it needs each
    extraction pass scoped to a few thousand chars to actually enumerate
    facts instead of just summarizing or truncating)."""
    # Prefer splitting on blank-line boundaries so a table row or sentence is
    # never cut mid-way; fall back to a hard character split only if a single
    # paragraph is itself larger than WINDOW_CHARS.
    paragraphs = re.split(r"\n\s*\n", blob)
    chunks = []
    cur = ""
    for para in paragraphs:
        if cur and len(cur) + len(para) > WINDOW_CHARS:
            chunks.append(cur)
            tail = cur[-WINDOW_OVERLAP:] if len(cur) > WINDOW_OVERLAP else cur
            cur = tail + "\n\n" + para
        else:
            cur = (cur + "\n\n" + para) if cur else para
        while len(cur) > WINDOW_CHARS * 2:
            # a single paragraph (e.g. one giant vision transcript) that's
            # still too big on its own -- hard-split it.
            chunks.append(cur[:WINDOW_CHARS])
            cur = cur[WINDOW_CHARS - WINDOW_OVERLAP:]
    if cur:
        chunks.append(cur)
    return [{"text": chunk, "pages": [pno]} for chunk in chunks]


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
        if len(blob) > WINDOW_CHARS:
            # flush whatever was accumulating first, then split this page on
            # its own (it needs multiple windows by itself).
            if cur_text:
                windows.append({"text": cur_text, "pages": list(cur_pages)})
                cur_text = ""
                cur_pages = []
            windows.extend(_split_oversized_blob(blob, pno))
            continue
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


_SYSTEM_PROMPT = (
    "You are a strict data-extraction engine, not a conversational assistant. "
    "You NEVER write a summary, a preamble, or any commentary. Your entire "
    "response is a single JSON array and nothing else -- it must start with "
    "'[' and end with ']'. If there is nothing to extract, respond with []."
)


def _call_model(window_text: str, model_role: str = "REASONING_LLM") -> List[Dict[str, Any]]:
    from core.model_registry import get_registry
    provider = get_registry().get_provider(model_role)
    if provider is None:
        raise RuntimeError(f"No provider registered for role {model_role}")
    prompt = _EXTRACTION_PROMPT.format(window_text=window_text)
    # Assistant-turn prefill: ending the message list on a short assistant
    # turn of just "[" strongly biases chat-tuned local models to continue
    # the array rather than open with a conversational summary -- this
    # model (qwen3.5:9b) ignores a system-only instruction not to summarize,
    # but reliably continues from a primed "[" (confirmed empirically against
    # this exact failure mode: raw responses otherwise opened with "Based on
    # the provided project data sheets...").
    raw = provider.chat([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": "["},
    ])
    facts = _parse_json_array("[" + raw if not raw.lstrip().startswith("[") else raw)
    if not facts:
        # One retry, blunter, still primed.
        retry_prompt = (
            "Your previous response did not follow the required format. "
            "Re-extract the SAME facts from the SAME text below as a JSON "
            "array ONLY -- no commentary, no markdown fence, nothing before "
            "'[' or after ']'.\n\n" + prompt
        )
        raw2 = provider.chat([
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": retry_prompt},
            {"role": "assistant", "content": "["},
        ])
        facts = _parse_json_array("[" + raw2 if not raw2.lstrip().startswith("[") else raw2)
    return facts


def _extract_balanced_objects(text: str) -> List[str]:
    """Scan for top-level {...} substrings respecting string literals and
    escapes, without requiring the surrounding array to be valid JSON. Local
    chat models occasionally drop a comma or otherwise malform ONE entry in
    an otherwise-good array (confirmed empirically against this model);
    recovering every other entry is much better than discarding the whole
    window's facts over one bad object."""
    objects = []
    depth = 0
    start = None
    in_string = False
    escape = False
    for i, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(text[start:i + 1])
                    start = None
    return objects


def _parse_json_array(raw: str) -> List[Dict[str, Any]]:
    raw = (raw or "").strip()
    # Models sometimes wrap the array in a code fence or add leading prose;
    # pull out the first top-level [...] block rather than failing outright.
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        logger.warning("document_memory: model returned no JSON array. raw[:800]={}", raw[:800])
        return []
    array_text = match.group(0)
    try:
        data = json.loads(array_text)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    except Exception as e:
        snippet_start = max(0, getattr(e, "pos", 0) - 150)
        snippet = array_text[snippet_start:snippet_start + 300]
        logger.warning(
            "document_memory: array-level JSON parse failed, falling back to "
            "per-object recovery: {} | context: {}", e, snippet,
        )
    # Fallback: recover whichever individual {...} objects ARE valid JSON,
    # rather than discarding the whole window over one malformed entry.
    recovered = []
    skipped = 0
    for obj_text in _extract_balanced_objects(array_text):
        try:
            obj = json.loads(obj_text)
            if isinstance(obj, dict):
                recovered.append(obj)
        except Exception:
            skipped += 1
    if skipped:
        logger.warning("document_memory: per-object recovery skipped {} malformed object(s), kept {}", skipped, len(recovered))
    return recovered


# ── verification ─────────────────────────────────────────────
# Pipe characters (markdown table cell delimiters) and newlines are treated
# as interchangeable with plain whitespace when comparing a model's "verbatim"
# quote against the source: the model consistently reconstructs a pipe-
# delimited table row ("| Basement 1 | 32,031.40 | 344,782.79 |") using
# newlines instead of pipes when it copies a cell boundary, which is a
# formatting difference, not a change to the actual words/numbers in the
# quote. Collapsing both to a single space before comparing recovers these
# facts as VERIFIED without weakening the check that matters: every word and
# number in the quote still has to appear in the source, in the same order.
_DELIM_RE = re.compile(r"[\s|]+")
_QUOTE_RE = re.compile(r"[\u2018\u2019\u201c\u201d'\"]+")
_MD_EMPHASIS_RE = re.compile(r"\*{1,2}|_{1,2}(?=\w)|(?<=\w)_{1,2}")


def _normalize(s: str) -> str:
    s = _QUOTE_RE.sub("", (s or ""))
    s = _MD_EMPHASIS_RE.sub("", s)
    return _DELIM_RE.sub(" ", s).strip().lower()


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


# ── Phase 2: query-time memory-first lookup ──────────────────
# Additive only. Called from main.py:ask_stream BEFORE the existing
# retrieve_context()/select_page_context() RAG path, and falls through to it
# unchanged whenever memory doesn't clearly cover the question -- this
# function never raises and returns None on anything short of a confident,
# re-verified, guard-passing match.

_meta_cache: Dict[str, Any] = {}  # doc path -> (mtime, page_text map)


def _cached_page_text(doc_path: str) -> Dict[int, str]:
    try:
        mtime = os.path.getmtime(doc_path + ".index.json")
    except OSError:
        return {}
    cached = _meta_cache.get(doc_path)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        meta = json.load(open(doc_path + ".index.json", encoding="utf-8"))
    except Exception:
        return {}
    page_text = _page_text_map(meta)
    _meta_cache[doc_path] = (mtime, page_text)
    return page_text


def _memory_row_content(row) -> str:
    return " ".join(str(x or "") for x in (
        row.property, row.claim, row.section, row.table,
        row.entity, " ".join(row.topic_tags or []),
    ))


def memory_lookup(project_id: int, query: str, permitted_filenames=None, focus_filename: str = None):
    """Return {"answer": str, "sources": [...]} for a confident, re-verified,
    guard-passing memory answer, or None to fall through to RAG. Never raises.
    """
    try:
        import db
        from intelligence.retrieval import BM25Index
        from intelligence.answer_guard import guarded_answer

        db_session = db.SessionLocal()
        try:
            q = db_session.query(db.DocumentMemory).filter_by(
                project_id=project_id, evidence_state="VERIFIED"
            ).filter(db.DocumentMemory.superseded_at.is_(None))
            if focus_filename:
                q = q.filter(db.DocumentMemory.doc == focus_filename)
            rows = q.all()
        finally:
            db_session.close()

        if not rows:
            return None
        if permitted_filenames is not None:
            rows = [r for r in rows if r.doc in permitted_filenames]
        if not rows:
            return None

        bm25 = BM25Index()
        bm25.add_documents([{"content": _memory_row_content(r), "idx": i} for i, r in enumerate(rows)])
        hits = bm25.search(query, k=8)
        if not hits:
            return None

        # Require at least one non-trivial query word to appear literally in
        # the matched row's `property` key -- BM25 alone can surface a
        # topically-related but wrong-field row; this keeps the lookup
        # conservative about what counts as "this question is about that fact".
        query_words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 4}
        candidates = []
        for idx, score in hits:
            row = rows[idx]
            prop_words = set(re.findall(r"[a-z0-9]+", (row.property or "").lower()))
            if query_words & prop_words:
                candidates.append((row, score))
        if not candidates:
            return None

        # Disambiguate: prefer the unqualified (empty parent_context) row
        # unless the query itself names the condition a qualified row covers.
        def _rank(item):
            row, score = item
            qualified = bool((row.parent_context or "").strip())
            matches_condition = qualified and bool(
                set(re.findall(r"[a-z0-9]+", (row.parent_context or "").lower())) & query_words
            )
            # Highest priority: a qualified row whose condition the query
            # actually names. Next: an unqualified default row. Last: a
            # qualified row the query didn't ask about.
            tier = 0 if matches_condition else (1 if not qualified else 2)
            return (tier, -score)
        candidates.sort(key=_rank)
        best_row, best_score = candidates[0]

        # Re-verify the chosen row's evidence against the CURRENT source text
        # (catches drift if the document was reprocessed since memory was built).
        doc_path = None
        import db as _db
        with _db.SessionLocal() as _s:
            d_row = _s.query(_db.Document).filter_by(id=best_row.document_id).first()
            doc_path = d_row.path if d_row else None
        if not doc_path:
            return None
        page_text = _cached_page_text(doc_path)
        quote_norm = _normalize(best_row.evidence_quote)
        page_norm = page_text.get(best_row.page, "")
        if quote_norm not in page_norm:
            # also accept if it verifies on ANY page (handles a page-number
            # correction since the memory row was written)
            if not any(quote_norm in t for t in page_text.values()):
                logger.info("document_memory: query-time re-verification failed for '{}', falling through to RAG", best_row.property)
                return None

        answer = f"{best_row.claim.strip()} [SOURCE: {best_row.doc} | PAGE {best_row.page}]"
        evidence = f"[SOURCE: {best_row.doc} | PAGE {best_row.page}]\n{best_row.evidence_quote}"
        sources = [{"source": best_row.doc, "page": best_row.page}]
        published, issues = guarded_answer(answer, evidence, sources)
        if issues:
            logger.info("document_memory: query-time guard rejected memory answer for '{}': {}", best_row.property, issues)
            return None
        return {"answer": published, "sources": sources}
    except Exception as e:
        logger.warning("document_memory: memory_lookup failed (falling through to RAG): {}", e)
        return None
