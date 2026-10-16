"""Score a job against the user's preferences (role, location, seniority)."""
import re

SENIORITY_WORDS = {
    "intern": r"\bintern(ship)?s?\b|\bco-?op\b|\bsummer analyst\b|\bapprentice",
    "entry": r"\bgraduate\b|\bnew grad\b|\bentry[- ]level\b|\bjunior\b|\bjr\.?\b|\bassociate\b|\bearly career\b|\b(engineer|developer) (i|1)\b",
    "senior": r"\bsenior\b|\bsr\.?\b|\b(engineer|developer) (iii|3)\b",
    "lead": r"\bstaff\b|\bprincipal\b|\blead\b|\bmanager\b|\bdirector\b|\bhead of\b|\bvp\b|\barchitect\b",
}
LEVELS = ["intern", "entry", "mid", "senior", "lead"]
DEFAULT_PREFS = {
    "roles": [], "locations": [], "seniority": [], "remote_ok": True, "exclude": [], "min_score": 0,
}


def infer_seniority(title: str, job_type: str = "") -> str:
    text = f"{title} {job_type}".lower()
    for level in ("intern", "lead", "senior", "entry"):  # intern first: "Senior Intern" is rare
        if re.search(SENIORITY_WORDS[level], text):
            return level
    return "mid"


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9+#]+", s.lower()) if len(t) > 1}


def score_job(job: dict, prefs: dict) -> tuple[int, list[str]]:
    title, loc = job.get("title") or "", (job.get("location") or "").lower()
    blob = f"{title} {job.get('description') or ''}".lower()
    reasons: list[str] = []

    for bad in prefs.get("exclude", []):
        if bad.strip() and bad.strip().lower() in blob:
            return 0, [f"excluded: {bad}"]

    parts: list[tuple[float, float]] = []  # (weight, 0..1 fit)
    roles = [r for r in prefs.get("roles", []) if r.strip()]
    if roles:
        tt, best = _tokens(title), 0.0
        for r in roles:
            rt = _tokens(r)
            if rt:
                best = max(best, len(rt & tt) / len(rt))
        parts.append((50, best))
        if best:
            reasons.append("role match" if best >= 0.99 else "partial role match")

    locs = [l.strip().lower() for l in prefs.get("locations", []) if l.strip()]
    if locs or prefs.get("remote_ok"):
        remote = "remote" in loc or "anywhere" in loc
        hit = any(l in loc for l in locs)
        fit = 1.0 if hit else 0.8 if (remote and prefs.get("remote_ok")) else 0.0
        if not locs and not remote:
            fit = 0.5  # no location preference; don't punish
        parts.append((25, fit))
        if hit:
            reasons.append("location match")
        elif remote and prefs.get("remote_ok"):
            reasons.append("remote")

    want = prefs.get("seniority", [])
    if want:
        lvl = job.get("seniority") or infer_seniority(title, job.get("job_type") or "")
        d = min(abs(LEVELS.index(lvl) - LEVELS.index(w)) for w in want)
        parts.append((25, max(0.0, 1 - d / 2)))
        if d == 0:
            reasons.append(f"{lvl} level")

    if not parts:
        return 50, []
    total = sum(w for w, _ in parts)
    return round(100 * sum(w * f for w, f in parts) / total), reasons
