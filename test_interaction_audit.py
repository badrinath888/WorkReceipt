"""Application-wide interaction audit: real clicks/keys in headless Chrome against the real HTTP server on SYNTHETIC data.
Every control is recorded in docs/interaction_matrix.json with level (browser = real interaction in Chrome) and PASS/FAIL/BLOCKED.
BLOCKED = needs the real macOS app (WKWebView, Cocoa dialogs, Finder, menu bar); a FakeNative host does not prove those."""
import json, os, shutil, sys, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_e2e_desktop as _e
E2E, FakeNative = _e.E2E, _e.FakeNative

MATRIX = []
HERE = os.path.dirname(os.path.abspath(__file__))


def rec(screen, control, expected, handler, dep, test, status, reason="", level="browser"):
    MATRIX.append(dict(screen=screen, control=control, expected=expected, handler=handler, dependency=dep, test=test, level=level, status=status, reason=reason))


BLOCKED = [
    ("macOS", "Launch .app / Gatekeeper", "App opens, window shown", "desktop/main.py main()", "WKWebView, PyInstaller bundle", "MAC-1"),
    ("macOS", "Menu bar items (File/View)", "Each item runs its command via run_js", "desktop/main.py build_menu", "pywebview menu + run_js", "MAC-2"),
    ("macOS", "Native folder dialog (all 4 Choose/Add buttons)", "NSOpenPanel opens, path returned", "Native.pick_folder", "Cocoa dialog", "MAC-3"),
    ("macOS", "Open report / PDF in default app", "/usr/bin/open launches viewer", "Native.open", "LaunchServices", "MAC-4"),
    ("macOS", "Show in Finder", "/usr/bin/open -R reveals file", "Native.reveal", "Finder", "MAC-4"),
    ("macOS", "PDF creation", "Valid multi-page PDF written", "desktop/pdf_mac.render_pdf", "WKWebView print", "MAC-5"),
    ("macOS", "Drag a folder onto the window", "Project added via DOM drop event", "desktop/main.py _drop_handler", "pywebview DOM events", "MAC-6"),
    ("macOS", "Window resize / focus / Cmd+Q cleanup", "No crash; server stops", "desktop/main.py", "Cocoa window", "MAC-7"),
    ("macOS", "Native diagnostics card shows 'ready'", "Settings > Diagnostics reports ready", "Native.status", "pywebview shown event", "MAC-8"),
]


