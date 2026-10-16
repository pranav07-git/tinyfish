"""Scrape careers pages with TinyFish and keep results fresh.

Per source: Fetch API (conditional GET) decides whether the page changed, then an
Agent run (queued) extracts structured jobs. A background worker polls Runs API for
completion and schedules due sources.
"""
import hashlib
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from tinyfish import RunStatus, TinyFish
from tinyfish.agent.types import (
    BrowserProfile, CompleteEvent, ProgressEvent, ProxyConfig,
    StartedEvent, StreamingUrlEvent,
)

import ats
import db
from matching import DEFAULT_PREFS, infer_seniority, score_job

MAX_AGENT_RUNS = int(os.getenv("MAX_CONCURRENT_AGENT_RUNS", "3"))
_clients: dict[str, TinyFish] = {}


def client(long: bool = False) -> TinyFish:
    """Quick calls (polling, fetch, search, account) get a short timeout so a hung request can't stall
    the worker; blocking agent calls (run/stream) keep the SDK's long default."""
    key = "long" if long else "quick"
    if key not in _clients:
        _clients[key] = TinyFish() if long else TinyFish(timeout=30, max_retries=1)
    return _clients[key]


JOBS_SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "location": {"type": "string"},
                    "job_type": {"type": "string"},
                    "url": {"type": "string"},
                    "posted": {"type": "string"},
                    "deadline": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["title", "url"],
            },
        }
    },
    "required": ["jobs"],
}


def prefs() -> dict:
    return {**DEFAULT_PREFS, **db.get_setting("prefs", {})}


def build_goal(source: dict) -> str:
    p = prefs()
    hint = []
    if p["roles"]:
        hint.append("roles like: " + ", ".join(p["roles"]))
    if p["locations"]:
        hint.append("locations: " + ", ".join(p["locations"]))
    if p["seniority"]:
        hint.append("levels: " + ", ".join(p["seniority"]))
    focus = (
        "If there are too many to list, collect the ones closest to " + "; ".join(hint) + " first, "
        "but do not filter anything out when the page has few listings. "
    ) if hint else ""
    return (
        f"List the open job and internship postings on this {source['kind']} page of {source['name']}. "
        "Wait for the listings to load (scroll down if the page loads more as you scroll). "
        "Read the listings shown on the page; if they are behind a link like 'View all jobs' or 'Search jobs', open it. "
        "Follow at most 2 'load more' / next-page clicks and stop at 30 postings. "
        f"{focus}For each posting return title, company, location, job_type, the direct posting url, "
        "posted date, application deadline and a one-line description. Use null for unknown fields. "
        "Only include real postings shown on the site; never invent data. If none are listed, return an empty list."
    )


def agent_kwargs(source: dict) -> dict:
    kw: dict = {
        "goal": build_goal(source),
        "url": source["url"],
        "output_schema": JOBS_SCHEMA,
        "browser_profile": BrowserProfile(source["browser_profile"]),
    }
    if source.get("proxy_country"):
        kw["proxy_config"] = ProxyConfig(enabled=True, country_code=source["proxy_country"])
    if source.get("use_vault"):
        kw["use_vault"] = True
        if source["credential_item_ids"]:
            kw["credential_item_ids"] = source["credential_item_ids"]
    return kw


# ---------------------------------------------------------------- ingestion
def _key(source_id: int, job: dict) -> str:
    base = job.get("url") or f"{job.get('company')}|{job.get('title')}|{job.get('location')}"
    base = re.sub(r"#.*$|[?&]utm_[^&#]*", "", base.strip().lower())
    return hashlib.sha1(f"{source_id}|{base}".encode()).hexdigest()


def ingest(source: dict, result: dict | None) -> tuple[int, int]:
    """Upsert jobs; mark unseen ones closed. Returns (found, new)."""
    raw = (result or {}).get("jobs") or []
    p, ts, seen, new = prefs(), db.now(), set(), 0
    baseline = int(not db.one("SELECT 1 FROM jobs WHERE source_id=? LIMIT 1", (source["id"],)))
    for j in raw:
        if not isinstance(j, dict):
            continue
        j = {k: (None if isinstance(v, str) and v.strip().lower() in ("", "null", "none", "n/a", "unknown") else v)
             for k, v in j.items()}
        if not j.get("title"):
            continue
        if not re.match(r"^https?://", str(j.get("url") or ""), re.I):
            j["url"] = None  # never store javascript:/data: or relative links from scraped pages
        j.setdefault("company", source["name"])
        j["seniority"] = infer_seniority(j["title"], j.get("job_type") or "")
        score, reasons = score_job(j, p)
        key = _key(source["id"], j)
        seen.add(key)
        fields = dict(
            title=str(j["title"])[:300], company=j.get("company") or source["name"], location=j.get("location"),
            job_type=j.get("job_type"), url=j.get("url"), posted=j.get("posted"), deadline=j.get("deadline"),
            description=j.get("description"), seniority=j["seniority"], score=score, reasons=reasons,
            is_open=1, last_seen=ts,
        )
        existing = db.one("SELECT id FROM jobs WHERE key=?", (key,))
        if existing:
            db.update("jobs", existing["id"], **fields)
        else:
            db.insert("jobs", source_id=source["id"], key=key, first_seen=ts, baseline=baseline, **fields)
            new += 1 - baseline
    if seen:  # only trust "gone" signals from a scan that actually found jobs
        for row in db.query("SELECT id, key FROM jobs WHERE source_id=? AND is_open=1", (source["id"],)):
            if row["key"] not in seen:
                db.update("jobs", row["id"], is_open=0)
    return len(seen), new


