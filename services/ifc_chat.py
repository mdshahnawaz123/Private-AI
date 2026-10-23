"""Deterministic chat answers from the IFC index (counts, areas, volumes, rooms, storeys,
phases, types).  `try_answer` returns markdown, or None when the question is not a BIM
data question (so the normal document RAG pipeline handles it)."""
import re
from services import ifc_query as Q

ELEMENTS = [
    (r"\bdoors?\b", "IFCDOOR", "doors"), (r"\bwindows?\b", "IFCWINDOW", "windows"),
    (r"\bwalls?\b", "IFCWALL", "walls"), (r"\b(slabs?|floors?\b(?! plan))", "IFCSLAB", "slabs / floors"),
    (r"\bcolumns?\b", "IFCCOLUMN", "columns"), (r"\bbeams?\b", "IFCBEAM", "beams"),
    (r"\bstairs?\b|\bstair ?flights?\b", "IFCSTAIRFLIGHT", "stair flights"), (r"\brailings?\b", "IFCRAILING", "railings"),
    (r"\broofs?\b", "IFCROOF", "roofs"), (r"\bplates?\b", "IFCPLATE", "plates"), (r"\bmembers?\b", "IFCMEMBER", "members"),
    (r"\bfurniture\b|\bfurnishings?\b", "IFCFURNISHINGELEMENT", "furniture"),
    (r"\bceilings?\b", "IFCCOVERING", "coverings / ceilings"), (r"\bproxies\b|\bproxy\b|\bequipment\b", "IFCBUILDINGELEMENTPROXY", "generic elements / equipment"),
    (r"\brooms?\b|\bspaces?\b|\bareas? schedule\b", "IFCSPACE", "rooms / spaces"),
]
BIM_WORDS = r"\b(ifc|bim|revit|model|3d|take-?off|qto|quantit(y|ies)|schedule)\b"
COUNT_WORDS = r"\b(how many|count|number of|total|sum|area|volume|length|list|schedule|quantit(y|ies)|take-?off|breakdown|per|by|show|what|which)\b"
DOC_WORDS = r"\b(code|specification|spec|required|requirement|standard|clause|section|pdf|page|drawing note|approved|submittal|rfi)\b"


def _fmt(n):
    return f"{n:,.2f}".rstrip("0").rstrip(".") if isinstance(n, float) else f"{n:,}"


def _table(rows, cols, heads):
    out = ["| " + " | ".join(heads) + " |", "|" + "|".join("---" for _ in heads) + "|"]
    for r in rows:
        out.append("| " + " | ".join(_fmt(r[c]) if isinstance(r[c], (int, float)) and r[c] is not None else str(r[c] if r[c] is not None else "-") for c in cols) + " |")
    return "\n".join(out)


def _storey_filter(project, ql, summ):
    names = sorted([s["storey"] for s in summ["storeys"] if s["storey"]], key=len, reverse=True)
    for n in names:
        if re.search(r"(?<![\w])" + re.escape(n.lower()) + r"(?![\w])", ql):
            return n
    m = re.search(r"\b(?:level|storey|story|floor)\s*0?(\d{1,2})\b", ql)
    if m:
        num = int(m.group(1))
        for n in names:
            if re.fullmatch(rf"(?i)level\s*0*{num}", n.strip()):
                return n
    return None


HEADER_Q = re.compile(r"\b(schema|ifc ?(version|2x3|4|4x3)|which (software|program|application|tool)|software|exported|exporter|"
                      r"authoring|originating|created (with|by|in)|made (with|in)|author|organi[sz]ation|time ?stamp|"
                      r"export(ed)? date|when was .{0,40}(created|exported)|preprocessor|file header|mvd|model view)\b", re.I)


