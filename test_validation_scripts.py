"""The macOS validation scripts themselves: syntax, report exit codes, and that the independent PDF checker really flags tampered PDFs.
(The native WKWebView/PDFKit/app-launch parts only run on a Mac via scripts/validate_macos.sh.)"""
import json, os, py_compile, socket, subprocess, sys, tempfile, time, unittest, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
SC = os.path.join(HERE, "scripts")
sys.path.insert(0, SC); sys.path.insert(0, HERE)
os.environ.setdefault("WRV_SELFTEST", "1")      # pdfkit_check falls back to pypdf/poppler off macOS
import app_core as core, pdfkit_check as pk


class Scripts(unittest.TestCase):
    def test_syntax(self):
        for f in sorted(os.listdir(SC)):
            if f.endswith(".py"):
                py_compile.compile(os.path.join(SC, f), doraise=True, cfile=os.path.join(tempfile.gettempdir(), "wrv-" + f + "c"))
        self.assertEqual(subprocess.run(["bash", "-n", os.path.join(SC, "validate_macos.sh")]).returncode, 0)
        self.assertTrue(os.access(os.path.join(SC, "validate_macos.sh"), os.X_OK))

    def test_script_has_no_destructive_or_real_data_paths(self):
        src = "\n".join(l for l in open(os.path.join(SC, "validate_macos.sh")).read().splitlines() if not l.lstrip().startswith("#"))
        for bad in ("rm -rf ~", "rm -rf $HOME", "~/.claude", "$HOME/.claude", "Library/Application Support"):
            self.assertNotIn(bad, src)
        self.assertIn('*/wr-validate.*', src)               # the only rm -rf is guarded to the mktemp sandbox

    def _report(self, rows):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "r.jsonl")
        open(p, "w").write("".join(json.dumps(dict(r, detail="")) + "\n" for r in rows))
        env = {k: v for k, v in os.environ.items() if k != "WRV_SELFTEST"}
        return subprocess.run([sys.executable, os.path.join(SC, "wrv_report.py"), "report", p], capture_output=True, text=True, env=env)

    def test_add_appends_to_results_file_and_makes_no_stray_files(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        res = os.path.join(d, "r.jsonl")
        r = subprocess.run([sys.executable, os.path.join(SC, "wrv_report.py"), "add", "some check", "PASS", "detail", "--optional"], cwd=d, env=dict(os.environ, WRV_RESULTS=res), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(os.listdir(d), ["r.jsonl"])
        row = json.loads(open(res).read())
        self.assertEqual((row["name"], row["status"], row["detail"], row["required"]), ("some check", "PASS", "detail", False))

    def test_exit_codes(self):
        ok = {"name": "a", "status": "PASS", "required": True}
        self.assertEqual(self._report([ok]).returncode, 0)
        self.assertEqual(self._report([ok, {"name": "b", "status": "FAIL", "required": True}]).returncode, 1)
        self.assertEqual(self._report([ok, {"name": "b", "status": "BLOCKED", "required": True}]).returncode, 2)
        self.assertEqual(self._report([ok, {"name": "b", "status": "SKIP", "required": True}]).returncode, 2)
        self.assertEqual(self._report([ok, {"name": "b", "status": "SKIP", "required": False}]).returncode, 0)
        self.assertEqual(self._report([]).returncode, 2)                      # no results is never a pass
        self.assertIn("RESULT: PASS", self._report([ok]).stdout)


class CrossProcessApproval(unittest.TestCase):
    """Root cause of 'approval was refused' for the launched source/packaged apps: finding ids are salted per process (app_core._SALT), so
    a review computed in the harness process can never match a separately launched app. This is correct product behaviour; the harness
    must review through the app's own API. Uses a REAL second process (the same app the desktop shell wraps)."""
    @classmethod
    def setUpClass(cls):
        from test_client_safe import hostile_ws
        cls.ws = hostile_ws()
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        cls.proc = subprocess.Popen([sys.executable, os.path.join(HERE, "workreceipt_app.py"), "--no-open", "--port", str(port)], env=dict(os.environ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        import wrv
        cls.wrv = wrv
        for _ in range(60):
            try:
                cls.api = wrv.Api(f"http://127.0.0.1:{port}"); break
            except Exception:                                                  # noqa: BLE001
                time.sleep(0.25)
        else:
            raise RuntimeError("the second app process did not start")
        cls.ctx = wrv.Ctx(cls.ws)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate(); cls.proc.wait(10); cls.ws.done()

    def approve(self, ctx_ap_override=None):
        w, ctx, api = self.wrv, self.ctx, self.api
        d = w.base_draft(ctx)
        c, pv = api.post("/api/client/preview", w.body(ctx, d, **({"approved": ctx_ap_override} if ctx_ap_override is not None else {})))
        return api.post("/api/client/approve", w.body(ctx, d, confirm={"privacy_review": True, "content_hash": pv["content_hash"]}, **({"approved": ctx_ap_override} if ctx_ap_override is not None else {}))), pv

    def test_ids_from_another_process_do_not_count_as_a_review(self):
        (c, r), pv = self.approve()                                            # ids computed in THIS process (Ctx.ap)
        self.assertEqual((c, r["reason"]), (409, "findings")); self.assertGreater(pv["pending_findings"], 0)
        self.assertFalse(r.get("token"))

    def test_review_through_the_apps_own_api_is_accepted_and_still_required(self):
        n = self.wrv.review_via_api(self.api, self.ctx)
        self.assertGreater(n, 0)
        (c, r), pv = self.approve()
        self.assertEqual(c, 200, r); self.assertTrue(r["token"]); self.assertEqual(pv["pending_findings"], 0)
        weaker = dict(self.ctx.ap); weaker.pop(next(iter(weaker)))             # drop one decision: approval must be refused again
        (c, r), pv = self.approve(weaker)
        self.assertEqual((c, r["reason"]), (409, "findings"))


class ReportAccounting(unittest.TestCase):
    """The browser stage showed FAIL although 12 tests passed: one of the 13 had failed. The report now names failing tests, and a skipped
    critical test (missing Chrome/poppler) can never be counted as coverage."""
    def run_junit(self, cases):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        x = os.path.join(d, "j.xml"); res = os.path.join(d, "r.jsonl")
        body = "".join(f'<testcase classname="{c}.K" name="{n}">{inner}</testcase>' for c, n, inner in cases)
        open(x, "w").write(f"<testsuites><testsuite>{body}</testsuite></testsuites>")
        r = subprocess.run([sys.executable, os.path.join(SC, "wrv_report.py"), "junit", x, res, "--min-client-safe", "2", "--min-ui", "2"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = {json.loads(l)["name"]: json.loads(l) for l in open(res)}
        return rows, d

    def test_failing_browser_test_is_named_and_fails_the_stage(self):
        rows, d = self.run_junit([("test_client_safe", "a", ""), ("test_client_safe", "b", ""), ("test_client_safe_ui", "ok1", ""), ("test_client_safe_ui", "ok2", ""),
                                  ("test_client_safe_ui", "full_flow", '<failure message="xcard.ok timeout">x</failure>')])
        ui = rows["Client-Safe real-click browser tests actually ran and passed"]
        self.assertEqual(ui["status"], "FAIL"); self.assertIn("full_flow", ui["detail"]); self.assertIn("xcard.ok timeout", ui["detail"])
        self.assertIn("test_client_safe_ui::full_flow", open(os.path.join(d, "failed-tests.txt")).read())
        self.assertEqual(rows["regression + security suite (pytest, all existing tests)"]["status"], "FAIL")
        self.assertIn("FAILED: test_client_safe_ui::full_flow", rows["regression + security suite (pytest, all existing tests)"]["detail"])

    def test_skipped_critical_tests_are_not_coverage(self):
        rows, d = self.run_junit([("test_client_safe", "a", ""), ("test_client_safe", "b", ""), ("test_client_safe_ui", "c", ""), ("test_client_safe_ui", "d", ""),
                                  ("test_client_safe", "needs_poppler", '<skipped message="needs Chrome and poppler"/>')])
        r = rows["no critical tests were skipped"]
        self.assertEqual(r["status"], "FAIL"); self.assertIn("poppler", r["detail"]); self.assertIn("brew install", r["detail"])
        self.assertEqual(rows["regression + security suite (pytest, all existing tests)"]["status"], "PASS")       # the suite itself did not fail ...

    def test_skips_outside_the_critical_suites_are_reported_not_fatal(self):
        rows, d = self.run_junit([("test_client_safe", "a", ""), ("test_client_safe", "b", ""), ("test_client_safe_ui", "c", ""), ("test_client_safe_ui", "d", ""),
                                  ("test_packaging", "x", '<skipped message="not on this OS"/>')])
        self.assertEqual(rows["no critical tests were skipped"]["status"], "PASS")
        self.assertIn("1 skipped", rows["regression + security suite (pytest, all existing tests)"]["detail"])

    def test_too_few_client_safe_tests_is_a_failure(self):
        rows, d = self.run_junit([("test_client_safe", "a", "")])
        self.assertEqual(rows["Client-Safe backend adversarial tests actually ran and passed"]["status"], "FAIL")

    def test_dependency_check_gives_install_instructions(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        res = os.path.join(d, "r.jsonl")
        env = dict(os.environ, PATH="/nonexistent", WR_CHROME="/nonexistent/chrome")
        subprocess.run([sys.executable, os.path.join(SC, "wrv_report.py"), "deps", res], env=env, check=True)
        rows = {json.loads(l)["name"]: json.loads(l) for l in open(res)}
        pop = [r for n, r in rows.items() if n.startswith("poppler")][0]
        self.assertEqual(pop["status"], "FAIL"); self.assertIn("brew install poppler", pop["detail"]); self.assertTrue(pop["required"])
        ch = [r for n, r in rows.items() if n.startswith("Google Chrome")][0]
        self.assertIn("brew install --cask google-chrome", ch["detail"]) if ch["status"] == "FAIL" else None


@unittest.skipUnless(core.chrome_path() and shutil.which("pdftotext"), "needs Chrome + poppler")
class PdfChecker(unittest.TestCase):
    def make(self, html):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        h = os.path.join(d, "r.html"); open(h, "w", encoding="utf-8").write(html)
        return core.to_pdf(h)

    BASE = "<html><head><title>Work report for Initech</title></head><body><h1>Work report</h1><p>Rebuilt the invoice screen so customers can pay online</p></body></html>"

    def verify(self, pdf, html=None):
        return pk.verify(pdf, html or self.BASE, expect=["Rebuilt the invoice screen"], title="Billing Revamp")[0]

    def test_clean_pdf_passes(self):
        self.assertEqual(self.verify(self.make(self.BASE)), [])

    def test_hidden_text_is_flagged(self):
        bad = self.BASE.replace("</body>", '<div style="color:#fff;font-size:1px">oracle-fin-01 secret words here</div></body>')
        codes = self.verify(self.make(bad))
        self.assertTrue(any(c.startswith("text_not_in_html") for c in codes), codes); self.assertIn("canary_in_text", codes)

    def test_private_title_is_flagged(self):
        bad = self.BASE.replace("Work report for Initech", "oracle-fin-01 internal")
        codes = self.verify(self.make(bad), self.BASE)
        self.assertIn("canary_in_metadata", codes)

    def test_dropped_content_is_flagged(self):
        codes = self.verify(self.make(self.BASE), self.BASE.replace("</body>", "<p>" + " ".join(f"extra{n}word" for n in range(40)) + "</p></body>"))
        self.assertTrue(any(c.startswith("html_text_missing_from_pdf") for c in codes), codes)

    def test_unreadable_pdf_is_not_clean(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "x.pdf"); open(p, "wb").write(b"%PDF-1.4 not really")
        try:
            codes = self.verify(p)
        except Exception:
            return                                                             # refusing to read it is also a non-pass
        self.assertTrue(codes)


if __name__ == "__main__":
    unittest.main()
