import ipaddress
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

load_dotenv()

import ats  # noqa: E402
import db  # noqa: E402
import keepalive  # noqa: E402
import scanner  # noqa: E402
import security  # noqa: E402
from security import rate_limit  # noqa: E402

log = logging.getLogger("jobfish")
settings = security.init()
security.epoch_getter = lambda: db.get_setting("session_epoch", 0)


@asynccontextmanager
async def lifespan(_):
    db.init()
    # stream/detect scans die with the process; queued agent runs keep going and are picked up by the worker
    db.execute("UPDATE scans SET status='failed', note='Interrupted by restart', finished_at=? WHERE status='running' AND mode IN ('stream','detect','ats')", (db.now(),))
    db.execute("UPDATE sources SET last_status='failed' WHERE last_status='running' AND id NOT IN (SELECT source_id FROM scans WHERE status='running')")
    scanner.start_worker()
    keepalive.start()
    yield


docs = os.getenv("ENABLE_DOCS") == "1"
app = FastAPI(title="JobFish", lifespan=lifespan, docs_url="/api/docs" if docs else None,
              redoc_url=None, openapi_url="/api/openapi.json" if docs else None)
app.middleware("http")(security.middleware)


def tf(fn, *a, **kw):
    """Call TinyFish and turn SDK errors into clean HTTP errors (details stay in the server log)."""
    try:
        r = fn(*a, **kw)
    except HTTPException:
        raise
    except Exception as e:
        log.warning("TinyFish call %s failed: %r", getattr(fn, "__name__", fn), e)
        msg = str(e)
        if "api key" in msg.lower() or "authentication" in msg.lower():
            msg = "TinyFish rejected the API key"
        raise HTTPException(502, msg[:300])
    return r.model_dump(mode="json", by_alias=False) if hasattr(r, "model_dump") else r


def _source(sid: int) -> dict:
    s = db.one("SELECT * FROM sources WHERE id=?", (sid,))
    if not s:
        raise HTTPException(404, "Source not found")
    return s


# ------------------------------------------------------------ validation helpers
def check_url(u: str) -> str:
    """Only public http(s) URLs: no other schemes, embedded credentials, or local/private hosts."""
    u = (u or "").strip()
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname or len(u) > 2000:
        raise ValueError("Enter a full http(s) URL")
    if p.username or p.password:
        raise ValueError("URLs with credentials are not allowed")
    host = p.hostname.lower()
    if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("Local addresses are not allowed")
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise ValueError("Private or reserved IP addresses are not allowed")
    except ValueError as e:
        if "not allowed" in str(e):
            raise
    return u


Text = lambda n: Field(default="", max_length=n)  # noqa: E731


def _agent_slots_left() -> int:
    running = db.one("SELECT COUNT(*) n FROM scans WHERE status='running' AND mode IN ('queue','stream')")["n"]
    return settings.max_agent_runs - running


# ------------------------------------------------------------ auth
class LoginIn(BaseModel):
    password: str = Field(max_length=200)


@app.post("/api/auth/login")
def login(b: LoginIn, request: Request, response: Response):
    if not settings.auth_enabled:
        return {"ok": True}
    key = f"login:{security.client_ip(request)}"
    limit, window = security.LIMITS["login"]
    # lockout is checked before the password, so guesses during a lockout are never evaluated
    if security.limiter.count(key, window) >= limit:
        raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")
    if not security.check_password(b.password):
        security.limiter.hit(key, limit, window)
        raise HTTPException(401, "Wrong password")
    security.limiter.reset(key)
    security.set_cookie(response, security.make_session())
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response):
    """Signs out everywhere: bumping the epoch invalidates every cookie issued so far."""
    db.set_setting("session_epoch", db.get_setting("session_epoch", 0) + 1)
    security.clear_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request):
    authed = not settings.auth_enabled or security.valid_session(request.cookies.get(security.COOKIE))
    return {"authenticated": authed, "auth_enabled": settings.auth_enabled, "vault_enabled": settings.vault_enabled}


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health():
    """Public liveness check for Render's health check and uptime monitors (which often send HEAD).
    Deliberately reveals nothing beyond up/down."""
    try:
        db.one("SELECT 1 AS ok")
    except Exception:
        return JSONResponse({"ok": False}, status_code=503)
    return {"ok": True}