def _ifc_header(path):
    """Read the STEP header of an IFC file (first 64 KB): schema, FILE_NAME and FILE_DESCRIPTION."""
    with open(path, "rb") as f:
        head = f.read(65536).decode("latin-1", "ignore")
    head = head.split("ENDSEC;", 1)[0]
    flat = re.sub(r"\s+", " ", head)
    out = {}
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", flat, re.I)
    out["schema"] = m.group(1) if m else ""
    m = re.search(r"FILE_DESCRIPTION\s*\(\s*\((.*?)\)\s*,\s*'([^']*)'", flat, re.I)
    if m:
        out["view"] = ", ".join(re.findall(r"'([^']*)'", m.group(1)))
    m = re.search(r"FILE_NAME\s*\((.*)\)\s*;", flat, re.I)
    if m:
        parts = re.findall(r"\(([^()]*)\)|'((?:[^']|'')*)'", m.group(1))
        vals = [(" / ".join(x for x in re.findall(r"'([^']*)'", a) if x) if a or not b else b) for a, b in parts]
        keys = ["name", "timestamp", "author", "organization", "preprocessor", "originating_system", "authorization"]
        out.update({k: v for k, v in zip(keys, vals)})
    return out


def _header_answer(project, ql, summ):
    import os
    try:
        import db as _db
        docs = [d for d in _db.list_documents(project) if str(d.get("filename", "")).lower().endswith((".ifc",))]
    except Exception:
        return None
    if not docs:
        return None
    named = [d for d in docs if re.sub(r"\.ifc$", "", d["filename"], flags=re.I).lower() in ql]
    docs = named or docs
    rows = []
    for d in docs[:40]:
        p = d.get("path")
        if not p or not os.path.isfile(p):
            continue
        try:
            h = _ifc_header(p)
        except OSError:
            continue
        rows.append({"model": d["filename"], "schema": h.get("schema", ""), "system": h.get("originating_system", ""),
                     "pre": h.get("preprocessor", ""), "date": (h.get("timestamp") or "")[:19].replace("T", " "),
                     "author": " ".join(x for x in (h.get("author"), h.get("organization")) if x), "view": h.get("view", "")})
    if not rows:
        return None
    body = _table(rows, ["model", "schema", "system", "pre", "date", "author"],
                  ["Model", "IFC schema", "Authoring software", "Exporter", "Exported", "Author / organisation"])
    schemas = sorted({r["schema"] for r in rows if r["schema"]})
    lead = (f"**{rows[0]['model']}** uses **{rows[0]['schema'] or 'an unstated schema'}**"
            + (f", exported from **{rows[0]['system']}**" if rows[0]["system"] else "") + "."
            if len(rows) == 1 else f"{len(rows)} IFC models; schema(s): **{', '.join(schemas) or 'not stated'}**.")
    views = sorted({r["view"] for r in rows if r["view"]})
    extra = f"\n\nModel view: {'; '.join(views[:3])}" if views else ""
    return (f"{lead}\n\n{body}{extra}\n\n*Source: the IFC file header (FILE_SCHEMA / FILE_NAME) of each model. "
            "Empty cells mean the exporter left that field blank.*")


