"""Automated privacy analysis: false-positive reduction that never clears a possibly-real credential. SYNTHETIC values only."""
import json, os, random, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app_core as core, workreceipt as w
from test_phase1 import WS, GH, AKIA, disp

REAL_Q = "Xk9#mQ2$vL7!pR4z-Qw8"
REAL_U = "Xk9mQ2vL7pR4zT"
# The shape that produced the four detections: keyword arguments / subscripts in Python test code.
BRIDGE = ("cat > test_bridge.py <<'EOF'\nimport pytest\nfrom bridge import verify, login\n\n"
          "def test_auth(tok, pw, secret_key):\n    ok = verify(token=tok)[0]\n    assert login(password=pw)[0]\n"
          "    r = login(secret=secret_key)[1]\n    assert verify(auth_token=tok)[0] == 1\nEOF\npytest -q")


def cls(text, rule="secret assignment"):
    m, fs, vals = core._findings("Check", 0, text, [], "Check 1")
    return [d for f in fs if f["severity"] == "high" for d in f["detections"]], vals, fs


class RootCause(unittest.TestCase):
    def test_scanner_span_for_the_reported_fragment(self):
        r = w.Redactor(); r("ok = verify(token=tok)[0]")
        dets, vals, _ = cls("ok = verify(token=tok)[0]")
        self.assertEqual(list(vals.values()), ["tok)[0]"])             # the exact fragment the user saw: kwarg value plus closing syntax
        self.assertEqual(dets[0]["class"]["category"], "code_fragment")

    def test_bridge_example_is_cleared_and_report_still_masks(self):
        dets, vals, _ = cls(BRIDGE)
        self.assertEqual(len(dets), 4)
        self.assertTrue(all(d["suppressed"] for d in dets), [d["class"]["category"] for d in dets])
        self.assertTrue(all(d["class"]["confidence"] in ("rule-proven", "high") and d["class"]["evidence"] for d in dets))
        ws = WS(); self.addCleanup(ws.done)
        ws.log(ws.bash("c1", BRIDGE, result="ok", err=False))
        b = ws.build()
        g = [f for f in b["findings"] if f["rule"] == "secret assignment"][0]
        self.assertEqual((g["count"], g["actionable"], g["cleared"]), (4, 0, 4))
        r = core.export({"repo": ws.repo}, {}, {})                      # nothing left for a human: export is allowed
        self.assertTrue(r["ok"])
        self.assertNotIn("tok)[0]", r["html"]); self.assertNotIn("pw)[0]", r["html"])      # still masked, nothing unmasked by clearing


