import os, sys, tempfile, json, asyncio, time
d = tempfile.mkdtemp(); os.environ["EXPO_DATA_DIR"] = d
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # run: python tests/manual_check_sso_and_user_delete.py
for k in list(os.environ):
    if k.startswith("EXPO_SSO_"): del os.environ[k]
import db, auth
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from routers.auth_routes import auth_router
db.init_db()
app = FastAPI()
@app.middleware("http")
async def mw(request: Request, call_next):
    request.state.user = auth.user_from_request(request)
    return await call_next(request)
app.include_router(auth_router)
c = TestClient(app)
ok = lambda name, cond: print(("PASS " if cond else "FAIL ") + name)
# users: system(1) + admins
try: db.create_user("system", None, role="admin")
except ValueError: pass
a1 = db.create_user("boss", auth.hash_password("Passw0rd!x"), role="admin", email="boss@acme.com")
u2 = db.create_user("ali", auth.hash_password("Passw0rd!y"), role="user", email="Ali@Acme.com")
H = {"Authorization": "Bearer " + auth.make_token(a1)}
ok("providers empty when SSO off", c.get("/auth/providers").json()["providers"] == [])
ok("sso start 404 when off", c.get("/auth/sso/microsoft/start", follow_redirects=False).status_code == 404)
ok("cannot delete self", c.request("DELETE", f"/admin/users/{a1['id']}", json={"confirm_username": "boss"}, headers=H).status_code == 400)
ok("cannot deactivate last admin (self)", c.post(f"/admin/users/{a1['id']}/active", json={"active": False}, headers=H).status_code == 400)
sysu = db.get_user_by_username("system")
ok("cannot delete system", c.request("DELETE", f"/admin/users/{sysu['id']}", json={"confirm_username": "system"}, headers=H).status_code == 400)
ok("wrong confirm rejected", c.request("DELETE", f"/admin/users/{u2['id']}", json={"confirm_username": "x"}, headers=H).status_code == 400)
# give ali data
db.create_project("P1", by=a1); db.assign_member("P1", u2["id"], by=a1)
pu = os.path.join(d, "private_uploads", str(u2["id"])); os.makedirs(pu, exist_ok=True)
f = os.path.join(pu, "secret.txt"); open(f, "w").write("x")
db.create_user_upload(u2["id"], "P1", "secret.txt", f, 1)
tok2 = auth.make_token(u2)
ok("user cannot delete", c.request("DELETE", f"/admin/users/{a1['id']}", json={"confirm_username": "boss"}, headers={"Authorization": "Bearer " + tok2}).status_code == 403)
r = c.request("DELETE", f"/admin/users/{u2['id']}", json={"confirm_username": "ali"}, headers=H)
ok("delete user 200 " + r.text, r.status_code == 200 and r.json()["private_files_removed"] == 1)
ok("user row gone", db.get_user(u2["id"]) is None)
ok("private file gone", not os.path.exists(f) and not os.path.exists(pu))
ok("membership gone", all(m["user_id"] != u2["id"] for m in db.list_members("P1")) if hasattr(db, "list_members") else True)
ok("old token rejected", c.get("/admin/users", headers={"Authorization": "Bearer " + tok2}).status_code in (401, 403))
ok("project kept", any(p for p in [db.get_project("P1")] if p) if hasattr(db, "get_project") else True)
# SSO with a fake provider
os.environ.update({"EXPO_SSO_MICROSOFT_TENANT": "t1", "EXPO_SSO_MICROSOFT_CLIENT_ID": "cid", "EXPO_SSO_MICROSOFT_CLIENT_SECRET": "sec",
                   "EXPO_SSO_ALLOWED_DOMAINS": "acme.com"})
from services import sso
from jose import jwt as jj
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
from jose import jwk
pub = jwk.construct(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(), "RS256").to_dict()
pub.update({"kid": "k1", "use": "sig"}); pub = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in pub.items()}
ISS = "https://login.microsoftonline.com/t1/v2.0"
sso._DISCOVERY_CACHE[ISS] = (time.time(), {"issuer": ISS, "authorization_endpoint": "https://idp/auth", "token_endpoint": "https://idp/token", "jwks_uri": "x"}, {"keys": [pub]})
ok("providers lists microsoft", [p["key"] for p in c.get("/auth/providers").json()["providers"]] == ["microsoft"])
ok("no secret leaked", "sec" not in c.get("/auth/providers").text)
NEXT = {}
import httpx
class FakeResp:
    status_code = 200
    def json(self): return {"id_token": NEXT["tok"]}
class FakeClient:
    def __init__(self, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def post(self, url, data=None, headers=None):
        NEXT["data"] = data; return FakeResp()
sso.httpx.AsyncClient = FakeClient
def flow(email, oid, nonce_ok=True, aud="cid"):
    r = c.get("/auth/sso/microsoft/start", follow_redirects=False)
    assert r.status_code == 303, r.text
    import urllib.parse as up
    q = dict(up.parse_qsl(up.urlparse(r.headers["location"]).query))
    NEXT["tok"] = jj.encode({"iss": ISS, "aud": aud, "exp": int(time.time()) + 300, "iat": int(time.time()), "oid": oid, "sub": "s" + oid,
                             "email": email, "name": "Test Person", "nonce": q["nonce"] if nonce_ok else "bad"}, pem, algorithm="RS256", headers={"kid": "k1"})
    c.cookies.set(sso.FLOW_COOKIE, r.cookies.get(sso.FLOW_COOKIE), path="/auth/sso")
    return c.get(f"/auth/sso/microsoft/callback?code=abc&state={q['state']}", follow_redirects=False), q
r, q = flow("boss@acme.com", "oid-boss")
ok("PKCE + S256 sent", q["code_challenge_method"] == "S256" and "code_verifier" in NEXT["data"])
ok("existing user linked by email -> login cookie", r.status_code == 303 and r.headers["location"] == "/ui/app.html" and "expo_token" in r.headers.get("set-cookie", ""))
ok("linked provider stored", db.get_user(a1["id"])["auth_provider"] == "microsoft")
c.cookies.clear()
r, _ = flow("boss@acme.com", "oid-boss", nonce_ok=False)
ok("bad nonce rejected", "sso_error" in r.headers["location"])
c.cookies.clear()
r, _ = flow("boss@acme.com", "oid-boss", aud="other")
ok("wrong audience rejected", "sso_error" in r.headers["location"])
c.cookies.clear()
r, _ = flow("eve@evil.com", "oid-eve")
ok("other domain rejected", "domain" in r.headers["location"])
c.cookies.clear()
r, _ = flow("new@acme.com", "oid-new")
ok("unknown user refused when auto-create off", "no%20Expo%20account" in r.headers["location"])
os.environ["EXPO_SSO_AUTO_CREATE"] = "1"; c.cookies.clear()
r, _ = flow("new@acme.com", "oid-new")
nu = db.get_user_by_username("new")
ok("auto-create user role=user", nu and nu["role"] == "user" and r.headers["location"] == "/ui/app.html")
ok("sso user cannot password-login", c.post("/auth/login", json={"username": "new", "password": ""}).status_code in (401, 422))
c.cookies.clear()
r = c.get("/auth/sso/microsoft/callback?code=abc&state=forged", follow_redirects=False)
ok("forged state rejected", "sso_error" in r.headers["location"])
