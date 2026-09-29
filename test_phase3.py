"""
Phase-3 smoke test (Architecture discipline + code knowledge base).
Run where requirements are installed:  python test_phase3.py
Uses a throwaway temp data dir; never touches your real data/.
"""
import os, sys, tempfile, shutil

tmp = tempfile.mkdtemp(prefix="expo_p3_")
os.environ["EXPO_DATA_DIR"] = tmp
os.environ["EXPO_DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "expo.db")

import disciplines as D
import db

ok = True
def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name); ok = ok and bool(cond)

# disciplines registry
check("normalize Cost / VE", D.normalize("Cost / VE") == "cost_ve")
check("architecture active", D.get("Architecture")["status"] == "active")
check("prompt grounded in DBC/IBC",
      "Dubai Building Code 2021" in D.system_prompt("architecture")
      and "International Building Code 2021" in D.system_prompt("architecture"))
check("no-fabrication rule present",
      "Never guess a number" in D.system_prompt("architecture"))
cl = D.checklist("architecture")
areas = sorted({i["area"] for i in cl})
check("checklist has 4 areas + items", len(cl) >= 20 and len(areas) == 4)
check("every item has code anchors + fields",
      all(all(f in i for f in ("id","area","title","check","ibc","dbc","note")) for i in cl))
check("unknown discipline -> empty prompt", D.system_prompt("nope") == "")

# db: discipline on project + code KB hidden from project list
db.init_db()
db.save_chat("Tower-A", "c1", "kickoff", [{"role":"user","content":"hi"}])
db.set_project_discipline("Tower-A", "architecture")
check("project not leaking code KB", "__codes__" not in db.projects_with_chats())
db.record_document("__codes__", "DBC_2021.pdf", "/x/DBC_2021.pdf", 1200, discipline="code")
db.record_document("__codes__", "IBC_2021.pdf", "/x/IBC_2021.pdf", 1500, discipline="code")
kb = db.list_documents("__codes__")
check("code KB lists both code docs", {d["filename"] for d in kb} == {"DBC_2021.pdf", "IBC_2021.pdf"})
check("__codes__ still hidden from projects", "__codes__" not in db.projects_with_chats())
acts = [r["action"] for r in db.recent_audit(limit=50)]
check("discipline change audited", "project.discipline" in acts)

# --- vision module (Phase 3 vision) ---
import vision as V
check("vision detects images", V.is_image("a.PNG") and not V.is_image("a.pdf"))
check("vision payload deterministic (temp 0)", V.build_payload("Zm9v")["options"]["temperature"] == 0)
check("vision no-guess rule in prompt", "[illegible]" in V.EXTRACTION_PROMPT and "NEVER guess" in V.EXTRACTION_PROMPT)
vok, vdetail = V.health()
print(("INFO  vision model present" if vok else "INFO  vision not detected (start Ollama and `ollama pull %s`)" % V.VISION_MODEL))

db.engine.dispose(); shutil.rmtree(tmp, ignore_errors=True)
print("\n" + ("ALL PHASE-3 TESTS PASSED" if ok else "SOME TESTS FAILED"))
sys.exit(0 if ok else 1)
