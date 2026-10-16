import { useState } from "react";
import { api, safeUrl } from "../api";
import { fmt } from "./Ui.jsx";

const PROVIDER = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", workable: "Workable" };

function describe(r) {
  if (r.kind === "board") return { label: `${PROVIDER[r.provider]} job board${r.count ? ` · ${fmt(r.count)} open roles` : ""}`, speed: "Fetched in seconds", tone: "ok" };
  if (r.kind === "careers") return { label: "Official careers page", speed: "TinyFish agent · a few minutes", tone: "warn" };
  return { label: r.site || "Web result", speed: "TinyFish agent · a few minutes", tone: "" };
}

/** Search any company by name and start tracking where it posts jobs. */
export default function CompanySearch({ refresh, setError, presets = [], compact = false }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(null);

  const search = async (term = q) => {
    if (term.trim().length < 2) return;
    setQ(term); setBusy(true); setRes(null);
    try { setRes(await api.companySearch(term)); } catch (e) { setError(e.message); }
    setBusy(false);
  };

  const track = async (r) => {
    setAdding(r.url);
    try {
      const s = await api.addSource({ name: r.name, url: r.url, kind: r.kind === "web" ? "portal" : "careers", interval_hours: 24 });
      await api.scan(s.id);
      setRes((list) => list.map((x) => (x.url === r.url ? { ...x, added: true } : x)));
      refresh();
    } catch (e) { setError(e.message); }
    setAdding(null);
  };

  return (
    <div className={`company-search ${compact ? "compact" : ""}`}>
      <form className="searchbar big" onSubmit={(e) => { e.preventDefault(); search(); }}>
        <span className="mono muted">⌕</span>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search any company — Google, Razorpay, Swiggy, Notion…" />
        <button className="pill dark" disabled={busy || q.trim().length < 2}>{busy ? "Searching…" : "Find jobs →"}</button>
      </form>

      {!res && !busy && presets.length > 0 && (
        <div className="presets">
          <span className="mono small muted">Try →</span>
          {presets.map((p) => <button key={p} className="chip-btn" onClick={() => search(p)}>{p}</button>)}
        </div>
      )}

      {busy && <p className="mono small muted searching">Checking Greenhouse, Lever, Ashby, Workable and searching the web for “{q}”…</p>}

      {res && (
        <div className="results">
          {res.length === 0 && <p className="muted">No careers page found for “{q}”. Paste its URL with <b>Add source</b> instead.</p>}
          {res.map((r) => {
            const d = describe(r);
            return (
              <div className="result" key={r.url}>
                <div className="main">
                  <div className="title">{r.name} <span className={`badge ${d.tone}`}>{d.label}</span></div>
                  <a className="small muted clip" href={safeUrl(r.url)} target="_blank" rel="noopener noreferrer">{r.url.replace(/^https?:\/\//, "")}</a>
                  <div className="mono small muted">{d.speed}</div>
                </div>
                <button className={`pill sm ${r.added ? "" : "dark"}`} disabled={r.added || adding === r.url} onClick={() => track(r)}>
                  {r.added ? "Tracking ✓" : adding === r.url ? "Adding…" : "Track +"}
                </button>
              </div>
            );
          })}
          {res.length > 0 && <button className="link sm" onClick={() => { setRes(null); setQ(""); }}>Clear results</button>}
        </div>
      )}
    </div>
  );
}
