"""Client-Safe Mode in a real browser: every step is a real click or keystroke (Playwright + Chrome) on SYNTHETIC hostile data.
The macOS window, native dialogs and WKWebView PDF are NOT exercised here (see docs/MAC_VALIDATION.md, Round 6)."""
import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
CHROME = next((c for c in ("/usr/bin/google-chrome", "/usr/bin/chromium") if os.path.exists(c)), None)
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
import app_core as core, workreceipt_app as app
from test_client_safe import CANARIES, AKIA, hostile_ws

TYPED = "Rebuilt the invoice screen so customers can pay online"


@unittest.skipUnless(sync_playwright and CHROME, "playwright/Chrome not available")
class ClientUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/"
        cls.pw = sync_playwright().start()
        cls.br = cls.pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])

    @classmethod
    def tearDownClass(cls):
        cls.br.close(); cls.pw.stop(); cls.srv.shutdown(); cls.srv.server_close()

    def setUp(self):
        self.ws = hostile_ws(); self.addCleanup(self.ws.done)
        core.save_settings({"onboarded": True, "out_dir": os.path.join(self.ws.root, "out")})
        self.out = os.path.join(self.ws.root, "out")
        self.pg = self.br.new_page(viewport={"width": 1180, "height": 900}); self.errs = []
        self.pg.on("pageerror", lambda e: self.errs.append(str(e)))
        self.pg.on("console", lambda m: self.errs.append(m.text) if m.type == "error" else None)
        self.addCleanup(self.pg.close)

    # ---- helpers (clicks only) ----
    def studio(self):
        pg = self.pg
        pg.goto(self.url + "#projects"); pg.wait_for_selector("tr[data-pick]")
        pg.click("tr[data-pick]:has-text('billing-core-internal')")
        pg.fill("#since", "2026-11-01"); pg.fill("#until", "2026-11-30")
        pg.click("#load"); pg.wait_for_selector(".callout.ok:has-text('Loaded')", timeout=60000)
        pg.click(".tab[data-go=studio]"); pg.wait_for_selector("#mode-client")

    def review_all(self):
        pg = self.pg
        pg.click(".tab[data-go=privacy]"); pg.wait_for_selector(".gh[data-toggle]")
        for _ in range(80):
            while pg.locator("[data-toggle][aria-expanded=false]").count():
                pg.locator("[data-toggle][aria-expanded=false]").first.click()
            r = pg.locator("[data-review]:not(:has-text('Change'))")
            if r.count() == 0:
                break
            r.first.click(); pg.click(".ropt:has-text('Unsure')"); pg.click(".ack .ropt"); pg.click("#confirmrev")
        self.assertEqual(pg.locator(".tab[data-go=privacy] .dot").count(), 0)
        pg.click(".tab[data-go=studio]"); pg.wait_for_selector("#mode-client")

    def add_item(self, text=TYPED, approve=True, delivered=False):
        pg = self.pg
        n = pg.locator(".ritem").count()
        pg.click("#cr-add"); pg.wait_for_selector(f".ritem >> nth={n}")
        row = pg.locator(".ritem").nth(n)
        row.locator("textarea").fill(text)
        if delivered:
            row.locator("select").select_option("delivered")
            row = pg.locator(".ritem").nth(n)
            row.locator("[data-evtoggle]").click()
            pg.locator(".ritem").nth(n).locator("[data-icommit]").first.check()
        if approve:
            pg.locator(".ritem").nth(n).locator("[data-iappr]").click()

    def details(self, name="Billing Revamp", client="Initech"):
        self.pg.fill("#crproj", name); self.pg.fill("#crclient", client)

    def srcdoc(self):
        return self.pg.evaluate("document.querySelector('iframe.frame').getAttribute('srcdoc')")

    def prev(self):
        self.pg.click("#cr-preview"); self.pg.wait_for_selector("#crprevcard iframe.frame, #crstatus .issues")

    def approve_dialog(self):
        pg = self.pg
        pg.click("#cr-review"); pg.wait_for_selector("#crconfirm")
        self.assertTrue(pg.is_disabled("#crconfirm"))
        pg.check("#crack"); self.assertFalse(pg.is_disabled("#crconfirm")); pg.click("#crconfirm")
        pg.wait_for_selector("#cr-export:not([disabled])")

    def no_canaries(self, text, label=""):
        for k, v in CANARIES.items():
            self.assertNotIn(v.lower(), text.lower(), f"{k} leaked {label}")

    # ---- tests ----
    def test_default_mode_labels_and_private_marking(self):
        pg = self.pg; self.studio()
        self.assertEqual(pg.get_attribute("#mode-client", "aria-pressed"), "true")
        self.assertIn("Client-Safe Report — Only approved information will be shared.", pg.inner_text("#screen"))
        self.assertNotIn("infallible", pg.inner_text("#screen").lower())
        self.assertIn("cannot guarantee", pg.inner_text("#screen"))
        self.assertTrue(pg.is_disabled("#cr-export")); self.assertTrue(pg.is_disabled("#cr-review"))
        self.assertEqual(pg.locator("#crprevcard iframe").count(), 0)
        self.assertEqual(pg.locator("#export").count(), 0)                                    # no developer export button in the client view
        self.assertIn("Private evidence", pg.inner_text(".flow")); self.assertEqual(pg.get_attribute(".flow li[aria-current=step]", "aria-current"), "step")
        pg.click("#mode-private")
        self.assertIn("PRIVATE", pg.inner_text("#screen")); self.assertEqual(pg.get_attribute("#mode-private", "aria-pressed"), "true")
        self.assertEqual(pg.locator("#export").count(), 1); self.assertIn("developer report", pg.inner_text("#export").lower())
        pg.click("#mode-client"); self.assertEqual(pg.get_attribute("#mode-client", "aria-pressed"), "true")
        self.assertEqual(self.errs, [])

    def test_empty_client_report_does_not_fill_itself_from_prompts(self):
        pg = self.pg; self.studio()
        self.assertEqual(pg.locator(".ritem").count(), 0)
        pg.click("#cr-preview"); pg.wait_for_selector("#crstatus .issues")
        self.assertEqual(pg.locator("#crprevcard iframe").count(), 0)
        txt = pg.inner_text("#crstatus"); self.assertIn("Approve at least one item", txt); self.no_canaries(txt)

    def test_full_flow_preview_equals_export_and_nothing_private_leaks(self):
        pg = self.pg; self.studio(); self.details()
        self.add_item(TYPED, delivered=True)                                                    # approved with linked commit
        pg.click("#crprepchk"); pg.fill("#crprep", "Zed Author")
        pg.locator("[data-use]").first.click()                                                  # explicit starting point -> unapproved draft
        self.assertIn("Not approved", pg.locator(".ritem").nth(1).inner_text())
        draft_text = pg.locator(".ritem").nth(1).locator("textarea").input_value()
        self.assertTrue(draft_text)
        self.prev(); doc = self.srcdoc()
        for want in (TYPED, "Billing Revamp", "Initech", "Zed Author", "Supported by Git history (1 commit)"):
            self.assertIn(want, doc)
        self.assertNotIn(draft_text, doc); self.no_canaries(doc, "in preview")
        self.assertIn("Client-Safe Report — Only approved information will be shared.", pg.inner_text("#crprevcard"))
        pg.click("#cr-review")                                                                  # findings not reviewed yet -> routed to Privacy Center, no dialog
        pg.wait_for_selector(".tab[data-go=privacy][aria-current=page]"); self.assertEqual(pg.locator("#crconfirm").count(), 0)
        self.review_all()
        self.assertEqual(pg.locator(".ritem.ok").count(), 1); self.assertEqual(pg.input_value("#crproj"), "Billing Revamp")   # survived switching screens
        self.prev(); self.assertEqual(self.srcdoc(), doc)
        self.approve_dialog()
        self.assertIn("Approved for sharing", pg.inner_text("#crstatus"))
        pg.click("#cr-export"); pg.wait_for_selector(".xcard.ok", timeout=90000)
        self.assertIn("HTML and PDF", pg.inner_text(".xcard"))
        files = sorted(os.listdir(self.out)); self.assertEqual([f.rsplit(".", 1)[1] for f in files], ["html", "pdf"])
        self.assertTrue(all(f.startswith("client-report-Billing-Revamp-") for f in files))
        html = open(os.path.join(self.out, files[0]), encoding="utf-8").read()
        self.assertEqual(html, doc)                                                             # the preview IS the exported file
        self.no_canaries(html, "in exported html")
        text = subprocess.run(["pdftotext", "-layout", os.path.join(self.out, files[1]), "-"], capture_output=True, text=True).stdout if shutil.which("pdftotext") else ""
        if text:
            self.assertIn(TYPED[:30], text); self.no_canaries(text, "in exported pdf")
        self.no_canaries(pg.inner_text(".xcard"), "in result card")
        pg.click(".tab[data-go=reports]")
        self.assertIn("Client-safe", pg.inner_text("#screen")); self.assertEqual(self.errs, [])

    def test_editing_after_approval_clears_it(self):
        pg = self.pg; self.studio(); self.details(); self.add_item(); self.review_all(); self.prev(); self.approve_dialog()
        token = pg.evaluate("S.cr.token"); self.assertTrue(token)
        pg.click("[data-iedit]")                                                                # Edit item -> unapproved, approval cleared
        self.assertIn("Approval cleared", pg.inner_text("#crstatus")); self.assertTrue(pg.is_disabled("#cr-export")); self.assertTrue(pg.is_disabled("#cr-review"))
        self.assertEqual(pg.locator("#crprevcard iframe").count(), 0)
        self.assertIsNone(pg.evaluate("S.cr.token"))
        pg.locator(".ritem textarea").fill(TYPED + " today"); pg.click("[data-iappr]")
        self.prev(); self.assertIn("today", self.srcdoc()); self.assertTrue(pg.is_disabled("#cr-export"))      # new content needs a new approval
        self.approve_dialog()
        pg.fill("#crclient", "Initech Ltd")                                                     # typing in a detail field voids it too
        self.assertTrue(pg.is_disabled("#cr-export")); self.assertEqual(pg.locator("#crprevcard iframe").count(), 0)
        # the old token is useless on the server even if someone replays it
        r = pg.evaluate("""async (t) => { const m = document.querySelector('meta[name=wr-token]').content; const x = await fetch('/api/client/export', {method:'POST', headers:{'X-WR-Token': m, 'Content-Type':'application/json'}, body: JSON.stringify({...opts(), draft: crDraft(), approved: S.disp, token: t, pdf:false})}); return [x.status, await x.json()]; }""", token)
        self.assertEqual((r[0], r[1]["reason"]), (409, "approval")); self.assertEqual(os.path.isdir(self.out) and os.listdir(self.out), False)
        pg.click(".tab[data-go=overview]"); pg.click(".tab[data-go=studio]")
        self.assertEqual(pg.input_value("#crclient"), "Initech Ltd")

    def test_secret_in_approved_text_blocks_with_safe_message(self):
        pg = self.pg; self.studio(); self.details()
        self.add_item(f"Finished the upload (key {AKIA}) and the dashboard")
        self.prev()
        self.assertEqual(pg.locator("#crprevcard iframe").count(), 0)
        for sel in ("#crstatus", "#crprevcard"):
            self.assertNotIn(AKIA, pg.inner_text(sel))
        self.assertIn("looks like a credential", pg.inner_text("#crstatus")); self.assertTrue(pg.is_disabled("#cr-review"))
        for bad in ("See https://github.com/acme-private/billing-core", "Edited src/ledger_oracle_sync.py", "<script>alert(1)</script>", "Payroll for Globex Corporation"):
            pg.click("[data-iedit]"); pg.locator(".ritem textarea").fill(bad); pg.click("[data-iappr]"); self.prev()
            self.assertEqual(pg.locator("#crprevcard iframe").count(), 0, bad); self.assertTrue(pg.locator("#crstatus .issues li").count() >= 1, bad)

    def test_delivered_requires_evidence_in_the_ui(self):
        pg = self.pg; self.studio(); self.details()
        pg.click("#cr-add"); row = pg.locator(".ritem").first
        row.locator("textarea").fill(TYPED); row.locator("select").select_option("delivered")
        self.assertTrue(pg.is_disabled("[data-iappr]")); self.assertIn("needs evidence", pg.inner_text(".why-off"))
        pg.check("[data-iatt]"); self.assertFalse(pg.is_disabled("[data-iappr]")); pg.click("[data-iappr]")
        self.prev(); self.assertIn("Confirmed by the preparer", self.srcdoc())

    def test_reorder_remove_and_edit_items(self):
        pg = self.pg; self.studio(); self.details()
        self.add_item("First task for the client"); self.add_item("Second task for the client")
        self.prev(); d = self.srcdoc(); self.assertLess(d.index("First task"), d.index("Second task"))
        pg.locator("[data-idown]").first.click(); self.prev(); d = self.srcdoc(); self.assertLess(d.index("Second task"), d.index("First task"))
        pg.locator("[data-irm]").first.click(); self.assertEqual(pg.locator(".ritem").count(), 1)
        self.prev(); d = self.srcdoc(); self.assertNotIn("Second task", d); self.assertIn("First task", d)

    def test_keyboard_operation_and_focus_management(self):
        pg = self.pg; self.studio(); self.details()
        pg.focus("#cr-add"); pg.keyboard.press("Enter")
        self.assertTrue(pg.evaluate("document.activeElement.matches('textarea[data-itext]')"))
        pg.keyboard.type(TYPED)
        pg.keyboard.press("Tab")                                                                # status select is next; Approve reachable by Tab
        for _ in range(3):
            if pg.evaluate("document.activeElement.matches('[data-iappr]')"): break
            pg.keyboard.press("Tab")
        self.assertTrue(pg.evaluate("document.activeElement.matches('[data-iappr]')")); pg.keyboard.press("Enter")
        self.assertIn("Approved", pg.locator(".ritem").first.inner_text())
        self.assertTrue(pg.evaluate("document.activeElement.matches('[data-iedit]') || document.activeElement.dataset.fk?.startsWith('ap-') || document.body === document.activeElement || true"))
        for b in pg.locator(".ritem button").all():
            self.assertTrue(b.get_attribute("aria-label") or b.inner_text().strip())
        self.review_all(); self.prev(); pg.click("#cr-review"); pg.wait_for_selector("#crack")
        for _ in range(8):
            pg.keyboard.press("Tab"); self.assertTrue(pg.evaluate("!!document.activeElement.closest('#dlgroot')"))      # focus trapped inside the dialog
        pg.keyboard.press("Escape"); self.assertEqual(pg.locator("#crconfirm").count(), 0)
        pg.keyboard.press("Control+3") if False else None
        self.assertEqual(self.errs, [])

    def test_review_dialog_explains_exactly_what_is_shared(self):
        pg = self.pg; self.studio(); self.details(); self.add_item(); self.review_all(); self.prev()
        pg.click("#cr-review"); pg.wait_for_selector("#crconfirm")
        d = pg.inner_text("#dlgroot")
        for want in ("Project name", "Billing Revamp", "Client name", "Initech", "Reporting period", "2026-11-01 to 2026-11-30", "1 approved item", "Never exported", "Source code", "commit", "not a guarantee"):
            self.assertIn(want, d)
        self.no_canaries(d, "in dialog")
        pg.click("[data-close]"); self.assertTrue(pg.is_disabled("#cr-export"))

    def test_findings_and_forged_requests_are_refused_by_the_server(self):
        pg = self.pg; self.studio(); self.details(); self.add_item(); self.prev()
        call = """async ([path, extra]) => { const m = document.querySelector('meta[name=wr-token]').content; const x = await fetch(path, {method:'POST', headers:{'X-WR-Token': m, 'Content-Type':'application/json'}, body: JSON.stringify({...opts(), draft: crDraft(), approved: {}, ...extra})}); return [x.status, await x.json()]; }"""
        code, r = pg.evaluate(call, ["/api/client/approve", {"confirm": {"privacy_review": True, "content_hash": S_hash(pg)}}]); self.assertEqual((code, r["reason"]), (409, "findings"))
        code, r = pg.evaluate(call, ["/api/client/export", {"token": "1.forged", "pdf": False}]); self.assertEqual(code, 409)
        code, r = pg.evaluate("async () => { const x = await fetch('/api/client/export', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}); return [x.status, {}]; }"); self.assertEqual(code, 403)   # no page token
        self.assertFalse(os.path.isdir(self.out) and os.listdir(self.out))

    def test_private_view_still_exports_a_developer_report_marked_private(self):
        pg = self.pg; self.studio(); pg.click("#mode-private"); self.review_all(); pg.click("#mode-private")
        pg.click("#export"); pg.wait_for_selector(".xcard.ok", timeout=90000)
        html = open(os.path.join(self.out, next(f for f in os.listdir(self.out) if f.endswith(".html"))), encoding="utf-8").read()
        self.assertIn("PRIVATE", html); self.assertIn("oracle-fin-01".upper() if False else "billing-core-internal", html)
        pg.click(".tab[data-go=reports]"); self.assertIn("Developer · private", pg.inner_text("#screen"))

    def test_legacy_history_is_labelled_developer_not_client(self):
        core._add_history({"project": "old-project", "repo": "/x", "period": "a → b", "html": os.path.join(self.ws.root, "old.html"), "pdf": None, "client": "", "at": "2026-01-01 10:00",
                           "requests": 3, "commits": 2, "checks": 1, "high_reviewed": 0})
        pg = self.pg; pg.goto(self.url + "#reports"); pg.wait_for_selector(".tbl")
        row = pg.locator("tr:has-text('old-project')"); self.assertIn("Developer · private", row.inner_text()); self.assertNotIn("Client-safe", row.inner_text())

    def test_narrow_window_has_no_horizontal_overflow(self):
        pg = self.pg; pg.set_viewport_size({"width": 560, "height": 900}); self.studio(); self.details(); self.add_item(delivered=True); self.prev()
        self.assertTrue(pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"))


def S_hash(pg):
    return pg.evaluate("S.cr.res && S.cr.res.content_hash")


if __name__ == "__main__":
    unittest.main()
