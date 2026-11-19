"""Script-run PDFs must carry Creator == the product name: pdf_mac stamps CFBundleName (the source of Creator) with the fixed constant.
Linux-safe: Foundation is faked. The real WKWebView result is checked on the Mac by scripts/validate_macos.sh (approve-and-export stages)."""
import os, sys, types, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path[:0] = [HERE, os.path.join(HERE, "desktop")]
import client_safe as cs, pdf_mac


def fake_foundation(info):
    m = types.ModuleType("Foundation")
    m.NSBundle = types.SimpleNamespace(mainBundle=lambda: types.SimpleNamespace(infoDictionary=lambda: info))
    return m


class Stamp(unittest.TestCase):
    def run_with(self, info):
        old = sys.modules.get("Foundation"); sys.modules["Foundation"] = fake_foundation(info)
        try: pdf_mac._stamp_creator()
        finally:
            if old is None: del sys.modules["Foundation"]
            else: sys.modules["Foundation"] = old

    def test_python_host_is_renamed_to_the_exact_product_name(self):
        info = {"CFBundleName": "Python"}; self.run_with(info)
        self.assertEqual(info["CFBundleName"], cs.PRODUCT_NAME)

    def test_read_only_bundle_info_never_raises(self):
        from types import MappingProxyType
        self.run_with(MappingProxyType({"CFBundleName": "Python"}))

    def test_allowlist_still_refuses_python(self):
        self.assertFalse(cs._PRODUCER_OK.match("Python")); self.assertNotEqual("Python", cs.PRODUCT_NAME)


if __name__ == "__main__":
    unittest.main()