# ------------------------------------------------------------ preferences
class PrefsIn(BaseModel):
    roles: list[str] = Field(default_factory=list, max_length=30)
    locations: list[str] = Field(default_factory=list, max_length=30)
    seniority: list[Literal["intern", "entry", "mid", "senior", "lead"]] = Field(default_factory=list)
    remote_ok: bool = True
    exclude: list[str] = Field(default_factory=list, max_length=50)
    min_score: int = Field(default=0, ge=0, le=100)

    @field_validator("roles", "locations", "exclude")
    @classmethod
    def clean_list(cls, v):
        v = [s.strip()[:80] for s in v if s and s.strip()]
        return list(dict.fromkeys(v))


@app.get("/api/prefs")
def get_prefs():
    return scanner.prefs()


@app.put("/api/prefs")
def put_prefs(b: PrefsIn):
    db.set_setting("prefs", b.model_dump())
    scanner.rescore_all()
    return scanner.prefs()


# ------------------------------------------------------------ sources
class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str
    kind: Literal["careers", "portal"] = "careers"
    method: Literal["auto", "agent"] = "auto"  # auto: public job-board API when found, else agent
    interval_hours: Literal[0, 6, 12, 24, 168] = 0
    browser_profile: Literal["lite", "stealth"] = "lite"
    proxy_country: Literal["US", "GB", "CA", "DE", "FR", "JP", "AU"] | None = None
    use_vault: bool = False
    credential_item_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("url")
    @classmethod
    def valid_url(cls, v):
        return check_url(v)

    @field_validator("name")
    @classmethod
    def clean_name(cls, v):
        return v.strip()

    @field_validator("credential_item_ids")
    @classmethod
    def valid_ids(cls, v):
        if any(len(i) > 300 for i in v):
            raise ValueError("Bad credential id")
        return v


def _source_fields(b: SourceIn) -> dict:
    if b.use_vault and not settings.vault_enabled:
        raise HTTPException(403, "Vault is disabled on this server (set ENABLE_VAULT=1)")
    return {**b.model_dump(), "use_vault": int(b.use_vault)}


PRESETS = [
    ("Jane Street", "https://www.janestreet.com/join-jane-street/open-roles/"),
    ("Stripe", "https://stripe.com/jobs"),
    ("Anthropic", "https://www.anthropic.com/careers"),
    ("OpenAI", "https://jobs.ashbyhq.com/openai"),
    ("Databricks", "https://www.databricks.com/company/careers"),
    ("Figma", "https://www.figma.com/careers/"),
    ("Cloudflare", "https://www.cloudflare.com/careers/jobs/"),
    ("Coinbase", "https://www.coinbase.com/careers/positions"),
    ("Notion", "https://jobs.ashbyhq.com/notion"),
    ("Ramp", "https://jobs.ashbyhq.com/ramp"),
    ("Airbnb", "https://careers.airbnb.com/positions/"),
    ("Duolingo", "https://careers.duolingo.com/"),
    ("Discord", "https://discord.com/careers"),
    ("Robinhood", "https://careers.robinhood.com/"),
    ("Linear", "https://jobs.ashbyhq.com/linear"),
    ("Hugging Face", "https://apply.workable.com/huggingface/"),
]


@app.get("/api/presets")
def presets():
    have = {s["url"] for s in db.query("SELECT url FROM sources")}
    return [{"name": n, "url": u, "added": u in have} for n, u in PRESETS]


@app.get("/api/stats")
def stats():
    one = lambda sql: db.one(sql)["n"]  # noqa: E731
    return {
        "open": one("SELECT COUNT(*) n FROM jobs WHERE is_open=1"),
        "new": one("SELECT COUNT(*) n FROM jobs WHERE is_open=1 AND baseline=0 AND first_seen >= strftime('%Y-%m-%dT%H:%M:%S','now','-2 days')"),
        "matches": one("SELECT COUNT(*) n FROM jobs WHERE is_open=1 AND status!='hidden' AND score >= 60"),
        "sources": one("SELECT COUNT(*) n FROM sources"),
        "applied": one("SELECT COUNT(*) n FROM jobs WHERE status='applied'"),
        "companies": one("SELECT COUNT(DISTINCT company) n FROM jobs WHERE is_open=1"),
    }


CAREER_HINT = re.compile(r"career|jobs|join|work-with-us|opportunit|hiring|positions|openings", re.I)
NOT_CAREERS = re.compile(r"/(docs?|blog|news|press|help|support)/")


