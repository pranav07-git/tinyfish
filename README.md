# JobFish — TinyFish job & internship scraper

Pulls live openings from company careers pages and job portals with the TinyFish Web Agent, scores them against what you're looking for (role, location, seniority), and keeps them fresh on a schedule.

Built for "AI That Clicks." — the TinyFish × Team Technojam workshop at Galgotias University.

## Run locally

```bash
cp .env.example .env            # set TINYFISH_API_KEY, APP_PASSWORD, SECRET_KEY, and COOKIE_SECURE=0 for local http
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd backend && ../.venv/bin/uvicorn app:app --port 8000 --reload   # API + background refresher
cd frontend && npm install && npm run dev                          # UI on http://localhost:5173
```

Or run the production image locally:

```bash
docker build -t jobfish .
docker run --env-file .env -e COOKIE_SECURE=0 -p 8000:8000 -v jobfish-data:/data jobfish   # http://localhost:8000
```

## Deploy on Render (free plan)

JobFish runs as **one container**: FastAPI serves the API and the built React app, a background thread refreshes sources, and SQLite stores everything. `render.yaml` describes the whole setup.

1. Push this repo to GitHub.
2. In Render: **New → Blueprint**, connect the repo. Render reads `render.yaml`.
3. When prompted, enter `TINYFISH_API_KEY` and a long random `APP_PASSWORD`. `SECRET_KEY` is generated for you.
4. Deploy. Render builds the `Dockerfile`, health-checks `/api/health`, and gives you `https://<name>.onrender.com`.

**Staying awake.** Free instances sleep after ~15 minutes without traffic. `backend/keepalive.py` pings the app's own public URL (`/api/health`) every 10 minutes, so it never goes idle. It's on automatically on Render; set `KEEP_ALIVE=0` to turn it off. As a backup (it also wakes the app after a crash), add a free uptime monitor such as UptimeRobot on `https://<name>.onrender.com/api/health` every 5 minutes.

**Data on free.** Free instances have no persistent disk, so the database starts empty after every deploy or restart: re-add sources and preferences (job-board sources re-fetch in seconds).

Keep it at **one instance**: the refresh worker, rate limits and SQLite assume a single process.

## Security

- **Sign-in required.** Every `/api` route except sign-in and health needs a session. Sessions are HMAC-signed, `HttpOnly`, `Secure`, `SameSite=Strict` cookies that expire after `SESSION_DAYS`. Signing out revokes every session, and changing `APP_PASSWORD` or `SECRET_KEY` does too.
- **Brute-force protection.** 5 failed sign-ins per IP in 15 minutes locks that IP out; the password isn't even checked while locked.
- **CSRF.** State-changing requests need an `X-Jobfish` header and a same-origin `Origin`.
- **Vault off by default.** `ENABLE_VAULT=1` turns it on; connecting or disconnecting then requires re-entering the password. Vault secrets are passed to TinyFish and never stored or logged by JobFish; only item labels are shown.
- **Spend limits.** Rate limits on agent scans, searches, fetches and browser sessions; at most `MAX_CONCURRENT_AGENT_RUNS` agent runs at once and `MAX_SOURCES` sources.
- **Input validation.** URLs must be public `http(s)` (no credentials, localhost or private IPs); all bodies are schema-checked with length limits; job-board slugs are whitelisted.
- **Safe rendering.** Links from scraped pages are only stored and rendered if they are `http(s)`, so `javascript:` links can't run. React escapes all text.
- **Headers.** Strict Content-Security-Policy, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, HSTS, `no-store` on API responses; API docs are off unless `ENABLE_DOCS=1`.
- **Container.** Runs as an unprivileged user; secrets come from environment variables only (`.env` and the database are excluded from git and the image).

### How jobs are fetched
1. **Job-board fast path (seconds).** Many careers pages are backed by Greenhouse, Lever, Ashby or Workable, which publish open JSON job boards. JobFish detects the board from the URL, from the page HTML (via TinyFish Fetch), or by trying the company's domain name, then reads every posting directly.
2. **TinyFish agent (minutes).** Any other site is browsed by the TinyFish Web Agent, which returns structured jobs. Scans are queued and a background worker collects the results, so closing the browser tab doesn't lose anything.

Set a source's "How to fetch" option to *Always use TinyFish agent* to skip step 1.

| TinyFish API | Where |
|---|---|
| `agent.queue` + `runs.get` | **Scan** of sites without a public job board; a background worker polls for results |
| `agent.stream` | **Live scan**: step-by-step progress and the live browser link streamed to the UI |
| `agent.run` | **Still open?**: checks a single posting synchronously |
| `fetch.get_contents` | Job-board detection, change detection (ETag / Last-Modified) to skip unchanged pages, **Read the posting**, source **Preview** |
| `search.query` | **Discover**: finds careers pages / job boards by role, location, recency, domain |
| `runs.list` | TinyFish tab: run history with results and replay links |
| `browser.sessions.create` | **Browse**: remote browser session (CDP URL for Playwright) |
| `vault.*` | Connect 1Password/Bitwarden, sync and list credentials for login-only portals |
| `wallet.get` | Balance and rates in the header and TinyFish tab |

Agent options per source: browser profile (lite/stealth), proxy country, vault credentials.

## Layout
- `backend/` — FastAPI + SQLite (`app.py` routes, `security.py` auth/CSRF/rate limits/headers, `scanner.py` scans and refresh worker, `ats.py` job-board fast path, `matching.py` scoring, `db.py`)
- `frontend/` — React (Vite): Openings, Sources, Discover, Preferences, TinyFish. Tabs are linkable (`/#sources`).
- `main.py` — the original workshop script
