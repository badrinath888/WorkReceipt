#!/usr/bin/env python3
"""Content-free final review: unknown log structure (and whether cache-like records duplicate real prompts), the nature and
exposure status of each high-severity detection, stale-check evidence, and report-section separation.

Prints counts, schema/field names and value *classes* only. Never prints prompts, commands, commit subjects, paths or detected
values. Read-only (the report is built in a temp folder). Normally run through validate_local.py.

    python3 final_review.py --repo /path/to/AssetHandoff --since 2026-11-01
"""
import argparse, contextlib, html, io, json, os, re, subprocess, sys, tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workreceipt as w  # noqa: E402

BENIGN_TYPES = {"user", "assistant", "summary", "system", "file-history-snapshot"}
META_KEYS = {"timestamp", "uuid", "parentUuid", "sessionId", "cwd", "version", "gitBranch", "requestId", "leafUuid", "type"}
NAME_RX = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]{0,40}")
HEADINGS = ["Work requested", "Changes delivered", "Verification", "Human review and sign-off", "Basis of this report", "Privacy"]
LIKELY_FP = {"variable/env reference", "placeholder/test-like", "letters only"}


def nm(x):
    x = x if isinstance(x, str) else type(x).__name__
    return "mcp__*" if x.startswith("mcp__") else (x if NAME_RX.fullmatch(x) else "<odd-name>")


# Fields that can hold text a person typed. Everything else (ids, hashes, signatures, system prompts, tool descriptions,
# titles, paths) is metadata and is counted by reason, never treated as a possible missing request.
PROMPT_LEAVES = {"content", "prompt", "lastPrompt", "text", "message", "userMessage", "input"}
QUEUE_NON_PROMPT_OPS = {"remove", "dequeue", "popall", "pop"}


SYSTEM_KEYS = {"system", "systemPrompt", "system_prompt", "tools", "tool_choice", "instructions"}


