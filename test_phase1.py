"""Phase-1 validation tests. SYNTHETIC data only: nothing here reads a real ~/.claude or any real repository."""
import json, os, shutil, subprocess, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app_core as core, workreceipt as w, workreceipt_app as srv

ENV = dict(os.environ, GIT_AUTHOR_NAME="Demo Dev", GIT_AUTHOR_EMAIL="dev@example.com", GIT_COMMITTER_NAME="Demo Dev", GIT_COMMITTER_EMAIL="dev@example.com")
AKIA = "AKIAIOSFODNN7EXAMPLE"          # AWS's documented example key (not a credential)
GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"   # synthetic, matches the pattern only
TS = "2026-11-10T10:00:00Z"


def sh(*a, cwd=None, **k):
    return subprocess.run(a, check=True, capture_output=True, text=True, cwd=cwd, env=ENV, **k)


class WS:
    """A throwaway claude dir + repo."""
    def __init__(self, name="demo", git=True, commits=(), subdir=None):
        self.root = tempfile.mkdtemp()
        self.repo = os.path.join(self.root, name)
        os.makedirs(self.repo)
        self.claude = os.path.join(self.root, "claude")
        self.d = os.path.join(self.claude, "projects", w.encode_project_dir(self.repo))
        os.makedirs(self.d)
        os.environ["WORKRECEIPT_CLAUDE_DIR"] = self.claude
        os.environ["WORKRECEIPT_HOME"] = os.path.join(self.root, "home")
        os.environ.pop("WORKRECEIPT_OUT", None)
        core.save_settings({"out_dir": os.path.join(self.root, "out"), "redact_terms": [], "author": "", "client": ""})
        if git:
            sh("git", "init", "-q", cwd=self.repo)
            for i, (path, msg, day) in enumerate(commits):
                os.makedirs(os.path.dirname(os.path.join(self.repo, path)) or self.repo, exist_ok=True)
                open(os.path.join(self.repo, path), "w").write("\n".join(f"l{n}" for n in range(5 + i)) + "\n")
                sh("git", "add", ".", cwd=self.repo)
                e = dict(ENV, GIT_AUTHOR_DATE=f"2026-11-{day}T12:00:00", GIT_COMMITTER_DATE=f"2026-11-{day}T12:00:00")
                subprocess.run(["git", "commit", "-qm", msg], cwd=self.repo, check=True, capture_output=True, env=e)

    def log(self, lines, name="s.jsonl"):
        with open(os.path.join(self.d, name), "w", encoding="utf-8", errors="surrogatepass") as f:
            f.write("\n".join(lines) + "\n")

    def user(self, text, ts=TS, **k):
        return json.dumps({"type": "user", "timestamp": ts, "cwd": self.repo, "message": {"role": "user", "content": text}, **k})

    def bash(self, cid, cmd, ts=TS, result=None, err=None):
        out = [json.dumps({"type": "assistant", "timestamp": ts, "cwd": self.repo, "message": {"content": [{"type": "tool_use", "id": cid, "name": "Bash", "input": {"command": cmd}}]}})]
        if result is not None:
            out.append(json.dumps({"type": "user", "timestamp": ts, "cwd": self.repo, "message": {"content": [{"type": "tool_result", "tool_use_id": cid, "content": result, **({"is_error": err} if err is not None else {})}]}}))
        return out

    def build(self, **o):
        return core.build(dict({"repo": self.repo}, **o))

    def done(self):
        shutil.rmtree(self.root, ignore_errors=True)


class Discovery(unittest.TestCase):
    def test_missing_or_empty_claude_dir(self):
        self.assertEqual(core.discover("/nonexistent/zzz"), [])
        d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "projects"))
        self.assertEqual(core.discover(d), []); shutil.rmtree(d)

    def test_malformed_first_lines_and_odd_entries(self):
        ws = WS(); self.addCleanup(ws.done)
        ws.log(["[1]", "5", '"s"', "null", "{{", ws.user("hello")])
        os.makedirs(os.path.join(ws.d, "dir.jsonl"))              # a directory named like a log
        ps = core.discover(ws.claude)
        self.assertEqual([p["name"] for p in ps], ["demo"])
        self.assertEqual(ps[0]["sessions"], 1)

    def test_deleted_project_folder_is_reported_not_crashing(self):
        ws = WS(); self.addCleanup(ws.done)
        ws.log([ws.user("x")]); shutil.rmtree(ws.repo)
        p = core.discover(ws.claude)[0]
        self.assertFalse(p["exists"])
        with self.assertRaises(ValueError): core.build({"repo": ws.repo})


