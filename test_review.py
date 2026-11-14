"""Privacy Center review workflow: per-detection review, local-only reveal, no leakage. SYNTHETIC values only."""
import json, os, random, sys, threading, unittest, urllib.error, urllib.request
from collections import Counter
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app_core as core, workreceipt as w, workreceipt_app as srv
from test_phase1 import WS, AKIA, GH, disp

V1, V2, V3, V4 = "dummyvalue-one-111", "dummyvalue-two-222", "changeme", "zzzz-test-4444"
HEREDOC = (f"cat > test_bridge.py <<'EOF'\nPASSWORD = \"{V1}\"\napi_key='{V2}'\nx = 1\nclient_secret: {V3}hello\nTOKEN={V4}\nEOF\npytest -q")
LEAKS = (V1, V2, V3 + "hello", V4, AKIA, GH)


def hi(b):
    return [f for f in b["findings"] if f["severity"] == "high"]


class Detect(unittest.TestCase):
    def setUp(self):
        self.ws = WS(); self.addCleanup(self.ws.done)

    def test_group_is_itemised_with_locations(self):
        self.ws.log(self.ws.bash("c1", HEREDOC, result="ok", err=False))
        b = self.ws.build()
        g = [f for f in hi(b) if f["rule"] == "secret assignment"]
        self.assertEqual(len(g), 1)
        g = g[0]
        self.assertEqual((g["count"], len(g["detections"]), g["itemised"]), (4, 4, True))
        self.assertEqual([d["line"] for d in g["detections"]], [2, 3, 5, 6])
        self.assertEqual([d["n"] for d in g["detections"]], [1, 2, 3, 4])
        self.assertEqual(len({d["id"] for d in g["detections"]}), 4)
        for d in g["detections"]:
            self.assertEqual(d["lines"], 8)
            self.assertFalse(d["in_report"])                      # lines 2+ of a command are never printed in the report
            hit = [l for l in d["context"] if l["hit"]]
            self.assertEqual(len(hit), 1)
            self.assertIn("[REDACTED:secret]", "".join(t for k, t in hit[0]["segs"] if k == "hl"))

    def test_report_matches_what_review_says(self):
        self.ws.log(self.ws.bash("c1", HEREDOC, result="ok", err=False))
        r = core.export({"repo": self.ws.repo}, disp(self.ws.build()["findings"]), {})
        self.assertTrue(r["ok"])
        for v in LEAKS:
            self.assertNotIn(v, r["html"])

    def test_first_line_secret_is_flagged_in_report(self):
        self.ws.log(self.ws.bash("c1", f"export TOKEN={V4} && pytest", result="ok", err=False))
        d = hi(self.ws.build())[0]["detections"][0]
        self.assertTrue(d["in_report"])

    def test_duplicate_values_are_separate_detections(self):
        self.ws.log([self.ws.user(f"a password={V1} and again password={V1}")])
        d = hi(self.ws.build())[0]["detections"]
        self.assertEqual(len(d), 2)
        self.assertNotEqual(d[0]["id"], d[1]["id"])
        self.assertEqual([x["same_value_elsewhere"] for x in d], [1, 1])
        self.assertEqual(len(core.export({"repo": self.ws.repo}, {d[0]["id"]: "unsure"}, {}).get("missing", [])), 1)   # one review is not both

    def test_placeholder_looking_values_still_need_review(self):
        self.ws.log([self.ws.user("password=changeme123 and api_key=your_api_key_here and token=EXAMPLE_TOKEN_00")])
        b = self.ws.build()
        det = [d for f in hi(b) for d in f["detections"]]
        self.assertEqual(len(det), 3)
        self.assertFalse(core.export({"repo": self.ws.repo}, {}, {})["ok"])
        self.assertFalse(core.export({"repo": self.ws.repo}, {det[0]["id"]: "not_credential"}, {})["ok"])
        self.assertTrue(core.export({"repo": self.ws.repo}, disp(b["findings"], "not_credential"), {})["ok"])

    def test_changed_value_invalidates_review(self):
        self.ws.log([self.ws.user(f"password={V1}")])
        old = disp(self.ws.build()["findings"])
        self.ws.log([self.ws.user(f"password={V2}")])
        r = core.export({"repo": self.ws.repo}, old, {})
        self.assertFalse(r["ok"]); self.assertEqual(len(r["missing"]), 1)

    def test_every_disposition_keeps_value_masked(self):
        self.ws.log([self.ws.user(f"password={V1}")])
        for v in core.DISPOSITIONS:
            r = core.export({"repo": self.ws.repo}, disp(self.ws.build()["findings"], v), {})
            self.assertTrue(r["ok"]); self.assertNotIn(V1, r["html"])

    def test_list_or_garbage_payloads_do_not_approve(self):
        self.ws.log([self.ws.user(f"password={V1}")])
        i = hi(self.ws.build())[0]["detections"][0]["id"]
        for bad in ([i], None, "x", {i: True}, {i: "approved"}, {i: ["unsure"]}):
            self.assertFalse(core.export({"repo": self.ws.repo}, bad, {})["ok"], bad)

    def test_counts_and_reconstruction_match_engine(self):
        rnd = random.Random(7)
        parts = [f"password={V1}", f"key {AKIA}", f"token {GH}", "mail a.b@example.com", "/Users/jane/proj/x.py", "10.1.2.3",
                 f"https://u:pw12345@host.test/x", "plain words", f"secret: '{V2}'", "Bearer abcdef0123456789abcdef0123456789",
                 "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop", "A8f3Kd92Lx0Qw7Zp1Vb6Nm4Rt5Yh2Uc9"]
        for _ in range(300):
            t = "\n".join(" ".join(rnd.sample(parts, rnd.randint(1, 5))) for _ in range(rnd.randint(1, 4)))
            r = w.Redactor(["acme"]); masked = r(t)
            m, fs, vals = core._findings("Check", 0, t + " acme", ["acme"], "Check 1")
            r2 = w.Redactor(["acme"]); self.assertEqual(m, r2(t + " acme"))
            self.assertEqual(sum(f["count"] for f in fs), sum(r2.hits.values()))
            for f in fs:
                self.assertEqual(r2.hits[(f["rule"], f["severity"])], f["count"])
                if f["itemised"] and f["severity"] == "high":
                    self.assertEqual(len(f["detections"]), f["count"])
            for did, val in vals.items():
                self.assertIn(val, t + " acme")

    def test_oversized_text_is_reviewed_as_one_unit(self):
        big = f"password={V1} " + "x " * (core.MAX_ITEMISE // 2 + 10)
        m, fs, vals = core._findings("Check", 0, big, [], "Check 1")
        g = [f for f in fs if f["severity"] == "high"][0]
        self.assertFalse(g["itemised"]); self.assertEqual(len(g["detections"]), 1); self.assertEqual(vals, {})
        self.assertNotIn(V1, json.dumps(fs))

    def test_missing_original_file(self):
        ws = self.ws
        ws.log([ws.user(f"password={V2}")])
        i = hi(ws.build())[0]["detections"][0]["id"]
        os.remove(os.path.join(ws.d, "s.jsonl"))                                   # the source log is gone
        with self.assertRaises(core.NotFound): core.reveal({"repo": ws.repo}, i)
        self.assertEqual(hi(ws.build()), [])
        self.assertTrue(core.export({"repo": ws.repo}, {i: "unsure"}, {})["ok"])    # stale reviews are ignored, nothing left to block

    def test_changed_source_value_is_not_revealable_under_old_id(self):
        ws = self.ws
        ws.log([ws.user(f"password={V1}")]); i = hi(ws.build())[0]["detections"][0]["id"]
        ws.log([ws.user(f"password={V2}")])
        with self.assertRaises(core.NotFound): core.reveal({"repo": ws.repo}, i)


class Reveal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = WS(); cls.ws.log(cls.ws.bash("c1", HEREDOC, result="ok", err=False) + [cls.ws.user(f"deploy with {AKIA}")])
        cls.s = ThreadingHTTPServer(("127.0.0.1", 0), srv.H); cls.port = cls.s.server_address[1]
        threading.Thread(target=cls.s.serve_forever, daemon=True).start()
        cls.ids = [d["id"] for f in hi(cls.ws.build()) for d in f["detections"]]

    @classmethod
    def tearDownClass(cls):
        cls.s.shutdown(); cls.ws.done()

    def req(self, path, body=None, token=True):
        h = {"X-WR-Token": srv.TOKEN} if token else {}
        try:
            r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", None if body is None else json.dumps(body).encode(), h))
            return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def reveal(self, i, **k):
        return self.req("/api/reveal", dict({"repo": self.ws.repo, "id": i, "confirm": True}, **k))

    def test_reveal_returns_one_value_only_when_asked(self):
        got = {}
        for i in self.ids:
            code, body, h = self.reveal(i)
            self.assertEqual(code, 200); self.assertIn("no-store", h["Cache-Control"])
            self.assertEqual(sum(v in body.decode() for v in LEAKS), 1)          # exactly one value per response
            got[i] = json.loads(body)["value"].strip("\"'")
        self.assertEqual(sorted(got.values()), sorted([V1, V2, V3 + "hello", V4, AKIA]))

    def test_reveal_requires_token_and_confirmation(self):
        self.assertEqual(self.req("/api/reveal", {"repo": self.ws.repo, "id": self.ids[0], "confirm": True}, token=False)[0], 403)
        for c in (None, False, "true", 1):
            code, body, _ = self.reveal(self.ids[0], confirm=c)
            self.assertEqual(code, 400); self.assertNotIn(V1.encode(), body)
        self.assertEqual(self.req(f"/api/reveal?id={self.ids[0]}")[0], 404)         # no GET reveal

    def test_unknown_or_malformed_ids(self):
        for i in ("nope", "", None, 5, ["x"], "a" * 500):
            code, body, _ = self.reveal(i)
            self.assertEqual(code, 404, i)

    def test_ordinary_responses_never_contain_values(self):
        for path, b in (("/api/preview", {"repo": self.ws.repo}), ("/api/render", {"repo": self.ws.repo}),
                        ("/api/export", {"repo": self.ws.repo}), ("/api/export", {"repo": self.ws.repo, "approved": {i: "unsure" for i in self.ids}})):
            code, body, _ = self.req(path, b)
            for v in LEAKS:
                self.assertNotIn(v, body.decode(), path)
        self.reveal(self.ids[0])
        code, body, _ = self.req("/api/state")
        for v in LEAKS:
            self.assertNotIn(v, body.decode())
        for fn in (core.load_settings(), core.history()):
            for v in LEAKS:
                self.assertNotIn(v, json.dumps(fn))
        for root, _, files in os.walk(os.environ["WORKRECEIPT_HOME"]):
            for f in files:
                data = open(os.path.join(root, f), errors="ignore", encoding="utf-8").read()
                for v in LEAKS:
                    self.assertNotIn(v, data, f)

    def test_errors_never_echo_values(self):
        orig = core.build
        def boom(*a, **k): raise RuntimeError(f"failed near password={V1}")
        core.build = boom
        try:
            for path in ("/api/preview", "/api/render", "/api/export", "/api/reveal"):
                code, body, _ = self.req(path, {"repo": self.ws.repo, "id": "x", "confirm": True})
                self.assertEqual(code, 500); self.assertNotIn(V1, body.decode()); self.assertNotIn("RuntimeError", body.decode())
        finally:
            core.build = orig


if __name__ == "__main__":
    unittest.main()
