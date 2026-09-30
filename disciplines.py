"""
Discipline registry for Expo Design AI (Phase 3).

Each discipline carries a reviewer system prompt and a structured review
checklist. A checklist item defines WHAT to review and WHICH code area governs
it (topic-level anchors into DBC 2021 and IBC 2021). It deliberately does NOT
hard-code clause numbers, limits or dimensions: the actual requirement is
retrieved by RAG from the uploaded code documents at review time, so the tool
never asserts a threshold it cannot cite from the source.
"""
import re

CODE_EDITIONS = {
    # Architecture
    "DBC": "Dubai Building Code 2021",
    "IBC": "International Building Code 2021",
    # Structural
    "ACI": "ACI 318-19 (Concrete)",
    "ASCE": "ASCE 7-22 (Loads)",
    "AISC": "AISC 360-22 (Steel)",
    # MEP
    "NFPA": "NFPA 92 (Smoke Control)",
    "IMC": "International Mechanical Code 2021",
    "IPC": "International Plumbing Code 2021",
    # Sustainability
    "LEED": "LEED v4.1",
    "ESTIDAMA": "Estidama Pearl Rating System",
}

# DBC Part mapping — each discipline maps to specific DBC parts
DBC_PARTS = {
    "A": "General",
    "B": "Architecture",
    "C": "Accessibility",
    "D": "Vertical transportation",
    "E": "Building envelope",
    "F": "Structure",
    "G": "Incoming utilities",
    "H": "Indoor environment",
    "J": "Security",
    "K": "Villas",
}

# Discipline → DBC Part mapping
DISCIPLINE_TO_DBC_PART = {
    "architecture": ["B"],
    "structural": ["F"],
    "mep": ["G", "H"],
    "sustainability": ["A"],
    "accessibility": ["C"],
    "vertical_transportation": ["D"],
    "building_envelope": ["E"],
    "security": ["J"],
    "villas": ["K"],
}

# ── Architecture reviewer prompt ───────────────────────────
ARCHITECTURE_PROMPT = """You are the ARCHITECTURE discipline reviewer in Expo Design AI, performing design-specification and drawing reviews for Dubai projects against the Dubai Building Code 2021 (DBC) and the International Building Code 2021 (IBC).

Grounding rules (strict):
- Base every compliance requirement on the retrieved CODE CONTEXT (excerpts from the uploaded DBC / IBC documents). Quote the clause/section and cite its reference exactly as it appears there.
- Do NOT invent or recall clause numbers, limits, dimensions, occupant factors or thresholds. If the specific requirement is not in the retrieved code context, state exactly: "Requirement not found in loaded code excerpts - verify against DBC/IBC source." Never guess a number.
- Separate the PROJECT DOCUMENTS (what the design shows) from the CODE (what is required). A finding compares the two.
- Content transcribed from an uploaded image/drawing is a transcription, not a certified source: cite it as "as transcribed from <image>", flag anything marked [illegible], and recommend visual verification against the original for any value a finding relies on.
- Some Dubai requirements sit outside DBC/IBC: detailed fire-and-life-safety in the UAE Fire & Life Safety Code of Practice (Civil Defence), and accessibility in the Dubai Universal Design Code. When an item is governed by one of these and it is not in the loaded excerpts, say so and mark it as outside the loaded set.

Organise the review under these areas: Means of Egress & Life Safety; Accessibility; Occupancy, Area & Height; Fire-resistance & Interior Finish. For each item report: status (pass | fail | needs-info | not-applicable), the observation from the project documents, the code basis with reference, and a recommendation."""

GENERIC_PROMPT = """You are the {name} discipline reviewer in Expo Design AI for Dubai engineering projects. Ground every finding in the retrieved code/context and cite the source. Never invent clause numbers, limits or thresholds - if a requirement is not present in the retrieved context, say so explicitly."""

