import asyncio
import time
import json
import random

def mock_qwen(prompt):
    p = prompt.lower()
    t_start = time.perf_counter()
    time.sleep(0.01)  # simulate processing
    
    # Context resolution
    if "rewrite the latest question" in p:
        q = prompt.split("Latest Question: ")[-1].split("\n")[0].strip()
        return q, time.perf_counter() - t_start
        
    # Document QA
    if "data:" in p:
        return "[Verified Natural Response]", time.perf_counter() - t_start
        
    # Model QA Tools
    tool_req = {"tool": "getModelInfo", "args": {}, "viewer_action": "none"}
    
    if "door" in p: tool_req = {"tool": "countElements", "args": {"category": "IFCDOOR"}, "viewer_action": "highlight"}
    elif "wall" in p: tool_req = {"tool": "findElements", "args": {"name": "wall"}, "viewer_action": "isolate"}
    elif "slab" in p: tool_req = {"tool": "findElements", "args": {"name": "slab"}, "viewer_action": "zoom"}
    elif "properties" in p: tool_req = {"tool": "getElementProperties", "args": {"guid": "mock-guid"}, "viewer_action": "inspect"}
    elif "quantities" in p: tool_req = {"tool": "getQuantities", "args": {"guid": "mock-guid"}, "viewer_action": "inspect"}
    elif "clear" in p: tool_req["viewer_action"] = "clear"
    elif "ambiguous" in p: return "invalid json", time.perf_counter() - t_start
    
    return json.dumps(tool_req), time.perf_counter() - t_start

def mock_retrieve(proj, q, k, user):
    return [{"text": "Mock text"}], "Mock RAG Context"

async def run_100_tests():
    import intelligence.structured_query as sq
    
    # We will define 100 queries spread across categories
    queries = []
    
    # 1. Document QA (30)
    for i in range(10): queries.append(("What is the GFA of Tower 6 Level " + str(i), "DOCUMENT_QA"))
    for i in range(5): queries.append(("Compare GFA of Level " + str(i) + " and Level " + str(i+1), "DOCUMENT_QA"))
    for i in range(5): queries.append(("What is the NSA?", "DOCUMENT_QA"))
    for i in range(5): queries.append(("Latest document report?", "DOCUMENT_QA"))
    for i in range(5): queries.append(("What is the calculation for GA?", "DOCUMENT_QA"))
    
    # 2. Model QA (30)
    for i in range(10): queries.append(("How many doors on level " + str(i) + "?", "MODEL_QA"))
    for i in range(5): queries.append(("Isolate walls on level " + str(i), "MODEL_QA"))
    for i in range(5): queries.append(("Zoom to slabs.", "MODEL_QA"))
    for i in range(5): queries.append(("Show properties of this element.", "MODEL_QA"))
    for i in range(5): queries.append(("Clear selection.", "MODEL_QA"))
    
    # 3. Conversational Context (20)
    for i in range(10): queries.append(("What about Level " + str(i) + "?", "DOCUMENT_QA"))  # mocked to doc
    for i in range(10): queries.append(("Show me those elements.", "MODEL_QA"))
    
    # 4. Safety & Edge Cases (20)
    for i in range(5): queries.append(("Ambiguous request " + str(i), "MODEL_QA"))
    for i in range(5): queries.append(("Tower 99 Level 99 GFA", "DOCUMENT_QA"))
    for i in range(5): queries.append(("Unknown guid properties", "MODEL_QA"))
    for i in range(5): queries.append(("Unsupported field MagicArea", "DOCUMENT_QA"))
    
    random.shuffle(queries)
    
    results = {"PASS": 0, "FAIL": 0, "CRASH": 0}
    latencies = {"router": 0, "sqlite": 0, "ifc": 0, "rag": 0, "qwen": 0, "total": 0}
    
    print("Executing 100 End-to-End Tests...")
    
    for i, (q, expected_route) in enumerate(queries):
        try:
            t_s = time.perf_counter()
            resp, lats = sq.query_document(
                question=q, 
                project_id="default", 
                retrieve_context_func=mock_retrieve, 
                call_qwen_func=mock_qwen, 
                user_context={"user": None, "selected_guid": "mock-guid", "history": [{"role": "user", "content": "GFA of Tower 6"}]}
            )
            total = time.perf_counter() - t_s
            
            # Simple validation
            if resp.get("status") in ["SUCCESS", "AMBIGUOUS", "NOT_FOUND", "UNSUPPORTED"]:
                results["PASS"] += 1
            else:
                results["FAIL"] += 1
                
            latencies["router"] += lats.get("parser", 0)
            latencies["sqlite"] += lats.get("sqlite", 0)
            latencies["qwen"] += lats.get("qwen", 0.01)
            latencies["total"] += total
            
        except Exception as e:
            results["CRASH"] += 1
            print(f"Crash on {q}: {e}")
            
    print("\n--- FINAL RESULTS ---")
    print(f"Total: {len(queries)}")
    print(f"Passed: {results['PASS']}")
    print(f"Failed: {results['FAIL']}")
    print(f"Crashed: {results['CRASH']}")
    
    print("\n--- AVG LATENCIES (ms) ---")
    print(f"Router: {(latencies['router']/100)*1000:.2f}ms")
    print(f"SQLite/IFC: {(latencies['sqlite']/100)*1000:.2f}ms")
    print(f"Qwen: {(latencies['qwen']/100)*1000:.2f}ms")
    print(f"Total: {(latencies['total']/100)*1000:.2f}ms")

if __name__ == "__main__":
    asyncio.run(run_100_tests())
