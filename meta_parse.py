"""meta_parse.py — Extract construction-drawing metadata from a filename.

Pure standard-library (regex only), no external deps, so it runs anywhere.
Goal: derive a *stable drawing identity* and its *revision* so the platform can
tell current drawings apart from superseded ones, and surface the revision in
answers and citations.

We deliberately do NOT try to guess a canonical "drawing number" token (naming
schemes vary too much to be safe). Instead the drawing's identity is the
filename with the revision token removed. Two files that differ only by their
revision token therefore share the same base_id and are treated as revisions of
one drawing.
"""
import os
import re

# Revision patterns, tried in priority order. Each returns the revision label.
# Group 1 must be the revision value.
_REV_PATTERNS = [
    # trailing parentheses just before the extension: (A) (C1) (03)
    (re.compile(r"\(\s*(?:rev[\s\-_]*)?([A-Za-z]{1,2}\d{0,2}|\d{1,3})\s*\)\s*$"), "paren"),
    # explicit "rev": Rev C, Rev-C, RevC, REV 03, rev_B
    (re.compile(r"[\-_\s]rev[\s\-_]*([A-Za-z]{1,2}\d{0,2}|\d{1,3})\s*$", re.I), "rev"),
    # R-number: R0 R1 R12 (word-boundaried, at end)
    (re.compile(r"[\-_\s]R(\d{1,3})\s*$", re.I), "rnum"),
    # trailing single/double letter after separator: -A _C  (risky, lowest priority)
    (re.compile(r"[\-_]([A-Za-z]{1,2})\s*$"), "sfx"),
]

_DOCTYPE_RULES = [
    ("schedule", re.compile(r"\b(sch|sched|schedule)\b", re.I)),
    ("legend",   re.compile(r"\b(legend|key|abbrev)\b", re.I)),
    ("spec",     re.compile(r"\b(spec|specification)\b", re.I)),
    ("report",   re.compile(r"\b(rpt|report|calc|calculation)\b", re.I)),
    ("drawing",  re.compile(r"\b(dwg|drawing|dr|plan|elevation|section|detail)\b", re.I)),
]

# discipline hints from common code tokens in filenames
_DISC_RULES = [
    ("Architecture", re.compile(r"\b(ar|arch|architect)\b", re.I)),
    ("Interior",     re.compile(r"\b(id|int|interior)\b", re.I)),
    ("Structural",   re.compile(r"\b(st|str|struct|structural)\b", re.I)),
    ("MEP",          re.compile(r"\b(me|mep|mech|elec|plumb|hvac)\b", re.I)),
    ("Landscape",    re.compile(r"\b(lx|land|landscape)\b", re.I)),
    ("Civil",        re.compile(r"\b(cv|civil)\b", re.I)),
]


def _norm_rev(val, kind):
    v = val.strip().upper()
    if kind == "rnum":
        return "R" + v
    return v


def parse_drawing_meta(filename):
    """Return {filename, stem, ext, base_id, revision, revision_kind, doctype,
    discipline_hint} for a filename. revision is None when none is detected."""
    filename = os.path.basename(filename or "")
    stem, ext = os.path.splitext(filename)
    ext = ext.lower().lstrip(".")

    revision, revision_kind, base_stem = None, None, stem
    for rx, kind in _REV_PATTERNS:
        m = rx.search(stem)
        if not m:
            continue
        # avoid mistaking a 4-digit sheet number chunk as a rev via 'sfx'
        cand = m.group(1)
        if kind == "sfx" and len(cand) == 1 and cand.isdigit():
            continue
        revision = _norm_rev(cand, kind)
        revision_kind = kind
        base_stem = (stem[:m.start()] + stem[m.end():]).strip(" -_")
        break

    base_id = re.sub(r"[\s\-_]+", "-", base_stem).strip("-").upper()

    doctype = None
    for name, rx in _DOCTYPE_RULES:
        if rx.search(stem):
            doctype = name
            break
    if doctype is None and ext in ("dwg", "dxf"):
        doctype = "drawing"
    elif doctype is None and ext in ("xlsx", "xls", "csv"):
        doctype = "schedule"

    discipline = None
    for name, rx in _DISC_RULES:
        if rx.search(stem):
            discipline = name
            break

    return {
        "filename": filename,
        "stem": stem,
        "ext": ext,
        "base_id": base_id,
        "revision": revision,
        "revision_kind": revision_kind,
        "doctype": doctype,
        "discipline_hint": discipline,
    }


def _rev_sort_key(rev):
    """Sortable key so latest revision wins. Handles letters (A<B<C),
    R-numbers (R0<R1<R12), and plain numbers. Unknown/None sorts lowest."""
    if not rev:
        return (0, 0, "")
    r = rev.upper()
    if r.startswith("R") and r[1:].isdigit():
        return (2, int(r[1:]), r)
    if r.isdigit():
        return (2, int(r), r)
    # letters, possibly letter+digit like C1
    m = re.match(r"^([A-Z]{1,2})(\d*)$", r)
    if m:
        letters, num = m.group(1), m.group(2)
        letter_val = 0
        for ch in letters:
            letter_val = letter_val * 26 + (ord(ch) - 64)
        return (1, letter_val * 100 + (int(num) if num else 0), r)
    return (0, 0, r)


def group_revisions(docs):
    """docs: iterable of dicts with at least 'filename'. Returns
    {base_id: {"revisions": [...], "latest": rev_or_None, "items": [meta,...]}}
    Only groups where more than one distinct revision exists are 'superseded'
    situations, but all groups are returned."""
    groups = {}
    for d in docs:
        meta = parse_drawing_meta(d.get("filename", ""))
        g = groups.setdefault(meta["base_id"], {"items": [], "revisions": []})
        g["items"].append(meta)
        if meta["revision"] and meta["revision"] not in g["revisions"]:
            g["revisions"].append(meta["revision"])
    for g in groups.values():
        revs = g["revisions"]
        g["latest"] = max(revs, key=_rev_sort_key) if revs else None
        g["multi"] = len(revs) > 1
    return groups