class Robustness(unittest.TestCase):
    def test_malformed_records_never_crash_and_valid_ones_survive(self):
        ws = WS(); self.addCleanup(ws.done)
        base = {"timestamp": TS, "cwd": ws.repo}
        bad = [ws.user("x", uuid=[1]), ws.user("x", uuid={"a": 1}),
               json.dumps({**base, "type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": [1], "content": "x"}]}}),
               json.dumps({**base, "type": "assistant", "message": {"content": [{"type": "tool_use", "id": [1], "name": "Bash", "input": {"command": "pytest"}}]}}),
               json.dumps({**base, "type": "assistant", "message": {"content": [{"type": "tool_use", "id": {"a": 1}, "name": "Bash", "input": "pytest"}]}}),
               ws.user("x", ts=12345), ws.user("x", ts=[1]), ws.user("x", ts="9999-99-99T99:99:99Z"),
               json.dumps({**base, "type": "user", "message": {"content": 5}}), json.dumps({**base, "type": "user", "message": "hi"}),
               json.dumps({**base, "type": "user", "message": {"content": [1, "a", None, [2]]}}),
               json.dumps({**base, "type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": 5}}]}}),
               "\x00\x00{{{", "[1,2]", '"x"', "5", "null", '{"type":"user","timestamp":"%s","message":{"content":"\\ud800 lone surrogate"}}' % TS]
        ws.log(bad + [ws.user("Valid request survives", uuid="ok1")])
        open(os.path.join(ws.d, "bin.jsonl"), "wb").write(os.urandom(4000))
        open(os.path.join(ws.d, "empty.jsonl"), "w").close()
        os.makedirs(os.path.join(ws.d, "dir.jsonl"))
        b = ws.build()
        self.assertIn("Valid request survives", [i["title"] for i in b["ctx"]["items"]])
        self.assertEqual(b["skipped"].get("unreadable session file"), 1)
        json.dumps(core.summary(b))

    def test_project_with_no_sessions_or_commits(self):
        ws = WS(); self.addCleanup(ws.done)
        s = core.summary(ws.build())
        self.assertEqual((len(s["requests"]), s["n_commits"], s["n_checks"], s["sessions"]), (0, 0, 0, 0))
        self.assertTrue(s["is_git"])
        r = core.export({"repo": ws.repo}, [], {})
        self.assertTrue(r["ok"]); self.assertIn("No session activity", r["html"])

    def test_not_a_git_repo(self):
        ws = WS(git=False); self.addCleanup(ws.done)
        ws.log([ws.user("Do the thing")])
        b = ws.build(); s = core.summary(b)
        self.assertFalse(s["is_git"]); self.assertEqual(s["n_commits"], 0); self.assertEqual(len(s["requests"]), 1)
        self.assertIn("No commits found", core.render_preview({"repo": ws.repo}, {}))

    def test_corrupt_git_dir_does_not_crash(self):
        ws = WS(git=False); self.addCleanup(ws.done)
        os.makedirs(os.path.join(ws.repo, ".git")); open(os.path.join(ws.repo, ".git", "HEAD"), "w").write("garbage")
        ws.log([ws.user("x")]); self.assertFalse(core.summary(ws.build())["is_git"])


