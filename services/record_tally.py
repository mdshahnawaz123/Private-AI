"""Whole-document record tally (2026-10-22).

Issue logs, registers, transmittals and inspection lists are many repeated
records ("Status / Open", "Assigned to / X", "Level / Ground Floor"). Counting
questions ("how many are open?", "who has the most?") cannot be answered by
quoting one page; they need every record. This module finds the repeated field
labels in the extracted text, tallies every value across ALL pages in code,
and answers counting questions from those exact counts. The model is not
involved, so the numbers are deterministic.
"""
import collections
import re

COUNT_Q = re.compile(
    r"\b(how\s+many|count|number\s+of|tally|breakdown|distribution|most|least|fewest|highest|lowest|"
    r"top\s+\d*|per\s+\w+|by\s+(?:status|assignee|level|type|discipline|stage|category|company|priority))\b", re.I)
_STOP = {"what", "which", "who", "how", "many", "the", "are", "is", "of", "in", "and", "or", "a", "an",
         "this", "these", "that", "issues", "issue", "items", "item", "records", "record", "document",
         "number", "count", "has", "have", "with", "most", "least", "there", "for", "by", "per", "each",
         "total", "all", "do", "does", "to", "on"}


def _clean_value(v):
    v = re.sub(r"\s+", " ", v).strip()
    return v


def _short_label(line):
    s = line.strip()
    if not (2 <= len(s) <= 32) or len(s.split()) > 4:
        return False
    if re.search(r"\d{2,}|[.:;!?]$", s) or s.startswith(("#", "(", "-", "—")):
        return False
    return bool(re.match(r"[A-Za-z]", s))


def tally(text, min_repeats=5):
    """Return (fields, n_pages): fields = {label: Counter(values)} for labels that repeat."""
    pages = re.split(r"\[PAGE \d+\]\n", text)
    n_pages = max(1, len([p for p in pages if p.strip()]))
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("[PAGE ")]
    short = collections.Counter(l for l in lines if _short_label(l))
    cands = {l for l, c in short.items() if c >= min_repeats}
    pairs = collections.defaultdict(collections.Counter)
    for i, l in enumerate(lines[:-1]):
        if l in cands:
            pairs[l][_clean_value(lines[i + 1])] += 1
    # A repeated short line that is mostly a VALUE of another candidate (e.g. "Open" after
    # "Status", "Ground Floor" after "ECD_Level") is a value, not a label.
    value_of = collections.Counter()
    for lab, cnt in pairs.items():
        if len(cnt) >= 2:                      # a real field has varying values
            for v, c in cnt.items():
                value_of[v] += c
    labels = {l for l in cands if value_of[l] < 0.5 * short[l]}
    fields = {}
    for lab in labels:
        cnt = collections.Counter({v: c for v, c in pairs[lab].items() if v not in labels or value_of[v] >= 0.5 * short.get(v, 1)})
        if cnt:
            fields[lab] = cnt
    for m in re.finditer(r"(?m)^\s*([A-Za-z][\w /&-]{1,30}?)\s*:\s*(\S[^\n]{0,80})$", text):
        fields.setdefault(m.group(1).strip(), collections.Counter())[_clean_value(m.group(2))] += 1
    out = {}
    for lab, cnt in fields.items():
        total = sum(cnt.values())
        if total < min_repeats or ">" in lab:
            continue
        if len(cnt) > 0.6 * total and total > 10:
            continue          # descriptions / IDs: not countable
        if len(cnt) == 1 and total >= 0.8 * n_pages and n_pages >= 5:
            top = next(iter(cnt))
            if re.search(r"page|created by|copyright|\u00a9|confidential", top, re.I):
                continue      # page header/footer boilerplate
        out[lab] = cnt
    return out, n_pages


def _words(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _STOP and len(w) > 1}


def _variants(w):
    return {w, w.rstrip("s"), w + "s", w.rstrip("ed"), w + "ed", w.rstrip("d")}


def answer(question, text, filename, min_repeats=5):
    """Markdown answer for a counting question, or None if no field fits."""
    if not COUNT_Q.search(question or ""):
        return None
    fields, n_pages = tally(text, min_repeats)
    if not fields:
        return None
    qw = _words(question)
    qwv = set().union(*(_variants(w) for w in qw)) if qw else set()
    ql = question.lower()
    scored = []
    for lab, cnt in fields.items():
        lw = _words(lab)
        s = 3.0 * len(lw & qwv)
        val_hits = [v for v in cnt if len(v) >= 3 and re.search(r"(?<!\w)" + re.escape(v.lower()) + r"(?!\w)", ql)]
        s += 4.0 * len(val_hits)
        if s > 0:
            scored.append((s, lab, cnt, val_hits))
    if not scored:
        return None
    # Only documents that really are repeated records: the chosen field must share its
    # record count with at least 2 other fields (Status/Assigned to/Level all = 198).
    totals = {lab: sum(cnt.values()) for lab, cnt in fields.items()}
    def in_record_group(lab):
        t = totals[lab]
        return t >= 10 and sum(1 for o, ot in totals.items() if o != lab and abs(ot - t) <= 0.05 * t) >= 2
    scored = [x for x in scored if in_record_group(x[1])]
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    best = scored[0][0]
    chosen = [x for x in scored if x[0] >= best * 0.75][:2]
    # Only registers / issue logs / transmittals are "records" documents (about one record per page
    # or more). In a report - a 700-page geotechnical report with a few repeated table labels - a count
    # like "how many boreholes" is stated in the text, so leave it to the normal reader.
    if max(sum(c[2].values()) for c in chosen) < 0.5 * n_pages:
        return None
    parts = [f"Counted in code across **all {n_pages} pages** of **{filename}** (every record, not a sample):\n"]
    for _, lab, cnt, hits in chosen:
        total = sum(cnt.values())
        rows = cnt.most_common()
        if hits:
            rows = [(v, cnt[v]) for v in hits] + [(v, c) for v, c in rows if v not in hits]
        shown = rows[:10]
        parts.append(f"**{lab}** ({total} records)\n\n| {lab} | Count |\n|---|---|")
        for v, c in shown:
            parts.append(f"| {v} | {c} |")
        if len(rows) > len(shown):
            parts.append(f"| _{len(rows) - len(shown)} other values_ | {sum(c for _, c in rows[len(shown):])} |")
        parts.append("")
    parts.append("_Counts come from the extracted text; a record whose field could not be read is not counted._")
    return "\n".join(parts)
