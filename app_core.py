"""WorkReceipt app core: thin layer over the v0.2.4 engine (workreceipt.py). No engine logic is changed here.
Everything runs locally; nothing is sent over the network."""
import hashlib, hmac, json, os, pathlib, re, secrets, shutil, subprocess, tempfile, time
from collections import Counter
from datetime import datetime, timedelta

import workreceipt as w

VERSION = "0.3.4"
DISPOSITIONS = ("credential", "not_credential", "unsure")     # what the human decided; every choice keeps the value masked in the report
MAX_ITEMISE = 400_000          # longer texts are reviewed as one group (no per-detection location or reveal)
REVEAL_MAX = 2000


class UserError(ValueError):
    """A message that is safe to show: written by this program, never built from log content."""


class NotFound(LookupError):
    pass


HOME_DIR = os.path.join(os.path.expanduser("~"), ".workreceipt")
DEFAULTS = {"claude_dir": os.environ.get("WORKRECEIPT_CLAUDE_DIR", os.path.expanduser("~/.claude")),
            "out_dir": os.path.join(os.path.expanduser("~"), "WorkReceipt Reports"),
            "author": "", "client": "", "theme": "system", "redact_terms": []}


def _home():
    return os.environ.get("WORKRECEIPT_HOME", HOME_DIR)


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(os.path.join(_home(), "settings.json"), encoding="utf-8") as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    if os.environ.get("WORKRECEIPT_CLAUDE_DIR"):
        s["claude_dir"] = os.environ["WORKRECEIPT_CLAUDE_DIR"]
    return s


