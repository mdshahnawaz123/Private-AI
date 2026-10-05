from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

res = client.post("/api/query_document", json={
    "project": "default",
    "question": "What is the GFA of Tower 6 Level 2?"
})

print(res.status_code)
print(res.json())
