import asyncio
from main import app, auth
import json

auth.require_project = lambda request, project: {"user_id": "test_user"}

class FakeRequest1:
    async def json(self): return {"project": "default", "question": "What is the GFA of Tower 6 Level 2 Rev 1?"}

class FakeRequest2:
    async def json(self): return {"project": "default", "question": "Compare Tower 6 and Tower 8 Level 2 GFA Rev 1"}

class FakeRequest3:
    async def json(self): return {"project": "default", "question": "Who is the main consultant?"}

class FakeRequest4:
    async def json(self): return {"project": "default", "question": "What is the GFA of Tower 99 Level 1?"}

async def run_test():
    import main
    
    print("--- E2E BACKEND INTEGRATION TESTS ---")
    r1 = await main.api_query_document(FakeRequest1())
    print("Test 1 (Structured GFA):", r1.get("status"), "| Route:", r1.get("route"))
    
    r2 = await main.api_query_document(FakeRequest2())
    print("Test 2 (Calculation Comparison):", r2.get("status"), "| Route:", r2.get("route"), "| Calc:", r2.get("calculation", {}).get("operation"))

    r3 = await main.api_query_document(FakeRequest3())
    print("Test 3 (RAG Fallback):", r3.get("status"), "| Route:", r3.get("route"))
    
    r4 = await main.api_query_document(FakeRequest4())
    print("Test 4 (Missing/Not Found):", r4.get("status"), "| Route:", r4.get("route"))

asyncio.run(run_test())
