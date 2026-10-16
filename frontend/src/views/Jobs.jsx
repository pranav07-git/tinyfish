import { useMemo, useState } from "react";
import { api, ago, safeUrl } from "../api";
import { Eyebrow, Grid, SectionHead, fmt, pad } from "../components/Ui.jsx";
import CompanySearch from "../components/CompanySearch.jsx";

const DAY = 864e5;
const isNew = (j) => !j.baseline && Date.now() - new Date(j.first_seen).getTime() < 2 * DAY;
const PAGE = 40;
const shortLoc = (l) => (l || "—").split(/\s*[|;]\s*/)[0].replace(/, United States$/, "");

function Detail({ job, onClose, refresh, setError }) {
  const [d, setD] = useState(null);
  const [v, setV] = useState(null);
  const [busy, setBusy] = useState("");

  const run = async (name, fn, set) => {
    setBusy(name);
    try { set(await fn()); if (name === "verify") refresh(); } catch (e) { setError(e.message); }
    setBusy("");
  };
  const mark = async (status) => { await api.setJobStatus(job.id, job.status === status ? "none" : status); refresh(); };

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer">
        <button className="close" onClick={onClose}>✕</button>
        <Eyebrow>{job.company}</Eyebrow>
        <h2 className="display lg">{job.title}</h2>
        <p className="muted">{job.location || "Location not listed"}</p>

        <div className="kv">
          <div><span className="mono">Match</span><b className="display">{job.score}%</b></div>
          <div><span className="mono">Level</span><b>{job.seniority}</b></div>
          <div><span className="mono">Type</span><b>{job.job_type || "—"}</b></div>
          <div><span className="mono">Posted</span><b>{job.posted || "—"}</b></div>
        </div>
        {job.reasons.length > 0 && <p className="small muted">Why: {job.reasons.join(" · ")}</p>}
        {job.deadline && <p className="badge warn">Deadline {job.deadline}</p>}
        {!job.is_open && <p className="badge bad">No longer listed</p>}
        {job.description && <p>{job.description}</p>}

        <div className="btn-row">
          {job.url && <a className="pill dark" href={safeUrl(job.url)} target="_blank" rel="noopener noreferrer">Apply ↗</a>}
          <button className={`pill ${job.status === "saved" ? "dark" : ""}`} onClick={() => mark("saved")}>{job.status === "saved" ? "Saved ★" : "Save"}</button>
          <button className={`pill ${job.status === "applied" ? "dark" : ""}`} onClick={() => mark("applied")}>{job.status === "applied" ? "Applied ✓" : "Mark applied"}</button>
        </div>
        <div className="btn-row">
          <button className="link" disabled={!!busy} onClick={() => run("details", () => api.details(job.id), setD)}>
            {busy === "details" ? "Reading…" : "Read the posting →"}
          </button>
          <button className="link" disabled={!!busy} onClick={() => run("verify", () => api.verify(job.id), setV)}>
            {busy === "verify" ? "Agent checking (≈1 min)…" : "Is it still open? →"}
          </button>
        </div>
        {v && <p className={`badge ${v.open ? "ok" : "bad"}`}>{v.open === null ? "Couldn't verify" : v.open ? "Still accepting applications" : "Closed"}{v.reason ? ` — ${v.reason}` : ""}</p>}
        {d && (
          <div className="panel">
            {d.highlights.map((h, i) => <blockquote key={i}>{h}</blockquote>)}
            {d.excerpt && <pre>{d.excerpt}</pre>}
          </div>
        )}
        <p className="mono small muted foot-note">First seen {ago(job.first_seen)} · last seen {ago(job.last_seen)} · via {job.source_name}</p>
      </aside>
    </>
  );
}

function Hero({ stats, sources, setTab, scanAll, scanning, refresh, setError }) {
  const companies = [...new Set(sources.map((s) => s.name))];
  return (
    <section className="hero">
      <Grid />
      <div className="wrap rel">
        <Eyebrow>Live openings, matched to you</Eyebrow>
        <h1 className="display xl">
          <span>Find the roles</span>
          <span>worth <span className="underline">applying</span> to.</span>
        </h1>
        <div className="hero-row">
          <p className="lead">JobFish pulls fresh postings from company careers pages and job boards, scores each one against your role, location and level, and keeps the list up to date.</p>
          <div className="btn-row">
            {sources.length ? (
              <button className="pill dark lg" disabled={scanning} onClick={scanAll}>{scanning ? "Scanning…" : "Refresh openings"} <span>→</span></button>
            ) : (
              <button className="pill dark lg" onClick={() => setTab("sources")}>Add companies <span>→</span></button>
            )}
            <button className="pill lg" onClick={() => setTab("prefs")}>Tune preferences</button>
          </div>
        </div>
        <div className="hero-search">
          <CompanySearch refresh={refresh} setError={setError} compact
            presets={sources.length ? [] : ["Google", "Razorpay", "Airbnb", "Swiggy", "Notion", "Jane Street"]} />
        </div>
        {stats && (
          <div className="stats">
            {[["open roles", stats.open], ["strong matches", stats.matches], ["new since last scan", stats.new], ["companies", stats.companies]].map(([l, n]) => (
              <div key={l}><b className="display">{fmt(n)}</b><span className="mono">{l}</span></div>
            ))}
          </div>
        )}
      </div>
      {companies.length > 0 && (
        <div className="marquee" aria-hidden>
          <div className="track">
            {[...companies, ...companies, ...companies, ...companies].map((c, i) => <span key={i}>{c}<i>✦</i></span>)}
          </div>
        </div>
      )}
    </section>
  );
}

