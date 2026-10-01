"""Security regression test suite. Run: python test_security.py

Covers the fixes from the 2026-10-02 security audit:
  1. Password hashing/verification (auth.py)
  2. JWT token issuance/validation, including tampered/invalid tokens
  3. auth.secret() no longer falls back to a hardcoded string
  4. Folder-level access control on direct file fetch (db.py / main.py's
     /projects/{project}/file + /document) -- the IDOR fix
  5. Path traversal guard (the same abspath+prefix pattern used in main.py)
  6. Upload size cap (services/ingestion.py's save_upload_capped)
  7. The eval() -> safe_eval_expression() replacement in
     intelligence/compliance.py rejects sandbox-escape payloads

Uses a throwaway temp data dir; never touches real data/. Does NOT import
main.py -- main.py has real side effects at import time (it hardcodes
DATA_DIR = "data" and calls db.init_db()/auth.ensure_admin() at module
level), so importing it from a test would touch the live app's data
directory. Everything here is tested at the db.py / auth.py / services /
intelligence layer instead, which is also what main.py itself calls.
"""
import os
import sys
import time
import shutil
import tempfile

tmp = tempfile.mkdtemp(prefix="expo_sec_")
os.environ["EXPO_DATA_DIR"] = tmp
os.environ["EXPO_DATABASE_URL"] = "sqlite:///" + os.path.join(tmp, "expo.db")
os.environ["EXPO_ADMIN_PASSWORD"] = "Secret123"

import db
import auth

ok = True
def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok = ok and bool(cond)

db.init_db()

# ============================================================
# 1-3. Password hashing, JWT, and secret() fallback
# ============================================================
h = auth.hash_password("correct horse battery staple")
check("password hash verifies correct password", auth.verify_password("correct horse battery staple", h))
check("password hash rejects wrong password", not auth.verify_password("wrong password", h))
check("password hash rejects empty hash", not auth.verify_password("anything", ""))
check("same password hashes differently each time (salted)",
      auth.hash_password("same") != auth.hash_password("same"))

tok = auth.make_token({"id": 1, "username": "admin", "role": "admin"})
claims = auth.decode_token(tok)
check("JWT round-trips", bool(claims) and claims.get("username") == "admin" and claims.get("role") == "admin")
check("tampered JWT is rejected", auth.decode_token(tok[:-4] + "xxxx") is None)
check("garbage token is rejected", auth.decode_token("not.a.jwt") is None)
check("empty token is rejected", auth.decode_token("") is None)

# secret() must never fall back to the old hardcoded string, even if the
# key file can't be read/written.
import secrets as _secrets_mod
auth._SECRET = None
real_open = open
def _boom(*a, **k):
    raise OSError("simulated: can't read or write secret.key")
try:
    import builtins
    builtins.open = _boom
    s = auth.secret()
finally:
    builtins.open = real_open
check("secret() fallback is random, not the old hardcoded string",
      s != "dev-insecure-secret-change-me" and len(s) >= 32)
auth._SECRET = None  # reset so later tests use the real on-disk secret

# ============================================================
# 4. Folder-level access control on direct file fetch (the IDOR fix)
# ============================================================
admin_actor = {"id": 1, "username": "system", "role": "admin"}
db.create_project("FolderTest", admin_actor)
fa = db.create_folder("FolderTest", "Folder-A", by=admin_actor)
fb = db.create_folder("FolderTest", "Folder-B", by=admin_actor)

restricted = db.create_user("restricted1", auth.hash_password("p"), role="user")
db.assign_member("FolderTest", restricted["id"])
db.assign_folder_member(fa["id"], restricted["id"])

path_a = os.path.join(tmp, "docs", "FolderTest", "Folder-A", "a.pdf")
path_b = os.path.join(tmp, "docs", "FolderTest", "Folder-B", "b.pdf")
os.makedirs(os.path.dirname(path_a), exist_ok=True)
os.makedirs(os.path.dirname(path_b), exist_ok=True)
open(path_a, "w").write("a")
open(path_b, "w").write("b")

db.record_document("FolderTest", "a.pdf", path_a, 0, folder_id=fa["id"], user=admin_actor)
db.record_document("FolderTest", "b.pdf", path_b, 0, folder_id=fb["id"], user=admin_actor)

ruser = {"id": restricted["id"], "username": "restricted1", "role": "user"}
allow_all, allowed_ids = db.folder_access(ruser, "FolderTest")
check("restricted user is NOT allow_all", allow_all is False)
check("restricted user's allowed folder set is exactly Folder-A",
      allowed_ids == {fa["id"]})

folder_id_a = db.document_folder_id_for_path("FolderTest", os.path.abspath(path_a))
folder_id_b = db.document_folder_id_for_path("FolderTest", os.path.abspath(path_b))
check("document_folder_id_for_path resolves Folder-A doc correctly", folder_id_a == fa["id"])
check("document_folder_id_for_path resolves Folder-B doc correctly", folder_id_b == fb["id"])

