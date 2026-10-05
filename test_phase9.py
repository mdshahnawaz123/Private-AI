import asyncio
from main import app, auth
import main

auth.require_project = lambda request, project: {"user_id": "test_admin"}

class MockRequest:
    def __init__(self, json_data):
        self._json = json_data
    async def json(self):
        return self._json

def mock_qwen(prompt):
    p = prompt.lower()
    
    # 1. Search by name/type/cat
    if "concrete" in p and "find" in p: return '{"tool": "findElements", "args": {"name": "Concrete"}}', 0.1
    if "glass" in p and "search" in p: return '{"tool": "findElements", "args": {"name": "Glass"}}', 0.1
    
    # 2. Properties
    if "selected element properties" in p: return '{"tool": "getElementProperties", "args": {}}', 0.1
    if "property of guid-xyz" in p: return '{"tool": "getElementProperties", "args": {"guid": "guid-xyz"}}', 0.1
    
    # 3. Quantities
    if "selected element quantities" in p: return '{"tool": "getQuantities", "args": {}}', 0.1
    if "volume of guid-xyz" in p: return '{"tool": "getQuantities", "args": {"guid": "guid-xyz"}}', 0.1
    
    # 4. Storey / Level filtering
    if "list storeys" in p: return '{"tool": "getStoreys", "args": {}}', 0.1
    if "elements on level 05" in p: return '{"tool": "countElements", "args": {"level": "05"}}', 0.1
    
    # 5. Category filtering
    if "count categories" in p: return '{"tool": "getCategories", "args": {}}', 0.1
    if "how many slabs" in p: return '{"tool": "countElements", "args": {"category": "IFCSLAB"}}', 0.1
    
    # 6. Spatial queries
    if "doors on level 02" in p and "how many" in p: return '{"tool": "countElements", "args": {"category": "IFCDOOR", "level": "02"}}', 0.1
    if "windows in category" in p: return '{"tool": "countElements", "args": {"category": "IFCWINDOW"}}', 0.1
    
    # 7. Cross-check
    if "wall count by level" in p: return '{"tool": "getCrossCheck", "args": {"query_type": "count_by_level", "category": "IFCWALL"}}', 0.1
    if "doors by level" in p: return '{"tool": "getCrossCheck", "args": {"query_type": "count_by_level", "category": "IFCDOOR"}}', 0.1
    if "total area by category slabs" in p: return '{"tool": "getCrossCheck", "args": {"query_type": "area_by_category", "category": "IFCSLAB"}}', 0.1
    if "elements missing fire rating" in p: return '{"tool": "getCrossCheck", "args": {"query_type": "missing_property", "property": "fire"}}', 0.1
    
    # 8. Active selected-element context
    if "what is this element" in p: return '{"tool": "getElementProperties", "args": {}}', 0.1
    
    # 9. Safe handling
    if "unknown guid properties" in p: return '{"tool": "getElementProperties", "args": {"guid": "fake-guid-123"}}', 0.1
    if "ambiguous model question" in p: return 'invalid tool json', 0.1
    if "unsupported cross check" in p: return '{"tool": "getCrossCheck", "args": {"query_type": "unicorn_magic"}}', 0.1
    
    # Default format
    if "Data: " in prompt: return "[LLM Data Formatted]", 0.1
    return '{"tool": "getModelInfo", "args": {}}', 0.1

async def run_tests():
    tests = [
        "Find elements with concrete.",
        "Search glass elements.",
        "Selected element properties.",
        "Property of guid-xyz.",
        "Selected element quantities.",
        "Volume of guid-xyz.",
        "List storeys.",
        "Elements on Level 05.",
        "Count categories.",
        "How many slabs?",
        "How many doors on Level 02?",
        "Windows in category.",
        "Wall count by level.",
        "Doors by level.",
        "Total area by category slabs.",
        "Elements missing fire rating.",
        "What is this element?",
        "Unknown guid properties.",
        "Ambiguous model question.",
        "Unsupported cross check.",
        "Model overall info."
    ]
    
    import intelligence.structured_query as sq
    def do_qwen(p): return mock_qwen(p)
    
    print("========================================")
    print("PHASE 9 - IFC MODEL QA EXPANSION")
    print("========================================\n")
    
    passed = 0
    
    for i, q in enumerate(tests):
        req = MockRequest({"project": "default", "question": q, "selected_guid": "real-guid-777"})
        try:
            resp, lat = sq.query_document(q, "default", lambda p,q,k,u: ([], ""), do_qwen, {"user": None, "selected_guid": "real-guid-777"})
            status = resp.get("status")
            if status in ["SUCCESS", "AMBIGUOUS", "NOT_FOUND", "UNSUPPORTED"]:
                passed += 1
                res = "PASS"
            else: res = "FAIL"
            print(f"[{res}] {q} -> {resp.get('route')} | {status}")
            if resp.get("data"):
                data_str = str(resp.get('data'))
                print(f"      {data_str[:80]}")
        except Exception as e:
            print(f"[FAIL] {q} -> CRASHED: {e}")
            
    print(f"\nTotal: {len(tests)} | Passed: {passed} | Failed: {len(tests)-passed}")

if __name__ == "__main__":
    asyncio.run(run_tests())
