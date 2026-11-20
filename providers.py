"""Provider-independent activity model + adapters (v0.7.0).

Activity model = the session dict the report already consumes:
  {id, provider, start, end, prompts:[{ts,text}], checks:[{ts,cmd,ok}], files:{path:n}, edits:[ts], shell_edits:[ts]}
Every adapter returns that shape, so redaction, Client-Safe Mode and rendering are provider-blind: nothing a provider
emits reaches a report without going through app_core.build's masking.

Status (honest):
  claude   - supported (existing, tested against real logs).
  codex    - EXPERIMENTAL: written from published CLI behaviour (rollout JSONL under <dir>/sessions), synthetic fixtures only.
  opencode - EXPERIMENTAL: written from the documented storage layout (storage/session|message|part), synthetic fixtures only.
  cursor   - NOT SUPPORTED: no documented, stable local transcript format (state lives in an internal SQLite DB). Integration
             boundary: a future adapter must be a `load(dir, repo, since, until, skipped)` returning the model above.
Git-only reporting needs no provider: with every provider off, load_all returns [] and the git section stands alone.
"""
import json, os
from collections import OrderedDict

import workreceipt as w

STATUS = {"claude": "supported", "codex": "experimental", "opencode": "experimental", "cursor": "unsupported"}
LABEL = {"claude": "Claude Code", "codex": "Codex CLI", "opencode": "OpenCode", "cursor": "Cursor"}
DIR_KEY = {"claude": "claude_dir", "codex": "codex_dir", "opencode": "opencode_dir"}


def _new(sid, provider):
    return {"id": sid, "provider": provider, "start": None, "end": None, "prompts": [], "checks": [], "files": OrderedDict(),
            "edits": [], "shell_edits": [], "_pending": {}}


def _touch(s, ts):
    s["start"] = s["start"] or ts
    s["end"] = ts


def _cmd(c):
    return " ".join(map(str, c)) if isinstance(c, list) else c


def _shell(s, ts, cmd, rec_key=None):
    if not isinstance(cmd, str):
        return
    if w.is_check(cmd):
        rec = {"ts": ts, "cmd": cmd, "ok": None}
        s["checks"].append(rec)
        if rec_key:
            s["_pending"][rec_key] = rec
    elif w.MODIFY_RX.search(cmd):
        s["shell_edits"].append(ts)


def _file(s, ts, p, base, repo):
    if isinstance(p, str) and p:
        p = p if os.path.isabs(p) else os.path.join(base or repo, p)
        if w.under(p, repo):
            s["files"][p] = s["files"].get(p, 0) + 1
            s["edits"].append(ts)


def _done(s, out):
    s.pop("_pending", None)
    if s["prompts"] or s["checks"] or s["files"]:
        out.append(s)


def _ok(since, until, ts):
    return ts is not None and not (since and ts < since) and not (until and ts >= until)


def _jsonl(path, skipped):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if isinstance(ev, dict):
                    yield ev
    except OSError:
        if skipped is not None:
            skipped["unreadable session file"] += 1


def load_claude(d, repo, since, until, skipped=None):
    out, _ = w.load_sessions(d, repo, since, until, skipped)
    for s in out:
        s["provider"] = "claude"
    return out


def load_codex(d, repo, since, until, skipped=None):
    """Rollout files: {timestamp, type, payload}. cwd comes from session_meta/turn_context; sessions outside repo are dropped."""
    out, root = [], os.path.join(d, "sessions")
    for dp, _dn, fns in sorted(os.walk(root)):
        for fn in sorted(fns):
            if not fn.endswith(".jsonl"):
                continue
            s, cwd, mine = _new(fn[:-6], "codex"), None, False
            for ev in _jsonl(os.path.join(dp, fn), skipped):
                p = ev.get("payload") if isinstance(ev.get("payload"), dict) else {}
                if isinstance(p.get("cwd"), str) and p["cwd"]:
                    cwd = p["cwd"]
                    mine = w.under(cwd, repo)
                if not mine:
                    continue
                ts = w.parse_ts(ev.get("timestamp", ""))
                if not _ok(since, until, ts):
                    continue
                _touch(s, ts)
                t, k = p.get("type"), ev.get("type")
                if k == "response_item" and t == "message" and p.get("role") == "user":
                    text, why = w.classify_prompt([{"type": "text", "text": b.get("text")} for b in p.get("content") or [] if isinstance(b, dict)])
                    if text and text.lower().strip(" .!") not in w.ACKS:
                        s["prompts"].append({"ts": ts, "text": text})
                    elif why and skipped is not None:
                        skipped[why] += 1
                elif k == "response_item" and t in ("function_call", "local_shell_call"):
                    try:
                        a = json.loads(p.get("arguments") or "{}")
                    except Exception:
                        a = {}
                    act = p.get("action") if isinstance(p.get("action"), dict) else {}
                    _shell(s, ts, _cmd(a.get("command") or act.get("command")), p.get("call_id"))
                elif k == "response_item" and t == "function_call_output" and p.get("call_id") in s["_pending"]:
                    try:
                        code = json.loads(p.get("output") or "{}").get("metadata", {}).get("exit_code")
                    except Exception:
                        code = None
                    s["_pending"][p["call_id"]]["ok"] = (code == 0) if isinstance(code, int) else None
                elif k == "response_item" and t == "custom_tool_call" and p.get("name") == "apply_patch":
                    for line in str(p.get("input") or "").splitlines():
                        for pre in ("*** Update File: ", "*** Add File: "):
                            if line.startswith(pre):
                                _file(s, ts, line[len(pre):].strip(), cwd, repo)
            _done(s, out)
    return out


