import os
import sys
import json
import httpx

sys.path.append(os.getcwd())
import db
from intelligence.structured_query import extract_and_store_structured_records, parse_structured_query, execute_structured_query

def call_qwen(question, context):
    sys_msg = f"""You are a BIM data assistant.
A deterministic database lookup has already calculated and verified the answer.
VERIFIED RECORD:
---
{context}
---
Write a concise natural language answer using ONLY the verified record. You MUST append the Provenance exactly as provided. DO NOT invent values."""
    
    payload = {
        "model": "qwen2.5:32b",
        "prompt": sys_msg + "\n\nUser: " + question + "\nAssistant:",
        "stream": False,
        "options": {"temperature": 0.0}
    }
    try:
        r = httpx.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=60)
        return r.json().get("response", "").strip()
    except Exception as e:
        return f"[Qwen Offline] Mock response based on verified record: \n{context}"

if __name__ == "__main__":
    pdf_path = r"C:\3EH\ExpoDesignAI - Copy\data\docs\C3085 - 3EH -Expo Hills\Schedules\C3085-SCH-3EH6105-AR-0000001(5).pdf"
    project_id = 1 # Mock project ID
    filename = "C3085-SCH-3EH6105-AR-0000001(5).pdf"
    
    # Ensure project exists
    session = db.SessionLocal()
    proj = session.query(db.Project).filter_by(id=project_id).first()
    if not proj:
        proj = db.Project(id=project_id, name="Test Project")
        session.add(proj)
        session.commit()
    session.close()
    
    print("--- 1. EXTRACTION PHASE ---")
    recs = extract_and_store_structured_records(pdf_path, project_id, filename, revision="Rev 1")
    print(f"Extracted and stored {recs} structured hierarchical records.\n")
    
    questions = [
        "Tower 6 Level 02 Floor GFA",
        "What is Tower 6 Level 2 Floor GA?",
        "Give me Tower 6 Level 02 BUA",
        "What is the total GFA for Tower 6?",
        "What is the difference between Tower 6 Level 02 and Level 11 GFA?",
        "What percentage of Tower 6 Level 02 GFA is NSA?",
        "What is the GFA of Level 02?",
        "Who is the main consultant?",
        "What is the Floor GFA for Tower 99 Level 1?"
    ]
    
    print("--- 2. QUERY & VALIDATION PHASE ---\n")
    for q in questions:
        print(f"Question: {q}")
        parsed = parse_structured_query(q)
        
        if not parsed:
            print("Route: Normal RAG (BM25/FAISS)")
            print("Final answer: [Handled by existing ask_stream]")
            print("-" * 50)
            continue
            
        print("Route: Structured Deterministic Table Lookup")
        print(f"Structured Query: {parsed}")
        
        status, context = execute_structured_query(parsed, project_id)
        
        if status == "ambiguous":
            print(f"Validation: AMBIGUOUS")
            print(f"Final answer: {context}")
        elif status == "not_found":
            print(f"Validation: NOT FOUND")
            print(f"Final answer: {context} (LLM prevented from hallucinating)")
        else:
            print("Database records: FOUND VERIFIED DATA")
            print(f"Calculation/Data:\n{context}")
            # Call Qwen
            final = call_qwen(q, context)
            print(f"Qwen Input: [System Msg + Verified Data] + {q}")
            print(f"Final answer: {final}")
            
        print("-" * 50)
