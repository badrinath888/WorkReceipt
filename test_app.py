import json, os, shutil, subprocess, sys, tempfile, threading, unittest, urllib.error, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app_core as core, workreceipt_app as srv
from http.server import ThreadingHTTPServer


class AppBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples", "make_demo_workspace.py"), cls.root], check=True, capture_output=True)
        os.environ["WORKRECEIPT_CLAUDE_DIR"] = os.path.join(cls.root, "claude")
        os.environ["WORKRECEIPT_HOME"] = os.path.join(cls.root, "home")
        cls.repo = os.path.join(cls.root, "acme-storefront")
        cls.out = os.path.join(cls.root, "out")
        core.save_settings({"out_dir": cls.out})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)


class Core(AppBase):
    def test_discover(self):
        ps = core.discover(core.load_settings()["claude_dir"])
        self.assertEqual({p["name"] for p in ps}, {"acme-storefront", "northwind-api"})
        self.assertTrue(all(p["git"] and p["exists"] for p in ps))

    def test_findings_never_contain_values(self):
        b = core.build({"repo": self.repo})
        blob = json.dumps(core.summary(b))
        self.assertNotIn("AKIAQWERTYUIOPASDFGH", blob)
        self.assertNotIn("jane@example.com", blob)
        self.assertEqual([f["severity"] for f in b["findings"]].count("high"), 1)

    def test_summary_matches_engine(self):
        s = core.summary(core.build({"repo": self.repo}))
        self.assertEqual((len(s["requests"]), s["n_commits"], s["n_checks"]), (6, 5, 5))

    def test_export_blocked_until_reviewed(self):
        r = core.export({"repo": self.repo}, [], {})
        self.assertFalse(r["ok"]); self.assertEqual(r["error"], "review_required")
        self.assertFalse(os.path.isdir(self.out) and os.listdir(self.out))
        ids = {d["id"]: "unsure" for f in core.build({"repo": self.repo})["findings"] if f["severity"] == "high" for d in f["detections"]}
        key = core.build({"repo": self.repo})["ctx"]["items"][5]["key"]
        r = core.export({"repo": self.repo}, ids, {key: "Edited title AKIAQWERTYUIOPASDFGH"})
        self.assertTrue(r["ok"])
        html = open(r["html_path"]).read()
        self.assertIn("Edited title", html); self.assertNotIn("AKIA", html); self.assertNotIn("jane@", html)

    def test_custom_term_is_high_and_masked(self):
        b = core.build({"repo": self.repo, "terms": ["storefront"]})
        self.assertTrue(any(f["rule"] == "custom term" for f in b["findings"]))
        self.assertNotIn("storefront", core.render_preview({"repo": self.repo, "terms": ["storefront"]}, {}).lower().replace("[redacted:custom]", ""))

    def test_errors(self):
        with self.assertRaises(ValueError): core.build({"repo": "/nonexistent/zzz"})
        with self.assertRaises(ValueError): core.build({"repo": self.repo, "since": "2026-02-01", "until": "2026-01-01"})
        with self.assertRaises(ValueError): core.build({"repo": self.repo, "since": "garbage"})


class Server(AppBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.s = ThreadingHTTPServer(("127.0.0.1", 0), srv.H)
        cls.port = cls.s.server_address[1]
        threading.Thread(target=cls.s.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.s.shutdown(); super().tearDownClass()

    def req(self, path, body=None, token=True, host=None):
        h = {"X-WR-Token": srv.TOKEN} if token else {}
        if host: h["Host"] = host
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", None if body is None else json.dumps(body).encode(), h)
        try:
            return urllib.request.urlopen(r)
        except urllib.error.HTTPError as e:
            return e

    def test_security(self):
        self.assertEqual(self.req("/api/preview", {"repo": self.repo}, token=False).code, 403)
        self.assertEqual(self.req("/", host="evil.example").code, 403)
        self.assertEqual(self.req("/report/..%2f..%2fetc%2fpasswd").code, 404)
        self.assertEqual(self.req("/..%2fapp_core.py").code, 404)

    def test_api(self):
        self.assertEqual(json.load(self.req("/api/state"))["claude_dir_ok"], True)
        self.assertIn(b"CSP", b"CSP" if self.req("/").headers["Content-Security-Policy"] else b"")
        j = json.load(self.req("/api/preview", {"repo": self.repo}))
        self.assertEqual(j["n_commits"], 5)
        e = self.req("/api/export", {"repo": self.repo, "approved": []})
        self.assertEqual(e.code, 409)
        self.assertEqual(self.req("/api/preview", {"repo": "/nope"}).code, 400)


if __name__ == "__main__":
    unittest.main()
