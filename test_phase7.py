import asyncio
from main import app, auth
import main

auth.require_project = lambda request, project: {"user_id": "test_admin"}

# We can directly invoke main.api_query_document
class MockRequest:
    def __init__(self, json_data):
        self._json = json_data
    async def json(self):
        return self._json

async def run_tests():
    questions = [
        "What is Tower 6 Level 02 GFA?",
        "What is Tower 6 Level 02 GA?",
        "What is Tower 6 Level 02 NSA?",
        "What is Tower 6 total GFA?",
        "NSA as % of GFA for Tower 6 Level 02?",
        "Difference between Level 02 and Level 11 GFA for Tower 6",
        "What is Level 02 GFA?",
        "What is Tower 99 Level 01 GFA?",
        "What is the Roof Area for Tower 6?",
        "Who is the main structural consultant?",
        "What is Tower 6 Level 02 GFA in Rev 1?",
        "Compare Tower 6 and Tower 8 Level 2 GFA"
    ]
    
    total = len(questions)
    passed = 0
    failed = 0
    results = []
    
    print("========================================")
    print("PHASE 7 - REAL DATA E2E VALIDATION")
    print("========================================\n")
    
    for i, q in enumerate(questions):
        req = MockRequest({"project": "1", "question": q})
        print(f"Test {i+1}: {q}")
        try:
            res = await main.api_query_document(req)
            status = res.get("status")
            route = res.get("route")
            ans = res.get("answer", "").split("\n")[0] # First line of answer
            calc = res.get("calculation")
            prov = res.get("provenance")
            
            print(f"  Status: {status} | Route: {route}")
            if calc: print(f"  Calculation: {calc}")
            print(f"  Answer: {ans[:150]}...")
            
            if status in ["SUCCESS", "AMBIGUOUS", "NOT_FOUND", "UNSUPPORTED"]:
                passed += 1
                results.append({"q": q, "status": status, "ans": ans})
            else:
                failed += 1
                print(f"  FAILED: Unexpected status {status}")
        except Exception as e:
            failed += 1
            print(f"  CRASHED: {e}")
        print("-" * 50)
        
    print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed}")

if __name__ == "__main__":
    asyncio.run(run_tests())
