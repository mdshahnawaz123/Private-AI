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

This text often contains MULTIPLE similarly-shaped tables back to back -- for \
example a per-floor area table may appear three separate times under three \
different names (e.g. "BUILT-UP AREA BREAKDOWN", "GROSS FLOOR AREA BREAKDOWN", \
"NET SELLABLE AREA BREAKDOWN"), each with a DIFFERENT number for the same floor. \
These are not duplicates -- extract every row of every one of these tables \
separately, with the "table" field naming exactly which one it came from, so \
"2nd Floor" from each of the three tables becomes three distinct facts, not one. \
The same applies to any other repeated-looking breakdown (Required vs Proposed, \
Allowed vs Actual, Incl. vs Excl. Balcony): extract each column/table's row as \
its own fact rather than only the first one you see. \
Do NOT stop partway through a long table because its rows look repetitive --a \
table listing every floor from Basement to Roof, or every unit type, must have \
every single row extracted, not just the first few or a representative sample. \
A table's rows may appear broken up by unrelated text in between (a PDF's \
multi-column layout can interleave table fragments) -- still extract every row \
you can find for that table by its header name, even if its rows are not all \
contiguous in the text below.

If a table row or named field is present but its value cell is EMPTY, blank, \
or shows only a placeholder like "-", "--", "N/A", or "TBC", still extract it \
as its own fact -- do not skip it just because it has no number. Set "value" \
to the literal placeholder text you see ("-", "N/A", "TBC", etc.) rather than \
omitting the row. A field the document deliberately leaves blank is itself a \
fact worth recording (e.g. "FAR Proposed: -" means the document does not \
state a proposed FAR), and the system otherwise has no way to distinguish \
"this field is blank in the source" from "this field was never read."

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


# ── Phase 3: LLM re-ranking among ambiguous memory candidates ──
# A sentinel distinct from None: None means "the rerank call itself didn't
# produce a usable answer" (fall back to the heuristic's top pick); _NO_MATCH
# means "the LLM looked at the candidates and concluded none of them answer
# the question" (fall through to RAG, same as the gate finding nothing).
_NO_MATCH = object()

_RERANK_SYSTEM_PROMPT = (
    "You are a strict fact-matching engine, not a conversational assistant. "
    "You are given a question and a short numbered list of candidate facts "
    "from an engineering document. Pick the ONE candidate that actually "
    "answers the question. If none of them do, say so. You NEVER write a "
    "summary or commentary -- your entire response is a single JSON object "
    "and nothing else, either {\"index\": <int>} or {\"index\": null}."
)

_RERANK_PROMPT = """Question: {query}

Candidate facts:
{candidate_list}

Which candidate (by its number) actually answers the question? A candidate only counts if it directly states the thing being asked -- a candidate that merely shares a topic or a few words with the question does NOT count. Respond with ONLY a JSON object: {{"index": <the matching candidate's number>}} or {{"index": null}} if none of them answer the question.
"""


def _llm_rerank(query: str, candidates: List[Any]):
    """Ask REASONING_LLM to pick which of up to 5 candidate DocumentMemory
    rows actually answers `query`. Returns the chosen row, _NO_MATCH if the
    model says none fit, or None if the call failed/was unusable (caller
    falls back to the heuristic ranking in that case). Never raises.
    """
    try:
        from core.model_registry import get_registry
        provider = get_registry().get_provider("REASONING_LLM")
        if provider is None:
            return None

        lines = []
        for i, row in enumerate(candidates):
            parent = f" (applies when: {row.parent_context})" if (row.parent_context or "").strip() else ""
            lines.append(f"{i}. {row.property}: {row.claim}{parent}")
        prompt = _RERANK_PROMPT.format(query=query, candidate_list="\n".join(lines))

        raw = provider.chat([
            {"role": "system", "content": _RERANK_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": "{"},
        ])
        text = "{" + raw if not raw.lstrip().startswith("{") else raw
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            return None
        idx = parsed.get("index")
        if idx is None:
            return _NO_MATCH
        if not isinstance(idx, int) or not (0 <= idx < len(candidates)):
            return None
        return candidates[idx]
    except Exception as e:
        logger.warning("document_memory: LLM rerank failed (falling back to heuristic ranking): {}", e)
        return None


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
        # Vision is interpreted evidence, never authority for VERIFIED memory.
        out[pno] = _normalize(str(page.get('text','') or '')+'\n'+str(page.get('tables','') or ''))
    return out


def verify_fact(fact: Dict[str, Any], window_pages: List[int], page_text: Dict[int, str]):
    """Returns (evidence_state, resolved_page, review_reason)."""
    quote = _normalize(fact.get("evidence_quote", ""))
    if len(quote) < 8 or not fact.get("property"):
        return "REJECTED", fact.get("page"), "degenerate output: missing property or evidence_quote too short"
    claim = _normalize(fact.get('claim',''))
    if not claim or claim not in quote:
        return 'REVIEW_REQUIRED', fact.get('page'), 'Claim is not an exact supported source statement; quote presence alone does not verify its meaning'

    claimed_page = fact.get("page")
    # Check the claimed page first (cheap, most common case).
    if claimed_page in window_pages and claimed_page in page_text and quote in page_text[claimed_page]:
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
            #
            # IMPORTANT (found 2026-10-09, re-extraction regression test):
            # extraction from a dense, multi-table page is NOT deterministic
            # between runs -- rebuilding memory for an UNCHANGED document
            # can genuinely miss facts a previous run found (confirmed: a
            # rebuild that raised total verified facts overall still lost
            # "FAR Proposed", the project data sheet's "Date", and "BUA
            # Proposed" entirely -- they simply weren't in this run's
            # output). Unconditionally superseding every previous row on
            # every rebuild means a rebuild can only ever be as complete as
            # its single worst run, forever, because anything it misses is
            # gone. A rebuild should be able to ADD or UPDATE facts; it
            # should never be able to SILENTLY DROP one that a previous run
            # already found and verified. So: only supersede an existing
            # row when the new batch actually produced a replacement for
            # it (same normalized property name on the same page) --
            # otherwise the existing, previously-verified row stays active
            # untouched. A row whose source has genuinely changed (new
            # document revision) still gets correctly superseded, because
            # the new extraction will produce a same-property/same-page row
            # with the new value; only a fact the new pass didn't mention at
            # all is preserved rather than deleted.
            def _prop_key(prop: str) -> str:
                return _WS_RE.sub(" ", (prop or "").strip()).lower()
            new_keys = {(_prop_key(r.property), r.page) for r in rows_to_insert}
            existing = db_session.query(db.DocumentMemory).filter_by(
                project_id=project_id, document_id=document_id
            ).filter(db.DocumentMemory.superseded_at.is_(None)).all()
            if existing:
                now = db._utcnow()
                kept, superseded_count = 0, 0
                for row in existing:
                    if row.source_sha256 != source_sha256 or (_prop_key(row.property), row.page) in new_keys:
                        row.superseded_at = now
                        superseded_count += 1
                    else:
                        kept += 1
                if kept:
                    logger.info(
                        "document_memory: {} -- kept {} previously-verified fact(s) this rebuild's "
                        "extraction didn't re-cover (superseded {} that were replaced)",
                        filename, kept, superseded_count,
                    )
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
        from intelligence.document_investigation import needs_coverage
        if needs_coverage(query):
            return None
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

        # Reject stale generations and existing rows built under weaker quote-only checks.
        import hashlib
        with db.SessionLocal() as session:
            documents={d.id:d for d in session.query(db.Document).filter_by(project_id=project_id).all()}
        hashes={}
        valid=[]
        for row in rows:
            document=documents.get(row.document_id)
            if not document or document.status not in ('ready','ready_with_warnings','verified','published'):
                continue
            if document.id not in hashes:
                try:
                    with open(document.path,'rb') as handle: hashes[document.id]=hashlib.file_digest(handle,'sha256').hexdigest()
                except OSError: hashes[document.id]=None
            if hashes[document.id]!=row.source_sha256:
                continue
            native=_cached_page_text(document.path)
            state,page,_=verify_fact({'property':row.property,'claim':row.claim,'page':row.page,
                                     'evidence_quote':row.evidence_quote},[row.page],native)
            if state=='VERIFIED' and page==row.page:
                valid.append(row)
        rows=valid
        if not rows:return None
        if permitted_filenames is not None:
            rows = [r for r in rows if r.doc in permitted_filenames]
        if not rows:
            return None

        bm25 = BM25Index()
        bm25.add_documents([{"content": _memory_row_content(r), "idx": i} for i, r in enumerate(rows)])
        hits = bm25.search(query, k=8)
        if not hits:
            return None

        # Qualifier/modal words common throughout this regulatory corpus'
        # property names -- "permitted", "required", "shall", etc. -- carry
        # almost no topic signal (nearly every rule says something is
        # "permitted" or "required") but can coincidentally overlap between
        # totally unrelated facts. Found via the 173-question live benchmark
        # (2026-10-08): a travel-distance fact answered a riser-height
        # question because both properties happened to contain "permitted".
        # "minimum"/"maximum"/"allowed" are deliberately NOT in this list --
        # they are often genuine, value-distinguishing signal in THIS corpus'
        # own property names (e.g. "Minimum guard height" vs "Guard maximum
        # height" are different facts; "FAR Allowed" vs "FAR Proposed" are
        # different facts) even though they read like qualifiers.
        _QUALIFIER_STOPWORDS = {
            "permitted", "required", "shall", "should", "provided",
            "must", "prohibited", "necessary", "within", "without", "least",
            "what", "how", "many", "they", "there", "does", "that", "this",
        }

        def _tokenize_for_match(text):
            # A word counts as a match-worthy token if it's reasonably long
            # (len>=4), a number of any length (digits distinguish "1
            # Bedroom" from "2 Bedroom" -- a len>=4 filter alone drops them
            # entirely, which was a real bug: nothing could tell those rows
            # apart), or an all-caps acronym of 2+ letters (FAR, GFA, BUA --
            # short but highly specific; a pure length filter was dropping
            # these as "too short" and letting generic rows like "F Value"
            # or "Section Value" win on the word "value" alone instead).
            raw = re.findall(r"[A-Za-z0-9]+", text)
            out = set()
            for w in raw:
                lw = w.lower()
                if lw.isdigit() or (w.isupper() and len(w) >= 2) or len(lw) >= 4:
                    out.add(lw)
            return out - _QUALIFIER_STOPWORDS

        query_words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 4}
        query_content = _tokenize_for_match(query)

        # Property-only BM25 index, used only for its IDF table: a rough,
        # corpus-calibrated measure of how distinguishing a given property
        # word actually is (a word that appears in many distinct properties,
        # like "stair" or "exit" in a stair/egress-heavy document, is a
        # weaker signal than one that appears in only a handful).
        _prop_bm25 = BM25Index()
        _prop_bm25.add_documents([{"content": (r.property or ""), "idx": i} for i, r in enumerate(rows)])

        def _prop_content_words(prop):
            return _tokenize_for_match(prop or "")

        # Require the matched row's `property` key to overlap the query on
        # at least one non-qualifier word. BM25 alone can surface a
        # topically-related but wrong-field row; this keeps the lookup
        # conservative about what counts as "this question is about that fact".
        candidates = []
        for idx, score in hits:
            row = rows[idx]
            if query_content & _prop_content_words(row.property):
                candidates.append((row, score))
        if not candidates:
            return None

        # Disambiguate: prefer the unqualified (empty parent_context) row
        # unless the query itself names the SPECIFIC condition a qualified
        # row covers. The naive version of this check -- "do any words in
        # parent_context appear in the query" -- was wrong in practice: a
        # query like "minimum guard height" shares the word "guard" with
        # EVERY guard-height variant's parent_context (including the
        # handrail-reduction one), so it always looked like a "match"
        # whether or not the query actually asked about that condition.
        # Fix: only count a word as a real condition signal if it is NOT
        # part of the shared vocabulary these candidates' own `property`
        # names already have in common (guard/height/minimum/maximum, etc.)
        # -- a word unique to one or two candidates' property names (like
        # "handrail") is a real distinguisher; a word every variant shares
        # is just the topic, not the condition.
        from collections import Counter
        _prop_word_counts = Counter()
        for _row, _ in candidates:
            _prop_word_counts.update(set(re.findall(r"[a-z0-9]+", (_row.property or "").lower())))
        _generic_words = {w for w, n in _prop_word_counts.items() if n > 1}

        # Bug (2026-10-09, found via B80/B81/B97): a "Total"/"Grand Total"/
        # "Overall"/"Summary" row (e.g. "Total Units", "Grand Total BUA") can
        # legitimately win a tie on raw word overlap against the specific
        # row the query actually asked for (e.g. "Apartment Units (Tower
        # A3)"), because the query's own content words ("units", "bua") are
        # a subset of both. That's correct when the query itself is asking
        # for the total/aggregate -- the 2026-10-08 "Total Units" fix above
        # depends on that case still winning -- but wrong when the query
        # names a SPECIFIC item (a tower, a unit type, a floor) and the
        # aggregate row just happens to share its generic vocabulary.
        # Demote an aggregate-named row to its own worst sub-tier unless the
        # query itself uses aggregate language, so a specific match always
        # wins when one exists, while an aggregate row remains available as
        # a fallback if it's the only candidate.
        _AGGREGATE_WORD_RE = re.compile(r"\b(total|grand\s*total|overall|summary|sum)\b", re.I)
        query_asks_aggregate = bool(_AGGREGATE_WORD_RE.search(query))

        def _rank(item):
            row, score = item
            qualified = bool((row.parent_context or "").strip())
            condition_words = set(re.findall(r"[a-z0-9]+", (row.parent_context or "").lower())) - _generic_words
            matches_condition = qualified and bool(condition_words & query_words)
            # Highest priority: a qualified row whose SPECIFIC condition the
            # query actually names. Next: an unqualified default row. Last:
            # a qualified row the query didn't ask about.
            tier = 0 if matches_condition else (1 if not qualified else 2)
            is_aggregate_row = bool(_AGGREGATE_WORD_RE.search(row.property or ""))
            if is_aggregate_row and not query_asks_aggregate:
                tier += 3
            # Within a tier, rank by (in priority order):
            #  1. Whether the row even HAS a value -- a property with an
            #     empty `value` is rarely the right answer to a "what is
            #     the value of X" question (it's usually a qualitative/
            #     descriptive fact that happened to match on vocabulary).
            #  2. The overlap RATIO: what fraction of the property name's
            #     own (IDF-weighted) content is explained by the query,
            #     rather than raw overlap count or sum. A short property
            #     made entirely of generic words ("Maximum Permitted
            #     Height") can otherwise look like a perfect, trivial match;
            #     a longer, genuinely specific property ("Stair Riser
            #     Height Range") loses on raw overlap size alone just for
            #     having one extra word. Ratio normalizes for that.
            #  3/4. Raw IDF-sum and overlap count, as further tiebreaks.
            #  5. Raw BM25 content score, as the final fallback.
            # All four of the live-benchmark failure cases (2026-10-08:
            # guard height, riser height, egress door force, exit
            # separation vs. tree separation) were traced by hand against
            # this exact formula before it was deployed.
            # Rank primarily on the ABSOLUTE combined IDF of the overlapping
            # words (a strong, specific match should win outright), not the
            # overlap RATIO alone -- ratio-first was tried and reverted
            # (2026-10-08 benchmark) because it let a short property made
            # entirely of matched words (e.g. "Total Units", fully matching a
            # query about "total units of 1-bedroom type") beat a longer,
            # genuinely more specific property with one unmatched word (e.g.
            # "1 Bedroom Units (Required)"). Ratio is kept only as a
            # tiebreak, with the empty-value penalty, raw overlap count and
            # raw BM25 score as further tiebreaks after that.
            prop_content = _prop_content_words(row.property)
            overlap = query_content & prop_content
            overlap_idf = sum(_prop_bm25.idf.get(w, 0.0) for w in overlap)
            total_idf = sum(_prop_bm25.idf.get(w, 0.0) for w in prop_content) or 1e-9
            ratio = overlap_idf / total_idf
            no_value = 0 if str(row.value or "").strip() else 1
            return (tier, -overlap_idf, no_value, -ratio, -len(overlap), -score)
        candidates.sort(key=_rank)

        # Phase 3.1 (2026-10-09): some documents genuinely restate "the same"
        # fact under several different tables with DIFFERENT values each --
        # e.g. a per-floor area table appearing three times as "BUILT-UP
        # AREA BREAKDOWN", "GROSS FLOOR AREA BREAKDOWN" and "NET SELLABLE
        # AREA BREAKDOWN", each giving a different number for "2nd Floor".
        # Picking just one of these (the heuristic rank or the LLM rerank
        # both must commit to a single row) silently answers with only one
        # of several equally valid numbers and never tells the user the
        # other two exist. Found via the Phase 3 benchmark (2026-10-09):
        # floor-area questions answered inconsistently depending on which
        # of these tables' rows happened to survive extraction. Detect this
        # BEFORE spending an LLM call on re-ranking: if 2+ of the top-tier
        # candidates come from different named tables and disagree on
        # value, that is not noise to rank away -- it is the real content
        # of the document, and the honest answer discloses all of them.
        best_tier = _rank(candidates[0])[0]
        top_tier = [(row, score) for row, score in candidates if _rank((row, score))[0] == best_tier]
        # Require each candidate to be a genuinely STRONG match on its own
        # terms, not merely "passed the lexical gate" -- the gate only
        # requires ONE shared non-qualifier word with the query, which is
        # loose enough to admit a weakly-related row (a unit's balcony size,
        # a different document's unrelated floor note) alongside the true
        # multi-table match. Found via re-test after the 2026-10-09 memory
        # rebuild: a genuine "2nd Floor" disclosure pulled in an unrelated
        # "1 Bedroom Unit Area" row and a different-document "Ground Floor"
        # note just because they all share the word "floor" or "area" with
        # the query. Fix: only admit a candidate within a comfortable margin
        # of the top candidate's own overlap strength (its match quality is
        # comparable, not just "also matched something").
        best_overlap_idf = -_rank(top_tier[0])[1]
        strong_tier = [
            (row, score) for row, score in top_tier
            if best_overlap_idf <= 1e-9 or (-_rank((row, score))[1]) >= 0.6 * best_overlap_idf
        ]
        # Additionally require the candidates to actually be about the SAME
        # specific thing as each other, not just each individually relevant
        # to the query -- compare property names directly (not via the
        # query), since two rows can each share a word with the query
        # without sharing anything with EACH OTHER beyond that one word.
        def _prop_tokens(row):
            return _tokenize_for_match(row.property or "")
        anchor_tokens = _prop_tokens(strong_tier[0][0]) if strong_tier else set()
        by_table = {}
        for row, score in strong_tier[:5]:
            table_name = (row.table or "").strip()
            val = str(row.value or "").strip()
            if not table_name or not val:
                continue
            if len(anchor_tokens & _prop_tokens(row)) < 2:
                continue
            by_table.setdefault(table_name, (row, score))
        distinct_values = {v for (r, _s) in by_table.values() for v in [str(r.value or "").strip()]}
        if len(by_table) > 1 and len(distinct_values) > 1:
            parts = []
            sources = []
            all_verify_ok = True
            for table_name, (row, _score) in sorted(by_table.items()):
                doc_path = None
                import db as _db2
                with _db2.SessionLocal() as _s2:
                    d_row2 = _s2.query(_db2.Document).filter_by(id=row.document_id).first()
                    doc_path = d_row2.path if d_row2 else None
                if not doc_path:
                    all_verify_ok = False
                    break
                page_text2 = _cached_page_text(doc_path)
                quote_norm2 = _normalize(row.evidence_quote)
                page_norm2 = page_text2.get(row.page, "")
                if quote_norm2 not in page_norm2 and not any(quote_norm2 in t for t in page_text2.values()):
                    all_verify_ok = False
                    break
                unit_part = f" {row.unit}".rstrip() if row.unit else ""
                parts.append(f"{table_name}: {row.value}{unit_part}")
                sources.append({"source": row.doc, "page": row.page})
            if all_verify_ok and parts:
                disclosure = (
                    "This document states different values for this depending on which table it's "
                    "drawn from: " + "; ".join(parts) + "."
                )
                evidence_text = "\n".join(
                    f"[SOURCE: {r.doc} | PAGE {r.page}]\n{r.evidence_quote}"
                    for _table_name, (r, _score) in sorted(by_table.items())
                )
                published, issues = guarded_answer(
                    disclosure + " " + " ".join(f"[SOURCE: {s['source']} | PAGE {s['page']}]" for s in sources),
                    evidence_text,
                    sources,
                )
                if not issues:
                    return {"answer": published, "sources": sources}
                # guard rejected the composed disclosure (e.g. citation
                # bookkeeping mismatch) -- fall through to the normal
                # single-answer path below rather than lose the lookup
                # entirely over a presentation-only failure.

        # Phase 3 (2026-10-09): when the lexical gate leaves more than one
        # candidate, ask the REASONING_LLM to pick the one that actually
        # answers the question, instead of trusting the IDF/BM25 heuristic
        # ranking alone. Proposal doc: "Phase 3 Proposal - LLM Re-ranking for
        # Memory Lookup". The heuristic ranking (above) earns its keep on
        # cost/latency for the common single-candidate case and is left
        # untouched; this only runs on the genuinely ambiguous ~10-20% of
        # queries where 2+ candidates survived the gate. A margin/threshold
        # check on the heuristic's own score was tried first and rejected --
        # verified-correct answers can tie at the exact same score as
        # verified-wrong ones (duplicate-extracted rows, or two equally
        # "generic" property names), so no threshold on that signal
        # separates good from bad. The LLM can read what each candidate
        # actually SAYS, which no word-overlap score can do.
        best_row, best_score = candidates[0]
        if len(candidates) > 1:
            reranked = _llm_rerank(query, [c[0] for c in candidates[:5]])
            if reranked is _NO_MATCH:
                logger.info("document_memory: LLM re-ranker found no matching candidate for '{}', falling through to RAG", query)
                return None
            if reranked is not None:
                best_row = reranked
            # else: rerank call itself failed/was inconclusive -- keep the
            # heuristic's top pick rather than discard an otherwise-working
            # answer over a transient LLM hiccup.

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
            logger.info("document_memory: query-time exact-page verification failed for '{}'", best_row.property)
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