@app.get("/api/companies/search")
def company_search(q: str, request: Request):
    """Find where a company posts jobs: public job boards (probed directly) plus its careers page
    found with TinyFish Search. Each result can be tracked as a source."""
    q = q.strip()[:80]
    if len(q) < 2:
        return []
    rate_limit(request, "search")
    from concurrent.futures import ThreadPoolExecutor

    def web():
        try:
            r = scanner.client().search.query(f"{q} careers jobs", purpose=f"Find the official careers page of {q}")
            return r.results
        except Exception:
            return []

    with ThreadPoolExecutor(2) as ex:
        boards_f, web_f = ex.submit(ats.lookup, q), ex.submit(web)
        boards, web_results = boards_f.result(), web_f.result()
    web_results = [r for r in web_results if urlparse(r.url).scheme in ("http", "https")]

    out, seen = list(boards), {(b["provider"], b["slug"]) for b in boards}
    tokens = [t for t in re.findall(r"[a-z0-9]+", q.lower()) if len(t) > 2] or [q.lower()]
    for r in web_results[:10]:
        board = ats.from_url(r.url)
        if board:
            if board not in seen:
                seen.add(board)
                out.append({"name": q, "url": ats.BOARD_URL[board[0]].format(board[1]), "provider": board[0],
                            "slug": board[1], "count": None, "kind": "board"})
            continue
        if NOT_CAREERS.search(r.url):
            continue
        host = re.sub(r"^www\.", "", r.site_name.lower())
        if any(t in host.replace("-", "") for t in tokens) and CAREER_HINT.search(r.url + " " + r.title):
            out.append({"name": q, "url": r.url, "provider": None, "slug": None, "count": None,
                        "kind": "careers", "title": r.title, "snippet": r.snippet})
    if not out:  # nothing obviously official: offer the best careers-looking web results instead
        for r in web_results:
            if CAREER_HINT.search(r.url + " " + r.title) and not NOT_CAREERS.search(r.url):
                out.append({"name": q, "url": r.url, "provider": None, "slug": None, "count": None,
                            "kind": "web", "title": r.title, "snippet": r.snippet, "site": r.site_name})
            if len(out) >= 4:
                break
    have = {s["url"] for s in db.query("SELECT url FROM sources")}
    for o in out:
        o["added"] = o["url"] in have
    # boards first (fast + complete), then official careers pages
    return sorted(out, key=lambda o: (o["kind"] != "board", -(o["count"] or 0)))[:8]


@app.get("/api/sources")
def list_sources():
    return db.query("SELECT * FROM sources ORDER BY id DESC")


@app.post("/api/sources")
def add_source(b: SourceIn):
    if db.one("SELECT COUNT(*) n FROM sources")["n"] >= settings.max_sources:
        raise HTTPException(409, f"Source limit reached ({settings.max_sources}). Remove one first.")
    if db.one("SELECT id FROM sources WHERE url=?", (b.url,)):
        raise HTTPException(409, "That URL is already a source")
    sid = db.insert("sources", created_at=db.now(), **_source_fields(b))
    return db.one("SELECT * FROM sources WHERE id=?", (sid,))


@app.put("/api/sources/{sid}")
def edit_source(sid: int, b: SourceIn):
    old = _source(sid)
    extra = {"ats": None} if old["url"] != b.url else {}  # re-detect the job board for a new URL
    db.update("sources", sid, **_source_fields(b), **extra)
    return _source(sid)


@app.delete("/api/sources/{sid}")
def delete_source(sid: int):
    db.execute("DELETE FROM jobs WHERE source_id=?", (sid,))
    db.execute("DELETE FROM scans WHERE source_id=?", (sid,))
    db.execute("DELETE FROM sources WHERE id=?", (sid,))
    return {"ok": True}


@app.post("/api/sources/{sid}/scan")
def scan_source(sid: int, request: Request, force: bool = True):
    """Public job-board API when one is found, otherwise a queued agent run (Agent queue + Runs get).
    force=false lets the agent path skip unchanged pages (Fetch conditional GET)."""
    source = _source(sid)
    rate_limit(request, "agent")
    return scanner.start_scan(source, force=force)


@app.post("/api/sources/{sid}/live-scan")
def live_scan(sid: int, request: Request):
    """Live agent run streamed to the browser as server-sent events (Agent stream)."""
    source = _source(sid)
    rate_limit(request, "agent")
    if _agent_slots_left() <= 0:
        raise HTTPException(429, f"{settings.max_agent_runs} agent runs already in progress. Wait for one to finish.")
    if not scanner.take_daily_agent_run():
        raise HTTPException(429, scanner.DAILY_CAP_MSG)

    def gen():
        for ev in scanner.stream_scan(source):
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@app.get("/api/scans")
def list_scans():
    return db.query(
        "SELECT sc.*, s.name AS source_name FROM scans sc LEFT JOIN sources s ON s.id=sc.source_id ORDER BY sc.id DESC LIMIT 50"
    )


