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
  git: '<circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="12" r="2"/><path d="M6 8v8M8 6c6 0 8 2 8 6"/>', check: '<path d="M5 12l5 5 9-10"/>', lib: '<path d="M4 6h16M4 12h16M4 18h10"/>'
};
const ic = (n, s = 14) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${I[n]}</svg>`;
const TABS = [["overview", "Overview"], ["projects", "Projects"], ["studio", "Report Studio"], ["privacy", "Privacy Center"], ["reports", "Reports"], ["settings", "Settings"]];
const ICON = { overview: "grid", projects: "folder", studio: "doc", privacy: "shield", reports: "lib", settings: "gear" };

const S = { tab: "overview", ob: null, q: "", rf: "", rt: "", busy: "", data: null, repo: "", since: "", until: "", client: "", author: "", gitAuthor: "", terms: [], prev: null,
  titles: {}, disp: {}, mode: "client", cr: null, open: new Set(), dlg: null, showCleared: false, loading: false, err: "", html: null, exporting: false, lastExport: null, exportFail: "", repoDraft: null };

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "X-WR-Token": TOKEN, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok && r.status !== 409) throw new Error(j.error || `Request failed (${r.status})`);
  return Object.assign(j, { _status: r.status });
}
/* ---- native actions ----
   Native dialogs/Finder/open run through the app's own local HTTP channel (/api/native/*), NOT the WebView JS bridge, so they work
   whenever the page itself loads. In the desktop app (?shell=desktop) the picker buttons stay disabled only until the host reports ready. */
const DESKTOP = new URLSearchParams(location.search).get("shell") === "desktop";
const B = { state: DESKTOP ? "wait" : "none", info: null };
const BRIDGE_DOWN = "The native folder dialog is not available. Quit and reopen WorkReceipt; if this continues, open Settings → Diagnostics, or type the folder path instead.";
function syncPickers() {
  const off = DESKTOP && B.state !== "ready";
  document.querySelectorAll("[data-choose],#addproj,#obpick").forEach(b => { b.disabled = off; b.title = off ? (B.state === "failed" ? BRIDGE_DOWN : "Starting up…") : ""; });
}
async function nativeCheck() {
  try { B.info = await api("/api/native/status", {}); } catch (e) { B.info = { available: false, reason: e.message }; }
  const was = B.state; B.state = B.info.available ? "ready" : (B.state === "failed" ? "failed" : "wait");
  if (was !== B.state) { cache.screen = null; render(); } syncPickers();
  return B.state === "ready";
}
if (DESKTOP) {
  const t0 = Date.now(), iv = setInterval(async () => {
    if (await nativeCheck()) clearInterval(iv);
    else if (Date.now() - t0 > (window.WR_BRIDGE_TIMEOUT_MS || 15000)) { clearInterval(iv); B.state = "failed"; cache.screen = null; render(); syncPickers(); toast(BRIDGE_DOWN); }
  }, 300);
}
async function pickFolder(start) {                 // -> path | null.  pickFolder.failed is true when null means "error", not "cancelled"
  pickFolder.failed = false;
  if (!DESKTOP) return null;
  if (B.state !== "ready" && !(await nativeCheck())) { pickFolder.failed = true; toast(B.state === "failed" ? BRIDGE_DOWN : "WorkReceipt is still starting. Try again in a moment."); return null; }
  try { const r = await api("/api/native/pick_folder", { start: start || null }); if (!r.ok) { pickFolder.failed = true; toast(r.error || "The folder dialog could not be opened."); return null; } return r.path || null; }
  catch (e) { pickFolder.failed = true; toast("The folder dialog could not be opened: " + e.message); return null; }
}
window.wrDropped = p => addProjectFlow(p);
const fname = p => String(p || "").split(/[\\/]/).pop();
async function fileAction(method, name, kind) {    // the page sends only a file NAME; the app resolves it against its own report history
  if (DESKTOP) {
    try { const r = await api("/api/native/" + method, { name, kind: kind || "html" }); if (!r.ok) toast(r.error || "Could not complete that action."); }
    catch (e) { toast("The action could not be completed: " + e.message); }
    return;
  }
  if (method === "open") { const w = window.open("/report/" + encodeURIComponent(name), "_blank", "noopener"); if (!w) toast("The browser blocked the new tab. Allow pop-ups for this page."); return; }
  toast("Show in Finder is available in the desktop app.");
}
const openFile = (name, kind) => fileAction("open", name, kind);
const revealFile = (name, kind) => fileAction("reveal", name, kind);
async function addProjectFlow(typed) {
  let path = typed || await pickFolder();
  if (!path) { if (!DESKTOP) { go("projects"); setTimeout(() => $("#repo")?.focus(), 50); toast("Type or paste a folder path, then press Use this folder"); } return null; }
  try { const r = await api("/api/project/add", { path }); await loadState(); pick(r.path); toast("Project added"); return r.path; }
  catch (e) { toast(e.message); return null; }
}
function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove("on"), 3200); }
const opts = () => ({ repo: S.repo, since: S.since, until: S.until, client: S.client, author: S.author, git_author: S.gitAuthor, terms: S.terms });
const highF = () => (S.prev ? S.prev.findings.filter(f => f.severity === "high") : []);
const highD = () => highF().flatMap(f => f.detections);
const pendingHigh = () => highD().filter(d => !d.suppressed && !S.disp[d.id]);
const needsReview = () => highD().filter(d => !d.suppressed);
const PRIO = { looks_real: 0, known_format: 0, custom_term: 1, unknown: 2, likely_dummy: 3, test_fixture: 3 };
const DISP = { credential: "Real credential (rotate it)", not_credential: "Not a credential (test or dummy value)", unsure: "Unsure (treat as sensitive)" };
const DISP_SHORT = { credential: "real", not_credential: "dummy", unsure: "unsure" };
function detRow(d) {
  const ctx = (d.context || []).map(l => `<div class="cl${l.hit ? " hit" : ""}">${l.segs.map(([k, t]) => k === "hl" ? `<mark>${esc(t)}</mark>` : esc(t)).join("")}</div>`).join("");
  const loc = d.line ? `${esc(d.where)}${d.at ? " · " + esc(d.at) : ""} · line ${d.line} of ${d.lines}, col ${d.col} · ${d.length} chars` : `${esc(d.where)} · ${d.unitemised} detection(s), not individually locatable (text too large)`;
  const rep = d.in_report === false ? "Masked, and not printed in the exported report (only the first line of each command is shown)." : d.in_report ? "Appears (masked) in the exported report." : "";
  const notes = [d.same_value_elsewhere ? `Same value appears in ${d.same_value_elsewhere} other place(s).` : "", d.inside ? `Inside a ${esc(d.inside)} match.` : "", d.also?.length ? `Also contains: ${d.also.map(esc).join(", ")}.` : "", rep].filter(Boolean).join(" ");
  const r = S.disp[d.id], c = d.class || {}, cls = c.suppressed ? "teal" : c.category === "looks_real" || c.category === "known_format" ? "high" : "";
  const why = `<div class="why"><span class="badge ${cls}">${esc(c.label || "")}</span> <span class="note">confidence: ${esc(c.confidence || "low")}. ${esc(c.explanation || "")}</span>${(c.evidence || []).length ? `<ul class="ev">${c.evidence.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>`;
  if (d.suppressed) return `<div class="det cleared"><div class="dh"><b>#${d.n} of ${d.of}</b><span class="note">${loc}</span></div>${ctx ? `<div class="ctx mono">${ctx}</div>` : ""}${why}<p class="note">Cleared automatically: no review needed. Still masked in the report.</p>${d.line ? `<div class="dact"><button class="btn" data-reveal="${d.id}">Reveal value</button></div>` : ""}</div>`;
  return `<div class="det"><div class="dh"><b>#${d.n} of ${d.of}</b><span class="note">${loc}</span></div>${ctx ? `<div class="ctx mono">${ctx}</div>` : ""}${why}${notes ? `<p class="note">${notes}</p>` : ""}
    <div class="dact">${d.line ? `<button class="btn" data-reveal="${d.id}">Reveal value</button>` : ""}<button class="btn ${r ? "" : "dark"}" data-review="${d.id}">${r ? "Change review" : "Review"}</button>${r ? `<span class="badge teal">${DISP_SHORT[r]}</span>` : '<span class="badge high">pending</span>'}</div></div>`;
}
function dialogHTML() {
  const g = S.dlg; if (!g) return "";
  if (g.kind === "delrep") return `<div class="ovl" role="alertdialog" aria-modal="true" aria-label="Delete report"><div class="dlgbox"><h3>Delete this report?</h3><p class="note">The exported HTML and PDF files are removed from disk. This cannot be undone.</p><div class="dact"><button class="btn dark" id="confirmdel">Delete report</button><button class="btn" data-close="1">Cancel</button></div></div></div>`;
  if (g.kind === "rmproj") return `<div class="ovl" role="alertdialog" aria-modal="true" aria-label="Remove project"><div class="dlgbox"><h3>Remove from WorkReceipt?</h3><p class="note">The project is only hidden here. Its folder, Git history and Claude Code logs are not changed or deleted.</p><div class="dact"><button class="btn dark" id="confirmdel">Remove project</button><button class="btn" data-close="1">Cancel</button></div></div></div>`;
  if (g.kind === "crreview") { const r = S.cr.res; if (!r || !r.html) return "";
    return `<div class="ovl" role="dialog" aria-modal="true" aria-labelledby="crt"><div class="dlgbox" style="max-width:580px"><h3 id="crt">Review sharing</h3>
    <p class="note">This is exactly what the exported HTML and PDF will contain (fingerprint <span class="mono">${esc(r.content_hash.slice(0, 8))}</span>). Changing anything afterwards clears this approval.</p>
    <dl class="manifest">${r.manifest.map(m => `<div><dt>${esc(m.label)}</dt><dd>${esc(m.value)}</dd></div>`).join("")}</dl>
    <p class="note"><b>Never exported:</b> ${(r.excluded || CR_EXCLUDED).map(esc).join("; ")}.</p>
    <div class="ack"><div class="ack-h">Required confirmation</div><p class="note">Automatic checks cannot know what is confidential to your client. They are a safety net, not a guarantee.</p>
      <label class="ropt"><input type="checkbox" id="crack" ${g.ack ? "checked" : ""}><span>I have read the client preview in full. It contains nothing my client has not agreed to receive, and I approve exactly this content for sharing.</span></label></div>
    <div class="dact split"><button class="btn cancel" data-close="1">Cancel</button><button class="btn dark" id="crconfirm" ${g.ack ? "" : "disabled"}>Approve for sharing</button></div></div></div>`; }
  const d = highD().find(x => x.id === g.id); if (!d) return "";
  if (g.kind === "reveal") return `<div class="ovl" role="dialog" aria-modal="true" aria-label="Reveal value"><div class="dlgbox"><h3>Original value</h3><p class="note">${esc(d.where)}, line ${d.line}. Shown only on this screen, only for this detection. It is not logged, stored or sent anywhere, and hides itself in 20 seconds.</p>
    ${g.value == null ? (g.err ? `<p class="note">${esc(g.err)}</p>` : '<p class="note">Loading…</p>') : '<pre class="revealed" id="rv"></pre>'}<div class="dact"><button class="btn dark" data-close="1">Hide and close</button></div></div></div>`;
  const ready = !!(g.pick && g.ack);
  return `<div class="ovl" role="dialog" aria-modal="true" aria-labelledby="rvt" aria-describedby="rvd"><div class="dlgbox"><h3 id="rvt">Review detection #${d.n} of ${d.of}</h3>
    <p class="note" id="rvd">${esc(d.rule)} · ${esc(d.where)}${d.line ? ", line " + d.line : ""}. Your choice is recorded for this session only. The value stays masked in the report either way.</p>
    <fieldset class="rgroup"><legend>1. What is this value?</legend>
      ${Object.entries(DISP).map(([k, v]) => `<label class="ropt"><input type="radio" name="disp" value="${k}" ${g.pick === k ? "checked" : ""}><span>${v}</span></label>`).join("")}</fieldset>
    <div class="ack"><div class="ack-h">Required acknowledgement</div>
      <p class="note">Reviewing a value does <b>not</b> make a credential safe, and it never unmasks anything. If this was a real credential, rotate it.</p>
      <label class="ropt"><input type="checkbox" id="ack" ${g.ack ? "checked" : ""}><span>I have inspected this detection myself (or understand I cannot) and I take responsibility for this choice.</span></label></div>
    <p class="why-off" id="rvhint" role="status" ${ready ? "hidden" : ""}>${!g.pick && !g.ack ? "Select a classification and tick the acknowledgement to enable Confirm review." : !g.pick ? "Select a classification to enable Confirm review." : "Tick the required acknowledgement to enable Confirm review."}</p>
    <div class="dact split"><button class="btn cancel" data-close="1">Cancel</button><button class="btn dark" id="confirmrev" aria-describedby="rvhint" ${ready ? "" : "disabled"}>Confirm review</button></div></div></div>`;
}
function closeDlg() { clearTimeout(closeDlg.t); S.dlg = null; const o = $("#dlgroot"); if (o) o.innerHTML = ""; }
function showDlg() {
  const o = $("#dlgroot"); if (!o) return; o.innerHTML = dialogHTML();
  const rv = $("#rv"); if (rv && S.dlg?.value != null) rv.textContent = S.dlg.value;
  o.querySelector("button,input")?.focus();
}
async function doReveal(id) {
  S.dlg = { kind: "reveal", id, value: null, err: "" }; showDlg();
  try { const r = await api("/api/reveal", { ...opts(), id, confirm: true }); if (S.dlg?.id !== id) return; S.dlg.value = r.value; showDlg(); clearTimeout(closeDlg.t); closeDlg.t = setTimeout(closeDlg, 20000); }
  catch (e) { if (S.dlg) { S.dlg.err = e.message; showDlg(); } }
}
const today = () => new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
const iso = d => { const z = new Date(d.getTime() - d.getTimezoneOffset() * 6e4); return z.toISOString().slice(0, 10); };
const proj = () => (S.data?.projects || []).find(p => p.path === S.repo);
const pname = () => proj()?.name || (S.repo ? S.repo.split(/[\\/]/).filter(Boolean).pop() : "");