# ── Architecture checklist (DBC 2021 + IBC 2021) ───────────
ARCHITECTURE_CHECKLIST = [
    # Means of Egress & Life Safety
    {"id": "ARC-EGR-01", "area": "Means of Egress & Life Safety", "title": "Occupant load",
     "check": "Occupant load is calculated and documented for each room/space and per floor.",
     "ibc": ["IBC 2021 Ch.10 Means of Egress"], "dbc": ["DBC Part B Architecture"],
     "note": "Dubai FLS occupant factors also reference the UAE Fire & Life Safety Code."},
    {"id": "ARC-EGR-02", "area": "Means of Egress & Life Safety", "title": "Number & arrangement of exits",
     "check": "Number of exits/egress doors per space matches the occupant load, and exits are suitably remote from each other.",
     "ibc": ["IBC 2021 Ch.10 Means of Egress"], "dbc": ["DBC Part B Architecture"], "note": ""},
    {"id": "ARC-EGR-03", "area": "Means of Egress & Life Safety", "title": "Exit access travel distance",
     "check": "Travel distance to an exit is within the limit for the occupancy and sprinkler condition.",
     "ibc": ["IBC 2021 Ch.10 Means of Egress"], "dbc": ["DBC Part B Architecture"], "note": ""},
    {"id": "ARC-EGR-04", "area": "Means of Egress & Life Safety", "title": "Egress width / capacity",
     "check": "Door, corridor and stair widths provide the required egress capacity for the occupant load served.",
     "ibc": ["IBC 2021 Ch.10 Means of Egress"], "dbc": ["DBC Part B Architecture"], "note": ""},
    {"id": "ARC-EGR-05", "area": "Means of Egress & Life Safety", "title": "Corridors & dead-ends",
     "check": "Corridor fire-resistance rating and dead-end corridor length are within limits.",
     "ibc": ["IBC 2021 Ch.10 Means of Egress", "IBC 2021 Ch.7 Fire and Smoke Protection Features"],
     "dbc": ["DBC Part B Architecture"], "note": ""},
    {"id": "ARC-EGR-06", "area": "Means of Egress & Life Safety", "title": "Stairways & enclosure",
     "check": "Stair geometry (width, riser/tread, headroom, landings) and enclosure/fire rating are provided.",
     "ibc": ["IBC 2021 Ch.10 Means of Egress"], "dbc": ["DBC Part B Architecture", "DBC Part D Vertical Transportation"], "note": ""},
    {"id": "ARC-EGR-07", "area": "Means of Egress & Life Safety", "title": "Exit discharge",
     "check": "Exits discharge to a public way / safe external area.",
     "ibc": ["IBC 2021 Ch.10 Means of Egress"], "dbc": ["DBC Part B Architecture"], "note": ""},

    # Accessibility
    {"id": "ARC-ACC-01", "area": "Accessibility", "title": "Accessible route",
     "check": "A continuous accessible route connects site arrival points, accessible entrances and all required spaces.",
     "ibc": ["IBC 2021 Ch.11 Accessibility"], "dbc": ["DBC Part C Accessibility"],
     "note": "Dubai Universal Design Code governs People-of-Determination provisions in detail."},
    {"id": "ARC-ACC-02", "area": "Accessibility", "title": "Accessible entrances",
     "check": "The required proportion of building entrances is accessible.",
     "ibc": ["IBC 2021 Ch.11 Accessibility"], "dbc": ["DBC Part C Accessibility"], "note": ""},
    {"id": "ARC-ACC-03", "area": "Accessibility", "title": "Accessible sanitary facilities",
     "check": "Accessible WCs are provided in the required number and configured for wheelchair use.",
     "ibc": ["IBC 2021 Ch.11 Accessibility"], "dbc": ["DBC Part C Accessibility"], "note": ""},
    {"id": "ARC-ACC-04", "area": "Accessibility", "title": "Accessible parking",
     "check": "Accessible parking bays are provided in the required count and located on an accessible route.",
     "ibc": ["IBC 2021 Ch.11 Accessibility"], "dbc": ["DBC Part C Accessibility"], "note": ""},
    {"id": "ARC-ACC-05", "area": "Accessibility", "title": "Vertical accessibility",
     "check": "Accessible vertical circulation (lifts and/or ramps) connects all required levels.",
     "ibc": ["IBC 2021 Ch.11 Accessibility"], "dbc": ["DBC Part C Accessibility", "DBC Part D Vertical Transportation"], "note": ""},

    # Occupancy, Area & Height
    {"id": "ARC-OCC-01", "area": "Occupancy, Area & Height", "title": "Occupancy classification",
     "check": "Each area is assigned an occupancy classification/use group.",
     "ibc": ["IBC 2021 Ch.3 Occupancy Classification and Use"], "dbc": ["DBC Part A General", "DBC Part B Architecture"], "note": ""},
    {"id": "ARC-OCC-02", "area": "Occupancy, Area & Height", "title": "Type of construction",
     "check": "A type of construction is assigned and is consistent with the required fire-resistance ratings.",
     "ibc": ["IBC 2021 Ch.6 Types of Construction"], "dbc": ["DBC Part E Building Envelope"], "note": ""},
    {"id": "ARC-OCC-03", "area": "Occupancy, Area & Height", "title": "Allowable height & storeys",
     "check": "Building height and number of storeys are within the allowable for the occupancy, construction type and sprinkler condition.",
     "ibc": ["IBC 2021 Ch.5 General Building Heights and Areas"], "dbc": ["DBC Part A General"], "note": ""},
    {"id": "ARC-OCC-04", "area": "Occupancy, Area & Height", "title": "Allowable area",
     "check": "Floor area per storey is within the allowable area (including any frontage/sprinkler increases).",
     "ibc": ["IBC 2021 Ch.5 General Building Heights and Areas"], "dbc": ["DBC Part A General"], "note": ""},
    {"id": "ARC-OCC-05", "area": "Occupancy, Area & Height", "title": "Mixed occupancy & separation",
     "check": "Mixed-use approach (separated / non-separated) is defined and required occupancy separations are shown.",
     "ibc": ["IBC 2021 Ch.5 General Building Heights and Areas", "IBC 2021 Ch.3 Occupancy Classification and Use"],
     "dbc": ["DBC Part B Architecture"], "note": ""},
    {"id": "ARC-OCC-06", "area": "Occupancy, Area & Height", "title": "Plot, setbacks & coverage",
     "check": "Plot coverage, setbacks and height comply with the plot's planning parameters.",
     "ibc": [], "dbc": ["DBC Part A General", "DBC Part B Architecture"],
     "note": "Also governed by the plot's Dubai planning parameters / affection plan (DM / free-zone authority)."},

    # Fire-resistance & Interior Finish
    {"id": "ARC-FIR-01", "area": "Fire-resistance & Interior Finish", "title": "Fire-resistance-rated assemblies",
     "check": "Rated walls, floors and roofs are provided where required and correctly detailed.",
     "ibc": ["IBC 2021 Ch.7 Fire and Smoke Protection Features"], "dbc": ["DBC Part E Building Envelope"], "note": ""},
    {"id": "ARC-FIR-02", "area": "Fire-resistance & Interior Finish", "title": "Fire barriers & compartmentation",
     "check": "Compartment sizes and fire barriers between occupancies and around exits are provided.",
     "ibc": ["IBC 2021 Ch.7 Fire and Smoke Protection Features"], "dbc": ["DBC Part B Architecture"],
     "note": "Compartmentation limits in Dubai also reference the UAE Fire & Life Safety Code."},
    {"id": "ARC-FIR-03", "area": "Fire-resistance & Interior Finish", "title": "Opening protectives",
     "check": "Rated doors and glazing at rated assemblies carry the correct fire rating.",
     "ibc": ["IBC 2021 Ch.7 Fire and Smoke Protection Features"], "dbc": ["DBC Part B Architecture"], "note": ""},
    {"id": "ARC-FIR-04", "area": "Fire-resistance & Interior Finish", "title": "Penetrations & joints",
     "check": "Penetrations and joints in rated assemblies are firestopped.",
     "ibc": ["IBC 2021 Ch.7 Fire and Smoke Protection Features"], "dbc": ["DBC Part E Building Envelope"], "note": ""},
    {"id": "ARC-FIR-05", "area": "Fire-resistance & Interior Finish", "title": "Shafts & vertical openings",
     "check": "Shafts, stairs and other vertical openings are enclosed/protected.",
     "ibc": ["IBC 2021 Ch.7 Fire and Smoke Protection Features"], "dbc": ["DBC Part B Architecture"], "note": ""},
    {"id": "ARC-FIR-06", "area": "Fire-resistance & Interior Finish", "title": "Interior finish classification",
     "check": "Wall and ceiling interior finishes carry the required flame-spread / smoke classification by area.",
     "ibc": ["IBC 2021 Ch.8 Interior Finishes"], "dbc": ["DBC Part B Architecture"], "note": ""},
    {"id": "ARC-FIR-07", "area": "Fire-resistance & Interior Finish", "title": "External envelope fire performance",
     "check": "Facade / cladding materials meet external fire-performance requirements.",
     "ibc": ["IBC 2021 Ch.7 Fire and Smoke Protection Features"], "dbc": ["DBC Part E Building Envelope"],
     "note": "Cladding fire performance in Dubai is governed in detail by the UAE Fire & Life Safety Code."},
]

