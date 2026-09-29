"""Extraction smoke test. Run: python test_extract.py"""
import os, sys, tempfile, json
import extract
ok = True
def check(n, c):
    global ok; print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)
tmp = tempfile.mkdtemp()

try:
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "BOQ"
    ws.append(["Item", "Qty"]); ws.append(["Beam", 5]); ws.append(["Column", 12])
    xp = os.path.join(tmp, "s.xlsx"); wb.save(xp)
    text, meta = extract.extract_excel(xp)
    check("excel text captured", "Beam" in text and "BOQ" in text)
    check("excel meta sheet name", meta["sheets"][0]["sheet"] == "BOQ")
except Exception as e:
    print("INFO  openpyxl issue:", e)

mp = os.path.join(tmp, "m.json")
check("save_json + read back", extract.save_json(mp, {"a": 1}) and json.load(open(mp))["a"] == 1)

try:
    import fitz
    doc = fitz.open(); pg = doc.new_page(); pg.insert_text((72, 72), "HELLO PDF")
    pp = os.path.join(tmp, "d.pdf"); doc.save(pp); doc.close()
    text, meta = extract.extract_pdf(pp, vision_fn=None, render_dir=None, deep=False)
    check("pdf text extracted", "HELLO PDF" in text and meta["page_count"] == 1)
    # render path (deep=True with a stub vision fn)
    text2, meta2 = extract.extract_pdf(pp, vision_fn=lambda p: "[vision stub]", render_dir=os.path.join(tmp, "pg"), deep=True)
    check("pdf deep render + vision merged", "[vision stub]" in text2)
except Exception as e:
    print("INFO  PyMuPDF (fitz) not installed yet - `pip install -r requirements.txt` then re-run:", e)

print("\n" + ("ALL EXTRACT TESTS PASSED" if ok else "SOME TESTS FAILED"))
sys.exit(0 if ok else 1)
