"""Single-user auth, CSRF protection, rate limiting and security headers.

JobFish spends the owner's TinyFish credit and can hold vault credentials, so every
/api route except login and health requires a session.

Config (environment):
  APP_PASSWORD    the one login password. If unset, login is turned off and the app is open to
                  anyone with the URL (vault is then forced off; spend caps still apply).
  SECRET_KEY      signs session cookies. If unset, a random key is used and sessions
                  reset on every restart.
  COOKIE_SECURE   "0" to allow the cookie over plain http (local dev only). Default "1".
  SESSION_DAYS    session lifetime, default 7.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

COOKIE = "jf_session"
CSRF_HEADER = "x-jobfish"  # custom header: cross-site forms/images can't set it
PUBLIC_PATHS = {"/api/auth/login", "/api/auth/me", "/api/health"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self):
        self.password = os.getenv("APP_PASSWORD", "")
        self.auth_enabled = bool(self.password)
        if self.auth_enabled and len(self.password) < 8:
            raise RuntimeError("APP_PASSWORD must be at least 8 characters (or unset it to turn login off).")
        if not self.auth_enabled:
            print("WARNING: APP_PASSWORD not set: login is OFF and anyone with the URL can use this app. "
                  "Vault is disabled; daily agent-run cap still applies.")
        key = os.getenv("SECRET_KEY")
        if not key:
            print("WARNING: SECRET_KEY not set; using a random key (everyone is logged out on restart).")
            key = secrets.token_hex(32)
        self.key = hashlib.sha256(key.encode()).digest()
        self.cookie_secure = _env_bool("COOKIE_SECURE", True)
        self.session_seconds = int(os.getenv("SESSION_DAYS", "7")) * 86400
        # Never expose stored credentials on an open (no-login) instance.
        self.vault_enabled = _env_bool("ENABLE_VAULT", False) and self.auth_enabled
        self.max_agent_runs = int(os.getenv("MAX_CONCURRENT_AGENT_RUNS", "3"))
        self.max_sources = int(os.getenv("MAX_SOURCES", "100"))


settings: Settings | None = None
# Returns the current session generation; bumping it (on sign-out) revokes every issued cookie.
epoch_getter = lambda: 0  # noqa: E731


def init() -> Settings:
    global settings
    settings = Settings()
    return settings


# ---------------------------------------------------------------- sessions
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _pw_fingerprint() -> str:
    # Changing APP_PASSWORD invalidates every existing session.
    return hmac.new(settings.key, settings.password.encode(), hashlib.sha256).hexdigest()[:16]


def make_session() -> str:
    payload = _b64(json.dumps({"exp": int(time.time()) + settings.session_seconds, "pw": _pw_fingerprint(),
                               "ep": epoch_getter(), "n": secrets.token_hex(8)}).encode())
    sig = _b64(hmac.new(settings.key, payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def valid_session(token: str | None) -> bool:
    if not token or token.count(".") != 1:
        return False
    payload, sig = token.split(".")
    expected = _b64(hmac.new(settings.key, payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        data = json.loads(_unb64(payload))
    except Exception:
        return False
    return (data.get("exp", 0) > time.time() and data.get("ep") == epoch_getter()
            and hmac.compare_digest(str(data.get("pw")), _pw_fingerprint()))


def check_password(given: str) -> bool:
    if not settings.auth_enabled:
        return False
    return hmac.compare_digest(
        hashlib.sha256(given.encode()).digest(), hashlib.sha256(settings.password.encode()).digest()
    )


def set_cookie(response, token: str):
    response.set_cookie(COOKIE, token, max_age=settings.session_seconds, httponly=True,
                        secure=settings.cookie_secure, samesite="strict", path="/")


def clear_cookie(response):
    response.delete_cookie(COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict")


# ---------------------------------------------------------------- rate limiting
class RateLimiter:
    """In-memory sliding window per key. Fine for the single instance JobFish runs as."""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int) -> bool:
        """Record a hit; False if the key is over its limit."""
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def count(self, key: str, window: int) -> int:
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            return len(q)

    def reset(self, key: str):
        with self._lock:
            self._hits.pop(key, None)


limiter = RateLimiter()

# (limit, window seconds) per route group, per client
LIMITS = {
    "login": (5, 900),          # failed logins
    "agent": (20, 3600),        # scans, live scans, verifications that may start a TinyFish agent
    "search": (60, 3600),       # TinyFish Search / company lookup
    "fetch": (120, 3600),       # previews and posting reads
    "account": (30, 600),       # browser sessions, vault actions
}


def client_ip(request: Request) -> str:
    # uvicorn --proxy-headers already resolves X-Forwarded-For from trusted proxies into client.host
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request, group: str):
    limit, window = LIMITS[group]
    if not limiter.hit(f"{group}:{client_ip(request)}", limit, window):
        raise HTTPException(429, "Too many requests. Try again in a few minutes.")


# ---------------------------------------------------------------- middleware
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "object-src 'none'",
])


async def middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        if request.method not in SAFE_METHODS:
            # CSRF: require our custom header and, when the browser sends one, a same-origin Origin.
            if request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse({"detail": "Missing CSRF header"}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin.split("://", 1)[-1] != request.headers.get("host"):
                return JSONResponse({"detail": "Cross-origin request blocked"}, status_code=403)
        if settings.auth_enabled and path not in PUBLIC_PATHS and not valid_session(request.cookies.get(COOKIE)):
            return JSONResponse({"detail": "Not signed in"}, status_code=401)

    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "no-referrer")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    h.setdefault("Content-Security-Policy", CSP)
    if settings.cookie_secure:
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")
    return response
