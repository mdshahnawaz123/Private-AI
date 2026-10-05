import asyncio
import io
import fitz
import json
import base64
from fastapi.testclient import TestClient
from main import app, auth
import db

app.dependency_overrides[auth.require_user] = lambda: {"username": "Test Reviewer"}

client = TestClient(app)

def test_phase13():
    print("========================================")
    print("PHASE 13 - PDF DRAWING REVIEW ENGINE")
    print("========================================\n")
    
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Test Drawing A-101")
    pdf_bytes = doc.write()
    b64_pdf = "data:application/pdf;base64," + base64.b64encode(pdf_bytes).decode("utf-8")
    doc_id = "A-101"
    
    session = db.SessionLocal()
    session.query(db.Annotation).filter_by(document_id=doc_id).delete()
    session.commit()
    session.close()
    
    anns = [
        {"document_id": doc_id, "drawing": doc_id, "annotation_type": "text", "x": 0.1, "y": 0.1, "width": 0.1, "height": 0.05, "page_number": 1, "comment_text": "Please fix door swing.", "status": "OPEN", "revision": "Rev 1"},
        {"document_id": doc_id, "drawing": doc_id, "annotation_type": "cloud", "x": 0.2, "y": 0.2, "width": 0.1, "height": 0.1, "page_number": 1, "comment_text": "Cloud annotation.", "status": "OPEN", "revision": "Rev 1"},
        {"document_id": doc_id, "drawing": doc_id, "annotation_type": "arrow", "x": 0.4, "y": 0.4, "width": 0.1, "height": 0.1, "page_number": 1, "comment_text": "Arrow pointing here.", "status": "OPEN", "revision": "Rev 1"}
    ]
    
    created_ids = []
    for a in anns:
        resp = client.post("/api/annotations", json=a)
        if resp.status_code != 200:
            print(resp.json())
        assert resp.status_code == 200
        data = resp.json()
        assert data["annotation_type"] == a["annotation_type"]
        created_ids.append(data["id"])
    print("[PASS] Created Text, Cloud, Arrow annotations with normalized coordinates.")
    
    resp = client.get(f"/api/annotations/{doc_id}")
    assert len(resp.json()) == 3
    print("[PASS] Retrieved annotations accurately.")
    
    resp = client.put(f"/api/annotations/{created_ids[0]}", json={"status": "CLOSED"})
    assert resp.status_code == 200
    resp = client.get(f"/api/annotations/{doc_id}")
    assert resp.json()[0]["status"] == "CLOSED"
    print("[PASS] Updated annotation status (OPEN -> CLOSED).")
    
    resp = client.get(f"/api/annotations/export/excel/{doc_id}")
    assert resp.status_code == 200
    assert "application/vnd.openxmlformats" in resp.headers["content-type"]
    print("[PASS] Excel export generated successfully.")
    
    resp = client.post(f"/api/annotations/export/pdf", json={"document_id": doc_id, "file_data": b64_pdf})
    assert resp.status_code == 200
    assert "pdf_data" in resp.json()
    print("[PASS] Annotated PDF exported successfully (fitz drawn).")
    
    resp = client.delete(f"/api/annotations/{created_ids[1]}")
    assert resp.status_code == 200
    resp = client.get(f"/api/annotations/{doc_id}")
    assert len(resp.json()) == 2
    print("[PASS] Annotation deleted (Eraser).")
    
    print("\nPhase 13 tests passed!")

if __name__ == "__main__":
    test_phase13()
