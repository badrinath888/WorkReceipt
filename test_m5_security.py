"""M5 privacy hardening regressions. SYNTHETIC values only; none of these is a real credential."""
import json, os, subprocess, sys, tempfile, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app_core as core, workreceipt as w
from test_phase1 import WS

PW = "correct_horse_staple"          # the audited counter-example: a real-looking unquoted passphrase
HI = "Xk9mQ2vL7pR4zT"


def high(text):
    m, fs, vals = core._findings("Check", 0, text, [], "Check 1")
    return m, [d for f in fs if f["severity"] == "high" for d in f["detections"]], vals


class NeverAutoClearPossibleCredentials(unittest.TestCase):
    CASES = [  # (language/context, text) -- each contains a plausible real unquoted/quoted secret
        ("python kwarg", f"login(password={PW})"), ("python nested", f"run(login(user, password={PW}), 1)"),
        ("python attr", f"password=self.{PW}"), ("python call", f"db_password=get_correct_horse(staple)"),
        ("python assert", f"assert login(password={PW})[0]"), ("fixture", f"cat > test_a.py <<'EOF'\ndef test_x():\n    login(password={PW})\nEOF"),
        ("js attr", "const c = {password: config.hunter2staple}"), ("js call", "client.auth({token: load_key(secret_name)})"),
        ("json", '{"password": "correcthorsebattery"}'), ("shell export", f"export PASSWORD={PW}"),
        ("shell inline", f"PGPASSWORD={PW} psql -h db"), ("yaml", f"password: {PW}_battery"),
        ("quoted angle value", 'password="<Tr0ub4dor3>"'), ("quoted angle word", 'password="<correcthorse>"'),
        ("kwarg hyphen", "foo(password=correct-horse-staple)"),
    ]

    def test_none_cleared(self):
        for name, text in self.CASES:
            with self.subTest(name):
                m, ds, _ = high(text)
                self.assertTrue(ds, "must be detected")
                self.assertFalse(any(d["suppressed"] for d in ds), [d["class"]["category"] for d in ds])
                self.assertNotIn(PW, m); self.assertNotIn("hunter2staple", m); self.assertNotIn("Tr0ub4dor3", m); self.assertNotIn("correcthorse", m)

    def test_confidence_is_advisory_only(self):
        for name, text in self.CASES:
            _, ds, _ = high(text)
            for d in ds:
                self.assertEqual(d["suppressed"], d["class"]["confidence"] == "rule-proven" and d["class"]["suppressed"])
                self.assertNotEqual(d["class"]["confidence"], "high" if d["suppressed"] else "x")

    def test_narrow_harmless_cases_still_cleared(self):
        for text in ("echo password=$DB_PASSWORD_X", "secret=os.environ[", 'password="<your_password>"', 'token="${API_TOKEN}"',
                     "login(password=pw)[0]", "verify(token=tok)[0]", "key=AKIAIOSFODNN7EXAMPLE"):
            with self.subTest(text):
                _, ds, _ = high(text)
                self.assertTrue(ds and all(d["suppressed"] for d in ds), text)

    def test_cleared_values_are_still_masked_in_exports(self):
        ws = WS(); self.addCleanup(ws.done)
        ws.log(ws.bash("c1", "pytest -q; echo password=$DB_PASSWORD_X; verify(token=tok)[0]", result="ok", err=False))
        r = core.export({"repo": ws.repo}, {}, {})
        self.assertTrue(r["ok"]); self.assertNotIn("DB_PASSWORD_X", r["html"]); self.assertNotIn("tok)[0]", r["html"])


class NewDetections(unittest.TestCase):
    def test_cli_option_secrets_are_masked_and_need_review(self):
        for cmd in (f"mysql --password {HI} -h x", f"tool --token {HI}", f"curl -u admin:{PW} https://x.test", f"curl --user 'admin:{PW}' https://x.test",
                    f"cli login -password {HI}", f"app --passphrase \"{PW} two\""):
            with self.subTest(cmd):
                m, ds, _ = high(cmd)
                self.assertTrue(ds and not any(d["suppressed"] for d in ds)); self.assertNotIn(HI, m); self.assertNotIn(PW, m)

    def test_no_false_positive_on_plain_flags(self):
        for cmd in ("npm --token-count 5", "git log --user-agent x", "ls -u -l", "pytest --secret-scan", "curl -u"):
            self.assertEqual(high(cmd)[1], [], cmd)


class Hostile(unittest.TestCase):
    def test_long_record_is_reviewed_as_a_unit_and_never_cleared(self):
        text = ("x " * 300_000) + f" login(password={PW}) " + ("y " * 10)
        m, fs, vals = core._findings("Check", 0, text, [], "Check 1")
        hs = [d for f in fs if f["severity"] == "high" for d in f["detections"]]
        self.assertTrue(hs and not any(d.get("suppressed") for d in hs)); self.assertNotIn(PW, m); self.assertNotIn(PW, json.dumps(fs))

    def test_pathological_inputs_terminate_quickly_and_mask(self):
        for text in ("password=" + "(" * 50_000, "token=" + "a" * 200_000, ("secret=" + HI + ")") * 20_000, "\x00password=" + HI + "‮﻿",
                     "p" * 100_000 + "password=" + HI, "{" * 10_000 + f"password: {HI}" + "}" * 10_000, ("-u a:b " * 30_000)):
            t0 = time.time(); m, fs, _ = core._findings("Check", 0, text, [], "c")
            self.assertLess(time.time() - t0, 20, text[:20]); self.assertNotIn(HI, m)

    def test_value_cannot_forge_a_cleared_shape(self):
        for text in (f"password=${{{HI}}}", f"password=os.environ[{HI}]", f"token=getenv({HI})", f"secret=<{HI}>", f"password='${HI}'"):
            m, ds, _ = high(text)
            self.assertNotIn(HI, m, text)


