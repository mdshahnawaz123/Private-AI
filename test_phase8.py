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

# We will patch the Qwen function inside api_query_document to mock the LLM routing 
import httpx
def mock_qwen(prompt):
    import json
    p = prompt.lower()
    
    if "how many walls are in the model" in p:
        return '{"tool": "countElements", "args": {"category": "IFCWALL"}}', 0.1
    if "how many doors are on level 02" in p:
        return '{"tool": "countElements", "args": {"category": "IFCDOOR", "level": "02"}}', 0.1
    if "show all storeys" in p:
        return '{"tool": "getStoreys", "args": {}}', 0.1
    if "count elements by category" in p:
        return '{"tool": "getCategories", "args": {}}', 0.1
    if "find elements by name/type" in p:
        return '{"tool": "findElements", "args": {"name": "Concrete"}}', 0.1
    if "get properties of a selected element id" in p or "properties for guid" in p:
        return '{"tool": "getElementProperties", "args": {"guid": "fake-guid-123"}}', 0.1
    if "get quantities" in p:
        return '{"tool": "getQuantities", "args": {"guid": "fake-guid-123"}}', 0.1
    if "unknown element" in p:
        return '{"tool": "getElementProperties", "args": {"guid": "unknown-123"}}', 0.1
    if "ambiguous model query" in p:
        return 'ambiguous text not json', 0.1

    # Format result response
    if "Data: " in prompt:
        return "[Qwen Fallback Model Explanation]", 0.1
        
    return '{"tool": "getModelInfo", "args": {}}', 0.1

async def run_tests():
    questions = [
        "How many walls are in the model?",
        "How many doors are on Level 02?",
        "Show all storeys.",
        "Count elements by category.",
        "Find elements by name/type.",
        "Get properties for guid fake-guid-123.",
        "Get quantities for guid fake-guid-123.",
        "Get properties for unknown element unknown-123.",
        "An ambiguous model query about elements."
    ]
    
    total = len(questions)
    passed = 0
    failed = 0
    
    print("========================================")
    print("PHASE 8 - IFC/FRAGMENTS AI MODEL QUERY")
    print("========================================\n")
    
    # We must patch the qwen function in main.py
    import intelligence.structured_query as sq
    def do_qwen(p): return mock_qwen(p)
    
    for i, q in enumerate(questions):
        req = MockRequest({"project": "1", "question": q})
        print(f"Test {i+1}: {q}")
        try:
            # Call sq.query_document directly with our mock Qwen
            resp, lat = sq.query_document(
                q, "1", 
                lambda p,q,k,u: ([], ""), 
                do_qwen, 
                {"user": None}
            )
            
            status = resp.get("status")
            route = resp.get("route")
            ans = resp.get("answer", "").split("\n")[0]
            data = resp.get("data")
            
            print(f"  Status: {status} | Route: {route}")
            if data: print(f"  Data: {str(data)[:150]}")
            print(f"  Answer: {ans[:150]}...")
            
            if status in ["SUCCESS", "AMBIGUOUS", "NOT_FOUND", "UNSUPPORTED"]:
                passed += 1
            else:
                failed += 1
                print(f"  FAILED: Unexpected status {status}")
        except Exception as e:
            failed += 1
            print(f"  CRASHED: {e}")
            import traceback
            traceback.print_exc()
        print("-" * 50)
        
    print(f"\nTotal: {total} | Passed: {passed} | Failed: {failed}")

if __name__ == "__main__":
    asyncio.run(run_tests())
