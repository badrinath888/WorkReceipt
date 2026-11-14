"""WorkReceipt app core: thin layer over the v0.2.4 engine (workreceipt.py). No engine logic is changed here.
Everything runs locally; nothing is sent over the network."""
import hashlib, hmac, json, os, pathlib, secrets, shutil, subprocess, tempfile, time
from collections import Counter
from datetime import datetime, timedelta

import workreceipt as w

VERSION = "0.3.2"
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
    s = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=w.LOCAL_TZ) if since else None
    u = (datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=w.LOCAL_TZ) + timedelta(days=1)) if until else None
    if s and u and s >= u:
        raise ValueError("Start date is after end date")
    return s, u


_SALT = secrets.token_bytes(16)      # per-process: ids cannot be guessed, and never match across restarts


def _hid(*parts):
    return hmac.new(_SALT, "|".join(str(p) for p in parts).encode("utf-8", "replace"), hashlib.sha256).hexdigest()[:12]


def _fid(section, idx, rule, raw=""):
    """Finding id covers the content too, so a different value that lands in the same slot never inherits an approval."""
    return _hid("f", section, idx, rule, raw)


def _findings(section, idx, raw, terms, label):
    """Mask `raw` with a fresh redactor; return (masked text, findings). Findings never contain the original value."""
    r = w.Redactor(terms)
    masked = r(raw)
    fs = [{"id": _fid(section, idx, n, raw), "rule": n, "severity": sev, "count": c, "section": section, "where": label,
           "context": w.first_line(masked, 160)} for (n, sev), c in sorted(r.hits.items(), key=lambda x: x[0][1])]
    return masked, fs


def _terms(s, opts):
    return [t.strip() for t in (list(s.get("redact_terms", [])) + list(opts.get("terms") or [])) if isinstance(t, str) and t.strip()]


def build(opts, settings=None):
    s = settings or load_settings()
    repo = os.path.abspath(opts.get("repo") or "")
    if not os.path.isdir(repo):
        raise ValueError("Project folder not found")
    since, until = _dates(opts.get("since") or "", opts.get("until") or "")
    terms = _terms(s, opts)
    skipped = Counter()
    sessions, _pdir = w.load_sessions(s["claude_dir"], repo, since, until, skipped)
    g = w.git_summary(repo, since, until, opts.get("git_author") or None)
    is_git = g is not None
    commits, files, ins, dele, n_auth = g or ([], Counter(), 0, 0, 0)
    findings, hits = [], Counter()

    def mask(section, idx, raw, label):
        m, fs = _findings(section, idx, raw, terms, label)
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
        work.append({"i": i, "key": _hid("r", ts.isoformat(), text), "title": w.first_line(mask("Work request", i, w.first_line(text, 10 ** 9), f"Request {i + 1}")),
                     "date": ts.astimezone(w.LOCAL_TZ).strftime("%b %d")})
    checks = []
    for i, (c, st) in enumerate(w.check_states(sessions)):
        checks.append({"cmd": mask("Check", i, c["cmd"], f"Check {i + 1}"), "ok": c["ok"], "state": st,
                       "date": c["ts"].astimezone(w.LOCAL_TZ).strftime("%b %d")})
    cm = [[h, d, mask("Commit", i, sj, f"Commit {h[:7]}")] for i, (h, d, sj) in enumerate(commits)]
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
    return {"ctx": ctx, "findings": uniq, "skipped": dict(skipped), "is_git": is_git, "n_sessions": len(sessions)}


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
    high = [f for f in b["findings"] if f["severity"] == "high"]
    missing = [f["id"] for f in high if f["id"] not in set(approved or [])]
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
        raise ValueError(f"Cannot write to the reports folder ({s['out_dir']}): {ex.strerror or ex}")
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
