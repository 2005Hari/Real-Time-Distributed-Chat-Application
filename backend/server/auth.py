"""Account security helpers: password hashing, signed session tokens, input validation, rate limiting."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections import defaultdict, deque
from typing import Optional

# ---------- passwords ----------
# scrypt is in the standard library (no native build step on the host) and is memory-hard.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _KEY_LEN = 2 ** 14, 8, 1, 32


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_KEY_LEN)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    if not isinstance(stored, str):
        return False
    try:
        scheme, n, r, p, salt, expected = stored.split('$')
        if scheme != 'scrypt':
            return False
        key = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=_KEY_LEN)
        return hmac.compare_digest(key, _unb64(expected))
    except (ValueError, TypeError):
        return False


# Verified against when a username does not exist, so "no such user" costs the same as "wrong password".
DUMMY_HASH = hash_password(secrets.token_hex(16))


# ---------- session tokens ----------
class TokenSigner:
    """Stateless signed tokens: base64(payload).base64(HMAC-SHA256). Payload is {uid, exp}."""

    def __init__(self, secret: str):
        self._key = secret.encode()

    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self._key, body.encode(), hashlib.sha256).digest())

    def issue(self, user_id: str, ttl_seconds: int) -> str:
        body = _b64(json.dumps({'uid': user_id, 'exp': int(time.time()) + ttl_seconds}).encode())
        return f"{body}.{self._sign(body)}"

    def verify(self, token: Optional[str]) -> Optional[str]:
        """Return the user id if the token is authentic and unexpired, else None."""
        if not token or not isinstance(token, str) or token.count('.') != 1:
            return None
        body, signature = token.split('.')
        if not hmac.compare_digest(signature, self._sign(body)):
            return None
        try:
            payload = json.loads(_unb64(body))
            if int(payload['exp']) < time.time():
                return None
            return str(payload['uid'])
        except (ValueError, KeyError, TypeError):
            return None


# ---------- validation ----------
_USERNAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 _.\-]{1,22}[A-Za-z0-9]$')


def clean_username(raw) -> str:
    return " ".join(str(raw or "").split())


def validate_username(username: str) -> Optional[str]:
    """Return an error message, or None if the username is acceptable."""
    if not _USERNAME_RE.match(username):
        return "Username must be 3-24 characters: letters, numbers, spaces, dots, dashes or underscores."
    return None


def validate_password(password: str) -> Optional[str]:
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if len(password) > 128:
        return "Password must be at most 128 characters."
    return None


# ---------- rate limiting ----------
class RateLimiter:
    """Sliding-window limiter kept in memory (one process, which is what this app runs as)."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > 10000:   # keep memory bounded under key-spraying
            for stale in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                del self._hits[stale]
        return True


def client_ip(request) -> str:
    forwarded = request.headers.get('x-forwarded-for', '')
    return forwarded.split(',')[0].strip() or (request.client.host if request.client else 'unknown')
