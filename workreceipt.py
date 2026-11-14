#!/usr/bin/env python3
"""WorkReceipt: turn Claude Code sessions + git history into a client-safe HTML report.

Local only. No network, no LLM, no dependencies (Python 3.9+).

  workreceipt.py --repo . --since 2026-11-01 --until 2026-11-14 --client "Acme" --preview
  workreceipt.py --repo . --since 2026-11-01 --out report.html
"""
import argparse, html, json, math, os, re, subprocess, sys
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone

# ---------- redaction ----------
# (name, severity, regex, replacement)
RULES = [
    ("private key", "high", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S), "[REDACTED:private-key]"),
    ("AWS access key", "high", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED:aws-key]"),
    ("GitHub token", "high", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "[REDACTED:github-token]"),
    ("Stripe key", "high", re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}\b"), "[REDACTED:stripe-key]"),
    ("Slack token", "high", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED:slack-token]"),
    ("API key (sk-)", "high", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED:api-key]"),
    ("Google API key", "high", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "[REDACTED:google-key]"),
    ("JWT", "high", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED:jwt]"),
    ("URL credentials", "high", re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^\s/:@]+:[^\s/@]+@"), r"\1[REDACTED:creds]@"),
    ("Bearer token", "high", re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{16,}"), r"\1 [REDACTED:token]"),
    ("npm token", "high", re.compile(r"\bnpm_[A-Za-z0-9]{30,}\b"), "[REDACTED:npm-token]"),
    ("Basic auth", "high", re.compile(r"(?i)\b(basic)\s+[A-Za-z0-9+/=]{16,}"), r"\1 [REDACTED:token]"),
    ("secret assignment", "high", re.compile(
        r"(?i)([\"']?\b[A-Z0-9_.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|credential|auth[_-]?key)[A-Z0-9_.-]*[\"']?)"
        r"(\s*[=:]\s*)(?:\"[^\"\n]{4,}\"|'[^'\n]{4,}'|[^\s'\",;}]{6,})"), r"\1\2[REDACTED:secret]"),
    ("email", "medium", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED:email]"),
    ("home path", "low", re.compile(r"(?:/Users|/home)/[^/\s'\"]+"), "~"),
    ("IPv4 address", "low", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED:ip]"),
]


ENTROPY_RX = re.compile(r"[A-Za-z0-9_+=-]{24,}")


def _entropy(tok):
    c = Counter(tok)
    return -sum(v / len(tok) * math.log2(v / len(tok)) for v in c.values())


class Redactor:
    def _entropy(self, m):
        t = m.group(0)
        if (re.search(r"[A-Z]", t) and re.search(r"[a-z]", t) and re.search(r"\d", t) and _entropy(t) >= 3.5):
            self.hits[("unlabeled high-entropy token", "high")] += 1
            return "[REDACTED:token]"
        return t

    def __init__(self, extra_terms=None):
        self.hits = Counter()      # (name, severity) -> count
        self.extra = [t for t in (extra_terms or []) if t]

    def __call__(self, text):
        if not text:
            return text
        for name, sev, rx, rep in RULES:
            text, n = rx.subn(rep, text)
            if n:
                self.hits[(name, sev)] += n
        text, n = ENTROPY_RX.subn(self._entropy, text)
        for term in self.extra:
            rx = re.compile(re.escape(term), re.I)
            text, n = rx.subn("[REDACTED:custom]", text)
            if n:
                self.hits[("custom term", "high")] += n
        return text


# ---------- sessions ----------
LOCAL_TZ = datetime.now().astimezone().tzinfo


def encode_project_dir(path):
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))


def parse_ts(s):
    """Aware datetime. Timestamps without a zone are treated as local time."""
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None
    return d if d.tzinfo else d.replace(tzinfo=LOCAL_TZ)


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                         and isinstance(b.get("text"), str))
    return ""


NOISE = ("<command-", "<local-command", "Caveat:", "<system-reminder", "[Request interrupted", "<ide_", "<user-prompt-submit-hook",
         "<bash-input", "<bash-stdout", "<bash-stderr", "<task-notification")