class Accuracy(unittest.TestCase):
    def test_titles_are_verbatim_prompt_text_and_nothing_is_invented(self):
        ws = WS(commits=[("a.py", "Add a", "05"), ("b.py", "Add b", "06")]); self.addCleanup(ws.done)
        prompts = ["Add login page with email field", "Please fix the broken footer links\nSecond line detail", "Rename the settings screen"]
        ws.log([ws.user(p, ts=f"2026-11-0{i + 5}T09:00:00Z") for i, p in enumerate(prompts)])
        html = core.render_preview({"repo": ws.repo}, {})
        titles = [i["title"] for i in ws.build()["ctx"]["items"]]
        self.assertEqual(titles, ["Add login page with email field", "Please fix the broken footer links", "Rename the settings screen"])
        body = html.lower().replace("does not mean the work was completed", "")           # the one legitimate use of the word
        for bad in ("completed", "delivered successfully", "passed", "all tests", "fixed the", "implemented", "finished"):
            self.assertNotIn(bad, body, bad)
        self.assertIn("does not mean the work was completed", html)

    def test_commits_come_only_from_git_and_match_it(self):
        ws = WS(commits=[("a.py", "One", "05"), ("b.py", "Two", "06"), ("c.py", "Three", "07")]); self.addCleanup(ws.done)
        ws.log([ws.user("Only one request")])
        s = core.summary(ws.build())
        self.assertEqual(s["n_commits"], int(sh("git", "rev-list", "--count", "HEAD", cwd=ws.repo).stdout))
        self.assertEqual(len(s["requests"]), 1)
        s2 = core.summary(ws.build(since="2026-11-06", until="2026-11-06"))
        self.assertEqual([c[2] for c in s2["commits"]], ["Two"])
        s3 = core.summary(ws.build(git_author="nobody-at-all"))
        self.assertEqual(s3["n_commits"], 0)

    def test_git_author_value_is_not_an_option_injection(self):
        ws = WS(commits=[("a.py", "One", "05")]); self.addCleanup(ws.done)
        for v in ("--all", "-p", "x --exec=touch pwned", "$(touch pwned)", "; touch pwned"):
            ws.build(git_author=v)
        self.assertFalse(os.path.exists(os.path.join(ws.repo, "pwned")))

    def test_check_outcomes_are_not_overstated(self):
        ws = WS(); self.addCleanup(ws.done)
        ws.log([ws.user("run checks")] + ws.bash("c1", "pytest -q", result="1 failed", err=True) + ws.bash("c2", "npm run lint")
               + ws.bash("c3", "ruff check .", result="All checks passed!", err=False))
        ch = {c["cmd"]: c["ok"] for c in ws.build()["ctx"]["checks"]}
        self.assertEqual(ch, {"pytest -q": False, "npm run lint": None, "ruff check .": True})
        html = core.render_preview({"repo": ws.repo}, {})
        self.assertIn("result not recorded", html); self.assertIn("failed", html); self.assertIn("no error reported", html)
        self.assertNotRegex(html, r"\bpassed\b")

    def test_sibling_project_with_shared_prefix_is_excluded(self):
        ws = WS(name="app"); self.addCleanup(ws.done)
        sib = os.path.join(ws.root, "app-two"); os.makedirs(sib)
        d2 = os.path.join(ws.claude, "projects", w.encode_project_dir(sib)); os.makedirs(d2)
        open(os.path.join(d2, "s.jsonl"), "w").write(json.dumps({"type": "user", "timestamp": TS, "cwd": sib, "message": {"content": "Sibling secret work"}}) + "\n")
        ws.log([ws.user("Real work")])
        self.assertEqual([i["title"] for i in ws.build()["ctx"]["items"]], ["Real work"])


