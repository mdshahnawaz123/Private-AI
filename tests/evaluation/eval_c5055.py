"""
C5055 Benchmark Evaluation Suite: 50+ Engineering Verification Questions
Target Document: C5055-SDW-2DR0229-ST-2B11102(1).pdf
Project: C5055 - Sider (Plot 3 - Sidr Residences Zone 02 Basement Level 1 Structural GA Plan)
"""
import os
import sys
import json
import time
import urllib.request
import urllib.error

# Ensure root is in path
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import auth

SERVER_URL = "http://127.0.0.1:8090"
PROJECT = "C5055 - Sider"
TARGET_DOC = "C5055-SDW-2DR0229-ST-2B11102(1).pdf"

# 52 Curated Benchmark Questions across 7 Engineering Categories
BENCHMARK_QUESTIONS = [
    # -------------------------------------------------------------
    # Category 1: Title Block & Drawing Identification
    # -------------------------------------------------------------
    {
        "id": "C5055-Q01",
        "category": "Title Block & Drawing ID",
        "question": "What is the Drawing Number for drawing C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["C5055-SDW-2DR0229-ST-2B11102"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q02",
        "category": "Title Block & Drawing ID",
        "question": "What is the official Project Title stated in the title block of C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["EXPO CITY SIDR RESIDENCES"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q03",
        "category": "Title Block & Drawing ID",
        "question": "What is the full Drawing Title for C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["PLOT 3", "SIDR RESIDENCES", "ZONE 02", "BASEMENT LEVEL 1", "STRUCTURAL GENERAL ARRANGEMENT PLAN"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q04",
        "category": "Title Block & Drawing ID",
        "question": "What is the project location address stated in the title block of C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["Plot 3946", "Madinat Al Mataar", "Dubai"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q05",
        "category": "Title Block & Drawing ID",
        "question": "What is the drawing Revision Number recorded in the title block of C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["1"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q06",
        "category": "Title Block & Drawing ID",
        "question": "What is the Scale @ A1 specified in the title block of C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["As indicated"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q07",
        "category": "Title Block & Drawing ID",
        "question": "What is the Model File Ref indicated in the title block of C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["C5055-MDL-2DR0229-ST-0001001"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q08",
        "category": "Title Block & Drawing ID",
        "question": "What is the Seal Date recorded in the title block of C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["09/02/2026"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q09",
        "category": "Title Block & Drawing ID",
        "question": "Who approved the drawing according to the title block (initials) on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["AG"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q10",
        "category": "Title Block & Drawing ID",
        "question": "Who designed and drew the drawing (initials) on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["DI"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q11",
        "category": "Title Block & Drawing ID",
        "question": "Who checked the drawing (initials) on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["SG"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q12",
        "category": "Title Block & Drawing ID",
        "question": "What is the revision description for revision 1 on drawing C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["FIRST ISSUE"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q13",
        "category": "Title Block & Drawing ID",
        "question": "What is the date for revision 1 First Issue on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["09/02/2026"],
        "expected_refusal": False,
    },

    # -------------------------------------------------------------
    # Category 2: Consultant Review, Approval & Stamp
    # -------------------------------------------------------------
    {
        "id": "C5055-Q14",
        "category": "Consultant Review & Stamps",
        "question": "What is the consultant review stamp date on drawing C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["24-02-2026"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q15",
        "category": "Consultant Review & Stamps",
        "question": "What review code options are listed on the consultant review stamp of C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["Code A", "Approved", "Code B", "Approved with Comments", "Code C", "Rejected"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q16",
        "category": "Consultant Review & Stamps",
        "question": "According to comment 1 of the review stamp on C5055-SDW-2DR0229-ST-2B11102(1).pdf, what is the consultant's statement?",
        "expected_type": "fact",
        "expected_keywords": ["No objection", "structural GA layout/plan", "BL1 @ Z2"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q17",
        "category": "Consultant Review & Stamps",
        "question": "According to comment 5 of the consultant review stamp on C5055-SDW-2DR0229-ST-2B11102(1).pdf, what is the approval limited to?",
        "expected_type": "fact",
        "expected_keywords": ["limited to GA for concrete work", "mentioned elements only"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q18",
        "category": "Consultant Review & Stamps",
        "question": "According to comment 6 of the consultant review stamp on C5055-SDW-2DR0229-ST-2B11102(1).pdf, how must reinforcement details be submitted?",
        "expected_type": "fact",
        "expected_keywords": ["separate shop drawings", "reinforcement details", "MEP with builders work"],
        "expected_refusal": False,
    },

    # -------------------------------------------------------------
    # Category 3: General Notes, Datum & Units
    # -------------------------------------------------------------
    {
        "id": "C5055-Q19",
        "category": "General Notes & Datum",
        "question": "Which company holds the copyright of the drawing according to General Note 1 on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["ECC ENGINEERING CONTRACTING", "ECC"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q20",
        "category": "General Notes & Datum",
        "question": "What does General Note 2 state regarding scaling on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["DO NOT SCALE"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q21",
        "category": "General Notes & Datum",
        "question": "What units are specified for dimensions and levels in General Note 3 of C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["MILLIMETERS", "METERS"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q22",
        "category": "General Notes & Datum",
        "question": "What is the site datum level specified in General Note 5 on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["SITE DATUM +0.00", "+.00 DMD"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q23",
        "category": "General Notes & Datum",
        "question": "What does General Note 4 state about reading this drawing on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["READ IN CONJUNCTION", "ARCHITECTURAL", "STRUCTURAL", "MECHANICAL", "ELECTRICAL"],
        "expected_refusal": False,
    },

    # -------------------------------------------------------------
    # Category 4: Schedules (Drop Panels & Beams)
    # -------------------------------------------------------------
    {
        "id": "C5055-Q24",
        "category": "Schedules",
        "question": "What are the dimensions (width, length, depth) of drop panel DP01 in the Drop Panel Schedule on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["3000", "3000", "350"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q25",
        "category": "Schedules",
        "question": "What are the dimensions (width, length, depth) of drop panel DP10 in the Drop Panel Schedule on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["3000", "3000", "450"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q26",
        "category": "Schedules",
        "question": "What is the depth difference between drop panel DP10 and DP01 on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["100"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q27",
        "category": "Schedules",
        "question": "What are the width and height of beam 2B11 in the Structural Beam Schedule on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["500", "600"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q28",
        "category": "Schedules",
        "question": "What are the width and height of beam 2B13 in the Structural Beam Schedule on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["500", "600"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q29",
        "category": "Schedules",
        "question": "What are the width and height of beam 2B14 in the Structural Beam Schedule on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["500", "600"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q30",
        "category": "Schedules",
        "question": "What types of beams are listed in the B2 - Zone 2 Structural Beam Schedule on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["2B11", "2B13", "2B14"],
        "expected_refusal": False,
    },

    # -------------------------------------------------------------
    # Category 5: Slabs, Levels, Walls & Legend
    # -------------------------------------------------------------
    {
        "id": "C5055-Q31",
        "category": "Slabs & Walls",
        "question": "What structural slab level (SSL) is specified for the 225 THK RC SLAB on drawing C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["+23.050", "+23.05"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q32",
        "category": "Slabs & Walls",
        "question": "What structural slab level (SSL) is specified for the 260 THK RC SLAB on drawing C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["+23.050", "+23.05"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q33",
        "category": "Slabs & Walls",
        "question": "What top of beam (TOB) elevation is marked for beam 1B14 on drawing C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["+23.05"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q34",
        "category": "Slabs & Walls",
        "question": "What thickness retaining walls are identified in the Slab Thickness and Wall Legend on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["400mm", "450mm"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q35",
        "category": "Slabs & Walls",
        "question": "What thickness filler board is listed in the legend on drawing C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["50mm"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q36",
        "category": "Slabs & Walls",
        "question": "Which slab thicknesses are listed in the legend of drawing C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["225", "260", "275", "325", "350", "400", "450", "550", "650", "700"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q37",
        "category": "Slabs & Walls",
        "question": "What column/wall condition symbols are defined in the legend on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["CONTINUOUS", "TERMINATE"],
        "expected_refusal": False,
    },

    # -------------------------------------------------------------
    # Category 6: Grid System, Dimensions & Key Plan
    # -------------------------------------------------------------
    {
        "id": "C5055-Q38",
        "category": "Grid Spacing & Key Plan",
        "question": "What grid lines are identified on drawing C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["F1", "F2", "F3", "F4", "F5"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q39",
        "category": "Grid Spacing & Key Plan",
        "question": "What is the total overall dimension between grids F1 and F5 on drawing C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["36240"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q40",
        "category": "Grid Spacing & Key Plan",
        "question": "What is the bay spacing between grids F1 and F2 on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["10440"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q41",
        "category": "Grid Spacing & Key Plan",
        "question": "What is the typical bay dimension between grids F2-F3, F3-F4, and F4-F5 on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["8600"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q42",
        "category": "Grid Spacing & Key Plan",
        "question": "What overall dimension spans the cross-direction grids on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["24200"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q43",
        "category": "Grid Spacing & Key Plan",
        "question": "Which avenues and crescents are shown on the Key Plan on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["AL FORSAN CRESCENT", "GHAF AVENUE", "SIDR AVENUE"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q44",
        "category": "Grid Spacing & Key Plan",
        "question": "How many zones are shown in the Zone Map on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["5", "ZONE 1", "ZONE 2", "ZONE 3", "ZONE 4", "ZONE 5"],
        "expected_refusal": False,
    },

    # -------------------------------------------------------------
    # Category 7: Contract Reference Drawings & Negative / Refusal Tests
    # -------------------------------------------------------------
    {
        "id": "C5055-Q45",
        "category": "Contract Reference Drawings",
        "question": "What is the drawing number for the Column Schedule referenced in item 05 of the Contract Reference Drawings on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["C3076-DWG-2DR0229-ST-7000420-421"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q46",
        "category": "Contract Reference Drawings",
        "question": "What is the drawing number for the Wall Schedule referenced in item 06 of the Contract Reference Drawings on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["C3076-DWG-2DR0229-ST-7000401-406"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q47",
        "category": "Contract Reference Drawings",
        "question": "What is the drawing number for Tower 1 Core Details referenced in item 07 of Contract Reference Drawings on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["C3076-DWG-2DR0229-AR-6B36201"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q48",
        "category": "Contract Reference Drawings",
        "question": "What is the drawing number for Tower 2 Core Details referenced in item 08 on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["C3076-DWG-2DR0229-AR-6B36204"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q49",
        "category": "Contract Reference Drawings",
        "question": "What is the drawing number for Tower 3 Core Details referenced in item 09 on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "fact",
        "expected_keywords": ["C3076-DWG-2DR0229-AR-6B36207"],
        "expected_refusal": False,
    },
    {
        "id": "C5055-Q50",
        "category": "Negative / Refusal Integrity",
        "question": "What is the rebar size and spacing for the top reinforcement of the 350mm slab on C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "refusal",
        "expected_keywords": ["not stated", "not found", "separate shop drawings", "could not find", "not included"],
        "expected_refusal": True,
    },
    {
        "id": "C5055-Q51",
        "category": "Negative / Refusal Integrity",
        "question": "What is the total electrical transformer rating in kVA specified on drawing C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "refusal",
        "expected_keywords": ["not found", "not stated", "not specified", "could not find"],
        "expected_refusal": True,
    },
    {
        "id": "C5055-Q52",
        "category": "Negative / Refusal Integrity",
        "question": "What is the fire pump flow rate in GPM for Zone 02 on drawing C5055-SDW-2DR0229-ST-2B11102(1).pdf?",
        "expected_type": "refusal",
        "expected_keywords": ["not found", "not stated", "not specified", "could not find"],
        "expected_refusal": True,
    },
]


def run_query(token, question):
    ask_body = json.dumps({
        "project": PROJECT,
        "query": question,
        "model": "qwen3.5:9b",
        "mode": "chat"
    }).encode("utf-8")

    ask_req = urllib.request.Request(
        f"{SERVER_URL}/ask_stream",
        data=ask_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
    )

    t0 = time.time()
    try:
        with urllib.request.urlopen(ask_req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"error": str(e), "latency": time.time() - t0, "answer": "", "sources": []}

    latency = time.time() - t0
    answer_tokens = []
    sources = []

    for line in raw.splitlines():
        if line.startswith("data:"):
            try:
                data = json.loads(line[5:].strip())
                if data.get("type") == "token":
                    answer_tokens.append(data.get("text", ""))
                elif data.get("type") == "sources":
                    sources = data.get("sources", [])
            except Exception:
                pass

    return {
        "answer": "".join(answer_tokens).strip(),
        "sources": sources,
        "latency": latency,
        "error": None
    }


def evaluate_item(q_spec, result):
    import re
    answer = result.get("answer", "")
    err = result.get("error")
    if err or not answer:
        return {"pass": False, "reason": f"Execution error: {err or 'Empty answer'}"}

    lower_ans = answer.lower()
    is_withheld = "i could not verify the generated answer against the retrieved source pages" in lower_ans or \
                  "no extracted review annotations or visible stamp readings were found" in lower_ans

    if q_spec["expected_refusal"]:
        if is_withheld:
            return {"pass": True, "reason": "Proper refusal produced: ungrounded fact withheld by safety guard"}
        refusal_hits = [k for k in q_spec["expected_keywords"] if re.search(r'\b' + re.escape(k.lower()) + r'\b', lower_ans)]
        if refusal_hits:
            return {"pass": True, "reason": f"Proper refusal produced: hit '{refusal_hits[0]}'"}
        else:
            return {"pass": False, "reason": "Expected refusal / abstention, but answer did not indicate absence"}

    # Factual verification - must not be a guard withheld refusal message
    if is_withheld:
        return {"pass": False, "reason": "Answer was withheld by evidence guard (insufficient retrieved evidence)"}

    hits = []
    for k in q_spec["expected_keywords"]:
        k_clean = k.strip().lower()
        # For short acronyms (<=3 chars), use strict word boundary
        if len(k_clean) <= 3:
            if re.search(r'\b' + re.escape(k_clean) + r'\b', lower_ans):
                hits.append(k)
        else:
            if k_clean in lower_ans:
                hits.append(k)

    if len(hits) >= 1:
        # Check source citation
        has_source = any(TARGET_DOC in str(s) for s in result.get("sources", [])) or TARGET_DOC in answer or "[SOURCE:" in answer
        return {
            "pass": True,
            "reason": f"Matched ground truth {hits}; citation verified={has_source}"
        }
    else:
        return {
            "pass": False,
            "reason": f"Expected keywords {q_spec['expected_keywords']} not found in answer"
        }


def main():
    print("=" * 80)
    print("EXPO DESIGN AI - C5055 BENCHMARK EVALUATION RUNNER")
    print(f"Total Questions: {len(BENCHMARK_QUESTIONS)}")
    print(f"Project: {PROJECT} | Document: {TARGET_DOC}")
    print("=" * 80)

    token = auth.make_token({"id": 2, "username": "admin", "role": "admin"})

    results = []
    passes = 0
    total = len(BENCHMARK_QUESTIONS)

    for i, q in enumerate(BENCHMARK_QUESTIONS, 1):
        print(f"\n[{i}/{total}] {q['id']} ({q['category']}): {q['question']}")
        res = run_query(token, q["question"])
        eval_res = evaluate_item(q, res)
        
        status_str = "PASS" if eval_res["pass"] else "FAIL"
        if eval_res["pass"]:
            passes += 1

        print(f"  Result: [{status_str}] (Latency: {res['latency']:.2f}s)")
        print(f"  Reason: {eval_res['reason']}")
        ans_preview = res['answer'].replace("\n", " ")[:140]
        print(f"  Answer: {ans_preview}...")

        results.append({
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "expected_type": q["expected_type"],
            "expected_refusal": q["expected_refusal"],
            "answer": res["answer"],
            "latency": res["latency"],
            "pass": eval_res["pass"],
            "reason": eval_res["reason"],
            "sources": res["sources"]
        })

    pass_rate = (passes / total) * 100.0
    print("\n" + "=" * 80)
    print(f"EVALUATION COMPLETE: {passes}/{total} Passed ({pass_rate:.1f}%)")
    print("=" * 80)

    out_file = os.path.join(ROOT, "tests", "evaluation", "eval_c5055_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "project": PROJECT,
            "document": TARGET_DOC,
            "total": total,
            "passed": passes,
            "pass_rate": pass_rate,
            "results": results
        }, f, indent=2)
    print(f"Saved evaluation results to {out_file}")


if __name__ == "__main__":
    main()
