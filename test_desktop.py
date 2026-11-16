import json, os, unittest, urllib.request, urllib.error
from unittest import mock
from desktop import main as dm
import workreceipt_app as app
import sys


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
        self.assertFalse(dm.Native().reveal("/etc/passwd")["ok"])


class Bridge(unittest.TestCase):
    """The packaged app no longer depends on the WebView JS bridge: native actions are served over the local HTTP channel."""
    def setUp(self):
        import types
        self.types = types
        self.nat = dm.Native(); self.nat._window = types.SimpleNamespace(create_file_dialog=lambda kind, directory="": ["/tmp/x"]); self.nat._ready.set()

    def fake_webview(self):
        return mock.patch.dict(sys.modules, {"webview": self.types.SimpleNamespace(FileDialog=self.types.SimpleNamespace(FOLDER=2), FOLDER_DIALOG=2, __version__="5.4")})

    def test_no_js_api_and_no_public_state(self):
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "desktop", "main.py")).read()
        self.assertNotIn("js_api", src); self.assertIn("?shell=desktop", src); self.assertIn("run_js", src); self.assertNotIn("evaluate_js", src)
        self.assertEqual([n for n in dir(self.nat) if not n.startswith("_") and not callable(getattr(self.nat, n))], [])

    def test_pick_folder_path_cancel_failure_busy_and_not_ready(self):
        with self.fake_webview():
            self.assertEqual(self.nat.pick_folder(), {"ok": True, "path": "/tmp/x", "cancelled": False})
            self.nat._window = self.types.SimpleNamespace(create_file_dialog=lambda kind, directory="": None)
            self.assertEqual(self.nat.pick_folder(), {"ok": True, "path": None, "cancelled": True})
            def boom(kind, directory=""): raise RuntimeError("secret-detail")
            self.nat._window = self.types.SimpleNamespace(create_file_dialog=boom)
            r = self.nat.pick_folder(); self.assertFalse(r["ok"]); self.assertNotIn("secret-detail", r["error"])
            self.nat._lock.acquire(); self.assertIn("already open", self.nat.pick_folder()["error"]); self.nat._lock.release()
        self.nat._ready.clear(); self.assertIn("starting", self.nat.pick_folder()["error"])

    def test_status_reports_readiness(self):
        with self.fake_webview():
            st = self.nat.status(); self.assertTrue(st["available"]); self.assertEqual(st["pywebview"], "5.4")
            self.nat._ready.clear(); self.assertFalse(self.nat.status()["available"])

    def test_http_endpoints_need_token_and_validate(self):
        import json, urllib.request, urllib.error
        srv, url = dm.start_server(); self.addCleanup(dm.stop_server, srv)
        def post(path, body, tok=True):
            r = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST", headers={"X-WR-Token": app.TOKEN} if tok else {})
            try: return json.load(urllib.request.urlopen(r))
            except urllib.error.HTTPError as e: return {"_code": e.code}
        app.NATIVE = None; self.addCleanup(setattr, app, "NATIVE", None)
        self.assertEqual(post("api/native/status", {}, tok=False), {"_code": 403})
        self.assertFalse(post("api/native/status", {})["available"])
        self.assertFalse(post("api/native/pick_folder", {})["ok"])               # outside the desktop app: clear refusal
        app.NATIVE = self.nat
        with self.fake_webview():
            self.assertEqual(post("api/native/pick_folder", {"start": 5})["path"], "/tmp/x")
        self.assertEqual(post("api/native/open", {"name": 5})["_code"], 400)
        self.assertEqual(post("api/native/open", {"name": "x.html", "kind": "exe"})["_code"], 400)
        self.assertFalse(post("api/native/reveal", {"name": "/etc/passwd"})["ok"])


if __name__ == "__main__":
    unittest.main()
