"""
Authentication & access control for Expo Design AI (Phase 5).

Local accounts only: usernames + PBKDF2-SHA256 hashed passwords in the database.
Login returns a signed JWT (HS256) carrying the user id, username and role.
Roles: admin (everything), lead (upload + manage own projects), user (query only).
Access to a project requires membership (admins bypass).

passlib / jose are imported lazily inside functions so this module imports even
before those packages are installed (the app can start and report clearly).
"""
import os
import datetime
import secrets

from fastapi import HTTPException
import db

ALGO = "HS256"
TOKEN_TTL_HOURS = int(os.getenv("EXPO_TOKEN_HOURS", "12"))

_SECRET = None
def secret():
    global _SECRET
    if _SECRET is not None:
        return _SECRET
    s = os.getenv("EXPO_SECRET")
    if not s:
        path = os.path.join(db.DATA_DIR, "secret.key")
        try:
            if os.path.exists(path):
                s = open(path, encoding="utf-8").read().strip()
            else:
                s = secrets.token_hex(32)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(s)
        except Exception:
            s = "dev-insecure-secret-change-me"
    _SECRET = s
    return _SECRET

def _ctx():
    from passlib.context import CryptContext
    # pbkdf2_sha256: pure-Python, offline, no 72-byte bcrypt limit / version issues
    return CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

def hash_password(pw):
    return _ctx().hash(pw)

def verify_password(pw, h):
    if not h:
        return False
    try:
        return _ctx().verify(pw, h)
    except Exception:
        return False

def make_token(user):
    from jose import jwt
    exp = datetime.datetime.utcnow() + datetime.timedelta(hours=TOKEN_TTL_HOURS)
    claims = {"sub": str(user["id"]), "username": user["username"],
              "role": user["role"], "exp": exp}
    return jwt.encode(claims, secret(), algorithm=ALGO)

def decode_token(token):
    try:
        from jose import jwt
        return jwt.decode(token, secret(), algorithms=[ALGO])
    except Exception:
        return None

def authenticate(username, password):
    u = db.get_user_by_username(username)
    if not u or not u.get("is_active"):
        return None
    if not verify_password(password, u.get("password_hash")):
        return None
    return {"id": u["id"], "username": u["username"], "role": u["role"]}

def user_from_request(request):
    """Return the user dict from the request's Bearer token, or None."""
    hdr = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    token = hdr[7:].strip() if hdr.lower().startswith("bearer ") else ""
    if not token:
        # allow token via query param (EventSource / SSE cannot set headers)
        try:
            token = request.query_params.get("token", "")
        except Exception:
            token = ""
    if not token:
        return None
    claims = decode_token(token)
    if not claims:
        return None
    try:
        return {"id": int(claims.get("sub")), "username": claims.get("username"),
                "role": claims.get("role")}
    except Exception:
        return None

# ── guard helpers (used inside endpoints) ──────────────────
def require_user(request):
    u = getattr(request.state, "user", None) if request is not None else None
    if not u:
        raise HTTPException(401, "Login required")
    return u

def require_roles(request, *roles):
    u = require_user(request)
    if u["role"] not in roles:
        raise HTTPException(403, "Not permitted for your role")
    return u

def require_project(request, project):
    u = require_user(request)
    if u["role"] == "admin":
        return u
    if not db.user_can_access(u, project):
        raise HTTPException(403, "You do not have access to this project")
    return u

def can_manage_project(user, project):
    """admin anywhere; lead only on projects they belong to."""
    if not user:
        return False
    if user["role"] == "admin":
        return True
    if user["role"] == "lead":
        return db.user_can_access(user, project)
    return False

# ── first-run admin seed ───────────────────────────────────
def ensure_admin():
    try:
        users = db.list_users()
    except Exception as e:
        db.logger.error("ensure_admin: cannot list users: {}", e)
        return
    real_admins = [u for u in users if u["role"] == "admin" and u["username"] != "system"]
    if real_admins:
        return
    pw = os.getenv("EXPO_ADMIN_PASSWORD", "admin")
    try:
        existing = db.get_user_by_username("admin")
        if existing:
            if not existing.get("password_hash"):
                db.set_user_password(existing["id"], hash_password(pw))
            db.set_user_role(existing["id"], "admin")
        else:
            db.create_user("admin", hash_password(pw), role="admin", full_name="Administrator")
        db.logger.info("Seeded 'admin' account - CHANGE THE PASSWORD after first login")
    except Exception as e:
        db.logger.error("admin seed failed: {}", e)