class ApprovalBinding(unittest.TestCase):
    def test_changed_value_invalidates_prior_approval(self):
        ws = WS(); self.addCleanup(ws.done)
        ws.log(ws.bash("c1", f"pytest -q && export PASSWORD={PW}", result="ok", err=False))
        ids = [d["id"] for f in ws.build()["findings"] for d in f["detections"] if f["severity"] == "high" and not d["suppressed"]]
        self.assertTrue(core.export({"repo": ws.repo}, {i: "credential" for i in ids}, {})["ok"])
        ws.log(ws.bash("c1", f"pytest -q && export PASSWORD={PW}_changed", result="ok", err=False))      # same place, different value
        r = core.export({"repo": ws.repo}, {i: "credential" for i in ids}, {})
        self.assertFalse(r["ok"]); self.assertEqual(r["error"], "review_required")

    def test_unknown_or_forged_dispositions_do_not_approve(self):
        ws = WS(); self.addCleanup(ws.done)
        ws.log(ws.bash("c1", f"pytest -q && export PASSWORD={PW}", result="ok", err=False))
        ids = [d["id"] for f in ws.build()["findings"] for d in f["detections"] if f["severity"] == "high" and not d["suppressed"]]
        for bad in ({}, {i: "approved" for i in ids}, {i: True for i in ids}, {i: "" for i in ids}, [], None, "all"):
            self.assertFalse(core.export({"repo": ws.repo}, bad, {})["ok"], bad)


class NoLeakage(unittest.TestCase):
    def test_api_responses_logs_and_errors_never_contain_the_secret(self):
        import threading, urllib.request, urllib.error
        from http.server import ThreadingHTTPServer
        import workreceipt_app as app
        ws = WS(); self.addCleanup(ws.done)
        ws.log(ws.bash("c1", f"pytest -q; export PASSWORD={PW}; curl -u admin:{HI} x", result=f"password={PW}", err=False), name="a.jsonl")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), app.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
        base = f"http://127.0.0.1:{srv.server_address[1]}/"
        def post(path, body):
            r = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST", headers={"X-WR-Token": app.TOKEN, "Content-Type": "application/json"})
            try: return urllib.request.urlopen(r).read().decode()
            except urllib.error.HTTPError as e: return e.read().decode()
        o = {"repo": ws.repo}
        blobs = [urllib.request.urlopen(base + "api/state").read().decode(), post("api/preview", o), post("api/render", o), post("api/export", o),
                 post("api/preview", {"repo": ws.repo, "since": PW}), post("api/export", {**o, "titles": {"k": PW}}), post("api/reveal", {**o, "id": "nope", "confirm": True})]
        for b in blobs:
            self.assertNotIn(PW, b); self.assertNotIn(HI, b)
        self.assertFalse(os.path.isdir(core.load_settings()["out_dir"]) and os.listdir(core.load_settings()["out_dir"]))   # blocked export wrote nothing
        for root, _, fs in os.walk(core._home()):                  # nothing persisted under the app's data folder
            for f in fs:
                self.assertNotIn(PW, open(os.path.join(root, f), errors="ignore").read())

    def test_edit_containing_a_secret_is_masked_in_export(self):
        ws = WS(); self.addCleanup(ws.done)
        ws.log([ws.user("add the login page")])
        key = core.build({"repo": ws.repo})["ctx"]["items"][0]["key"]
        r = core.export({"repo": ws.repo}, {}, {key: f"call login(password={PW}) now"})
        self.assertTrue(r["ok"] or r.get("error") == "review_required")
        if r["ok"]: self.assertNotIn(PW, r["html"])


class Consistency(unittest.TestCase):
    def test_cli_preview_and_export_agree(self):
        ws = WS(); self.addCleanup(ws.done)
        ws.log([ws.user(f"deploy with password={PW}")] + ws.bash("c1", f"pytest -q; mysql --password {HI} && curl -u a:{PW} x", result="ok", err=False))
        out = os.path.join(ws.root, "cli.html")
        p = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "workreceipt.py"), "--repo", ws.repo, "--claude-dir", ws.claude, "--out", out],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode != 0 or os.path.exists(out), True)         # CLI refuses (high severity) or writes a masked file
        for blob in (p.stdout, p.stderr, open(out).read() if os.path.exists(out) else ""):
            self.assertNotIn(PW, blob); self.assertNotIn(HI, blob)
        b = core.build({"repo": ws.repo})
        ids = {d["id"]: "unsure" for f in b["findings"] for d in f["detections"] if f["severity"] == "high" and not d["suppressed"]}
        self.assertTrue(ids)
        prev = core.render_preview({"repo": ws.repo}, {}); exp = core.export({"repo": ws.repo}, ids, {})
        self.assertTrue(exp["ok"])
        for blob in (prev, exp["html"], open(exp["html_path"]).read(), json.dumps(core.summary(b))):
            self.assertNotIn(PW, blob); self.assertNotIn(HI, blob)


if __name__ == "__main__":
    unittest.main()
