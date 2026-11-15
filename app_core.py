"""WorkReceipt app core: thin layer over the v0.2.4 engine (workreceipt.py). No engine logic is changed here.
Everything runs locally; nothing is sent over the network."""
import hashlib, hmac, json, os, pathlib, re, secrets, shutil, subprocess, sys, tempfile, time
from collections import Counter
from datetime import datetime, timedelta

import workreceipt as w

VERSION = "0.3.5"
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
            "author": "", "client": "", "theme": "system", "redact_terms": [],
            "projects": [], "hidden": [], "onboarded": False, "demo": False}


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
    for k in ("projects", "hidden"):
        s[k] = [x for x in (s[k] if isinstance(s[k], list) else []) if isinstance(x, str) and x][:200]
    s["onboarded"], s["demo"] = bool(s["onboarded"]), bool(s["demo"])
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


def demo_dir():
    return os.path.join(_home(), "demo")


def _claude_dir_for(repo, s):
    """Demo projects live in their own synthetic workspace; everything else uses the configured Claude folder."""
    d = os.path.realpath(demo_dir())
    return os.path.join(d, "claude") if os.path.realpath(repo).startswith(d + os.sep) else s["claude_dir"]


def enable_demo():
    """Create the synthetic demo workspace (fake repos and logs, no real data) and show it in Projects."""
    import runpy
    root = demo_dir()
    if not os.path.isdir(os.path.join(root, "claude")):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples", "make_demo_workspace.py")
        if not os.path.isfile(script):
            raise UserError("Demo files are missing from this installation")
        old = sys.argv
        sys.argv = [script, root]
        try:
            runpy.run_path(script, run_name="__demo__")
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise UserError("Could not create the demo workspace (is Git installed?)")
        finally:
            sys.argv = old
    save_settings({"demo": True})
    return [p for p in all_projects(load_settings()) if p.get("demo")]


def _norm(p):
    return os.path.realpath(os.path.expanduser(p))


def all_projects(s):
    """Claude-discovered projects + demo + folders the user added, minus ones the user removed from WorkReceipt."""
    ps = discover(s["claude_dir"])
    if s.get("demo"):
        for p in discover(os.path.join(demo_dir(), "claude")):
            p["demo"] = True
            ps.append(p)
    have = {_norm(p["path"]) for p in ps}
    for path in s.get("projects", []):
        if _norm(path) not in have:
            ex = os.path.isdir(path)
            ps.append({"path": path, "name": os.path.basename(path.rstrip("/\\")) or path, "sessions": 0, "last": "", "mtimes": [],
                       "exists": ex, "git": ex and w.git(path, "rev-parse", "--git-dir") is not None, "manual": True})
    hid = {_norm(x) for x in s.get("hidden", [])}
    ps = [p for p in ps if _norm(p["path"]) not in hid]
    ps.sort(key=lambda p: p["last"], reverse=True)
    return ps


def add_project(path):
    path = (path or "").strip()
    if not path or not os.path.isabs(os.path.expanduser(path)):
        raise UserError("Choose a folder using the folder picker or an absolute path")
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isdir(path):
        raise UserError("That folder does not exist or cannot be read")
    s = load_settings()
    save_settings({"projects": [x for x in s["projects"] if _norm(x) != _norm(path)] + [path],
                   "hidden": [x for x in s["hidden"] if _norm(x) != _norm(path)]})
    return path


def remove_project(path):
    """Hide from WorkReceipt only. Never touches the folder or the Claude Code logs."""
    s = load_settings()
    save_settings({"projects": [x for x in s["projects"] if _norm(x) != _norm(path)],
                   "hidden": s["hidden"] + [path]})


def delete_report(name):
    """Delete an exported report (and its PDF) that this app created. Only files listed in history are ever touched."""
    h, keep, hit = history(), [], None
    for rec in h:
        if hit is None and os.path.basename(rec.get("html") or "") == os.path.basename(name or ""):
            hit = rec
        else:
            keep.append(rec)
    if hit is None:
        raise NotFound()
    for k in ("html", "pdf"):
        if hit.get(k):
            try:
                os.remove(hit[k])
            except OSError:
                pass
    with open(os.path.join(_home(), "history.json"), "w", encoding="utf-8") as f:
        json.dump(keep, f)


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