class Editing(unittest.TestCase):
    def setUp(self):
        self.ws = WS(); self.addCleanup(self.ws.done)
        self.ws.log([self.ws.user("First request", ts="2026-11-10T09:00:00Z"), self.ws.user("Second request", ts="2026-11-10T10:00:00Z")])

    def items(self):
        return {i["title"]: i["key"] for i in self.ws.build()["ctx"]["items"]}

    def test_edit_applies_by_key_and_survives_reordering(self):
        k = self.items()["Second request"]
        self.ws.log([self.ws.user("A new earlier request", ts="2026-11-10T08:00:00Z"), self.ws.user("First request", ts="2026-11-10T09:00:00Z"),
                     self.ws.user("Second request", ts="2026-11-10T10:00:00Z")])      # the log changed after loading: positions shifted
        html = core.render_preview({"repo": self.ws.repo}, {k: "Second, reworded"})
        self.assertIn("Second, reworded", html); self.assertIn("A new earlier request", html); self.assertIn("First request", html)
        self.assertNotIn("Second request", html)

    def test_stale_or_garbage_keys_are_dropped_and_counted(self):
        r = core.export({"repo": self.ws.repo}, [], {"deadbeef": "x", "0": "y", "": "z"})
        self.assertTrue(r["ok"]); self.assertEqual((r["edits_applied"], r["edits_dropped"]), (0, 3))
        self.assertNotIn(">x<", r["html"])

    def test_edits_are_masked_escaped_and_blank_edits_ignored(self):
        k = self.items()
        r = core.export({"repo": self.ws.repo}, [], {k["First request"]: f"Use key {AKIA} and token {GH} <script>alert(1)</script>", k["Second request"]: "   "})
        for leak in (AKIA, GH, "<script>"):
            self.assertNotIn(leak, r["html"])
        self.assertIn("&lt;script&gt;", r["html"]); self.assertIn("Second request", r["html"])


class Privacy(unittest.TestCase):
    def test_secrets_masked_in_every_report_section_and_never_in_api_payload(self):
        ws = WS(name="proj", commits=[(f"cfg-{GH}/a.py", f"Rotate {AKIA} key", "05")]); self.addCleanup(ws.done)
        ws.log([ws.user(f"Deploy with password=hunter2hunter2 and email jane@example.com")] + ws.bash("c1", f"pytest --token {GH} -q", result="ok", err=False))
        s = core.summary(ws.build(client=f"Client {AKIA}", author=f"me {GH}"))
        blob = json.dumps(s)
        for leak in (AKIA, GH, "hunter2hunter2", "jane@example.com"):
            self.assertNotIn(leak, blob)
        ids = [f["id"] for f in s["findings"] if f["severity"] == "high"]
        self.assertGreaterEqual(len(ids), 4)
        r = core.export({"repo": ws.repo, "client": f"Client {AKIA}", "author": f"me {GH}"}, ids, {})
        self.assertTrue(r["ok"])
        for leak in (AKIA, GH, "hunter2hunter2", "jane@example.com"):
            self.assertNotIn(leak, r["html"])
            self.assertNotIn(leak, open(r["html_path"]).read())
            self.assertNotIn(leak, os.path.basename(r["html_path"]))

    def test_export_requires_every_high_finding(self):
        ws = WS(); self.addCleanup(ws.done)
        ws.log([ws.user(f"key {AKIA}", ts="2026-11-10T09:00:00Z"), ws.user(f"token {GH}", ts="2026-11-10T10:00:00Z")])
        F = ws.build()["findings"]; hi = [f["id"] for f in F if f["severity"] == "high"]
        self.assertEqual(len(hi), 2)
        for partial in ([], hi[:1], ["bogus", hi[1]], [f["id"] for f in F if f["severity"] != "high"]):
            r = core.export({"repo": ws.repo}, partial, {})
            self.assertFalse(r["ok"], partial)
        self.assertFalse(os.path.isdir(core.load_settings()["out_dir"]) and os.listdir(core.load_settings()["out_dir"]))
        self.assertTrue(core.export({"repo": ws.repo}, hi, {})["ok"])

    def test_approval_is_bound_to_the_value_not_the_slot(self):
        ws = WS(); self.addCleanup(ws.done)
        ws.log([ws.user(f"key {AKIA}")]); old = [f["id"] for f in ws.build()["findings"] if f["severity"] == "high"]
        self.assertEqual(old, [f["id"] for f in ws.build()["findings"] if f["severity"] == "high"])      # stable within a run
        ws.log([ws.user("key AKIAABCDEFGHIJKLMNOP")])                                                     # a different secret, same slot
        self.assertFalse(core.export({"repo": ws.repo}, old, {})["ok"])

    def test_custom_terms(self):
        ws = WS(name="acme-storefront"); self.addCleanup(ws.done)
        ws.log([ws.user("Work for Initech Corp on the Storefront")])
        b = ws.build(terms=["initech", "  ", "", "storefront"])
        self.assertEqual({f["rule"] for f in b["findings"] if f["severity"] == "high"}, {"custom term"})
        html = core.render_preview({"repo": ws.repo, "terms": ["initech", " "]}, {})
        self.assertNotIn("Initech", html); self.assertIn("Corp", html)               # a blank term must not mask everything

    def test_redaction_is_linear_on_pathological_input(self):
        r = w.Redactor()
        for txt in ("a." * 50000, "A-" * 50000, "1." * 50000, "sk-" * 40000, "eyJ." * 25000, "a_b-" * 25000, "http" * 30000, "a@" * 40000, "password " * 20000):
            t = time.time(); r(txt); self.assertLess(time.time() - t, 3, txt[:8])

    def test_pathological_prompt_does_not_hang_the_report(self):
        ws = WS(); self.addCleanup(ws.done)
        ws.log([ws.user("a." * 100000), ws.user("password=" + "x" * 50000, ts="2026-11-10T11:00:00Z")])
        t = time.time(); b = ws.build(); self.assertLess(time.time() - t, 10)
        self.assertEqual(len(b["ctx"]["items"]), 2)


