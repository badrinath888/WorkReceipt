"""Build identity: a packaged .app built before a fix must be recognised as stale even though its version number is unchanged.
(The macOS run: the source app exported, the packaged .app was refused with validation ['metadata'] - consistent with an app built before the
metadata fix, but nothing in the harness could say which source it contained. VERSION alone cannot: it did not change between those builds.)"""
import json, os, shutil, stat, subprocess, sys, tempfile, textwrap, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import app_core as core, buildinfo as bi


def copy_runtime(dst):
    for rel in bi.runtime_paths(HERE):
        os.makedirs(os.path.dirname(os.path.join(dst, rel)), exist_ok=True)
        shutil.copyfile(os.path.join(HERE, rel), os.path.join(dst, rel))


def fake_app(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + textwrap.dedent(body))
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


class Fingerprint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        copy_runtime(self.tmp)

    def test_stable_and_matches_the_checkout(self):
        self.assertEqual(bi.source_fingerprint(self.tmp), bi.source_fingerprint(HERE))
        self.assertEqual(bi.source_fingerprint(HERE), bi.source_fingerprint(HERE))

    def test_any_runtime_code_change_changes_it(self):
        base = bi.source_fingerprint(self.tmp)
        for rel in ("client_safe.py", "app_core.py", "desktop/pdf_mac.py", "ui/app.js", "ui/index.html"):
            p = os.path.join(self.tmp, rel); old = open(p, "rb").read()
            open(p, "ab").write(b"\n# changed\n")
            with self.subTest(rel):
                self.assertNotEqual(bi.source_fingerprint(self.tmp), base)
            open(p, "wb").write(old)
        self.assertEqual(bi.source_fingerprint(self.tmp), base)

    def test_docs_and_tests_do_not_change_it(self):
        base = bi.source_fingerprint(self.tmp)
        open(os.path.join(self.tmp, "README.md"), "w").write("docs"); open(os.path.join(self.tmp, "test_x.py"), "w").write("pass")
        self.assertEqual(bi.source_fingerprint(self.tmp), base)

    def test_missing_runtime_file_gives_none(self):
        os.remove(os.path.join(self.tmp, "client_safe.py"))
        self.assertIsNone(bi.source_fingerprint(self.tmp))


class Compare(unittest.TestCase):
    def test_current_stale_and_unidentifiable(self):
        fp = bi.source_fingerprint(HERE)
        self.assertTrue(bi.compare(bi.current(core.VERSION), fp)[0])
        same_version_old_code = dict(bi.current(core.VERSION), fingerprint="0" * 64)           # the real case: version identical, code older
        ok, msg = bi.compare(same_version_old_code, fp)
        self.assertFalse(ok); self.assertIn("different source", msg)
        for none in (None, {}, "garbage", {"version": core.VERSION}, {"fingerprint": "unknown"}, {"fingerprint": ""}):
            with self.subTest(repr(none)):
                self.assertFalse(bi.compare(none, fp)[0])


class Reporting(unittest.TestCase):
    def test_source_run_reports_live_source_and_state_route_carries_it(self):
        b = core.build_info()
        self.assertEqual(b["fingerprint"], bi.source_fingerprint(HERE)); self.assertEqual(b["version"], core.VERSION); self.assertEqual(b["source"], "source checkout")
        import threading
        from http.server import ThreadingHTTPServer
        import urllib.request, workreceipt_app as app
        srv = ThreadingHTTPServer(("127.0.0.1", 0), app.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        s = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/api/state" % srv.server_address[1]).read())
        self.assertEqual(s["build"]["fingerprint"], b["fingerprint"])

    def test_packaged_app_reports_what_was_baked_in_not_its_live_files(self):
        fake = mock.MagicMock(FINGERPRINT="a" * 64, GIT="abc1234", DIRTY=False, BUILT_AT="2026-11-17T09:00:00")
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.dict(sys.modules, {"_build_info": fake}):
            got = bi.current("9.9.9")
        self.assertEqual((got["fingerprint"], got["git"], got["source"]), ("a" * 64, "abc1234", "packaged build"))
        self.assertFalse(bi.compare(got, bi.source_fingerprint(HERE))[0])                     # baked from other source -> stale

    def test_packaged_app_without_build_identity_never_matches(self):
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.dict(sys.modules, {"_build_info": None}):
            got = bi.current("9.9.9")
        self.assertEqual(got["fingerprint"], "unknown"); self.assertFalse(bi.compare(got, bi.source_fingerprint(HERE))[0])

    def test_baked_file_round_trips_and_is_git_ignored(self):
        tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, tmp, True)
        path = bi.write_baked("1.2.3", HERE, os.path.join(tmp, "_build_info.py"))
        ns = {}; exec(open(path).read(), ns)
        self.assertEqual(ns["FINGERPRINT"], bi.source_fingerprint(HERE)); self.assertEqual(ns["VERSION"], "1.2.3")
        self.assertIn("_build_info.py", open(os.path.join(HERE, ".gitignore")).read().split())

    def test_build_info_flag_prints_and_writes_without_opening_a_window(self):
        out = os.path.join(tempfile.mkdtemp(), "bi.json"); self.addCleanup(shutil.rmtree, os.path.dirname(out), True)
        r = subprocess.run([sys.executable, os.path.join(HERE, "desktop", "main.py"), "--build-info", out], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.load(open(out)), json.loads(r.stdout.strip().splitlines()[-1]))
        self.assertEqual(json.load(open(out))["fingerprint"], bi.source_fingerprint(HERE))