# Text Claude Code writes itself when a conversation is compacted/resumed (also flagged isCompactSummary on the record).
CONTINUATION = "This session is being continued from a previous conversation"
# Record flags that mean "not typed by the human as a new request".
SKIP_FLAGS = ("isMeta", "isSidechain", "isCompactSummary", "isVisibleInTranscriptOnly", "toolUseResult")
# Paste wrappers/placeholders: only the markers are removed. Text inside <pasted_content> is the user's own pasted
# instruction as far as the logs show, so it is kept (and redacted like everything else); a marker with nothing else is dropped.
PLACEHOLDER_RX = re.compile(r"</?pasted_content\b[^>]*>|\[Pasted text #\d+(?: \+\d+ lines?)?\]|\[Image #\d+\]", re.I)
# A prompt that is only the CLI being launched (e.g. `claude --dangerously-skip-permissions`) is not a task.
CLI_ONLY_RX = re.compile(r"^\s*[$>]?\s*(?:npx\s+)?claude(?:\s+-{1,2}[\w-]+)*\s*$", re.I)
ACKS = {"yes", "y", "ok", "okay", "continue", "go", "go on", "proceed", "thanks", "thank you", "sure", "do it", "next", "yep", "no"}
_TOOLS = (r"pytest|py\.test|unittest|jest|vitest|mocha|tox|ruff|eslint|flake8|mypy|tsc|rspec|phpunit|"
          r"go (?:test|build|vet)|cargo (?:test|build|clippy)|mvn (?:test|verify|package)|gradle(?:w)? (?:test|build)|"
          r"(?:npm|pnpm|yarn|bun)(?: run)? (?:test|build|lint|typecheck)|make (?:test|build|lint|check)|python3? -m (?:pytest|unittest)|swift (?:test|build)|xcodebuild|dotnet (?:test|build)|flutter test|deno test")
TEST_RX = re.compile(r"^\s*(?:(?:time|timeout\s+\d+\w*)\s+)*(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*(?:(?:npx|uv run|poetry run|pipenv run|bundle exec|\./)\s*)?(?:" + _TOOLS + r")\b")
# Shell commands that may change files (used only to flag earlier checks as possibly stale).
MODIFY_RX = re.compile(r"(?:^|[\s;&|(])(?:sed\s+-[A-Za-z]*i|perl\s+-[A-Za-z]*i|tee|patch|mv|cp|rm|git\s+(?:apply|checkout|restore|stash|reset|merge|rebase|pull|cherry-pick|am))\b"
                       r"|(?<![0-9&>\-])>{1,2}\s*(?!/dev/null|&)[^\s&|;]+")
WRAP_RX = re.compile(r"""^\s*(?:(?:time|timeout\s+\d+\w*|env|nice)\s+)*(?:bash|sh|zsh)\s+-[lc]+\s+(["'])(.*)\1\s*$""", re.S)


def split_segments(cmd):
    """Split a shell line on unquoted && || ; | and newlines, so text inside quotes (commit messages, echo) is never a command."""
    segs, cur, q, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if q:
            cur.append(ch)
            if ch == "\\" and q == '"' and i + 1 < len(cmd):
                cur.append(cmd[i + 1]); i += 1
            elif ch == q:
                q = None
        elif ch in "\"'":
            q = ch; cur.append(ch)
        elif ch == "\\" and i + 1 < len(cmd):
            cur.append(ch); cur.append(cmd[i + 1]); i += 1
        elif cmd.startswith(("&&", "||"), i):
            segs.append("".join(cur)); cur = []; i += 1
        elif ch in ";|\n":
            segs.append("".join(cur)); cur = []
        else:
            cur.append(ch)
        i += 1
    segs.append("".join(cur))
    return segs


def is_check(cmd, depth=0):
    for seg in split_segments(cmd):
        if TEST_RX.match(seg):
            return True
        m = WRAP_RX.match(seg)
        if m and depth < 2 and is_check(m.group(2), depth + 1):
            return True
    return False