class Scale(unittest.TestCase):
    def test_large_report(self):
        ws = WS(); self.addCleanup(ws.done)
        lines = []
        for i in range(1500):
            ts = f"2026-11-{1 + i % 28:02d}T{i % 24:02d}:{i % 60:02d}:00Z"
            lines.append(ws.user(f"Request number {i}: tweak component {i % 40}", ts=ts, uuid=f"u{i}"))
            if i % 3 == 0:
                lines += ws.bash(f"c{i}", f"pytest tests/test_{i}.py -q", ts=ts, result="ok", err=False)
        ws.log(lines)
        stream = ["commit refs/heads/master", "committer D <d@e.com> 1762800000 +0000", "data 2", "x\n", "M 100644 inline f.txt", "data 1", "x\n"]
        stream = []
        for i in range(1500):
            msg = f"Commit {i}"
            stream += ["commit refs/heads/master", f"committer D <d@e.com> {1762800000 + i * 60} +0000", f"data {len(msg)}", msg, f"M 100644 inline f{i % 50}.txt", f"data {len(str(i))}", str(i)]
        subprocess.run(["git", "fast-import", "--quiet"], cwd=ws.repo, input="\n".join(stream) + "\n", text=True, check=True, capture_output=True, env=ENV)
        t = time.time(); s = core.summary(ws.build()); r = core.render_preview({"repo": ws.repo}, {}); dt = time.time() - t
        self.assertEqual((len(s["requests"]), s["n_commits"]), (1500, 1500)); self.assertEqual(s["n_checks"], 500)
        self.assertLess(dt, 30); self.assertLess(len(json.dumps(s)), 1_500_000)
        self.assertLess(len(r), 400_000)                                       # report caps commits (60) and checks (40)
        self.assertIn("more commits", r); self.assertIn("earliest check(s) are omitted", r)


