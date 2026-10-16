import { useState } from "react";
import { api } from "../api";
import { Eyebrow, Grid } from "../components/Ui.jsx";

export default function Login({ onDone }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try { await api.login(pw); onDone(); } catch (e2) { setErr(e2.message); setPw(""); }
    setBusy(false);
  };

  return (
    <div className="page noise">
      <section className="hero login">
        <Grid />
        <div className="wrap rel">
          <div className="logo static">JobFish<sup>™</sup></div>
          <Eyebrow>Private workspace</Eyebrow>
          <h1 className="display xl"><span>Welcome</span><span><span className="underline">back.</span></span></h1>
          <form className="searchbar big login-form" onSubmit={submit}>
            <span className="mono muted">⚿</span>
            <input type="password" autoFocus autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Password" aria-label="Password" />
            <button className="pill dark" disabled={busy || !pw}>{busy ? "Signing in…" : "Sign in →"}</button>
          </form>
          {err && <p className="bad-t mono small">{err}</p>}
          <p className="muted small">This instance spends its owner's TinyFish credit, so it's password-protected.</p>
        </div>
      </section>
    </div>
  );
}
