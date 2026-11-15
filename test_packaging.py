"""M6: packaging configuration, PDF export, data locations, error messages. Runs on Linux; the macOS-only pieces are only
statically checked here (see docs/MAC_VALIDATION.md)."""
import json, os, plistlib, py_compile, re, shutil, subprocess, sys, tempfile, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app_core as core
from test_phase1 import WS
from desktop import main as dm

ROOT = os.path.dirname(os.path.abspath(__file__))
PW = "correct_horse_staple"
HI = "Xk9mQ2vL7pR4zT"


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


class BuildConfig(unittest.TestCase):
    def test_version_is_single_source(self):
        self.assertIn(f'version = "{core.VERSION}"', read("pyproject.toml"))
        self.assertIn("app_core.VERSION", read("desktop", "WorkReceipt.spec"))

    def test_spec_and_files_exist(self):
        spec = read("desktop", "WorkReceipt.spec")
        compile(spec, "WorkReceipt.spec", "exec")                      # syntax only
        for rel in ("ui/index.html", "ui/app.js", "ui/app.css", "examples/make_demo_workspace.py", "desktop/main.py", "desktop/icon/icon_1024.png"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), rel)
        self.assertIn("pdf_mac", read("desktop", "main.py")); py_compile.compile(os.path.join(ROOT, "desktop", "pdf_mac.py"), doraise=True)
        self.assertEqual(open(os.path.join(ROOT, "desktop", "icon", "icon_1024.png"), "rb").read(24)[16:24], b"\x00\x00\x04\x00\x00\x00\x04\x00")   # 1024x1024

    def test_entitlements_are_minimal(self):
        p = plistlib.loads(open(os.path.join(ROOT, "desktop", "entitlements.plist"), "rb").read())
        self.assertFalse([k for k in p if "network" in k or "device" in k or "personal-information" in k], p)

    def test_build_script_has_no_credentials_and_is_valid(self):
        s = read("desktop", "build_macos.sh")
        subprocess.run(["bash", "-n", os.path.join(ROOT, "desktop", "build_macos.sh")], check=True)
        self.assertIn("${SIGN_IDENTITY", s); self.assertIn("${NOTARY_PROFILE", s)
        self.assertNotRegex(s, r"(?i)password|app-specific|BEGIN .*KEY|[A-Z0-9]{10}\)\"")           # no hardcoded identities or secrets
        self.assertIn("NOT notarized", s)                                                          # never claims notarization it did not do
        self.assertFalse([f for f in os.listdir(os.path.join(ROOT, "desktop")) if f.endswith((".p12", ".cer", ".pem", ".key", ".mobileprovision"))])

    def test_menu_commands_and_shortcuts_exist_in_ui(self):
        js = read("ui", "app.js")
        for _, items in dm.MENU:
            for it in items:
                if it:
                    cmd = it[1]
                    self.assertTrue(f'"{cmd}"' in js or (cmd.startswith("go:") and f'"{cmd[3:]}"' in js), cmd)


class DataLocations(unittest.TestCase):
    def test_darwin_defaults_are_user_directories_not_the_bundle(self):
        src = read("app_core.py")
        self.assertIn('"Library", "Application Support", "WorkReceipt"', src); self.assertIn('"Documents", "WorkReceipt Reports"', src)

    def test_legacy_home_is_copied_once_without_demo(self):
        root = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, root, True)
        old, new = os.path.join(root, "old"), os.path.join(root, "new", "WR")
        os.makedirs(os.path.join(old, "demo")); open(os.path.join(old, "settings.json"), "w").write("{}")
        env = dict(os.environ); env.pop("WORKRECEIPT_HOME", None)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(core, "LEGACY_HOME", old), mock.patch.object(core, "HOME_DIR", new):
            self.assertEqual(core._home(), new)
        self.assertTrue(os.path.exists(os.path.join(new, "settings.json"))); self.assertFalse(os.path.exists(os.path.join(new, "demo")))


