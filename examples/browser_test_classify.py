"""Browser test: automated privacy analysis + complete review workflow + export (HTML and PDF). SYNTHETIC data only."""
import glob, os, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from playwright.sync_api import sync_playwright
from test_phase1 import WS
from test_classify import BRIDGE, REAL_U
cmd = BRIDGE.replace("EOF\npytest -q", f"    assert login(password={REAL_U})[0]\nEOF\npytest -q")
ws = WS(name="handoff"); ws.log(ws.bash("c1", cmd, result="ok", err=False))
out = os.path.join(ws.root, "out")
env = dict(os.environ, WORKRECEIPT_CLAUDE_DIR=ws.claude, WORKRECEIPT_HOME=os.path.join(ws.root, "home"))
port = 8792
srv = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workreceipt_app.py"), "--no-open", "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
R = []
def ok(n, c, x=""): R.append(bool(c)); print(("PASS " if c else "FAIL ") + n + (" " + str(x) if x and not c else ""))
try:
    for _ in range(50):
        try: urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state"); break
        except Exception: time.sleep(.2)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), args=["--no-sandbox"])
        for tag, w, h in (("desktop", 1459, 900), ("mobile", 390, 844)):
            pg = b.new_page(viewport={"width": w, "height": h}); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"http://127.0.0.1:{port}/"); pg.wait_for_timeout(700)
            pg.fill("#repo", ws.repo); pg.click("#usepath"); pg.click("button[data-range='all']"); pg.click("#load"); pg.wait_for_selector("#projects .callout.ok")
            pg.evaluate("document.querySelector('#privacy').scrollIntoView()"); pg.wait_for_timeout(600)
            row = pg.locator("#privacy button.gh", has_text="secret assignment")
            ok(f"{tag}: group shows 0/1 actionable, 4 cleared", "0/1 reviewed" in row.inner_text() and "4 cleared" in row.inner_text(), row.inner_text())
            ok(f"{tag}: nav badge counts only actionable (1)", pg.locator(".tab .dot").first.inner_text() == "1")
            row.click(); pg.wait_for_timeout(250)
            ok(f"{tag}: one actionable panel, labelled as likely real", pg.locator("#privacy .det:visible").count() == 1 and "Looks like a real secret" in pg.inner_text("#privacy .det"))
            ok(f"{tag}: evidence listed, no certainty claimed", "confidence: likely" in pg.inner_text("#privacy .det") and "random-looking" in pg.inner_text("#privacy .det"))
            ok(f"{tag}: cleared findings hidden by default, count disclosed", "4 high-severity detection(s) were proven harmless" in pg.inner_text("#privacy"))
            pg.click("#togglecleared"); pg.wait_for_timeout(250)
            ok(f"{tag}: toggle reveals 4 cleared panels with explanations", pg.locator("#privacy .det.cleared:visible").count() == 4 and "Code fragment" in pg.inner_text("#privacy"))
            pg.locator("#privacy .det.cleared [data-reveal]").first.click(); pg.wait_for_selector("#rv")
            ok(f"{tag}: cleared detection can still be revealed (exact span)", pg.inner_text("#rv").endswith(")[0]") or pg.inner_text("#rv").endswith(")[1]"), pg.inner_text("#rv"))
            pg.click("#dlgroot [data-close]")
            pg.click("#togglecleared"); pg.wait_for_timeout(200)
            ok(f"{tag}: can hide cleared again", pg.locator("#privacy .det.cleared:visible").count() == 0)
            n0 = len(glob.glob(out + "/*")); pg.evaluate("scrollTo(0,0)"); pg.click("#export"); pg.wait_for_timeout(1000)
            ok(f"{tag}: export blocked while the genuine secret is unresolved", len(glob.glob(out + "/*")) == n0 and pg.evaluate("document.querySelector('.tab[aria-current]')?.dataset.go") == "privacy")
            pg.locator("#privacy [data-review]").first.click(); pg.check("input[name=disp][value=credential]"); pg.check("#ack"); pg.click("#confirmrev"); pg.wait_for_timeout(250)
            ok(f"{tag}: review recorded, badge cleared", pg.locator(".tab .dot").count() == 0 and "1/1 reviewed" in row.inner_text())
            if tag == "desktop":
                pg.click("#export"); pg.wait_for_selector("text=Exported.", timeout=60000)
                htmls, pdfs = glob.glob(out + "/*.html"), glob.glob(out + "/*.pdf")
                ok("desktop: HTML and PDF written", len(htmls) == 1 and len(pdfs) == 1, (htmls, pdfs))
                html = open(htmls[0]).read()
                ok("desktop: HTML has no secret, no fragment, no raw credential", not any(s in html for s in (REAL_U, "tok)[0]", "pw)[0]", "secret_key)[1]")))
                txt = subprocess.run(["pdftotext", pdfs[0], "-"], capture_output=True, text=True).stdout if subprocess.run(["which", "pdftotext"], capture_output=True).returncode == 0 else open(pdfs[0], "rb").read().decode("latin-1")
                ok("desktop: PDF has no raw credential", REAL_U not in txt and "tok)[0]" not in txt)
            ok(f"{tag}: no horizontal overflow, no page errors, storage empty", pg.evaluate("document.documentElement.scrollWidth<=innerWidth+1") and not errs and pg.evaluate("[localStorage.length,sessionStorage.length]") == [0, 0], errs)
            pg.close()
        b.close()
finally:
    srv.terminate(); ws.done()
print(sum(R), "/", len(R)); sys.exit(0 if all(R) else 1)
