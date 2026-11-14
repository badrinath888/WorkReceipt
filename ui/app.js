"use strict";
const TOKEN = document.querySelector('meta[name=wr-token]').content;
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const I = {
  grid: '<path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/>', folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  doc: '<path d="M7 3h8l4 4v14H7z"/><path d="M15 3v4h4M10 12h6M10 16h6"/>', shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
  dl: '<path d="M12 4v10M8 10l4 4 4-4M5 19h14"/>', arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>', plus: '<path d="M12 5v14M5 12h14"/>',
  chart: '<path d="M4 19V5M4 19h16M8 15v-4M12 15V8M16 15v-6"/>', clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  git: '<circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="12" r="2"/><path d="M6 8v8M8 6c6 0 8 2 8 6"/>', check: '<path d="M5 12l5 5 9-10"/>'
};
const ic = (n, s = 14) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${I[n]}</svg>`;
const TABS = [["overview", "Overview"], ["projects", "Projects"], ["studio", "Report Studio"], ["privacy", "Privacy Center"], ["settings", "Settings"]];
const ICON = { overview: "grid", projects: "folder", studio: "doc", privacy: "shield", settings: "gear" };

const S = { tab: "", data: null, repo: "", since: "", until: "", client: "", author: "", gitAuthor: "", terms: [], prev: null,
  titles: {}, approved: new Set(), loading: false, err: "", html: null, exporting: false, lastExport: null, repoDraft: null };

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "X-WR-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok && r.status !== 409) throw new Error(j.error || `Request failed (${r.status})`);
  return Object.assign(j, { _status: r.status });
}
function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("on"), 3200); }
const opts = () => ({ repo: S.repo, since: S.since, until: S.until, client: S.client, author: S.author, git_author: S.gitAuthor, terms: S.terms });
const highF = () => (S.prev ? S.prev.findings.filter(f => f.severity === "high") : []);
const pendingHigh = () => highF().filter(f => !S.approved.has(f.id));
const today = () => new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
const iso = d => { const z = new Date(d.getTime() - d.getTimezoneOffset() * 6e4); return z.toISOString().slice(0, 10); };
const proj = () => (S.data?.projects || []).find(p => p.path === S.repo);
const pname = () => proj()?.name || (S.repo ? S.repo.split(/[\\/]/).filter(Boolean).pop() : "");

function applyTheme() {
  const t = S.data?.settings.theme || "system";
  const dark = t === "dark" || (t === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}
function go(id) {
  const el = id === "top" ? document.body : document.getElementById(id); if (!el) return;
  const rm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (id === "top") scrollTo({ top: 0, behavior: rm ? "auto" : "smooth" }); else el.scrollIntoView({ behavior: rm ? "auto" : "smooth", block: "start" });
  history.replaceState(null, "", id === "top" ? location.pathname : "#" + id);
}

const cache = {};
function setHTML(el, html) { if (cache[el.id] !== html) { cache[el.id] = html; el.innerHTML = html; } }
function renderChrome() {
  const hp = pendingHigh().length;
  setHTML($("#tabs"), TABS.map(([k, l]) => `<button class="tab" data-go="${k}" ${S.tab === k ? 'aria-current="true"' : ""}>${l}${k === "privacy" && hp ? `<span class="dot">${hp}</span>` : ""}</button>`).join(""));
  $("#tabs .tab[aria-current]")?.scrollIntoView({ inline: "center", block: "nearest" });
}

/* ---------- Overview ---------- */
function spark(vals, color) {
  const max = Math.max(1, ...vals), w = 120, h = 26, n = vals.length;
  const pts = vals.map((v, i) => `${(i / Math.max(1, n - 1) * w).toFixed(1)},${(h - 2 - v / max * (h - 4)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round" points="${pts}"/></svg>`;
}
function vOverview() {
  const d = S.data, ps = d.projects, hist = d.history, wk = d.weekly, sess = ps.reduce((a, p) => a + p.sessions, 0);
  const max = Math.max(1, ...wk.map(x => x.n)), thisWeek = wk[wk.length - 1].n, lastWeek = wk[wk.length - 2]?.n || 0;
  const hp = pendingHigh().length;
  const noDir = !d.claude_dir_ok;
  return `<div><div class="ph"><div><h2>Overview <span class="chip">${today()}</span></h2><p>Your projects, recent Claude Code activity and exported reports.</p></div>
    <div class="act"><button class="btn dark" data-go="projects">${ic("plus")} New report</button></div></div>
  ${noDir ? `<div class="callout err"><div><b>Claude Code folder not found.</b> No <span class="mono">projects</span> folder at <span class="mono">${esc(d.settings.claude_dir)}</span>. Set the correct location in Settings.</div></div>` : ""}
  <div class="grid g4">
    <div class="card stat"><div class="k">Projects ${ic("folder", 13)}</div><div class="v">${ps.length}</div><div class="d">${ps.filter(p => p.git).length} with Git history</div></div>
    <div class="card stat"><div class="k">Sessions ${ic("chart", 13)}</div><div class="v">${sess}</div><div class="d">${thisWeek} this week${lastWeek ? ` · ${thisWeek >= lastWeek ? '<span class="up">▲' : '<span class="down">▼'} ${Math.abs(thisWeek - lastWeek)} vs last</span>` : ""}</div>${spark(wk.map(x => x.n), "#f26a21")}</div>
    <div class="card stat"><div class="k">Reports exported ${ic("doc", 13)}</div><div class="v">${hist.length}</div><div class="d">${hist[0] ? "Last " + esc(hist[0].at) : "None yet"}</div></div>
    <div class="card stat"><div class="k">Latest activity ${ic("clock", 13)}</div><div class="v" style="font-size:18px;margin-top:10px">${ps[0] ? esc(ps[0].last.slice(0, 10)) : "—"}</div><div class="d">${ps[0] ? esc(ps[0].name) : "No sessions found"}</div></div>
  </div>
  <div class="grid g2 sec"><div class="card"><h3>Session activity <span class="chip">Last 12 weeks</span></h3>
    ${sess ? `<div class="bars">${wk.map((x, i) => `<div class="col ${i === wk.length - 1 ? "hot" : ""}" title="${x.n} session file(s), week of ${esc(x.label)}"><span class="val">${x.n || ""}</span><div class="bar" style="height:${Math.max(2, x.n / max * 100)}%"></div></div>`).join("")}</div><div class="xl">${wk.map(x => `<span>${esc(x.label.split(" ")[1] || "")}</span>`).join("")}</div><p class="note" style="margin-top:8px">Counts session files by last-modified week. Weeks start Monday.</p>` : `<div class="empty"><b>No sessions yet</b>Run Claude Code in a project and it will appear here.</div>`}</div>
  <div class="card"><h3>Needs attention <span class="chip">${hp ? hp + " open" : "clear"}</span></h3>
    ${S.prev ? (hp ? `<p style="font-size:20px;font-weight:600;letter-spacing:-.02em">${hp} high-severity</p><p class="note">masked value${hp > 1 ? "s" : ""} in <b>${esc(pname())}</b> need your review before export.</p><button class="linkbtn" data-go="privacy">Review findings ${ic("arrow")}</button>` :
      `<p style="font-size:20px;font-weight:600;letter-spacing:-.02em">All reviewed</p><p class="note">${S.prev.findings.length} masked value(s) in the loaded report${highF().length ? ", every high-severity one reviewed" : ""}.</p><button class="linkbtn" data-go="studio">Open Report Studio ${ic("arrow")}</button>`) :
      `<p class="note">Load a project's activity to scan it for secrets. Nothing is checked until you do.</p><button class="linkbtn" data-go="projects">Choose a project ${ic("arrow")}</button>`}
    ${ps.filter(p => p.exists && !p.git).slice(0, 2).map(p => `<div class="row"><div class="grow"><div class="t">${esc(p.name)}</div><div class="s">Not a Git repository — report would have no delivered changes</div></div></div>`).join("")}</div></div>
  <div class="card sec"><h3>Recent reports <span class="chip">${hist.length}</span></h3>
    ${hist.length ? `<table class="tbl"><thead><tr><th>Project</th><th>Period</th><th class="hide-m">Requests</th><th class="hide-m">Commits</th><th>Exported</th><th></th></tr></thead><tbody>${hist.slice(0, 6).map(h => `<tr><td><b style="font-weight:500">${esc(h.project)}</b></td><td class="mono">${esc(h.period)}</td><td class="hide-m">${h.requests}</td><td class="hide-m">${h.commits}</td><td>${esc(h.at)}</td><td style="text-align:right"><a class="btn sm" target="_blank" rel="noopener" href="/report/${encodeURIComponent(h.html.split(/[\\/]/).pop())}">Open</a></td></tr>`).join("")}</tbody></table>` : `<div class="empty"><b>No reports yet</b>Pick a project, load its activity and export your first report.<br><button class="btn dark" data-go="projects">Choose a project</button></div>`}</div></div>`;
}

/* ---------- Projects ---------- */
function vProjects() {
  const d = S.data, ps = d.projects;
  const p = proj();
  return `<div><div class="ph"><div><h2>Projects <span class="chip">${ps.length} found</span></h2><p>Choose a repository and the period to report on.</p></div></div>
  <div class="card"><h3>Claude Code projects</h3>${ps.length ? `<table class="tbl"><thead><tr><th>Project</th><th class="hide-m">Folder</th><th>Sessions</th><th class="hide-m">Last activity</th><th>Git</th></tr></thead><tbody>${ps.map(x => `<tr class="click" data-pick="${esc(x.path)}" ${x.path === S.repo ? 'style="background:var(--teal-soft)"' : ""}><td><b style="font-weight:500">${esc(x.name)}</b></td><td class="mono hide-m" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(x.path)}</td><td>${x.sessions}</td><td class="hide-m">${esc(x.last)}</td><td>${!x.exists ? '<span class="badge bad">folder missing</span>' : x.git ? '<span class="badge ok">Git</span>' : '<span class="badge">no Git</span>'}</td></tr>`).join("")}</tbody></table>` :
    `<div class="empty"><b>${d.claude_dir_ok ? "No sessions found" : "Claude Code folder not found"}</b>${d.claude_dir_ok ? "Claude Code has not recorded sessions in this location yet." : "Check the location in Settings."}<br><button class="btn" data-go="settings">Open Settings</button></div>`}
  <div class="grid sec" style="grid-template-columns:1fr auto;align-items:end"><label class="field">Or enter a repository folder
    <input id="repo" value="${esc(S.repoDraft ?? S.repo)}" placeholder="/Users/you/projects/client-site" spellcheck="false"></label><button class="btn" id="usepath">Use this folder</button></div></div>
  <div class="card sec"><h3>Period &amp; filters ${p ? `<span class="chip">${esc(p.name)}</span>` : ""}</h3>
    <div class="pill-row" style="margin-bottom:12px">${[["Last 7 days", 7], ["Last 30 days", 30], ["Last 90 days", 90]].map(([l, n]) => `<button class="pill" data-range="${n}">${l}</button>`).join("")}<button class="pill" data-range="month">This month</button><button class="pill" data-range="all">All time</button></div>
    <div class="grid gform"><label class="field">From<input type="date" id="since" value="${esc(S.since)}"></label><label class="field">To<input type="date" id="until" value="${esc(S.until)}"></label>
    <label class="field">Only commits by (optional)<input id="gitauthor" value="${esc(S.gitAuthor)}" placeholder="name or email"></label>
    <label class="field">Client name<input id="client" value="${esc(S.client)}" placeholder="Acme Co"></label></div>
    ${S.err ? `<div class="callout err sec"><div>${esc(S.err)}</div></div>` : ""}
    <div style="display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap"><button class="btn teal lg" id="load" ${S.repo ? "" : "disabled"}>${S.loading ? "Loading…" : "Load activity"}</button>
    <span class="note">${S.repo ? `Reads sessions and Git history for <b>${esc(pname())}</b> on this computer.` : "Select a project above first."}</span></div>
    ${S.loading ? '<div class="skel" style="width:60%"></div><div class="skel" style="width:40%"></div>' : ""}
    ${S.prev && !S.loading ? `<div class="callout ok sec"><div><b>Loaded:</b> ${S.prev.requests.length} work requests, ${S.prev.n_commits} commits, ${S.prev.n_checks} checks, ${S.prev.findings.length} masked value(s). <a href="#studio" data-go="studio" style="color:var(--teal);font-weight:500">Open Report Studio →</a></div></div>` : ""}</div></div>`;
}

/* ---------- Report Studio ---------- */
function vStudio() {
  const P = S.prev;
  if (!P) return `<div><div class="ph"><div><h2>Report Studio</h2><p>Edit work descriptions, check the evidence and export.</p></div></div><div class="card"><div class="empty"><b>No activity loaded</b>Choose a project and load its activity to start a report.<br><button class="btn dark" data-go="projects">Choose a project</button></div></div></div>`;
  const cs = P.check_stats, pend = pendingHigh().length, nTitles = Object.keys(S.titles).length;
  return `<div><div class="ph"><div><h2>Report Studio <span class="chip">${esc(P.project)}</span></h2><p>${esc(P.period)} · Git is the evidence of delivered changes; requests are not proof of completion.</p></div>
    <div class="act"><button class="btn" id="preview">${S.html ? "Refresh preview" : "Preview"}</button><button class="btn dark" id="export" ${S.exporting ? "disabled" : ""}>${ic("dl")} Export report</button></div></div>
  ${pend ? `<div class="callout"><div><b>${pend} high-severity masked value${pend > 1 ? "s" : ""} not reviewed yet.</b> Export unlocks after you review each one in the <a href="#privacy" data-go="privacy" style="color:var(--teal);font-weight:500">Privacy Center</a>.</div></div>` : ""}
  ${S.lastExport ? `<div class="callout ok"><div><b>Exported.</b> Saved to <span class="mono">${esc(S.lastExport.html_path)}</span>${S.lastExport.pdf_path ? ` and <span class="mono">${esc(S.lastExport.pdf_path)}</span>` : ""}. <a target="_blank" rel="noopener" style="color:var(--teal);font-weight:500" href="/report/${encodeURIComponent(S.lastExport.html_path.split(/[\\/]/).pop())}">Open report</a></div></div>` : ""}
  <div class="grid g4">
    <div class="card stat"><div class="k">Work requests</div><div class="v">${P.requests.length}</div><div class="d">${nTitles ? nTitles + " edited" : "from session logs"}</div></div>
    <div class="card stat"><div class="k">Commits ${ic("git", 13)}</div><div class="v">${P.n_commits}</div><div class="d">${P.authors} author(s)</div></div>
    <div class="card stat"><div class="k">Files changed</div><div class="v">${P.files}</div><div class="d"><span class="up">+${P.ins}</span> / <span class="down">−${P.dele}</span> lines</div></div>
    <div class="card stat"><div class="k">Checks ${ic("check", 13)}</div><div class="v">${P.n_checks}</div><div class="d">${cs.ok} no error · ${cs.failed} failed</div></div></div>
  <div class="grid g2 sec"><div class="card"><h3>Work requested <span class="chip">editable</span></h3>
    ${P.requests.length ? `<div class="reqs">${P.requests.map(r => `<div class="req ${S.titles[r.key] != null ? "edited" : ""}"><span class="no">${r.i + 1}</span><div class="tx" contenteditable="plaintext-only" data-req="${r.key}" spellcheck="false">${esc(S.titles[r.key] ?? r.title)}</div><span class="dt">${esc(r.date)}</span></div>`).join("")}</div><p class="note" style="margin-top:8px">Edits are re-checked for secrets before they reach the report.</p>` : `<div class="empty"><b>No requests in this period</b>Try a wider date range.</div>`}</div>
    <div class="grid" style="align-content:start"><div class="card"><h3>Git evidence</h3>${P.is_git ? (P.commits.length ? `<div class="list">${P.commits.slice(0, 8).map(c => `<div class="row"><span class="mono" style="color:var(--faint)">${esc(c[0].slice(0, 7))}</span><div class="grow"><div class="t" title="${esc(c[2])}">${esc(c[2])}</div><div class="s">${esc(c[1])}</div></div></div>`).join("")}</div>${P.n_commits > 8 ? `<p class="note" style="margin-top:6px">…and ${P.n_commits - 8} more.</p>` : ""}` : `<div class="empty" style="padding:14px"><b>No commits in this period</b></div>`) : `<div class="empty" style="padding:14px"><b>Not a Git repository</b>No delivered changes can be shown.</div>`}
      ${P.dirs.length ? `<p class="note" style="margin-top:8px"><b>Where changes landed:</b> ${P.dirs.slice(0, 4).map(d => `<span class="mono">${esc(d[0])}</span> (${d[1]})`).join(", ")}</p>` : ""}</div>
    <div class="card"><h3>Verification</h3>${P.n_checks ? `<div class="pill-row"><span class="badge ok">${cs.ok} no error reported</span><span class="badge bad">${cs.failed} failed</span><span class="badge">${cs.unknown} no result</span></div>
      <p class="note" style="margin:8px 0">${cs.superseded} re-run later · ${cs.edited} followed by edits and not re-run · ${cs.possible} possibly affected · ${cs.current} no later change.</p>
      <div class="list">${P.checks.slice(-5).reverse().map(c => `<div class="row"><div class="grow"><div class="t mono" title="${esc(c.cmd)}">${esc(c.cmd.slice(0, 70))}</div><div class="s">${esc(c.date)}${c.state === "edited" ? " · edited after, not re-run" : c.state === "superseded" ? " · re-run later" : ""}</div></div><span class="badge ${c.ok === true ? "ok" : c.ok === false ? "bad" : ""}">${c.ok === true ? "no error" : c.ok === false ? "failed" : "no result"}</span></div>`).join("")}</div>` : `<div class="empty" style="padding:14px"><b>No checks recorded</b>Test, lint or build commands appear here.</div>`}</div></div></div>
  <div class="card sec"><h3>Report preview <span class="chip">masked</span></h3>${S.html ? `<iframe class="frame" sandbox="allow-same-origin" title="Report preview" srcdoc="${esc(S.html)}"></iframe><p class="note" style="margin-top:8px">The exported file can be printed or saved as PDF from your browser.</p>` : `<div class="empty"><b>Preview not generated</b>Preview shows exactly what will be exported, after masking.<br><button class="btn" id="preview2">Generate preview</button></div>`}</div></div>`;
}

/* ---------- Privacy Center ---------- */
function vPrivacy() {
  const P = S.prev;
  const termsCard = `<div class="card"><h3>Custom redaction terms</h3><div style="display:flex;gap:8px"><input id="term" class="field" style="flex:1;height:34px;border:1px solid var(--line-2);border-radius:10px;background:var(--surface);padding:0 11px;font-size:13px" placeholder="Client or product name to mask everywhere" spellcheck="false"><button class="btn" id="addterm">Add</button></div>
    <div class="tags">${S.terms.map((t, i) => `<span class="tag">${esc(t)}<button data-rmterm="${i}" aria-label="Remove ${esc(t)}">×</button></span>`).join("")}${(S.data.settings.redact_terms || []).map(t => `<span class="tag" title="Saved in Settings">${esc(t)} <span class="badge teal">saved</span></span>`).join("")}</div>
    <p class="note" style="margin-top:8px">Terms are matched case-insensitively and always count as high severity. ${S.repo ? "Adding a term re-scans the loaded project." : ""}</p></div>`;
  if (!P) return `<div><div class="ph"><div><h2>Privacy Center</h2><p>Review everything that was masked before you export.</p></div></div><div class="card"><div class="empty"><b>Nothing to review yet</b>Load a project's activity and every masked value will be listed here.<br><button class="btn dark" data-go="projects">Choose a project</button></div></div><div class="sec">${termsCard}</div></div>`;
  const F = P.findings, H = highF(), done = H.length - pendingHigh().length, sv = k => F.filter(f => f.severity === k).length;
  return `<div><div class="ph"><div><h2>Privacy Center <span class="chip">${esc(P.project)}</span></h2><p>Masked values are shown by rule and location only; original values are never displayed or transmitted.</p></div>
    <div class="act"><button class="btn dark" id="approveall" ${pendingHigh().length ? "" : "disabled"}>Mark all high-severity reviewed</button></div></div>
  <div class="grid g4">
    <div class="card stat"><div class="k"><span><span class="sev high"></span> High</span></div><div class="v">${sv("high")}</div><div class="d">review required before export</div></div>
    <div class="card stat"><div class="k"><span><span class="sev medium"></span> Medium</span></div><div class="v">${sv("medium")}</div><div class="d">e.g. email addresses</div></div>
    <div class="card stat"><div class="k"><span><span class="sev low"></span> Low</span></div><div class="v">${sv("low")}</div><div class="d">paths, IP addresses</div></div>
    <div class="card stat"><div class="k">Export approval</div><div class="v">${H.length ? `${done}/${H.length}` : "Clear"}</div><div class="prog"><i style="width:${H.length ? done / H.length * 100 : 100}%"></i></div><div class="d">${H.length ? (done === H.length ? "all high-severity reviewed" : "reviewed") : "no high-severity findings"}</div></div></div>
  ${H.length && done < H.length ? `<div class="callout sec"><div><b>Check each high-severity item in your own files before approving.</b> If a masked value was a real credential, rotate it. Ticking “reviewed” confirms you looked at it; it does not make it safe. Automatic redaction is best-effort and not a guarantee of confidentiality.</div></div>` : ""}
  <div class="card sec"><h3>Masked values <span class="chip">${F.length}</span></h3>${F.length ? `<table class="tbl"><thead><tr><th>Severity</th><th>Rule</th><th>Where</th><th class="hide-m">Masked context</th><th style="text-align:right">Reviewed</th></tr></thead><tbody>${F.map(f => `<tr><td><span class="badge ${f.severity}"><span class="sev ${f.severity}"></span>${f.severity}</span></td><td>${esc(f.rule)}${f.count > 1 ? ` ×${f.count}` : ""}</td><td>${esc(f.where)}</td><td class="hide-m mono" style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(f.context)}">${esc(f.context)}</td><td style="text-align:right">${f.severity === "high" ? `<input type="checkbox" class="chk" data-appr="${f.id}" ${S.approved.has(f.id) ? "checked" : ""} aria-label="Reviewed">` : '<span class="note">—</span>'}</td></tr>`).join("")}</tbody></table>` : `<div class="empty"><b>No sensitive values found</b>Nothing in this period matched a redaction rule. Read the report before sharing anyway.</div>`}</div>
  <div class="sec">${termsCard}</div>
  <div class="card sec"><h3>Export approval</h3><p class="note">${pendingHigh().length ? `${pendingHigh().length} high-severity item(s) still need review. Export is blocked, in the app and on the server, until each one is reviewed.` : "All high-severity items are reviewed. You can export from Report Studio."}</p><div style="margin-top:10px"><button class="btn teal" data-go="studio">Go to Report Studio ${ic("arrow")}</button></div></div></div>`;
}