# ---------------------------------------------------------------- classification
# Narrow, syntax-only rules decide what is auto-cleared. They never look at the variable name, and every cleared detection stays
# masked in the report. Anything ambiguous, random-looking, provider-shaped or unknown is left for a human.
PUBLISHED_EXAMPLES = {"AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "ASIAIOSFODNN7EXAMPLE"}     # AWS documentation constants
_CLOSERS = re.compile(r"(?:[)\]]|\[\d{1,3}\])+$")      # closing syntax only; a bracket holding letters is never stripped
_ENV_REF = re.compile(r"^(?:\$\{[A-Za-z_]\w*\}?|\$[A-Z][A-Z0-9]*_[A-Z0-9_]+|%\(\w+\)s|process\.env\.[A-Za-z_]\w*|os\.environ\[|(?:os\.|System\.)?getenv\(|(?:os\.)?environ\.get\(|ENV\[)$")
_TEMPLATE = re.compile(r"^<[A-Za-z][A-Za-z0-9 _.-]{0,40}>$")
_CODE_ATTR = re.compile(r"^(?:self|cls|this|os|config|settings|args|request|params|env|ctx|kwargs|options|opts|conf|cfg)\.[a-z_][a-z0-9_.]*(?:\(\))?$")
_CODE_CALL = re.compile(r"^[a-z_][a-z0-9_.]*\((?:[a-z_][a-z0-9_.]*)?\)(?:\[\d+\])?$")
_DUMMY_WORDS = re.compile(r"(?i)dummy|fake|example|sample|placeholder|change[_-]?me|your[_-]|mock|not[_-]?real|redacted|todo|xxxx|(?<![a-z])test")
_TEST_CTX = re.compile(r"(?i)\btest_\w+\.py|\bpytest\b|\bunittest\b|/tests?/|\btests?/|\bconftest\b")
SUPPRESSED_CATEGORIES = ("code_fragment", "code_reference", "env_reference", "template_placeholder", "published_example")


def _entropy(s):
    from math import log2
    return -sum(n / len(s) * log2(n / len(s)) for n in Counter(s).values()) if s else 0.0


def _open_calls(left):
    """Number of call parentheses ('name(') still open at the end of `left` (one line of code before the match). Strings are skipped."""
    st, q = [], None
    for i, ch in enumerate(left):
        if q:
            q = None if ch == q else q
        elif ch in "\"'":
            q = ch
        elif ch == "(":
            st.append(bool(re.search(r"[A-Za-z_][\w.]*$", left[:i])))
        elif ch == ")" and st:
            st.pop()
    return sum(st) if q is None else 0


_SNAKE = re.compile(r"^[a-z]+(?:_[a-z0-9]+)+$")


def _classify(raw, lo, hi, val, rule):
    """Evidence-based label for one high-severity detection. `suppressed` is True only when a narrow syntactic rule PROVES the
    matched text holds no secret material; confidence is 'rule-proven' then, otherwise 'likely' or 'low' and a human decides."""
    def out(cat, label, conf, why, ev, sup=False):
        return {"category": cat, "label": label, "confidence": conf, "explanation": why, "evidence": ev, "suppressed": sup}
    if rule == "custom term":
        return out("custom_term", "Your custom term", "likely", "Matches a term you asked to mask.", ["custom redaction term"])
    inner = val[1:-1] if len(val) > 1 and val[0] in "\"'" and val[-1] == val[0] else val
    if inner in PUBLISHED_EXAMPLES:
        return out("published_example", "Published documentation example", "rule-proven",
                   "This exact value is a public example from vendor documentation, not a working credential.", ["exact match to a published example value"], True)
    if rule != "secret assignment":
        if rule == "unlabeled high-entropy token":
            return out("unknown", "Random-looking token", "low", "A long random-looking string. It may be an identifier or a credential; the scanner cannot tell.", [f"entropy {_entropy(inner):.1f} bits/char"])
        return out("known_format", "Matches a credential format", "likely", f"Has the format of a {rule}. Treat as a real credential until you have checked it yourself.", [f"matches the {rule} pattern"])
    quoted = val[:1] in "\"'"
    ev = []
    if not quoted:
        core = _CLOSERS.sub("", val)
        if core != val and len(core) < 6:
            return out("code_fragment", "Code fragment", "rule-proven",
                       "The match is a short name followed by closing code syntax; the scanner's 6-character minimum was only reached by including the syntax.",
                       [f"text before the syntax is {len(core)} characters", f"closing syntax is {len(val) - len(core)} characters"], True)
        left = raw[raw.rfind("\n", 0, lo) + 1:lo]
        left = re.sub(r"[A-Za-z0-9_.-]*[\"']?\s*[=:]\s*$", "", left)              # drop the key and separator that belong to this match
        if core != val and _SNAKE.match(core) and 1 <= val.count(")") <= _open_calls(left):
            return out("code_reference", "Variable passed to a function call", "high",
                       "A snake_case name followed by the closing of an open call, i.e. a variable reference. This assumes the text is code: if it is not, review it.",
                       [f"call parenthesis opened earlier on this line", f"name is {len(core)} characters of lower-case words, no quotes"], True)
        if _ENV_REF.match(val):
            return out("env_reference", "Reference to an environment variable", "rule-proven", "A lookup of a value stored elsewhere, not the value itself.", ["environment or shell variable reference"], True)
        if _CODE_ATTR.match(val):
            return out("code_reference", "Code reference", "rule-proven", "An attribute path on a common code object (for example self.* or config.*), not a literal value.", ["dotted attribute path on a code object"], True)
        if _CODE_CALL.match(val) and ("_" in val.split("(")[0] or "." in val.split("(")[0]):
            return out("code_reference", "Function call", "rule-proven", "A call to a lower-case function with identifier arguments, not a literal value.", ["call expression with identifier arguments"], True)
    elif _TEMPLATE.match(inner) or _ENV_REF.match(inner):
        return out("template_placeholder", "Template placeholder or variable reference", "rule-proven", "A delimited placeholder or variable reference, not a literal value.", ["delimited placeholder"], True)
    test_ctx = bool(_TEST_CTX.search(raw))
    if test_ctx:
        ev.append("appears in a command that creates or runs test code")
    words = sorted({m.group(0).lower() for m in _DUMMY_WORDS.finditer(inner)})
    if words:
        ev.append("contains " + ", ".join(f"'{x}'" for x in words))
    if len(inner) >= 6 and len(set(inner)) <= 2:
        ev.append("repeated characters")
    if len(inner) >= 12 and _entropy(inner) >= 3.5 and not words:
        ev.append(f"random-looking ({_entropy(inner):.1f} bits/char)")
    dummyish = bool(words) or (len(inner) >= 6 and len(set(inner)) <= 2)
    if dummyish and test_ctx:
        return out("test_fixture", "Likely test fixture", "likely", "Dummy-looking value inside test code. It is not cleared automatically, because a dummy-looking word is not proof the value is fake.", ev)
    if dummyish:
        return out("likely_dummy", "Likely dummy value", "low", "The value looks like a placeholder, but nothing proves it. Check it yourself.", ev)
    if any(e.startswith("random-looking") for e in ev):
        return out("looks_real", "Looks like a real secret", "likely", "Random-looking value assigned to a secret-like name. Treat as real until you have checked.", ev)
    return out("unknown", "Unclassified", "low", "Could not tell whether this is a credential. Check it yourself.", ev)


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
                if key[1] == "high":
                    det["class"] = _classify(raw, lo, d["hi"], val, key[0])
                    det["suppressed"] = det["class"]["suppressed"]
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
                                        "vsig": "", "context": [], "in_report": None, "also": [], "unitemised": n, "suppressed": False,
                                        "class": {"category": "unknown", "label": "Too large to classify", "confidence": "low", "suppressed": False,
                                                  "explanation": "Text too large to analyse per detection; review as a whole.", "evidence": []}})
            groups[key] = f
    for f in groups.values():
        f["cleared"] = sum(1 for d in f["detections"] if d.get("suppressed"))
        f["actionable"] = len(f["detections"]) - f["cleared"] if f["severity"] == "high" else 0
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
    sessions, _pdir = w.load_sessions(_claude_dir_for(repo, s), repo, since, until, skipped)
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
    high = [d["id"] for f in b["findings"] if f["severity"] == "high" for d in f["detections"] if not d.get("suppressed")]
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
                  "client": (opts.get("client") or "")[:80], "at": datetime.now().strftime("%Y-%m-%d %H:%M"), "requests": ctx["n_items"], "commits": ctx["n_commits"],
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
