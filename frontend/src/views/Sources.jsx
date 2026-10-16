import { useEffect, useState } from "react";
import { api, ago, liveScan, safeUrl } from "../api";
import { SectionHead, pad, fmt } from "../components/Ui.jsx";
import CompanySearch from "../components/CompanySearch.jsx";

const EMPTY = { name: "", url: "", kind: "careers", method: "auto", interval_hours: 24, browser_profile: "lite", proxy_country: "", use_vault: false, credential_item_ids: [] };
const EVERY = [[0, "Manual only"], [6, "Every 6 hours"], [12, "Every 12 hours"], [24, "Daily"], [168, "Weekly"]];
const VIA = { greenhouse: "Greenhouse API", lever: "Lever API", ashby: "Ashby API", workable: "Workable API" };
const via = (s) => (s.method === "agent" ? "TinyFish agent" : s.ats && s.ats !== "none" ? VIA[s.ats.split(":")[0]] : s.ats === "none" ? "TinyFish agent" : "auto-detect");

function Form({ initial, onClose, onSaved, setError, vaultEnabled }) {
  const [f, setF] = useState({ ...EMPTY, ...initial, proxy_country: initial.proxy_country || "", use_vault: !!initial.use_vault, method: initial.method || "auto" });
  const [items, setItems] = useState([]);
  const [pv, setPv] = useState(null);
  const [busy, setBusy] = useState(false);
  const up = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  useEffect(() => { if (f.use_vault) api.vault().then((v) => setItems(v.items)).catch(() => {}); }, [f.use_vault]);

  const save = async (scan) => {
    const body = { ...f, interval_hours: Number(f.interval_hours), proxy_country: f.proxy_country || null };
    try {
      const s = initial.id ? await api.editSource(initial.id, body) : await api.addSource(body);
      if (scan) await api.scan(s.id);
      onSaved();
    } catch (e) { setError(e.message); }
  };
  const preview = async () => { setBusy(true); try { setPv(await api.preview(f.url)); } catch (e) { setError(e.message); } setBusy(false); };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <span className="eyebrow"><span className="rule" />{initial.id ? "Edit source" : "New source"}</span>
        <h2 className="display md">{initial.id ? initial.name : "Add a careers page"}</h2>
        <label>Company or board name<input value={f.name} onChange={up("name")} placeholder="Jane Street" /></label>
        <label>Careers page or job portal URL<input value={f.url} onChange={up("url")} placeholder="https://company.com/careers" /></label>
        <div className="grid2">
          <label>How to fetch
            <select value={f.method} onChange={up("method")}>
              <option value="auto">Auto — job-board API, else agent</option>
              <option value="agent">Always use TinyFish agent</option>
            </select>
          </label>
          <label>Auto-refresh<select value={f.interval_hours} onChange={up("interval_hours")}>{EVERY.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label>Page type<select value={f.kind} onChange={up("kind")}><option value="careers">Company careers page</option><option value="portal">Job portal</option></select></label>
          <label>Agent browser<select value={f.browser_profile} onChange={up("browser_profile")}><option value="lite">Lite (fast)</option><option value="stealth">Stealth (anti-bot)</option></select></label>
          <label>Agent proxy<select value={f.proxy_country} onChange={up("proxy_country")}><option value="">None</option>{["US", "GB", "CA", "DE", "FR", "JP", "AU"].map((c) => <option key={c}>{c}</option>)}</select></label>
          {vaultEnabled && <label className="check"><input type="checkbox" checked={f.use_vault} onChange={up("use_vault")} /> Needs login (vault)</label>}
        </div>
        {f.use_vault && (
          <>
            <select multiple value={f.credential_item_ids} onChange={(e) => setF({ ...f, credential_item_ids: [...e.target.selectedOptions].map((o) => o.value) })}>
              {items.map((i) => <option key={i.item_id} value={i.item_id}>{i.label} {i.domains.join(", ")}</option>)}
            </select>
            {!items.length && <p className="small muted">No vault items yet — connect 1Password or Bitwarden in the TinyFish tab.</p>}
          </>
        )}
        {pv && <div className="panel"><b>{pv.title}</b><p className="small muted">{pv.description}</p>{pv.excerpt && <pre>{pv.excerpt.slice(0, 700)}</pre>}</div>}
        <div className="btn-row end">
          <button className="link" disabled={!f.url || busy} onClick={preview}>{busy ? "Fetching…" : "Preview page"}</button>
          <button className="pill" onClick={onClose}>Cancel</button>
          <button className="pill" disabled={!f.name || !f.url} onClick={() => save(false)}>Save</button>
          <button className="pill dark" disabled={!f.name || !f.url} onClick={() => save(true)}>Save & scan</button>
        </div>
      </div>
    </div>
  );
}

