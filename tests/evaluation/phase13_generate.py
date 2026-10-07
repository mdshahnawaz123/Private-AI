# -*- coding: utf-8 -*-
"""
Phase 13 - Step 1: Generate 120+ benchmark questions with gold answers from SQLite.
All gold answers come directly from the structured_records table.
"""
import sys, os, json, sqlite3

sys.path.insert(0, r"C:\3EH\ExpoDesignAI - Copy")

DB = r"C:\3EH\ExpoDesignAI - Copy\data\expo.db"
OUT = r"C:\3EH\ExpoDesignAI - Copy\tests\evaluation\phase13_questions.json"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Load all valid records (skip tower='TOWER' artifacts)
ALL = [dict(r) for r in cur.execute(
    "SELECT tower, level, field, value, unit, page, schedule, revision "
    "FROM structured_records WHERE tower IS NOT NULL AND level IS NOT NULL "
    "AND tower != 'TOWER' ORDER BY tower, level, field"
).fetchall()]

# Build lookup  (tower, level, field) -> record
lookup = {}
for r in ALL:
    lookup[(r['tower'], r['level'], r['field'])] = r

# Unique values
towers  = sorted(set(r['tower'] for r in ALL), key=lambda x: int(x) if x.isdigit() else 999)
levels  = sorted(set(r['level'] for r in ALL))
area_fields = ['Floor GFA', 'Floor GA', 'Floor NISA', 'Floor NSA', 'Floor BUA', 'Balconies']
unit_fields = [f for f in sorted(set(r['field'] for r in ALL)) if 'Bed' in f]

dataset = []
qid = [0]

def add(cat, question, expected_answer, expected_type, tower=None, level=None, field=None,
        page=None, unit=None, deterministic=True, paraphrase_group=None):
    qid[0] += 1
    dataset.append({
        "id": f"{cat}{qid[0]:03d}",
        "category": cat,
        "question": question,
        "expected_answer": str(expected_answer),
        "expected_type": expected_type,
        "expected_unit": unit or "",
        "source_tower": tower or "",
        "source_level": level or "",
        "source_field": field or "",
        "source_page": str(page or ""),
        "deterministic": deterministic,
        "paraphrase_group": paraphrase_group or ""
    })

# ============================================================
# CATEGORY A - EXACT AREA LOOKUPS  (30+ questions)
# ============================================================
cat_a_combos = [
    ('6','02'), ('6','05'), ('6','08'),
    ('7','02'), ('7','05'), ('7','08'),
    ('1','02'), ('1','05'),
    ('2','03'), ('3','04'), ('4','06'), ('5','07'),
]
for t, l in cat_a_combos:
    for f in area_fields:
        key = (t, l, f)
        if key in lookup:
            r = lookup[key]
            add("A", f"What is the {f} of Tower {t} Level {l}?",
                r['value'], "NUMERIC", t, l, f, r['page'], r['unit'])

# ============================================================
# CATEGORY B - MULTI-FIELD LOOKUPS  (20+ questions)
# ============================================================
multi_combos = [
    ('6','02'), ('6','05'), ('7','02'), ('7','05'),
    ('1','02'), ('2','03'), ('3','04'), ('4','06'), ('5','07'), ('5','03'),
]
for t, l in multi_combos:
    # 2-field
    f1, f2 = 'Floor GFA', 'Floor GA'
    k1, k2 = (t,l,f1), (t,l,f2)
    if k1 in lookup and k2 in lookup:
        ans = f"{f1}={lookup[k1]['value']}, {f2}={lookup[k2]['value']}"
        add("B", f"Give the {f1} and {f2} for Tower {t} Level {l}.",
            ans, "MULTI_VALUE", t, l, f"{f1},{f2}", lookup[k1]['page'])
    # 3-field
    f3 = 'Floor NISA'
    k3 = (t,l,f3)
    if k1 in lookup and k2 in lookup and k3 in lookup:
        ans = f"{f1}={lookup[k1]['value']}, {f2}={lookup[k2]['value']}, {f3}={lookup[k3]['value']}"
        add("B", f"What are {f1}, {f2} and {f3} for Tower {t} Level {l}?",
            ans, "MULTI_VALUE", t, l, f"{f1},{f2},{f3}", lookup[k1]['page'])

