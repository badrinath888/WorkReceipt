#!/usr/bin/env python3
"""One-command, read-only validation of WorkReceipt against YOUR repo and YOUR real Claude Code logs.

    python3 validate_local.py --repo /path/to/AssetHandoff --since 2026-11-01

Prints a PASS / FAIL / NEEDS REVIEW summary that contains only counts and fixed labels (no prompts, commit
subjects, paths, command text or secrets). Nothing in your repo or ~/.claude is modified; the HTML report is
generated in a temp folder and deleted. Exit code: 0 PASS, 3 NEEDS REVIEW, 1 FAIL.
"""
import argparse, contextlib, html.parser, io, os, re, subprocess, sys, tempfile
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import workreceipt as w  # noqa: E402

SYSTEM_TAG_RX = re.compile(r"&lt;(?:task-notification|system-reminder|command-|local-command|bash-|ide_|user-prompt-submit|pasted_content)", re.I)
ALLOWED = {"meta", "title", "style", "h1", "h2", "div", "b", "ol", "ul", "li", "span", "p", "code", "table", "thead", "tbody", "tr", "th", "td"}


class _Tags(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self.seen = set(); self.on = 0

    def handle_starttag(self, tag, attrs):
        self.seen.add(tag); self.on += sum(1 for k, _ in attrs if k.startswith("on"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--since", required=True, help="YYYY-MM-DD")
    ap.add_argument("--until")
    ap.add_argument("--claude-dir", default=os.path.expanduser("~/.claude"))
    ap.add_argument("--skip-unit-tests", action="store_true")
    ap.add_argument("--summary-out", default=os.path.join(HERE, "validation_summary.txt"))
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    rows, status = [], {"FAIL": 0, "REVIEW": 0}

    def add(level, label, detail=""):
        rows.append((level, label, detail))
        if level in status:
            status[level] += 1

    # 1. automated tests
    if a.skip_unit_tests:
        add("INFO", "unit tests", "skipped by flag")
    else:
        r = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=HERE, capture_output=True, text=True,
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        tail = (r.stderr.strip().splitlines() or [""])[-1]
        ran = re.search(r"Ran (\d+) tests", r.stderr)
        add("PASS" if r.returncode == 0 else "FAIL", "automated tests", f"{ran.group(1) if ran else '?'} run; {tail}")

    # 2. discovery + structure (content-free by construction)
    if not os.path.isdir(repo):
        add("FAIL", "repo path", "not a directory")
        return finish(rows, status, a)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        w.diagnose(a.claude_dir, repo)
    diag = buf.getvalue().splitlines()
    m = re.search(r"jsonl files: (\d+)\s+lines: (\d+)\s+not-json: (\d+)", buf.getvalue())
    files_n, lines_n, bad_n = (int(x) for x in m.groups()) if m else (0, 0, 0)
    add("PASS" if files_n else "FAIL", "session files found", f"{files_n} files, {lines_n} records, {bad_n} unparseable")
    if lines_n and bad_n / lines_n > 0.01:
        add("REVIEW", "unparseable lines", f"{bad_n}/{lines_n}")
    for l in diag:
        if "records whose cwd is outside" in l:
            add("INFO", "other-project records excluded", l.split(":")[-1].strip())
        if l.strip().startswith("timestamps:") and "unparseable" in l:
            add("REVIEW", "timestamp format", l.strip())
    other_keys = [l.strip() for l in diag if l.strip().startswith(("key=other", "type=other", "block=other"))]
    if other_keys:
        add("REVIEW", "unknown log structure", "; ".join(other_keys))

    # 3. session classification
    since = w.datetime.strptime(a.since, "%Y-%m-%d").replace(tzinfo=w.LOCAL_TZ)
    until = (w.datetime.strptime(a.until, "%Y-%m-%d").replace(tzinfo=w.LOCAL_TZ) + w.timedelta(days=1)) if a.until else None
    skipped = Counter()
    sessions, _ = w.load_sessions(a.claude_dir, repo, since, until, skipped)
    prompts = [p for s in sessions for p in s["prompts"]]
    add("PASS" if prompts else "REVIEW", "work requests kept", str(len(prompts)))
    shape = Counter()
    for p in prompts:
        t = p["text"]
        shape["starts with <"] += t.startswith("<"); shape["starts with ["] += t.startswith("[")
        shape["over 2000 chars"] += len(t) > 2000
    if shape["starts with <"] or shape["starts with ["]:
        add("REVIEW", "kept requests that start with < or [", f"{shape['starts with <']} / {shape['starts with [']} (possible internal artifacts)")
    add("INFO", "skipped/excluded records by reason", ", ".join(f"{k}={n}" for k, n in sorted(skipped.items())) or "none")
    add("INFO", "kept requests over 2000 chars (long pastes)", str(shape["over 2000 chars"]))

    # 4. git accuracy: tool totals vs an independent per-commit `git show`
    g = w.git_summary(repo, since, until)
    if g is None:
        add("FAIL", "git history", "not a git repo or git failed")
    else:
        commits, files, ins, dele, nauth = g
        i2 = d2 = 0
        paths = set()
        for h, _, _ in commits:
            out = subprocess.run(["git", "-C", repo, "show", "--no-renames", "--numstat", "--format=", h], capture_output=True, text=True).stdout
            for l in out.splitlines():
                p = l.split("\t")
                if len(p) == 3:
                    paths.add(p[2]); i2 += int(p[0]) if p[0].isdigit() else 0; d2 += int(p[1]) if p[1].isdigit() else 0
        ok = (i2, d2, len(paths)) == (ins, dele, len(files))
        add("PASS" if ok else "FAIL", "git totals vs independent per-commit numstat", f"{len(commits)} commits, {nauth} author(s), +{ins}/-{dele}, {len(files)} files")
        rl = ["git", "-C", repo, "rev-list", "--no-merges", "--count", "HEAD", "--since", a.since + " 00:00:00"]
        if a.until:
            rl += ["--until", a.until + " 23:59:59"]
        n2 = subprocess.run(rl, capture_output=True, text=True).stdout.strip()
        if n2.isdigit() and int(n2) != len(commits):
            add("REVIEW", "commit count vs `git rev-list --since`", f"{len(commits)} vs {n2} (usually author-date vs commit-date or timezone edges)")
        if nauth > 1:
            add("REVIEW", "multiple commit authors", f"{nauth}; use --git-author to limit the report to yours")

    # 5. checks
    chk = Counter()
    for c, st in w.check_states(sessions):
        chk[{True: "no error reported", False: "failed", None: "result not recorded"}[c["ok"]]] += 1
        chk["state:" + st] += 1
    total = sum(chk[k] for k in ("no error reported", "failed", "result not recorded"))
    add("INFO", "checks detected", f"{total} (" + ", ".join(f"{k}={chk[k]}" for k in ("no error reported", "failed", "result not recorded")) + "; " +
        ", ".join(f"{k[6:]}={chk[k]}" for k in ("state:superseded", "state:edited", "state:possible", "state:current")) + ")")
    if total and chk["result not recorded"] / total > 0.5:
        add("REVIEW", "most checks have no recorded result", "result linking may not match your log format")

    # 6. report generation + output audit (temp folder, deleted afterwards)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "report.html")
        err = io.StringIO()
        argv = ["--repo", repo, "--claude-dir", a.claude_dir, "--since", a.since, "--out", out, "--allow-high"] + (["--until", a.until] if a.until else [])
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            try:
                rc = w.main(argv)
            except Exception as ex:      # a crash is a FAIL, reported by type only
                rc = -1; add("FAIL", "report generation crashed", type(ex).__name__)
        if rc == 0 and os.path.exists(out):
            doc = open(out, encoding="utf-8").read()
            add("PASS", "report generated", f"{len(doc)//1024} KB")
            t = _Tags(); t.feed(doc)
            add("PASS" if t.seen <= ALLOWED and not t.on and "Content-Security-Policy" in doc else "FAIL", "HTML structure/CSP",
                "only expected tags, no event handlers" if t.seen <= ALLOWED and not t.on else "unexpected tags or handlers")
            resid = w.Redactor()
            resid(re.sub(r"<[^>]+>", " ", doc))
            high = {k[0]: n for k, n in resid.hits.items() if k[1] == "high"}
            add("FAIL" if high else "PASS", "re-scan of finished report for secrets", ", ".join(f"{k}={n}" for k, n in high.items()) or "none found")
            home = os.path.expanduser("~")
            add("FAIL" if (home in doc or repo in doc) else "PASS", "home/repo absolute path in report", "present" if (home in doc or repo in doc) else "absent")
            sysn = len(SYSTEM_TAG_RX.findall(doc))
            add("REVIEW" if sysn else "PASS", "internal tags visible in report", str(sysn))
        elif rc != -1:
            add("FAIL", "report generation", f"exit {rc}")
        masks = [l.strip() for l in err.getvalue().splitlines() if l.strip().startswith(("high", "medium", "low", "high-severity"))]
        highn = sum(int(l.rsplit(":", 1)[1]) for l in masks if l.startswith("high ") and ":" in l and l.rsplit(":", 1)[1].strip().isdigit())
        if highn:
            add("REVIEW", "high-severity values masked", f"{highn}; run --preview and read the masked titles, then --allow-high only after reviewing")
        for l in masks:
            add("INFO", "redaction", l)
    # 7. final review (structure, detections incl. exposure status, stale evidence, report separation)
    fr = subprocess.run([sys.executable, os.path.join(HERE, "final_review.py"), "--repo", repo, "--claude-dir", a.claude_dir, "--since", a.since]
                        + (["--until", a.until] if a.until else []), capture_output=True, text=True)
    body = [l for l in fr.stdout.splitlines() if not l.startswith(("WorkReceipt final review", "OVERALL:"))]
    rows.append(("INFO", "final review follows", ""))
    for l in body:
        rows.append(("RAW", l, ""))
    if fr.returncode == 1: status["FAIL"] += 1
    elif fr.returncode == 3: status["REVIEW"] += 1
    elif fr.returncode != 0: status["FAIL"] += 1; rows.append(("FAIL", "final_review crashed", fr.stderr.strip().splitlines()[-1][:80] if fr.stderr.strip() else ""))
    return finish(rows, status, a)


def finish(rows, status, a):
    verdict = "FAIL" if status["FAIL"] else ("NEEDS REVIEW" if status["REVIEW"] else "PASS")
    lines = ["WorkReceipt local validation (content-free)"] + [lb if lv == "RAW" else f"[{lv:6}] {lb}" + (f": {d}" if d else "") for lv, lb, d in rows]
    lines.append(f"OVERALL: {verdict}")
    txt = "\n".join(lines)
    print(txt)
    try:
        with open(a.summary_out, "w") as f:
            f.write(txt + "\n")
        print(f"(summary also saved to {a.summary_out}; it is safe to share)")
    except OSError:
        pass
    return {"PASS": 0, "NEEDS REVIEW": 3, "FAIL": 1}[verdict]


if __name__ == "__main__":
    sys.exit(main())