def rescore_all():
    p = prefs()
    for j in db.query("SELECT * FROM jobs"):
        s, r = score_job(j, p)
        db.update("jobs", j["id"], score=s, reasons=r)


def _finish_source(source_id: int, status: str, found: int | None = None):
    f = dict(last_status=status, last_scan_at=db.now())
    if found is not None:
        f["job_count"] = db.one("SELECT COUNT(*) n FROM jobs WHERE source_id=? AND is_open=1", (source_id,))["n"]
    db.update("sources", source_id, **f)


# ---------------------------------------------------------------- scans
def change_check(source: dict) -> bool:
    """Fetch API conditional GET. True if the page may have changed (or can't tell)."""
    try:
        r = client().fetch.get_contents(
            [source["url"]], format="markdown", include_etag_and_last_modified=True,
            if_none_match=source.get("etag"), if_modified_since=source.get("last_modified"),
            purpose="Detect whether a careers page changed since the last scan",
        )
    except Exception:
        return True
    db.update("sources", source["id"], last_checked=db.now())
    if not r.results:
        return True
    res = r.results[0]
    if res.not_modified:
        return False
    db.update("sources", source["id"], etag=res.etag, last_modified=res.last_modified)
    return True


def detect_board(source: dict, refresh: bool = False):
    """Find a public ATS job board behind this source. Cached on the source as 'provider:slug' or 'none'."""
    if source.get("ats") and not refresh:
        return None if source["ats"] == "none" else tuple(source["ats"].split(":", 1))
    found = ats.from_url(source["url"])
    if not found:
        try:  # Fetch API: look for an embedded board in the page HTML / links
            r = client().fetch.get_contents([source["url"]], format="html", links=True,
                                            purpose="Find the job board embedded in a careers page")
            if r.results:
                res = r.results[0]
                found = ats.from_html((res.text or "") + " " + " ".join(res.links))
        except Exception:
            pass
    found = found or ats.guess(source["url"], source["name"])
    db.update("sources", source["id"], ats=":".join(found) if found else "none")
    return found


def _run_scan(scan_id: int, source: dict, force: bool):
    if source.get("method") != "agent":
        try:
            board = detect_board(source, refresh=force)
            if board:
                provider, slug = board
                jobs = ats.fetch_jobs(provider, slug)
                found, new = ingest(source, {"jobs": jobs})
                db.update("scans", scan_id, status="completed", mode="ats", jobs_found=found, new_jobs=new,
                          finished_at=db.now(), note=f"{ats.LABEL[provider]} board '{slug}'")
                _finish_source(source["id"], "completed", found)
                return
        except Exception as e:
            print("ATS path failed, falling back to agent:", e)

    running = db.one("SELECT COUNT(*) n FROM scans WHERE status='running' AND mode IN ('queue','stream')")["n"]
    if running >= MAX_AGENT_RUNS:
        db.update("scans", scan_id, status="failed", finished_at=db.now(),
                  note=f"{MAX_AGENT_RUNS} agent runs already in progress; try again when one finishes")
        _finish_source(source["id"], "failed")
        return
    if not force and not change_check(source):
        db.update("scans", scan_id, status="unchanged", finished_at=db.now(), note="Page not modified (Fetch API)")
        _finish_source(source["id"], "unchanged")
        return
    try:
        resp = client().agent.queue(**agent_kwargs(source))
        if resp.error or not resp.run_id:
            raise RuntimeError(resp.error.message if resp.error else "No run id returned")
        db.update("scans", scan_id, status="running", mode="queue", tinyfish_run_id=resp.run_id,
                  note="TinyFish agent is browsing the page (usually 2-8 min)")
    except Exception as e:
        db.update("scans", scan_id, status="failed", note=str(e), finished_at=db.now())
        _finish_source(source["id"], "failed")


