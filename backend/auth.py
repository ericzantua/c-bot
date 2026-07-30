"""Cookie-session auth + a Supabase-backed, editable user store.

Accounts live in the Supabase ``app_users`` table so they can be managed at
runtime from the Settings UI (add / edit / delete, change password, toggle
admin). Passwords are PBKDF2-SHA256 hashed. The session is an HMAC-signed cookie
whose format is shared with the Edge middleware (middleware.js) — the backend
issues it on login; both the backend and the middleware verify it.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time

import config
import db

_PBKDF2_ITER = 100_000
_seeded = False


# ---------- base64url ----------
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---------- password hashing (PBKDF2-SHA256) ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITER)
    return f"pbkdf2_sha256${_PBKDF2_ITER}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt_b64), int(iters))
        return hmac.compare_digest(_b64(dk), hash_b64)
    except Exception:  # noqa: BLE001
        return False


# ---------- session cookie (HMAC-SHA256; format matches middleware.js) ----------
def sign_session(username: str, is_admin: bool) -> str:
    exp = int(time.time() * 1000) + config.SESSION_DAYS * 86400 * 1000
    payload = json.dumps(
        {"u": username, "admin": bool(is_admin), "exp": exp}, separators=(",", ":")
    )
    pb = _b64(payload.encode())
    sig = hmac.new(config.AUTH_SECRET.encode(), pb.encode(), hashlib.sha256).digest()
    return f"{pb}.{_b64(sig)}"


def verify_session(token: str) -> dict | None:
    if not token or "." not in token or not config.AUTH_SECRET:
        return None
    pb, _, sb = token.partition(".")
    expected = _b64(hmac.new(config.AUTH_SECRET.encode(), pb.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sb):
        return None
    try:
        payload = json.loads(_unb64(pb))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < time.time() * 1000:
        return None
    return payload


# ---------- user store (Supabase app_users) ----------
def _ensure_seeded() -> None:
    """Populate app_users from the AUTH_USERS/AUTH_ADMINS env seed if empty."""
    global _seeded
    if _seeded:
        return
    rows = db.client().table("app_users").select("username").limit(1).execute().data or []
    if not rows:
        admins = {a.strip() for a in config.AUTH_ADMINS_SEED.split(",") if a.strip()}
        for pair in config.AUTH_USERS_SEED.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            u, pw = pair.split(":", 1)
            u = u.strip()
            if u:
                create_user(u, pw, is_admin=(u in admins))
    _seeded = True


def list_users() -> list[dict]:
    _ensure_seeded()
    return (
        db.client().table("app_users").select("username,is_admin").order("username").execute().data
        or []
    )


def get_user(username: str) -> dict | None:
    rows = (
        db.client().table("app_users").select("*").eq("username", username).limit(1).execute().data
        or []
    )
    return rows[0] if rows else None


def create_user(username: str, password: str, is_admin: bool = False) -> dict:
    if get_user(username):
        raise ValueError("A user with that name already exists.")
    db.client().table("app_users").insert(
        {
            "username": username,
            "password_hash": hash_password(password),
            "is_admin": bool(is_admin),
        }
    ).execute()
    return {"username": username, "is_admin": bool(is_admin)}


def update_user(
    username: str,
    password: str | None = None,
    is_admin: bool | None = None,
    new_username: str | None = None,
) -> dict:
    user = get_user(username)
    if not user:
        raise ValueError("No such user.")
    patch: dict = {}
    if new_username and new_username != username:
        if get_user(new_username):
            raise ValueError("A user with the new name already exists.")
        patch["username"] = new_username
    if password:
        patch["password_hash"] = hash_password(password)
    if is_admin is not None:
        patch["is_admin"] = bool(is_admin)
    if patch:
        db.client().table("app_users").update(patch).eq("username", username).execute()
    return {
        "username": patch.get("username", username),
        "is_admin": patch.get("is_admin", bool(user.get("is_admin"))),
    }


def delete_user(username: str) -> None:
    db.client().table("app_users").delete().eq("username", username).execute()


def authenticate(cookie_value: str) -> dict | None:
    """Return {username, is_admin} for a valid session cookie, else None.

    Re-reads is_admin from the store so role changes take effect (and deleted
    users are rejected) without depending on the possibly-stale cookie.
    """
    payload = verify_session(cookie_value)
    if not payload:
        return None
    user = get_user(payload.get("u", ""))
    if not user:
        return None
    return {"username": user["username"], "is_admin": bool(user.get("is_admin"))}
