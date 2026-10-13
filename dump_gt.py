import json

with open("output/phase4c-evaluation/PHASE4C_GROUND_TRUTH_v1.json", encoding="utf-8") as f:
    gt = json.load(f)

for q in gt["questions"]:
    print(f"{q['question_id']} [{q['document_id']}]: {q['question']}")
    print(f"   EXP: {q['expected_answer']}")
    cit = q.get('citation', {})
    print(f"   CIT: p.{cit.get('pdf_page')} | {cit.get('source_excerpt')}\n")