/* ---------- Settings ---------- */
function vSettings() {
  const s = S.data.settings;
  return `<div><div class="ph"><div><h2>Settings</h2><p>Local directories, appearance and report defaults.</p></div><div class="act"><button class="btn dark" id="savesettings">Save settings</button></div></div>
  <div class="grid g3f"><div class="card"><h3>Local directories</h3><div class="grid"><label class="field">Claude Code folder<input id="s_claude" value="${esc(s.claude_dir)}" spellcheck="false"><small>${S.data.claude_dir_ok ? "projects folder found" : "no projects folder at this location"}</small></label>
    <label class="field">Reports folder<input id="s_out" value="${esc(s.out_dir)}" spellcheck="false"><small>Created on first export</small></label></div></div>
  <div class="card"><h3>Appearance</h3><div class="seg" id="s_theme">${["system", "light", "dark"].map(t => `<button data-theme="${t}" class="${s.theme === t ? "on" : ""}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div></div>
  <div class="card"><h3>Report defaults</h3><div class="grid"><label class="field">Prepared by<input id="s_author" value="${esc(s.author)}" placeholder="Your name"></label><label class="field">Default client<input id="s_client" value="${esc(s.client)}" placeholder="Optional"></label></div></div></div>
  <div class="card sec"><h3>Always-redact terms</h3><label class="field"><span>One per line. Saved on this computer and applied to every report.</span><textarea id="s_terms" rows="4" style="border:1px solid var(--line-2);border-radius:10px;background:var(--surface);padding:9px 11px;font-size:13px;resize:vertical" spellcheck="false">${esc((s.redact_terms || []).join("\n"))}</textarea></label></div>
  <div class="card sec"><h3>About this app</h3><div class="grid gform"><div class="note"><b>Version</b><br>WorkReceipt ${esc(S.data.version)}</div><div class="note"><b>Engine</b><br>Python report engine (stdlib only)</div><div class="note"><b>Server</b><br>${esc(location.host)} — this computer only</div><div class="note"><b>Data</b><br>Settings and report history: <span class="mono">~/.workreceipt</span></div></div></div>
  <div class="card sec"><h3>PDF export</h3><p class="note">${S.data.chrome ? "Chrome was found on this computer; “Export report” can also create a PDF." : "Chrome was not found. Open the exported HTML and use your browser’s Print → Save as PDF."}</p></div></div>`;
}

const VIEWS = { overview: vOverview, projects: vProjects, studio: vStudio, privacy: vPrivacy, settings: vSettings };
function render() {
  if (!S.data) return;
  renderChrome();
  for (const k of Object.keys(VIEWS)) setHTML($(`#${k} .body`), VIEWS[k]());   // unchanged sections keep their DOM (preview, focus, scroll)
  fitFrame();
}
function fitFrame() {                                  // the preview grows with its content so the page never has a nested scroller
  const f = $(".frame"); if (!f) return;
  const fit = () => { try { f.style.height = f.contentDocument.documentElement.scrollHeight + 8 + "px"; } catch (e) { } };
  f.addEventListener("load", fit, { once: true }); fit();
}
addEventListener("resize", () => fitFrame());