def start_scan(source: dict, force: bool = True) -> dict:
    if source.get("last_status") == "running":
        running = db.one("SELECT * FROM scans WHERE source_id=? AND status IN ('queued','running') ORDER BY id DESC", (source["id"],))
        if running:
            return running
    scan_id = db.insert("scans", source_id=source["id"], status="running", mode="detect", started_at=db.now())
    db.update("sources", source["id"], last_status="running")
    threading.Thread(target=_run_scan, args=(scan_id, source, force), daemon=True).start()
    return db.one("SELECT * FROM scans WHERE id=?", (scan_id,))


def poll_scans():
    for scan in db.query("SELECT * FROM scans WHERE status='running' AND mode='queue'"):
        source = db.one("SELECT * FROM sources WHERE id=?", (scan["source_id"],))
        if not source:
            continue
        try:
            run = client().runs.get(scan["tinyfish_run_id"])
        except Exception:
            continue
        if run.streaming_url and not scan["streaming_url"]:
            db.update("scans", scan["id"], streaming_url=run.streaming_url)
        if run.status in (RunStatus.PENDING, RunStatus.RUNNING):
            continue
        if run.status == RunStatus.COMPLETED:
            found, new = ingest(source, run.result)
            note = f"TinyFish agent found {found} postings" if found else (
                "Agent found no postings. Try a URL that lists jobs directly, or Live agent to watch what it sees")
            db.update("scans", scan["id"], status="completed", jobs_found=found, new_jobs=new, finished_at=db.now(), note=note)
            _finish_source(source["id"], "completed", found)
        else:
            msg = run.error.message if run.error else str(run.status)
            db.update("scans", scan["id"], status="failed", note=msg, finished_at=db.now())
            _finish_source(source["id"], "failed")


def stream_scan(source: dict):
    """Generator of SSE-ready dicts for a live scan (Agent stream endpoint)."""
    scan_id = db.insert("scans", source_id=source["id"], status="running", mode="stream", started_at=db.now())
    db.update("sources", source["id"], last_status="running")
    yield {"type": "scan", "scan_id": scan_id}
    try:
        with client(long=True).agent.stream(**agent_kwargs(source)) as stream:
            for ev in stream:
                if isinstance(ev, StartedEvent):
                    db.update("scans", scan_id, tinyfish_run_id=ev.run_id)
                    yield {"type": "started", "run_id": ev.run_id}
                elif isinstance(ev, StreamingUrlEvent):
                    db.update("scans", scan_id, streaming_url=ev.streaming_url)
                    yield {"type": "streaming_url", "url": ev.streaming_url}
                elif isinstance(ev, ProgressEvent):
                    yield {"type": "progress", "message": ev.purpose}
                elif isinstance(ev, CompleteEvent):
                    if ev.status == RunStatus.COMPLETED:
                        found, new = ingest(source, ev.result_json)
                        db.update("scans", scan_id, status="completed", jobs_found=found, new_jobs=new, finished_at=db.now())
                        _finish_source(source["id"], "completed", found)
                        yield {"type": "complete", "found": found, "new": new}
                    else:
                        msg = ev.error.message if ev.error else str(ev.status)
                        db.update("scans", scan_id, status="failed", note=msg, finished_at=db.now())
                        _finish_source(source["id"], "failed")
                        yield {"type": "error", "message": msg}
    except Exception as e:
        db.update("scans", scan_id, status="failed", note=str(e), finished_at=db.now())
        _finish_source(source["id"], "failed")
        yield {"type": "error", "message": str(e)}


def verify_job(job: dict) -> dict:
    """Agent run (blocking): is this posting still open?"""
    run = client(long=True).agent.run(
        url=job["url"],
        goal="Open this job posting and check whether it is still accepting applications "
             "(look for 'closed', 'no longer available', 404, or a working Apply button).",
        output_schema={
            "type": "object",
            "properties": {"open": {"type": "boolean"}, "reason": {"type": "string"}},
            "required": ["open"],
        },
    )
    result = run.result or {}
    is_open = bool(result.get("open")) if run.status == RunStatus.COMPLETED else None
    if is_open is not None:
        db.update("jobs", job["id"], is_open=int(is_open), verified=db.now())
    return {"open": is_open, "reason": result.get("reason") or (run.error.message if run.error else None)}


# ---------------------------------------------------------------- worker
def _due(source: dict) -> bool:
    if not source["interval_hours"] or source["last_status"] == "running":
        return False
    if not source["last_scan_at"]:
        return True
    last = datetime.fromisoformat(source["last_scan_at"])
    return datetime.now(timezone.utc) - last >= timedelta(hours=source["interval_hours"])


def worker():
    while True:
        try:
            poll_scans()
            for s in db.query("SELECT * FROM sources WHERE interval_hours > 0"):
                if _due(s):
                    start_scan(s, force=False)
        except Exception as e:  # never let the worker die
            print("worker error:", e)
        time.sleep(8)


def start_worker():
    threading.Thread(target=worker, daemon=True).start()