class AppCheck(unittest.TestCase):
    """buildinfo.check_app / `buildinfo.py check-app`, which the build script and the validation harness use on dist/WorkReceipt.app."""
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cur = json.dumps(bi.current(core.VERSION))

    def app(self, body):
        return fake_app(os.path.join(self.tmp, "app.sh"), body)

    def test_current_app_passes(self):
        ok, msg, got = bi.check_app(self.app(f'echo \'{self.cur}\' > "$2"\n'), HERE, timeout=10)
        self.assertTrue(ok, msg)

    def test_stale_app_with_the_same_version_is_refused_with_rebuild_instructions(self):
        old = json.dumps(dict(json.loads(self.cur), fingerprint="1" * 64, git="3f2c1ab"))
        p = self.app(f'echo \'{old}\' > "$2"\n')
        ok, msg, got = bi.check_app(p, HERE, timeout=10)
        self.assertFalse(ok); self.assertIn("different source", msg); self.assertEqual(got["version"], core.VERSION)
        r = subprocess.run([sys.executable, os.path.join(HERE, "buildinfo.py"), "check-app", p], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1); self.assertIn("STALE", r.stdout); self.assertIn("desktop/build_macos.sh", r.stdout)

    def test_app_that_predates_the_flag_is_stale_and_is_killed(self):
        import time
        t0 = time.time()
        ok, msg, got = bi.check_app(self.app("sleep 60\n"), HERE, timeout=2)                      # an old app ignores --build-info and just runs
        self.assertFalse(ok); self.assertIsNone(got); self.assertLess(time.time() - t0, 20)
        self.assertIn("predates build identity", msg)

    def test_unreadable_or_crashing_app_is_not_current(self):
        for body in ("exit 3\n", 'echo not-json > "$2"\n', 'echo \'{"fingerprint": 5}\' > "$2"\n'):
            with self.subTest(body):
                self.assertFalse(bi.check_app(self.app(body), HERE, timeout=5)[0])


class WiredIn(unittest.TestCase):
    def read(self, *p):
        return open(os.path.join(HERE, *p), encoding="utf-8").read()

    def test_build_script_bakes_checks_and_cleans_up(self):
        s = self.read("desktop", "build_macos.sh")
        self.assertIn("buildinfo.py bake", s); self.assertIn("check-app", s); self.assertIn("_build_info.py", s)
        self.assertLess(s.index("buildinfo.py bake"), s.index("pyinstaller")); self.assertLess(s.index("pyinstaller"), s.index("check-app"))
        self.assertLess(s.index("check-app"), s.index("codesign --force --deep")); self.assertLess(s.index("check-app"), s.index("hdiutil create"))
        self.assertIn('rm -rf build dist', s)                                                      # a rebuild is always clean

    def test_harness_refuses_a_stale_packaged_app_and_does_not_launch_it(self):
        s = self.read("scripts", "macos_app.py")
        self.assertIn("check_app", s); self.assertIn("STALE packaged app", s); self.assertIn('is_current', s.replace("packaged_is_current", "is_current"))
        self.assertIn('compare(s.get("build")', s)                                                 # the RUNNING app's own report is compared too
        self.assertLess(s.index("packaged_is_current()") if "packaged_is_current()" in s else s.index("def packaged_is_current"), s.index('run_app("packaged app"'))
        self.assertIn("packaged app:", self.read("scripts", "validate_macos.sh"))                  # report header says current / STALE / not built

    def test_spec_bundles_the_build_identity_modules(self):
        s = self.read("desktop", "WorkReceipt.spec")
        self.assertIn('"buildinfo"', s); self.assertIn('"_build_info"', s)


if __name__ == "__main__":
    unittest.main()
