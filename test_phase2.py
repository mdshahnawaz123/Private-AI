"""
Phase-2 smoke test. Run on a machine where requirements are installed:

    python test_phase2.py

It uses a throwaway temp data dir, so it never touches your real data/ folder.
Exits 0 on success, 1 on failure.
"""
import os, sys, tempfile, json, shutil

tmp = tempfile.mkdtemp(prefix="expo_p2_")
os.environ["EXPO_DATA_DIR"] = tmp
os.environ["EXPO_DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "expo.db")

# seed a legacy JSON chat to prove the migration
os.makedirs(os.path.join(tmp, "projects", "DemoProj"), exist_ok=True)
with open(os.path.join(tmp, "projects", "DemoProj", "chat_legacy1.json"), "w", encoding="utf-8") as f:
    json.dump({"title": "Legacy review", "messages": [{"role": "user", "content": "hi"}]}, f)

import db
from sqlalchemy import text

ok = True
def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok = ok and bool(cond)

db.init_db()

pw = db.projects_with_chats()
check("legacy JSON migrated", "DemoProj" in pw and "chat_legacy1" in pw["DemoProj"])

db.save_chat("Bridge-MEP", "c1", "MEP coordination", [{"role": "user", "content": "duct clash?"}])
loaded = db.load_chat("Bridge-MEP", "c1")
check("save + load chat", loaded and loaded["title"] == "MEP coordination")

db.save_chat("Bridge-MEP", "c1", "MEP v2", [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
check("upsert same chat", db.load_chat("Bridge-MEP", "c1")["title"] == "MEP v2")

db.record_document("Bridge-MEP", "ductwork.pdf", "/x/ductwork.pdf", 42)
check("document record + clear", db.clear_docs("Bridge-MEP") == 1)

check("delete chat", db.delete_chat("Bridge-MEP", "c1") and db.load_chat("Bridge-MEP", "c1") is None)

actions = [r["action"] for r in db.recent_audit(limit=100)]
check("audit captured actions",
      all(a in actions for a in ["project.create", "chat.save", "document.upload", "document.clear", "chat.delete"]))

blocked = 0
for stmt in ["UPDATE audit_log SET action='x' WHERE id=1", "DELETE FROM audit_log WHERE id=1"]:
    try:
        with db.engine.begin() as c:
            c.execute(text(stmt))
    except Exception:
        blocked += 1
check("audit log append-only (UPDATE+DELETE blocked)", blocked == 2)

db.engine.dispose()
shutil.rmtree(tmp, ignore_errors=True)
print("\n" + ("ALL PHASE-2 TESTS PASSED" if ok else "SOME TESTS FAILED"))
sys.exit(0 if ok else 1)
