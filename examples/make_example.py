#!/usr/bin/env python3
"""Builds a SYNTHETIC demo project + Claude Code-style session log in a temp folder and writes examples/example_report.html.
No real data is involved. Usage: python3 examples/make_example.py"""
import json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import workreceipt as w

tmp = tempfile.mkdtemp(); repo = os.path.join(tmp, "acme-demo-site"); os.makedirs(repo)
env = dict(os.environ, GIT_AUTHOR_NAME="Demo Dev", GIT_AUTHOR_EMAIL="dev@example.com", GIT_COMMITTER_NAME="Demo Dev", GIT_COMMITTER_EMAIL="dev@example.com")
def git(*a, date=None):
    e = dict(env); e.update({"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {})
    subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=e)
git("init", "-q")
for i, (path, msg, day) in enumerate([("src/pricing.py", "Add pricing page with three plans", "03"), ("src/checkout.py", "Fix checkout total rounding", "04"),
                                      ("tests/test_checkout.py", "Add checkout regression tests", "04"), ("src/export.py", "Add CSV export for orders", "06")]):
    os.makedirs(os.path.dirname(os.path.join(repo, path)), exist_ok=True)
    open(os.path.join(repo, path), "w").write("\n".join(f"line {n}" for n in range(10 + i * 7)) + "\n")
    git("add", "."); git("commit", "-qm", msg, date=f"2026-11-{day}T15:00:00")

d = os.path.join(tmp, "claude", "projects", w.encode_project_dir(repo)); os.makedirs(d)
def ev(t, c, ts, **k): return json.dumps({"type": t, "timestamp": ts, "cwd": repo, "message": {"role": t, "content": c}, **k})
def tu(i, name, inp, ts): return ev("assistant", [{"type": "tool_use", "id": i, "name": name, "input": inp}], ts)
def tr(i, txt, ts, err=None): return ev("user", [{"type": "tool_result", "tool_use_id": i, "content": txt, **({"is_error": err} if err is not None else {})}], ts)
L = [ev("user", "Add a pricing page with three plans (Basic, Team, Enterprise)", "2026-11-03T09:00:00Z", uuid="a1"),
     tu("e1", "Edit", {"file_path": os.path.join(repo, "src/pricing.py")}, "2026-11-03T09:10:00Z"),
     tu("c1", "Bash", {"command": "python3 -m pytest -q"}, "2026-11-03T09:20:00Z"), tr("c1", "12 passed", "2026-11-03T09:20:30Z", False),
     ev("user", "Checkout totals are off by a cent for some carts. Please fix and add regression tests. Customer contact: jane@example.com", "2026-11-04T09:00:00Z", uuid="a2"),
     tu("e2", "Edit", {"file_path": os.path.join(repo, "src/checkout.py")}, "2026-11-04T09:30:00Z"),
     tu("c2", "Bash", {"command": "python3 -m pytest -q"}, "2026-11-04T09:40:00Z"), tr("c2", "1 failed, 11 passed\nExit code 1", "2026-11-04T09:40:20Z", True),
     tu("e3", "Edit", {"file_path": os.path.join(repo, "src/checkout.py")}, "2026-11-04T10:00:00Z"),
     tu("c3", "Bash", {"command": "python3 -m pytest -q"}, "2026-11-04T10:10:00Z"), tr("c3", "13 passed", "2026-11-04T10:10:20Z", False),
     ev("user", "This session is being continued from a previous conversation that ran out of context. Summary: ...", "2026-11-06T08:00:00Z", isCompactSummary=True),
     ev("user", "<task-notification><status>completed</status></task-notification>", "2026-11-06T08:05:00Z"),
     ev("user", "Add CSV export for orders on the admin page", "2026-11-06T09:00:00Z", uuid="a3"),
     json.dumps({"type": "last-prompt", "lastPrompt": "Add CSV export for orders on the admin page"}),
     tu("e4", "Edit", {"file_path": os.path.join(repo, "src/export.py")}, "2026-11-06T09:30:00Z"),
     tu("c4", "Bash", {"command": "npm run lint"}, "2026-11-06T09:50:00Z"), tr("c4", "ok", "2026-11-06T09:50:10Z", False)]
open(os.path.join(d, "demo.jsonl"), "w").write("\n".join(L) + "\n")
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "example_report.html")
sys.exit(w.main(["--repo", repo, "--claude-dir", os.path.join(tmp, "claude"), "--since", "2026-11-01", "--until", "2026-11-07",
                 "--client", "Acme Demo Co (synthetic)", "--author", "Demo Dev", "--out", out]))