class PdfExport(unittest.TestCase):
    def setUp(self):
        self.ws = WS(); self.addCleanup(self.ws.done); self.addCleanup(setattr, core, "PDF_BACKEND", None)

    def log(self, cmd):
        self.ws.log([self.ws.user(f"deploy with password={PW}")] + self.ws.bash("c1", cmd, result="ok", err=False))

    def ids(self):
        return {d["id"]: "unsure" for f in self.ws.build()["findings"] for d in f["detections"] if f["severity"] == "high" and not d["suppressed"]}

    def test_backend_gets_only_redacted_html_after_approval(self):
        self.log(f"pytest -q; mysql --password {HI}")
        seen = []
        def backend(html, out):
            seen.append(html); open(out, "wb").write(b"%PDF-1.4 fake")
        core.PDF_BACKEND = backend
        r = core.export({"repo": self.ws.repo, "pdf": True}, {}, {})                  # unresolved high severity: blocked, backend never called
        self.assertFalse(r["ok"]); self.assertEqual(seen, [])
        r = core.export({"repo": self.ws.repo, "pdf": True}, self.ids(), {})
        self.assertTrue(r["ok"]); self.assertTrue(os.path.exists(r["pdf_path"])); self.assertFalse(r["pdf_failed"])
        self.assertEqual(len(seen), 1); self.assertNotIn(HI, seen[0]); self.assertNotIn(PW, seen[0])
        self.assertTrue(core.pdf_available())

    def test_failing_or_empty_backend_keeps_html_and_leaves_no_pdf(self):
        self.log(f"pytest -q; mysql --password {HI}")
        for backend in (lambda h, o: (_ for _ in ()).throw(RuntimeError(HI)), lambda h, o: open(o, "wb").close()):
            core.PDF_BACKEND = backend
            r = core.export({"repo": self.ws.repo, "pdf": True}, self.ids(), {})
            self.assertTrue(r["ok"] and r["pdf_failed"] and r["pdf_path"] is None and os.path.exists(r["html_path"]))
            self.assertFalse(os.path.exists(r["html_path"][:-5] + ".pdf")); self.assertNotIn(HI, json.dumps({k: v for k, v in r.items() if k != "html"}))

    @unittest.skipUnless(core.chrome_path() and shutil.which("pdftotext"), "Chrome + pdftotext needed")
    def test_real_pdf_is_masked(self):
        self.log(f"pytest -q; mysql --password {HI}; curl -u a:{PW} x")
        r = core.export({"repo": self.ws.repo, "pdf": True}, self.ids(), {})
        self.assertTrue(r["ok"] and r["pdf_path"])
        text = subprocess.run(["pdftotext", r["pdf_path"], "-"], capture_output=True, text=True).stdout
        self.assertIn("REDACTED", text); self.assertNotIn(HI, text); self.assertNotIn(PW, text)
        self.assertNotIn(HI, open(r["pdf_path"], "rb").read().decode("latin-1"))


class Errors(unittest.TestCase):
    def test_permission_missing_git_and_unwritable_export(self):
        ws = WS(commits=[("a.py", "init", "10")]); self.addCleanup(ws.done)
        with mock.patch.object(core.os, "access", return_value=False):
            with self.assertRaisesRegex(core.UserError, "permission"): core.add_project(ws.repo)
            with self.assertRaisesRegex(core.UserError, "permission"): core.build({"repo": ws.repo})
        with mock.patch.object(core, "git_ok", return_value=False):
            with self.assertRaisesRegex(core.UserError, "Git is not available"): core.build({"repo": ws.repo})
        with self.assertRaisesRegex(core.UserError, "moved or deleted"): core.build({"repo": os.path.join(ws.root, "gone")})
        blocker = os.path.join(ws.root, "afile"); open(blocker, "w").write("x")
        core.save_settings({"out_dir": os.path.join(blocker, "sub")})
        with self.assertRaisesRegex(core.UserError, "Choose another folder"): core.export({"repo": ws.repo}, {}, {})


class FinderReveal(unittest.TestCase):
    def test_only_files_workreceipt_exported(self):
        ws = WS(); self.addCleanup(ws.done); ws.log([ws.user("add login page")])
        r = core.export({"repo": ws.repo}, {}, {}); self.assertTrue(r["ok"])
        other = os.path.join(ws.root, "other.html"); open(other, "w").write("x")
        with mock.patch.object(dm.sys, "platform", "darwin"), mock.patch.object(dm.subprocess, "run") as run:
            api = dm.Api()
            self.assertFalse(api.reveal(other)); self.assertFalse(api.reveal("/etc/hosts")); self.assertFalse(api.open_report(other)); run.assert_not_called()
            self.assertTrue(api.reveal(r["html_path"])); self.assertEqual(run.call_args[0][0], ["open", "-R", r["html_path"]])
            self.assertTrue(api.open_report(r["html_path"]))


if __name__ == "__main__":
    unittest.main()
