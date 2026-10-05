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

def mock_qwen(prompt):
    p = prompt.lower()
    
    if "how many walls are in the model" in p:
        return '{"tool": "countElements", "args": {"category": "IFCWALL"}}', 0.1
    if "how many doors are on level 02" in p:
        return '{"tool": "countElements", "args": {"category": "IFCDOOR", "level": "02"}}', 0.1
    if "list storeys" in p:
        return '{"tool": "getStoreys", "args": {}}', 0.1
    if "count categories" in p:
        return '{"tool": "getCategories", "args": {}}', 0.1
    if "find elements by type/name" in p:
        return '{"tool": "findElements", "args": {"name": "Concrete"}}', 0.1
    if "selected element properties" in p:
        return '{"tool": "getElementProperties", "args": {}}', 0.1  # Leave args blank so python auto-fills guid!
    if "selected element quantities" in p:
        return '{"tool": "getQuantities", "args": {}}', 0.1 # Leave args blank so python auto-fills guid!
    if "unknown guid" in p:
        return '{"tool": "getElementProperties", "args": {"guid": "unknown-123"}}', 0.1
    if "unknown category" in p:
        return '{"tool": "countElements", "args": {"category": "IFCUNICORN"}}', 0.1
    if "ambiguous model question" in p:
        return 'ambiguous text not json', 0.1

    if "Data: " in prompt:
        return "[Qwen Explains Result]", 0.1
        
    return '{"tool": "getModelInfo", "args": {}}', 0.1

async def run_tests():
    questions = [
        "How many walls are in the model?",
        "How many doors are on Level 02?",
        "List storeys.",
        "Count categories.",
        "Find elements by type/name.",
        "Selected element properties.",
        "Selected element quantities.",
        "Unknown GUID.",
        "Unknown category.",
        "Ambiguous model question."
    ]
    
    total = len(questions)
    passed = 0
    failed = 0
    
    print("========================================")
    print("PHASE 8.1 - REAL DATA MODEL QA")
    print("========================================\n")
    
    import intelligence.structured_query as sq
    def do_qwen(p): return mock_qwen(p)
    
    for i, q in enumerate(questions):
        # We simulate the UI sending selected_guid in the JSON body
        req = MockRequest({"project": "default", "question": q, "selected_guid": "real-guid-777"})
        print(f"Test {i+1}: {q}")
        try:
            # Call sq.query_document directly with our mock Qwen and user_context
            resp, lat = sq.query_document(
                q, "default", 
                lambda p,q,k,u: ([], ""), 
                do_qwen, 
                {"user": None, "selected_guid": "real-guid-777"}
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
