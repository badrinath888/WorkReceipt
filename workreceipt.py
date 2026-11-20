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
    ("URL credentials", "high", re.compile(r"(\b[a-z][a-z0-9+.-]{0,30}://)[^\s/:@]+:[^\s/@]+@"), r"\1[REDACTED:creds]@"),
    ("Bearer token", "high", re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{16,}"), r"\1 [REDACTED:token]"),
    ("npm token", "high", re.compile(r"\bnpm_[A-Za-z0-9]{30,}\b"), "[REDACTED:npm-token]"),
    ("Basic auth", "high", re.compile(r"(?i)\b(basic)\s+[A-Za-z0-9+/=]{16,}"), r"\1 [REDACTED:token]"),
    ("secret assignment", "high", re.compile(
        r"(?i)(?<![A-Z0-9_.-])([\"']?\b[A-Z0-9_.-]*(?:password|passwd|passphrase|pwd|secret|token|api[_-]?key|private[_-]?key|credential|auth[_-]?key)[A-Z0-9_.-]*[\"']?)"
        r"(\s*[=:]\s*)(?:\"[^\"\n]{4,}\"|'[^'\n]{4,}'|[^\s'\",;}]{6,})"), r"\1\2[REDACTED:secret]"),
    # Space-separated CLI secrets: `--password hunter2xyz`, `curl -u user:pass`. (Added in M5: previously not masked at all.)
    ("secret option", "high", re.compile(r"(?i)(?<![\w-])(--?(?:password|passwd|passphrase|token|secret|api[_-]?key|auth[_-]?token|access[_-]?token)\s+)(?![-$<])(?:\"[^\"\n]{4,}\"|'[^'\n]{4,}'|[^\s'\"]{4,})"), r"\1[REDACTED:secret]"),
    ("curl user:password", "high", re.compile(r"(?<![\w-])((?:-u|--user)[ =]+)(?![-$<])(?:\"[^\"\s:]+:[^\"\n]{3,}\"|'[^'\s:]+:[^'\n]{3,}'|[^\s:'\"]+:[^\s'\"]{3,})"), r"\1[REDACTED:creds]"),
    ("email", "medium", re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED:email]"),
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
        try:
            fns = sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []
        except OSError:
            fns = []
        for fn in fns:
            if not fn.endswith(".jsonl"):
                continue
            prompts, cmds, files, pending, edits, shell_edits = [], [], OrderedDict(), {}, [], []
            first = last = None
            try:
                f = open(os.path.join(pdir, fn), encoding="utf-8", errors="replace")
            except OSError:
                if skipped is not None:
                    skipped["unreadable session file"] += 1
                continue
            with f:
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
                    if isinstance(uid, str) and uid:
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
                                if isinstance(b, dict) and b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str) and b.get("tool_use_id") in pending:
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
                                if isinstance(b.get("id"), str) and b.get("id"):
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
# One stylesheet serves the on-screen preview, the exported HTML and the PDF. Print rules (Letter, 0.75in margins, keep-together rows,
# repeating table headers, running footer where the renderer supports page-margin boxes) are what the PDF pagination relies on.
CSS = """
:root{--ink:#1d2430;--mute:#5b6676;--line:#dde2ea;--teal:#0f766e;--teal-bg:#e8f4f2;--ok:#166534;--bad:#b42318;--warn:#8a5a00;--soft:#f6f8fa}
*{box-sizing:border-box}
html{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font:10pt/1.42 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif;color:var(--ink);max-width:8.5in;margin:0 auto;padding:.6in .75in;overflow-wrap:anywhere;orphans:3;widows:3}
.brand{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid var(--teal);padding-bottom:6pt;margin-bottom:12pt}
.brand b{color:var(--teal);font-size:11pt;letter-spacing:.04em}.brand span{color:var(--mute);font-size:9pt;text-transform:uppercase;letter-spacing:.08em}
h1{font-size:22pt;line-height:1.2;margin:0 0 4pt;letter-spacing:-.01em;font-weight:650}
.ident{display:grid;grid-template-columns:repeat(2,1fr);gap:3pt 24pt;margin:8pt 0 10pt;font-size:9.5pt}
.ident div{display:flex;gap:8pt}.ident dt,.ident .k{color:var(--mute);min-width:62pt}.ident .v{font-weight:550}
.stats{display:grid;grid-template-columns:repeat(4,1fr) 1.5fr;border:1px solid var(--line);border-radius:6pt;margin:0 0 6pt;background:var(--soft);break-inside:avoid}
.stat{padding:6pt 9pt;border-right:1px solid var(--line)}.stat:last-child{border-right:0}
.stat b{display:block;font-size:14pt;line-height:1.2;white-space:nowrap;color:var(--teal);font-weight:650}.stat{font-size:8pt;color:var(--mute);text-transform:uppercase;letter-spacing:.05em}.stat b{text-transform:none;letter-spacing:0}
h2{font-size:12pt;margin:13pt 0 3pt;padding-bottom:3pt;border-bottom:1px solid var(--line);color:var(--ink);break-after:avoid;page-break-after:avoid}
h2 .n{color:var(--teal);margin-right:6pt}
.lead{color:var(--mute);font-size:9pt;margin:2pt 0 5pt;break-after:avoid;page-break-after:avoid}
.small{font-size:8.5pt;color:var(--mute)}
.req{display:grid;grid-template-columns:20pt 1fr auto;gap:8pt;padding:3pt 0;border-bottom:1px solid #eef1f5;break-inside:avoid;page-break-inside:avoid}
.req .no{color:var(--teal);font-weight:650;font-variant-numeric:tabular-nums}.req .src{color:var(--mute);font-size:8pt;border:1px solid var(--line,#ddd);border-radius:8pt;padding:0 5pt;white-space:nowrap}.req .dt{color:var(--mute);font-size:8.5pt;white-space:nowrap}
table{width:100%;border-collapse:collapse;font-size:9.5pt}
thead{display:table-header-group}
th{white-space:nowrap;text-align:left;font-size:8pt;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);font-weight:600;padding:4pt 6pt;border-bottom:1px solid var(--line)}
td{padding:2.5pt 6pt;border-bottom:1px solid #eef1f5;vertical-align:top}
tr{break-inside:avoid;page-break-inside:avoid}
td.d,td.h{white-space:nowrap;color:var(--mute);font-variant-numeric:tabular-nums;width:1%}td.h{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:8.5pt}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:8.5pt;background:var(--soft);padding:1pt 3pt;border-radius:3pt}
.chip{display:inline-block;font-size:8pt;font-weight:600;padding:1pt 6pt;border-radius:8pt;border:1px solid currentColor;white-space:nowrap}
.chip.ok{color:var(--ok);background:#ecf8f0}.chip.bad{color:var(--bad);background:#fdf0ee}.chip.unk{color:var(--warn);background:#fdf6e6}
.note{color:var(--mute);font-size:8.5pt;display:block;margin-top:1pt}
.sign{border:1px solid var(--line);border-radius:6pt;padding:6pt 12pt;background:var(--soft);break-inside:avoid;page-break-inside:avoid}
.sign p{margin:5pt 0}.cb{display:inline-block;width:10pt;height:10pt;border:1.4pt solid var(--ink);border-radius:2pt;vertical-align:-1.5pt;margin-right:7pt}
.line{display:inline-block;min-width:150pt;border-bottom:1px solid var(--ink);padding:0 4pt}
.two{display:grid;grid-template-columns:1fr 1fr;gap:0 22pt;break-inside:avoid;page-break-inside:avoid}.basis li{margin:2pt 0}.basis{padding-left:14pt;margin:4pt 0}
.keep{break-inside:avoid;page-break-inside:avoid}
[contenteditable]{outline:1px dashed #c4cbd8;outline-offset:2px;border-radius:3px}
.foot{break-before:avoid;page-break-before:avoid;margin-top:8pt;padding-top:6pt;border-top:1px solid var(--line);font-size:8pt;color:var(--mute)}
@page{size:letter;margin:.7in .75in .75in}
@media print{body{max-width:none;padding:0;margin:0;font-size:10pt}[contenteditable]{outline:none}.noprint{display:none}}
@media screen and (max-width:640px){.two{grid-template-columns:1fr}.stats{grid-template-columns:repeat(2,1fr)}.ident{grid-template-columns:1fr}body{padding:.4in .3in}}
"""
# Chrome renders page-margin boxes; WKWebView printing ignores them (so the macOS PDF has no running footer).
PRINT_FOOTER = "@page{@bottom-left{content:'WorkReceipt work report';font:8pt sans-serif;color:#5b6676}@bottom-right{content:'Page ' counter(page) ' of ' counter(pages);font:8pt sans-serif;color:#5b6676}}"


