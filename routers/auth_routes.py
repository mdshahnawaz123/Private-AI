"""
FastAPI Router for Authentication, Authorization & User Administration.
Extracted from main.py for modularity and enterprise security auditing.
"""
import os
import time
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Request, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from loguru import logger

import db
import auth
from services.rate_limiter import check_rate_limit, reset_rate_limit, rate_limit

auth_router = APIRouter(tags=["auth"])

DATA_DIR = db.DATA_DIR


def _session_response(payload, request):
    response = JSONResponse(payload)
    response.set_cookie("expo_token", str(payload["token"]),
        max_age=auth.TOKEN_TTL_HOURS * 3600, httponly=True, samesite="lax",
        secure=bool(request and request.url.scheme == "https"), path="/")
    return response


# ── Request / Response Schemas ──────────────────────────────
class LoginReq(BaseModel):
    username: str
    password: str


class CreateUserReq(BaseModel):
    username: str
    password: str = ""
    role: str = "user"
    full_name: str = ""
    email: str = ""


class PasswordReq(BaseModel):
    password: str


class RoleReq(BaseModel):
    role: str


class ActiveReq(BaseModel):
    active: bool


class ChangePwReq(BaseModel):
    old_password: str
    new_password: str
    new_username: Optional[str] = None
    username: Optional[str] = None


class UpdateProfileReq(BaseModel):
    old_password: str
    new_username: Optional[str] = None
    new_password: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    username: Optional[str] = None


TRUSTED_PROXIES = set(os.environ.get("EXPO_TRUSTED_PROXIES", "").split(",")) - {""}


def _client_ip(request: Request) -> Optional[str]:
    try:
        if not request or not request.client:
            return None
        peer_ip = request.client.host
        # Only trust X-Forwarded-For if peer is an explicitly trusted proxy
        if peer_ip in TRUSTED_PROXIES and request.headers.get("X-Forwarded-For"):
            forwarded = request.headers.get("X-Forwarded-For").split(",")[0].strip()
            return forwarded
        return peer_ip
    except Exception:
        return None


# ── Endpoints ───────────────────────────────────────────────

@auth_router.post("/auth/login")
async def login(body: LoginReq, request: Request = None):
    # Determine true physical client IP (ignoring forged headers for locality check)
    peer_ip = request.client.host if request and request.client else "unknown"
    client_ip = _client_ip(request) or peer_ip
    is_local = peer_ip in ("127.0.0.1", "::1", "localhost", "testclient")
    max_reqs = 100 if is_local else 10
    window = 60.0 if is_local else 300.0

    # Rate limit by client IP and by account to prevent credential stuffing / header rotation
    if not check_rate_limit(f"login:ip:{client_ip}", max_requests=max_reqs, window_seconds=window):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts from this network. Please try again later.")

    user_key = f"login:user:{(body.username or '').strip().lower()}"
    if not check_rate_limit(user_key, max_requests=15, window_seconds=300.0):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts for this account. Please wait 5 minutes.")
    try:
        u = auth.authenticate(body.username, body.password)
        if not u:
            db.audit("auth.fail", target=body.username, ip=_client_ip(request))
            raise HTTPException(401, "Invalid username or password")
        # Clear rate limit bucket on successful authentication
        reset_rate_limit(f"login:{client_ip}")
        token = auth.make_token(u)
        db.audit("auth.login", target=u["username"], user=u, ip=_client_ip(request))
        projects = None if u["role"] == "admin" else db.user_projects(u["id"])
        must_change = auth.must_change_password(u)
        return _session_response({
            "token": str(token),
            "user": u,
            "projects": projects,
            "must_change_password": bool(must_change)
        }, request)
    except HTTPException:
        raise
    except Exception as _le:
        import traceback as _tb
        try:
            with open(os.path.join(DATA_DIR, "login_error.log"), "w", encoding="utf-8") as _f:
                _f.write(_tb.format_exc())
        except Exception:
            pass
        logger.exception("login failed")
        raise


