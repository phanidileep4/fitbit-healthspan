"""Authenticated, encrypted browser sessions. Legacy unsigned cookies are rejected."""
import base64
import hashlib
import json
import os
import secrets
import zlib
from http.cookies import SimpleCookie
from cryptography.fernet import Fernet, InvalidToken

COOKIE_NAME = "gh_session_v2"
_LOCAL_KEY = Fernet.generate_key()
TTL = 30 * 24 * 3600


def _cipher():
    key = os.environ.get("SESSION_ENCRYPTION_KEY")
    if key:
        return Fernet(key.encode("ascii"))
    secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if secret:
        # Domain-separated from the OAuth use of this server-only secret.
        key = base64.urlsafe_b64encode(hashlib.sha256(b"healthspan-session-v2\0" + secret.encode()).digest())
        return Fernet(key)
    if os.environ.get("VERCEL"):
        raise RuntimeError("Set SESSION_ENCRYPTION_KEY or GOOGLE_CLIENT_SECRET before connecting.")
    return Fernet(_LOCAL_KEY)


def decode_session(header):
    try:
        cookie = SimpleCookie()
        cookie.load(header or "")
        if COOKIE_NAME not in cookie:
            return {}
        encrypted = cookie[COOKIE_NAME].value.encode("ascii")
        if len(encrypted) > 3800:
            return {}
        plain = zlib.decompress(_cipher().decrypt(encrypted, ttl=TTL))
        state = json.loads(plain)
        return state if isinstance(state, dict) else {}
    except (ValueError, KeyError, InvalidToken, zlib.error, UnicodeError):
        return {}


def encode_session_cookie(state, is_https):
    # Never store health records in the session.
    payload = zlib.compress(json.dumps(state, separators=(",", ":"), allow_nan=False).encode())
    value = _cipher().encrypt(payload).decode("ascii")
    if len(value) > 3800:
        raise ValueError("Session exceeds the browser cookie limit. Use server-configured OAuth credentials.")
    parts = [f"{COOKIE_NAME}={value}", "Path=/", "HttpOnly", "SameSite=Lax", f"Max-Age={TTL}"]
    if is_https:
        parts.append("Secure")
    return "; ".join(parts)