class GenuineSecretsStillBlock(unittest.TestCase):
    def setUp(self):
        self.ws = WS(); self.addCleanup(self.ws.done)

    def blocked(self, cmd):
        self.ws.log(self.ws.bash("c1", cmd, result="ok", err=False))
        b = self.ws.build()
        ids = [d["id"] for f in b["findings"] for d in f["detections"] if f["severity"] == "high" and not d["suppressed"]]
        self.assertTrue(ids, "expected a detection that needs review")
        r = core.export({"repo": self.ws.repo}, {}, {})
        self.assertFalse(r["ok"]); self.assertEqual(sorted(r["missing"]), sorted(ids))
        self.assertTrue(core.export({"repo": self.ws.repo}, {i: "unsure" for i in ids}, {})["ok"])
        return b

    def test_real_credential_inside_test_code(self):
        for secret in (f'client.login(token="{GH}")', f'assert verify(password="{REAL_Q}")[0]', f"assert login(password={REAL_U})[0]",
                       f"API_KEY={REAL_U}", f"cfg = dict(client_secret='{REAL_Q}')", f"aws = '{AKIA}'"):
            with self.subTest(secret=secret):
                self.blocked("cat > test_real.py <<'EOF'\ndef test_x(tok):\n    ok = verify(token=tok)[0]\n    " + secret + "\nEOF\npytest")

    def test_mixed_group_clears_only_the_harmless_ones(self):
        b = self.blocked(BRIDGE + f"\npython -c \"login(password={REAL_U})[0]\"")
        g = [f for f in b["findings"] if f["rule"] == "secret assignment"][0]
        self.assertEqual((g["count"], g["cleared"], g["actionable"]), (5, 4, 1))

    def test_hostile_values_are_not_cleared(self):
        for t in ("password=s3cr3t)[0]", "password=hunter2)", "token=abc[Xk9mQ2vL7pR4zT]", "password=Passw0rd(1)", "token = mytoken123.xyz",
                  "secret=$Xk9mQ2vL7pR4zT", "secret=$TOKEN12345", "password=config", "password=${", "key=abc)Xk9mQ2vL7pR4zT",
                  "api_key=get_Token(Xk9mQ2vL7)", "password=self", "f(password=correct_horse_staple_9a)x", "password=correct_horse_staple)", "login(password=hunter2hunter2)", "login(password=Xk9mQ2vL7pR4zT)[0]", "login(pw=a_b_c_d)[0]) ) )"):
            for d in cls(t)[0]:
                self.assertFalse(d["suppressed"], t)

    def test_dummy_looking_values_are_labelled_but_never_cleared(self):
        dets, _, _ = cls("password='dummy-password-1' api_key=xxxxxxxxxx token=\"your_api_key_here\" secret=changeme123")
        self.assertEqual(len(dets), 4)
        for d in dets:
            self.assertFalse(d["suppressed"])
            self.assertIn(d["class"]["category"], ("likely_dummy", "test_fixture"))
            self.assertNotEqual(d["class"]["confidence"], "rule-proven")
        d = cls("cat > test_x.py <<'EOF'\npassword='dummy-password-1'\nEOF")[0][0]
        self.assertEqual((d["class"]["category"], d["suppressed"]), ("test_fixture", False))

    def test_variable_name_never_decides(self):
        for name in ("token", "password", "api_key", "my_secret_value", "auth_key", "PASSWORD"):
            self.assertTrue(cls(f"{name}=tok)[0]")[0][0]["suppressed"], name)
            self.assertFalse(cls(f"{name}=s3cr3t)[0]")[0][0]["suppressed"], name)
            self.assertFalse(cls(f"{name}='{REAL_Q}'")[0][0]["suppressed"], name)

    def test_provider_formats_and_published_examples(self):
        a = cls(f"k={GH}")[0][0]; self.assertEqual((a["class"]["category"], a["suppressed"]), ("known_format", False))
        self.assertTrue(cls("k=AKIAIOSFODNN7EXAMPLE")[0][0]["suppressed"])                  # AWS documentation constant
        self.assertFalse(cls("k=AKIAIOSFODNN7EXAMPLF")[0][0]["suppressed"])                  # one character off: not the published value
        self.assertFalse(cls(f"k={AKIA}")[0][0]["suppressed"])

    def test_custom_terms_always_need_review(self):
        m, fs, _ = core._findings("Check", 0, "deploy acme now", ["acme"], "Check 1")
        d = fs[0]["detections"][0]; self.assertFalse(d["suppressed"]); self.assertEqual(d["class"]["category"], "custom_term")

    def test_suppressed_iff_rule_proven(self):
        rnd = random.Random(3)
        bits = ["token=tok)[0]", f"password={REAL_U}", "x=self.token", f"k={GH}", "secret=get_token()", "password='dummy-1234'", "auth_key=$MY_TOKEN",
                f"api_key='{REAL_Q}'", "pw=os.environ[", "token=\"<your-token>\"", "password=abcdefg", "token=x(y)[0]"]
        for _ in range(200):
            dets, _, _ = cls(" ; ".join(rnd.sample(bits, rnd.randint(1, 6))))
            for d in dets:
                c = d["class"]
                self.assertEqual(d["suppressed"], c["suppressed"])
                self.assertEqual(c["suppressed"], c["confidence"] in ("rule-proven", "high"), c)
                self.assertEqual(c["suppressed"], c["category"] in core.SUPPRESSED_CATEGORIES)

    def test_classification_text_never_contains_the_value(self):
        for t in (BRIDGE, f"password={REAL_U})[0]", f"token='{REAL_Q}'", f"password='dummy-{REAL_U}'", f"k={GH}"):
            dets, vals, fs = cls(t)
            blob = json.dumps(fs)
            for v in vals.values():
                core_v = v.strip("\"'")
                if len(core_v) > 3:
                    self.assertNotIn(core_v, blob, t)


class SpanExactness(unittest.TestCase):
    def test_revealed_value_is_exactly_the_masked_span(self):
        rnd = random.Random(11)
        parts = [f"password={REAL_U}", "ok = verify(token=tok)[0]", f"secret: '{REAL_Q}'", f"k={GH}", "x=AKIAQWERTYUIOPASDFGH", "mail a.b@example.com", "https://u:pw12345@host.test/x",
                 "Bearer abcdef0123456789abcdef0123456789", "api_key=\"dummy-key-1234\"", "  token =   spaced-value-12345  ", "10.1.2.3"]
        for _ in range(300):
            t = "\n".join(" ".join(rnd.sample(parts, rnd.randint(1, 4))) for _ in range(rnd.randint(1, 3)))
            masked = w.Redactor()(t)
            fin, dets = core._replay(t, [])
            self.assertEqual(fin, masked)
            roots = sorted((d for d in dets if d["parent"] is None), key=lambda d: d["lo"])
            out, pos = [], 0
            for d in roots:
                self.assertGreaterEqual(d["lo"], pos, "spans must not overlap")
                out += [t[pos:d["lo"]], d["mask"]]; pos = d["hi"]
            out.append(t[pos:])
            self.assertEqual("".join(out), masked, t)                    # substituting each reported span reproduces the engine output exactly
            _, _, vals = core._findings("Check", 0, t, [], "Check 1")
            for v in vals.values():
                self.assertIn(v, t)


if __name__ == "__main__":
    unittest.main()
