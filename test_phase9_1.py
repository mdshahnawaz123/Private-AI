import asyncio
from main import app, auth
import main

auth.require_project = lambda request, project: {"user_id": "test_admin"}

def mock_qwen(prompt):
    return '{"tool": "countElements", "args": {}}', 0.1

async def run_tests():
    # 30+ mixed questions
    questions = [
        # Model QA (15)
        ("How many slabs?", "MODEL_QA"),
        ("Wall count by level.", "MODEL_QA"),
        ("Find elements by type.", "MODEL_QA"),
        ("Selected element properties.", "MODEL_QA"),
        ("What is the volume of this element?", "MODEL_QA"),
        ("List all storeys.", "MODEL_QA"),
        ("How many doors on level 05?", "MODEL_QA"),
        ("Count elements in category IFCWINDOW.", "MODEL_QA"),
        ("Highlight the selected slab.", "MODEL_QA"),
        ("Show me the properties of guid-xyz.", "MODEL_QA"),
        ("Total area of slabs in the model.", "MODEL_QA"),
        ("Elements missing fire rating.", "MODEL_QA"),
        ("Isolate all columns.", "MODEL_QA"),
        ("Count of beams.", "MODEL_QA"),
        ("Search for furniture.", "MODEL_QA"),
        
        # Document QA (15)
        ("What is the GFA of Tower 6 Level 2?", "DOCUMENT_QA"),
        ("Tell me the area for Tower 6 Level 02.", "DOCUMENT_QA"),
        ("Gross floor area of Level 11.", "DOCUMENT_QA"),
        ("Compare Tower 6 Level 2 and Level 11 GFA.", "DOCUMENT_QA"),
        ("What is the NSA of Tower 6?", "DOCUMENT_QA"),
        ("What is Tower 6 Level 2 net usable area?", "DOCUMENT_QA"),
        ("What is the BUA of Level 2?", "DOCUMENT_QA"),
        ("Give me the Floor GA.", "DOCUMENT_QA"),
        ("What is the latest report from the consultant?", "DOCUMENT_QA"),
        ("Which revision is the document?", "DOCUMENT_QA"),
        ("What is the NISA for Level 5?", "DOCUMENT_QA"),
        ("Document schedule for Tower 1.", "DOCUMENT_QA"),
        ("Show me the area calculation.", "DOCUMENT_QA"),
        ("What is the GFA of Tower 99 Level 1?", "DOCUMENT_QA"),
        ("Ambiguous GFA question.", "DOCUMENT_QA")
    ]
    
    print("========================================")
    print("PHASE 9.1 - MODEL/DOCUMENT ROUTER HARDENING")
    print("========================================\n")
    
    import intelligence.structured_query as sq
    def do_qwen(p): return mock_qwen(p)
    
    passed = 0
    total = len(questions)
    correct_cases = 0
    
    for q, expected in questions:
        try:
            # First just test the classifier!
            intent = sq.classify_query(q)
            if intent == expected:
                correct_cases += 1
                res = "PASS"
            else:
                res = "FAIL"
            print(f"[{res}] '{q}' -> {intent} (Expected: {expected})")
        except Exception as e:
            print(f"[CRASH] '{q}' -> {e}")
            
    print(f"\nTotal: {total} | Passed: {correct_cases} | Failed: {total - correct_cases}")

if __name__ == "__main__":
    asyncio.run(run_tests())
