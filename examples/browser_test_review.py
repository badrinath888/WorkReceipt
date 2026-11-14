"""Browser regression test: clicking a grouped high-severity finding must open its individual detections (desktop + mobile).
SYNTHETIC data only. Needs: playwright + Chrome (CHROME env var overrides the path)."""
import os, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from playwright.sync_api import sync_playwright
from test_phase1 import WS
V = ["dummyvalue-one-111", "dummyvalue-two-222", "changeme-three", "zzzz-test-4444"]
cmd = f"cat > test_bridge.py <<'EOF'\nPASSWORD = \"{V[0]}\"\napi_key='{V[1]}'\nclient_secret: {V[2]}\nTOKEN={V[3]}\nEOF\npytest -q"
ws = WS(name="handoff"); ws.log(ws.bash("c1", cmd, result="ok", err=False))
env = dict(os.environ, WORKRECEIPT_CLAUDE_DIR=ws.claude, WORKRECEIPT_HOME=os.path.join(ws.root, "home"))
port = 8791
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
            pg.evaluate("document.querySelector('#privacy').scrollIntoView()"); pg.wait_for_timeout(700)
            row = pg.locator("#privacy button.gh", has_text="secret assignment")
            ok(f"{tag}: grouped row is a button with count and 0/4", row.count() == 1 and "×4" in row.inner_text() and "0/4" in row.inner_text(), row.inner_text() if row.count() else "")
            ok(f"{tag}: collapsed, aria-expanded=false, no detections visible", row.get_attribute("aria-expanded") == "false" and pg.locator("#privacy .det:visible").count() == 0)
            ok(f"{tag}: visible expand affordance", pg.locator("#privacy .gh .chev:visible").count() >= 1 and "Show 4 detections" in row.inner_text())
            row.focus(); pg.keyboard.press("Enter"); pg.wait_for_timeout(250)           # keyboard works too
            ok(f"{tag}: Enter expands (aria-expanded=true)", row.get_attribute("aria-expanded") == "true")
            row.click(); pg.wait_for_timeout(200); ok(f"{tag}: click collapses", row.get_attribute("aria-expanded") == "false" and pg.locator("#privacy .det:visible").count() == 0)
            row.click(); pg.wait_for_timeout(250)                                         # a real mouse click on the row
            dets = pg.locator("#privacy .det:visible")
            ok(f"{tag}: click opens exactly four visible detection panels", dets.count() == 4, dets.count())
            ok(f"{tag}: each panel has location, redacted context, Reveal and Review", all(dets.nth(i).locator(".mark, mark").count() >= 1 and dets.nth(i).locator("[data-reveal]").count() == 1 and dets.nth(i).locator("[data-review]").count() == 1 and "line" in dets.nth(i).inner_text() for i in range(4)))
            ok(f"{tag}: nothing sensitive in the page yet", not any(v in pg.content() for v in V))
            pg.click("#privacy .card.sec h3"); pg.wait_for_timeout(200)                   # clicking elsewhere must not collapse/re-render
            ok(f"{tag}: clicking blank space keeps it open", pg.locator("#privacy .det:visible").count() == 4)
            ok(f"{tag}: no horizontal overflow", pg.evaluate("document.documentElement.scrollWidth<=innerWidth+1"))
            dets.nth(1).locator("[data-reveal]").click(); pg.wait_for_selector("#rv")
            ok(f"{tag}: reveal shows only the chosen value", V[1] in pg.inner_text("#rv") and not any(v in pg.content() for v in (V[0], V[2], V[3])))
            pg.click("#dlgroot [data-close]"); pg.wait_for_timeout(150)
            ok(f"{tag}: hidden again, storage empty", not any(v in pg.content() for v in V) and pg.evaluate("[localStorage.length,sessionStorage.length]") == [0, 0])
            dets.nth(0).locator("[data-review]").click(); pg.wait_for_selector("#confirmrev")
            ok(f"{tag}: review dialog needs choice + acknowledgement", pg.locator("#confirmrev").is_disabled())
            pg.check("input[name=disp][value=not_credential]"); ok(f"{tag}: still disabled without acknowledgement", pg.locator("#confirmrev").is_disabled())
            pg.check("#ack"); pg.click("#confirmrev"); pg.wait_for_timeout(250)
            ok(f"{tag}: progress 1/4 and still expanded", "1/4" in row.inner_text() and pg.locator("#privacy .det:visible").count() == 4)
            pg.click("#export"); pg.wait_for_timeout(900)
            ok(f"{tag}: export still blocked with 3 pending", pg.locator("#studio .callout").count() >= 0 and not os.path.isdir(os.path.expanduser("~/__none__")) and "Exported." not in pg.inner_text("#studio"))
            ok(f"{tag}: no page errors", not errs, errs)
            pg.screenshot(path=f"/tmp/review-{tag}.png"); pg.close()
        b.close()
finally:
    srv.terminate(); ws.done()
print(sum(R), "/", len(R)); sys.exit(0 if all(R) else 1)
