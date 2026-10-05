import asyncio
from main import app, auth
import main
import json

auth.require_project = lambda request, project: {"user_id": "test_admin"}

class MockRequest:
    def __init__(self, json_data):
        self._json = json_data
    async def json(self):
        return self._json

def mock_qwen(prompt):
    p = prompt.lower()
    
    # 1. Context Resolution Mock
    if "rewrite the latest question" in p:
        if "what about level 02?" in p and "gfa of tower 6" in p: return "What is the GFA of Tower 6 Level 02?", 0.1
        if "and level 03?" in p and "gfa of tower 6" in p: return "What is the GFA of Tower 6 Level 03?", 0.1
        if "what about the doors?" in p and "how many windows" in p: return "How many doors?", 0.1
        if "show me those" in p and "how many doors" in p: return "Show me the doors.", 0.1
        if "what about this element?" in p: return "What is the property of this element?", 0.1
        if "zoom to them" in p: return "Zoom to the selected elements.", 0.1
        # Fallback to the latest question (just parse it out roughly)
        q = prompt.split("Latest Question: ")[-1].split("\n")[0].strip()
        return q, 0.1
        
    # 2. Model QA Tools Mock
    if "data: " in prompt: return "[Qwen Verified Response]", 0.1
    
    # Defaults for Phase 11
    if "highlight" in p and "slab" in p: return '{"tool": "findElements", "args": {"name": "slab"}, "viewer_action": "highlight"}', 0.1
    if "isolate" in p and "concrete" in p: return '{"tool": "findElements", "args": {"name": "concrete"}, "viewer_action": "isolate"}', 0.1
    if "zoom" in p and "door" in p: return '{"tool": "countElements", "args": {"category": "IFCDOOR"}, "viewer_action": "zoom"}', 0.1
    if "select" in p and "wall" in p: return '{"tool": "getElementProperties", "args": {"guid": "wall-123"}, "viewer_action": "select"}', 0.1
    if p == "clear selection.": return '{"tool": "getModelInfo", "args": {}, "viewer_action": "clear"}', 0.1
    if "properties" in p and "unknown" not in p: return '{"tool": "getElementProperties", "args": {}, "viewer_action": "inspect"}', 0.1
    if "quantities" in p: return '{"tool": "getQuantities", "args": {}, "viewer_action": "inspect"}', 0.1
    if "unknown guid test" in p: return '{"tool": "getElementProperties", "args": {"guid": "fake-123"}, "viewer_action": "highlight"}', 0.1
    if "ambiguous" in p: return 'invalid json', 0.1
    
    return '{"tool": "getModelInfo", "args": {}, "viewer_action": "none"}', 0.1

async def run_tests():
    import intelligence.structured_query as sq
    def do_qwen(p): return mock_qwen(p)
    
    # Phase 10 Tests
    print("========================================")
    print("PHASE 10 - CONVERSATIONAL BIM COPILOT")
    print("========================================\n")
    p10_cases = [
        # Document -> follow-up
        ({"role": "user", "content": "What is the GFA of Tower 6?"}, "What about Level 02?", "What is the GFA of Tower 6 Level 02?", "DOCUMENT_QA"),
        ({"role": "user", "content": "What is the GFA of Tower 6?"}, "And Level 03?", "What is the GFA of Tower 6 Level 03?", "DOCUMENT_QA"),
        # Model -> follow-up
        ({"role": "user", "content": "How many windows?"}, "What about the doors?", "How many doors?", "MODEL_QA"),
        ({"role": "user", "content": "How many doors?"}, "Show me those.", "Show me the doors.", "MODEL_QA"),
        # Selected element
        ({"role": "user", "content": "What is the volume?"}, "What about this element?", "What is the property of this element?", "MODEL_QA"),
    ]
    
    for hist, followup, expected_resolved, expected_route in p10_cases:
        req_hist = [hist]
        resolved = sq.resolve_context(followup, req_hist, do_qwen)
        intent = sq.classify_query(resolved)
        pass_fail = "PASS" if intent == expected_route else "FAIL"
        print(f"[{pass_fail}] {hist['content']} -> {followup} => '{resolved}' ({intent})")
        
    # Phase 11 Tests
    print("\n========================================")
    print("PHASE 11 - ADVANCED AI VIEWER CONTROL")
    print("========================================\n")
    p11_cases = [
        ("Highlight the slab.", "highlight"),
        ("Isolate the concrete walls.", "isolate"),
        ("Zoom to the doors.", "zoom"),
        ("Select the wall.", "select"),
        ("Clear selection.", "clear"),
        ("Show me properties.", "inspect"),
        ("What are the quantities?", "inspect"),
        ("Unknown guid test.", "highlight"),
        ("Ambiguous.", "none"),
        ("What is the GFA?", "none"), # Document QA should have NO viewer action
    ]
    
    for q, expected_action in p11_cases:
        try:
            resp, _ = sq.query_document(q, "default", lambda p,q,k,user=None: ([], ""), do_qwen, {"user": None, "selected_guid": "real-guid-777"})
            if resp.get("route") == "model_qa":
                v_action = resp.get("viewer_action", {}).get("action")
            else:
                v_action = "none" # Document QA has no viewer action
                
            pass_fail = "PASS" if v_action == expected_action or (expected_action == "none" and not resp.get("viewer_action")) else "FAIL"
            print(f"[{pass_fail}] '{q}' -> Action: {v_action} | Status: {resp.get('status')}")
        except Exception as e:
            print(f"[FAIL] '{q}' -> CRASHED: {e}")

if __name__ == "__main__":
    asyncio.run(run_tests())
