// Every request carries this header; the server rejects state-changing requests without it (CSRF).
const HEADERS = { "Content-Type": "application/json", "X-Jobfish": "1" };
let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

async function req(path, opts = {}) {
  const res = await fetch("/api" + path, {
    headers: HEADERS,
    credentials: "same-origin",
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && !path.startsWith("/auth/")) onUnauthorized();
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    const detail = Array.isArray(e.detail) ? e.detail.map((d) => d.msg.replace(/^Value error, /, "")).join("; ") : e.detail;
    throw new Error(typeof detail === "string" ? detail : res.statusText);
  }
  return res.json();
}
const post = (p, body) => req(p, { method: "POST", body });

export const api = {
  me: () => req("/auth/me"),
  login: (password) => post("/auth/login", { password }),
  logout: () => post("/auth/logout"),
  prefs: () => req("/prefs"),
  stats: () => req("/stats"),
  presets: () => req("/presets"),
  companySearch: (q) => req(`/companies/search?q=${encodeURIComponent(q)}`),
  savePrefs: (b) => req("/prefs", { method: "PUT", body: b }),
  sources: () => req("/sources"),
  addSource: (b) => post("/sources", b),
  editSource: (id, b) => req(`/sources/${id}`, { method: "PUT", body: b }),
  deleteSource: (id) => req(`/sources/${id}`, { method: "DELETE" }),
  scan: (id, force = true) => post(`/sources/${id}/scan?force=${force}`),
  scans: () => req("/scans"),
  jobs: () => req("/jobs"),
  setJobStatus: (id, status) => req(`/jobs/${id}`, { method: "PATCH", body: { status } }),
  verify: (id) => post(`/jobs/${id}/verify`),
  details: (id) => req(`/jobs/${id}/details`),
  discover: (b) => post("/discover", b),
  preview: (url) => post("/preview", { url }),
  tfRuns: (status) => req(`/tf/runs${status ? `?status=${status}` : ""}`),
  tfRun: (id) => req(`/tf/runs/${id}`),
  browser: (url) => post("/tf/browser", { url }),
  wallet: () => req("/tf/wallet"),
  vault: () => req("/tf/vault"),
  vaultConnect: (b) => post("/tf/vault/connect", b),
  vaultSync: () => post("/tf/vault/sync"),
  vaultDisconnect: (id, confirm_password) => post(`/tf/vault/connections/${encodeURIComponent(id)}/disconnect`, { confirm_password }),
};

// Live scan: Agent stream proxied as server-sent events.
export async function liveScan(id, onEvent) {
  const res = await fetch(`/api/sources/${id}/live-scan`, { method: "POST", headers: HEADERS, credentials: "same-origin" });
  if (res.status === 401) onUnauthorized();
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(typeof e.detail === "string" ? e.detail : res.statusText);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop();
    for (const p of parts) if (p.startsWith("data: ")) onEvent(JSON.parse(p.slice(6)));
  }
}

export const ago = (iso) => {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
};

// Only ever render http(s) links from scraped data; anything else (javascript:, data:) becomes inert.
export const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : undefined);