# ------------------------------------------------------------ jobs
@app.get("/api/jobs")
def list_jobs():
    return db.query(
        "SELECT j.*, s.name AS source_name FROM jobs j LEFT JOIN sources s ON s.id=j.source_id ORDER BY j.score DESC, j.first_seen DESC LIMIT 5000"
    )


class JobPatch(BaseModel):
    status: Literal["none", "saved", "applied", "hidden"]


@app.patch("/api/jobs/{jid}")
def patch_job(jid: int, b: JobPatch):
    _job(jid)
    db.update("jobs", jid, status=b.status)
    return {"ok": True}


def _job(jid: int) -> dict:
    j = db.one("SELECT * FROM jobs WHERE id=?", (jid,))
    if not j:
        raise HTTPException(404, "Job not found")
    return j


def _job_url(job: dict) -> str:
    try:
        return check_url(job.get("url") or "")
    except ValueError:
        raise HTTPException(422, "This posting has no usable link")


@app.post("/api/jobs/{jid}/verify")
def verify(jid: int, request: Request):
    """Agent run (sync): is the posting still open?"""
    job = _job(jid)
    _job_url(job)
    rate_limit(request, "agent")
    if _agent_slots_left() <= 0:
        raise HTTPException(429, "Agent runs are busy. Try again shortly.")
    if not scanner.take_daily_agent_run():
        raise HTTPException(429, scanner.DAILY_CAP_MSG)
    try:
        return scanner.verify_job(job)
    except Exception as e:
        log.warning("verify failed: %r", e)
        raise HTTPException(502, "The agent couldn't check this posting")


def _fetch_page(url: str, query: str, purpose: str) -> dict:
    """Fetch API; uses ranked highlights when the account has them, else a text excerpt."""
    base = dict(format="markdown", links=True, purpose=purpose)
    try:
        r = tf(scanner.client().fetch.get_contents, [url], highlights={"query": query[:200], "max_snippets": 6}, **base)
    except HTTPException as e:
        if "highlights" not in str(e.detail):
            raise
        r = tf(scanner.client().fetch.get_contents, [url], **base)
    if r["errors"]:
        raise HTTPException(502, str(r["errors"][0]["error"])[:200])
    res = r["results"][0]
    hl = [h["text"] for h in (res["highlights"] or [])]
    links = [l for l in res["links"] if urlparse(l).scheme in ("http", "https")][:20]
    return {"title": res["title"], "description": res["description"], "highlights": hl,
            "excerpt": (res["text"] or "")[:3000] if not hl else "", "links": links,
            "latency_ms": res["latency_ms"]}


@app.get("/api/jobs/{jid}/details")
def job_details(jid: int, request: Request):
    """Fetch API: pull the posting text, ranked against the user's preferences."""
    url = _job_url(_job(jid))
    rate_limit(request, "fetch")
    q = " ".join(scanner.prefs()["roles"] + ["requirements", "qualifications"])
    return _fetch_page(url, q, "Summarise a job posting for a candidate")


# ------------------------------------------------------------ discovery (Search API)
class DiscoverIn(BaseModel):
    query: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=100)
    recency_days: int | None = Field(default=None, ge=1, le=365)
    include_domains: str | None = Field(default=None, max_length=500, pattern=r"^[\w.,\s-]*$")
    page: int = Field(default=0, ge=0, le=20)


@app.post("/api/discover")
def discover(b: DiscoverIn, request: Request):
    rate_limit(request, "search")
    p = scanner.prefs()
    q = b.query or " ".join(filter(None, [(p["roles"] or ["software engineer"])[0], "careers openings"]))
    kw = dict(purpose="Find live job or internship openings and careers pages", page=b.page)
    loc = b.location or (p["locations"][0] if p["locations"] else None)
    if loc:
        kw["location"] = loc
    if b.recency_days:
        kw["recency_minutes"] = b.recency_days * 1440
    if b.include_domains:
        kw["include_domains"] = b.include_domains.replace(" ", "")
    r = tf(scanner.client().search.query, q, **kw)
    r["results"] = [x for x in r["results"] if urlparse(x["url"]).scheme in ("http", "https")]
    have = {s["url"] for s in db.query("SELECT url FROM sources")}
    for x in r["results"]:
        x["is_source"] = x["url"] in have
    return r


