"""Phase-5 auth + access-control smoke test. Run: python test_phase5.py
Uses a throwaway temp data dir; never touches real data/."""
import os, sys, tempfile, shutil
tmp = tempfile.mkdtemp(prefix="expo_p5_")
os.environ["EXPO_DATA_DIR"] = tmp
os.environ["EXPO_DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "expo.db")
os.environ["EXPO_ADMIN_PASSWORD"] = "Secret123"

import db
ok = True
def check(n, c):
    global ok; print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)

db.init_db()

try:
    import auth
    HAVE = True
except Exception as e:
    HAVE = False
    print("INFO  auth needs passlib + python-jose (pip install -r requirements.txt):", e)

if HAVE:
    auth.ensure_admin()
    admin = db.get_user_by_username("admin")
    check("admin account seeded", bool(admin) and admin["role"] == "admin")
    check("admin password verifies", auth.verify_password("Secret123", admin["password_hash"]))
    tok = auth.make_token({"id": admin["id"], "username": "admin", "role": "admin"})
    claims = auth.decode_token(tok)
    check("JWT round-trips", bool(claims) and claims["username"] == "admin")
    check("authenticate good", auth.authenticate("admin", "Secret123") is not None)
    check("authenticate bad rejected", auth.authenticate("admin", "nope") is None)
    lead = db.create_user("lead1", auth.hash_password("p"), role="lead", full_name="Lead One")
    usr  = db.create_user("user1", auth.hash_password("p"), role="user")
else:
    lead = db.create_user("lead1", "x", role="lead")
    usr  = db.create_user("user1", "x", role="user")

check("roles stored", db.get_user(lead["id"])["role"] == "lead" and db.get_user(usr["id"])["role"] == "user")

lead_actor = {"id": lead["id"], "username": "lead1", "role": "lead"}
db.create_project("TowerA", lead_actor)
db.create_project("Secret", lead_actor)
db.assign_member("TowerA", usr["id"])

uview = {"id": usr["id"], "username": "user1", "role": "user"}
check("user sees only assigned project", set(db.projects_with_chats(uview).keys()) == {"TowerA"})
check("user can access assigned",        db.user_can_access(uview, "TowerA"))
check("user cannot access unassigned",   not db.user_can_access(uview, "Secret"))

admin_view = {"id": 1, "username": "system", "role": "admin"}
check("admin sees all projects", {"TowerA", "Secret"}.issubset(set(db.projects_with_chats(admin_view).keys())))
check("admin bypasses membership",  db.user_can_access(admin_view, "Secret"))

db.remove_member("TowerA", usr["id"])
check("removing membership revokes access", not db.user_can_access(uview, "TowerA"))

db.engine.dispose(); shutil.rmtree(tmp, ignore_errors=True)
print("\n" + ("ALL PHASE-5 TESTS PASSED" if ok else "SOME TESTS FAILED"))
sys.exit(0 if ok else 1)
