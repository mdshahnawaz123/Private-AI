"""Single sign-on (OpenID Connect) for Expo Design AI.

Off by default. Nothing here runs until a provider is configured in .env, so the
app stays fully offline and keeps its normal username/password login.

Any OpenID Connect provider works (Microsoft Entra ID / Office 365, Google
Workspace, Okta, Keycloak, Auth0 ...). Microsoft has a shortcut because it is
the most common company sign-in:

    EXPO_SSO_MICROSOFT_TENANT=<your directory (tenant) id>
    EXPO_SSO_MICROSOFT_CLIENT_ID=<application (client) id>
    EXPO_SSO_MICROSOFT_CLIENT_SECRET=<client secret value>

Any other provider (the NAME part becomes the button key, lowercase):

    EXPO_SSO_<NAME>_ISSUER=https://login.example.com/realms/acme
    EXPO_SSO_<NAME>_CLIENT_ID=...
    EXPO_SSO_<NAME>_CLIENT_SECRET=...
    EXPO_SSO_<NAME>_LABEL=Company login        (optional button text)

Shared options:

    EXPO_PUBLIC_URL=https://expo.company.local    (address users open; used for the
                                                   redirect URI, default http://127.0.0.1:<port>)
    EXPO_SSO_ALLOWED_DOMAINS=company.com,company.ae   (only these email domains may sign in)
    EXPO_SSO_AUTO_CREATE=0     (1 = create an account on first sign-in with role "user";
                                0 = an admin must create the account first, matched by email)

Register this redirect URI with the provider:
    <EXPO_PUBLIC_URL>/auth/sso/<name>/callback      e.g. .../auth/sso/microsoft/callback

Security: authorization-code flow with PKCE; state and nonce are kept in a signed,
short-lived, httponly cookie; the ID token signature is checked against the
provider's published keys (JWKS) together with issuer, audience, expiry and nonce.
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse

import httpx

_DISCOVERY_CACHE = {}   # issuer -> (fetched_at, config, jwks)
_CACHE_SECONDS = 3600
FLOW_COOKIE = "expo_sso_flow"
FLOW_TTL = 600          # seconds a user has to finish signing in at the provider


def _env(name, default=""):
    return (os.getenv(name) or default).strip()


def providers():
    """Configured providers as {key: {...}}. Empty dict when SSO is not set up."""
    out = {}
    tenant = _env("EXPO_SSO_MICROSOFT_TENANT")
    if tenant and _env("EXPO_SSO_MICROSOFT_CLIENT_ID"):
        out["microsoft"] = {
            "key": "microsoft",
            "label": _env("EXPO_SSO_MICROSOFT_LABEL", "Sign in with Microsoft"),
            "issuer": f"https://login.microsoftonline.com/{tenant}/v2.0",
            "client_id": _env("EXPO_SSO_MICROSOFT_CLIENT_ID"),
            "client_secret": _env("EXPO_SSO_MICROSOFT_CLIENT_SECRET"),
            "scope": "openid profile email",
            "id_claim": "oid",   # Entra's stable per-tenant user id
        }
    for k, v in os.environ.items():
        if not (k.startswith("EXPO_SSO_") and k.endswith("_ISSUER")):
            continue
        name = k[len("EXPO_SSO_"):-len("_ISSUER")]
        key = name.lower()
        if not key or key == "microsoft" or not v.strip():
            continue
        cid = _env(f"EXPO_SSO_{name}_CLIENT_ID")
        if not cid:
            continue
        out[key] = {
            "key": key,
            "label": _env(f"EXPO_SSO_{name}_LABEL", f"Sign in with {name.replace('_', ' ').title()}"),
            "issuer": v.strip().rstrip("/"),
            "client_id": cid,
            "client_secret": _env(f"EXPO_SSO_{name}_CLIENT_SECRET"),
            "scope": _env(f"EXPO_SSO_{name}_SCOPE", "openid profile email"),
            "id_claim": "sub",
        }
    return out


def public_list():
    """What the login screen may see: keys and button labels only, never secrets."""
    return [{"key": p["key"], "label": p["label"]} for p in providers().values()]


def allowed_domains():
    return [d.strip().lower().lstrip("@") for d in _env("EXPO_SSO_ALLOWED_DOMAINS").split(",") if d.strip()]


def auto_create():
    return _env("EXPO_SSO_AUTO_CREATE", "0") == "1"


def redirect_uri(request, key):
    base = _env("EXPO_PUBLIC_URL") or str(request.base_url).rstrip("/")
    return f"{base.rstrip('/')}/auth/sso/{key}/callback"


async def _discover(issuer):
    hit = _DISCOVERY_CACHE.get(issuer)
    if hit and time.time() - hit[0] < _CACHE_SECONDS:
        return hit[1], hit[2]
    async with httpx.AsyncClient(timeout=15) as c:
        r1 = await c.get(issuer.rstrip("/") + "/.well-known/openid-configuration"); r1.raise_for_status()
        conf = r1.json()
        r2 = await c.get(conf["jwks_uri"]); r2.raise_for_status()
        jwks = r2.json()
    _DISCOVERY_CACHE[issuer] = (time.time(), conf, jwks)
    return conf, jwks


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _sign(payload, secret):
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = _b64(hashlib.sha256((secret + "." + body).encode()).digest())
    return body + "." + mac


def _unsign(value, secret):
    try:
        body, mac = value.split(".", 1)
        if not secrets.compare_digest(mac, _b64(hashlib.sha256((secret + "." + body).encode()).digest())):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if time.time() - data.get("t", 0) > FLOW_TTL:
            return None
        return data
    except Exception:
        return None


async def start(request, key, app_secret):
    """Return (authorize_url, flow_cookie_value)."""
    p = providers().get(key)
    if not p:
        raise KeyError(key)
    conf, _ = await _discover(p["issuer"])
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    params = {
        "client_id": p["client_id"], "response_type": "code", "scope": p["scope"],
        "redirect_uri": redirect_uri(request, key), "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account",
    }
    url = conf["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)
    cookie = _sign({"k": key, "s": state, "n": nonce, "v": verifier, "t": int(time.time())}, app_secret)
    return url, cookie


async def finish(request, key, code, state, flow_cookie, app_secret):
    """Exchange the code and verify the ID token. Returns the identity:
    {"provider", "external_id", "email", "name", "username_hint"}. Raises ValueError on any failure."""
    from jose import jwt

    p = providers().get(key)
    if not p:
        raise ValueError("Unknown sign-in provider")
    flow = _unsign(flow_cookie or "", app_secret)
    if not flow or flow.get("k") != key or not secrets.compare_digest(str(flow.get("s")), str(state or "")):
        raise ValueError("Sign-in session expired or did not match. Please try again.")
    conf, jwks = await _discover(p["issuer"])
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(request, key),
            "client_id": p["client_id"], "code_verifier": flow["v"]}
    if p["client_secret"]:
        data["client_secret"] = p["client_secret"]
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(conf["token_endpoint"], data=data, headers={"Accept": "application/json"})
    if r.status_code != 200:
        raise ValueError("The sign-in provider refused the login code.")
    id_token = r.json().get("id_token")
    if not id_token:
        raise ValueError("The sign-in provider did not return an identity token.")
    header = jwt.get_unverified_header(id_token)
    keys = [k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")] or jwks.get("keys", [])
    claims = None
    for k in keys:
        try:
            claims = jwt.decode(id_token, k, algorithms=[header.get("alg", "RS256")], audience=p["client_id"],
                                issuer=conf.get("issuer", p["issuer"]), options={"verify_at_hash": False})
            break
        except Exception:
            continue
    if not claims:
        raise ValueError("The identity token could not be verified.")
    if claims.get("nonce") != flow.get("n"):
        raise ValueError("The identity token did not match this sign-in.")
    ext = str(claims.get(p["id_claim"]) or claims.get("sub") or "")
    email = (claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").strip()
    if not ext:
        raise ValueError("The identity token has no user id.")
    doms = allowed_domains()
    if doms and email.split("@")[-1].lower() not in doms:
        raise ValueError("This account's email domain is not allowed to sign in.")
    return {"provider": key, "external_id": ext, "email": email,
            "name": claims.get("name") or "", "username_hint": (email.split("@")[0] if email else "")}