function Live({ source, onClose, refresh }) {
  const [log, setLog] = useState([]);
  const [url, setUrl] = useState(null);
  const [done, setDone] = useState(null);
  const [t0] = useState(Date.now());
  const [, tick] = useState(0);

  useEffect(() => {
    const t = setInterval(() => tick((x) => x + 1), 1000);
    liveScan(source.id, (ev) => {
      if (ev.type === "progress") setLog((l) => [...l, ev.message]);
      if (ev.type === "streaming_url") setUrl(ev.url);
      if (ev.type === "complete") setDone(`Found ${ev.found} openings (${ev.new} new)`);
      if (ev.type === "error") setDone("Failed: " + ev.message);
    }).catch((e) => setDone("Failed: " + e.message)).finally(() => { clearInterval(t); refresh(); });
    return () => clearInterval(t);
  }, [source.id]);

  const secs = Math.floor((Date.now() - t0) / 1000);
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="term-head">
          <span className="mono small">agent.stream — {source.name}</span>
          <span className={`badge ${done ? (done.startsWith("Failed") ? "bad" : "ok") : "warn"}`}>{done ? (done.startsWith("Failed") ? "Failed" : "Done") : `Running ${Math.floor(secs / 60)}:${pad(secs % 60)}`}</span>
        </div>
        <ol className="term">
          {log.map((l, i) => <li key={i}><span className="mono muted">{pad(i + 1)}</span>{l}</li>)}
          {!done && <li className="muted"><span className="mono">··</span>Agent is working — this usually takes 2–8 minutes…</li>}
        </ol>
        {done && <p className={done.startsWith("Failed") ? "bad-t" : "ok-t"}>{done}</p>}
        <div className="btn-row end">
          {url && <a className="pill" href={safeUrl(url)} target="_blank" rel="noopener noreferrer">Watch the browser ↗</a>}
          <button className="pill dark" onClick={onClose}>{done ? "Close" : "Run in background"}</button>
        </div>
      </div>
    </div>
  );
}

export default function Sources({ sources, scans, refresh, setError, scanAll, scanning, vaultEnabled }) {
  const [edit, setEdit] = useState(null);
  const [live, setLive] = useState(null);
  const [presets, setPresets] = useState([]);

  useEffect(() => { api.presets().then(setPresets).catch(() => {}); }, [sources.length]);
  const latest = (sid) => scans.find((x) => x.source_id === sid);

  const scan = async (s) => { try { await api.scan(s.id); } catch (e) { setError(e.message); } refresh(); };
  return (
    <section className="wrap block top">
      <SectionHead n="02" eyebrow="Sources" title={<>Where we look. <em>Every day.</em></>}>
        <button className="pill" disabled={!sources.length || scanning} onClick={scanAll}>Refresh all</button>
        <button className="pill dark" onClick={() => setEdit({})}>Add source +</button>
      </SectionHead>

      <CompanySearch refresh={refresh} setError={setError} presets={presets.filter((p) => !p.added).map((p) => p.name).slice(0, 10)} />

      {!sources.length && <div className="empty"><p className="display md">No sources yet.</p><p className="muted">Search for a company above, or paste a careers URL with Add source.</p></div>}

      <div className="cards">
        {sources.map((s, i) => {
          const sc = latest(s.id);
          const running = s.last_status === "running";
          return (
            <div className="card src" key={s.id}>
              <div className="card-top">
                <span className="mono num">{pad(i + 1)}</span>
                <span className={`badge ${running ? "warn" : s.last_status === "failed" ? "bad" : s.last_status ? "ok" : ""}`}>
                  {running && <i className="live-dot" />}{s.last_status || "not scanned"}
                </span>
              </div>
              <h3 className="display md">{s.name}</h3>
              <a className="small muted clip" href={safeUrl(s.url)} target="_blank" rel="noopener noreferrer">{s.url.replace(/^https?:\/\//, "")}</a>
              <div className="kv compact">
                <div><span className="mono">Open roles</span><b className="display">{fmt(s.job_count)}</b></div>
                <div><span className="mono">Scanned</span><b>{ago(s.last_scan_at)}</b></div>
                <div><span className="mono">Via</span><b>{via(s)}</b></div>
                <div><span className="mono">Refresh</span><b>{s.interval_hours ? (s.interval_hours === 24 ? "daily" : s.interval_hours === 168 ? "weekly" : `${s.interval_hours}h`) : "manual"}</b></div>
              </div>
              {sc?.note && <p className={`small ${sc.status === "failed" ? "bad-t" : "muted"}`}>{running && sc.mode === "queue" ? `Agent running for ${ago(sc.started_at).replace(" ago", "")} — ` : ""}{sc.note}{sc.streaming_url && running ? <> · <a href={safeUrl(sc.streaming_url)} target="_blank" rel="noopener noreferrer">watch ↗</a></> : null}</p>}
              <div className="btn-row">
                <button className="pill dark sm" disabled={running} onClick={() => scan(s)}>{running ? "Scanning…" : "Scan now"}</button>
                <button className="pill sm" disabled={running} onClick={() => setLive(s)} title="Stream the TinyFish agent step by step">Live agent</button>
                <button className="link sm" onClick={() => setEdit(s)}>Edit</button>
                <button className="link sm" onClick={async () => { if (confirm(`Remove ${s.name} and its jobs?`)) { await api.deleteSource(s.id); refresh(); } }}>Remove</button>
              </div>
            </div>
          );
        })}
      </div>

      {scans.length > 0 && (
        <div className="block-sm">
          <SectionHead eyebrow="Recent scans" title="Activity log" />
          <ol className="log-table">
            {scans.slice(0, 12).map((x) => (
              <li key={x.id}>
                <span className="mono muted">{ago(x.started_at)}</span>
                <span>{x.source_name}</span>
                <span className={`badge ${x.status === "completed" ? "ok" : x.status === "failed" ? "bad" : x.status === "running" ? "warn" : ""}`}>{x.status}</span>
                <span className="mono small">{x.status === "completed" ? `${fmt(x.jobs_found)} found · ${x.new_jobs} new` : x.mode}</span>
                <span className="small muted clip">{x.note}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {edit && <Form initial={edit} vaultEnabled={vaultEnabled} onClose={() => setEdit(null)} setError={setError} onSaved={() => { setEdit(null); refresh(); }} />}
      {live && <Live source={live} onClose={() => { setLive(null); refresh(); }} refresh={refresh} />}
    </section>
  );
}