const ICON_MOON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
const ICON_SUN = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.4 1.4M17.6 17.6L19 19M19 5l-1.4 1.4M6.4 17.6L5 19"/></svg>';
function applyTheme() {
  const t = S.data?.settings.theme || "system";
  const dark = t === "dark" || (t === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  const b = $("#theme"); if (b) { b.innerHTML = dark ? ICON_SUN : ICON_MOON; const l = dark ? "Switch to light theme" : "Switch to dark theme"; b.title = l; b.setAttribute("aria-label", l); }
}
function go(id) {                         // switch screen; all state (project, edits, reviews, preview) lives in S and survives
  if (!VIEWS_OK.includes(id)) return;
  S.tab = id; cache.screen = null; history.replaceState(null, "", "#" + id);
  render(); const m = $("#screen"); m.scrollTop = 0; m.focus({ preventScroll: true });
}
const VIEWS_OK = ["overview", "projects", "studio", "privacy", "reports", "settings"];
const cache = {};
function setHTML(el, html) { const k = el.id + S.tab; if (cache[el.id] !== k + html) { cache[el.id] = k + html; el.innerHTML = html; } }
function renderChrome() {
  const hp = pendingHigh().length;
  setHTML($("#tabs"), TABS.map(([k, l]) => `<button class="tab" data-go="${k}" ${S.tab === k ? 'aria-current="page"' : ""}>${ic(ICON[k], 16)}<span>${l}</span>${k === "privacy" && hp ? `<span class="dot">${hp}</span>` : ""}</button>`).join(""));
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
  const noDir = !d.claude_dir_ok && !ps.length && (d.settings.providers || {}).claude !== false;
  return `<div><div class="ph"><div><h2>Overview <span class="chip">${today()}</span></h2><p>Your projects, recent Claude Code activity and exported reports.</p></div>
    <div class="act"><button class="btn" id="refresh" title="Rescan projects and reports">Refresh</button><button class="btn" id="addproj">${ic("plus")} Add project</button><button class="btn dark" id="genreport">${ic("doc")} Generate report</button><button class="btn" id="openrecent" ${hist.length ? "" : "disabled"}>Open recent report</button></div></div>
  ${d.git_ok === false ? `<div class="callout err"><div><b>Git is not installed.</b> WorkReceipt needs Git to read commit history. On a Mac, run <span class="mono">xcode-select --install</span> once in Terminal, then reopen WorkReceipt.</div></div>` : ""}
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
    ${hist.length ? `<table class="tbl"><thead><tr><th>Project</th><th>Period</th><th class="hide-m">Requests</th><th class="hide-m">Commits</th><th>Exported</th><th></th></tr></thead><tbody>${hist.slice(0, 6).map(h => `<tr><td><b style="font-weight:500">${esc(h.project)}</b></td><td class="mono">${esc(h.period)}</td><td class="hide-m">${h.requests}</td><td class="hide-m">${h.commits}</td><td>${esc(h.at)}</td><td style="text-align:right"><button class="btn sm" data-open="${esc(fname(h.html))}" data-kind="html">Open</button></td></tr>`).join("")}</tbody></table>` : `<div class="empty"><b>No reports yet</b>Pick a project, load its activity and export your first report.<br><button class="btn dark" data-go="projects">Choose a project</button></div>`}</div></div>`;
}

/* ---------- Projects ---------- */
function vProjects() {
  const d = S.data, ps = d.projects;
  const p = proj();
  return `<div><div class="ph"><div><h2>Projects <span class="chip">${ps.length} found</span></h2><p>Choose a repository and the period to report on. Removing a project only hides it here; your files are never touched.</p></div><div class="act"><button class="btn" id="refresh">Refresh</button><button class="btn dark" id="addproj">${ic("plus")} Add project</button></div></div>
  <div class="card"><h3>Claude Code projects</h3>${ps.length ? `<table class="tbl"><thead><tr><th>Project</th><th class="hide-m">Folder</th><th>Sessions</th><th class="hide-m">Last activity</th><th>Git</th><th></th></tr></thead><tbody>${ps.map(x => `<tr class="click" data-pick="${esc(x.path)}" ${x.path === S.repo ? 'style="background:var(--teal-soft)"' : ""}><td><b style="font-weight:500">${esc(x.name)}</b></td><td class="mono hide-m" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(x.path)}</td><td>${x.sessions}</td><td class="hide-m">${esc(x.last)}</td><td>${!x.exists ? '<span class="badge bad">folder missing</span>' : x.git ? '<span class="badge ok">Git</span>' : '<span class="badge">no Git</span>'}</td><td style="text-align:right;white-space:nowrap"><button class="btn sm" data-rmproj="${esc(x.path)}" aria-label="Remove ${esc(x.name)} from WorkReceipt">Remove</button></td></tr>`).join("")}</tbody></table>` :
    `<div class="empty"><b>${d.claude_dir_ok ? "No sessions found" : "Claude Code folder not found"}</b>${d.claude_dir_ok ? "Claude Code has not recorded sessions in this location yet." : "Check the location in Settings."}<br><button class="btn" data-go="settings">Open Settings</button></div>`}
  ${p ? `<div class="callout ${p.exists ? "ok" : ""} sec"><div><b>${esc(p.name)}</b> <span class="mono">${esc(p.path)}</span><br>${!p.exists ? "This folder was moved or deleted. Remove it, or add its new location." : `${p.sessions} Claude Code session file(s)${p.sessions ? "" : " found. If you expected some, set the Claude Code folder in Settings"} · ${p.git ? "Git repository detected" : "not a Git repository, so reports will have no delivered changes"}${p.demo ? " · synthetic demo data" : ""}`}</div></div>` : ""}
  <div class="grid sec" style="grid-template-columns:1fr auto;align-items:end"><label class="field">Or enter a repository folder
    <input id="repo" value="${esc(S.repoDraft ?? S.repo)}" placeholder="/Users/you/projects/client-site" spellcheck="false"></label><button class="btn" id="usepath">Use this folder</button></div></div>
  <div class="card sec"><h3>Period &amp; filters ${p ? `<span class="chip">${esc(p.name)}</span>` : ""}</h3>
    <div class="pill-row" role="group" aria-label="Date range" style="margin-bottom:12px">${[["Last 7 days", "7"], ["Last 30 days", "30"], ["Last 90 days", "90"], ["This month", "month"], ["All time", "all"]].map(([l, n]) => `<button type="button" class="pill${activeRange() === n ? " on" : ""}" data-range="${n}" aria-pressed="${activeRange() === n}">${l}</button>`).join("")}</div>
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
const shortErr = m => String(m || "").replace(/\/[^\s)"']+/g, "…").slice(0, 240);       // never show filesystem paths in notifications
function exportCard() {
  const X = S.lastExport, bad = S.exportFail;
  if (S.exporting) return `<div class="xcard busy" role="status" aria-live="polite"><div class="xh"><span class="xdot"></span><b>Exporting report…</b></div><p class="xs">Creating the HTML file and the PDF. This can take a few seconds.</p></div>`;
  if (bad) return `<div class="xcard err" role="alert"><div class="xh"><span class="xdot"></span><b>Export failed</b></div><p class="xs">${esc(shortErr(bad))}</p><div class="xact"><button class="btn sm" id="retryexp">Try again</button></div></div>`;
  if (!X) return "";
  const hn = X.html_name || fname(X.html_path), pn = X.pdf_name || (X.pdf_path ? fname(X.pdf_path) : "");
  const partial = !!X.pdf_failed, st = partial ? "warn" : "ok";
  const title = partial ? "HTML exported, PDF failed" : (pn ? "Exported: HTML and PDF" : "Exported: HTML");
  const sub = partial ? "The HTML report was saved. The PDF could not be created, so it is not listed." : (pn ? "Both files were saved to your reports folder." : "The HTML report was saved to your reports folder.");
  const files = `<span class="xf" title="${esc(hn)}">${esc(hn)}</span>${pn ? `<span class="xf" title="${esc(pn)}">${esc(pn)}</span>` : ""}`;
  const acts = `<button class="btn sm" data-open="${esc(hn)}" data-kind="html">Open HTML</button>${pn ? `<button class="btn sm" data-open="${esc(pn)}" data-kind="pdf">Open PDF</button>` : ""}<button class="btn sm" data-showfile="${esc(pn || hn)}" data-kind="${pn ? "pdf" : "html"}">Show in Finder</button>`;
  const det = partial && X.pdf_error ? `<details class="xd"><summary>View technical details</summary><p class="mono">${esc(shortErr(X.pdf_error))}</p></details>` : "";
  return `<div class="xcard ${st}" role="status"><div class="xh"><span class="xdot"></span><b>${title}</b></div><p class="xs">${sub}</p><div class="xfiles">${files}</div><div class="xact">${acts}</div>${det}</div>`;
}
function vStudio() { return !S.prev || S.mode === "private" ? vStudioPrivate() : vClient(); }
function vStudioPrivate() {
  const P = S.prev;
  if (!P) return `<div><div class="ph"><div><h2>Report Studio</h2><p>Edit work descriptions, check the evidence and export.</p></div></div><div class="card"><div class="empty"><b>No activity loaded</b>Choose a project and load its activity to start a report.<br><button class="btn dark" data-go="projects">Choose a project</button></div></div></div>`;
  const cs = P.check_stats, pend = pendingHigh().length, nTitles = Object.keys(S.titles).length;
  return `<div><div class="ph"><div><h2>Report Studio <span class="chip">${esc(P.project)}</span></h2><p>${esc(P.period)} · Git is the evidence of delivered changes; requests are not proof of completion.</p></div>
    <div class="act"><button class="btn" id="preview">${S.html ? "Refresh preview" : "Preview"}</button><button class="btn dark" id="export" ${S.exporting ? "disabled" : ""}>${ic("dl")} Export developer report</button></div></div>
  ${modeSwitch()}
  <div class="callout"><div><span class="badge bad">PRIVATE</span> <b>Developer View.</b> This view and its export include your prompts, commit messages and commands. Do not send them to a client. Use the Client-Safe Report for anything you share.</div></div>
  ${pend ? `<div class="callout"><div><b>${pend} high-severity masked value${pend > 1 ? "s" : ""} not reviewed yet.</b> Export unlocks after you review each one in the <a href="#privacy" data-go="privacy" style="color:var(--teal);font-weight:500">Privacy Center</a>.</div></div>` : ""}
  ${exportCard()}
  <div class="grid g4">
    <div class="card stat"><div class="k">Work requests</div><div class="v">${P.requests.length}</div><div class="d">${nTitles ? nTitles + " edited" : "from session logs"}</div></div>
    <div class="card stat"><div class="k">Commits ${ic("git", 13)}</div><div class="v">${P.n_commits}</div><div class="d">${P.authors} author(s)</div></div>
    <div class="card stat"><div class="k">Files changed</div><div class="v">${P.files}</div><div class="d"><span class="up">+${P.ins}</span> / <span class="down">−${P.dele}</span> lines</div></div>
    <div class="card stat"><div class="k">Checks ${ic("check", 13)}</div><div class="v">${P.n_checks}</div><div class="d">${cs.ok} no error · ${cs.failed} failed</div></div></div>
  <div class="grid g2 sec"><div class="card"><h3>Work requested <span class="chip">editable</span></h3>
    ${P.requests.length ? `<div class="reqs">${P.requests.map(r => `<div class="req ${S.titles[r.key] != null ? "edited" : ""}"><span class="no">${r.i + 1}</span><div class="tx" contenteditable="plaintext-only" data-req="${r.key}" spellcheck="false">${esc(S.titles[r.key] ?? r.title)}</div><span class="badge" title="Source AI tool">${esc(r.source || "")}</span><span class="dt">${esc(r.date)}</span></div>`).join("")}</div><p class="note" style="margin-top:8px">Edits are re-checked for secrets before they reach the report.</p>` : `<div class="empty"><b>No requests in this period</b>Try a wider date range.</div>`}</div>
    <div class="grid" style="align-content:start"><div class="card"><h3>Git evidence</h3>${P.is_git ? (P.commits.length ? `<div class="list">${P.commits.slice(0, 8).map(c => `<div class="row"><span class="mono" style="color:var(--faint)">${esc(c[0].slice(0, 7))}</span><div class="grow"><div class="t" title="${esc(c[2])}">${esc(c[2])}</div><div class="s">${esc(c[1])}</div></div></div>`).join("")}</div>${P.n_commits > 8 ? `<p class="note" style="margin-top:6px">…and ${P.n_commits - 8} more.</p>` : ""}` : `<div class="empty" style="padding:14px"><b>No commits in this period</b></div>`) : `<div class="empty" style="padding:14px"><b>Not a Git repository</b>No delivered changes can be shown.</div>`}
      ${P.dirs.length ? `<p class="note" style="margin-top:8px"><b>Where changes landed:</b> ${P.dirs.slice(0, 4).map(d => `<span class="mono">${esc(d[0])}</span> (${d[1]})`).join(", ")}</p>` : ""}</div>
    <div class="card"><h3>Verification</h3>${P.n_checks ? `<div class="pill-row"><span class="badge ok">${cs.ok} no error reported</span><span class="badge bad">${cs.failed} failed</span><span class="badge">${cs.unknown} no result</span></div>
      <p class="note" style="margin:8px 0">${cs.superseded} re-run later · ${cs.edited} followed by edits and not re-run · ${cs.possible} possibly affected · ${cs.current} no later change.</p>
      <div class="list">${P.checks.slice(-5).reverse().map(c => `<div class="row"><div class="grow"><div class="t mono" title="${esc(c.cmd)}">${esc(c.cmd.slice(0, 70))}</div><div class="s">${esc(c.date)}${c.state === "edited" ? " · edited after, not re-run" : c.state === "superseded" ? " · re-run later" : ""}</div></div><span class="badge ${c.ok === true ? "ok" : c.ok === false ? "bad" : ""}">${c.ok === true ? "no error" : c.ok === false ? "failed" : "no result"}</span></div>`).join("")}</div>` : `<div class="empty" style="padding:14px"><b>No checks recorded</b>Test, lint or build commands appear here.</div>`}</div></div></div>
  <div class="card sec"><h3>Report preview <span class="chip">masked</span></h3>${S.html ? `<iframe class="frame" sandbox="allow-same-origin" title="Report preview" srcdoc="${esc(S.html)}"></iframe><p class="note" style="margin-top:8px">${S.data.chrome ? "Export also creates a PDF." : "PDF export is not available here; the HTML export always works and can be printed to PDF."}</p>` : `<div class="empty"><b>Preview not generated</b>Preview shows exactly what will be exported, after masking.<br><button class="btn" id="preview2">Generate preview</button></div>`}</div></div>`;
}

/* ---------- Client-Safe Report ---------- */
/* Everything the client report contains is typed or approved here by the developer. The server builds the report from this draft
   (allowlisted fields only) and from nothing else; unapproved items are never sent. */
function newCR() { return { project: "", client: "", showPrep: false, prep: "", items: [], vmode: "none", vtext: "", res: null, token: null, hash: null, busy: "", cleared: false, pdf: true, nid: 1, ev: new Set() }; }
S.cr = newCR();
const CR_EXCLUDED = ["Source code and diffs", "Your prompts and the AI's responses", "Terminal commands and their output", "Git commit messages and commit ids", "File names, folder names and file paths", "Repository addresses and any other links", "Passwords, keys, tokens and environment variables", "Server, database and infrastructure names", "Your computer's user name, machine name and device details", "Raw verification logs", "Anything you have not approved"];
const crItem = id => S.cr.items.find(i => String(i.id) === String(id));
const crApproved = () => S.cr.items.filter(i => i.approved);
const crWhy = i => !i.text.trim() ? "Write a description for your client first." : (i.status === "delivered" && !i.commits.length && !i.attested) ? "A Delivered item needs evidence: link Git commits, or confirm the work yourself." : "";
function crDraft() {
  const c = S.cr;
  return { project_name: c.project, client_name: c.client, include_prepared_by: c.showPrep, prepared_by: c.prep,
    items: crApproved().map(i => ({ text: i.text, status: i.status, commits: i.status === "delivered" ? i.commits : [], attested: i.status === "delivered" && i.attested, approved: true })),
    verification: { mode: c.vmode, text: c.vtext } };
}
const crBody = () => ({ ...opts(), draft: crDraft(), approved: S.disp });
function crInvalidate() {                     // any change to what would be shared voids the preview and the approval
  const c = S.cr, had = !!c.token;
  c.res = null; c.token = null; c.hash = null; if (had) { c.cleared = true; S.lastExport = null; }
  crPaint();
}
function renderKeep() {
  const a = document.activeElement, fk = a?.dataset?.fk, s = a?.selectionStart, e = a?.selectionEnd;
  cache.screen = null; render();
  if (fk) { const n = document.querySelector(`[data-fk="${fk}"]`); if (n) { n.focus({ preventScroll: true }); try { if (s != null) n.setSelectionRange(s, e); } catch (x) { } } }
}
function modeSwitch() {
  return `<div class="seg" id="modeseg" role="group" aria-label="Report mode" style="margin:0 0 14px"><button type="button" id="mode-private" data-mode="private" aria-pressed="${S.mode === "private"}" class="${S.mode === "private" ? "on" : ""}">Private Evidence</button><button type="button" id="mode-client" data-mode="client" aria-pressed="${S.mode === "client"}" class="${S.mode === "client" ? "on" : ""}">Client-Safe Report</button></div>`;
}
function crStatusHTML() {
  const c = S.cr, ap = crApproved(), un = c.items.length - ap.length, pend = pendingHigh().length, r = c.res;
  const row = (ok, t) => `<li class="${ok ? "ok" : ""}"><span class="mk" aria-hidden="true">${ok ? "✓" : ""}</span><span>${t}</span></li>`;
  const issues = r && r.issues && r.issues.length ? `<ul class="issues" role="alert">${r.issues.map(i => `<li>${esc(i.message)}</li>`).join("")}</ul>` : (r && r.message ? `<div class="issues" role="alert">${esc(r.message)}</div>` : "");
  return `<ul class="chk5">${row(!!c.project.trim(), "Project name written by you")}
    ${row(ap.length > 0, `${ap.length} approved item${ap.length === 1 ? "" : "s"}${un ? ` · ${un} not approved (will not be shared)` : ""}`)}
    ${row(!pend, pend ? `${pend} high-severity finding${pend > 1 ? "s" : ""} still need your review in the <button type="button" class="linkbtn" data-go="privacy">Privacy Center</button>` : "High-severity privacy findings reviewed")}
    ${row(!!(r && r.ok), r ? (r.ok ? "Passed the automatic checks" : "Fix the problems listed below") : "Automatic checks not run yet. Choose Preview client report")}
    ${row(!!c.token, c.token ? `Approved for sharing · fingerprint <span class="mono">${esc(c.hash.slice(0, 8))}</span>` : (c.cleared ? "Approval cleared because the content changed. Review sharing again" : "Not approved yet"))}</ul>${issues}`;
}
function crPreviewHTML() {
  const r = S.cr.res;
  if (r && r.html) return `<div class="callout ok" role="status"><div><b>Client-Safe Report — Only approved information will be shared.</b> This is the exact content that will be exported (fingerprint <span class="mono">${esc(r.content_hash.slice(0, 8))}</span>). Read all of it.</div></div><iframe class="frame" sandbox="allow-same-origin" title="Client report preview" srcdoc="${esc(r.html)}"></iframe>`;
  return `<div class="empty"><b>${r ? "No preview: fix the problems listed above" : "Preview not generated"}</b>The preview is built from approved items only and is the exact file that will be exported.<br><button class="btn" id="cr-preview2" data-fk="crprev2">Preview client report</button></div>`;
}
function crPaint() {
  const s = $("#crstatus"), p = $("#crprevcard"), a = $("#cr-review"), b = $("#cr-export");
  if (s) s.innerHTML = crStatusHTML();
  if (p) { p.innerHTML = crPreviewHTML(); fitFrame(); }
  if (a) a.disabled = !(S.cr.res && S.cr.res.ok);
  if (b) b.disabled = !S.cr.token || S.exporting;
}
function crItemHTML(i, n, total) {
  const ok = i.approved, why = ok ? "" : crWhy(i), fk = k => `data-fk="${k}-${i.id}"`;
  const ev = i.status === "delivered" ? `<div class="rev"><label class="ropt"><input type="checkbox" data-iatt="${i.id}" ${fk("att")} ${i.attested ? "checked" : ""} ${ok ? "disabled" : ""}><span>I confirm this work was delivered and I take responsibility for saying so.</span></label>
      <button type="button" class="btn sm" data-evtoggle="${i.id}" ${fk("evt")} ${ok ? "disabled" : ""} aria-expanded="${S.cr.ev.has(i.id)}">Link Git commits as evidence (${i.commits.length} selected)</button>
      ${S.cr.ev.has(i.id) && !ok ? `<div class="evlist" role="group" aria-label="Commits supporting item ${n}">${S.prev.commits.length ? S.prev.commits.map(c => `<label class="ropt"><input type="checkbox" data-icommit="${i.id}" value="${esc(c[0])}" ${fk("cm" + c[0].slice(0, 7))} ${i.commits.includes(c[0]) ? "checked" : ""}><span><span class="mono">${esc(c[0].slice(0, 7))}</span> ${esc(c[2])} <span class="note">${esc(c[1])}</span></span></label>`).join("") : '<p class="note">No commits in this period.</p>'}</div>` : ""}</div>` : "";
  return `<div class="ritem ${ok ? "ok" : "draft"}" data-iid="${i.id}"><div class="rtop"><b>Item ${n}</b>${ok ? '<span class="badge teal">Approved</span>' : '<span class="badge bad">Not approved: will not be shared</span>'}
      <span class="rbtns"><button type="button" class="btn sm" data-iup="${i.id}" ${fk("up")} aria-label="Move item ${n} up" ${n === 1 ? "disabled" : ""}>↑</button><button type="button" class="btn sm" data-idown="${i.id}" ${fk("dn")} aria-label="Move item ${n} down" ${n === total ? "disabled" : ""}>↓</button>
      ${ok ? `<button type="button" class="btn sm" data-iedit="${i.id}" ${fk("ed")} aria-label="Edit item ${n}">Edit item</button>` : ""}<button type="button" class="btn sm" data-irm="${i.id}" ${fk("rm")} aria-label="Remove item ${n}">Remove item</button></span></div>
    ${ok ? `<p class="rtext">${esc(i.text)}</p>` : `<textarea data-itext="${i.id}" ${fk("t")} rows="2" maxlength="400" placeholder="Describe the work in words your client would use. No code, file names, links or secrets." aria-label="Client-facing description for item ${n}">${esc(i.text)}</textarea>`}
    <div class="rmeta"><label>Status <select data-istatus="${i.id}" ${fk("st")} ${ok ? "disabled" : ""}><option value="in_progress" ${i.status === "in_progress" ? "selected" : ""}>In progress</option><option value="delivered" ${i.status === "delivered" ? "selected" : ""}>Delivered (needs evidence)</option></select></label>
      ${ok ? "" : `<button type="button" class="btn dark sm" data-iappr="${i.id}" ${fk("ap")} ${why ? "disabled" : ""} ${why ? `aria-describedby="why-${i.id}"` : ""}>Approve item</button>`}</div>${ev}
    ${why ? `<p class="why-off" id="why-${i.id}">${esc(why)}</p>` : ""}</div>`;
}
function vClient() {
  const P = S.prev, c = S.cr, cs = P.check_stats, hasChecks = P.n_checks > 0;
  const done = [true, !!c.project.trim() && crApproved().length > 0, !!(c.res && c.res.ok) && !pendingHigh().length, !!c.token, !!S.lastExport];
  const now = done.findIndex(x => !x);
  const steps = ["Private evidence", "Prepare client summary", "Privacy review", "Client preview", "Export"];
  const rq = P.requests.slice(0, 30);
  return `<div><div class="ph"><div><h2>Report Studio <span class="chip">${esc(P.project)}</span></h2><p>${esc(P.period)} · Only information you approve here can reach the client report.</p></div>
    <div class="act"><button class="btn" id="cr-preview" data-fk="crprev" ${c.busy ? "disabled" : ""}>${c.busy === "preview" ? "Checking…" : "Preview client report"}</button><button class="btn" id="cr-review" data-fk="crrev" ${c.res && c.res.ok ? "" : "disabled"}>Review sharing</button><button class="btn dark" id="cr-export" data-fk="crexp" ${c.token && !S.exporting ? "" : "disabled"}>${ic("dl")} Export client report</button></div></div>
  ${modeSwitch()}
  <div class="callout ok"><div><b>Client-Safe Report — Only approved information will be shared.</b> Your prompts, commit messages, commands, file names and logs stay private. Automatic checks reduce mistakes but cannot guarantee that nothing confidential remains, so read the preview before you approve it.</div></div>
  <ol class="flow" aria-label="Client report steps">${steps.map((t, i) => `<li class="${done[i] ? "done" : i === now ? "now" : ""}"${i === now ? ' aria-current="step"' : ""}><span class="n">${done[i] ? "✓" : i + 1}</span>${t}</li>`).join("")}</ol>
  ${exportCard()}
  <div class="card sec"><h3>Report details <span class="chip">typed by you</span></h3><div class="grid gform">
    <label class="field">Project name for the client<input id="crproj" maxlength="80" value="${esc(c.project)}" placeholder="The name your client knows" autocomplete="off" spellcheck="false"><small>Never filled in from your folder or repository name.</small></label>
    <label class="field">Client name (optional)<input id="crclient" maxlength="80" value="${esc(c.client)}" placeholder="Acme Co" autocomplete="off" spellcheck="false"></label>
    <div class="field"><label class="ropt"><input type="checkbox" id="crprepchk" data-fk="prepchk" ${c.showPrep ? "checked" : ""}><span>Show “Prepared by” on the report</span></label><input id="crprep" maxlength="80" value="${esc(c.prep)}" placeholder="Your name" ${c.showPrep ? "" : "disabled"} aria-label="Prepared by" autocomplete="off" spellcheck="false"><small>Off by default. Your name is only included if you turn this on.</small></div></div></div>
  <div class="card sec"><h3>Client summary <span class="chip">${crApproved().length} approved of ${c.items.length}</span></h3>
    <p class="note" style="margin-bottom:10px">Write each item in plain language. Only <b>approved</b> items are shared. A Delivered item needs evidence; a request alone never counts as completed work.</p>
    ${c.items.length ? c.items.map((i, k) => crItemHTML(i, k + 1, c.items.length)).join("") : '<div class="empty" style="padding:14px"><b>No items yet</b>Add an item, or start from your private evidence below.</div>'}
    <div class="dact"><button class="btn" id="cr-add" data-fk="add">${ic("plus")} Add item</button></div></div>
  <div class="card sec"><h3>Start from your private evidence <span class="chip">private</span></h3>
    <p class="note" style="margin-bottom:8px">${P.requests.length} request${P.requests.length === 1 ? "" : "s"}, ${P.n_commits} commit${P.n_commits === 1 ? "" : "s"} and ${P.n_checks} recorded check${P.n_checks === 1 ? "" : "s"} are available only to you. “Use as starting point” copies one request’s masked wording into a <b>new, unapproved</b> item for you to rewrite. Nothing is copied automatically.</p>
    ${rq.length ? `<div class="reqs">${rq.map(r => `<div class="req"><span class="no">${r.i + 1}</span><div class="tx" style="cursor:default">${esc(r.title)}</div><span class="badge" title="Source AI tool">${esc(r.source || "")}</span><button type="button" class="btn sm" data-use="${esc(r.key)}" aria-label="Use request ${r.i + 1} as a starting point">Use as starting point</button></div>`).join("")}</div>${P.requests.length > rq.length ? `<p class="note" style="margin-top:6px">Showing the first ${rq.length} of ${P.requests.length}. Add items by hand for the rest.</p>` : ""}` : '<div class="empty" style="padding:14px"><b>No requests in this period</b></div>'}</div>
  <div class="card sec"><h3>Verification statement</h3><fieldset class="rgroup"><legend class="note">What should the report say about testing?</legend>
    <label class="ropt"><input type="radio" name="crv" value="none" ${c.vmode === "none" ? "checked" : ""}><span>No verification statement</span></label>
    <label class="ropt"><input type="radio" name="crv" value="auto" ${c.vmode === "auto" ? "checked" : ""} ${hasChecks ? "" : "disabled"}><span>Counts only: ${hasChecks ? `${cs.ok} of ${P.n_checks} recorded checks finished without a reported error` : "no checks were recorded in this period"}. No commands or output.</span></label>
    <label class="ropt"><input type="radio" name="crv" value="custom" ${c.vmode === "custom" ? "checked" : ""}><span>My own wording</span></label></fieldset>
    ${c.vmode === "custom" ? `<textarea id="crvtext" rows="2" maxlength="300" aria-label="Verification wording" placeholder="e.g. Checkout flow tested on desktop and mobile before delivery." style="width:100%;margin-top:8px;border:1px solid var(--line-2);border-radius:10px;background:var(--surface);padding:8px 10px;font-size:13.5px">${esc(c.vtext)}</textarea>` : ""}
    <p class="note" style="margin-top:8px">Counts come from commands recorded in your session logs. They were not re-run for this report, and the report says so.</p></div>
  <div class="card sec"><h3>Privacy review</h3><div id="crstatus">${crStatusHTML()}</div>
    <p class="note" style="margin-top:12px"><b>Never exported:</b> ${CR_EXCLUDED.map(esc).join("; ")}.</p>
    <p class="note" style="margin-top:6px">Reviewing a secret finding in the Privacy Center does not approve anything for the client report. The two approvals are separate, and both are required.</p>
    ${S.data.chrome ? `<label class="ropt" style="margin-top:10px"><input type="checkbox" id="crpdf" ${c.pdf ? "checked" : ""}><span>Also create a PDF (checked against the approved content before it is saved)</span></label>` : '<p class="note" style="margin-top:8px">PDF export is not available here; the HTML report can be printed to PDF.</p>'}</div>
  <div class="card sec"><h3>Client preview <span class="chip">exact export</span></h3><div id="crprevcard">${crPreviewHTML()}</div></div></div>`;
}
async function crDoPreview() {
  const c = S.cr; c.busy = "preview"; renderKeep();
  try {
    const r = await api("/api/client/preview", crBody());
    if (c.token && r.content_hash !== c.hash) { c.token = null; c.hash = null; c.cleared = true; }
    c.res = r;
  } catch (e) { toast(e.message); }
  c.busy = ""; cache.screen = null; render();
  const card = $("#crprevcard"); if (card) card.closest(".card").scrollIntoView({ block: "start" });
  return !!(c.res && c.res.ok);
}
async function crReview() {
  const c = S.cr;
  if (!(c.res && c.res.ok) && !(await crDoPreview())) { toast("Fix the problems listed in the Privacy review first"); return; }
  if (pendingHigh().length) { toast("Review high-severity findings first"); go("privacy"); return; }
  S.dlg = { kind: "crreview", ack: false }; showDlg();
}
async function crApprove() {
  const g = S.dlg, c = S.cr; if (!g || !g.ack || !c.res || !c.res.ok) return;
  try {
    const r = await api("/api/client/approve", { ...crBody(), confirm: { privacy_review: true, content_hash: c.res.content_hash } });
    if (r._status === 409 || !r.ok) { c.res = null; c.token = null; c.hash = null; toast(r.message || "Approval was refused. Preview again."); }
    else { c.token = r.token; c.hash = r.content_hash; c.cleared = false; toast("Approved for sharing"); }
  } catch (e) { toast(e.message); }
  closeDlg(); cache.screen = null; render();
}
async function crExport() {
  const c = S.cr; if (!c.token) { toast("Preview and approve the client report first"); return; }
  S.exporting = true; S.exportFail = ""; S.lastExport = null; renderKeep();
  try {
    const r = await api("/api/client/export", { ...crBody(), token: c.token, pdf: !!(c.pdf && S.data.chrome) });
    if (r._status === 409 || !r.ok) {
      S.exportFail = r.message || "Export was blocked. Nothing was saved.";
      if (r.reason === "approval") { c.token = null; c.hash = null; c.cleared = true; }
      if (r.reason === "findings") go("privacy");
    } else { S.lastExport = r; await loadState(); }
  } catch (e) { S.exportFail = e.message || "The client report could not be exported."; }
  S.exporting = false; cache.screen = null; render();
}
const crNext = () => (S.cr.token ? crExport() : crReview());

/* ---------- Privacy Center ---------- */
function vPrivacy() {
  const P = S.prev;
  const termsCard = `<div class="card"><h3>Custom redaction terms</h3><div style="display:flex;gap:8px"><input id="term" class="field" style="flex:1;height:34px;border:1px solid var(--line-2);border-radius:10px;background:var(--surface);padding:0 11px;font-size:13px" placeholder="Client or product name to mask everywhere" spellcheck="false"><button class="btn" id="addterm">Add</button></div>
    <div class="tags">${S.terms.map((t, i) => `<span class="tag">${esc(t)}<button data-rmterm="${i}" aria-label="Remove ${esc(t)}">×</button></span>`).join("")}${(S.data.settings.redact_terms || []).map(t => `<span class="tag" title="Saved in Settings">${esc(t)} <span class="badge teal">saved</span></span>`).join("")}</div>
    <p class="note" style="margin-top:8px">Terms are matched case-insensitively and always count as high severity. ${S.repo ? "Adding a term re-scans the loaded project." : ""}</p></div>`;
  if (!P) return `<div><div class="ph"><div><h2>Privacy Center</h2><p>Review everything that was masked before you export.</p></div></div><div class="card"><div class="empty"><b>Nothing to review yet</b>Load a project's activity and every masked value will be listed here.<br><button class="btn dark" data-go="projects">Choose a project</button></div></div><div class="sec">${termsCard}</div></div>`;
  const F = P.findings.filter(f => f.severity !== "high" || f.actionable > 0 || S.showCleared), nCleared = highD().filter(d => d.suppressed).length, H = needsReview(), done = H.length - pendingHigh().length, sv = k => k === "high" ? H.length : F.filter(f => f.severity === k).reduce((a, f) => a + f.count, 0);
  return `<div><div class="ph"><div><h2>Privacy Center <span class="chip">${esc(P.project)}</span></h2><p>Values stay masked unless you choose to reveal one. Each high-severity detection needs your own review before export.</p></div></div>
  <div class="grid g4">
    <div class="card stat"><div class="k"><span><span class="sev high"></span> High</span></div><div class="v">${sv("high")}</div><div class="d">detections to review before export</div></div>
    <div class="card stat"><div class="k"><span><span class="sev medium"></span> Medium</span></div><div class="v">${sv("medium")}</div><div class="d">e.g. email addresses</div></div>
    <div class="card stat"><div class="k"><span><span class="sev low"></span> Low</span></div><div class="v">${sv("low")}</div><div class="d">paths, IP addresses</div></div>
    <div class="card stat"><div class="k">Export approval</div><div class="v">${H.length ? `${done}/${H.length}` : "Clear"}</div><div class="prog"><i style="width:${H.length ? done / H.length * 100 : 100}%"></i></div><div class="d">${H.length ? (done === H.length ? "all high-severity reviewed" : "reviewed") : "no high-severity findings"}</div></div></div>
  ${H.length && done < H.length ? `<div class="callout sec"><div><b>Check each high-severity item in your own files before approving.</b> If a masked value was a real credential, rotate it. Reviewing records your decision; it does not make anything safe and never unmasks the report. Automatic redaction is best-effort and not a guarantee of confidentiality.</div></div>` : ""}
  <div class="card sec"><h3>Masked values <span class="chip">${F.length}</span>${nCleared ? ` <button type="button" class="btn" id="togglecleared" aria-pressed="${S.showCleared}" style="margin-left:auto">${S.showCleared ? "Hide" : "Show"} ${nCleared} automatically cleared</button>` : ""}</h3>${nCleared && !S.showCleared ? `<p class="note">${nCleared} high-severity detection(s) were proven harmless by narrow syntax rules (code fragments, variable references, published examples) and cleared automatically. They remain masked in the report.</p>` : ""}${F.length ? F.map(f => { const hi = f.severity === "high", op = hi && S.open.has(f.id), dets = f.detections.filter(d => !d.suppressed || S.showCleared).sort((a, b) => (PRIO[a.class?.category] ?? 2) - (PRIO[b.class?.category] ?? 2) || a.n - b.n), nrev = f.detections.filter(d => !d.suppressed && S.disp[d.id]).length;
    const head = `<span class="badge ${f.severity}"><span class="sev ${f.severity}"></span>${f.severity}</span> <b>${esc(f.rule)}</b>${f.count > 1 ? ` ×${f.count}` : ""} <span class="note">${esc(f.where)}</span>${hi ? ` <span class="note">· ${nrev}/${f.actionable} reviewed${f.cleared ? `, ${f.cleared} cleared` : ""}</span>` : ""}`;
    return `<div class="grp${op ? " open" : ""}" data-gid="${f.id}">${hi ? `<button type="button" class="gh" data-toggle="${f.id}" aria-expanded="${op}" aria-controls="gp-${f.id}"><span class="chev" aria-hidden="true">${ic("arrow", 12)}</span>${head}<span class="gcta">${op ? "Hide" : "Show"} ${dets.length} detection${dets.length === 1 ? "" : "s"}</span></button>` : `<div class="gh plain">${head}</div>`}
      <div class="mono gctx">${esc(f.context)}</div>${hi ? `<div class="gp" id="gp-${f.id}" role="region" aria-label="${esc(f.rule)} detections" ${op ? "" : "hidden"}>${op ? dets.map(detRow).join("") : ""}</div>` : '<p class="note">Masked automatically; no review needed.</p>'}</div>`; }).join("") : `<div class="empty"><b>No sensitive values found</b>Nothing in this period matched a redaction rule. Read the report before sharing anyway.</div>`}</div>
  <div class="sec">${termsCard}</div>
  <div class="card sec"><h3>Client report approval <span class="chip">${S.cr.token ? "approved" : "not approved"}</span></h3><p class="note">${S.cr.token ? "The current client report is approved for sharing. Any change to its content, to this project or period, or to the findings above clears the approval." : "Reviewing a finding here does not approve anything for the client report. Approve the final client content separately in Report Studio → Client-Safe Report."}</p><div style="margin-top:10px"><button class="btn" data-go="studio">Open Report Studio ${ic("arrow")}</button></div></div>
  <div class="card sec"><h3>Export approval</h3><p class="note">${pendingHigh().length ? `${pendingHigh().length} high-severity item(s) still need review. Export is blocked, in the app and on the server, until each one is reviewed.` : "All high-severity items are reviewed. You can export from Report Studio."}</p><div style="margin-top:10px"><button class="btn teal" data-go="studio">Go to Report Studio ${ic("arrow")}</button></div></div></div>`;
}

/* ---------- Settings ---------- */
function vSettings() {
  const s = S.data.settings;
  return `<div><div class="ph"><div><h2>Settings</h2><p>Local directories, appearance and report defaults.</p></div><div class="act"><button class="btn dark" id="savesettings">Save settings</button></div></div>
  ${DESKTOP && B.state === "failed" ? `<div class="callout err"><div><b>Native folder dialog unavailable.</b> ${BRIDGE_DOWN}</div></div>` : ""}
  <div class="grid g2s"><div class="card" style="grid-column:1/-1"><h3>Local directories</h3><div class="grid"><label class="field">Claude Code folder<span class="inrow"><input id="s_claude" class="path" title="${esc(s.claude_dir)}" value="${esc(s.claude_dir)}" spellcheck="false"><button type="button" class="btn sm" data-choose="s_claude">Choose…</button></span><small>${S.data.claude_dir_ok ? "projects folder found" : "no projects folder at this location"}</small></label>
    <label class="field">Default reports folder<span class="inrow"><input id="s_out" class="path" title="${esc(s.out_dir)}" value="${esc(s.out_dir)}" spellcheck="false"><button type="button" class="btn sm" data-choose="s_out">Choose…</button></span><small>Created on first export</small></label></div></div>
  <div class="card" style="grid-column:1/-1"><h3>AI tools</h3><p class="small">Choose which tools' local session logs feed reports. Turn all off for Git-only reports. Nothing is read from a tool you leave off.</p><div class="grid">
    ${[["claude", "Claude Code", "supported", "claude_dir"], ["codex", "Codex CLI", "experimental", "codex_dir"], ["opencode", "OpenCode", "experimental", "opencode_dir"]].map(([k, n, st, dk]) => `<label class="field"><span><input type="checkbox" id="p_${k}" ${(s.providers || {})[k] ? "checked" : ""}> ${n} <small>(${st})</small></span>${k === "claude" ? "" : `<input id="s_${dk}" class="path" value="${esc(s[dk] || "")}" spellcheck="false">`}</label>`).join("")}
    <small>Cursor is not supported: it has no documented local transcript format. Git-only reports work for any repository.</small></div></div>
  <div class="card"><h3>Appearance</h3><div class="seg" id="s_theme">${["system", "light", "dark"].map(t => `<button data-theme="${t}" class="${s.theme === t ? "on" : ""}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div></div>
  <div class="card"><h3>Report defaults</h3><div class="grid"><label class="field">Prepared by<input id="s_author" value="${esc(s.author)}" placeholder="Your name"></label><label class="field">Default client<input id="s_client" value="${esc(s.client)}" placeholder="Optional"></label></div></div></div>
  <div class="card sec"><h3>Always-redact terms</h3><label class="field"><span>One per line. Saved on this computer and applied to every report.</span><textarea id="s_terms" rows="4" style="border:1px solid var(--line-2);border-radius:10px;background:var(--surface);padding:9px 11px;font-size:13px;resize:vertical" spellcheck="false">${esc((s.redact_terms || []).join("\n"))}</textarea></label></div>
  <div class="card sec"><h3>About this app</h3><div class="grid gform"><div class="note"><b>Version</b><br>WorkReceipt ${esc(S.data.version)}</div><div class="note"><b>Engine</b><br>Local Python report engine · native macOS window</div><div class="note"><b>Server</b><br>${esc(location.host)} — this computer only</div><div class="note"><b>Data</b><br>Settings and history: <span class="mono path-txt">${esc(S.data.home)}</span></div></div></div>
  <div class="card sec"><h3>Privacy &amp; storage</h3><p class="note">Everything runs on this computer. No account, no telemetry, no uploads, no AI service. Detected secrets are never stored: settings and report history hold only project names, dates, counts and file paths. Local data: <span class="mono">${esc(S.data.home)}</span>. Reports are saved to your reports folder.</p></div>
  ${DESKTOP ? `<div class="card sec"><h3>Diagnostics <button type="button" class="btn sm" id="diagretry" style="margin-left:auto">Check again</button></h3><p class="note" id="diag">Native services: <b>${B.state === "ready" ? "ready" : B.state === "failed" ? "not responding" : "starting"}</b>${B.info ? ` · pywebview ${esc(B.info.pywebview || "?")} · ${esc(B.info.platform || "")} · window ${B.info.window ? "created" : "missing"} · shown ${B.info.shown ? "yes" : "no"}${B.info.reason ? " · " + esc(B.info.reason) : ""}` : ""}</p></div>` : ""}
  <div class="card sec"><h3>Updates</h3><p class="note">Manual updates: download the newest WorkReceipt from its release page, open the disk image and drag the app to Applications, replacing the old one. Your settings and reports are kept. This app does not check for updates automatically.</p></div>
  <div class="card sec"><h3>PDF export</h3><p class="note">${S.data.chrome ? "“Export report” creates an HTML file and a PDF. The PDF is made from the already-masked HTML, on this computer." : "PDF export is not available in this environment. Open the exported HTML and use Print → Save as PDF."}</p></div></div>`;
}

/* ---------- Reports library ---------- */
function vReports() {
  const q = S.q.trim().toLowerCase();
  const all = S.data.history, list = all.filter(h => (!q || (h.project + " " + (h.client || "")).toLowerCase().includes(q)) && (!S.rf || h.at.slice(0, 10) >= S.rf) && (!S.rt || h.at.slice(0, 10) <= S.rt));
  return `<div><div class="ph"><div><h2>Reports <span class="chip">${all.length}</span></h2><p>Reports exported from this app, stored on this computer.</p></div><div class="act"><button class="btn dark" id="genreport">${ic("doc")} New report</button></div></div>
  <div class="card"><div class="grid gform"><label class="field">Search project or client<input id="rq" type="search" value="${esc(S.q)}" placeholder="Search" spellcheck="false"></label><label class="field">From<input type="date" id="rf" value="${esc(S.rf)}"></label><label class="field">To<input type="date" id="rt" value="${esc(S.rt)}"></label></div></div>
  <div class="card sec">${list.length ? `<table class="tbl"><thead><tr><th>Project</th><th class="hide-m">Client</th><th>Period</th><th class="hide-m">Items</th><th>Exported</th><th></th></tr></thead><tbody>${list.map(h => { const n = esc(h.html.split(/[\\/]/).pop()); return `<tr><td><b style="font-weight:500">${esc(h.project)}</b> ${h.mode === "client" ? '<span class="badge teal">Client-safe</span>' : '<span class="badge">Developer · private</span>'}</td><td class="hide-m">${esc(h.client || "—")}</td><td class="mono">${esc(h.period)}</td><td class="hide-m">${h.mode === "client" ? `${h.requests} approved item${h.requests === 1 ? "" : "s"}` : `${h.requests} req · ${h.commits} commits`}</td><td>${esc(h.at)}</td>
    <td style="text-align:right;white-space:nowrap"><button class="btn sm" data-open="${esc(fname(h.html))}" data-kind="html">Open</button> ${h.pdf ? `<button class="btn sm" data-open="${esc(fname(h.pdf))}" data-kind="pdf">PDF</button> ` : ""}<button class="btn sm" data-showfile="${esc(fname(h.html))}" data-kind="html">Show in Finder</button> <button class="btn sm" data-delrep="${n}" aria-label="Delete report ${esc(h.project)}">Delete</button></td></tr>`; }).join("")}</tbody></table>` :
    `<div class="empty"><b>${all.length ? "No reports match" : "No reports yet"}</b>${all.length ? "Clear the search or date filters." : "Export a report from Report Studio and it will be listed here."}</div>`}</div></div>`;
}

/* ---------- Onboarding ---------- */
const OB = [
  ["Welcome to WorkReceipt", "Turn your Claude Code sessions and Git history into a clear report your client can read. No account and no sign-in."],
  ["Private by design", "Everything is analysed on this computer. Nothing is uploaded, there is no telemetry and no AI service is called. Secrets are masked, and every high-severity one needs your review before a report can be exported."],
  ["Choose your first project", "Pick a project folder, or explore with a synthetic demo project that contains no real data. You can add more later."],
];
function obHTML() {
  const o = S.ob; if (!o) return "";
  const [h, p] = OB[o.step];
  const body = o.step === 2 ? `<div class="dact" style="flex-direction:column;align-items:stretch"><button class="btn teal lg" id="obpick">Select project folder…</button><button class="btn lg" id="obdemo">${o.busy ? "Creating demo…" : "Try the demo project"}</button>${o.err ? `<p class="note" style="color:var(--red)">${esc(o.err)}</p>` : ""}</div>` : "";
  return `<div class="ovl ob" role="dialog" aria-modal="true" aria-label="Welcome"><div class="dlgbox"><div class="steps" aria-hidden="true">${OB.map((_, i) => `<i class="${i <= o.step ? "on" : ""}"></i>`).join("")}</div><h3>${h}</h3><p class="note" style="font-size:14px;margin:8px 0 14px">${p}</p>${body}
  <div class="dact">${o.step > 0 ? '<button class="btn" id="obback">Back</button>' : ""}${o.step < 2 ? '<button class="btn dark" id="obnext">Continue</button>' : '<button class="btn" id="obskip">Finish setup</button>'}</div></div></div>`;
}
function showOb() { const r = $("#obroot"); r.innerHTML = obHTML(); syncPickers(); r.querySelector("button.dark,button.teal,button")?.focus(); }
async function finishOb(go_) {
  if (S.ob?.finishing) return;                         // a double click must not start a second save
  if (S.ob) S.ob.finishing = true;
  // Persist FIRST and close the dialog after: closing before the save landed left a window (slow disk, slow Mac) in which "setup finished" was
  // visible but not stored, so a quit right then showed onboarding again, and tests that read the settings right after the close raced the save.
  try { S.data.settings = await api("/api/settings", { onboarded: true }); } catch (e) { toast(e.message); }
  S.ob = null; showOb();
  go(go_ || "overview");
}

const VIEWS = { overview: vOverview, projects: vProjects, studio: vStudio, privacy: vPrivacy, reports: vReports, settings: vSettings };
function render() {
  if (!S.data) return;
  renderChrome();
  setHTML($("#screen"), (VIEWS[S.tab] || vOverview)());   // unchanged screen keeps its DOM (focus, preview, edits)
  fitFrame(); syncPickers();
}
function fitFrame() {
  const f = $(".frame"); if (!f) return;
  const fit = () => { try { f.style.height = Math.max(420, f.contentDocument.documentElement.scrollHeight + 8) + "px"; } catch (e) { } };
  f.addEventListener("load", fit, { once: true }); fit();
}
addEventListener("resize", () => fitFrame());

/* ---------- actions ---------- */
async function loadState() { S.data = await api("/api/state"); S.loadedAt = Date.now(); applyTheme(); }
async function autoRefresh() {                           // when the window regains focus after a while (projects/reports may have changed on disk)
  if (!S.data || S.dlg || S.ob || document.hidden || Date.now() - (S.loadedAt || 0) < 20000) return;
  try { await loadState(); render(); } catch (e) { }
}
addEventListener("focus", autoRefresh); document.addEventListener("visibilitychange", autoRefresh);
async function load() {
  S.loading = true; S.err = ""; S.html = null; S.lastExport = null; S.exportFail = ""; render();
  try {
    S.prev = await api("/api/preview", opts()); { const ids = new Set(highD().map(d => d.id)); for (const k of Object.keys(S.disp)) if (!ids.has(k)) delete S.disp[k]; }
    S.titles = {};
    { const c = S.cr, have = new Set(S.prev.commits.map(x => x[0])); c.items.forEach(i => { i.commits = i.commits.filter(h => have.has(h)); if (i.approved && i.status === "delivered" && !i.commits.length && !i.attested) i.approved = false; }); c.res = null; c.token = null; c.hash = null; }
  } catch (e) { S.err = e.message; S.prev = null; }
  S.loading = false; render();
  if (S.prev) toast(`Loaded ${S.prev.requests.length} requests, ${S.prev.n_commits} commits`);
}
async function makePreview() {
  try { S.html = (await api("/api/render", { ...opts(), titles: S.titles })).html; } catch (e) { toast(e.message); }
  cache.screen = null; render();                       // force a fresh iframe so it starts at the top, not at an old scroll position
  const f = $(".frame"); if (f) { try { f.contentWindow.scrollTo(0, 0); } catch (e) { } f.closest(".card").scrollIntoView({ block: "start" }); $("#screen").scrollTop = Math.max(0, $("#screen").scrollTop - 8); }
}
async function doExport() {
  if (pendingHigh().length) { toast("Review high-severity findings first"); go("privacy"); return; }
  S.exporting = true; S.exportFail = ""; S.lastExport = null; render();
  try {
    const r = await api("/api/export", { ...opts(), titles: S.titles, approved: S.disp, pdf: S.data.chrome });
    if (r._status === 409) { toast("Export blocked: high-severity findings need review"); go("privacy"); }
    else { S.lastExport = r; await loadState(); if (r.edits_dropped) toast(`${r.edits_dropped} edit(s) skipped: that request is no longer in the logs`); }
  } catch (e) { S.exportFail = e.message || "The report could not be exported."; }
  S.exporting = false; render();
}
async function saveSettings(msg) {                  // persists every Settings field; used by Save and by each "Choose…" pick
  try {
    S.data.settings = await api("/api/settings", { claude_dir: $("#s_claude").value.trim(), out_dir: $("#s_out").value.trim(), author: $("#s_author").value.trim(), client: $("#s_client").value.trim(),
      theme: S.data.settings.theme, codex_dir: $("#s_codex_dir").value.trim(), opencode_dir: $("#s_opencode_dir").value.trim(),
      providers: Object.fromEntries(["claude", "codex", "opencode"].map(k => [k, $("#p_" + k).checked])), redact_terms: $("#s_terms").value.split("\n") });
    await loadState(); if (!S.author) S.author = S.data.settings.author; if (!S.client) S.client = S.data.settings.client;
    const typed = ["s_author", "s_client", "s_terms"].map(id => [id, document.getElementById(id)]).filter(x => x[1]).map(x => [x[0], x[1].value]);   // text typed while the save was in flight
    cache.screen = null; render();
    typed.forEach(([id, v]) => { const el = document.getElementById(id); if (el) el.value = v; });                                                       // must survive the re-render
    toast(msg);
  } catch (er) { toast(er.message); }
}
function rangeFor(k) {
  const now = new Date();
  if (k === "all") return ["", ""];
  if (k === "month") return [iso(new Date(now.getFullYear(), now.getMonth(), 1)), iso(now)];
  return [iso(new Date(now - (+k - 1) * 864e5)), iso(now)];
}
function activeRange() { for (const k of ["7", "30", "90", "month", "all"]) { const [a, b] = rangeFor(k); if (S.since === a && S.until === b) return k; } return ""; }
function setRange(k) {
  const now = new Date();
  if (k === "all") { S.since = ""; S.until = ""; } else if (k === "month") { S.since = iso(new Date(now.getFullYear(), now.getMonth(), 1)); S.until = iso(now); }
  else { S.since = iso(new Date(now - (+k - 1) * 864e5)); S.until = iso(now); }
}
function pick(path) { S.repo = path; S.repoDraft = null; S.prev = null; S.html = null; S.cr = newCR(); S.err = ""; S.lastExport = null; render(); }
async function rescan() { if (S.repo) { await load(); } else render(); }

document.addEventListener("click", async e => {
  const t = e.target.closest("[data-mode],[data-iappr],[data-iedit],[data-irm],[data-iup],[data-idown],[data-use],[data-evtoggle],[data-open],[data-showfile],[data-delrep],[data-rmproj],[data-choose],[data-go],[data-pick],[data-range],[data-rmterm],button[data-theme],[data-toggle],[data-reveal],[data-review],[data-close],button[id]");
  if (!t) return;
  if (t.dataset.mode) { S.mode = t.dataset.mode === "private" ? "private" : "client"; cache.screen = null; render(); $("#mode-" + S.mode)?.focus({ preventScroll: true }); return; }
  if (t.dataset.iappr) { const i = crItem(t.dataset.iappr); if (i && !crWhy(i)) { i.approved = true; i.text = i.text.trim(); S.cr.ev.delete(i.id); crInvalidate(); renderKeep(); } return; }
  if (t.dataset.iedit) { const i = crItem(t.dataset.iedit); if (i) { i.approved = false; crInvalidate(); cache.screen = null; render(); $(`[data-fk="t-${i.id}"]`)?.focus(); } return; }
  if (t.dataset.irm) { const k = S.cr.items.findIndex(i => String(i.id) === t.dataset.irm); if (k >= 0) { S.cr.items.splice(k, 1); crInvalidate(); cache.screen = null; render(); $("#cr-add")?.focus(); toast("Item removed"); } return; }
  if (t.dataset.iup || t.dataset.idown) { const id = t.dataset.iup || t.dataset.idown, a = S.cr.items, k = a.findIndex(i => String(i.id) === id), j = t.dataset.iup ? k - 1 : k + 1; if (k >= 0 && j >= 0 && j < a.length) { [a[k], a[j]] = [a[j], a[k]]; crInvalidate(); renderKeep(); } return; }
  if (t.dataset.use) { const r = S.prev.requests.find(x => x.key === t.dataset.use); if (r) { const id = S.cr.nid++; S.cr.items.push({ id, text: r.title, status: "in_progress", commits: [], attested: false, approved: false }); cache.screen = null; render(); $(`[data-fk="t-${id}"]`)?.focus(); toast("Added as a draft. Rewrite it for your client, then approve it."); } return; }
  if (t.dataset.evtoggle) { const id = +t.dataset.evtoggle; S.cr.ev.has(id) ? S.cr.ev.delete(id) : S.cr.ev.add(id); renderKeep(); return; }
  if (t.dataset.open) return openFile(t.dataset.open, t.dataset.kind);
  if (t.dataset.showfile) return revealFile(t.dataset.showfile, t.dataset.kind);
  if (t.dataset.delrep) { S.dlg = { kind: "delrep", name: t.dataset.delrep }; return showDlg(); }
  if (t.dataset.rmproj) { S.dlg = { kind: "rmproj", path: t.dataset.rmproj }; return showDlg(); }
  if (t.dataset.choose) { const v = await pickFolder(); if (v) { $("#" + t.dataset.choose).value = v; await saveSettings("Folder saved"); } else if (!DESKTOP) toast("Type or paste the folder path"); return; }
  if (t.dataset.toggle) { const id = t.dataset.toggle; S.open.has(id) ? S.open.delete(id) : S.open.add(id); return render(); }
  if (t.dataset.close) return closeDlg();
  if (t.dataset.reveal) return doReveal(t.dataset.reveal);
  if (t.dataset.review) { S.dlg = { kind: "review", id: t.dataset.review, pick: S.disp[t.dataset.review] || "", ack: false }; return showDlg(); }
  if (t.dataset.go) { e.preventDefault(); return go(t.dataset.go); }
  if (t.dataset.pick) return pick(t.dataset.pick);
  if (t.dataset.range) { setRange(t.dataset.range); return render(); }
  if (t.dataset.rmterm != null) { S.terms.splice(+t.dataset.rmterm, 1); return rescan(); }
  if (t.dataset.theme) { S.data.settings.theme = t.dataset.theme; applyTheme(); return render(); }
  switch (t.id) {
    case "theme": S.data.settings.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark"; applyTheme(); cache.screen = null; render(); api("/api/settings", { theme: S.data.settings.theme }); break;
    case "addproj": await addProjectFlow(); break;
    case "refresh": await loadState(); render(); toast("Project list refreshed"); break;
    case "genreport": if (S.prev) go("studio"); else if (S.repo) { go("projects"); await load(); } else { go("projects"); toast("Select a project, then Load activity"); } break;
    case "openrecent": { const h = S.data.history[0]; if (h) openFile(fname(h.html), "html"); break; }
    case "obnext": S.ob.step++; showOb(); break;
    case "obback": S.ob.step--; showOb(); break;
    case "obskip": await finishOb("overview"); break;
    case "obpick": { const path = await pickFolder(); if (!path) { S.ob.err = pickFolder.failed ? BRIDGE_DOWN : DESKTOP ? "" : "Folder dialog is only available in the desktop app. Skip, then use Add project."; showOb(); break; }
      try { const r = await api("/api/project/add", { path }); await loadState(); pick(r.path); await finishOb("projects"); } catch (er) { S.ob.err = er.message; showOb(); } break; }
    case "obdemo": { S.ob.busy = true; S.ob.err = ""; showOb(); try { await api("/api/demo", {}); await loadState(); const d = S.data.projects.find(x => x.demo); if (d) pick(d.path); await finishOb("projects"); } catch (er) { S.ob.busy = false; S.ob.err = er.message; showOb(); } break; }
    case "confirmdel": { const g = S.dlg; closeDlg(); try { if (g.kind === "delrep") await api("/api/report/delete", { name: g.name, confirm: true }); else { await api("/api/project/remove", { path: g.path }); if (S.repo === g.path) { S.repo = ""; S.prev = null; S.html = null; } } await loadState(); render(); toast(g.kind === "delrep" ? "Report deleted" : "Project removed from WorkReceipt"); } catch (er) { toast(er.message); } break; }
    case "usepath": { const v = $("#repo").value.trim(); if (v) pick(v); break; }
    case "load": syncForm(); await load(); break;
    case "preview": case "preview2": await makePreview(); break;
    case "export": await doExport(); break;
    case "retryexp": await (S.mode === "client" ? crExport() : doExport()); break;
    case "cr-add": { const id = S.cr.nid++; S.cr.items.push({ id, text: "", status: "in_progress", commits: [], attested: false, approved: false }); cache.screen = null; render(); $(`[data-fk="t-${id}"]`)?.focus(); break; }
    case "cr-preview": case "cr-preview2": await crDoPreview(); break;
    case "cr-review": await crReview(); break;
    case "crconfirm": await crApprove(); break;
    case "cr-export": await crExport(); break;
    case "togglecleared": S.showCleared = !S.showCleared; render(); break;
    case "confirmrev": { const g = S.dlg; if (g?.pick && g.ack) { S.disp[g.id] = g.pick; closeDlg(); render(); toast("Review recorded"); } break; }
    case "addterm": { const v = $("#term").value.trim(); if (v) { S.terms.push(v); await rescan(); } break; }
    case "diagretry": B.state = "wait"; await nativeCheck(); if (B.state !== "ready") B.state = "failed"; cache.screen = null; render(); toast(B.state === "ready" ? "Native services are ready" : BRIDGE_DOWN); break;
    case "savesettings": await saveSettings("Settings saved"); break;
  }
});
document.addEventListener("change", e => {
  const d = e.target.dataset || {};
  if (d.istatus) { const i = crItem(d.istatus); if (i && !i.approved) { i.status = e.target.value; if (i.status !== "delivered") { i.commits = []; i.attested = false; } renderKeep(); } }
  else if (d.iatt) { const i = crItem(d.iatt); if (i && !i.approved) { i.attested = e.target.checked; renderKeep(); } }
  else if (d.icommit) { const i = crItem(d.icommit); if (i && !i.approved) { const h = e.target.value; i.commits = e.target.checked ? [...new Set([...i.commits, h])] : i.commits.filter(x => x !== h); renderKeep(); } }
  else if (e.target.id === "crprepchk") { S.cr.showPrep = e.target.checked; crInvalidate(); renderKeep(); }
  else if (e.target.name === "crv") { S.cr.vmode = e.target.value; crInvalidate(); renderKeep(); }
  else if (e.target.id === "crpdf") S.cr.pdf = e.target.checked;
  else if (S.dlg?.kind === "crreview" && e.target.id === "crack") { S.dlg.ack = e.target.checked; $("#crconfirm").disabled = !S.dlg.ack; }
  if (S.dlg?.kind === "review" && (e.target.name === "disp" || e.target.id === "ack")) {      // update in place so keyboard focus stays put
    if (e.target.name === "disp") S.dlg.pick = e.target.value; else S.dlg.ack = e.target.checked;
    const ok = !!(S.dlg.pick && S.dlg.ack), b = $("#confirmrev"), h = $("#rvhint");
    b.disabled = !ok; h.hidden = ok;
    h.textContent = !S.dlg.pick && !S.dlg.ack ? "Select a classification and tick the acknowledgement to enable Confirm review." : !S.dlg.pick ? "Select a classification to enable Confirm review." : "Tick the required acknowledgement to enable Confirm review.";
  }
});
document.addEventListener("input", e => {
  const t = e.target;
  if (t.dataset?.itext) { const i = crItem(t.dataset.itext); if (i && !i.approved) { i.text = t.value; const b = $(`[data-iappr="${i.id}"]`); if (b) b.disabled = !!crWhy(i); const w = $(`#why-${i.id}`); if (w) w.hidden = !crWhy(i); } }
  const f = { crproj: "project", crclient: "client", crprep: "prep", crvtext: "vtext" }[t.id];
  if (f) { S.cr[f] = t.value; crInvalidate(); }
  if (e.target.id === "repo") S.repoDraft = e.target.value;
  if (["rq", "rf", "rt"].includes(e.target.id)) { const id = e.target.id, pos = e.target.selectionStart; S[{ rq: "q", rf: "rf", rt: "rt" }[id]] = e.target.value; cache.screen = null; render(); const n = $("#" + id); n.focus(); try { n.setSelectionRange(pos, pos); } catch (x) { } }
  if (["since", "until", "gitauthor", "client"].includes(e.target.id)) syncForm();
  const r = e.target.dataset?.req;
  if (r != null) { const orig = S.prev.requests.find(q => q.key === r)?.title, v = e.target.textContent.trim(); if (v && v !== orig) S.titles[r] = v; else delete S.titles[r]; S.html = null; e.target.closest(".req").classList.toggle("edited", r in S.titles); }
});
/* Commands shared by keyboard shortcuts and the native menu bar (menu items call window.wrCommand). */
window.wrCommand = async c => {
  if (!S.data) return;
  if (c.startsWith("go:")) return go(c.slice(3));
  if (c === "add") return addProjectFlow();
  if (c === "refresh") { await loadState(); render(); return toast("Project list refreshed"); }
  if (c === "export") { if (!S.prev) { go("projects"); return toast("Load a project's activity first"); } go("studio"); return S.mode === "client" ? crNext() : doExport(); }
  if (c === "preview") { if (!S.prev) return toast("Load a project's activity first"); go("studio"); return S.mode === "client" ? crDoPreview() : makePreview(); }
};
document.addEventListener("keydown", e => {
  if (e.key === "Tab" && S.dlg) { const f = [...document.querySelectorAll("#dlgroot input,#dlgroot button")].filter(x => !x.disabled && x.offsetParent !== null); if (f.length) { const i = f.indexOf(document.activeElement); if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); } else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); } } }
  if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && !S.ob) {
    const nav = { 1: "overview", 2: "projects", 3: "studio", 4: "privacy", 5: "reports", ",": "settings" }[e.key];
    const cmd = nav ? "go:" + nav : { o: "add", r: "refresh", e: "export", p: "preview" }[e.key];
    if (cmd && !(e.key === "r" && e.ctrlKey && !e.metaKey)) { e.preventDefault(); window.wrCommand(cmd); return; }
  } if (e.key === "Escape" && S.dlg) closeDlg(); if (e.target.id === "term" && e.key === "Enter") $("#addterm").click(); if (e.target.id === "repo" && e.key === "Enter") $("#usepath").click(); });
