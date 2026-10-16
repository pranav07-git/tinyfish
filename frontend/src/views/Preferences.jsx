import { useState } from "react";
import { api } from "../api";
import { SectionHead } from "../components/Ui.jsx";

const LEVELS = [["intern", "Internship"], ["entry", "Entry / New grad"], ["mid", "Mid-level"], ["senior", "Senior"], ["lead", "Lead+"]];

function Tags({ n, label, hint, value, onChange, placeholder }) {
  const [t, setT] = useState("");
  const add = () => { const v = t.trim(); if (v && !value.includes(v)) onChange([...value, v]); setT(""); };
  return (
    <div className="pref">
      <div className="pref-label"><span className="mono num">{n}</span><div><h3>{label}</h3><p className="small muted">{hint}</p></div></div>
      <div className="tags">
        {value.map((v) => <span className="tag" key={v}>{v}<button onClick={() => onChange(value.filter((x) => x !== v))}>×</button></span>)}
        <input value={t} placeholder={placeholder} onChange={(e) => setT(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); } }} onBlur={add} />
      </div>
    </div>
  );
}

export default function Preferences({ prefs, refresh, setError, setTab }) {
  const [p, setP] = useState(prefs);
  const [saved, setSaved] = useState(false);
  const save = async () => {
    try { await api.savePrefs(p); await refresh(); setSaved(true); setTimeout(() => setSaved(false), 1500); } catch (e) { setError(e.message); }
  };
  return (
    <section className="wrap block top narrow">
      <SectionHead n="04" eyebrow="Preferences" title={<>What are you <em>looking for?</em></>} />
      <p className="lead">Every opening is scored 0–100 against this. Saving re-scores everything instantly; no new scan needed.</p>
      <Tags n="01" label="Roles" hint="Job titles you'd apply for." value={p.roles} onChange={(roles) => setP({ ...p, roles })} placeholder="software engineer intern… ⏎" />
      <Tags n="02" label="Locations" hint="Cities or countries." value={p.locations} onChange={(locations) => setP({ ...p, locations })} placeholder="Bangalore, London… ⏎" />
      <div className="pref">
        <div className="pref-label"><span className="mono num">03</span><div><h3>Seniority</h3><p className="small muted">Pick one or more.</p></div></div>
        <div>
        <div className="btn-row">
          {LEVELS.map(([k, l]) => (
            <button key={k} className={`pill sm ${p.seniority.includes(k) ? "dark" : ""}`}
              onClick={() => setP({ ...p, seniority: p.seniority.includes(k) ? p.seniority.filter((x) => x !== k) : [...p.seniority, k] })}>{l}</button>
          ))}
        </div>
        <label className="check"><input type="checkbox" checked={p.remote_ok} onChange={(e) => setP({ ...p, remote_ok: e.target.checked })} /> Remote roles count as a location match</label>
        </div>
      </div>
      <Tags n="04" label="Exclude" hint="Hide anything mentioning these words." value={p.exclude} onChange={(exclude) => setP({ ...p, exclude })} placeholder="unpaid, sales… ⏎" />
      <div className="pref">
        <div className="pref-label"><span className="mono num">05</span><div><h3>Best-match threshold</h3><p className="small muted">Minimum score shown under “Best matches” (at least 50).</p></div></div>
        <div className="range"><input type="range" min="0" max="90" step="10" value={p.min_score} onChange={(e) => setP({ ...p, min_score: Number(e.target.value) })} /><b className="display">{Math.max(p.min_score, 50)}</b></div>
      </div>
      <div className="btn-row">
        <button className="pill dark lg" onClick={save}>{saved ? "Saved ✓" : "Save preferences"}</button>
        <button className="pill lg" onClick={() => setTab("jobs")}>See matches →</button>
      </div>
    </section>
  );
}
