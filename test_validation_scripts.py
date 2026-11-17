"""The macOS validation scripts themselves: syntax, report exit codes, and that the independent PDF checker really flags tampered PDFs.
(The native WKWebView/PDFKit/app-launch parts only run on a Mac via scripts/validate_macos.sh.)"""
import json, os, py_compile, subprocess, sys, tempfile, unittest, shutil
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