class UrlIn(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def valid_url(cls, v):
        return check_url(v)


@app.post("/api/preview")
def preview(b: UrlIn, request: Request):
    """Fetch API: quick look at a page before adding it as a source."""
    rate_limit(request, "fetch")
    return _fetch_page(b.url, " ".join(scanner.prefs()["roles"]) or "open positions", "Preview a careers page")


# ------------------------------------------------------------ TinyFish account: runs, browser, vault, wallet
RUN_ID = r"^[A-Za-z0-9-]{8,64}$"


@app.get("/api/tf/runs")
def tf_runs(status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"] | None = None, limit: int = 30):
    return tf(scanner.client().runs.list, limit=max(1, min(limit, 100)), status=status, sort_direction="desc")


@app.get("/api/tf/runs/{rid}")
def tf_run(rid: str):
    if not re.match(RUN_ID, rid):
        raise HTTPException(422, "Bad run id")
    return tf(scanner.client().runs.get, rid)


class BrowserIn(BaseModel):
    url: str | None = None
    timeout_seconds: int = Field(default=300, ge=60, le=900)

    @field_validator("url")
    @classmethod
    def valid_url(cls, v):
        return check_url(v) if v else None


@app.post("/api/tf/browser")
def tf_browser(b: BrowserIn, request: Request):
    rate_limit(request, "account")
    return tf(scanner.client().browser.sessions.create, url=b.url, timeout_seconds=b.timeout_seconds)


@app.get("/api/tf/wallet")
def tf_wallet():
    return tf(scanner.client().wallet.get)


def _vault_on():
    if not settings.vault_enabled:
        raise HTTPException(403, "Vault is disabled on this server (needs login on and ENABLE_VAULT=1)")


def _confirm(password: str):
    if not security.check_password(password or ""):
        raise HTTPException(403, "Re-enter your JobFish password to change vault settings")


@app.get("/api/tf/vault")
def tf_vault():
    if not settings.vault_enabled:
        return {"enabled": False, "connections": [], "items": []}
    items = tf(scanner.client().vault.items.list)["items"]
    # metadata only: never expose field values (the SDK doesn't return them, but be explicit)
    safe = [{"item_id": i["item_id"], "label": i["label"], "domains": i["domains"], "vault_name": i["vault_name"],
             "has_totp": i["has_totp"]} for i in items]
    return {"enabled": True, "connections": tf(scanner.client().vault.connections.list)["connections"], "items": safe}


class VaultConnectIn(BaseModel):
    confirm_password: str = Field(max_length=200)
    provider: Literal["1password", "bitwarden"]
    token: str | None = Field(default=None, max_length=4000)
    client_id: str | None = Field(default=None, max_length=500)
    client_secret: str | None = Field(default=None, max_length=500)
    master_password: str | None = Field(default=None, max_length=500)
    server_url: str | None = None

    @field_validator("server_url")
    @classmethod
    def valid_url(cls, v):
        return check_url(v) if v else None


@app.post("/api/tf/vault/connect")
def tf_vault_connect(b: VaultConnectIn, request: Request):
    _vault_on()
    rate_limit(request, "account")
    _confirm(b.confirm_password)
    v = scanner.client().vault.connections
    if b.provider == "1password":
        if not b.token:
            raise HTTPException(422, "Service account token required")
        r = tf(v.connect_1password, token=b.token)
    else:
        if not (b.client_id and b.client_secret and b.master_password):
            raise HTTPException(422, "Client ID, client secret and master password are required")
        r = tf(v.connect_bitwarden, client_id=b.client_id, client_secret=b.client_secret,
               master_password=b.master_password, server_url=b.server_url)
    return {"connected": r["connected"], "provider": r["provider"], "items": len(r.get("items") or [])}


class ConfirmIn(BaseModel):
    confirm_password: str = Field(max_length=200)


@app.post("/api/tf/vault/sync")
def tf_vault_sync(request: Request):
    _vault_on()
    rate_limit(request, "account")
    r = tf(scanner.client().vault.items.sync)
    return {"sync_summary": r["sync_summary"]}


@app.post("/api/tf/vault/connections/{cid}/disconnect")
def tf_vault_disconnect(cid: str, b: ConfirmIn, request: Request):
    _vault_on()
    rate_limit(request, "account")
    _confirm(b.confirm_password)
    if not re.match(r"^[A-Za-z0-9_-]{1,100}$", cid):
        raise HTTPException(422, "Bad connection id")
    return tf(scanner.client().vault.connections.disconnect, cid)


# ------------------------------------------------------------ frontend (built React app)
DIST = Path(os.getenv("FRONTEND_DIST", Path(__file__).resolve().parent.parent / "frontend" / "dist"))
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