const STEPS = [
  ["I", "Pick companies", "Add careers pages, or one-click popular companies. Discover finds more with TinyFish Search."],
  ["II", "We fetch", "Public job boards are read directly in seconds; anything else is browsed by the TinyFish agent."],
  ["III", "You apply", "Ranked by your role, location and level. New postings are flagged; closed ones drop off."],
];

export default function Jobs(props) {
  const { jobs, sources, prefs, refresh, setError, setTab } = props;
  const [q, setQ] = useState("");
  const [view, setView] = useState("matches");
  const [level, setLevel] = useState("all");
  const [company, setCompany] = useState("all");
  const [sel, setSel] = useState(null);
  const [limit, setLimit] = useState(PAGE);

  const companies = useMemo(() => [...new Set(jobs.map((j) => j.company))].sort(), [jobs]);
  const shown = useMemo(() => {
    const min = Math.max(prefs?.min_score || 0, 50);
    const t = q.toLowerCase();
    return jobs.filter((j) => {
      if (view === "saved") return j.status === "saved";
      if (view === "applied") return j.status === "applied";
      if (view === "closed") return !j.is_open;
      if (j.status === "hidden" || !j.is_open) return false;
      if (view === "new" && !isNew(j)) return false;
      if (view === "matches" && j.score < min) return false;
      if (level !== "all" && j.seniority !== level) return false;
      if (company !== "all" && j.company !== company) return false;
      return !t || `${j.title} ${j.company} ${j.location}`.toLowerCase().includes(t);
    });
  }, [jobs, q, view, level, company, prefs]);

  const hide = async (e, j) => { e.stopPropagation(); await api.setJobStatus(j.id, "hidden"); refresh(); };
  const save = async (e, j) => { e.stopPropagation(); await api.setJobStatus(j.id, j.status === "saved" ? "none" : "saved"); refresh(); };
  const setV = (v) => { setView(v); setLimit(PAGE); };
  const selected = sel && (jobs.find((j) => j.id === sel) || null);

  return (
    <>
      <Hero {...props} />

      {!sources.length ? (
        <section className="wrap block">
          <SectionHead n="01" eyebrow="How it works" title={<>Three steps. <em>Zero</em> tab-hopping.</>} />
          <div className="cards three">
            {STEPS.map(([n, t, d]) => (
              <div className="card" key={n}><span className="mono num">{n}</span><h3 className="display md">{t}</h3><p className="muted">{d}</p></div>
            ))}
          </div>
          <div className="btn-row center"><button className="pill dark lg" onClick={() => setTab("sources")}>Add your first source →</button></div>
        </section>
      ) : (
        <section className="wrap block" id="openings">
          <SectionHead n="01" eyebrow="Openings" title={<>{fmt(shown.length)} roles, <em>ranked for you.</em></>} />
          <div className="filters">
            <input className="search" placeholder="Search title, company, location…" value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} />
            <select value={company} onChange={(e) => setCompany(e.target.value)}>
              <option value="all">All companies</option>{companies.map((c) => <option key={c}>{c}</option>)}
            </select>
            <select value={level} onChange={(e) => setLevel(e.target.value)}>
              <option value="all">Any level</option>{["intern", "entry", "mid", "senior", "lead"].map((l) => <option key={l}>{l}</option>)}
            </select>
          </div>
          <div className="seg">
            {[["matches", "Best matches"], ["new", "New"], ["all", "All open"], ["saved", "Saved"], ["applied", "Applied"], ["closed", "Closed"]].map(([k, l]) => (
              <button key={k} className={view === k ? "on" : ""} onClick={() => setV(k)}>{l}</button>
            ))}
          </div>

          {shown.length === 0 && (
            <div className="empty">
              <p className="display md">{jobs.length ? "Nothing here yet." : "No openings yet."}</p>
              <p className="muted">{jobs.length ? "Try “All open”, or loosen your preferences." : "Run a scan from Sources to pull live postings."}</p>
            </div>
          )}

          <ol className="rows">
            {shown.slice(0, limit).map((j, i) => (
              <li key={j.id} className="row" onClick={() => setSel(j.id)}>
                <span className="mono idx">{pad(i + 1)}</span>
                <div className="main">
                  <div className="title">{j.title}{isNew(j) && <span className="badge ok">New</span>}{j.status === "applied" && <span className="badge">Applied</span>}</div>
                  <div className="meta">{j.company} · {shortLoc(j.location)} · <span className="mono">{j.seniority}</span>{j.posted ? ` · posted ${j.posted}` : ""}</div>
                </div>
                <div className="score"><b className="display">{j.score}</b><span className="mono">match</span></div>
                <div className="row-actions">
                  <button title="Save" className={j.status === "saved" ? "on" : ""} onClick={(e) => save(e, j)}>★</button>
                  <button title="Hide" onClick={(e) => hide(e, j)}>✕</button>
                </div>
                <span className="arrow">→</span>
              </li>
            ))}
          </ol>
          {shown.length > limit && <div className="btn-row center"><button className="pill" onClick={() => setLimit(limit + PAGE * 2)}>Show more ({fmt(shown.length - limit)} left)</button></div>}
        </section>
      )}
      {selected && <Detail key={selected.id} job={selected} onClose={() => setSel(null)} refresh={refresh} setError={setError} />}
    </>
  );
}
