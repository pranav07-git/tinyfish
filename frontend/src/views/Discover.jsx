import { useState } from "react";
import { api, safeUrl } from "../api";
import { SectionHead, pad } from "../components/Ui.jsx";

export default function Discover({ prefs, refresh, setError }) {
  const [q, setQ] = useState(prefs.roles[0] ? `${prefs.roles[0]} careers` : "software engineering internship careers");
  const [loc, setLoc] = useState(prefs.locations[0] || "");
  const [days, setDays] = useState("");
  const [domains, setDomains] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(0);

  const search = async (p = 0) => {
    setBusy(true);
    try {
      setRes(await api.discover({ query: q, location: loc || null, recency_days: days ? Number(days) : null, include_domains: domains || null, page: p }));
      setPage(p);
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  const add = async (r) => {
    try {
      const s = await api.addSource({ name: r.site_name.replace(/^www\./, ""), url: r.url, kind: "portal", interval_hours: 24 });
      api.scan(s.id).catch(() => {});
      setRes({ ...res, results: res.results.map((x) => (x.url === r.url ? { ...x, is_source: true } : x)) });
      refresh();
    } catch (e) { setError(e.message); }
  };

  return (
    <section className="wrap block top">
      <SectionHead n="03" eyebrow="Discover · TinyFish Search" title={<>Find more places <em>to look.</em></>} />
      <form className="searchbar" onSubmit={(e) => { e.preventDefault(); search(); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. data science internship" />
        <button className="pill dark" disabled={busy || !q}>{busy ? "Searching…" : "Search →"}</button>
      </form>
      <div className="filters">
        <input value={loc} onChange={(e) => setLoc(e.target.value)} placeholder="Location" />
        <select value={days} onChange={(e) => setDays(e.target.value)}>
          <option value="">Any time</option><option value="1">Past day</option><option value="7">Past week</option><option value="30">Past month</option>
        </select>
        <input value={domains} onChange={(e) => setDomains(e.target.value)} placeholder="Only these domains (a.com,b.com)" />
      </div>
      {res && (
        <>
          <ol className="rows">
            {res.results.map((r, i) => (
              <li className="row static" key={r.url}>
                <span className="mono idx">{pad(page * 10 + i + 1)}</span>
                <div className="main">
                  <a className="title" href={safeUrl(r.url)} target="_blank" rel="noopener noreferrer">{r.title} ↗</a>
                  <div className="meta"><span className="mono">{r.site_name}</span>{r.date ? ` · ${r.date}` : ""}</div>
                  <p className="small muted snippet">{r.snippet}</p>
                </div>
                <button className={`pill sm ${r.is_source ? "" : "dark"}`} disabled={r.is_source} onClick={() => add(r)}>{r.is_source ? "Added ✓" : "Track +"}</button>
              </li>
            ))}
          </ol>
          {res.results.length === 0 && <div className="empty"><p className="display md">No results.</p></div>}
          <div className="btn-row center">
            <button className="pill" disabled={page === 0 || busy} onClick={() => search(page - 1)}>← Prev</button>
            <span className="mono small muted">Page {page + 1}</span>
            <button className="pill" disabled={busy || !res.results.length} onClick={() => search(page + 1)}>Next →</button>
          </div>
        </>
      )}
    </section>
  );
}
