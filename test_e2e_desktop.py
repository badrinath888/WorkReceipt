"""End-to-end UI test on SYNTHETIC data. Needs playwright + Chrome; skipped otherwise.
A FakeNative host on workreceipt_app.NATIVE stands in for the macOS window (the real WKWebView/Cocoa dialogs are NOT exercised here)."""
import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
CHROME = next((c for c in ("/usr/bin/google-chrome", "/usr/bin/chromium") if os.path.exists(c)), None)
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipUnless(sync_playwright and CHROME, "playwright/Chrome not available")
class FakeNative:
    """Same interface as desktop.main.Native. Behaviour is scripted per test; every call is recorded."""
    def __init__(self, ready=True, picks=(), pick_error=None, res=None):
        self.ready, self.picks, self.pick_error, self.res, self.calls = ready, list(picks), pick_error, res, []
    def status(self):
        return {"available": self.ready, "window": True, "shown": self.ready, "pywebview": "fake", "platform": "test"}
    def pick_folder(self, start=None):
        self.calls.append(("pick", start))
        if self.pick_error: return {"ok": False, "error": self.pick_error}
        p = self.picks.pop(0) if self.picks else None
        return {"ok": True, "path": p, "cancelled": p is None}
    def open(self, name, kind="html"):
        self.calls.append(("open", name, kind)); return self.res or {"ok": True}
    def reveal(self, name, kind="html"):
        self.calls.append(("reveal", name, kind)); return self.res or {"ok": True}


