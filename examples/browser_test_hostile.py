# Browser test with hostile SYNTHETIC input (needs: pip install playwright + Chrome). Run from the repo root: python3 examples/browser_test_hostile.py
import json, os, subprocess, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import workreceipt as w
from playwright.sync_api import sync_playwright
root = tempfile.mkdtemp(); name = 'x"><img src=x onerror="window.__xss=1"><b id=pwn>'
repo = os.path.join(root, name); os.makedirs(repo)
env = dict(os.environ, GIT_AUTHOR_NAME="D", GIT_AUTHOR_EMAIL="d@e.com", GIT_COMMITTER_NAME="D", GIT_COMMITTER_EMAIL="d@e.com", WORKRECEIPT_CLAUDE_DIR=os.path.join(root, "claude"), WORKRECEIPT_HOME=os.path.join(root, "h"))
subprocess.run(["git", "-C", repo, "init", "-q"], check=True); open(os.path.join(repo, "a"), "w").write("x")
subprocess.run(["git", "-C", repo, "add", "."], check=True); subprocess.run(["git", "-C", repo, "commit", "-qm", '<img src=x onerror="window.__xss=1"> & "q"'], check=True, env=env)
d = os.path.join(root, "claude", "projects", w.encode_project_dir(repo)); os.makedirs(d)
now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
ev = lambda t, c: json.dumps({"type": "user", "timestamp": now, "cwd": repo, "message": {"role": "user", "content": c}})
open(os.path.join(d, "s.jsonl"), "w").write(ev("user", '<img src=x onerror="window.__xss=2"><script>window.__xss=3</script>') + "\n")
srv = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workreceipt_app.py"), "--no-open", "--port", "8791"], env=env, stdout=subprocess.DEVNULL); time.sleep(1.5)
ok = True
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"]); pg = b.new_page()
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e))); pg.goto("http://127.0.0.1:8791/"); pg.wait_for_timeout(700)
        pg.click("#projects tr.click"); pg.click("button[data-range='all']"); pg.click("#load"); pg.wait_for_selector("#projects .callout.ok"); pg.click("#preview"); pg.wait_for_selector(".frame"); pg.wait_for_timeout(600)
        pg.locator("#studio [data-req]").first.fill("<img src=x onerror=window.__xss=4>"); pg.click("#preview"); pg.wait_for_timeout(600)
        res = {"no script ran": pg.evaluate("window.__xss === undefined"), "no injected element": pg.evaluate("!document.getElementById('pwn') && !document.querySelector('main img')"),
               "frame has no img": all(f.evaluate("!document.querySelector('img')") for f in pg.frames[1:]), "no page errors": not errs}
        for k, v in res.items(): print(("PASS " if v else "FAIL ") + k); ok &= bool(v)
        b.close()
finally:
    srv.terminate()
sys.exit(0 if ok else 1)