function syncForm() { for (const [id, k] of [["since", "since"], ["until", "until"], ["gitauthor", "gitAuthor"], ["client", "client"], ["repo", "repo"]]) { const el = $("#" + id); if (el && id !== "repo") S[k] = el.value.trim(); } }
document.addEventListener("focusout", e => { if (["since", "until", "gitauthor", "client"].includes(e.target.id)) syncForm(); });
matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", applyTheme);


/* drag & drop a project folder (path is only available inside the desktop webview) */
addEventListener("dragover", e => { e.preventDefault(); $("#dropveil").hidden = false; });
addEventListener("dragleave", e => { if (!e.relatedTarget) $("#dropveil").hidden = true; });
addEventListener("drop", async e => {
  e.preventDefault(); $("#dropveil").hidden = true;
  const f = e.dataTransfer?.files?.[0], path = f && f.pywebviewFullPath;
  if (!path) return toast("Drag-and-drop works in the desktop app. Use Add project instead.");
  await addProjectFlow(path);
});
(async () => {
  try { await loadState(); S.author = S.data.settings.author; S.client = S.data.settings.client; $("#ver").textContent = "v" + S.data.version; }
  catch (e) { $("#screen").innerHTML = `<div class="callout err" style="margin:30px"><div>Could not reach the local WorkReceipt server: ${esc(e.message)}</div></div>`; return; }
  const h = location.hash.slice(1); if (VIEWS_OK.includes(h)) S.tab = h;
  render();
  if (!S.data.settings.onboarded) { S.ob = { step: 0, err: "", busy: false }; showOb(); }
})();