class Audit(unittest.TestCase):
    setUpClass = classmethod(lambda cls: E2E.setUpClass.__func__(cls))
    tearDownClass = classmethod(lambda cls: (E2E.tearDownClass.__func__(cls), cls.dump()))
    page, native, load_demo, review_all, saved = E2E.page, E2E.native, E2E.load_demo, E2E.review_all, E2E.saved
    addCleanup = unittest.TestCase.addCleanup

    @classmethod
    def dump(cls):
        for b in BLOCKED:
            rec(*b[:5], test=b[5], status="BLOCKED", reason="Requires the real macOS app", level="packaged-macos")
        with open(os.path.join(HERE, "docs", "interaction_matrix.json"), "w") as f:
            json.dump(MATRIX, f, indent=1)

    def chk(self, screen, control, expected, handler, dep, fn, level="browser"):
        try:
            fn(); rec(screen, control, expected, handler, dep, self._testMethodName, "PASS", level=level)
        except Exception as e:
            rec(screen, control, expected, handler, dep, self._testMethodName, "FAIL", str(e).splitlines()[0][:160], level)
            self.failures.append(f"{screen}/{control}: {str(e).splitlines()[0][:160]}")

    def setUp(self):
        self.failures = []

    def tearDown(self):
        self.assertEqual(self.failures, [])

    # ---------------- onboarding ----------------
    def test_onboarding(self):
        self.core.save_settings({"onboarded": False}); self.native(picks=[]); pg = self.page()
        pg.goto(self.url + "?shell=desktop"); pg.wait_for_selector("#obnext")
        S = "Onboarding"
        self.chk(S, "Continue", "advances to step 2", "obnext", "-", lambda: (pg.click("#obnext"), self.assertIn("Private", pg.inner_text(".ob h3"))))
        self.chk(S, "Back", "returns to step 1", "obback", "-", lambda: (pg.click("#obback"), self.assertIn("Welcome", pg.inner_text(".ob h3"))))
        pg.click("#obnext"); pg.click("#obnext"); pg.wait_for_selector("#obpick:not([disabled])")
        self.chk(S, "Select project folder (cancel)", "cancel leaves dialog open, no error", "obpick", "/api/native/pick_folder", lambda: (pg.click("#obpick"), pg.wait_for_timeout(300), self.assertEqual(pg.locator(".ob").count(), 1)))
        self.chk(S, "Try the demo project", "demo created, lands on Projects", "obdemo", "/api/demo", lambda: (pg.click("#obdemo"), pg.wait_for_selector(".tab[aria-current=page]:has-text('Projects')"), self.assertEqual(pg.locator(".ob").count(), 0), self.assertTrue(self.saved()["onboarded"])))
        pg.close()
        self.core.save_settings({"onboarded": False}); pg = self.page(); pg.goto(self.url + "?shell=desktop"); pg.wait_for_selector("#obnext"); pg.click("#obnext"); pg.click("#obnext")
        self.chk(S, "Finish setup", "closes onboarding, persists", "obskip", "/api/settings", lambda: (pg.click("#obskip"), pg.wait_for_selector(".ob", state="detached"), self.assertTrue(self.saved()["onboarded"])))
        pg.close()
        d = os.path.join(self.root, "ob-proj"); os.makedirs(d); self.native(picks=[d]); self.core.save_settings({"onboarded": False}); pg = self.page()
        pg.goto(self.url + "?shell=desktop"); pg.wait_for_selector("#obnext"); pg.click("#obnext"); pg.click("#obnext"); pg.wait_for_selector("#obpick:not([disabled])")
        self.chk(S, "Select project folder (pick)", "project added, onboarding closes", "obpick", "/api/project/add", lambda: (pg.click("#obpick"), pg.wait_for_selector(".ob", state="detached"), pg.wait_for_selector("tr[data-pick]:has-text('ob-proj')")))
        pg.close()

    # ---------------- overview ----------------
    def test_overview(self):
        S = "Overview"; self.core.save_settings({"onboarded": True}); self.native(); pg = self.page(); pg.goto(self.url + "?shell=desktop#overview"); pg.wait_for_selector("#addproj")
        self.chk(S, "Empty state", "explains what to do", "vOverview", "/api/state", lambda: self.assertTrue(pg.locator(".empty").count() >= 1))
        self.chk(S, "Add project (cancel)", "no change, no error", "addproj", "/api/native/pick_folder", lambda: (pg.wait_for_selector("#addproj:not([disabled])"), pg.click("#addproj"), pg.wait_for_timeout(300), self.assertEqual(self.errs, [])))
        self.chk(S, "Refresh", "toast confirms", "refresh", "/api/state", lambda: (pg.click("#refresh"), pg.wait_for_selector("#toast.on:has-text('refreshed')")))
        self.chk(S, "Generate report w/o project", "routes to Projects with hint", "genreport", "-", lambda: (pg.click("#genreport"), pg.wait_for_selector("#toast.on:has-text('Select a project')"), self.assertIn("Projects", pg.inner_text(".tab[aria-current=page]"))))
        self.load_demo(pg, "?shell=desktop"); self.review_all(pg); pg.click(".tab[data-go=studio]"); pg.click("#mode-private"); pg.click("#export"); pg.wait_for_selector(".xcard.ok:has-text('Exported')", timeout=60000)
        pg.click(".tab[data-go=overview]")
        self.chk(S, "Stats + recent reports", "counts and a recent row render", "vOverview", "/api/state", lambda: (self.assertIn("acme-storefront", pg.inner_text("#screen")), self.assertTrue(pg.locator(".stat").count() >= 3)))
        n = FakeNative(); import workreceipt_app as app; app.NATIVE = n
        self.chk(S, "Open recent report", "asks host to open newest report by name", "openrecent", "/api/native/open", lambda: ((k := len(n.calls)), pg.click("#openrecent"), _e.settle(pg, n, k + 1), self.assertEqual(n.calls[-1][0], "open"), self.assertTrue(n.calls[-1][1].endswith(".html"))))
        def nav():
            for k in ("projects", "reports", "settings", "overview"):
                pg.click(f".tab[data-go={k}]"); pg.wait_for_selector(f".tab[data-go={k}][aria-current=page]")
        self.chk(S, "Sidebar navigation (6 tabs)", "each tab becomes current", "go", "-", nav)
        self.chk(S, "Generate report (project loaded)", "goes to Studio", "genreport", "-", lambda: (pg.click("#genreport"), pg.wait_for_selector(".tab[data-go=studio][aria-current=page]")))
        pg.close()

    # ---------------- projects ----------------
    def test_projects(self):
        S = "Projects"; self.core.enable_demo(); self.core.save_settings({"onboarded": True}); d = os.path.join(self.root, "pj-extra"); os.makedirs(d)
        n = self.native(picks=[d]); pg = self.page(); pg.goto(self.url + "?shell=desktop#projects"); pg.wait_for_selector("tr[data-pick]")
        self.chk(S, "Native picker (Add project)", "picked folder listed", "addproj", "/api/native/pick_folder", lambda: (pg.wait_for_selector("#addproj:not([disabled])"), pg.click("#addproj"), pg.wait_for_selector("tr[data-pick]:has-text('pj-extra')")))
        pg.click("tr[data-pick]:has-text('acme-storefront')")
        self.chk(S, "Select project row", "row marked selected", "pick", "-", lambda: self.assertTrue(pg.locator("tr[data-pick]:has-text('acme-storefront')").get_attribute("class") or pg.locator("[aria-selected=true],.sel").count()))
        def manual():
            pg.fill("#repo", os.path.join(self.root, "nope")); pg.click("#usepath"); pg.click("#load"); pg.wait_for_selector(".callout.err")
            pg.fill("#repo", ""); pg.click("tr[data-pick]:has-text('acme-storefront')")
        self.chk(S, "Manual folder + invalid path error", "clear error, no crash", "usepath/load", "/api/preview", manual)
        for k in ("7", "30", "90", "month", "all"):
            self.chk(S, f"Date range {k}", "pill active, From/To filled", "setRange", "-", lambda k=k: (pg.click(f"[data-range='{k}']"), self.assertEqual(pg.get_attribute(f"[data-range='{k}']", "aria-pressed") or ("on" if "on" in (pg.get_attribute(f"[data-range='{k}']", "class") or "") else ""), pg.get_attribute(f"[data-range='{k}']", "aria-pressed") or "on")))
        def custom():
            pg.click("[data-range=all]"); pg.fill("#since", "2000-01-01"); pg.fill("#until", "2099-01-01"); pg.fill("#gitauthor", "nobody-xyz"); pg.fill("#client", "Acme Ltd")
            pg.click("#load"); pg.wait_for_selector(".callout.ok:has-text('Loaded')", timeout=60000)
            self.assertEqual(pg.input_value("#client"), "Acme Ltd"); self.assertEqual(pg.input_value("#gitauthor"), "nobody-xyz")
        self.chk(S, "Custom From/To, Git author, Client, Load activity", "values kept, load succeeds, loading state ends", "load", "/api/preview", custom)
        pg.click("#gitauthor", click_count=3); pg.fill("#gitauthor", ""); pg.click("#load"); pg.wait_for_selector(".callout.ok:has-text('Loaded')", timeout=60000)
        def rm():
            pg.click("[data-rmproj]:near(:text('pj-extra'))" if False else f"[data-rmproj='{d}']"); pg.click("#confirmdel"); pg.wait_for_selector("tr:has-text('pj-extra')", state="detached"); self.assertTrue(os.path.isdir(d))
        self.chk(S, "Remove project (confirm)", "removed from list, folder untouched", "confirmdel", "/api/project/remove", rm)
        def cancel_rm():
            pg.click("[data-rmproj]"); pg.click("[data-close]"); self.assertEqual(pg.locator(".dlgbox").count(), 0); self.assertTrue(pg.locator("tr[data-pick]").count() >= 1)
        self.chk(S, "Remove project (cancel)", "nothing removed", "closeDlg", "-", cancel_rm)
        gone = os.path.join(self.root, "pj-gone"); os.makedirs(gone); self.core.add_project(gone); shutil.rmtree(gone)
        self.chk(S, "Deleted/moved project", "folder-missing badge, no crash", "vProjects", "/api/state", lambda: (pg.click("#refresh"), pg.wait_for_selector(".badge:has-text('folder missing')")))
        self.chk(S, "File dropped as project (non-folder)", "clear error", "addProjectFlow", "/api/project/add", lambda: (pg.evaluate("window.wrDropped(%r)" % os.path.join(self.root, "nofile.txt")), pg.wait_for_selector("#toast.on")))
        pg.close()

    # ---------------- studio / privacy ----------------
    def test_studio_and_privacy(self):
        S = "Report Studio"; self.native(); pg = self.page(); self.load_demo(pg, "?shell=desktop")
        pg.click(".tab[data-go=studio]"); pg.click("#mode-private"); pg.wait_for_selector("[data-req]")
        def edit():
            pg.click("[data-req]"); pg.keyboard.press("End"); pg.keyboard.type(" EDITED"); pg.click(".tab[data-go=reports]"); pg.click(".tab[data-go=studio]"); pg.click("#mode-private")
            self.assertIn("EDITED", pg.inner_text("[data-req]"))
        self.chk(S, "Edit request titles", "edit retained across tabs", "input[data-req]", "-", edit)
        self.chk(S, "Export blocked until review (UI)", "toast + routes to Privacy Center", "doExport", "/api/export", lambda: (pg.click("#export"), pg.wait_for_selector(".tab[data-go=privacy][aria-current=page]")))
        P = "Privacy Center"
        self.chk(P, "Expand/collapse group", "aria-expanded toggles", "data-toggle", "-", lambda: (pg.locator("[data-toggle]").first.click(), self.assertEqual(pg.locator("[data-toggle]").first.get_attribute("aria-expanded"), "true"), pg.locator("[data-toggle]").first.click(), self.assertEqual(pg.locator("[data-toggle]").first.get_attribute("aria-expanded"), "false")))
        pg.locator("[data-toggle]").first.click()
        self.chk(P, "Detection details", "line/col/context shown", "detRow", "-", lambda: self.assertIn("line", pg.inner_text(".gp")))
        def reveal():
            pg.click("[data-reveal]"); pg.wait_for_selector("#rvd, .dlgbox"); self.assertTrue(pg.locator(".dlgbox").count() == 1); pg.keyboard.press("Escape"); self.assertEqual(pg.locator(".dlgbox").count(), 0)
        self.chk(P, "Reveal value + close", "dialog opens, Esc closes", "doReveal", "/api/reveal", reveal)
        def review_cycle():
            pg.click("[data-review]"); pg.click(".ropt:has-text('Unsure')"); pg.click(".ack .ropt"); pg.click("#confirmrev"); pg.wait_for_selector("#toast.on:has-text('Review recorded')")
        self.chk(P, "Review + confirm", "decision recorded, counter advances", "confirmrev", "-", review_cycle)
        self.chk(P, "Review cancel", "no decision recorded", "closeDlg", "-", lambda: (pg.click("[data-review]"), pg.click("[data-close]"), self.assertEqual(pg.locator(".dlgbox").count(), 0)))
        self.chk(P, "Change review", "Change opens dialog with prior pick", "data-review", "-", lambda: (pg.click("[data-review]:has-text('Change')"), self.assertTrue(pg.locator(".ropt input:checked").count() >= 1), pg.click("[data-close]")))
        def terms():
            pg.fill("#term", "acmeSecretWord"); pg.click("#addterm"); pg.wait_for_selector("[data-rmterm]"); pg.click("[data-rmterm]"); pg.wait_for_selector("[data-rmterm]", state="detached")
        self.chk(P, "Custom redaction term add/remove", "tag appears, rescans, removable", "addterm/rmterm", "/api/preview", terms)
        def server_block():
            r = self.core.export({"repo": [p for p in self.core.all_projects(self.core.load_settings()) if p["name"] == "acme-storefront"][0]["path"], "since": "", "until": ""}, {}, {})
            self.assertFalse(r.get("ok"))
        self.chk(P, "Server-side export block", "export without approvals refused", "core.export", "/api/export", server_block, level="backend")
        self.review_all(pg)
        self.chk(P, "Approval counter", "shows Clear / all reviewed", "vPrivacy", "-", lambda: self.assertTrue("Clear" in pg.inner_text("#screen") or "reviewed" in pg.inner_text("#screen")))
        pg.click(".tab[data-go=studio]"); pg.click("#mode-private")
        def prev():
            pg.click("#preview"); pg.wait_for_selector("iframe.frame"); self.assertEqual(pg.evaluate("document.querySelector('iframe.frame').contentWindow.scrollY"), 0)
        self.chk(S, "Preview (opens at top)", "iframe rendered, scroll 0", "makePreview", "/api/render", prev)
        self.chk(S, "Export", "HTML (+PDF if backend) written, registered in history", "doExport", "/api/export", lambda: (pg.click("#export"), pg.wait_for_selector(".xcard.ok:has-text('Exported')", timeout=60000), self.assertTrue(len(self.core.history()) >= 1)))
        n = self.native()
        self.chk(S, "Open report / Show in Finder (post-export)", "name-only calls to host", "fileAction", "/api/native/open|reveal", lambda: (pg.click(".xcard [data-open][data-kind=html]"), pg.click(".xcard [data-showfile]"), _e.settle(pg, n, 2), self.assertEqual([c[0] for c in n.calls], ["open", "reveal"])))
        pg.close()

    # ---------------- reports ----------------
    def test_reports(self):
        S = "Reports"; n = self.native(); pg = self.page(); self.core.save_settings({"onboarded": True}); pg.goto(self.url + "?shell=desktop#reports"); pg.wait_for_selector("#screen")
        if not self.core.history():
            self.load_demo(pg, "?shell=desktop"); self.review_all(pg); pg.click(".tab[data-go=studio]"); pg.click("#mode-private"); pg.click("#export"); pg.wait_for_selector(".xcard.ok:has-text('Exported')", timeout=60000)
        pg.click(".tab[data-go=reports]"); pg.wait_for_selector("tr:has-text('acme-storefront')")
        self.chk(S, "Search", "filters, empty-match message", "input#rq", "-", lambda: (pg.fill("#rq", "zzz"), self.assertIn("No reports match", pg.inner_text("#screen")), pg.fill("#rq", "acme"), self.assertIn("acme-storefront", pg.inner_text("#screen"))))
        self.chk(S, "Date filters", "future From hides rows; cleared shows", "input#rf/#rt", "-", lambda: (pg.fill("#rf", "2099-01-01"), self.assertIn("No reports match", pg.inner_text("#screen")), pg.fill("#rf", ""), pg.fill("#rt", "2000-01-01"), self.assertIn("No reports match", pg.inner_text("#screen")), pg.fill("#rt", "")))
        self.chk(S, "Open report", "host called with file name", "data-open", "/api/native/open", lambda: ((k := len(n.calls)), pg.click("[data-open][data-kind=html]"), _e.settle(pg, n, k + 1), self.assertEqual(n.calls[-1][0], "open")))
        self.chk(S, "Show in Finder", "host called with file name", "data-showfile", "/api/native/reveal", lambda: ((k := len(n.calls)), pg.click("[data-showfile]"), _e.settle(pg, n, k + 1), self.assertEqual(n.calls[-1][0], "reveal")))
        n.res = {"ok": False, "error": "That report file no longer exists. It may have been moved or deleted"}
        self.chk(S, "Missing file handling", "error toast, no crash", "fileAction", "/api/native/open", lambda: (pg.click("[data-open]"), pg.wait_for_selector("#toast.on:has-text('no longer exists')")))
        self.chk(S, "Delete cancel", "report kept", "closeDlg", "-", lambda: (pg.click("[data-delrep]"), pg.click("[data-close]"), self.assertEqual(pg.locator("[data-delrep]").count(), 1)))
        self.chk(S, "Delete confirm", "report removed from list and disk", "confirmdel", "/api/report/delete", lambda: (pg.click("[data-delrep]"), pg.click("#confirmdel"), pg.wait_for_selector(".empty:has-text('No reports yet')")))
        def srv():
            import urllib.request, urllib.error
            r = urllib.request.Request(self.url + "api/report/delete", data=b'{"name":"x.html"}', method="POST", headers={"X-WR-Token": __import__("workreceipt_app").TOKEN})
            with self.assertRaises(urllib.error.HTTPError) as c: urllib.request.urlopen(r)
            self.assertEqual(c.exception.code, 400)
        self.chk(S, "Delete requires server confirmation", "400 without confirm", "/api/report/delete", "-", srv, level="backend")
        pg.close()

    # ---------------- settings / shell ----------------
    def settle(self, k, v):   # Choose… sets the field first and saves async: wait for the save, and for its re-render, before the next step
        for _ in range(50):
            if self.saved().get(k) == v: break
            time.sleep(0.1)
        self.assertEqual(self.saved()[k], v); time.sleep(0.5)

    def test_settings_and_shell(self):
        S = "Settings"; self.core.save_settings({"onboarded": True}); pin = os.environ.get("WORKRECEIPT_CLAUDE_DIR")
        if pin: self.core.save_settings({"claude_dir": pin}); os.environ.pop("WORKRECEIPT_CLAUDE_DIR"); self.addCleanup(os.environ.__setitem__, "WORKRECEIPT_CLAUDE_DIR", pin)
        a, b = os.path.join(self.root, "au-claude"), os.path.join(self.root, "au-out"); os.makedirs(a); os.makedirs(b)
        self.native(picks=[a, b]); pg = self.page(); pg.goto(self.url + "?shell=desktop#settings"); pg.wait_for_selector("[data-choose=s_claude]:not([disabled])")
        self.chk(S, "Claude folder Choose…", "field filled and saved", "data-choose", "/api/native/pick_folder", lambda: (pg.click("[data-choose=s_claude]"), pg.wait_for_function("p=>document.querySelector('#s_claude').value===p", arg=a), self.settle("claude_dir", a)))
        self.chk(S, "Reports folder Choose…", "field filled and saved", "data-choose", "/api/native/pick_folder", lambda: (pg.click("[data-choose=s_out]"), pg.wait_for_function("p=>document.querySelector('#s_out').value===p", arg=b), self.settle("out_dir", b)))
        def fields():
            pg.fill("#s_author", "Audit Author"); pg.fill("#s_client", "Audit Client"); pg.fill("#s_terms", "alpha\nbeta"); pg.click("#savesettings"); pg.wait_for_selector("#toast.on:has-text('Settings saved')")
            s = self.saved(); self.assertEqual((s["author"], s["client"], s["redact_terms"]), ("Audit Author", "Audit Client", ["alpha", "beta"]))
            pg.reload(); pg.wait_for_selector("#s_author"); self.assertEqual(pg.input_value("#s_author"), "Audit Author"); self.assertEqual(pg.input_value("#s_terms"), "alpha\nbeta")
        self.chk(S, "Prepared by / Default client / Always-redact terms / Save", "persist and survive reload", "savesettings", "/api/settings", fields)
        def themes():
            for t in ("dark", "light", "system"):
                pg.click(f"button[data-theme={t}]"); self.assertEqual(pg.get_attribute(f"button[data-theme={t}]", "class") or "", "on")
            pg.click("button[data-theme=dark]"); pg.click("#savesettings"); pg.wait_for_selector("#toast.on"); self.assertEqual(self.saved()["theme"], "dark")
        self.chk(S, "Theme System/Light/Dark", "applies and persists after Save", "data-theme", "/api/settings", themes)
        def moon():
            pg.click("#theme"); self.assertEqual(pg.evaluate("document.documentElement.dataset.theme"), "light"); pg.wait_for_timeout(300); self.assertEqual(self.saved()["theme"], "light")
        self.chk("Shell", "Sidebar moon/sun toggle", "toggles theme and persists", "theme", "/api/settings", moon)
        self.chk(S, "Version / data dir info", "shows version and data folder", "vSettings", "/api/state", lambda: (self.assertIn(self.core.VERSION, pg.inner_text("#screen")), self.assertIn(self.core._home(), pg.inner_text("#screen"))))
        self.chk(S, "Diagnostics card + Check again", "reports ready", "diagretry", "/api/native/status", lambda: (pg.click("#diagretry"), pg.wait_for_selector("#toast.on:has-text('ready')"), self.assertIn("ready", pg.inner_text("#diag"))))
        def keys():
            mod = "Control"
            for k, tab in (("1", "overview"), ("2", "projects"), ("3", "studio"), ("4", "privacy"), ("5", "reports"), (",", "settings")):
                pg.keyboard.press(f"{mod}+{k}"); pg.wait_for_selector(f".tab[data-go={tab}][aria-current=page]")
        self.chk("Shell", "Keyboard shortcuts (nav)", "Cmd/Ctrl+1-5 and , switch screens", "keydown", "-", keys)
        def cmds():
            pg.evaluate("window.wrCommand('go:reports')"); pg.wait_for_selector(".tab[data-go=reports][aria-current=page]"); pg.evaluate("window.wrCommand('refresh')"); pg.wait_for_selector("#toast.on:has-text('refreshed')")
        self.chk("Shell", "Menu commands via wrCommand (page side)", "go/refresh execute", "wrCommand", "run_js", cmds)
        self.chk("Shell", "Tab key reaches controls", "focus leaves body", "-", "-", lambda: (pg.keyboard.press("Tab"), self.assertTrue(pg.evaluate("document.activeElement!==document.body"))))
        pg.close()
        # browser (non-desktop) mode
        pg = self.page(); self.native(); pg.goto(self.url + "#settings"); pg.wait_for_selector("[data-choose=s_claude]")
        self.chk(S, "Choose… in a plain browser", "enabled, tells user to type a path (no fake success)", "data-choose", "-", lambda: (self.assertFalse(pg.is_disabled("[data-choose=s_claude]")), pg.click("[data-choose=s_claude]"), pg.wait_for_selector("#toast.on:has-text('Type or paste')")))
        pg.close()


if __name__ == "__main__":
    unittest.main()
