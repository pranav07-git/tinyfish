import { useCallback, useEffect, useState } from "react";
import { api, setUnauthorizedHandler } from "./api";
import Login from "./views/Login.jsx";
import Jobs from "./views/Jobs.jsx";
import Sources from "./views/Sources.jsx";
import Discover from "./views/Discover.jsx";
import Preferences from "./views/Preferences.jsx";
import TinyFishPanel from "./views/TinyFishPanel.jsx";

const TABS = [
  ["jobs", "Openings"],
  ["sources", "Sources"],
  ["discover", "Discover"],
  ["prefs", "Preferences"],
  ["tinyfish", "TinyFish"],
];

export default function App() {
  const [auth, setAuth] = useState(null); // null = checking, false = signed out, {vault_enabled}
  useEffect(() => {
    setUnauthorizedHandler(() => setAuth(false));
    api.me().then((m) => setAuth(m.authenticated ? m : false)).catch(() => setAuth(false));
  }, []);

  if (auth === null) return <div className="page noise" />;
  if (!auth) return <Login onDone={() => api.me().then((m) => setAuth(m.authenticated ? m : false))} />;
  return <Workspace auth={auth} onSignOut={async () => { await api.logout().catch(() => {}); setAuth(false); }} />;
}

function Workspace({ auth, onSignOut }) {
  const [tab, setTab] = useState(() => {
    const h = window.location.hash.slice(1);
    return TABS.some(([k]) => k === h) ? h : "jobs";
  });
  const [jobs, setJobs] = useState([]);
  const [sources, setSources] = useState([]);
  const [scans, setScans] = useState([]);
  const [stats, setStats] = useState(null);
  const [prefs, setPrefs] = useState(null);
  const [wallet, setWallet] = useState(null);
  const [error, setError] = useState("");
  const [menu, setMenu] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [j, s, p, st, sc] = await Promise.all([api.jobs(), api.sources(), api.prefs(), api.stats(), api.scans()]);
      setJobs(j); setSources(s); setPrefs(p); setStats(st); setScans(sc);
    } catch (e) { setError(e.message); }
  }, []);

  useEffect(() => { refresh(); api.wallet().then(setWallet).catch(() => {}); }, [refresh]);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 24);
    window.addEventListener("scroll", on);
    return () => window.removeEventListener("scroll", on);
  }, []);
  const scanning = sources.some((s) => s.last_status === "running");
  useEffect(() => {
    if (!scanning) return;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [scanning, refresh]);

  const scanAll = async () => {
    await Promise.all(sources.map((s) => api.scan(s.id, false).catch(() => {})));
    refresh();
  };
  const go = (t) => { setTab(t); setMenu(false); window.location.hash = t === "jobs" ? "" : t; window.scrollTo({ top: 0 }); };
  const ctx = { jobs, sources, scans, stats, prefs, refresh, setError, setTab: go, scanAll, scanning, vaultEnabled: auth.vault_enabled };

  return (
    <div className="page noise">
      <header className={scrolled ? "scrolled" : ""}>
        <div className="bar">
          <button className="logo" onClick={() => go("jobs")}>
            JobFish<sup>™</sup>
          </button>
          <nav className="links">
            {TABS.map(([k, label]) => (
              <button key={k} className={tab === k ? "on" : ""} onClick={() => go(k)}>
                {label}
                {k === "sources" && scanning && <i className="live-dot" />}
              </button>
            ))}
          </nav>
          <div className="actions">
            {wallet && <span className="mono muted small" title="TinyFish wallet">${Number(wallet.available_balance).toFixed(2)}</span>}
            <button className="pill dark sm" disabled={!sources.length || scanning} onClick={scanAll}>
              {scanning ? "Scanning…" : "Refresh all"}
            </button>
            <button className="link sm" onClick={onSignOut} title="Signs out on every device">Sign out</button>
          </div>
          <button className="burger" onClick={() => setMenu(!menu)} aria-label="Menu">{menu ? "✕" : "☰"}</button>
        </div>
      </header>
      {menu && (
        <div className="sheet">
          {TABS.map(([k, label]) => <button key={k} onClick={() => go(k)}>{label}</button>)}
          <button onClick={onSignOut}>Sign out</button>
        </div>
      )}

      {error && <div className="toast" onClick={() => setError("")}><span className="mono">ERROR</span> {error} <span className="muted">· dismiss</span></div>}

      <main>
        {tab === "jobs" && prefs && <Jobs {...ctx} />}
        {tab === "sources" && <Sources {...ctx} />}
        {tab === "discover" && prefs && <Discover {...ctx} />}
        {tab === "prefs" && prefs && <Preferences {...ctx} />}
        {tab === "tinyfish" && <TinyFishPanel {...ctx} wallet={wallet} vaultEnabled={auth.vault_enabled} />}
      </main>

      <footer>
        <div className="wrap foot">
          <div>
            <div className="logo">JobFish<sup>™</sup></div>
            <p className="muted small">Live openings from careers pages and job boards, matched to you.<br />Powered by TinyFish · Built at “AI That Clicks.”, TinyFish × Team Technojam.</p>
          </div>
          <div className="mono small muted status">
            <i className={`dot ${scanning ? "warn" : "ok"}`} /> {scanning ? "Scan in progress" : "Worker idle · auto-refresh on"}
          </div>
        </div>
      </footer>
    </div>
  );
}
