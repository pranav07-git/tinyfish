"""Optional self-ping so a Render free instance doesn't spin down when idle.

Render puts free web services to sleep after ~15 minutes without inbound traffic. On Render
(which sets RENDER=true) this is on unless KEEP_ALIVE=0; elsewhere set KEEP_ALIVE=1. It pings the service's own public URL (RENDER_EXTERNAL_URL, which Render
sets automatically, or KEEP_ALIVE_URL) every KEEP_ALIVE_MINUTES (default 10), so the
request arrives through Render's edge like a normal visitor.
Paid instances never sleep and don't need this.
"""
import os
import threading
import time

import httpx


def _loop(url: str, every: int):
    time.sleep(60)  # let the server finish starting
    while True:
        try:
            r = httpx.get(url, timeout=20, headers={"User-Agent": "JobFish-keepalive"})
            if r.status_code != 200:
                print(f"keepalive: {url} returned {r.status_code}")
        except Exception as e:
            print(f"keepalive: ping failed: {e!r}")
        time.sleep(every * 60)


def start():
    default = "1" if os.getenv("RENDER") else "0"
    if os.getenv("KEEP_ALIVE", default).lower() not in ("1", "true", "yes", "on"):
        return
    base = (os.getenv("KEEP_ALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if not base.startswith("https://"):
        print("keepalive: KEEP_ALIVE=1 but no https RENDER_EXTERNAL_URL / KEEP_ALIVE_URL; not starting")
        return
    every = max(1, int(os.getenv("KEEP_ALIVE_MINUTES", "10")))
    threading.Thread(target=_loop, args=(f"{base}/api/health", every), daemon=True).start()
    print(f"keepalive: pinging {base}/api/health every {every} min")