def _json(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def _ms(v):
    return w.datetime.fromtimestamp(v / 1000, w.LOCAL_TZ) if isinstance(v, (int, float)) else None


def load_opencode(d, repo, since, until, skipped=None):
    """storage/session/<project>/<id>.json (directory), storage/message/<session>/*.json (role,time), storage/part/<message>/*.json."""
    st, out = os.path.join(d, "storage"), []
    sroot = os.path.join(st, "session")
    for dp, _dn, fns in sorted(os.walk(sroot)):
        for fn in sorted(f for f in fns if f.endswith(".json")):
            meta = _json(os.path.join(dp, fn))
            if not meta or not w.under(meta.get("directory"), repo):
                continue
            sid = str(meta.get("id") or fn[:-5])
            s = _new(sid, "opencode")
            mdir = os.path.join(st, "message", sid)
            msgs = [m for m in (_json(os.path.join(mdir, f)) for f in sorted(os.listdir(mdir)) if f.endswith(".json")) if m] if os.path.isdir(mdir) else []
            for m in sorted(msgs, key=lambda m: (m.get("time") or {}).get("created") or 0):
                ts = _ms((m.get("time") or {}).get("created"))
                if not _ok(since, until, ts):
                    continue
                _touch(s, ts)
                pdir = os.path.join(st, "part", str(m.get("id")))
                for pf in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
                    part = _json(os.path.join(pdir, pf)) or {}
                    if m.get("role") == "user" and part.get("type") == "text" and not part.get("synthetic"):
                        text, why = w.classify_prompt(part.get("text"))
                        if text and text.lower().strip(" .!") not in w.ACKS:
                            s["prompts"].append({"ts": ts, "text": text})
                        elif why and skipped is not None:
                            skipped[why] += 1
                    elif part.get("type") == "tool":
                        inp = (part.get("state") or {}).get("input") or {}
                        if part.get("tool") == "bash":
                            _shell(s, ts, inp.get("command"))
                            if s["checks"] and s["checks"][-1]["ts"] == ts and s["checks"][-1]["ok"] is None:
                                stt = (part.get("state") or {}).get("status")
                                s["checks"][-1]["ok"] = True if stt == "completed" else False if stt == "error" else None
                        elif part.get("tool") in ("edit", "write", "patch"):
                            _file(s, ts, inp.get("filePath") or inp.get("path"), meta.get("directory"), repo)
            _done(s, out)
    return out


LOADERS = {"claude": load_claude, "codex": load_codex, "opencode": load_opencode}


def enabled(settings):
    e = settings.get("providers")
    return [p for p in LOADERS if (e.get(p) if isinstance(e, dict) else p == "claude")]


def load_all(settings, repo, since, until, skipped=None, claude_dir=None):
    """Sessions from every enabled provider, tagged with `provider`. One broken adapter never blocks the others or the git report."""
    out = []
    for p in enabled(settings):
        d = claude_dir if (p == "claude" and claude_dir) else settings.get(DIR_KEY[p])
        if not d:
            continue
        try:
            out += LOADERS[p](d, repo, since, until, skipped)
        except Exception:
            if skipped is not None:
                skipped[f"{p} adapter error"] += 1
    return out


def discover(provider, d):
    """[(cwd, mtime)] per session for the project list. Reads only the cwd field, never content."""
    out = []
    if provider == "codex":
        for dp, _dn, fns in os.walk(os.path.join(d, "sessions")):
            for fn in fns:
                if fn.endswith(".jsonl"):
                    p = os.path.join(dp, fn)
                    for ev in _jsonl(p, None):
                        c = (ev.get("payload") or {}).get("cwd") if isinstance(ev.get("payload"), dict) else None
                        if isinstance(c, str) and c:
                            out.append((c, os.path.getmtime(p)))
                            break
    elif provider == "opencode":
        for dp, _dn, fns in os.walk(os.path.join(d, "storage", "session")):
            for fn in fns:
                if fn.endswith(".json"):
                    m = _json(os.path.join(dp, fn))
                    if m and isinstance(m.get("directory"), str):
                        out.append((m["directory"], os.path.getmtime(os.path.join(dp, fn))))
    return out