@auth_router.post("/auth/logout")
async def logout(request: Request = None):
    resp = JSONResponse({"status": "ok", "message": "Logged out successfully"})
    resp.delete_cookie("expo_token", path="/")
    return resp


@auth_router.get("/auth/me")
async def me(request: Request):
    u = auth.require_user(request)
    projects = None if u["role"] == "admin" else db.user_projects(u["id"])
    must_change = auth.must_change_password(u)
    return {"user": u, "projects": projects, "must_change_password": bool(must_change)}


@auth_router.post("/auth/change-password")
async def change_password(body: ChangePwReq, request: Request = None):
    client_ip = _client_ip(request) or "unknown"
    if not check_rate_limit(f"changepw:{client_ip}", max_requests=5, window_seconds=300):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many password change attempts. Please try again later.")
    u = auth.user_from_request(request) if request else None
    target_un = body.username or (u["username"] if u else "admin")
    if not u:
        u = auth.authenticate(target_un, body.old_password)
        if not u:
            target_user = db.get_user_by_username(target_un)
            if not target_user:
                raise HTTPException(400, f"User '{target_un}' not found")
            raise HTTPException(400, "Current password is incorrect")
    else:
        full = db.get_user_by_username(u["username"])
        if not full or not auth.verify_password(body.old_password, full.get("password_hash")):
            raise HTTPException(400, "Current password is incorrect")

    if len(body.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    if body.new_password == body.old_password and not body.new_username:
        raise HTTPException(400, "New password must be different from current password")
    try:
        updated_user = db.update_user_profile(
            uid=u["id"],
            new_username=body.new_username if body.new_username else None,
            new_password_hash=auth.hash_password(body.new_password),
            by=u
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    new_token = auth.make_token(updated_user)
    return _session_response({"status": "ok", "token": new_token, "user": updated_user, "message": "Password updated successfully"}, request)


@auth_router.post("/auth/update-profile")
async def update_profile(body: UpdateProfileReq, request: Request = None):
    client_ip = _client_ip(request) or "unknown"
    if not check_rate_limit(f"updateprof:{client_ip}", max_requests=10, window_seconds=300):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many update profile attempts. Please try again later.")
    u = auth.user_from_request(request) if request else None
    target_un = body.username or (u["username"] if u else "admin")
    if not u:
        u = auth.authenticate(target_un, body.old_password)
        if not u:
            raise HTTPException(401, "Login required or current password incorrect")
    else:
        full = db.get_user_by_username(u["username"])
        if not full or not auth.verify_password(body.old_password, full.get("password_hash")):
            raise HTTPException(400, "Current password is incorrect")
    
    new_pw_hash = None
    if body.new_password:
        if len(body.new_password) < 8:
            raise HTTPException(400, "New password must be at least 8 characters")
        if body.new_password == body.old_password:
            raise HTTPException(400, "New password must be different from current password")
        new_pw_hash = auth.hash_password(body.new_password)
        
    if not body.new_username and not new_pw_hash and body.full_name is None and body.email is None:
        raise HTTPException(400, "No changes specified")

    try:
        updated_user = db.update_user_profile(
            uid=u["id"],
            new_username=body.new_username if body.new_username else None,
            full_name=body.full_name,
            email=body.email,
            new_password_hash=new_pw_hash,
            by=u
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    
    new_token = auth.make_token(updated_user)
    return _session_response({"status": "ok", "token": new_token, "user": updated_user, "message": "Profile updated successfully"}, request)


@auth_router.get("/admin/users")
async def admin_list_users(request: Request):
    auth.require_roles(request, "admin")
    return {"users": db.list_users()}


@auth_router.post("/admin/users")
async def admin_create_user(body: CreateUserReq, request: Request):
    u = auth.require_roles(request, "admin")
    try:
        if body.password and len(body.password) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not body.password and not (body.email or "").strip():
            raise ValueError("Give a temporary password, or a work email for company sign-in")
        created = db.create_user(body.username, auth.hash_password(body.password) if body.password else None,
                                 role=body.role, full_name=body.full_name,
                                 email=body.email, by=u)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"user": created}


@auth_router.post("/admin/users/{uid}/password")
async def admin_reset_password(uid: int, body: PasswordReq, request: Request):
    u = auth.require_roles(request, "admin")
    if not db.set_user_password(uid, auth.hash_password(body.password), by=u):
        raise HTTPException(404, "User not found")
    return {"status": "ok"}


def _guard_admin_change(uid, actor, action):
    """Refuse changes that would lock everyone out or touch the internal account."""
    target = db.get_user(uid)
    if not target:
        raise HTTPException(404, "User not found")
    if target["username"] == "system":
        raise HTTPException(400, "The internal 'system' account cannot be changed.")
    if action in ("delete", "deactivate", "demote") and uid == actor["id"]:
        raise HTTPException(400, "You cannot " + ("delete" if action == "delete" else "lock out") + " your own account. Ask another admin.")
    if (action in ("delete", "deactivate", "demote") and target["role"] == "admin" and target["is_active"]
            and db.count_active_admins(exclude_uid=uid) == 0):
        raise HTTPException(400, "This is the last active admin. Make another user admin first.")
    return target


@auth_router.post("/admin/users/{uid}/role")
async def admin_set_role(uid: int, body: RoleReq, request: Request):
    u = auth.require_roles(request, "admin")
    if body.role != "admin":
        _guard_admin_change(uid, u, "demote")
    try:
        if not db.set_user_role(uid, body.role, by=u):
            raise HTTPException(404, "User not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok"}


@auth_router.post("/admin/users/{uid}/active")
async def admin_set_active(uid: int, body: ActiveReq, request: Request):
    u = auth.require_roles(request, "admin")
    if not body.active:
        _guard_admin_change(uid, u, "deactivate")
    if not db.set_user_active(uid, body.active, by=u):
        raise HTTPException(404, "User not found")
    return {"status": "ok"}


class DeleteUserReq(BaseModel):
    confirm_username: str


@auth_router.delete("/admin/users/{uid}")
async def admin_delete_user(uid: int, body: DeleteUserReq, request: Request):
    """Permanently delete an account and its personal data (see db.delete_user)."""
    u = auth.require_roles(request, "admin")
    target = _guard_admin_change(uid, u, "delete")
    if (body.confirm_username or "").strip() != target["username"]:
        raise HTTPException(400, "Type the exact username to confirm deletion.")
    res = db.delete_user(uid, by=u)
    if not res:
        raise HTTPException(404, "User not found")
    removed = 0
    base = os.path.realpath(os.path.join(DATA_DIR, "private_uploads"))
    for pth in res["private_upload_paths"]:
        try:
            rp = os.path.realpath(pth if os.path.isabs(pth) else os.path.join(DATA_DIR, pth))
            if rp.startswith(base + os.sep) and os.path.isfile(rp):
                os.remove(rp); removed += 1
        except OSError:
            pass
    # The user's private upload folder, if now empty or left over.
    try:
        import shutil
        udir = os.path.realpath(os.path.join(base, str(uid)))
        if udir.startswith(base + os.sep) and os.path.isdir(udir):
            shutil.rmtree(udir, ignore_errors=True)
    except Exception:
        pass
    return {"status": "ok", "deleted": res["username"], "private_files_removed": removed}


# ── Single sign-on (OpenID Connect; off until configured in .env) ───────
from fastapi.responses import RedirectResponse
from services import sso as _sso


@auth_router.get("/auth/providers")
async def auth_providers():
    """Public: which company sign-in buttons the login screen should show (empty when SSO is off)."""
    return {"providers": _sso.public_list(), "password_login": True}


def _sso_fail(msg):
    resp = RedirectResponse("/ui/app.html?sso_error=" + __import__("urllib.parse").parse.quote(msg[:200]), status_code=303)
    resp.delete_cookie(_sso.FLOW_COOKIE, path="/auth/sso")
    return resp


@auth_router.get("/auth/sso/{key}/start")
async def sso_start(key: str, request: Request):
    peer = request.client.host if request.client else "unknown"
    if not check_rate_limit(f"sso:ip:{peer}", max_requests=30, window_seconds=300.0):
        raise HTTPException(429, "Too many sign-in attempts. Please wait a few minutes.")
    try:
        url, cookie = await _sso.start(request, key, auth.secret())
    except KeyError:
        raise HTTPException(404, "This sign-in option is not configured.")
    except Exception as e:
        logger.warning("SSO start failed for {}: {}", key, e)
        return _sso_fail("Could not reach the company sign-in service.")
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(_sso.FLOW_COOKIE, cookie, max_age=_sso.FLOW_TTL, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https", path="/auth/sso")
    return resp


@auth_router.get("/auth/sso/{key}/callback")
async def sso_callback(key: str, request: Request, code: str = "", state: str = "", error: str = "",
                       error_description: str = ""):
    if error:
        return _sso_fail(error_description or error)
    try:
        ident = await _sso.finish(request, key, code, state, request.cookies.get(_sso.FLOW_COOKIE), auth.secret())
    except ValueError as e:
        db.audit("auth.sso_fail", target=key, detail={"reason": str(e)[:200]}, ip=_client_ip(request))
        return _sso_fail(str(e))
    except Exception as e:
        logger.exception("SSO callback failed")
        return _sso_fail("Company sign-in failed. Please try again or use your password.")
    user, matched_by = db.find_sso_user(ident["provider"], ident["external_id"], ident["email"])
    if user and matched_by == "email" and not _sso.allowed_domains():
        # Linking an existing account by email is only safe when the email domain is one the company controls.
        return _sso_fail("Set EXPO_SSO_ALLOWED_DOMAINS to your company domain before existing accounts can use company sign-in.")
    if user and matched_by == "email":
        if user.get("auth_provider") not in (None, "local", ident["provider"]):
            return _sso_fail("This email is already linked to a different sign-in method.")
        db.link_sso_identity(user["id"], ident["provider"], ident["external_id"], ident["name"], ident["email"])
        user = db.get_user(user["id"])
    if not user:
        if not _sso.auto_create():
            db.audit("auth.sso_noaccount", target=ident["email"] or ident["external_id"], ip=_client_ip(request))
            return _sso_fail("You signed in, but there is no Expo account for " + (ident["email"] or "this user")
                             + ". Ask an admin to add you (with this email).")
        base = "".join(ch for ch in (ident["username_hint"] or "user") if ch.isalnum() or ch in "._-")[:40] or "user"
        name, n = base, 1
        while db.get_user_by_username(name):
            n += 1; name = f"{base}{n}"
        user = db.create_user(name, None, role="user", full_name=ident["name"], email=ident["email"],
                              auth_provider=ident["provider"], external_id=ident["external_id"])
    if not user.get("is_active"):
        return _sso_fail("Your account is deactivated. Contact an admin.")
    token = auth.make_token(user)
    db.audit("auth.login", target=user["username"], detail={"via": ident["provider"]}, user=user, ip=_client_ip(request))
    resp = RedirectResponse("/ui/app.html", status_code=303)
    resp.set_cookie("expo_token", str(token), max_age=auth.TOKEN_TTL_HOURS * 3600, httponly=True, samesite="lax",
                    secure=request.url.scheme == "https", path="/")
    resp.delete_cookie(_sso.FLOW_COOKIE, path="/auth/sso")
    return resp


@auth_router.get("/admin/users/{uid}/permissions")
async def user_permissions(uid: int, request: Request):
    auth.require_roles(request, "admin")
    u = db.get_user(uid)
    if not u:
        raise HTTPException(404, "user not found")
    role = u["role"]
    if role == "admin":
        return {"user": u, "role": role, "full_access": True, "projects": []}
    out = []
    for pj in db.user_projects(uid):
        allow_all, ids = db.folder_access(u, pj)
        folders = db.list_folders(pj)
        vis = folders if allow_all else [f for f in folders if f["id"] in (ids or set())]
        out.append({"project": pj, "all_access": bool(allow_all),
                    "total_folders": len(folders),
                    "folders": [{"id": f["id"], "name": f["name"]} for f in vis]})
    return {"user": u, "role": role, "full_access": False, "projects": out}


@auth_router.get("/admin/users/{uid}/projects/{project}/folders")
async def user_project_folders(uid: int, project: str, request: Request):
    auth.require_roles(request, "admin")
    u = db.get_user(uid)
    if not u:
        raise HTTPException(404, "user not found")
    allow_all, ids = db.folder_access(u, project)
    is_member = db.user_can_access(u, project)
    folders = db.list_folders(project)
    aset = ids or set()
    return {"project": project, "is_member": bool(is_member), "all_access": bool(allow_all),
            "folders": [{"id": f["id"], "name": f["name"],
                         "assigned": bool(allow_all or f["id"] in aset),
                         "doc_count": f.get("doc_count", 0)} for f in folders]}


@auth_router.post("/admin/permission-test")
async def permission_test(request: Request):
    """Prove folder isolation: run the SAME retrieval the chat uses, as the target
    user, and confirm no document from an unauthorized folder is returned."""
    admin_user = auth.require_roles(request, "admin")
    body = await request.json()
    username = (body or {}).get("username")
    project = (body or {}).get("project")
    folder_id = (body or {}).get("folder_id")
    query = ((body or {}).get("query") or "").strip()
    if not username or not project:
        raise HTTPException(400, "username and project required")
    tgt = db.get_user_by_username(username)
    if not tgt:
        raise HTTPException(404, "user not found")
    target = {k: v for k, v in tgt.items() if k != "password_hash"}

    allow_all, ids = db.folder_access(target, project)
    allowed_ids = None if allow_all else set(ids or set())
    folders = db.list_folders(project)
    fmap = {f["id"]: f["name"] for f in folders}
    access = [{"id": f["id"], "name": f["name"],
               "allowed": bool(allow_all or f["id"] in (allowed_ids or set()))}
              for f in folders]

    result = {"status": "ok",
              "user": {"username": target["username"], "role": target["role"]},
              "project": project, "all_access": bool(allow_all), "folders": access}

    if folder_id is not None:
        result["folder_check"] = {
            "folder_id": folder_id, "folder": fmap.get(folder_id),
            "allowed": bool(allow_all or folder_id in (allowed_ids or set()))}

    if query:
        # Import lazily to avoid circular imports
        import sys as _sys
        retrieve_context = (_sys.modules.get("main") or _sys.modules["__main__"]).retrieve_context
        docfolder = db.doc_folder_map(project)
        srcs, ctx = retrieve_context(project, query, 12, target)
        returned, leaked = [], []
        for sc in srcs:
            fn = sc.get("source")
            if fn in docfolder:
                fid = docfolder.get(fn)
                ok = allow_all or (fid in (allowed_ids or set()))
                returned.append({"source": fn, "page": sc.get("page"),
                                 "folder": fmap.get(fid), "allowed": ok})
                if not ok:
                    leaked.append(fn)
            else:
                returned.append({"source": fn, "page": sc.get("page"),
                                 "folder": "(code reference)", "allowed": True})

        admin_srcs, _ = retrieve_context(project, query, 12, None)
        admin_files = sorted({s.get("source") for s in admin_srcs if s.get("source") in docfolder})
        user_files = sorted({r["source"] for r in returned if r["folder"] != "(code reference)"})
        withheld = [f for f in admin_files if f not in user_files]
        result["probe"] = {
            "query": query,
            "returned": returned,
            "leaked": leaked,
            "context_empty": not bool(ctx.strip()),
            "admin_would_see": admin_files,
            "withheld_from_user": withheld,
            "pass": len(leaked) == 0,
        }
    db.audit("permission.test", project=project, target=username,
             detail={"query": bool(query), "folder_id": folder_id}, user=admin_user)
    return result