/* ---------- actions ---------- */
async function loadState() { S.data = await api("/api/state"); applyTheme(); }
async function load() {
  S.loading = true; S.err = ""; S.html = null; S.lastExport = null; render();
  try {
    S.prev = await api("/api/preview", opts()); S.approved = new Set([...S.approved].filter(id => S.prev.findings.some(f => f.id === id)));
    S.titles = {};
  } catch (e) { S.err = e.message; S.prev = null; }
  S.loading = false; render();
  if (S.prev) toast(`Loaded ${S.prev.requests.length} requests, ${S.prev.n_commits} commits`);
}
async function makePreview() {
  try { S.html = (await api("/api/render", { ...opts(), titles: S.titles })).html; } catch (e) { toast(e.message); }
  render(); setTimeout(() => $(".frame")?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
}
async function doExport() {
  if (pendingHigh().length) { toast("Review high-severity findings first"); go("privacy"); return; }
  S.exporting = true; render();
  try {
    const r = await api("/api/export", { ...opts(), titles: S.titles, approved: [...S.approved], pdf: S.data.chrome });
    if (r._status === 409) { toast("Export blocked: high-severity findings need review"); go("privacy"); }
    else { S.lastExport = r; await loadState(); toast(r.edits_dropped ? `Report exported (${r.edits_dropped} edit(s) skipped: that request is no longer in the logs)` : "Report exported"); }
  } catch (e) { toast(e.message); }
  S.exporting = false; render();
}
function setRange(k) {
  const now = new Date();
  if (k === "all") { S.since = ""; S.until = ""; } else if (k === "month") { S.since = iso(new Date(now.getFullYear(), now.getMonth(), 1)); S.until = iso(now); }
  else { S.since = iso(new Date(now - (+k - 1) * 864e5)); S.until = iso(now); }
}
function pick(path) { S.repo = path; S.repoDraft = null; S.prev = null; S.html = null; S.err = ""; S.lastExport = null; render(); }
async function rescan() { if (S.repo) { await load(); } else render(); }

document.addEventListener("click", async e => {
  const t = e.target.closest("[data-go],[data-pick],[data-range],[data-rmterm],[data-theme],button[id]");
  if (!t) return;
  if (t.dataset.go) { e.preventDefault(); return go(t.dataset.go); }
  if (t.dataset.pick) return pick(t.dataset.pick);
  if (t.dataset.range) { setRange(t.dataset.range); return render(); }
  if (t.dataset.rmterm != null) { S.terms.splice(+t.dataset.rmterm, 1); return rescan(); }
  if (t.dataset.theme) { S.data.settings.theme = t.dataset.theme; applyTheme(); return render(); }
  switch (t.id) {
    case "theme": S.data.settings.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; applyTheme(); api("/api/settings", { theme: S.data.settings.theme }); break;
    case "usepath": { const v = $("#repo").value.trim(); if (v) pick(v); break; }
    case "load": syncForm(); await load(); break;
    case "preview": case "preview2": await makePreview(); break;
    case "export": await doExport(); break;
    case "approveall": highF().forEach(f => S.approved.add(f.id)); render(); toast("High-severity findings marked reviewed"); break;
    case "addterm": { const v = $("#term").value.trim(); if (v) { S.terms.push(v); await rescan(); } break; }
    case "savesettings": {
      try {
        S.data.settings = await api("/api/settings", { claude_dir: $("#s_claude").value.trim(), out_dir: $("#s_out").value.trim(), author: $("#s_author").value.trim(), client: $("#s_client").value.trim(),
          theme: S.data.settings.theme, redact_terms: $("#s_terms").value.split("\n") });
        await loadState(); if (!S.author) S.author = S.data.settings.author; if (!S.client) S.client = S.data.settings.client; render(); toast("Settings saved");
      } catch (er) { toast(er.message); }
    }
  }
});
document.addEventListener("change", e => {
  if (e.target.dataset.appr) { e.target.checked ? S.approved.add(e.target.dataset.appr) : S.approved.delete(e.target.dataset.appr); render(); }
});
document.addEventListener("input", e => {
  if (e.target.id === "repo") S.repoDraft = e.target.value;
  if (["since", "until", "gitauthor", "client"].includes(e.target.id)) syncForm();
  const r = e.target.dataset?.req;
  if (r != null) { const orig = S.prev.requests.find(q => q.key === r)?.title, v = e.target.textContent.trim(); if (v && v !== orig) S.titles[r] = v; else delete S.titles[r]; S.html = null; e.target.closest(".req").classList.toggle("edited", r in S.titles); }
});
document.addEventListener("keydown", e => { if (e.target.id === "term" && e.key === "Enter") $("#addterm").click(); if (e.target.id === "repo" && e.key === "Enter") $("#usepath").click(); });
function syncForm() { for (const [id, k] of [["since", "since"], ["until", "until"], ["gitauthor", "gitAuthor"], ["client", "client"], ["repo", "repo"]]) { const el = $("#" + id); if (el && id !== "repo") S[k] = el.value.trim(); } }
document.addEventListener("focusout", e => { if (["since", "until", "gitauthor", "client"].includes(e.target.id)) syncForm(); });
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", applyTheme);


function initScroll() {
  const rm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const secs = [...document.querySelectorAll(".band")];
  if ("IntersectionObserver" in window) {
    const spy = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting && S.tab !== en.target.id) { S.tab = en.target.id; renderChrome(); } }), { rootMargin: "-40% 0px -55% 0px" });
    secs.forEach(s => spy.observe(s));
    const top = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting && S.tab) { S.tab = ""; renderChrome(); } }), { rootMargin: "-40% 0px -55% 0px" });
    top.observe($("#top"));
    if (!rm) {
      document.documentElement.classList.add("reveal");
      const rv = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting) { en.target.classList.add("in"); rv.unobserve(en.target); } }), { rootMargin: "0px 0px -8% 0px", threshold: 0.02 });
      secs.forEach(s => rv.observe(s));
    }
  }
  const tt = $("#totop"); const upd = () => tt.classList.toggle("on", scrollY > 900); addEventListener("scroll", upd, { passive: true }); upd();
}
(async () => {
  initScroll();
  try { await loadState(); S.author = S.data.settings.author; S.client = S.data.settings.client; $("#ver").textContent = "v" + S.data.version; }
  catch (e) { $("#overview .body").innerHTML = `<div class="callout err"><div>Could not reach the local WorkReceipt server: ${esc(e.message)}</div></div>`; return; }
  render();
  const h = location.hash.slice(1); if (h && document.getElementById(h)) setTimeout(() => go(h), 80);
})();
