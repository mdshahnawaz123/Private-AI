"""Final publication checks for deterministic early-answer shortcuts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


_READY_STATUSES = {"ready", "ready_with_warnings", "verified", "published"}


def source_context_for_sources(documents, sources):
    """Rebuild native source/page evidence for an early deterministic answer.

    The caller passes only documents already filtered by project permissions.
    A shortcut citation is eligible only when its source file, current source
    hash (when recorded), and exact page are available in that set. Visual
    observations remain explicitly unverified.
    """
    by_name = {str(doc.get("filename") or ""): doc for doc in documents
               if isinstance(doc, dict) and doc.get("filename")}
    context = []
    allowed = []
    seen = set()
    for item in sources:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("source") or item.get("filename") or "")
        raw_page = item.get("page")
        if not filename or raw_page is None:
            continue
        try:
            page_number = int(raw_page)
        except (TypeError, ValueError):
            continue
        key = (filename, str(page_number))
        if key in seen:
            continue
        seen.add(key)
        doc = by_name.get(filename)
        if not doc or doc.get("status", "ready") not in _READY_STATUSES:
            continue
        source_path = Path(str(doc.get("path") or ""))
        index_path = Path(str(source_path) + ".index.json")
        try:
            metadata = json.loads(index_path.read_text(encoding="utf-8"))
            if metadata.get("truncated") or metadata.get("processing_complete") is False:
                continue
            expected_hash = metadata.get("source_sha256")
            if expected_hash:
                digest = hashlib.sha256()
                with source_path.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest().casefold() != str(expected_hash).casefold():
                    continue
            page = next((p for p in metadata.get("pages", [])
                         if str(p.get("page")) == str(page_number)), None)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
        if page is None:
            continue
        body = "\n\n".join(str(page.get(field) or "") for field in ("tables", "text") if page.get(field))
        visual = "\n".join(str(page.get(field) or "") for field in ("vision", "inspection_text") if page.get(field))
        if visual:
            body += "\n[UNVERIFIED EXTRACTION; REVIEW_REQUIRED]\n" + visual
        context.append(f"[SOURCE: {filename} | PAGE {page_number}]\n{body}")
        allowed.append({"source": filename, "page": page_number})
    return allowed, "\n\n====\n\n".join(context)


def validate_precomputed_answer(answer, documents, sources, question):
    """Normalize and validate an exact/memory answer at the stream boundary."""
    from intelligence.answer_guard import guarded_answer
    from intelligence.citation_identity import (
        append_source_qualifications, prepare_citations, resolve_citations,
    )

    allowed, evidence = source_context_for_sources(documents, sources)
    _model_context, identities = prepare_citations(evidence, allowed)
    resolved = resolve_citations(str(answer or ""), identities)
    qualified = append_source_qualifications(resolved, evidence, allowed)
    published, issues = guarded_answer(qualified, evidence, allowed, question=question)
    return published, issues, allowed
