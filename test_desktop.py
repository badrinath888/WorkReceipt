import json, os, unittest, urllib.request, urllib.error
from unittest import mock
from desktop import main as dm


class Shell(unittest.TestCase):
    def test_server_starts_serves_and_stops(self):
        srv, url = dm.start_server()
        self.assertTrue(url.startswith("http://127.0.0.1:"))
        self.assertEqual(urllib.request.urlopen(url).status, 200)
        r = urllib.request.Request(url + "api/settings", data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as c:   # no token => forbidden
            urllib.request.urlopen(r)
        self.assertEqual(c.exception.code, 403)
        dm.stop_server(srv)
        with self.assertRaises(Exception):
            urllib.request.urlopen(url, timeout=1)

    def test_reveal_rejects_unknown_paths(self):
        self.assertFalse(dm.Api().reveal("/etc/passwd"))


class Bridge(unittest.TestCase):
    """Regression: the packaged app's JS bridge never appeared because Api held the pywebview Window as a PUBLIC attribute.
    pywebview (webview/util.py get_functions) recurses into every public non-callable attribute that has __module__."""
    def public_non_callables(self, api):
        return [n for n in dir(api) if not n.startswith("_") and not callable(getattr(api, n))]

    def test_api_exposes_only_methods(self):
        class FakeWindow:                      # stands in for webview.Window: an object with a __module__ and a large graph
            gui = object()
        api = dm.Api(); api._window = FakeWindow()
        self.assertEqual(self.public_non_callables(api), [])
        self.assertTrue({"pick_folder", "reveal", "open_report", "ping"} <= {n for n in dir(api) if callable(getattr(api, n)) and not n.startswith("_")})
        self.assertTrue(api.ping())

    def test_main_stores_window_privately_and_loads_desktop_url(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop", "main.py")).read()
        self.assertIn("api._window = win", src); self.assertNotIn("api.window", src); self.assertIn("?shell=desktop", src)

    def test_pick_folder_returns_path_none_on_cancel_and_raises_on_failure(self):
        import types, sys as _s
        fake = types.SimpleNamespace(FileDialog=types.SimpleNamespace(FOLDER=2), FOLDER_DIALOG=2)
        api = dm.Api()
        with mock.patch.dict(_s.modules, {"webview": fake}):
            api._window = types.SimpleNamespace(create_file_dialog=lambda kind, directory="": ["/tmp/x"])
            self.assertEqual(api.pick_folder(), "/tmp/x")
            api._window = types.SimpleNamespace(create_file_dialog=lambda kind, directory="": None)
            self.assertIsNone(api.pick_folder())
            def boom(kind, directory=""): raise RuntimeError("no window")
            api._window = types.SimpleNamespace(create_file_dialog=boom)
            with self.assertRaises(RuntimeError): api.pick_folder()


if __name__ == "__main__":
    unittest.main()