def try_answer(project, query):
    try:
        st = Q.status(project)
    except Exception:
        return None
    if not st.get("indexed"):
        return None
    ql = (query or "").lower()
    if len(ql) > 400:
        return None
    if HEADER_Q.search(ql) and re.search(r"\b(ifc|model|bim|revit|\.ifc)\b", ql):
        try:
            ans = _header_answer(project, ql, None)
            if ans:
                return ans
        except Exception:
            pass
    elem = next(((c, label) for pat, c, label in ELEMENTS if re.search(pat, ql)), None)
    wants_storeys = re.search(r"\b(storeys?|stories|levels?|floors?)\b", ql) and re.search(r"\b(how many|list|which|what|number of|count)\b", ql)
    wants_phase = re.search(r"\bphas(e|es|ing)\b", ql)
    bim = re.search(BIM_WORDS, ql)
    if re.search(DOC_WORDS, ql) and not bim:
        return None
    if not (elem or wants_storeys or wants_phase):
        return None
    if not (bim or re.search(COUNT_WORDS, ql)):
        return None
    if elem is None and not bim and not wants_phase and not wants_storeys:
        return None

    summ = Q.summary(project)
    # A question naming one model ("...in C3082-MDL-...-ST-0000001") is about that model only.
    model = None
    for m in sorted((r["model"] for r in summ.get("models", []) if r.get("model")), key=len, reverse=True):
        stem = re.sub(r"\.(ifc|frag)$", "", m, flags=re.I).lower()
        if stem and stem in ql:
            model = m
            break
    storey = _storey_filter(project, ql, summ)
    phase = next((p["phase"] for p in summ["phases"] if p["phase"] and re.search(r"\b" + re.escape(p["phase"].lower()) + r"\b", ql)), None)
    note = (f"\n\n*Source: IFC model data index - model **{model}**.*" if model else
            f"\n\n*Source: IFC model data index for **{project}** - all {len(summ.get('models', []))} models ({st['elements']:,} indexed elements). Name a model file to count one model only.*")
    note += " *Quantities come from the models' `Dimensions` / `Pset_QuantityTakeOff` properties; they are only as complete as the model.*"

    # --- storeys overview
    if elem is None and wants_storeys:
        rows = Q.storeys(project, model=model)
        body = _table(rows, ["storey", "elev", "count", "area", "volume"], ["Storey", "Elevation", "Elements", "Area (m²)", "Volume (m³)"])
        return f"The models define **{len(rows)} storeys**:\n\n{body}{note}"

    # --- phases overview
    if elem is None and wants_phase:
        d = Q.qto(project, "phase")
        body = _table(d["rows"], ["key", "count", "area", "volume"], ["Phase", "Elements", "Area (m²)", "Volume (m³)"])
        return f"Elements by **phase**:\n\n{body}{note}"

    cls, label = elem
    f = {"cls": cls, "storey": storey, "phase": phase, "model": model}
    scope = (f" in **{model}**" if model else "") + (f" on **{storey}**" if storey else "") + (f" in phase **{phase}**" if phase else "")

    # --- rooms / spaces
    if cls == "IFCSPACE":
        sp = Q.spaces(project)
        spaces = [s for s in sp["spaces"] if not storey or s["storey"] == storey]
        if not spaces:
            return f"No rooms/spaces{scope} are defined in the indexed IFC models (only some models carry `IfcSpace`).{note}"
        total = round(sum(s["area"] or 0 for s in spaces), 2)
        if storey or re.search(r"\blist\b|schedule", ql):
            shown = spaces[:30]
            body = _table(shown, ["number", "name", "storey", "area"], ["No.", "Room", "Storey", "Area (m²)"])
            more = f"\n\n…and {len(spaces)-30} more." if len(spaces) > 30 else ""
            return f"**{len(spaces):,} rooms**{scope}, total area **{_fmt(total)} m²**:\n\n{body}{more}{note}"
        body = _table(sp["by_storey"][:25], ["storey", "count", "area"], ["Storey", "Rooms", "Area (m²)"])
        return f"The models contain **{len(spaces):,} rooms** with total area **{_fmt(total)} m²**:\n\n{body}{note}"

    # --- generic quantity query
    group = None
    if re.search(r"\b(by|per|each)\s+(type|family)\b|\btypes\b", ql): group = "type"
    elif re.search(r"\b(by|per|each)\s+(storey|story|level|floor)\b", ql): group = "storey"
    elif re.search(r"\b(by|per|each)\s+phase\b", ql): group = "phase"
    elif re.search(r"\b(by|per|each)\s+material\b", ql): group = "material"
    d = Q.qto(project, group or "class", **f)
    t = d["total"]
    if t["count"] == 0:
        return f"No **{label}**{scope} were found in the indexed IFC models.{note}"
    head = f"**{t['count']:,} {label}**{scope}"
    extras = []
    if t["area"]: extras.append(f"total area **{_fmt(t['area'])} m²**")
    if t["volume"]: extras.append(f"total volume **{_fmt(t['volume'])} m³**")
    if t["length"]: extras.append(f"total length **{_fmt(t['length'])} m**")
    ans = head + (": " + ", ".join(extras) if extras else "") + "."
    if group:
        rows = d["rows"][:30]
        ans += f"\n\nBy **{group}**:\n\n" + _table(rows, ["key", "count", "area", "volume"], [group.title(), "Count", "Area (m²)", "Volume (m³)"])
    elif not storey:
        # helpful default breakdown by storey (top 10)
        by = Q.qto(project, "storey", **f)["rows"][:10]
        if len(by) > 1:
            ans += "\n\nTop storeys:\n\n" + _table(by, ["key", "count", "area"], ["Storey", "Count", "Area (m²)"])
    return ans + note