# Replicate the exact check main.py's /projects/{project}/file now applies.
def would_be_permitted(user, project, abs_path):
    allow_all, ids = db.folder_access(user, project)
    if allow_all:
        return True
    fid = db.document_folder_id_for_path(project, abs_path)
    return fid is not None and fid in (ids or set())

check("restricted user CAN fetch a file in their assigned folder",
      would_be_permitted(ruser, "FolderTest", os.path.abspath(path_a)))
check("restricted user is BLOCKED from a file in an unassigned folder (the IDOR this fix closes)",
      not would_be_permitted(ruser, "FolderTest", os.path.abspath(path_b)))
check("admin is unaffected (full access regardless of folder)",
      would_be_permitted(admin_actor, "FolderTest", os.path.abspath(path_b)))

# ============================================================
# 5. Path traversal guard (same abspath+prefix pattern as main.py)
# ============================================================
def path_is_safe(docs_dir, project, rel):
    base = os.path.abspath(os.path.join(docs_dir, project))
    target = os.path.abspath(os.path.join(base, rel))
    return target == base or target.startswith(base + os.sep)

docs_dir = os.path.join(tmp, "docs")
check("normal relative path is accepted", path_is_safe(docs_dir, "FolderTest", "Folder-A/a.pdf"))
check("'../../' traversal outside the project is rejected",
      not path_is_safe(docs_dir, "FolderTest", "../../../etc/passwd"))
check("absolute path escape is rejected",
      not path_is_safe(docs_dir, "FolderTest", "/etc/passwd" if os.sep == "/" else "C:\\Windows\\win.ini"))
check("sibling-project traversal ('../OtherProject/x') is rejected",
      not path_is_safe(docs_dir, "FolderTest", "../OtherProject/secret.pdf"))

# ============================================================
# 6. Upload size cap (services/ingestion.py)
# ============================================================
from services.ingestion import save_upload_capped, UploadTooLargeError

class _FakeFile:
    """Mimics UploadFile.file: has a .read(n) method, yields chunks until empty."""
    def __init__(self, total_bytes, chunk=256 * 1024):
        self._remaining = total_bytes
        self._chunk = chunk
    def read(self, n):
        if self._remaining <= 0:
            return b""
        take = min(n, self._chunk, self._remaining)
        self._remaining -= take
        return b"x" * take

small_path = os.path.join(tmp, "small.bin")
written = save_upload_capped(_FakeFile(1024 * 1024), small_path, max_bytes=5 * 1024 * 1024)
check("a within-limit upload writes the full byte count", written == 1024 * 1024)
check("the written file exists and matches the size", os.path.getsize(small_path) == 1024 * 1024)

big_path = os.path.join(tmp, "big.bin")
raised = False
try:
    save_upload_capped(_FakeFile(10 * 1024 * 1024), big_path, max_bytes=1 * 1024 * 1024)
except UploadTooLargeError:
    raised = True
check("an over-limit upload raises UploadTooLargeError", raised)
check("the partial file is cleaned up after an over-limit upload", not os.path.exists(big_path))

# ============================================================
# 7. Safe expression evaluator (intelligence/compliance.py)
# ============================================================
from intelligence.compliance import safe_eval_expression, UnsafeExpressionError

check("safe eval: simple numeric comparison",
      safe_eval_expression("value >= 1200", {"value": 1500, "context": {}}) is True)
check("safe eval: boolean logic",
      safe_eval_expression("value > 0 and value < 100", {"value": 50, "context": {}}) is True)
check("safe eval: string equality",
      safe_eval_expression("value == 'RWP'", {"value": "RWP", "context": {}}) is True)
check("safe eval: dict indexing on context",
      safe_eval_expression("context['min'] <= value", {"value": 10, "context": {"min": 5}}) is True)
check("safe eval: whitelisted function call",
      safe_eval_expression("abs(value) == 5", {"value": -5, "context": {}}) is True)

def rejects(expr):
    try:
        safe_eval_expression(expr, {"value": 1, "context": {}})
        return False
    except UnsafeExpressionError:
        return True
    except Exception:
        return True  # any other failure (e.g. SyntaxError wrapped) still counts as "did not execute"

check("safe eval rejects __import__", rejects("__import__('os').system('echo pwned')"))
check("safe eval rejects attribute-chain sandbox escape",
      rejects("value.__class__.__base__.__subclasses__()"))
check("safe eval rejects unknown names", rejects("os.system('echo pwned')"))
check("safe eval rejects arbitrary function calls", rejects("open('/etc/passwd').read()"))

# ============================================================
db.engine.dispose()
shutil.rmtree(tmp, ignore_errors=True)
print("\n" + ("ALL SECURITY TESTS PASSED" if ok else "SOME SECURITY TESTS FAILED"))
sys.exit(0 if ok else 1)
