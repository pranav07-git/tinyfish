import { useEffect, useState } from "react";
import { api, ago, safeUrl } from "../api";
import { SectionHead } from "../components/Ui.jsx";

const ENDPOINTS = [
  ["agent.queue + runs.get", "Background scans of non-ATS careers pages"],
  ["agent.stream", "Live agent view with step-by-step progress"],
  ["agent.run", "“Is it still open?” check on a posting"],
  ["fetch.get_contents", "Change detection, board detection, posting reader"],
  ["search.query", "Discover new careers pages and job boards"],
  ["runs.list", "Run history below"],
  ["browser.sessions.create", "Remote browser for your own Playwright scripts"],
  ["vault.*", "Credentials for login-only portals"],
  ["wallet.get", "Balance and rates"],
];

function Runs({ setError }) {
  const [runs, setRuns] = useState([]);
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState(null);
  useEffect(() => { api.tfRuns(status).then((r) => setRuns(r.data)).catch((e) => setError(e.message)); }, [status]);
  const show = async (id) => { try { setOpen(await api.tfRun(id)); } catch (e) { setError(e.message); } };
  return (
    <div className="card wide">
      <div className="card-top">
        <h3 className="display md">Agent runs</h3>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All</option>{["RUNNING", "COMPLETED", "FAILED", "CANCELLED"].map((s) => <option key={s}>{s}</option>)}
        </select>
      </div>
      <ol className="log-table">
        {runs.map((r) => (
          <li key={r.run_id} className="click" onClick={() => show(r.run_id)}>
            <span className="mono muted">{ago(r.created_at)}</span>
            <span className={`badge ${r.status === "COMPLETED" ? "ok" : r.status === "FAILED" ? "bad" : r.status === "RUNNING" ? "warn" : ""}`}>{r.status.toLowerCase()}</span>
            <span className="small clip">{r.goal}</span>
          </li>
        ))}
        {!runs.length && <li className="muted">No runs.</li>}
      </ol>
      {open && (
        <div className="panel">
          <div className="card-top"><span className="mono small">{open.run_id}</span><button className="link" onClick={() => setOpen(null)}>Close</button></div>
          {open.streaming_url && <p><a href={safeUrl(open.streaming_url)} target="_blank" rel="noopener noreferrer">Session replay ↗</a></p>}
          {open.error && <p className="bad-t">{open.error.message}</p>}
          <pre>{JSON.stringify(open.result, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

function Vault({ setError, enabled }) {
  const [v, setV] = useState({ connections: [], items: [] });
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => api.vault().then(setV).catch((e) => setError(e.message));
  useEffect(() => { if (enabled) load(); }, [enabled]);
  const up = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const connect = async () => {
    setBusy(true);
    try { await api.vaultConnect(form); setForm(null); load(); } catch (e) { setError(e.message); }
    setBusy(false);
  };
  const disconnect = async (c) => {
    const pw = prompt(`Re-enter your JobFish password to disconnect ${c.provider}:`);
    if (!pw) return;
    try { await api.vaultDisconnect(c.id, pw); load(); } catch (e) { setError(e.message); }
  };

  if (!enabled)
    return (
      <div className="card">
        <div className="card-top"><h3 className="display md">Vault</h3><span className="badge">disabled</span></div>
        <p className="small muted">Credential vaults (1Password, Bitwarden) let the agent log in to portals. It's off on this server; the owner can turn it on with <code>ENABLE_VAULT=1</code>.</p>
      </div>
    );

  return (
    <div className="card">
      <div className="card-top"><h3 className="display md">Vault</h3><span className={`badge ${v.connections.length ? "ok" : ""}`}>{v.connections.length ? "connected" : "not connected"}</span></div>
      <p className="small muted">For portals that need a login. Secrets go straight to TinyFish and are never stored by JobFish. Changes need your password.</p>
      {v.connections.map((c) => (
        <div className="card-top" key={c.id}><span>{c.provider} · <span className="mono small">{c.connection_status}</span></span>
          <button className="link" onClick={() => disconnect(c)}>Disconnect</button></div>
      ))}
      {v.items.length > 0 && <p className="small">{v.items.length} credentials: {v.items.map((i) => i.label).join(", ")}</p>}
      {form ? (
        <form className="panel" autoComplete="off" onSubmit={(e) => { e.preventDefault(); connect(); }}>
          <select value={form.provider} onChange={up("provider")}><option value="1password">1Password</option><option value="bitwarden">Bitwarden</option></select>
          {form.provider === "1password" ? <input type="password" autoComplete="off" placeholder="Service account token (ops_…)" onChange={up("token")} /> : (
            <>
              <input autoComplete="off" placeholder="Client ID" onChange={up("client_id")} />
              <input type="password" autoComplete="off" placeholder="Client secret" onChange={up("client_secret")} />
              <input type="password" autoComplete="off" placeholder="Master password" onChange={up("master_password")} />
              <input placeholder="Server URL (optional)" onChange={up("server_url")} />
            </>
          )}
          <input type="password" autoComplete="current-password" placeholder="Your JobFish password (to confirm)" onChange={up("confirm_password")} />
          <div className="btn-row end"><button type="button" className="pill sm" onClick={() => setForm(null)}>Cancel</button><button className="pill dark sm" disabled={busy || !form.confirm_password}>{busy ? "Connecting…" : "Connect"}</button></div>
        </form>
      ) : (
        <div className="btn-row">
          <button className="pill sm" onClick={() => setForm({ provider: "1password" })}>Connect</button>
          <button className="link sm" onClick={() => api.vaultSync().then(load).catch((e) => setError(e.message))}>Sync items</button>
        </div>
      )}
    </div>
  );
}

function Browser({ setError }) {
  const [url, setUrl] = useState("");
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const open = async () => { setBusy(true); setCopied(false); try { setS(await api.browser(url || null)); } catch (e) { setError(e.message); } setBusy(false); };
  const copy = async () => { await navigator.clipboard.writeText(s.cdp_url); setCopied(true); };
  return (
    <div className="card">
      <div className="card-top"><h3 className="display md">Remote browser</h3><span className="badge">developers</span></div>
      <p className="small muted">Starts a cloud Chrome you control from your own code (Playwright, Puppeteer). It isn't a page you can watch. To see what the agent sees, use <b>Live agent</b> on a source.</p>
      <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Start at https://… (optional)" />
      <div className="btn-row"><button className="pill sm" disabled={busy} onClick={open}>{busy ? "Starting…" : "Start session"}</button></div>
      {s && (
        <div className="panel small">
          <div className="card-top"><span className="mono">CDP URL</span><button className="link sm" onClick={copy}>{copied ? "Copied ✓" : "Copy"}</button></div>
          <code>{s.cdp_url}</code>
          <pre>{`browser = playwright.chromium.connect_over_cdp(CDP_URL)\npage = browser.contexts[0].new_page()\npage.goto("https://…")`}</pre>
          <p className="bad-t">Treat this URL like a password: anyone with it can control the browser until it times out (5 min idle).</p>
        </div>
      )}
    </div>
  );
}

export default function TinyFishPanel({ wallet, setError, vaultEnabled }) {
  return (
    <section className="wrap block top">
      <SectionHead n="05" eyebrow="TinyFish" title={<>Under the hood. <em>Every endpoint.</em></>} />
      <div className="cards">
        <div className="card">
          <div className="card-top"><h3 className="display md">Wallet</h3><span className="badge ok"><i className="dot ok" /> live</span></div>
          {wallet ? (
            <>
              <b className="display xl-num">${Number(wallet.available_balance).toFixed(2)}</b>
              <p className="mono small muted">{wallet.currency} · as of {ago(wallet.as_of)}</p>
              <ol className="meters">{wallet.rates?.meters.map((m) => <li key={m.label}><span>{m.label}</span><span className="mono">${m.unit_amount}/{m.per}</span></li>)}</ol>
            </>
          ) : <p className="muted">Unavailable.</p>}
        </div>
        <div className="card">
          <div className="card-top"><h3 className="display md">Endpoints in use</h3><span className="mono small muted">{ENDPOINTS.length}</span></div>
          <ol className="meters">{ENDPOINTS.map(([e, d]) => <li key={e}><span className="mono small">{e}</span><span className="small muted right">{d}</span></li>)}</ol>
        </div>
        <Vault setError={setError} enabled={vaultEnabled} />
        <Browser setError={setError} />
      </div>
      <div className="block-sm"><Runs setError={setError} /></div>
    </section>
  );
}
