"""Quote-verified answer fallback (2026-10-21).

When the normal publication checks reject a draft, the model is asked for the
facts that answer the question, each with a VERBATIM quote and its page. Code
then checks every quote against the cited page text and every number/name in
each fact against its quote. Only facts that pass are published, each with
its quote and citation, so the user can check them at a glance. No fact passes
on the model's word alone."""
import json
import re

_DEG = re.compile(r"(?<=\d)\s?[Ooº°]\s?C\b")


def _norm(text):
    text = _DEG.sub("\u00b0C", str(text or ""))
    text = re.sub(r"(?<=\d)[, ](?=\d{3}(?!\d))", "", text)          # 2,044 / 2 044 -> 2044 (one token)
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2212", "-")
    text = re.sub(r"[^\w.\-/\u00b0%\u00b1+&]+", " ", text)          # drop brackets, colons, |, quotes, bullets
    text = re.sub(r"(?<!\w)[.\-/]+|[.\-/]+(?!\w)", " ", text)      # stray punctuation, keep 620.75 / 1-hour
    return re.sub(r"\s+", " ", text).strip().casefold()


def _colocated(quote, page, slack=3.0):
    """Table pages: every token of the quote occurs in ONE short window of the
    page (at most `slack` times the quote length). Proves the label and value
    sit together in the source even when the PDF scatters table cells."""
    q = _norm(quote).split()
    p = _norm(page).split()
    if len(q) < 2 or not p:
        return False
    need = {}
    for t in q:
        need[t] = need.get(t, 0) + 1
    width = max(int(len(q) * slack), len(q) + 6)
    for start in range(len(p)):
        if p[start] not in need:
            continue
        window = p[start:start + width]
        if all(window.count(t) >= c for t, c in need.items()):
            return True
    return False


_BOX = re.compile(r"([\u2610\u2612\u2611\u2713\u2714])\s*([A-Za-z][^\u2610\u2612\u2611\n]{0,60})")
_NEG = re.compile(r"\b(not|no|none|neither|nor|un\w+|pending|blank|empty)\b", re.I)


def _checkbox_conflict(statement, quote, page):
    """Forms: a statement may not assert an option that is unticked (\u2610) in the
    quote/page and never ticked (\u2612/\u2611). 'Approved' on '\u2610 Approved' is false."""
    src = quote + "\n" + page
    if "\u2610" not in src:
        return ""
    ticked, unticked = set(), set()
    for m in _BOX.finditer(src):
        words = m.group(2).split()
        if not words:
            continue
        opt = _norm(words[0])
        (ticked if m.group(1) != "\u2610" else unticked).add(opt)
    st = _norm(statement)
    if _NEG.search(statement):
        return ""          # "has not been approved" / "no box is ticked" is fine
    in_quote = {_norm(m.group(2).split()[0]) for m in _BOX.finditer(quote) if m.group(2).split()}
    for opt in (unticked - ticked) & in_quote:
        stem = opt[:6]
        if len(opt) >= 3 and re.search(r"(?<!\w)" + re.escape(stem), st):
            return opt
    return ""


