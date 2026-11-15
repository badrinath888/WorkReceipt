"""End-to-end UI test on SYNTHETIC data. Needs playwright + Chrome; skipped otherwise.
A stub of window.pywebview.api stands in for the macOS webview bridge (the real WKWebView is NOT exercised here)."""
import os, shutil, subprocess, sys, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
CHROME = next((c for c in ("/usr/bin/google-chrome", "/usr/bin/chromium") if os.path.exists(c)), None)
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipUnless(sync_playwright and CHROME, "playwright/Chrome not available")
class E2E(unittest.TestCase):
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
        pg = self.page(); pg.add_init_script("window.pywebview={api:{pick_folder:async()=>%r,reveal:async()=>true,open_report:async()=>true}}" % extra)
        pg.goto(self.url + "#projects"); pg.wait_for_selector("#addproj")
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