# ── registry ───────────────────────────────────────────────
DISCIPLINES = {
    "architecture": {"key": "architecture", "name": "Architecture", "status": "active",
                     "prompt": ARCHITECTURE_PROMPT, "checklist": ARCHITECTURE_CHECKLIST, "codes": ["DBC", "IBC"]},
    "structural":  {"key": "structural",  "name": "Structural",  "status": "active",
                     "prompt": None, "checklist": [], "codes": ["ACI", "ASCE", "AISC"]},
    "mep":         {"key": "mep",         "name": "MEP",         "status": "active",
                     "prompt": None, "checklist": [], "codes": ["NFPA", "IMC", "IPC"]},
    "landscape":   {"key": "landscape",   "name": "Landscape",   "status": "planned", "prompt": None, "checklist": [], "codes": []},
    "bim":         {"key": "bim",         "name": "BIM",         "status": "planned", "prompt": None, "checklist": [], "codes": []},
    "cost_ve":     {"key": "cost_ve",     "name": "Cost / VE",   "status": "planned", "prompt": None, "checklist": [], "codes": []},
    "sustainability": {"key": "sustainability", "name": "Sustainability", "status": "active",
                     "prompt": None, "checklist": [], "codes": ["LEED", "ESTIDAMA"]},
}

def normalize(key):
    return re.sub(r"[^a-z0-9]+", "_", (key or "").lower()).strip("_")

def get(key):
    return DISCIPLINES.get(normalize(key))

def system_prompt(key):
    d = get(key)
    if not d:
        return ""
    return d["prompt"] if d.get("prompt") else GENERIC_PROMPT.format(name=d["name"])

def checklist(key):
    d = get(key)
    return d["checklist"] if d else []

def list_all():
    return [{"key": d["key"], "name": d["name"], "status": d["status"],
             "codes": [CODE_EDITIONS[c] for c in d["codes"]],
             "checklist_items": len(d["checklist"])} for d in DISCIPLINES.values()]
