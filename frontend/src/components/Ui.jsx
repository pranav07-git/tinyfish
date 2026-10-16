export const Eyebrow = ({ children }) => (
  <span className="eyebrow"><span className="rule" />{children}</span>
);

export const SectionHead = ({ n, eyebrow, title, children }) => (
  <div className="section-head">
    <Eyebrow>{n ? `${n} — ` : ""}{eyebrow}</Eyebrow>
    <div className="section-row">
      <h2 className="display">{title}</h2>
      {children && <div className="section-actions">{children}</div>}
    </div>
  </div>
);

export const Grid = () => (
  <div className="gridlines" aria-hidden>
    {Array.from({ length: 8 }, (_, i) => <span key={"h" + i} className="h" style={{ top: `${(i + 1) * 12.5}%` }} />)}
    {Array.from({ length: 12 }, (_, i) => <span key={"v" + i} className="v" style={{ left: `${(i + 1) * 8.33}%` }} />)}
  </div>
);

export const pad = (n) => String(n).padStart(2, "0");
export const fmt = (n) => (n ?? 0).toLocaleString();