def _nums(text):
    return {n.replace(",", "") for n in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", str(text or ""))}


def _names(text):
    out = []
    for m in re.finditer(r"\b[A-Z][A-Za-z&'-]+(?:\s+[A-Z][A-Za-z&'.-]+)+", str(text or "")):
        w = m.group().split()
        if w[0].casefold() in {"the", "this", "that", "based", "according", "in", "on", "for", "a", "an"}:
            w = w[1:]
        if len(w) >= 2:
            out.append(" ".join(w))
    return out


def _log(reason, st, qt, pg):
    try:
        from loguru import logger
        logger.info("Verified-extract rejected ({}): {!r} quote={!r} page={}", reason, st[:200], qt[:200], pg)
    except Exception:
        pass


def _chat_json(url, model, prompt, num_ctx=16384):
    import httpx
    def call(fmt):
        body = {"model": model, "stream": False, "think": False,
                "options": {"temperature": 0, "num_ctx": num_ctx, "num_predict": 2048},
                "messages": [{"role": "user", "content": prompt}]}
        if fmt:
            body["format"] = "json"
        r = httpx.post(url.rstrip("/") + "/api/chat", json=body, timeout=240)
        r.raise_for_status()
        return str((r.json().get("message") or {}).get("content") or "")
    raw = ""
    for fmt in (True, False):
        raw = call(fmt)
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            data = json.loads(m.group()) if m else None
        except ValueError:
            data = None
        if isinstance(data, dict) and ("facts" in data or "found" in data):
            return data
        try:
            from loguru import logger
            logger.info("Verified-extract raw reply (json={}, ctx={}, prompt={} chars): {!r}", fmt, num_ctx, len(prompt), raw[:400])
        except Exception:
            pass
    return {}


def verified_answer(url, model, question, evidence, sources, max_chars=24000, page_cap=6000, whole_document=False):
    """Return (answer_text, n_facts) or (None, 0) when nothing could be verified
    and the evidence does not support saying 'not found' either."""
    from intelligence.answer_guard import _excerpts_by_page
    pages = _excerpts_by_page(evidence or "")
    allowed = {(str(s.get("source") or s.get("filename") or ""), str(s.get("page")).upper())
               for s in (sources or []) if isinstance(s, dict)}
    pages = {k: v for k, v in pages.items() if v.strip() and (not allowed or k in allowed or k[1] != "UNPAGINATED")}
    if not pages:
        return None, 0
    blocks, used = [], 0
    for (fn, pg), body in pages.items():
        compact = re.sub(r"[ \t]+", " ", body)
        compact = re.sub(r"\n\s*\n+", "\n", compact).strip()
        chunk = f"[SOURCE: {fn} | PAGE {pg}]\n{compact[:page_cap]}\n"
        if used + len(chunk) > max_chars:
            break
        blocks.append(chunk)
        used += len(chunk)
    prompt = (
        "Answer the QUESTION using ONLY the EXCERPTS. Return JSON:\n"
        '{"found": true|false, "facts": [{"statement": "...", "quote": "...", "file": "...", "page": "..."}]}\n'
        "Forms: \u2610 is an EMPTY (unticked) box and \u2612 is a TICKED box - an option is only selected "
        "if its box is \u2612; if no box is ticked, say so. "
        "Rules: each statement is one short fact that answers the question. If one fact needs two source lines, "
        "add them as \"quotes\": [\"...\", \"...\"]. 'quote' must be copied "
        "CHARACTER-FOR-CHARACTER from the excerpt of that file/page (one sentence or table row, max 300 chars) "
        "and must contain every number and name used in the statement. If the excerpts do not answer the "
        "question, return {\"found\": false, \"facts\": []}. Do not use outside knowledge. Table text may be "
        "split one value per line: then quote the label and its value exactly as they appear, in order "
        "(e.g. \"NURSERY 620.75\"). Answer exactly what is asked - no extra facts.\n\n"
        f"QUESTION: {question}\n\nEXCERPTS:\n" + "\n".join(blocks) +
        f"\n\n=== END OF EXCERPTS ===\nNow answer ONLY this question: {question}\n"
        'Reply with JSON only, exactly this shape: {"found": true|false, "facts": [{"statement": "...", '
        '"quote": "<copied exactly from one excerpt>", "file": "...", "page": "..."}]}')
    try:
        data = _chat_json(url, model, prompt, num_ctx=min(32768, max(8192, len(prompt) // 2 + 3000)))
    except Exception:
        return None, 0
    facts = data.get("facts") if isinstance(data, dict) else None
    try:
        from loguru import logger
        logger.info("Verified-extract: {} candidate fact(s), found={}", len(facts or []), data.get("found") if isinstance(data, dict) else None)
    except Exception:
        pass
    good = []
    for f in facts or []:
        if not isinstance(f, dict):
            continue
        st = str(f.get("statement") or "").strip()
        qts = [str(x).strip() for x in (f.get("quotes") or []) if str(x).strip()] if isinstance(f.get("quotes"), list) else []
        qt = str(f.get("quote") or "").strip()
        if qts and not qt:
            qt = qts[0]
        extra = [x for x in qts if x != qt]
        fn, pg = str(f.get("file") or "").strip(), str(f.get("page") or "").strip().upper()
        if not st or len(qt) < 8:
            continue
        key = next((k for k in pages if k[1] == pg and (not fn or k[0].casefold() == fn.casefold())), None)
        if key is None:  # wrong page given: accept only if the quote is on exactly one page
            hits = [k for k, b in pages.items() if _norm(qt) in _norm(b)]
            key = hits[0] if len(hits) == 1 else None
        table_match = False
        if key is not None and _norm(qt) not in _norm(pages[key]) and _colocated(qt, pages[key]):
            table_match = True
        if key is None or (_norm(qt) not in _norm(pages[key]) and not table_match):
            _log("quote not on page", st, qt, pg); continue
        # Extra quotes (a fact spanning two lines) must each be on the same page too.
        if extra and not all(_norm(x) in _norm(pages[key]) or _colocated(x, pages[key]) for x in extra):
            _log("extra quote not on page", st, " || ".join(extra), pg); continue
        if extra:
            qt = qt + " ... " + " ... ".join(extra)
        _cb = _checkbox_conflict(st, qt, pages[key])
        if _cb:
            _log("asserts unticked option '%s'" % _cb, st, qt, pg); continue
        if not _nums(st) <= _nums(qt):
            _log("number not in quote", st, qt, pg); continue
        qn = _norm(qt)
        if any(_norm(n) not in qn and _norm(n) not in _norm(question) for n in _names(st)):
            _log("name not in quote", st, qt, pg); continue
        if any(g[0].casefold() == st.casefold() or (g[1] == qt and g[2] == key) for g in good):
            continue   # duplicate fact
        good.append((st, qt, key, table_match))
    if good:
        lines = []
        for st, qt, (fn, pg), tbl in good[:8]:
            note = " _(table values found together on this page - check the column on the page)_" if tbl else ""
            lines.append(f"- {st} [SOURCE: {fn} | PAGE {pg}]{note}\n  > \"{re.sub(chr(10), ' ', qt)}\"")
        head = ("From the document (each point checked against the cited page):" if any(g[3] for g in good)
                else "From the document (each point checked word-for-word against the cited page):")
        return head + "\n\n" + "\n".join(lines), len(good)
    if isinstance(data, dict) and data.get("found") is False and (whole_document or not facts):
        return "I could not find this in the uploaded documents.", 0
    return None, 0