def classify_prompt(content):
    """(text, reason): the human-typed request in a message, or "" plus why nothing qualified (None if no text at all)."""
    if isinstance(content, str):
        blocks = [content]
    elif isinstance(content, list):
        blocks = [b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    else:
        blocks = []
    keep, why = [], None
    for t in blocks:
        if not isinstance(t, str) or not t.strip():
            continue
        t = PLACEHOLDER_RX.sub("", t.strip()).strip()      # unwrap first so wrapped system text is still recognised
        if t.startswith(CONTINUATION):
            why = why or "continuation summary"
        elif t.startswith(NOISE):
            why = why or "system/command text"
        elif re.search(r"\w", t):
            keep.append(t)
        else:
            why = why or "pasted placeholder only"
    text = "\n".join(keep).strip()
    if text and CLI_ONLY_RX.match(text):
        return "", "terminal command"
    return text, (None if text else why)


def clean_prompt(content):
    return classify_prompt(content)[0]


def user_prompt(ev):
    """(text, None) if a user record is a human-typed request; ("", reason) if it had text but is not one."""
    msg = ev.get("message")
    text, why = classify_prompt(msg.get("content") if isinstance(msg, dict) else None)
    if not (text or why):
        return "", None                      # tool results / empty: nothing was skipped
    for k in SKIP_FLAGS:
        if ev.get(k):
            return "", "flag:" + k
    if not text:
        return "", why
    if text.lower().strip(" .!") in ACKS:
        return "", "acknowledgement"
    return text, None


def check_states(sessions):
    """[(check, state)] oldest first. state: superseded (same command ran again later), edited (an Edit/Write tool use on a repo
    file came later and the command was not re-run), possible (only shell commands that may change files came later, not re-run),
    current (nothing later in the logs). 'edited' is observed evidence; 'possible' is not."""
    allc = sorted((c for s in sessions for c in s["checks"]), key=lambda c: c["ts"])
    obs = max((e for s in sessions for e in s["edits"]), default=None)
    shl = max((e for s in sessions for e in s["shell_edits"]), default=None)
    sig = lambda c: " ".join(c["cmd"].split())
    last = {}
    for c in allc:
        last[sig(c)] = max(last.get(sig(c), c["ts"]), c["ts"])
    out = []
    for c in allc:
        st = "superseded" if last[sig(c)] > c["ts"] else "edited" if obs and obs > c["ts"] else "possible" if shl and shl > c["ts"] else "current"
        out.append((c, st))
    return out


def result_ok(block):
    if block.get("is_error"):
        return False
    m = re.search(r"Exit code:?\s*(-?\d+)", text_of(block.get("content")) if isinstance(block.get("content"), list)
                  else str(block.get("content") or ""))
    return not (m and m.group(1) != "0")


_RP = {}


def _real(p):
    r = _RP.get(p)
    if r is None:
        r = _RP[p] = os.path.normcase(os.path.realpath(p))
    return r


def under(path, repo):
    if not isinstance(path, str) or not path:
        return False
    p, r = _real(path), _real(repo)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def load_sessions(claude_dir, repo, since, until, skipped=None):
    base = os.path.join(claude_dir, "projects")
    enc = encode_project_dir(repo)
    out, seen = [], set()
    if not os.path.isdir(base):
        return out, os.path.join(base, enc)
    for dn in sorted(os.listdir(base)):
        exact = dn == enc
        if not (exact or dn.startswith(enc + "-")):
            continue
        pdir = os.path.join(base, dn)
        for fn in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
            if not fn.endswith(".jsonl"):
                continue
            prompts, cmds, files, pending, edits, shell_edits = [], [], OrderedDict(), {}, [], []
            first = last = None
            with open(os.path.join(pdir, fn), encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(ev, dict):
                        continue
                    cwd = ev.get("cwd")
                    if isinstance(cwd, str) and cwd:
                        if not under(cwd, repo):
                            if skipped is not None:
                                skipped["record from another project directory"] += 1
                            continue      # sibling project sharing a name prefix, or an encoding collision (a-b vs a/b)
                    elif not exact:
                        continue
                    uid = ev.get("uuid")
                    if uid:
                        if uid in seen:
                            continue      # resumed/forked sessions repeat earlier events
                        seen.add(uid)
                    ts = parse_ts(ev.get("timestamp", ""))
                    if ts is None or (since and ts < since) or (until and ts >= until):
                        continue
                    first = first or ts
                    last = ts
                    msg = ev.get("message")
                    content = msg.get("content") if isinstance(msg, dict) else None
                    if ev.get("type") == "user":
                        if isinstance(content, list):
                            for b in content:
                                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                                    pending[b["tool_use_id"]]["ok"] = result_ok(b)
                        t, why = user_prompt(ev)
                        if t:
                            prompts.append({"ts": ts, "text": t})
                        elif why and skipped is not None:
                            skipped[why] += 1
                    elif ev.get("type") == "assistant" and isinstance(content, list):
                        for b in content:
                            if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                                continue
                            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                            cmd = inp.get("command")
                            if b.get("name") == "Bash" and isinstance(cmd, str) and is_check(cmd):
                                rec = {"ts": ts, "cmd": cmd, "ok": None}
                                cmds.append(rec)
                                if b.get("id"):
                                    pending[b["id"]] = rec
                            elif b.get("name") == "Bash" and isinstance(cmd, str) and MODIFY_RX.search(cmd):
                                shell_edits.append(ts)      # possible (not observed) change: only used to flag earlier checks
                            elif b.get("name") in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                                p = inp.get("file_path") or inp.get("notebook_path")
                                if isinstance(p, str) and p:
                                    p = p if os.path.isabs(p) else os.path.join(cwd if isinstance(cwd, str) and cwd else repo, p)
                                    if under(p, repo):          # edits elsewhere are not this project's work
                                        files[p] = files.get(p, 0) + 1
                                        edits.append(ts)
            if prompts or cmds or files:
                out.append({"id": fn[:-6], "start": first, "end": last, "prompts": prompts, "checks": cmds, "files": files, "edits": edits, "shell_edits": shell_edits})
    return out, os.path.join(base, enc)


# ---------- diagnose (structure only, never prints content) ----------
KNOWN_KEYS = {"type", "timestamp", "uuid", "parentUuid", "cwd", "sessionId", "isMeta", "isSidechain", "message", "version",
              "gitBranch", "userType", "requestId", "toolUseResult", "summary", "leafUuid", "content", "level", "subtype",
              "isCompactSummary", "isVisibleInTranscriptOnly", "lastPrompt"}
KNOWN_TYPES = {"user", "assistant", "summary", "system", "file-history-snapshot", "queue-operation", "last-prompt"}
KNOWN_BLOCKS = {"text", "tool_use", "tool_result", "thinking", "image", "redacted_thinking"}
KNOWN_TOOLS = {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Read", "Glob", "Grep", "Task", "WebFetch", "WebSearch", "TodoWrite"}


def diagnose(claude_dir, repo):
    base = os.path.join(claude_dir, "projects")
    enc = encode_project_dir(repo)
    print(f"claude dir exists: {os.path.isdir(base)}")
    dirs = [d for d in (os.listdir(base) if os.path.isdir(base) else []) if d == enc or d.startswith(enc + "-")]
    print(f"project dirs matching this repo: {len(dirs)} (exact: {enc in dirs})")
    c = Counter(); bad = nonjson = total = 0; uuids = Counter(); tsfmt = Counter(); files_n = 0
    for d in dirs:
        for fn in os.listdir(os.path.join(base, d)):
            if not fn.endswith(".jsonl"):
                continue
            files_n += 1
            for line in open(os.path.join(base, d, fn), encoding="utf-8", errors="replace"):
                if not line.strip():
                    continue
                total += 1
                try:
                    ev = json.loads(line)
                except Exception:
                    nonjson += 1
                    continue
                if not isinstance(ev, dict):
                    bad += 1
                    continue
                t = ev.get("type")
                c["type=" + (t if t in KNOWN_TYPES else "other")] += 1
                for k in ev:
                    c["key=" + (k if k in KNOWN_KEYS else "other")] += 1
                ts = ev.get("timestamp")
                if ts is not None:
                    p = parse_ts(ts)
                    tsfmt["unparseable" if p is None else ("with zone" if re.search(r"(Z|[+-]\d\d:?\d\d)$", str(ts)) else "no zone")] += 1
                if ev.get("uuid"):
                    uuids[ev["uuid"]] += 1
                if isinstance(ev.get("cwd"), str) and ev["cwd"] and not under(ev["cwd"], repo):
                    c["records whose cwd is outside this repo (excluded)"] += 1
                if t == "user":      # how each user record is classified (fixed labels only, never content)
                    txt, why = user_prompt(ev)
                    if txt:
                        c["user prompt: kept"] += 1
                        for lead in "<[":
                            if txt.startswith(lead):
                                c["user prompt: kept, starts with " + lead] += 1
                    elif why:
                        c["user prompt: skipped " + why] += 1
                m = ev.get("message")
                cont = m.get("content") if isinstance(m, dict) else None
                if t == "user":      # leading tag names and paste-wrapper shape of user text blocks (no text printed)
                    for tx in [cont] if isinstance(cont, str) else [b.get("text") for b in cont if isinstance(b, dict) and b.get("type") == "text"] if isinstance(cont, list) else []:
                        if not isinstance(tx, str):
                            continue
                        mt = re.match(r"^\s*<([A-Za-z][\w-]{0,30})", tx)
                        if mt:
                            nm = mt.group(1).lower()
                            c["user text block starts <tag>: " + (nm if re.fullmatch(r"[a-z][a-z0-9_-]*", nm) else "other")] += 1
                        if re.search(r"<pasted_content\b", tx, re.I):
                            body = re.sub(r"</?pasted_content\b[^>]*>", "", tx, flags=re.I).strip()
                            c["pasted_content wrapper: %s, %s" % ("closed" if "</pasted_content>" in tx.lower() else "not closed",
                                                                  "has body" if body else "no body")] += 1
                            c["pasted_content record keys: " + ",".join(sorted({k if k in KNOWN_KEYS else "other" for k in ev}))] += 1
                c["content=" + (type(cont).__name__)] += 1
                for b in cont if isinstance(cont, list) else []:
                    if isinstance(b, dict):
                        bt = b.get("type")
                        c["block=" + (bt if bt in KNOWN_BLOCKS else "other")] += 1
                        if bt == "tool_use":
                            c["tool=" + (b.get("name") if b.get("name") in KNOWN_TOOLS else "other")] += 1
                        if bt == "tool_result":
                            c["tool_result has is_error=" + str("is_error" in b)] += 1
                            c["tool_result content=" + type(b.get("content")).__name__] += 1
    print(f"jsonl files: {files_n}   lines: {total}   not-json: {nonjson}   non-object: {bad}")
    print(f"duplicate uuids: {sum(1 for v in uuids.values() if v > 1)}")
    print("timestamps:", dict(tsfmt))
    for k in sorted(c):
        print(f"  {k}: {c[k]}")
    print("\n(no prompt text, paths, tool inputs or file names were printed)")


# ---------- git ----------
def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, errors="replace")
    return r.stdout if r.returncode == 0 else None


def git_summary(repo, since, until, author=None):
    # Dates are filtered in Python: git's --since stops at the first older commit, which breaks on rebased history.
    extra = ["--author=" + author] if author else []
    raw = git(repo, "log", "--no-merges", "--no-renames", "--numstat", *extra, "--pretty=format:@@%H%x1f%aI%x1f%an%x1f%s")
    if raw is None:
        # a repository with no commits yet makes `git log` fail; that is an empty history, not "not a git repo"
        return ([], Counter(), 0, 0, 0) if git(repo, "rev-parse", "--git-dir") is not None else None
    commits, files, authors = [], Counter(), set()
    ins = dele = 0
    keep = False
    for l in raw.splitlines():
        if l.startswith("@@"):
            h, d, an, sj = (l[2:].split("\x1f", 3) + ["", "", ""])[:4]
            ts = parse_ts(d)
            keep = bool(ts) and not (since and ts < since) and not (until and ts >= until)
            if keep:
                commits.append([h, ts.strftime("%Y-%m-%d"), sj])
                authors.add(an)
        elif keep:
            parts = l.split("\t")
            if len(parts) == 3:
                a_, dd, path = parts
                files[path] += 1
                ins += int(a_) if a_.isdigit() else 0
                dele += int(dd) if dd.isdigit() else 0
    return commits, files, ins, dele, len(authors)


# ---------- render ----------
CSS = """
body{font:15px/1.55 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:860px;margin:2rem auto;padding:0 1.2rem;color:#1c2330}
h1{font-size:1.7rem;margin:.2rem 0}h2{font-size:1.15rem;margin:2rem 0 .6rem;border-bottom:1px solid #d9dee7;padding-bottom:.3rem}
.meta{color:#5a6577}.cards{display:flex;gap:.8rem;flex-wrap:wrap;margin:1rem 0}
.card{flex:1;min-width:130px;border:1px solid #d9dee7;border-radius:8px;padding:.7rem .9rem}.card b{display:block;font-size:1.4rem}
li{margin:.35rem 0}code{background:#f2f4f8;padding:.1rem .35rem;border-radius:4px;font-size:.88em;word-break:break-all}
.ok{color:#14803c}.bad{color:#b42318}.unk{color:#8a6d00}.box{border:1px solid #d9dee7;border-radius:8px;padding:.8rem 1rem;background:#fafbfd}
[contenteditable]{outline:1px dashed #c4cbd8;outline-offset:2px;border-radius:3px}
.small{font-size:.85rem;color:#5a6577}
@page{margin:16mm}
h2{break-after:avoid}li{break-inside:avoid}
@media print{body{margin:0}[contenteditable]{outline:none}.noprint{display:none}}
"""


def esc(s):
    return html.escape(s, quote=True)


def first_line(t, n=110):
    l = t.strip().splitlines()[0] if t.strip() else ""
    return l if len(l) <= n else l[: n - 1] + "…"


def render(ctx):
    e = esc
    o = []
    o.append(f"<!doctype html><meta charset=utf-8><meta http-equiv=Content-Security-Policy content=\"default-src 'none'; style-src 'unsafe-inline'\"><title>{e(ctx['title'])}</title><style>{CSS}</style>")
    o.append(f"<h1>{e(ctx['title'])}</h1>")
    o.append(f"<div class=meta>{e(ctx['project'])} · {e(ctx['period'])}"
             f"{' · Prepared by ' + e(ctx['author']) if ctx['author'] else ''} · generated {e(ctx['generated'])}</div>")
    o.append("<div class=cards>"
             f"<div class=card><b>{ctx['n_items']}</b>work requests</div>"
             f"<div class=card><b>{ctx['n_commits']}</b>commits</div>"
             f"<div class=card><b>{ctx['n_files']}</b>files changed</div>"
             f"<div class=card><b>+{ctx['ins']} / −{ctx['dele']}</b>lines</div></div>")
    o.append("<h2>Work requested</h2>")
    o.append("<p class=small>Requests given to the AI coding assistant during this period. A request listed here "
             "does not mean the work was completed; see Changes delivered and Verification below.</p>")
    if ctx["items"]:
        o.append("<p class='small noprint'>Titles below are editable in your browser before you print or save as PDF.</p><ol>")
        for it in ctx["items"]:
            o.append(f"<li><span contenteditable>{e(it['title'])}</span> <span class=small>({e(it['date'])})</span></li>")
        o.append("</ol>")
    else:
        o.append("<p>No session activity found in this period.</p>")
    o.append("<h2>Changes delivered</h2>")
    if ctx["commits"]:
        o.append(f"<p class=small>Commits in this repository's history during the period "
                 f"({ctx['n_authors']} author(s){'; filtered by author' if ctx['git_filtered'] else ''}). Git is the evidence of delivered changes.</p>")
        o.append("<ul>")
        for _h, d, s in ctx["commits"][:60]:
            o.append(f"<li><span class=small>{e(d)}</span> {e(s)}</li>")
        o.append("</ul>")
        if len(ctx["commits"]) > 60:
            o.append(f"<p class=small>…and {len(ctx['commits']) - 60} more commits.</p>")
        o.append("<p><b>Where the changes landed</b></p><ul>")
        for d, n in ctx["dirs"][:12]:
            o.append(f"<li><code>{e(d)}</code> — {n} file(s)</li>")
        o.append("</ul>")
    else:
        o.append("<p>No commits found in this period.</p>")
    o.append("<h2>Verification</h2>")
    o.append("<p class=small>Test, lint and build commands recorded in the session logs, with the outcome the tool recorded. "
             "They were not re-run for this report.</p>")
    if ctx["checks"]:
        n = len(ctx["checks"]); cnt = Counter(c["ok"] for c in ctx["checks"]); st = Counter(c.get("state") for c in ctx["checks"])
        o.append(f"<p class=small>{n} check command(s) recorded: {cnt[True]} no error reported, {cnt[False]} failed, "
                 f"{cnt[None]} result not recorded. {st['superseded']} were re-run later; {st['edited']} were followed by file edits and not re-run; "
                 f"{st['possible']} by shell commands that may have changed files and not re-run; {st['current']} have no later change recorded.</p>")
        if n > 40:
            o.append(f"<p class=small>The {n - 40} earliest check(s) are omitted; the 40 most recent are listed.</p>")
        o.append("<ul>")
        for c in ctx["checks"][-40:]:
            cls, label = {True: ("ok", "no error reported"), False: ("bad", "failed"), None: ("unk", "result not recorded")}[c["ok"]]
            late = {"edited": " <span class=unk>(files were edited after this check; not re-run since)</span>",
                    "possible": " <span class=small>(shell commands that may change files ran after this check; not re-run since)</span>",
                    "superseded": " <span class=small>(re-run later)</span>"}.get(c.get("state"), "")
            o.append(f"<li><code>{e(first_line(c['cmd'], 140))}</code> — <span class={cls}>{label}</span>{late}</li>")
        o.append("</ul>")
    else:
        o.append("<p>No test, lint or build commands were recorded in this period.</p>")
    o.append("<h2>Human review</h2><div class=box>"
             "<p>☐ I reviewed the changes listed above before delivery.</p>"
             "<p>☐ I ran the application / tests myself before delivery.</p>"
             "<p>Notes: <span contenteditable>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span></p>"
             f"<p>Reviewer: <span contenteditable>{e(ctx['author'] or '__________')}</span> &nbsp; Date: <span contenteditable>__________</span></p></div>")
    o.append("<h2>Basis of this report</h2><ul class=small>"
             "<li>Work requested: prompts typed by the developer in Claude Code sessions for this repository. Requests are not proof of completion.</li>"
             "<li>Changes delivered: commits from the repository history only. Session activity in other folders is excluded.</li>"
             "<li>Verification: commands as recorded in the logs; &ldquo;no error reported&rdquo; means the tool recorded no error, not that coverage was adequate.</li></ul>")
    o.append("<h2>Privacy</h2>")
    total = sum(ctx["hits"].values())
    o.append(f"<p class=small>Prompts and commands in this report were automatically scanned; {total} sensitive value(s) were masked "
             "(secrets, tokens, emails, home paths, IP addresses). Automatic redaction is best-effort. Read this report before sending it.</p>")
    o.append(f"<p class=small>Prepared with AI-assisted development tools (Claude Code). Session logs and repository history are the source for this report.</p>")
    return "".join(o)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Client-safe work report from Claude Code sessions + git.")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--since", help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--until", help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--client", default="")
    ap.add_argument("--author", default="", help="name shown as 'Prepared by' (does not filter commits)")
    ap.add_argument("--git-author", default=None, help="only include commits whose author matches this pattern (git --author)")
    ap.add_argument("--redact-term", action="append", default=[], help="extra private word to mask (repeatable)")
    ap.add_argument("--claude-dir", default=os.path.expanduser("~/.claude"))
    ap.add_argument("--out", help="write HTML report here")
    ap.add_argument("--preview", action="store_true", help="print every work item and redaction summary; write nothing")
    ap.add_argument("--diagnose", action="store_true", help="print log structure only (no content) to check format support")
    ap.add_argument("--allow-high", action="store_true", help="write the report even if high-severity secrets were masked")
    a = ap.parse_args(argv)

    repo = os.path.abspath(a.repo)
    if not os.path.isdir(repo):
        print(f"error: --repo {repo} is not a directory", file=sys.stderr)
        return 1
    if a.diagnose:
        diagnose(a.claude_dir, repo)
        return 0
    try:
        since = datetime.strptime(a.since, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ) if a.since else None
        until = (datetime.strptime(a.until, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ) + timedelta(days=1)) if a.until else None
    except ValueError:
        print("error: dates must be YYYY-MM-DD", file=sys.stderr)
        return 1
    if since and until and since >= until:
        print("error: --since is after --until", file=sys.stderr)
        return 1

    red = Redactor(a.redact_term)
    skipped = Counter()
    sessions, pdir = load_sessions(a.claude_dir, repo, since, until, skipped)
    if not sessions:
        print(f"warning: no Claude Code sessions found for this repo/period (looked in {pdir}*)", file=sys.stderr)
    g = git_summary(repo, since, until, a.git_author)
    if g is None:
        print(f"warning: {repo} is not a git repository (or git failed); the commits section will be empty", file=sys.stderr)
        g = ([], Counter(), 0, 0, 0)
    commits, files, ins, dele, n_authors = g

    src = {}                                   # redaction hits per report section, so review is targeted
    def phase(name, fn):
        before = Counter(red.hits)
        r = fn()
        src[name] = sum(v - before.get(k, 0) for k, v in red.hits.items() if k[1] == "high")
        return r

    def mk_items():
        out = []
        for s_ in sessions:
            for p in s_["prompts"]:
                out.append({"title": first_line(red(first_line(p["text"], 10**9))), "date": p["ts"].astimezone(LOCAL_TZ).strftime("%b %d"), "ts": p["ts"]})
        out.sort(key=lambda i: i["ts"])
        return out

    def mk_checks():
        return [{"cmd": red(c["cmd"]), "ok": c["ok"], "ts": c["ts"], "state": st} for c, st in check_states(sessions)]

    items = phase("work requests", mk_items)
    checks = phase("checks", mk_checks)
    commits = phase("commits", lambda: [[h, d, red(sj)] for h, d, sj in commits])
    def mk_meta():
        dirs_ = Counter()
        for p in files:                        # where the delivered (git) changes landed, relative to the repo
            dirs_[red(os.path.dirname(p) or "(project root)")] += 1
        return dict(title=("Work report" + (f" for {red(a.client)}" if a.client else "")), project=red(os.path.basename(repo)),
                    author=red(a.author), dirs=dirs_.most_common())
    meta = phase("title/author/folders", mk_meta)

    period = f"{a.since or 'start'} → {a.until or 'today'}"
    ctx = dict(meta, period=period, generated=datetime.now().strftime("%Y-%m-%d %H:%M"), items=items, n_items=len(items),
               commits=commits, n_commits=len(commits), n_files=len(files), ins=ins, dele=dele, n_authors=n_authors,
               git_filtered=bool(a.git_author), checks=checks, hits=red.hits)

    print(f"== {len(items)} work items, {len(commits)} commits, {len(checks)} checks ==", file=sys.stderr)
    if a.preview or not a.out:
        flag = lambda t: "⚑ " if "[REDACTED" in t else "  "
        for i, it in enumerate(items, 1):
            print(f"[{i}] {flag(it['title'])}{it['date']}  {it['title']}")
        print("-- checks (redacted; ⚑ = something was masked) --")
        for c in checks:
            print(f"  {flag(c['cmd'])}{ {True: 'no-error', False: 'FAILED', None: 'no-result'}[c['ok']] }{ {'edited': ' (edited after; not re-run)', 'possible': ' (possible changes after; not re-run)', 'superseded': ' (re-run later)'}.get(c['state'], '') }: {first_line(c['cmd'], 140)}")
        print("-- commits (redacted) --")
        for _h, d, sj in commits:
            print(f"  {flag(sj)}{d}  {sj}")
    if skipped:
        print("== skipped / excluded records: " + ", ".join(f"{k} {n}" for k, n in sorted(skipped.items())) + " ==", file=sys.stderr)
    print("== redactions ==", file=sys.stderr)
    if not red.hits:
        print("  none", file=sys.stderr)
    for (n, sev), c in sorted(red.hits.items(), key=lambda x: x[0][1]):
        print(f"  {sev:6} {n}: {c}", file=sys.stderr)
    hs = ", ".join(f"{k} {n}" for k, n in src.items() if n)
    if hs:
        print(f"  high-severity masks by report section: {hs}", file=sys.stderr)
    if a.preview or not a.out:
        return 0
    high = sum(c for (n, sev), c in red.hits.items() if sev == "high")
    if high and not a.allow_high:
        print(f"refusing to write: {high} high-severity secret(s) were masked. Review with --preview, rotate the secrets, "
              "then re-run with --allow-high.", file=sys.stderr)
        return 2
    try:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(render(ctx))
    except OSError as ex:
        print(f"error: cannot write {a.out}: {ex.strerror}", file=sys.stderr)
        return 1
    print(f"wrote {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
