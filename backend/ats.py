"""Fast path: many careers pages are backed by an applicant-tracking system (ATS) with a
public JSON job board. When we can identify one, we read it directly (about a second)
instead of driving a browser. Anything else falls back to the TinyFish agent."""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

TIMEOUT = 30

URL_PATTERNS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)"),
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([\w-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([\w.-]+)"),
    ("workable", r"apply\.workable\.com/([\w-]+)"),
]
BOARD_HINTS = [  # markers inside a careers page's HTML that reveal the ATS board
    ("greenhouse", r"greenhouse\.io/(?:embed/job_board(?:/js)?\?for=|v1/boards/)?([\w-]+)"),
    ("lever", r"jobs\.lever\.co/([\w-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([\w.-]+)"),
    ("workable", r"apply\.workable\.com/([\w-]+)"),
]
LABEL = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workable": "Workable"}


def _get(url: str):
    r = httpx.get(url, headers={"User-Agent": "JobFish/1.0", "Accept": "application/json"}, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    return r.json()


def _iso(v) -> str | None:
    if not v:
        return None
    if isinstance(v, (int, float)):  # Lever: epoch ms
        return datetime.fromtimestamp(v / 1000, timezone.utc).date().isoformat()
    return str(v)[:10]


def _greenhouse(slug):
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    out = []
    for j in data.get("jobs", []):
        meta = {m["name"]: m["value"] for m in j.get("metadata") or [] if m.get("value")}
        out.append(dict(
            title=j["title"].strip(), company=j.get("company_name"), location=(j.get("location") or {}).get("name"),
            job_type=meta.get("Employment Type") or meta.get("Duration"), url=j.get("absolute_url"),
            posted=_iso(j.get("first_published") or j.get("updated_at")), deadline=_iso(j.get("application_deadline")),
        ))
    return out


def _lever(slug):
    data = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=100")
    out = []
    for j in data if isinstance(data, list) else []:
        c = j.get("categories") or {}
        loc = c.get("location") or ", ".join(c.get("allLocations") or [])
        if j.get("workplaceType") == "remote" and "remote" not in (loc or "").lower():
            loc = f"{loc} (Remote)" if loc else "Remote"
        out.append(dict(
            title=j["text"].strip(), location=loc, job_type=c.get("commitment"), url=j.get("hostedUrl"),
            posted=_iso(j.get("createdAt")), description=(j.get("descriptionPlain") or "")[:220].strip() or None,
        ))
    return out


def _ashby(slug):
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        loc = j.get("location") or ""
        if j.get("isRemote") and "remote" not in loc.lower():
            loc = f"{loc} (Remote)" if loc else "Remote"
        out.append(dict(
            title=j["title"].strip(), location=loc, job_type=re.sub(r"(?<!^)([A-Z])", r"-\1", j.get("employmentType") or "") or None,
            url=j.get("jobUrl"), posted=_iso(j.get("publishedAt")),
            description=" · ".join(filter(None, [j.get("department"), j.get("team")])) or None,
        ))
    return out


def _workable(slug):
    data = _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    out = []
    for j in data.get("jobs", []):
        loc = ", ".join(filter(None, [j.get("city"), j.get("country")]))
        if j.get("telecommuting"):
            loc = f"{loc} (Remote)" if loc else "Remote"
        out.append(dict(
            title=j["title"].strip(), location=loc, job_type=j.get("employment_type"), url=j.get("url"),
            posted=_iso(j.get("published_on")), description=j.get("department") or None,
        ))
    return out


FETCHERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby, "workable": _workable}


def from_url(url: str):
    for provider, pat in URL_PATTERNS:
        m = re.search(pat, url)
        if m and m.group(1) not in ("embed", "v1") and SLUG.match(m.group(1)) and ".." not in m.group(1):
            return provider, m.group(1)
    return None


def from_html(html: str):
    for provider, pat in BOARD_HINTS:
        for slug in re.findall(pat, html or ""):
            if slug not in ("embed", "v1", "js", "jobs", "assets") and SLUG.match(slug) and ".." not in slug:
                return provider, slug
    return None


def guess_slugs(url: str) -> list[str]:
    host = urlparse(url).hostname or ""
    parts = [p for p in host.split(".") if p not in ("www", "careers", "jobs", "join", "about", "com", "co", "io", "ai", "org", "net", "in", "uk")]
    return [parts[0]] if parts else []


SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


def fetch_jobs(provider: str, slug: str) -> list[dict]:
    if provider not in FETCHERS or not SLUG.match(slug) or ".." in slug:
        raise ValueError(f"Bad job board {provider}:{slug}")
    return FETCHERS[provider](slug)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def guess(url: str, name: str):
    """Try the company's domain name as a board slug on boards that answer quickly.
    Only accept when the board's company name agrees, to avoid picking up a namesake."""
    want = {_norm(name), *(_norm(s) for s in guess_slugs(url))} - {""}
    for slug in guess_slugs(url):
        try:
            gh = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
            if _norm(gh.get("name")) in want or any(w in _norm(gh.get("name")) for w in want):
                return "greenhouse", slug
        except Exception:
            pass
        try:
            wk = _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
            if wk.get("jobs") and any(w in _norm(wk.get("name")) for w in want):
                return "workable", slug
        except Exception:
            pass
        try:
            ab = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
            if ab.get("jobs"):
                return "ashby", slug
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- company lookup
BOARD_URL = {
    "greenhouse": "https://boards.greenhouse.io/{}",
    "lever": "https://jobs.lever.co/{}",
    "ashby": "https://jobs.ashbyhq.com/{}",
    "workable": "https://apply.workable.com/{}/",
}


def slug_candidates(name: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", name.lower())
    words = [w for w in words if w not in ("inc", "llc", "ltd", "corp", "the")] or words
    out = ["".join(words), "-".join(words), words[0] if words else ""]
    return [s for i, s in enumerate(out) if s and s not in out[:i]]


def _probe_one(provider: str, slug: str) -> dict | None:
    """Cheap existence check for a board; returns {name, count} or None."""
    if not SLUG.match(slug) or ".." in slug:
        return None
    try:
        if provider == "greenhouse":
            meta = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
            jobs = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs").get("jobs", [])
            return {"name": meta.get("name"), "count": len(jobs)} if jobs else None
        if provider == "ashby":
            jobs = [j for j in _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}").get("jobs", []) if j.get("isListed", True)]
            return {"name": None, "count": len(jobs)} if jobs else None
        if provider == "workable":
            d = _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
            return {"name": d.get("name"), "count": len(d.get("jobs", []))} if d.get("jobs") else None
        if provider == "lever":
            r = httpx.get(f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=1", timeout=10)
            return {"name": None, "count": None} if r.status_code == 200 and r.json() else None
    except Exception:
        return None


def lookup(name: str) -> list[dict]:
    """Find public job boards for a company name across all supported providers, in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    tries = [(p, s) for s in slug_candidates(name) for p in FETCHERS]
    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(lambda ps: (ps, _probe_one(*ps)), tries))
    out = []
    for (provider, slug), hit in results:
        if hit:
            out.append({
                "name": hit["name"] or name.strip(), "url": BOARD_URL[provider].format(slug),
                "provider": provider, "slug": slug, "count": hit["count"], "kind": "board",
            })
    return out