def collect(ev):
    """Candidate user-authored text outside user records, decided by structure.
    -> ([(path, text, origin)], Counter of reasons for text that is NOT a candidate). Paths are schema names only.
    A dict with `role` + `content` is a chat message: only role 'user' text blocks can be user-authored (assistant, system and
    tool roles, tool_use/tool_result blocks, `system`/`tools` definitions are never candidates). origin 'replay' = a copy of a
    message inside an API payload; 'direct' = a prompt-style field of a record such as queue-operation or last-prompt."""
    items, meta = [], Counter()

    def message(role, content, path):
        if role != "user":
            meta[f"message with role '{nm(role)}' (not user-authored)"] += 1
            return
        blocks = [content] if isinstance(content, str) else [b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"] if isinstance(content, list) else []
        for tx in blocks:
            if not isinstance(tx, str) or not tx.strip():
                continue
            clean, why = w.classify_prompt(tx)
            if not clean:
                meta["user-role text: " + (why or "empty")] += 1
            elif len(norm(clean)) < 8:
                meta["user-role text: shorter than 8 characters"] += 1
            else:
                items.append((path + ".message[user]", clean, "replay"))

    def walk(o, path, depth):
        if depth > 8:
            return
        if isinstance(o, dict):
            role = o.get("role")
            if isinstance(role, str) and "content" in o:
                message(role, o["content"], path); return
            for k, v in o.items():
                if depth == 0 and k in META_KEYS:
                    continue
                if k in SYSTEM_KEYS:
                    meta["system prompt / tool definitions (not user-authored)"] += 1; continue
                walk(v, path + "." + nm(k), depth + 1)
        elif isinstance(o, list):
            for v in o[:500]:
                walk(v, path + "[]", depth + 1)
        elif isinstance(o, str) and len(o) >= 20:
            if len(o) <= 2_000_000 and o.lstrip()[:1] in ("{", "["):      # a serialized payload ("blob")
                try:
                    parsed = json.loads(o)
                except Exception:
                    parsed = None
                if isinstance(parsed, (dict, list)):
                    walk(parsed, path + ".<json>", depth + 1); return
            why = non_prompt_reason(ev, path.rsplit(".", 1)[-1].replace("[]", ""), o)
            if why:
                meta[why] += 1
            else:
                items.append((path, o, "direct"))

    walk(ev, "", 0)
    return items, meta


def non_prompt_reason(ev, leaf, s):
    """None if the string could be typed user text; otherwise a short reason it is metadata/system content."""
    t = ev.get("type")
    if leaf not in PROMPT_LEAVES:
        return "field is not a prompt-style field (ids, hashes, signatures, titles, paths, tool/system descriptions)"
    att = ev.get("attachment")
    if isinstance(att, dict) and not re.search(r"queue|prompt", str(att.get("type", "")), re.I):
        return "attachment of a non-prompt kind (" + nm(att.get("type")) + ")"
    if t == "queue-operation" and str(ev.get("operation", "")).lower() in QUEUE_NON_PROMPT_OPS:
        return "queue bookkeeping record (" + nm(ev.get("operation")) + ")"
    body = norm(s)
    if not re.search(r"\s", body) or re.fullmatch(r"[0-9a-fA-F-]{20,}|[A-Za-z0-9+/=_-]{20,}", body):
        return "no whitespace: id / hash / signature / token-like"
    if body.startswith(w.NOISE + (w.CONTINUATION,)):
        return "Claude Code system text (command / reminder / continuation envelope)"
    if body[:1] in "{[" or len(body) > 0 and re.match(r"^<[A-Za-z][\w-]*[ >]", body) and not body.startswith("<pasted_content"):
        return "structured data / markup"
    return None


def norm(s):
    return re.sub(r"\s+", " ", w.PLACEHOLDER_RX.sub("", s)).strip()[:120]


def vclass(v):
    if re.search(r"\$\{?[A-Za-z_]|process\.env|os\.environ|getenv|%[A-Z_]+%", v): return "variable/env reference"
    if re.search(r"(?i)xxx|your[_-]|example|changeme|change-me|dummy|fake|sample|placeholder|<[^>]+>|\*{3,}|todo|\btest", v): return "placeholder/test-like"
    if re.fullmatch(r"[A-Za-z]+", v): return "letters only"
    if re.fullmatch(r"\d+", v): return "digits only"
    if re.fullmatch(r"[0-9a-fA-F]{16,}", v): return "hex string"
    if re.search(r"[A-Z]", v) and re.search(r"[a-z]", v) and re.search(r"\d", v): return "random-looking (mixed case + digits)"
    return "other"


def where(text, start):
    if text[max(0, start - 3):start].endswith("--"): return "CLI flag"
    if re.search(r"(?:^|[;&|]\s*)[\w.-]*$", text[:start]) and not text[:start].strip().endswith(("-", "=")): return "env prefix / assignment"
    return "inline"


def git_has(repo, *args, timeout=60):
    try:
        r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout)
        return r
    except subprocess.TimeoutExpired:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True); ap.add_argument("--since", required=True); ap.add_argument("--until")
    ap.add_argument("--claude-dir", default=os.path.expanduser("~/.claude")); ap.add_argument("--summary-out")
    a = ap.parse_args()
    repo = os.path.abspath(a.repo)
    L, flags = [], Counter()

    def add(level, label, detail=""):
        L.append(f"[{level:6}] {label}" + (f": {detail}" if detail else "")); flags[level] += 1

    # 1. structure census (names only) + user-text index for duplicate analysis
    base = os.path.join(a.claude_dir, "projects"); enc = w.encode_project_dir(repo)
    dirs = [d for d in (os.listdir(base) if os.path.isdir(base) else []) if d == enc or d.startswith(enc + "-")]
    types, ukeys, ublocks, utools, texty, meta_text = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    cands, utexts, tool_edit, shell_mod, origin_of = {}, [], 0, 0, {}
    for d in dirs:
        for fn in os.listdir(os.path.join(base, d)):
            if not fn.endswith(".jsonl"): continue
            for line in open(os.path.join(base, d, fn), encoding="utf-8", errors="replace"):
                try: ev = json.loads(line)
                except Exception: continue
                if not isinstance(ev, dict): continue
                t = ev.get("type"); types[nm(t)] += 1
                for k in ev:
                    if k not in w.KNOWN_KEYS: ukeys[nm(k)] += 1
                if t == "user":
                    txt, why = w.user_prompt(ev)
                    msg = ev.get("message"); cont = msg.get("content") if isinstance(msg, dict) else None
                    for b in [cont] if isinstance(cont, str) else [x.get("text") for x in cont if isinstance(x, dict) and x.get("type") == "text"] if isinstance(cont, list) else []:
                        if isinstance(b, str) and norm(b):
                            utexts.append((norm(b), "kept" if txt else (why or "skipped")))
                elif t not in BENIGN_TYPES:
                    op = nm(ev.get("operation")) if t == "queue-operation" and ev.get("operation") is not None else None
                    items_, meta_ = collect(ev); meta_text.update(meta_)
                    for pth, sv, origin in items_:
                        key = f"{nm(t)}{'[' + op + ']' if op else ''}{pth}"; texty[key] += 1; origin_of[key] = origin
                        cands.setdefault(key, set()).add(norm(sv))
                m = ev.get("message"); c = m.get("content") if isinstance(m, dict) else None
                for b in c if isinstance(c, list) else []:
                    if not isinstance(b, dict): continue
                    if b.get("type") not in w.KNOWN_BLOCKS: ublocks[nm(b.get("type"))] += 1
                    if b.get("type") == "tool_use":
                        n = b.get("name")
                        if n not in w.KNOWN_TOOLS: utools[nm(n)] += 1
                        if n in ("Edit", "Write", "MultiEdit", "NotebookEdit"): tool_edit += 1
                        cmd = (b.get("input") or {}).get("command") if isinstance(b.get("input"), dict) else None
                        if n == "Bash" and isinstance(cmd, str) and not w.is_check(cmd) and w.MODIFY_RX.search(cmd): shell_mod += 1
    add("INFO", "record types", ", ".join(f"{k}={n}" for k, n in types.most_common()))
    add("INFO", "unrecognised top-level keys (metadata names)", ", ".join(f"{k}={n}" for k, n in ukeys.most_common(25)) or "none")
    add("INFO", "unrecognised block types / tool names", ", ".join(f"{k}={n}" for k, n in (ublocks + utools).most_common(25)) or "none")
    if meta_text:
        add("INFO", "text fields outside user records classed as metadata/system (not requests)", "; ".join(f"{k}={n}" for k, n in meta_text.most_common()))
    if not texty:
        add("PASS", "no prompt-style text fields outside user records", "no alternate prompt source present")
    else:
        uidx = {}
        for u, st in utexts:
            uidx.setdefault(u[:8], []).append((u, st))
        bad, replay_bad, replay_shape = [], [], Counter()
        for key in sorted(cands):
            kept = skip = none = 0; why = Counter()
            for c_ in cands[key]:
                best = None
                for u, st in uidx.get(c_[:8], []):
                    n = min(len(c_), len(u))
                    if n >= 8 and c_[:n] == u[:n]:
                        best = st
                        if st == "kept": break
                if best == "kept": kept += 1
                elif best: skip += 1; why[best] += 1
                else:
                    none += 1
                    if origin_of.get(key) == "replay":
                        replay_shape["start with '<' or '['" if c_[:1] in "<[" else "start with text"] += 1
            tag = " [replayed API payload]" if origin_of.get(key) == "replay" else ""
            L.append(f"           - {key}{tag}: {len(cands[key])} distinct value(s): duplicate of a kept request {kept}, of a skipped record {skip}"
                     + (f" ({', '.join(f'{k}={n}' for k, n in why.items())})" if why else "") + f", matches no user record {none}")
            if none:
                (replay_bad if origin_of.get(key) == "replay" else bad).append(f"{key}={none}")
        if replay_bad:
            add("INFO", "user-role text inside replayed API payloads with no matching user record (payload copies / system-injected context; "
                        "not treated as requests: typed prompts always have their own user record)", ", ".join(replay_bad) + "; " + ", ".join(f"{k}={n}" for k, n in replay_shape.items()))
        if bad:
            add("REVIEW", "prompt-style text outside user records that matches NO user record (possible requests not captured)", ", ".join(bad))
        else:
            add("PASS", "every prompt-style field outside user records duplicates text already in user records (cache/queue copy)", "no additional requests found")

    # 2. generate the report once (temp), then analyse detections against it
    since = w.datetime.strptime(a.since, "%Y-%m-%d").replace(tzinfo=w.LOCAL_TZ)
    until = (w.datetime.strptime(a.until, "%Y-%m-%d").replace(tzinfo=w.LOCAL_TZ) + w.timedelta(days=1)) if a.until else None
    sessions, _ = w.load_sessions(a.claude_dir, repo, since, until)
    g = w.git_summary(repo, since, until) or ([], Counter(), 0, 0, 0)
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "r.html")
        argv = ["--repo", repo, "--claude-dir", a.claude_dir, "--since", a.since, "--out", out, "--allow-high"] + (["--until", a.until] if a.until else [])
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            rc = w.main(argv)
        doc = open(out, encoding="utf-8").read() if rc == 0 and os.path.exists(out) else ""

    exported = [("work requests", w.first_line(p["text"], 10 ** 9)) for s in sessions for p in s["prompts"]]
    exported += [("checks", c["cmd"]) for s in sessions for c in s["checks"]] + [("commits", sj) for _h, _d, sj in g[0]]
    det, vals, overlap = Counter(), {}, 0
    for sec, text in exported:
        cur = text                                   # same order as the real Redactor: later rules see earlier masks
        for name, sev, rx, rep in w.RULES:
            for m in rx.finditer(cur):
                val = m.group(0)
                if name == "secret assignment": val = val[len(m.group(1)) + len(m.group(2)):]
                if sev != "high": continue
                if "[REDACTED" in val:
                    overlap += 1; det[(sec, name, where(cur, m.start()), "overlaps a value another rule already masked", "-")] += 1
                else:
                    det[(sec, name, where(cur, m.start()), vclass(val), "<16" if len(val) < 16 else "16-39" if len(val) < 40 else "40+")] += 1
                    vals[val] = vclass(val)
            cur = rx.sub(rep, cur)
        for m in w.ENTROPY_RX.finditer(cur):
            tk = m.group(0)
            if re.search(r"[A-Z]", tk) and re.search(r"[a-z]", tk) and re.search(r"\d", tk) and w._entropy(tk) >= 3.5:
                det[(sec, "unlabeled high-entropy token", "inline", vclass(tk), "16-39" if len(tk) < 40 else "40+")] += 1; vals[tk] = vclass(tk)
    add("INFO", "high-severity detections", f"{sum(det.values())} rule hit(s): {sum(det.values()) - overlap} on {len(vals)} distinct value(s), {overlap} overlapping a value another rule had already masked")
    for (sec, rule, ctx_, cls, ln), n in sorted(det.items(), key=lambda x: -x[1]):
        L.append(f"           - {n}x in {sec}: rule '{rule}', {ctx_}, value class '{cls}', length {ln}")
    for i, (v, cls) in enumerate(sorted(vals.items(), key=lambda kv: kv[1]), 1):
        in_report = bool(doc) and (v in doc or html.escape(v) in doc or (len(v) >= 16 and v[:12] in doc))
        gr = git_has(repo, "grep", "-F", "-q", "--untracked", "-e", v)
        in_files = None if gr is None else gr.returncode == 0
        hr = git_has(repo, "log", "--all", "-F", "-S", v, "--oneline", timeout=90)
        in_hist = None if hr is None else bool(hr.stdout.strip())
        yn = lambda x: "unknown" if x is None else "YES" if x else "no"
        L.append(f"           - value #{i}: class '{cls}'; in finished report: {yn(in_report)}; in repo files: {yn(in_files)}; in git history: {yn(in_hist)}")
        if in_report: add("FAIL", f"value #{i} appears in the report", "masking failed")
        elif cls in LIKELY_FP: add("INFO", f"value #{i} looks like a reference/placeholder", "stays masked; confirm by reading the masked line in --preview")
        elif in_files or in_hist: add("REVIEW", f"value #{i} looks like a real credential AND is in your repo/history", "rotate it and purge it from git; it was masked in the report")
        else: add("REVIEW", f"value #{i} looks like a real credential (only in local logs)", "rotate if it is live; it was masked in the report")

    # 3. stale-check evidence (observed vs possible)
    states = Counter(st for _c, st in w.check_states(sessions))
    add("INFO", "file-change evidence in logs", f"Edit/Write tool uses={tool_edit}, shell commands that may modify files={shell_mod}")
    add("INFO", "check states", ", ".join(f"{k}={states[k]}" for k in ("superseded", "edited", "possible", "current")))
    if sum(states.values()) and not (tool_edit or shell_mod): add("REVIEW", "no file-change evidence found", "staleness cannot be assessed; edits may use unrecognised tool names")

    # 4. report separation audit
    if not doc: add("FAIL", "report generation", f"exit {rc}")
    else:
        heads = [re.sub(r"^\d+", "", re.sub(r"<[^>]+>", "", h)) for h in re.findall(r"<h2[^>]*>(.*?)</h2>", doc)]
        add("PASS" if heads == HEADINGS else "FAIL", "section order", " > ".join(heads))
        need = ["does not mean the work was completed", "were not re-run", "Git is the evidence" if g[0] else "No commits found"]
        miss = [n for n in need if n not in doc]
        add("PASS" if not miss else "FAIL", "disclaimers present for requests / git / checks", f"missing {len(miss)}")
        add("PASS" if ">passed<" not in doc else "FAIL", "no check labelled 'passed'")
        nreq = len(re.findall(r"<div class=req>", doc)); card = int(re.search(r"<b>(\d+)</b>work requests", doc).group(1))
        add("PASS" if nreq == card == sum(len(s["prompts"]) for s in sessions) else "FAIL", "request list = request card = kept requests", f"{nreq}/{card}")
    verdict = "FAIL" if flags["FAIL"] else "NEEDS REVIEW" if flags["REVIEW"] else "PASS"
    L.append(f"OVERALL: {verdict}")
    txt = "\n".join(["WorkReceipt final review (content-free)"] + L); print(txt)
    if a.summary_out:
        open(a.summary_out, "w").write(txt + "\n")
    return {"PASS": 0, "NEEDS REVIEW": 3, "FAIL": 1}[verdict]


if __name__ == "__main__":
    sys.exit(main())
