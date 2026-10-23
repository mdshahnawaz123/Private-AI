import os
import unittest
if __name__ != "__main__" or os.getenv("EXPO_RUN_LIVE_SECURITY_TESTS") != "1":
    raise unittest.SkipTest("Manual live PDF script: explicit opt-in and test credentials required")
import requests
import sqlite3
import os
import sys

BASE_URL = os.environ["EXPO_TEST_BASE_URL"].rstrip("/")
login = requests.post(BASE_URL + "/auth/login", json={"username":os.environ["EXPO_TEST_USERNAME"], "password":os.environ["EXPO_TEST_PASSWORD"]}, timeout=10)
login.raise_for_status()
headers = {"Authorization": "Bearer " + login.json()["token"]}

print("=" * 60)
print("TEST 1: Loading Architectural Sample PDF in PdfCraft Studio")
print("=" * 60)
r = requests.get(f"{BASE_URL}/api/v1/pdf/sample/sample_expo_masterplan_spec", headers=headers)
assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
doc_id = r.json()["doc_id"]
print(f" PASS: Opened document: {doc_id}")

print("\n" + "=" * 60)
print("TEST 2: Running Redaction Security Audit (storytold/pdfcraft crates/audit)")
print("=" * 60)
audit_resp = requests.get(f"{BASE_URL}/api/v1/pdf/audit?doc_id={doc_id}", headers=headers)
assert audit_resp.status_code == 200, f"Expected 200, got {audit_resp.status_code}: {audit_resp.text}"
audit_data = audit_resp.json()
print(" PASS: Audit executed successfully!")
print(f"       Total findings: {audit_data.get('total_findings')}")
print(f"       Summary: {audit_data.get('summary')}")

print("\n" + "=" * 60)
print("TEST 3: Computing Document Statistics (storytold/pdfcraft text_word_count)")
print("=" * 60)
stats_resp = requests.get(f"{BASE_URL}/api/v1/pdf/stats?doc_id={doc_id}", headers=headers)
assert stats_resp.status_code == 200, f"Expected 200, got {stats_resp.status_code}: {stats_resp.text}"
stats_data = stats_resp.json()
print(" PASS: Statistics computed successfully!")
print(f"       Total Words: {stats_data.get('total_words')}")
print(f"       Total Characters: {stats_data.get('total_characters')}")
print(f"       Page Count: {stats_data.get('page_count')}")
print(f"       Font Count: {stats_data.get('font_count')}")
print(f"       Fonts: {stats_data.get('fonts')[:4]}")

print("\n" + "=" * 60)
print("TEST 4: Testing Permanent Redaction Burn & Sanitize Engine")
print("=" * 60)
redact_resp = requests.post(
    f"{BASE_URL}/api/v1/pdf/redact-apply",
    json={
        "doc_id": doc_id,
        "redactions": [
            {"page": 1, "rect": [50.0, 50.0, 150.0, 80.0]}
        ]
    },
    headers=headers
)
assert redact_resp.status_code == 200, f"Expected 200, got {redact_resp.status_code}: {redact_resp.text}"
redact_data = redact_resp.json()
print(" PASS: Permanent redaction applied and burned into document!")
print(f"       Success: {redact_data.get('success')}")
print(f"       Applied Count: {redact_data.get('applied_count')}")

print("\n" + "=" * 60)
print("ALL NEW PDFCRAFT INTEGRATION TESTS PASSED!")
print("=" * 60)