# ============================================================
# CATEGORY C - UNIT MATRIX  (20+ questions)
# ============================================================
unit_combos = [
    ('6','02'), ('6','05'), ('7','02'), ('7','05'),
    ('1','02'), ('1','05'), ('2','03'), ('3','04'),
]
for t, l in unit_combos:
    for uf in unit_fields:
        key = (t, l, uf)
        if key in lookup:
            r = lookup[key]
            add("C", f"How many {uf} units in Tower {t} Level {l}?",
                r['value'], "NUMERIC", t, l, uf, r['page'], "units")

# ============================================================
# CATEGORY D - TOTALS / CALCULATIONS  (10+ questions)
# ============================================================
for t in ['1','2','3','4','5','6','7']:
    recs = [r for r in ALL if r['tower'] == t and r['field'] == 'Floor GFA']
    if recs:
        total = sum(r['value'] for r in recs if r['value'])
        add("D", f"What is the total Floor GFA for Tower {t}?",
            round(total, 2), "NUMERIC", t, "", "Floor GFA", "Multiple", "sqm")

for t in ['6','7']:
    for f in ['Floor GA', 'Floor NISA', 'Floor NSA']:
        recs = [r for r in ALL if r['tower'] == t and r['field'] == f]
        if recs:
            total = sum(r['value'] for r in recs if r['value'])
            add("D", f"What is the total {f} for Tower {t}?",
                round(total, 2), "NUMERIC", t, "", f, "Multiple", "sqm")

# ============================================================
# CATEGORY E - NOT FOUND  (15 questions)
# ============================================================
nf = [
    "What is the Floor GFA of Tower 9 Level 02?",
    "What is the Floor GFA of Tower 6 Level 15?",
    "What is the Floor GFA of Tower 6 Level 99?",
    "What is the structural column size of Tower 6?",
    "What is the concrete grade?",
    "What is the beam size?",
    "What is the architectural ceiling height?",
    "What is the fire rating?",
    "What is the construction cost?",
    "What is the consultant fee?",
    "What is the structural design code?",
    "What is the total number of swimming pools?",
    "How many elevators are in Tower 7?",
    "What is the roof color?",
    "What is the thickness of the glass?",
]
for q in nf:
    add("E", q, "NOT_FOUND", "NOT_FOUND", deterministic=True)

# ============================================================
# CATEGORY F - PARAPHRASE GROUPS  (10 groups x 5 wordings = 50)
# ============================================================
para_seeds = [
    ('6','02','Floor GFA'), ('6','05','Floor GA'), ('7','02','Floor NISA'),
    ('7','05','Floor NSA'), ('1','02','Floor BUA'), ('2','03','Balconies'),
    ('3','04','Floor GFA'), ('4','06','Floor GA'), ('5','07','Floor NISA'),
    ('6','08','Floor GFA'),
]
for gi, (t, l, f) in enumerate(para_seeds, 1):
    key = (t, l, f)
    if key not in lookup:
        continue
    r = lookup[key]
    pg = f"PG{gi:02d}"
    templates = [
        f"What is the {f} of Tower {t} Level {l}?",
        f"What is Tower {t} Level {l} {f}?",
        f"How much {f} does Tower {t} have at Level {l}?",
        f"Tower {t}, Level {l} - {f}?",
        f"Tell me the Level {l} {f} for Tower {t}.",
    ]
    for q in templates:
        add("F", q, r['value'], "NUMERIC", t, l, f, r['page'], r['unit'],
            paraphrase_group=pg)

# ============================================================
# CATEGORY G - NUMERIC ROBUSTNESS  (5 questions same value)
# ============================================================
rob_key = ('6','02','Floor GFA')
if rob_key in lookup:
    rr = lookup[rob_key]
    t,l,f = rob_key
    for q in [
        f"What is the {f} of Tower {t} Level {l}?",
        f"Can you give me the {f} for Tower {t} Level {l} in sqm?",
        f"Provide the {f} value for Tower {t} Level {l}.",
        f"Find the {f} of Tower {t} Level {l}.",
        f"Show me Tower {t} Level {l} {f}.",
    ]:
        add("G", q, rr['value'], "NUMERIC", t, l, f, rr['page'], rr['unit'])

conn.close()

# Write output
with open(OUT, "w", encoding="utf-8") as fp:
    json.dump(dataset, fp, indent=2, ensure_ascii=False)

# Category summary
cats = {}
for q in dataset:
    c = q['category']
    cats[c] = cats.get(c, 0) + 1
print(f"Generated {len(dataset)} questions -> {OUT}")
for c in sorted(cats):
    print(f"  Category {c}: {cats[c]}")
