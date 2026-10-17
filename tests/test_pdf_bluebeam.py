"""
Test Suite: Bluebeam Revu Counterpart Features for PdfCraft Studio
Tests:
1. Bluebeam Overlay Pages (Two-color subtractive raster comparison: Red vs Green)
2. Bluebeam Local AI Markups Review Memo (QA/QC punch-list via local qwen3.5:9b)
3. Markups List integration (Revision Clouds, Callouts, Stamps, Calibrated Measurements)
"""
import sys
import os
import requests
import json
import sqlite3

BASE_URL = "http://127.0.0.1:8090"

sys.path.insert(0, os.path.abspath("."))
import auth

# 1. Auth token
conn = sqlite3.connect("data/expo.db")
cur = conn.cursor()
user_row = cur.execute("SELECT id, username, role FROM users WHERE username='admin'").fetchone()
token = auth.make_token({"id": user_row[0], "username": user_row[1], "role": user_row[2]})
headers = {"Authorization": f"Bearer {token}"}

print("=" * 65)
print("TEST 1: Opening Sample Architectural PDF in PdfCraft")
print("=" * 65)
open_resp = requests.get(f"{BASE_URL}/api/v1/pdf/sample/sample_expo_masterplan_spec", headers=headers)
assert open_resp.status_code == 200, f"Expected 200, got {open_resp.status_code}: {open_resp.text}"
data = open_resp.json()
doc_id = data["doc_id"]
print(f" PASS: Opened sample document {doc_id}")
print(f"       Filename: {data['filename']}, Pages: {data['info']['page_count']}")

print("\n" + "=" * 65)
print("TEST 2: Bluebeam Overlay Pages (Two-color Red vs Green Comparison)")
print("=" * 65)
# Test compare page 1 with page 1 (should render clean black lines on white paper)
overlay_resp = requests.get(
    f"{BASE_URL}/api/v1/pdf/overlay?doc1={doc_id}&page1=1&doc2={doc_id}&page2=1",
    headers=headers
)
assert overlay_resp.status_code == 200, f"Expected 200, got {overlay_resp.status_code}"
assert overlay_resp.headers.get("Content-Type") == "image/png"
assert len(overlay_resp.content) > 5000, f"Overlay image too small: {len(overlay_resp.content)} bytes"
print(f" PASS: Differential overlay generated successfully ({len(overlay_resp.content)} bytes PNG)")

# Test compare page 1 with page 2 (multi-page differential)
if data["info"]["page_count"] > 1:
    overlay_diff_resp = requests.get(
        f"{BASE_URL}/api/v1/pdf/overlay?doc1={doc_id}&page1=1&doc2={doc_id}&page2=2",
        headers=headers
    )
    assert overlay_diff_resp.status_code == 200, f"Expected 200, got {overlay_diff_resp.status_code}"
    print(f" PASS: Page 1 vs Page 2 multi-page overlay generated ({len(overlay_diff_resp.content)} bytes)")

print("\n" + "=" * 65)
print("TEST 3: Bluebeam Local AI Markups Review Memo (qwen3.5:9b)")
print("=" * 65)
sample_markups = [
    {
        "id": "mk_101",
        "page": 1,
        "subject": "Revision Cloud",
        "type": "cloud",
        "author": "Lead Structural Engineer",
        "date": "2026-10-17 12:00",
        "status": "Pending",
        "measurement": "—",
        "text": "Revision required: Verify transfer slab cantilever reinforcement and deflection limits under seismic load"
    },
    {
        "id": "mk_102",
        "page": 1,
        "subject": "Engineering Callout",
        "type": "callout",
        "author": "MEP Coordinator",
        "date": "2026-10-17 12:05",
        "status": "Pending",
        "measurement": "—",
        "text": "HVAC duct shaft conflicts with structural shear wall boundary element"
    },
    {
        "id": "mk_103",
        "page": 1,
        "subject": "Stamp: REVISE & RESUBMIT",
        "type": "stamp",
        "stampType": "REVISE & RESUBMIT",
        "author": "Chief Architect",
        "date": "2026-10-17 12:10",
        "status": "Rejected",
        "measurement": "—",
        "text": "REVISE & RESUBMIT"
    },
    {
        "id": "mk_104",
        "page": 2,
        "subject": "Calibrated Distance",
        "type": "distance",
        "author": "Civil Lead",
        "date": "2026-10-17 12:15",
        "status": "Accepted",
        "measurement": "18.50 m",
        "text": "Verified fire truck turning radius clearance"
    }
]

memo_resp = requests.post(
    f"{BASE_URL}/api/v1/pdf/summarize-markups",
    json={
        "markups": sample_markups,
        "document_name": "Expo_Hills_Masterplan_Spec.pdf"
    },
    headers=headers
)
assert memo_resp.status_code == 200, f"Expected 200, got {memo_resp.status_code}: {memo_resp.text}"
memo_data = memo_resp.json()
assert "summary" in memo_data, "Missing 'summary' in response"
summary = memo_data["summary"]
print(" PASS: Local AI memo generated successfully!")
print(f"       Executive Summary: {summary.get('executive_summary', '')[:120]}...")
print(f"       Total Count: {summary.get('total_count')}")
print(f"       Open Issues: {summary.get('open_issues_count')}")
print(f"       By Discipline: {summary.get('by_discipline')}")
print(f"       Action Items ({len(summary.get('action_items', []))}):")
for item in summary.get('action_items', []):
    print(f"         • {item}")

print("\n" + "=" * 65)
print("TEST 4: Frontend UI Assets Verification (ui/pdfcraft.js)")
print("=" * 65)
with open("ui/pdfcraft.js", "r", encoding="utf-8") as f:
    js_content = f.read()

required_symbols = [
    "_generateCloudSvgPath",
    "_toggleMarkupsDrawer",
    "_renderMarkupsTable",
    "_locateMarkup",
    "_updateMarkupStatus",
    "_updateMarkupComment",
    "_deleteMarkup",
    "_exportMarkupsCsv",
    "_pickStamp",
    "_renderToolChestContent",
    "_selectToolChestTool",
    "_openAiMarkupsReviewModal",
    "_openOverlayModal",
    "pdf-markups-drawer",
    "pdf-stamp-box",
    "pdf-toolchest-card"
]

for sym in required_symbols:
    assert sym in js_content, f"Missing required Bluebeam UI symbol in pdfcraft.js: {sym}"
    print(f" PASS: Found {sym} in ui/pdfcraft.js")

print("\n" + "=" * 65)
print("ALL BLUEBEAM REVU COUNTERPART TESTS PASSED!")
print("=" * 65)