class E2E(unittest.TestCase):
    def native(self, **kw):
        import workreceipt_app as app
        app.NATIVE = FakeNative(**kw); self.addCleanup(setattr, app, "NATIVE", None); return app.NATIVE

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        os.environ["WORKRECEIPT_HOME"] = os.path.join(cls.root, "home")
        os.environ["WORKRECEIPT_CLAUDE_DIR"] = os.path.join(cls.root, "emptyclaude")   # no real logs are ever read
        import app_core as core, workreceipt_app as app
        cls.core = core
        core.save_settings({"out_dir": os.path.join(cls.root, "out")})
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/"
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close(); cls.pw.stop(); cls.srv.shutdown(); cls.srv.server_close()
        shutil.rmtree(cls.root, ignore_errors=True)

    def page(self, w=1180, h=760):
        pg = self.br.new_page(viewport={"width": w, "height": h})
        self.errs = []
        pg.on("pageerror", lambda e: self.errs.append(str(e)))
        pg.on("console", lambda m: self.errs.append(m.text) if m.type == "error" else None)
        return pg

    def test_1_onboarding_demo_and_screens(self):
        pg = self.page(); pg.goto(self.url)
        pg.wait_for_selector(".ob")                                     # first run
        self.assertIn("Welcome", pg.inner_text(".ob"))
        pg.click("#obnext"); self.assertIn("Private by design", pg.inner_text(".ob"))
        pg.click("#obback"); pg.click("#obnext"); pg.click("#obnext")
        pg.click("#obpick")                                              # no native bridge in a plain browser: honest message, no crash
        self.assertIn("desktop app", pg.inner_text(".ob"))
        pg.click("#obdemo"); pg.wait_for_selector("#screen .ph h2:has-text('Projects')", timeout=60000)
        self.assertEqual(pg.locator(".ob").count(), 0)
        self.assertTrue(self.core.load_settings()["onboarded"])
        self.assertIn("acme-storefront", pg.inner_text("#screen"))
        for k, h in [("overview", "Overview"), ("projects", "Projects"), ("studio", "Report Studio"), ("privacy", "Privacy Center"), ("reports", "Reports"), ("settings", "Settings")]:
            pg.click(f".tab[data-go={k}]")
            self.assertIn(h, pg.inner_text("#screen .ph h2"))
            self.assertEqual(pg.get_attribute(f".tab[data-go={k}]", "aria-current"), "page")
        self.assertEqual(self.errs, [])
        pg.close()

    def test_2_workflow_state_survives_navigation_and_export_gate(self):
        self.core.enable_demo()
        self.core.save_settings({"onboarded": True})
        pg = self.page(); pg.goto(self.url + "#projects"); pg.wait_for_selector("tr[data-pick]")
        pg.click("tr[data-pick]:has-text('acme-storefront')"); pg.click("#load")
        pg.wait_for_selector(".callout.ok:has-text('Loaded')", timeout=60000)
        pg.click(".tab[data-go=studio]"); pg.wait_for_selector("[data-req]")
        el = pg.locator("[data-req]").first; el.click(); el.press("Control+A"); el.type("Edited by user")
        pg.click(".tab[data-go=overview]"); pg.click(".tab[data-go=reports]"); pg.click(".tab[data-go=studio]")
        self.assertEqual(pg.locator("[data-req]").first.inner_text(), "Edited by user")        # edits survive navigation
        pg.click("#preview"); pg.wait_for_selector("iframe.frame")
        self.assertNotIn("AKIAQWERTYUIOPASDFGH", pg.content())
        pg.click("#export"); pg.wait_for_selector("#toast.on, .callout:has-text('not reviewed')")  # blocked until reviewed
        self.assertFalse(os.path.isdir(os.path.join(self.root, "out")) and os.listdir(os.path.join(self.root, "out")))
        pg.click(".tab[data-go=privacy]"); pg.wait_for_selector(".gh[data-toggle]")
        for _ in range(10):
            b = pg.locator("[data-toggle]").first
            if b.get_attribute("aria-expanded") != "true": b.click()
            r = pg.locator("[data-review]:not(:has-text('Change'))")
            if r.count() == 0: break
            r.first.click(); pg.check("input[value=unsure]"); pg.check("#ack"); pg.click("#confirmrev")
        pg.click(".tab[data-go=studio]"); pg.click("#export"); pg.wait_for_selector(".callout.ok:has-text('Exported')", timeout=60000)
        files = os.listdir(os.path.join(self.root, "out"))
        html = open(os.path.join(self.root, "out", next(f for f in files if f.endswith(".html")))).read()
        self.assertIn("Edited by user", html); self.assertNotIn("AKIA", html)
        pg.click(".tab[data-go=reports]"); self.assertIn("acme-storefront", pg.inner_text("#screen"))
        pg.fill("#rq", "nomatch"); self.assertIn("No reports match", pg.inner_text("#screen")); pg.fill("#rq", "acme")
        pg.click("[data-delrep]"); pg.click("#confirmdel"); pg.wait_for_selector(".empty:has-text('No reports yet')")
        self.assertFalse([f for f in os.listdir(os.path.join(self.root, "out")) if f.endswith(".html")])
        self.assertEqual(self.errs, [])
        pg.close()

    def test_3_native_bridge_stub_remove_project_dark_resize(self):
        extra = os.path.join(self.root, "extra-proj"); os.makedirs(extra)
        self.core.save_settings({"onboarded": True})
        self.native(picks=[extra]); pg = self.page()
        pg.goto(self.url + "?shell=desktop#projects"); pg.wait_for_selector("#addproj:not([disabled])")
        pg.click("#addproj"); pg.wait_for_selector("tr[data-pick]:has-text('extra-proj')")
        self.assertIn("not a Git repository", pg.inner_text("#screen"))
        pg.click("[data-rmproj='%s']" % extra); pg.click("#confirmdel"); pg.wait_for_selector("tr:has-text('extra-proj')", state="detached")
        self.assertTrue(os.path.isdir(extra))                                  # source folder untouched
        gone = os.path.join(self.root, "gone"); os.makedirs(gone); self.core.add_project(gone); shutil.rmtree(gone)
        pg.click("#refresh"); pg.wait_for_selector(".badge:has-text('folder missing')")   # moved/deleted project: no crash
        pg.click(".tab[data-go=settings]"); pg.click("button[data-theme=dark]")
        self.assertEqual(pg.evaluate("document.documentElement.dataset.theme"), "dark")
        pg.set_viewport_size({"width": 700, "height": 600}); pg.click(".tab[data-go=overview]")
        self.assertFalse(pg.evaluate("document.documentElement.scrollWidth > innerWidth"))
        pg.keyboard.press("Tab"); self.assertTrue(pg.evaluate("document.activeElement !== document.body"))   # keyboard reachable
        self.assertEqual(self.errs, [])
        pg.close()

    # ---- native folder picker bridge (pywebview stub; the real WKWebView is NOT exercised here) ----
    def desk(self, timeout=15000):
        # The suite pins the Claude folder with an env var so real logs are never read; that override would mask what the
        # Settings page saves. Pin it in settings.json instead (an empty temp dir) and drop the env override for this test.
        pin = os.environ.get("WORKRECEIPT_CLAUDE_DIR")
        if pin:
            self.core.save_settings({"claude_dir": pin}); os.environ.pop("WORKRECEIPT_CLAUDE_DIR")
            self.addCleanup(os.environ.__setitem__, "WORKRECEIPT_CLAUDE_DIR", pin)
        self.core.save_settings({"onboarded": True})
        pg = self.page(); pg.add_init_script(f"window.WR_BRIDGE_TIMEOUT_MS={timeout};")
        pg.goto(self.url + "?shell=desktop#settings"); pg.wait_for_selector("[data-choose=s_claude]")
        return pg

    def saved(self):
        with open(os.path.join(self.core._home(), "settings.json")) as f:
            return json.load(f)

    def test_6_picker_waits_for_host_then_populates_and_persists(self):
        d1, d2 = os.path.join(self.root, "claude-picked"), os.path.join(self.root, "reports-picked"); os.makedirs(d1); os.makedirs(d2)
        n = self.native(ready=False, picks=[d1, d2]); pg = self.desk()
        self.assertTrue(pg.is_disabled("[data-choose=s_claude]")); self.assertTrue(pg.is_disabled("[data-choose=s_out]"))   # not usable before the host is ready
        n.ready = True
        pg.wait_for_selector("[data-choose=s_claude]:not([disabled])")
        pg.click("[data-choose=s_claude]"); pg.wait_for_function("p=>document.querySelector('#s_claude').value===p", arg=d1)
        pg.click("[data-choose=s_out]"); pg.wait_for_function("p=>document.querySelector('#s_out').value===p", arg=d2)
        self.assertEqual((self.saved()["claude_dir"], self.saved()["out_dir"]), (d1, d2))       # persisted, in the right fields
        pg.reload(); pg.wait_for_selector("#s_claude"); self.assertEqual(pg.input_value("#s_claude"), d1)
        self.assertEqual(self.errs, []); pg.close()

    def test_7_cancel_changes_nothing_and_failure_shows_error(self):
        self.native(); pg = self.desk()
        pg.wait_for_selector("[data-choose=s_claude]:not([disabled])")
        old = pg.input_value("#s_claude"); pg.click("[data-choose=s_claude]"); pg.wait_for_timeout(300)
        self.assertEqual(pg.input_value("#s_claude"), old); self.assertNotIn("could not be opened", pg.inner_text("#toast"))
        pg.close()
        self.native(pick_error="The folder dialog could not be opened (RuntimeError)."); pg = self.desk()
        pg.wait_for_selector("[data-choose=s_claude]:not([disabled])")
        pg.click("[data-choose=s_claude]"); pg.wait_for_selector("#toast.on:has-text('could not be opened')")
        self.assertEqual(pg.input_value("#s_claude"), old); pg.close()

    def test_8_host_never_ready_is_a_clear_error_with_diagnostics(self):
        self.native(ready=False); pg = self.desk(timeout=1200)
        pg.wait_for_selector(".callout.err:has-text('Native folder dialog unavailable')", timeout=5000)
        self.assertTrue(pg.is_disabled("[data-choose=s_claude]")); self.assertIn("not available", pg.get_attribute("[data-choose=s_claude]", "title"))
        self.assertIn("not responding", pg.inner_text("#diag"))
        pg.fill("#s_claude", self.root); pg.click("#savesettings"); pg.wait_for_selector("#toast.on:has-text('Settings saved')")   # typing a path still works
        self.assertEqual(self.saved()["claude_dir"], self.root)
        import workreceipt_app as app; app.NATIVE.ready = True                       # recovers via "Check again"
        pg.click("#diagretry"); pg.wait_for_selector("[data-choose=s_claude]:not([disabled])"); self.assertIn("ready", pg.inner_text("#diag")); pg.close()

    def test_9_add_project_uses_native_picker_and_waits_for_host(self):
        extra = os.path.join(self.root, "picked-proj"); os.makedirs(extra)
        self.core.save_settings({"onboarded": True})
        n = self.native(ready=False, picks=[extra]); pg = self.page()
        pg.goto(self.url + "?shell=desktop#projects"); pg.wait_for_selector("#addproj")
        self.assertTrue(pg.is_disabled("#addproj"))
        n.ready = True; pg.wait_for_selector("#addproj:not([disabled])")
        pg.click("#addproj"); pg.wait_for_selector("tr[data-pick]:has-text('picked-proj')"); self.assertEqual(self.errs, []); pg.close()

    # ---- macOS validation fixes: real clicks, no forced UI state ----
    def load_demo(self, pg, q=""):
        self.core.enable_demo(); self.core.save_settings({"onboarded": True})
        pg.goto(self.url + q + "#projects"); pg.wait_for_selector("tr[data-pick]")
        pg.click("tr[data-pick]:has-text('acme-storefront')"); pg.click("#load"); pg.wait_for_selector(".callout.ok:has-text('Loaded')", timeout=60000)

    def review_all(self, pg):
        pg.click(".tab[data-go=privacy]"); pg.wait_for_selector(".gh[data-toggle]")
        for _ in range(10):
            b = pg.locator("[data-toggle]").first
            if b.get_attribute("aria-expanded") != "true": b.click()
            r = pg.locator("[data-review]:not(:has-text('Change'))")
            if r.count() == 0: break
            r.first.click(); pg.click(".ropt:has-text('Unsure')"); pg.click(".ack .ropt"); pg.click("#confirmrev")

    def test_a_review_dialog_ux(self):
        pg = self.page(); self.load_demo(pg); pg.click(".tab[data-go=privacy]"); pg.wait_for_selector(".gh[data-toggle]")
        pg.locator("[data-toggle]").first.click(); pg.click("[data-review]")
        self.assertEqual(pg.locator(".rgroup input[type=radio]").count(), 3)                  # three classifications, own group
        self.assertEqual(pg.locator(".rgroup input[type=checkbox]").count(), 0)               # acknowledgement is NOT in the radio group
        self.assertIn("Required acknowledgement", pg.inner_text(".ack")); self.assertIn("not", pg.inner_text(".ack"))
        self.assertTrue(pg.is_disabled("#confirmrev")); self.assertIn("Select a classification and tick the acknowledgement", pg.inner_text("#rvhint"))
        pg.click(".ropt:has-text('Real credential')")                                           # classification only -> still disabled, hint says what is missing
        self.assertTrue(pg.is_disabled("#confirmrev")); self.assertIn("Tick the required acknowledgement", pg.inner_text("#rvhint"))
        pg.click(".ack .ropt"); self.assertFalse(pg.is_disabled("#confirmrev")); self.assertTrue(pg.is_hidden("#rvhint"))
        pg.click(".ack .ropt"); self.assertTrue(pg.is_disabled("#confirmrev"))                  # un-ticking disables again
        self.assertIn("cancel", pg.get_attribute("[data-close]", "class"))
        pg.click("[data-close]"); self.assertEqual(pg.locator(".dlgbox").count(), 0)             # cancel records nothing
        self.assertTrue(pg.locator("[data-review]:not(:has-text('Change'))").count() >= 1)
        pg.click("[data-review]")                                                               # keyboard: focus stays on the radio when arrows change the choice
        pg.focus(".rgroup input[type=radio]"); pg.keyboard.press("ArrowDown")
        self.assertEqual(pg.evaluate("document.activeElement.name"), "disp"); self.assertTrue(pg.evaluate("document.querySelector('.rgroup input:checked')!==null"))
        pg.keyboard.press("Tab"); self.assertEqual(pg.evaluate("document.activeElement.id"), "ack")
        pg.keyboard.press("Space"); self.assertFalse(pg.is_disabled("#confirmrev"))
        self.assertNotEqual(pg.evaluate("getComputedStyle(document.activeElement.closest('.ropt')).outlineStyle"), "none")      # visible focus ring
        pg.keyboard.press("Escape"); self.assertEqual(pg.locator(".dlgbox").count(), 0); self.assertEqual(self.errs, []); pg.close()

    def test_b_open_and_reveal_send_names_only_and_show_errors(self):
        n = self.native(); pg = self.page(); self.load_demo(pg, "?shell=desktop"); self.review_all(pg)
        pg.click(".tab[data-go=studio]"); pg.click("#export"); pg.wait_for_selector(".callout.ok:has-text('Exported')", timeout=60000)
        pg.click(".callout.ok [data-open]"); pg.click(".callout.ok [data-showfile]")
        calls = n.calls; self.assertEqual([c[0] for c in calls], ["open", "reveal"])
        for c in calls: self.assertTrue(c[1].endswith(".html") and "/" not in c[1] and "\\" not in c[1], c); self.assertEqual(c[2], "html")
        n.res = {"ok": False, "error": "That report file no longer exists. It may have been moved or deleted"}   # simulate backend refusal
        pg.click(".callout.ok [data-open]"); pg.wait_for_selector("#toast.on:has-text('no longer exists')")
        pg.click(".tab[data-go=reports]"); pg.click("[data-open]"); pg.click("[data-showfile]"); self.assertEqual(len(n.calls), 5)
        self.assertEqual(self.errs, []); pg.close()

    def test_c_theme_icon_pills_overview_refresh_preview_settings(self):
        pg = self.page(); self.load_demo(pg)
        self.assertEqual(pg.inner_text("#theme").strip(), ""); self.assertEqual(pg.locator("#theme svg").count(), 1)       # icon, no "Theme" text
        before = pg.get_attribute("#theme", "aria-label"); pg.click("#theme")
        self.assertNotEqual(pg.get_attribute("#theme", "aria-label"), before); self.assertIn("Switch to", pg.get_attribute("#theme", "title"))
        pg.click("#theme")
        pg.click(".tab[data-go=projects]")                                                      # date pills: hover + active state
        self.assertEqual(pg.get_attribute("[data-range=all]", "aria-pressed"), "true")
        bg = pg.evaluate("getComputedStyle(document.querySelector('[data-range=\"7\"]')).backgroundColor"); pg.hover("[data-range='7']"); pg.wait_for_timeout(400)
        self.assertNotEqual(pg.evaluate("getComputedStyle(document.querySelector('[data-range=\"7\"]')).backgroundColor"), bg)
        pg.click("[data-range='7']"); self.assertEqual(pg.get_attribute("[data-range='7']", "aria-pressed"), "true"); self.assertEqual(pg.get_attribute("[data-range=all]", "aria-pressed"), "false")
        pg.click("[data-range=all]")
        pg.click(".tab[data-go=overview]")                                                      # overview refresh picks up changes made outside the page
        n = int(pg.inner_text(".stat .v").strip()); extra = os.path.join(self.root, "refresh-me"); os.makedirs(extra); self.core.add_project(extra)
        pg.click("#refresh"); pg.wait_for_function("n=>parseInt(document.querySelector('.stat .v').textContent)===n+1", arg=n)
        pg.click(".tab[data-go=studio]"); pg.click("#preview"); pg.wait_for_selector("iframe.frame")      # preview opens at the top after scrolling away
        pg.mouse.move(600, 400); pg.mouse.wheel(0, 3000); pg.wait_for_timeout(300); pg.mouse.wheel(0, -4000); pg.wait_for_timeout(300)
        pg.click("#preview"); pg.wait_for_timeout(500)
        top = pg.evaluate("document.querySelector('.frame').closest('.card').getBoundingClientRect().top")
        self.assertTrue(0 <= top < 260, top); self.assertEqual(pg.evaluate("document.querySelector('.frame').contentWindow.scrollY"), 0)
        pg.click(".tab[data-go=settings]")                                                      # readable path fields, current data dir + version
        self.assertGreater(pg.evaluate("document.querySelector('#s_claude').getBoundingClientRect().width"), 380)
        self.assertEqual(pg.get_attribute("#s_claude", "title"), pg.input_value("#s_claude"))
        txt = pg.inner_text("#screen"); self.assertIn(self.core._home(), txt); self.assertIn(self.core.VERSION, txt); self.assertNotIn("~/.workreceipt", txt)
        self.assertEqual(self.errs, []); pg.close()

    def test_5_keyboard_shortcuts(self):
        self.core.save_settings({"onboarded": True})
        pg = self.page(); pg.goto(self.url); pg.wait_for_selector(".tab")
        for key, h in (("2", "Projects"), ("5", "Reports"), (",", "Settings"), ("1", "Overview"), ("3", "Report Studio"), ("4", "Privacy Center")):
            pg.keyboard.press("Control+" + key); self.assertIn(h, pg.inner_text("#screen .ph h2"))
        self.assertEqual(self.errs, []); pg.close()

    def test_4_missing_claude_dir_and_empty_state(self):
        pg = self.page(); pg.goto(self.url + "#reports"); pg.wait_for_selector("#screen .ph")
        self.assertIn("Reports", pg.inner_text("#screen")); pg.close()


class Backend(unittest.TestCase):
    def test_add_project_rejects_bad_paths(self):
        import app_core as core
        with self.assertRaises(core.UserError): core.add_project("relative/path")
        with self.assertRaises(core.UserError): core.add_project("/nonexistent/zzz")

    def test_delete_report_only_touches_history_files(self):
        import app_core as core
        with self.assertRaises(core.NotFound): core.delete_report("passwd")


if __name__ == "__main__":
    unittest.main()