def save_settings(new):
    s = load_settings()
    for k in DEFAULTS:
        if k in new:
            s[k] = new[k]
    s["redact_terms"] = [t.strip() for t in s["redact_terms"] if str(t).strip()][:50]
    os.makedirs(_home(), exist_ok=True)
    with open(os.path.join(_home(), "settings.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    return s


def history():
    try:
        with open(os.path.join(_home(), "history.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _add_history(rec):
    h = history()[-49:] + [rec]
    os.makedirs(_home(), exist_ok=True)
    with open(os.path.join(_home(), "history.json"), "w", encoding="utf-8") as f:
        json.dump(h, f)


# ---------- project discovery ----------
def _first_cwd(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 400:
                    break
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                c = rec.get("cwd") if isinstance(rec, dict) else None
                if isinstance(c, str) and c:
                    return c
    except OSError:
        pass
    return None


def discover(claude_dir):
    """One entry per Claude Code project folder: working directory, session count, last activity, weekly session counts."""
    root = os.path.join(claude_dir, "projects")
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for n in names:
        d = os.path.join(root, n)
        if not os.path.isdir(d):
            continue
        try:
            files = [os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jsonl") and os.path.isfile(os.path.join(d, f))]
            files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        except OSError:
            continue
        if not files:
            continue
        cwd = next((c for c in (_first_cwd(p) for p in files[:3]) if c), None)
        if not cwd:
            continue
        exists = os.path.isdir(cwd)
        out.append({"path": cwd, "name": os.path.basename(cwd.rstrip("/\\")) or cwd, "sessions": len(files),
                    "last": datetime.fromtimestamp(os.path.getmtime(files[0])).strftime("%Y-%m-%d %H:%M"),
                    "mtimes": [os.path.getmtime(p) for p in files], "exists": exists,
                    "git": exists and w.git(cwd, "rev-parse", "--git-dir") is not None})
    out.sort(key=lambda p: p["last"], reverse=True)
    return out


def weekly(projects, weeks=12):
    now = datetime.now()
    start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(weeks=weeks - 1)
    buckets = [0] * weeks
    for p in projects:
        for m in p["mtimes"]:
            i = int((datetime.fromtimestamp(m) - start).days // 7)
            if 0 <= i < weeks:
                buckets[i] += 1
    return [{"label": (start + timedelta(weeks=i)).strftime("%b %d"), "n": n} for i, n in enumerate(buckets)]


# ---------- report assembly (same pipeline as workreceipt.main) ----------
def _dates(since, until):
    try:
        s = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=w.LOCAL_TZ) if since else None
        u = (datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=w.LOCAL_TZ) + timedelta(days=1)) if until else None
    except (ValueError, TypeError):
        raise UserError("Dates must be written YYYY-MM-DD")
    if s and u and s >= u:
        raise UserError("Start date is after end date")
    return s, u


_SALT = secrets.token_bytes(16)      # per-process: ids cannot be guessed, and never match across restarts


def _hid(*parts):
    return hmac.new(_SALT, "|".join(str(p) for p in parts).encode("utf-8", "replace"), hashlib.sha256).hexdigest()[:12]


def _fid(section, idx, rule, raw=""):
    """Finding id covers the content too, so a different value that lands in the same slot never inherits an approval."""
    return _hid("f", section, idx, rule, raw)


def _replay(text, terms):
    """Re-runs the engine's redaction step by step while tracking where each substitution came from, so every individual
    detection gets an exact location in the original text. Returns (masked, detections) or None if the replay does not
    reproduce the engine's own output exactly (then the caller falls back to group-level review)."""
    lo, hi, tok = list(range(len(text))), list(range(1, len(text) + 1)), [-1] * len(text)
    cur, dets = text, []
    helper = w.Redactor()                                  # reuses the engine's own entropy decision
    steps = [(n, sv, rx, rep) for n, sv, rx, rep in w.RULES] + [("unlabeled high-entropy token", "high", w.ENTROPY_RX, None)]
    steps += [("custom term", "high", re.compile(re.escape(t), re.I), "[REDACTED:custom]") for t in terms]
    for name, sev, rx, rep in steps:
        out, nlo, nhi, ntok, last = [], [], [], [], 0
        for m in rx.finditer(cur):
            if rep is None:
                new = helper._entropy(m)
                if new == m.group(0):
                    continue
                pre = 0
            else:
                new = m.expand(rep)
                lead = re.match(r"(?:\\\d)*", rep).group(0)
                pre = sum(len(m.group(int(d))) for d in re.findall(r"\\(\d)", lead))
            s, e = m.start(), m.end()
            a = s + pre
            out.append(cur[last:a]); nlo += lo[last:a]; nhi += hi[last:a]; ntok += tok[last:a]      # untouched text + kept prefix
            vlo, vhi = min(lo[a:e]), max(hi[a:e])
            idx = len(dets)
            kids = {t for t in tok[a:e] if t >= 0}
            dets.append({"rule": name, "sev": sev, "lo": vlo, "hi": vhi, "mask": new[pre:], "parent": None})
            for k in kids:
                dets[k]["parent"] = idx
            mk = new[pre:]
            out.append(mk); nlo += [vlo] * len(mk); nhi += [vhi] * len(mk); ntok += [idx] * len(mk)
            last = e
        if out:
            out.append(cur[last:]); nlo += lo[last:]; nhi += hi[last:]; ntok += tok[last:]
            cur, lo, hi, tok = "".join(out), nlo, nhi, ntok
    start = {}
    for i, t in enumerate(tok):
        if t >= 0 and t not in start:
            start[t] = i
    for i, d in enumerate(dets):
        root = i
        while dets[root]["parent"] is not None:
            root = dets[root]["parent"]
        d["root"] = root
    for d in dets:
        d["fs"] = start.get(d["root"])
        d["fe"] = None if d["fs"] is None else d["fs"] + len(dets[d["root"]]["mask"])
    return cur, dets


def _context(final, s, e):
    """Redacted lines around a detection; the detection itself is flagged 'hl'. Built only from already-masked text."""
    lines = final.split("\n")
    ln = final.count("\n", 0, s)
    col = s - (final.rfind("\n", 0, s) + 1)
    out = []
    for i in range(max(0, ln - 2), min(len(lines), ln + 3)):
        L = lines[i]
        if i == ln:
            ec = min(len(L), col + (e - s))
            a, b = max(0, col - 100), min(len(L), ec + 100)
            out.append({"hit": True, "segs": [["t", ("…" if a else "") + L[a:col]], ["hl", L[col:ec]], ["t", L[ec:b] + ("…" if b < len(L) else "")]]})
        else:
            out.append({"hit": False, "segs": [["t", L[:200] + ("…" if len(L) > 200 else "")]]})
    return out


def _in_report(final, fs, limit, shown):
    """Would this masked token be printed in the exported report? Informational only: every high detection still needs review."""
    if not shown:
        return False
    lead = len(final) - len(final.lstrip())
    st = final.strip()
    if not st:
        return False
    first = st.splitlines()[0]
    pos = fs - lead
    if pos < 0 or pos >= len(first):
        return False
    return not (limit and len(first) > limit and pos >= limit - 1)


def _findings(section, idx, raw, terms, label, at="", limit=None, shown=True):
    """Mask `raw`; return (masked text, findings, values). A finding is one (rule, severity) group in one place; each high-severity
    one carries its individual detections. `values` maps detection id -> original value for the explicit reveal action only;
    it is never serialised into any ordinary response, report or file."""
    r = w.Redactor(terms)
    masked = r(raw)
    if not r.hits:
        return masked, [], {}
    rep = _replay(raw, terms) if len(raw) <= MAX_ITEMISE else None
    if rep is not None:
        final, dets = rep
        cnt = Counter((d["rule"], d["sev"]) for d in dets)
        if final != masked or cnt != Counter(r.hits):
            rep = None
    groups = {}
    values = {}
    if rep is not None:
        by = {}
        for d in dets:
            by.setdefault((d["rule"], d["sev"]), []).append(d)
        total_lines = raw.count("\n") + 1
        for key, ds in by.items():
            n = len(ds)
            gid = _hid("g", section, idx, key[0], "")
            f = {"id": gid, "rule": key[0], "severity": key[1], "count": n, "section": section, "where": label, "itemised": True,
                 "context": w.first_line(masked, 160), "detections": []}
            for k, d in enumerate(ds, 1):
                val = raw[d["lo"]:d["hi"]]
                if d["mask"].endswith("@") and val.endswith("@"):
                    val = val[:-1]
                lead = len(val) - len(val.lstrip())
                val = val.strip()
                lo = d["lo"] + lead
                did = _hid("d", section, idx, key[0], lo, val)             # bound to the value itself: a changed value is a new detection
                line = raw.count("\n", 0, lo) + 1
                col = lo - (raw.rfind("\n", 0, lo) + 1) + 1
                kids = sorted({x["rule"] for x in dets if x["parent"] is not None and x["root"] == d["root"] and x is not dets[d["root"]]})
                det = {"id": did, "n": k, "of": n, "rule": key[0], "severity": key[1], "section": section, "where": label, "at": at,
                       "line": line, "col": col, "lines": total_lines, "length": len(val), "vsig": _hid("v", val),
                       "context": _context(final, d["fs"], d["fe"]) if d["fs"] is not None else [],
                       "in_report": _in_report(final, d["fs"], limit, shown) if d["fs"] is not None else None,
                       "also": [x for x in kids if x != key[0]]}
                if d["parent"] is not None:
                    det["inside"] = dets[d["root"]]["rule"]
                f["detections"].append(det)
                if key[1] == "high":
                    values[did] = val[:REVEAL_MAX]
            groups[key] = f
    else:
        for key, n in r.hits.items():
            gid = _hid("g", section, idx, key[0], "")
            f = {"id": gid, "rule": key[0], "severity": key[1], "count": n, "section": section, "where": label, "itemised": False,
                 "context": w.first_line(masked, 160), "detections": []}
            if key[1] == "high":          # too large (or not reproducible) to itemise: reviewed as one unit, no reveal possible
                f["detections"].append({"id": _hid("d", section, idx, key[0], "group", raw[:4096]), "n": 1, "of": 1, "rule": key[0], "severity": "high",
                                        "section": section, "where": label, "at": at, "line": None, "col": None, "lines": None, "length": None,
                                        "vsig": "", "context": [], "in_report": None, "also": [], "unitemised": n})
            groups[key] = f
    return masked, sorted(groups.values(), key=lambda f: ("high", "medium", "low").index(f["severity"])), values


def _terms(s, opts):
    return [t.strip() for t in (list(s.get("redact_terms", [])) + list(opts.get("terms") or [])) if isinstance(t, str) and t.strip()]


def build(opts, settings=None):
    s = settings or load_settings()
    repo = os.path.abspath(opts.get("repo") or "")
    if not os.path.isdir(repo):
        raise UserError("Project folder not found")
    since, until = _dates(opts.get("since") or "", opts.get("until") or "")
    terms = _terms(s, opts)
    skipped = Counter()
    sessions, _pdir = w.load_sessions(s["claude_dir"], repo, since, until, skipped)
    g = w.git_summary(repo, since, until, opts.get("git_author") or None)
    is_git = g is not None
    commits, files, ins, dele, n_auth = g or ([], Counter(), 0, 0, 0)
    findings, hits, values = [], Counter(), {}

    def mask(section, idx, raw, label, at="", limit=None, shown=True):
        m, fs, vals = _findings(section, idx, raw, terms, label, at, limit, shown)
        values.update(vals)
        findings.extend(fs)
        for f in fs:
            hits[(f["rule"], f["severity"])] += f["count"]
        return m

    items = []
    for s_ in sessions:
        for p in s_["prompts"]:
            items.append((p["ts"], p["text"]))
    items.sort(key=lambda x: x[0])
    work = []
    for i, (ts, text) in enumerate(items):
        work.append({"i": i, "key": _hid("r", ts.isoformat(), text), "title": w.first_line(mask("Work request", i, w.first_line(text, 10 ** 9), f"Request {i + 1}", ts.astimezone(w.LOCAL_TZ).strftime("%Y-%m-%d %H:%M"), 110)),
                     "date": ts.astimezone(w.LOCAL_TZ).strftime("%b %d")})
    checks = []
    cs = w.check_states(sessions)
    for i, (c, st) in enumerate(cs):
        checks.append({"cmd": mask("Check", i, c["cmd"], f"Check {i + 1}", c["ts"].astimezone(w.LOCAL_TZ).strftime("%Y-%m-%d %H:%M"), 140, i >= len(cs) - 40), "ok": c["ok"], "state": st,
                       "date": c["ts"].astimezone(w.LOCAL_TZ).strftime("%b %d")})
    cm = [[h, d, mask("Commit", i, sj, f"Commit {h[:7]}", str(d)[:16], None, i < 60)] for i, (h, d, sj) in enumerate(commits)]
    dirs = Counter()
    for p in files:
        dirs[mask("Folder", len(dirs), os.path.dirname(p) or "(project root)", "Changed folder")] += 1
    project = mask("Title", 0, os.path.basename(repo), "Project name")
    client = mask("Title", 1, opts.get("client") or "", "Client name") if opts.get("client") else ""
    author = mask("Title", 2, opts.get("author") or "", "Prepared by") if opts.get("author") else ""
    # de-duplicate findings that share an id (same rule in the same place)
    seen, uniq = set(), []
    for f in findings:
        if f["id"] not in seen:
            seen.add(f["id"]); uniq.append(f)
    ctx = dict(title="Work report" + (f" for {client}" if client else ""), project=project,
               period=f"{opts.get('since') or 'start'} → {opts.get('until') or 'today'}", author=author,
               generated=datetime.now().strftime("%Y-%m-%d %H:%M"), items=work, n_items=len(work), commits=cm,
               n_commits=len(cm), n_files=len(files), ins=ins, dele=dele, n_authors=n_auth, dirs=dirs.most_common(),
               git_filtered=bool(opts.get("git_author")), checks=checks, hits=hits)
    dup = Counter(d["vsig"] for f in uniq for d in f["detections"] if d["vsig"])
    for f in uniq:
        for d in f["detections"]:
            d["same_value_elsewhere"] = max(0, dup[d["vsig"]] - 1) if d["vsig"] else 0
    return {"values": values, "ctx": ctx, "findings": uniq, "skipped": dict(skipped), "is_git": is_git, "n_sessions": len(sessions)}


def summary(b):
    c = b["ctx"]
    st = Counter(x["state"] for x in c["checks"])
    ok = Counter(x["ok"] for x in c["checks"])
    sev = Counter(f["severity"] for f in b["findings"])
    return {"is_git": b["is_git"], "sessions": b["n_sessions"], "requests": c["items"], "commits": c["commits"][:200],
            "n_commits": c["n_commits"], "files": c["n_files"], "ins": c["ins"], "dele": c["dele"], "authors": c["n_authors"],
            "checks": c["checks"][-200:], "n_checks": len(c["checks"]),
            "check_stats": {"ok": ok[True], "failed": ok[False], "unknown": ok[None], "superseded": st["superseded"],
                            "edited": st["edited"], "possible": st["possible"], "current": st["current"]},
            "dirs": c["dirs"][:12], "findings": b["findings"], "severity": dict(sev), "skipped": b["skipped"],
            "project": c["project"], "period": c["period"]}


def reveal(opts, det_id, settings=None):
    """Return ONE original value, only when the caller asks for that detection by id. Re-reads the logs each time, so a value that
    changed or whose source is gone is simply not found. Nothing is cached or written anywhere."""
    s = settings or load_settings()
    if not isinstance(det_id, str) or len(det_id) > 64:
        raise NotFound()
    b = build(opts, s)
    v = b["values"].get(det_id)
    if v is None:
        raise NotFound()
    return {"value": v, "length": len(v)}


def _apply_titles(ctx, title_edits, terms):
    """Edits are keyed to the request itself (not its position), so a log that changed since loading can't shift an edit onto
    a different request. Edited titles are masked again. Returns how many were applied / dropped (request no longer present)."""
    by_key = {it["key"]: it for it in ctx["items"]}
    done = dropped = 0
    for k, text in (title_edits or {}).items():
        if k in by_key and isinstance(text, str) and text.strip():
            by_key[k]["title"] = w.first_line(w.Redactor(terms)(text.strip()))
            done += 1
        else:
            dropped += 1
    return done, dropped


def render_preview(opts, title_edits, settings=None):
    """Masked HTML for on-screen preview only. Nothing is written to disk."""
    s = settings or load_settings()
    b = build(opts, s)
    _apply_titles(b["ctx"], title_edits, _terms(s, opts))
    return w.render(b["ctx"])


def export(opts, approved, title_edits, settings=None):
    """Write the HTML report. High-severity findings must each be approved by the human first (enforced here, not only in the UI)."""
    s = settings or load_settings()
    b = build(opts, s)
    high = [d["id"] for f in b["findings"] if f["severity"] == "high" for d in f["detections"]]
    rev = approved if isinstance(approved, dict) else {}
    missing = [i for i in high if rev.get(i) not in DISPOSITIONS]
    if missing:
        return {"ok": False, "error": "review_required", "missing": missing}
    terms = _terms(s, opts)
    ctx = b["ctx"]
    applied, dropped = _apply_titles(ctx, title_edits, terms)
    html = w.render(ctx)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in ctx["project"])[:40] or "report"
    try:
        os.makedirs(s["out_dir"], exist_ok=True)
        path, n = os.path.join(s["out_dir"], f"{base}-{stamp}.html"), 1
        while os.path.exists(path):                       # never overwrite an earlier export
            n += 1
            path = os.path.join(s["out_dir"], f"{base}-{stamp}-{n}.html")
        with open(path, "x", encoding="utf-8") as f:
            f.write(html)
    except OSError as ex:
        raise UserError(f"Cannot write to the reports folder ({s['out_dir']}): {ex.strerror or 'error'}")
    pdf = None
    if opts.get("pdf"):
        pdf = to_pdf(path)
    _add_history({"project": ctx["project"], "repo": os.path.abspath(opts["repo"]), "period": ctx["period"], "html": path, "pdf": pdf,
                  "at": datetime.now().strftime("%Y-%m-%d %H:%M"), "requests": ctx["n_items"], "commits": ctx["n_commits"],
                  "checks": len(ctx["checks"]), "high_reviewed": len(high)})
    return {"ok": True, "html_path": path, "pdf_path": pdf, "high_reviewed": len(high), "edits_applied": applied,
            "edits_dropped": dropped, "html": html}


def chrome_path():
    for c in ("google-chrome", "chromium", "chromium-browser", "chrome",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        p = shutil.which(c) or (c if os.path.isabs(c) and os.path.exists(c) else None)
        if p:
            return p
    return None


def to_pdf(html_path):
    chrome = chrome_path()
    if not chrome:
        return None
    pdf = html_path[:-5] + ".pdf"
    prof = tempfile.mkdtemp(prefix="wr-chrome-")
    try:
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", f"--user-data-dir={prof}", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", pathlib.Path(html_path).resolve().as_uri()], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    return pdf if os.path.exists(pdf) else None
