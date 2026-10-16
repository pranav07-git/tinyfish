import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("DB_PATH") or Path(__file__).parent / "jobfish.db")
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  kind TEXT DEFAULT 'careers',
  interval_hours INTEGER DEFAULT 0,
  browser_profile TEXT DEFAULT 'lite',
  proxy_country TEXT,
  use_vault INTEGER DEFAULT 0,
  credential_item_ids TEXT DEFAULT '[]',
  etag TEXT, last_modified TEXT,
  last_checked TEXT, last_scan_at TEXT, last_status TEXT,
  job_count INTEGER DEFAULT 0,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
  key TEXT NOT NULL UNIQUE,
  title TEXT, company TEXT, location TEXT, job_type TEXT, url TEXT,
  posted TEXT, deadline TEXT, description TEXT,
  seniority TEXT, score INTEGER DEFAULT 0, reasons TEXT DEFAULT '[]',
  is_open INTEGER DEFAULT 1,
  status TEXT DEFAULT 'none',
  verified TEXT,
  first_seen TEXT, last_seen TEXT
);
CREATE TABLE IF NOT EXISTS scans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
  status TEXT, mode TEXT,
  tinyfish_run_id TEXT, streaming_url TEXT,
  jobs_found INTEGER DEFAULT 0, new_jobs INTEGER DEFAULT 0,
  note TEXT, started_at TEXT, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, data TEXT);
"""

JSON_COLS = {"credential_item_ids", "reasons", "data"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


MIGRATIONS = {
    "sources": {"method": "TEXT DEFAULT 'auto'", "ats": "TEXT"},
    "jobs": {"baseline": "INTEGER DEFAULT 0"},  # found by a source's first scan, so not "new"
}


def init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock, conn() as c:
        c.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            for col, decl in cols.items():
                if col not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def _row(r):
    d = dict(r)
    for k in JSON_COLS & d.keys():
        d[k] = json.loads(d[k]) if d[k] else []
    return d


def query(sql, args=()):
    args = _enc(args)
    with _lock, conn() as c:
        return [_row(r) for r in c.execute(sql, args).fetchall()]


def one(sql, args=()):
    rows = query(sql, args)
    return rows[0] if rows else None


def _enc(args):
    return tuple(json.dumps(a) if isinstance(a, (list, dict)) else a for a in args)


def execute(sql, args=()):
    with _lock, conn() as c:
        cur = c.execute(sql, _enc(args))
        return cur.lastrowid


def insert(table, **f):
    cols = ", ".join(f)
    return execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(f))})", tuple(f.values()))


def update(table, id_, **f):
    if f:
        execute(f"UPDATE {table} SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), id_))


def get_setting(key, default):
    r = one("SELECT data FROM settings WHERE key=?", (key,))
    return r["data"] if r else default


def set_setting(key, data):
    execute("INSERT INTO settings (key, data) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET data=excluded.data", (key, data))
