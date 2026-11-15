#!/usr/bin/env python3
"""Creates a SYNTHETIC workspace (repos + Claude Code-style logs) for trying the app without real data.
Usage: python3 examples/make_demo_workspace.py /tmp/wr-demo   then   WORKRECEIPT_CLAUDE_DIR=/tmp/wr-demo/claude python3 workreceipt_app.py"""
import json, os, subprocess, sys, time
from datetime import datetime, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import workreceipt as w

root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "/tmp/wr-demo")
os.makedirs(root, exist_ok=True)
now = datetime.now()
env = dict(os.environ, GIT_AUTHOR_NAME="Demo Dev", GIT_AUTHOR_EMAIL="dev@example.com", GIT_COMMITTER_NAME="Demo Dev", GIT_COMMITTER_EMAIL="dev@example.com")

def mk(name, commits, prompts, fake_secret=False):
    repo = os.path.join(root, name); os.makedirs(repo, exist_ok=True)
    def git(*a, date=None):
        e = dict(env); e.update({"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {})
        subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=e)
    git("init", "-q")
    for i, (path, msg, ago) in enumerate(commits):
        os.makedirs(os.path.dirname(os.path.join(repo, path)) or repo, exist_ok=True)
        open(os.path.join(repo, path), "w").write("\n".join(f"line {n}" for n in range(8 + i * 9)) + "\n")
        git("add", "."); git("commit", "-qm", msg, date=(now - timedelta(days=ago)).strftime("%Y-%m-%dT15:00:00"))
    d = os.path.join(root, "claude", "projects", w.encode_project_dir(repo)); os.makedirs(d, exist_ok=True)
    L = []
    def ev(t, c, ts, **k): L.append(json.dumps({"type": t, "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "cwd": repo, "message": {"role": t, "content": c}, **k}))
    for j, (ago, text, edit, cmd, ok) in enumerate(prompts):
        ts = now - timedelta(days=ago)
        ev("user", text, ts, uuid=f"{name}-u{j}")
        if edit: ev("assistant", [{"type": "tool_use", "id": f"e{j}", "name": "Edit", "input": {"file_path": os.path.join(repo, edit)}}], ts + timedelta(minutes=10))
        if cmd:
            ev("assistant", [{"type": "tool_use", "id": f"c{j}", "name": "Bash", "input": {"command": cmd}}], ts + timedelta(minutes=20))
            ev("user", [{"type": "tool_result", "tool_use_id": f"c{j}", "content": "ok" if ok else "1 failed\nExit code 1", "is_error": not ok}], ts + timedelta(minutes=21))
    p = os.path.join(d, f"{name}.jsonl"); open(p, "w").write("\n".join(L) + "\n")
    for k in range(len(prompts)):                      # several session files with different modified weeks
        q = os.path.join(d, f"{name}-s{k}.jsonl"); open(q, "w").write(L[k] + "\n" if k < len(L) else "")
        t = time.time() - prompts[k][0] * 86400; os.utime(q, (t, t))
    os.utime(p, (time.time() - prompts[0][0] * 86400,) * 2)

mk("acme-storefront", [("src/pricing.py", "Add pricing page with three plans", 20), ("src/checkout.py", "Fix checkout total rounding", 13),
                       ("tests/test_checkout.py", "Add checkout regression tests", 13), ("src/export.py", "Add CSV export for orders", 6), ("docs/README.md", "Document export endpoint", 3)],
   [(21, "Add a pricing page with three plans (Basic, Team, Enterprise)", "src/pricing.py", "python3 -m pytest -q", True),
    (14, "Checkout totals are off by a cent for some carts. Fix and add regression tests. Contact: jane@example.com", "src/checkout.py", "python3 -m pytest -q", False),
    (13, "Re-run and fix the failing checkout test", "src/checkout.py", "python3 -m pytest -q", True),
    (7, "Add CSV export for orders on the admin page. Use AWS key AKIAQWERTYUIOPASDFGH for the S3 upload (synthetic example key)", "src/export.py", "npm run lint", True),
    (4, "Write docs for the export endpoint", "docs/README.md", None, True),
    (1, "Tidy the admin table spacing", None, None, True)], True)
mk("northwind-api", [("api/routes.py", "Add /health endpoint", 9), ("api/auth.py", "Harden token validation", 5)],
   [(10, "Add a health endpoint for the load balancer", "api/routes.py", "python3 -m pytest -q", True),
    (6, "Harden token validation and add tests", "api/auth.py", "python3 -m pytest -q", True)])
print("demo workspace:", root, "\nclaude dir:", os.path.join(root, "claude"))