def esc(s):
    return html.escape(s, quote=True)


def first_line(t, n=110):
    l = t.strip().splitlines()[0] if t.strip() else ""
    return l if len(l) <= n else l[: n - 1] + "…"


def render(ctx):
    e = esc
    o = []
    o.append(f"<!doctype html><meta charset=utf-8><meta http-equiv=Content-Security-Policy content=\"default-src 'none'; style-src 'unsafe-inline'\">"
             f"<meta name=viewport content='width=device-width,initial-scale=1'><title>{e(ctx['title'])}</title><style>{CSS}{PRINT_FOOTER}</style>")
    o.append("<div class=brand><b>WorkReceipt</b><span>"
             + ("Developer report · PRIVATE · not for clients" if ctx.get("private") else "Client work report") + "</span></div>")
    o.append(f"<h1>{e(ctx['title'])}</h1><div class=ident>"
             f"<div><span class=k>Project</span><span class=v>{e(ctx['project'])}</span></div>"
             f"<div><span class=k>Period</span><span class=v>{e(ctx['period'])}</span></div>"
             + (f"<div><span class=k>Prepared by</span><span class=v>{e(ctx['author'])}</span></div>" if ctx["author"] else "")
             + f"<div><span class=k>Generated</span><span class=v>{e(ctx['generated'])}</span></div></div>")
    nchk = len(ctx["checks"]); ok = sum(1 for c in ctx["checks"] if c["ok"] is True)
    o.append("<div class=stats>"
             f"<div class=stat><b>{ctx['n_items']}</b>work requests</div>"
             f"<div class=stat><b>{ctx['n_commits']}</b>commits</div>"
             f"<div class=stat><b>{ctx['n_files']}</b>files changed</div>"
             f"<div class=stat><b>+{ctx['ins']} / −{ctx['dele']}</b>lines</div>"
             f"<div class=stat><b>{ok} / {nchk}</b>checks, no error</div></div>")
    o.append("<p class=small>Counts come from the session logs and Git history for this period. Checks are commands recorded in the logs; they were not re-run for this report.</p>")
    o.append("<h2><span class=n>1</span>Work requested</h2>")
    o.append("<p class=lead>Requests given to the AI coding assistant during this period. A request listed here "
             "does not mean the work was completed; see Changes delivered and Verification below.</p>")
    if ctx["items"]:
        o.append("<p class='small noprint'>Titles below are editable in your browser before you print or save as PDF.</p>")
        for i, it in enumerate(ctx["items"], 1):
            src = "<span class=src>" + e(it["source"]) + "</span>" if it.get("source") else ""
            o.append(f"<div class=req><span class=no>{i}</span><span contenteditable>{e(it['title'])}</span>{src}<span class=dt>{e(it['date'])}</span></div>")
    else:
        o.append("<p>No session activity found in this period.</p>")
    o.append("<h2><span class=n>2</span>Changes delivered</h2>")
    if ctx["commits"]:
        o.append(f"<p class=lead>All {ctx['n_commits']} commit(s) in this repository's history during the period "
                 f"({ctx['n_authors']} author(s){'; filtered by author' if ctx['git_filtered'] else ''}). Git is the evidence of delivered changes.</p>")
        o.append("<table><thead><tr><th>Date</th><th>Commit</th><th>Summary</th></tr></thead><tbody>")
        for h, d, s in ctx["commits"]:
            o.append(f"<tr><td class=d>{e(d)}</td><td class=h>{e(str(h)[:7])}</td><td>{e(s)}</td></tr>")
        o.append("</tbody></table>")
        if ctx["dirs"]:
            o.append("<p class='lead keep' style='margin-top:12pt'><b>Where the changes landed</b></p>")
            o.append("<table><thead><tr><th>Folder</th><th>Files</th></tr></thead><tbody>")
            for d, n in ctx["dirs"]:
                o.append(f"<tr><td><code>{e(d)}</code></td><td class=d>{n}</td></tr>")
            o.append("</tbody></table>")
    else:
        o.append("<p>No commits found in this period.</p>")
    o.append("<h2><span class=n>3</span>Verification</h2>")
    o.append("<p class=lead>Test, lint and build commands recorded in the session logs, with the outcome the tool recorded. "
             "They were not re-run for this report.</p>")
    if ctx["checks"]:
        n = len(ctx["checks"]); cnt = Counter(c["ok"] for c in ctx["checks"]); st = Counter(c.get("state") for c in ctx["checks"])
        o.append(f"<p class='small keep'>{n} check command(s) recorded: {cnt[True]} no error reported, {cnt[False]} failed, "
                 f"{cnt[None]} result not recorded. {st['superseded']} were re-run later; {st['edited']} were followed by file edits and not re-run; "
                 f"{st['possible']} by shell commands that may have changed files and not re-run; {st['current']} have no later change recorded.</p>")
        o.append("<table><thead><tr><th>Command</th><th>Outcome</th></tr></thead><tbody>")
        for c in ctx["checks"]:
            cls, label = {True: ("ok", "No error reported"), False: ("bad", "Failed"), None: ("unk", "Result not recorded")}[c["ok"]]
            late = {"edited": "Files were edited after this check; not re-run since.",
                    "possible": "Shell commands that may change files ran after this check; not re-run since.",
                    "superseded": "Re-run later."}.get(c.get("state"), "")
            o.append(f"<tr><td><code>{e(first_line(c['cmd'], 140))}</code>{f'<span class=note>{late}</span>' if late else ''}</td>"
                     f"<td style='white-space:nowrap;width:1%'><span class='chip {cls}'>{label}</span></td></tr>")
        o.append("</tbody></table>")
    else:
        o.append("<p>No test, lint or build commands were recorded in this period.</p>")
    o.append("<h2><span class=n>4</span>Human review and sign-off</h2><div class=sign>"
             "<p><span class=cb></span>I reviewed the changes listed above before delivery.</p>"
             "<p><span class=cb></span>I ran the application / tests myself before delivery.</p>"
             "<p>Notes: <span class=line contenteditable>&nbsp;</span></p>"
             f"<p>Reviewer: <span class=line contenteditable>{e(ctx['author'] or '')}&nbsp;</span> &nbsp; Date: <span class=line contenteditable style='min-width:90pt'>&nbsp;</span></p></div>")
    tools = ctx.get("tools", ["Claude Code"])
    tl = e(" / ".join(tools))
    li1 = (f"<li>Work requested: prompts typed by the developer in {tl} sessions for this repository. Requests are not proof of completion.</li>" if tools
           else "<li>Work requested: not included (Git-only report; no AI session logs were read).</li>")
    o.append("<div class=two><div><h2 class=keep><span class=n>5</span>Basis of this report</h2><ul class='basis small'>"
             + li1 +
             "<li>Changes delivered: commits from the repository history only. Session activity in other folders is excluded.</li>"
             "<li>Verification: commands as recorded in the logs; &ldquo;no error reported&rdquo; means the tool recorded no error, not that coverage was adequate.</li></ul></div>")
    total = sum(ctx["hits"].values())
    o.append("<div><h2><span class=n>6</span>Privacy</h2>")
    o.append(f"<p class='small keep'>Prompts and commands in this report were automatically scanned; {total} sensitive value(s) were masked "
             "(secrets, tokens, emails, home paths, IP addresses). Automatic redaction is best-effort. Read this report before sending it.</p>"
             + (f"<p class='small keep'>Prepared with AI-assisted development tools ({tl}). Session logs and repository history are the source for this report.</p></div></div>" if tools
                else "<p class='small keep'>Prepared from repository (Git) history only; no AI session logs were used.</p></div></div>"))
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
