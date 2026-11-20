"""Regression for the Mac failure "RuntimeError: Reload of objc._objc detected, this is not supported" (7 failures, 2 required PDF security tests).
Root cause: tests used mock.patch.dict(sys.modules, ...). Its exit restores a snapshot of sys.modules, which EVICTS every module first imported inside the block;
on a Mac the code under test imports the real PyObjC there, so the next `import objc` re-ran a C extension that cannot be loaded twice.
A fake extension that, like objc._objc, refuses a second execution reproduces it on any OS."""
import glob, importlib, os, sys, tempfile, textwrap, unittest
from unittest import mock
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from testsupport import modules_patched

EXT = textwrap.dedent('''
    import builtins
    if getattr(builtins, "_fake_objc_loaded", False):
        raise RuntimeError("Reload of fake_objc_ext detected, this is not supported")
    builtins._fake_objc_loaded = True
    VALUE = 1
''')


class NonReloadableExtension(unittest.TestCase):
    def setUp(self):
        import builtins
        self.d = tempfile.mkdtemp(); open(os.path.join(self.d, "fake_objc_ext.py"), "w").write(EXT)
        sys.path.insert(0, self.d)
        builtins.__dict__.pop("_fake_objc_loaded", None); sys.modules.pop("fake_objc_ext", None)
        def clean():
            sys.path.remove(self.d); sys.modules.pop("fake_objc_ext", None); builtins.__dict__.pop("_fake_objc_loaded", None)
        self.addCleanup(clean)

    def test_the_old_pattern_reproduces_the_mac_error(self):
        with mock.patch.dict(sys.modules, {"Quartz": object()}):
            importlib.import_module("fake_objc_ext")                      # the code under test imports the native module inside the block
        self.assertNotIn("fake_objc_ext", sys.modules)                    # ... and the snapshot restore evicted it
        with self.assertRaisesRegex(RuntimeError, "Reload of"):
            importlib.import_module("fake_objc_ext")

    def test_modules_patched_keeps_modules_imported_inside_the_block(self):
        with modules_patched({"Quartz": object()}):
            first = importlib.import_module("fake_objc_ext")
        self.assertIs(importlib.import_module("fake_objc_ext"), first)    # no reload

    def test_modules_patched_restores_exactly_what_it_changed(self):
        real = object(); sys.modules["wr_fake_a"] = real; self.addCleanup(sys.modules.pop, "wr_fake_a", None)
        sys.modules.pop("wr_fake_b", None)
        fake = object()
        with modules_patched({"wr_fake_a": fake, "wr_fake_b": fake, "wr_fake_c": None}):
            self.assertIs(sys.modules["wr_fake_a"], fake); self.assertIsNone(sys.modules["wr_fake_c"])
        self.assertIs(sys.modules["wr_fake_a"], real)
        self.assertNotIn("wr_fake_b", sys.modules); self.assertNotIn("wr_fake_c", sys.modules)

    def test_restores_even_when_the_block_raises(self):
        sys.modules.pop("wr_fake_d", None)
        with self.assertRaises(ValueError), modules_patched({"wr_fake_d": object()}):
            raise ValueError("boom")
        self.assertNotIn("wr_fake_d", sys.modules)


class NoSnapshotPatchingAnywhere(unittest.TestCase):
    def test_no_test_or_script_uses_patch_dict_on_sys_modules(self):
        bad = []
        for p in glob.glob(os.path.join(HERE, "*.py")) + glob.glob(os.path.join(HERE, "scripts", "*.py")) + glob.glob(os.path.join(HERE, "desktop", "*.py")):
            if os.path.basename(p) in (os.path.basename(__file__), "testsupport.py"):      # these two only describe the pattern
                continue
            src = open(p, encoding="utf-8").read()
            if "patch.dict(sys.modules" in src or "patch.dict('sys.modules'" in src or 'patch.dict("sys.modules"' in src:
                bad.append(os.path.relpath(p, HERE))
        self.assertEqual(bad, [], "use testsupport.modules_patched: patch.dict(sys.modules) evicts natively imported modules (PyObjC cannot be reloaded)")


if __name__ == "__main__":
    unittest.main()