class Export(unittest.TestCase):
    def test_unwritable_reports_folder_is_a_clean_error(self):
        ws = WS(); self.addCleanup(ws.done)
        blocker = os.path.join(ws.root, "file"); open(blocker, "w").write("x")
        core.save_settings({"out_dir": os.path.join(blocker, "sub")})
        with self.assertRaises(ValueError) as cm: core.export({"repo": ws.repo}, [], {})
        self.assertIn("Cannot write", str(cm.exception))

    def test_exports_in_the_same_second_never_overwrite(self):
        ws = WS(); self.addCleanup(ws.done)
        a = core.export({"repo": ws.repo}, [], {}); b = core.export({"repo": ws.repo}, [], {})
        self.assertNotEqual(a["html_path"], b["html_path"]); self.assertTrue(os.path.exists(a["html_path"]))

    def test_pdf_graceful_without_chrome_and_with_odd_path(self):
        ws = WS(); self.addCleanup(ws.done)
        out = os.path.join(ws.root, "My Reports #1 %20")
        core.save_settings({"out_dir": out})
        real = core.chrome_path
        core.chrome_path = lambda: None
        try:
            r = core.export({"repo": ws.repo, "pdf": True}, [], {})
        finally:
            core.chrome_path = real
        self.assertTrue(r["ok"]); self.assertIsNone(r["pdf_path"])
        if core.chrome_path():
            r = core.export({"repo": ws.repo, "pdf": True}, [], {})
            self.assertTrue(r["pdf_path"] and os.path.getsize(r["pdf_path"]) > 1000)
            self.assertTrue(open(r["pdf_path"], "rb").read(5) == b"%PDF-")

    def test_report_escapes_hostile_text_everywhere(self):
        ws = WS(name='x"><img src=x onerror=1>', commits=[("a.py", "<script>alert(1)</script> & co", "05")]); self.addCleanup(ws.done)
        ws.log([ws.user("<b onmouseover=1>hi</b> </li><script>1</script>")] + ws.bash("c1", "pytest '<img src=x onerror=1>'", result="ok", err=False))
        html = core.render_preview({"repo": ws.repo, "client": "<svg onload=1>", "author": '"><i>'}, {})
        for raw in ("<script", "<img", "<svg", "<b onmouse", "<i>"):
            self.assertNotIn(raw, html, raw)


class ServerSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ws = WS(); cls.ws.log([cls.ws.user(f"Use {AKIA}")])
        cls.s = ThreadingHTTPServer(("127.0.0.1", 0), srv.H); cls.port = cls.s.server_address[1]
        threading.Thread(target=cls.s.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.s.shutdown(); cls.ws.done()

    def req(self, path, body=None, raw=None, token=True, headers=None):
        h = dict(headers or {})
        if token: h["X-WR-Token"] = srv.TOKEN
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        try:
            r = urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data, h)); return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_bad_requests_are_clean(self):
        self.assertEqual(self.req("/api/preview", raw=b"{not json")[0], 400)
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port); c.putrequest("POST", "/api/preview")
        c.putheader("X-WR-Token", srv.TOKEN); c.putheader("Content-Length", "3000000"); c.endheaders()
        self.assertEqual(c.getresponse().status, 413); c.close()                  # refused from the header alone, body never read
        self.assertEqual(self.req("/api/nope", body={})[0], 404)
        code, body = self.req("/api/preview", body={"repo": self.ws.repo, "since": "bad"})
        self.assertEqual(code, 400); self.assertNotIn(b"Traceback", body)
        code, body = self.req("/api/preview", body={"repo": 123})
        self.assertIn(code, (400, 500)); self.assertNotIn(b"Traceback", body)

    def test_no_secret_value_ever_leaves_the_server(self):
        code, body = self.req("/api/preview", body={"repo": self.ws.repo}); self.assertEqual(code, 200)
        code2, body2 = self.req("/api/render", body={"repo": self.ws.repo})
        for b in (body, body2, self.req("/api/state")[1], self.req("/")[1]):
            self.assertNotIn(AKIA.encode(), b)

    def test_cross_origin_posts_and_foreign_hosts_are_refused(self):
        self.assertEqual(self.req("/api/preview", body={"repo": self.ws.repo}, token=False, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.req("/", headers={"Host": "evil.example:8765"}, token=False)[0], 403)
        self.assertEqual(self.req("/api/state", headers={"Host": "127.0.0.1.evil.example"}, token=False)[0], 403)
        self.assertNotIn(b"Access-Control", b"")
        r = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/state")
        self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))

    def test_static_serving_cannot_escape_ui_dir(self):
        for p in ("/../app_core.py", "/%2e%2e/app_core.py", "/..%2fapp_core.py", "/ui/../app_core.py", "/fonts/../../app_core.py", "/report/%2e%2e%2fapp_core.py"):
            self.assertEqual(self.req(p)[0], 404, p)


if __name__ == "__main__":
    unittest.main()
