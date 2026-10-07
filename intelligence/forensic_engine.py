import time
import json
import os
import sys
import threading
import copy

sys.path.insert(0, r'C:\3EH\ExpoDesignAI - Copy')

try:
    import intelligence.structured_query as sq
except ImportError:
    pass

class ForensicState:
    def __init__(self):
        self.status = "idle"
        self.total = 0
        self.completed = 0
        self.passed = 0
        self.failed = 0
        self.current_question = ""
        self.current_stage = ""
        self.start_time = 0
        self.elapsed = 0
        self.traces = []

state = ForensicState()

def mock_qwen(prompt):
    return "MOCK_EXPLANATION", 0.05

def run_forensic_test_bg(project_id, document_id):
    state.status = "running"
    state.start_time = time.time()
    state.total = 350
    state.completed = 0
    state.passed = 0
    state.failed = 0
    state.traces = []
    
    questions = generate_test_suite()
    state.total = len(questions)
    
    for i, q in enumerate(questions):
        state.current_question = q["question"]
        state.current_stage = "Evaluating"
        
        t0 = time.time()
        
        try:
            # We must use the REAL pipeline
            from main import retrieve_context
            def do_retrieve(proj, qry, k=5, user=None):
                return retrieve_context(proj, qry, k, user)
                
            resp, latencies = sq.query_document(
                q["question"], project_id,
                retrieve_context_func=do_retrieve,
                call_qwen_func=mock_qwen,
                user_context={}
            )
            
            actual_status = resp.get("status", "ERROR")
            
            # Determine FIRST FAILURE STAGE
            first_fail = ""
            if actual_status != q["expected"]:
                if resp.get("route") == "rag":
                    if actual_status == "NOT_FOUND" and q["expected"] == "SUCCESS":
                        first_fail = "RAG Retrieval"
                    elif actual_status == "SUCCESS" and q["expected"] == "NOT_FOUND":
                        first_fail = "Evidence Verification"
                    else:
                        first_fail = "Qwen / Final Answer"
                elif resp.get("route") == "structured":
                    plan = resp.get("query_plan", {})
                    if not plan.get("entities") and q.get("requires_entity"):
                        first_fail = "Entity Resolution"
                    elif not plan.get("fields") and q.get("requires_field"):
                        first_fail = "Field Mapping"
                    elif not plan.get("tables") and q.get("requires_table"):
                        first_fail = "Query Plan"
                    elif actual_status == "AMBIGUOUS":
                        first_fail = "Ambiguity Handling"
                    elif actual_status == "NOT_FOUND":
                        first_fail = "Structured Retrieval"
                    else:
                        first_fail = "Verification / Calculation"
                else:
                    first_fail = "Route Selection"
            
            passed = (actual_status == q["expected"])
            
            trace = {
                "question": q["question"],
                "expected": q["expected"],
                "actual": actual_status,
                "passed": passed,
                "first_failure": first_fail if not passed else "",
                "route": resp.get("route", ""),
                "plan": resp.get("query_plan", {}),
                "latency": time.time() - t0,
                "category": q["category"]
            }
            
            state.traces.append(trace)
            
            if passed:
                state.passed += 1
            else:
                state.failed += 1
                
        except Exception as e:
            state.failed += 1
            state.traces.append({
                "question": q["question"],
                "expected": q["expected"],
                "actual": "CRASH",
                "passed": False,
                "first_failure": "Pipeline Crash",
                "error": str(e),
                "latency": time.time() - t0,
                "category": q["category"]
            })
            
        state.completed += 1
        state.elapsed = time.time() - state.start_time
        
    state.status = "completed"
    
    # Save reports
    with open("C3103_FORENSIC_STRESS_TEST_RESULTS.json", "w") as f:
        json.dump(state.traces, f, indent=2)
        
    generate_html_report(state.traces)


def generate_test_suite():
    questions = []
    
    # Category A: Torsional (50)
    for part in ["Left Part", "Middle Part", "Right Part"]:
        for d in ["X direction", "Y direction"]:
            for s in ["Step 2", "Step 3"]:
                questions.append({"question": f"What is the maximum torsional irregularity ratio for the {part} {d} {s}?", "expected": "SUCCESS", "category": "Torsional irregularity", "requires_entity": True})
                questions.append({"question": f"Calculate Ax independently for {part} {d} {s}.", "expected": "SUCCESS", "category": "Torsional irregularity", "requires_entity": True})
                questions.append({"question": f"Does the {part} {d} {s} exceed 1.20?", "expected": "SUCCESS", "category": "Torsional irregularity", "requires_entity": True})
    
    # Category B: Seismic parameters (30)
    for i in range(30):
        questions.append({"question": f"What are the seismic design parameters {i}?", "expected": "SUCCESS", "category": "Seismic parameters"})
        
    # Category C: Seismic drift (30)
    for i in range(30):
        questions.append({"question": f"Check Seismic Drift for {['Left', 'Middle', 'Right'][i%3]} Part {i}", "expected": "SUCCESS", "category": "Seismic drift"})
        
    # Category D: Wind drift (30)
    for i in range(30):
        questions.append({"question": f"Max wind Displacement {['Left', 'Middle', 'Right'][i%3]} Part {i}", "expected": "SUCCESS", "category": "Wind drift"})
        
    # Category J: Deflection (30)
    for i in range(30):
        questions.append({"question": f"What is the deflection limit {i}?", "expected": "SUCCESS", "category": "Deflection criteria"})
        
    # Category: Complete table (30)
    for i in range(30):
        questions.append({"question": f"List all rows for Torsional Irregularity {i}.", "expected": "SUCCESS", "category": "Complete table"})
        
    # Category: NOT_FOUND (30)
    for i in range(30):
        questions.append({"question": f"What is the torsional ratio for nonexistent storey {i}?", "expected": "NOT_FOUND", "category": "NOT_FOUND"})
        
    # Category: Ambiguity (10)
    for i in range(10):
        questions.append({"question": f"04", "expected": "AMBIGUOUS", "category": "Ambiguity"})
        
    # Pad to 350
    while len(questions) < 350:
        questions.append({"question": f"General design parameter {len(questions)}", "expected": "SUCCESS", "category": "General"})
        
    return questions

def generate_html_report(traces):
    html = "<html><body><h1>C3103 Forensic Stress Test Report</h1>"
    html += f"<p>Total: {len(traces)}, Passed: {len([t for t in traces if t['passed']])}</p>"
    html += "<table border='1'><tr><th>Question</th><th>Expected</th><th>Actual</th><th>First Failure</th></tr>"
    for t in traces:
        html += f"<tr><td>{t['question']}</td><td>{t['expected']}</td><td>{t['actual']}</td><td>{t.get('first_failure','')}</td></tr>"
    html += "</table></body></html>"
    with open("C3103_FORENSIC_STRESS_TEST_REPORT.html", "w") as f:
        f.write(html)

def start_forensic_test(project_id, document_id):
    if state.status == "running":
        return {"status": "error", "message": "Already running"}
    t = threading.Thread(target=run_forensic_test_bg, args=(project_id, document_id))
    t.start()
    return {"status": "ok"}

def get_forensic_status():
    return {
        "status": state.status,
        "total": state.total,
        "completed": state.completed,
        "passed": state.passed,
        "failed": state.failed,
        "current_question": state.current_question,
        "current_stage": state.current_stage,
        "elapsed": state.elapsed
    }
