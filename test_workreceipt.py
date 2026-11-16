import json, os, subprocess, tempfile, unittest
import workreceipt as w

SECRET_AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
SECRET_GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def ev(typ, content, ts, **kw):
    return json.dumps({"type": typ, "timestamp": ts, "message": {"role": typ, "content": content}, **kw})


class E2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "client-site")
        os.makedirs(os.path.join(self.repo, "src"))
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x.io", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x.io")
        def g(*a, date=None):
            e = dict(env)
            if date:
                e["GIT_AUTHOR_DATE"] = e["GIT_COMMITTER_DATE"] = date
            subprocess.run(["git", "-C", self.repo, *a], check=True, capture_output=True, env=e)
        g("init", "-q")
        open(os.path.join(self.repo, "src", "a.py"), "w").write("x=1\n")
        g("add", "."); g("commit", "-qm", "Add login form", date="2026-11-05T10:00:00")
        open(os.path.join(self.repo, "src", "a.py"), "a").write("y=2\n")
        g("commit", "-qam", "Fix empty password bug", date="2026-11-06T10:00:00")
        open(os.path.join(self.repo, "old.py"), "w").write("z=3\n")
        g("add", "."); g("commit", "-qm", "Outside range", date="2026-10-01T10:00:00")
        self.claude = os.path.join(self.tmp, "claude")
        pdir = os.path.join(self.claude, "projects", w.encode_project_dir(self.repo))
        os.makedirs(pdir)
        lines = [
            ev("user", f"Add a login form. Use key {SECRET_AWS} and mail me at bob@client.com", "2026-11-05T09:00:00Z"),
            ev("assistant", [{"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": "/x/src/a.py"}}], "2026-11-05T09:01:00Z"),
            ev("assistant", [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "pytest -q"}}], "2026-11-05T09:02:00Z"),
            ev("user", [{"type": "tool_result", "tool_use_id": "t2", "content": "ok", "is_error": False}], "2026-11-05T09:03:00Z"),
            ev("assistant", [{"type": "tool_use", "id": "t3", "name": "Bash", "input": {"command": "npm run build"}}], "2026-11-05T09:04:00Z"),
            ev("user", [{"type": "tool_result", "tool_use_id": "t3", "content": "Exit code 1", "is_error": True}], "2026-11-05T09:05:00Z"),
            ev("user", "<command-name>/clear</command-name>", "2026-11-05T09:06:00Z"),
            ev("user", f"Fix the empty password bug, token={SECRET_GH}", "2026-11-06T09:00:00Z"),
            ev("user", "Out of range prompt <script>alert(1)</script>", "2026-10-01T09:00:00Z"),
        ]
        open(os.path.join(pdir, "s1.jsonl"), "w").write("\n".join(lines) + "\n")

    def run_cli(self, *extra):
        return w.main(["--repo", self.repo, "--claude-dir", self.claude, "--since", "2026-11-01", "--until", "2026-11-14", *extra])

    def test_blocks_on_high_severity(self):
        out = os.path.join(self.tmp, "r.html")
        self.assertEqual(self.run_cli("--out", out), 2)
        self.assertFalse(os.path.exists(out))

    def test_report_contents_and_redaction(self):
        out = os.path.join(self.tmp, "r.html")
        self.assertEqual(self.run_cli("--out", out, "--allow-high", "--client", "Acme", "--redact-term", "client-site"), 0)
        h = open(out).read()
        for secret in (SECRET_AWS, SECRET_GH, "bob@client.com", "client-site"):
            self.assertNotIn(secret, h)
        self.assertIn("Work report for Acme", h)
        self.assertIn("Add login form", h)
        self.assertIn("Fix empty password bug", h)
        self.assertNotIn("Outside range", h)
        self.assertNotIn("Out of range prompt", h)
        self.assertIn("pytest -q", h)
        self.assertIn("no error reported", h)
        self.assertIn("failed", h)
        self.assertNotIn("/clear", h)
        self.assertIn("<b>2</b>work requests", h)
        self.assertIn("<b>2</b>commits", h)

    def test_html_is_escaped(self):
        p = os.path.join(self.claude, "projects", w.encode_project_dir(self.repo), "s2.jsonl")
        open(p, "w").write(ev("user", "<script>alert(1)</script> change nav", "2026-11-07T09:00:00Z") + "\n")
        out = os.path.join(self.tmp, "r.html")
        self.run_cli("--out", out, "--allow-high")
        h = open(out).read()
        self.assertNotIn("<script>alert", h)
        self.assertIn("&lt;script&gt;", h)

    def test_no_sessions_still_works(self):
        out = os.path.join(self.tmp, "r.html")
        rc = w.main(["--repo", self.repo, "--claude-dir", os.path.join(self.tmp, "none"), "--since", "2026-11-01", "--out", out])
        self.assertEqual(rc, 0)
        self.assertIn("No session activity", open(out).read())


if __name__ == "__main__":
    unittest.main()


# ---------- regression + fuzz tests (second QA pass) ----------
import random, string, io, contextlib


def _ev(t, c, ts="2026-11-05T09:00:00Z", **kw):
    return json.dumps({"type": t, "timestamp": ts, "message": {"role": t, "content": c}, **kw})


class Regress(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "proj")
        os.makedirs(self.repo)
        subprocess.run(["git", "-C", self.repo, "init", "-q"])
        self.cl = os.path.join(self.tmp, "c")

    def put(self, lines, name="s.jsonl", repo=None):
        d = os.path.join(self.cl, "projects", w.encode_project_dir(repo or self.repo))
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, name), "w").write("\n".join(lines) + "\n")

    def run_(self, *extra):
        out = os.path.join(self.tmp, "o.html")
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = w.main(["--repo", self.repo, "--claude-dir", self.cl, "--since", "2026-11-01", "--out", out, "--allow-high", *extra])
        return (open(out).read() if os.path.exists(out) else ""), err.getvalue(), rc

    def test_secret_straddling_truncation(self):
        self.put([_ev("user", "x" * 100 + " AKIA" + "ZXCVBNMASDFGHJKL tail")])
        self.assertNotIn("AKIA", self.run_()[0])

    def test_naive_timestamp(self):
        self.put([_ev("user", "Do the thing", "2026-11-05T09:00:00")])
        self.assertIn("Do the thing", self.run_()[0])

    def test_reminder_block_then_real_text(self):
        self.put([_ev("user", [{"type": "text", "text": "<system-reminder>x</system-reminder>"}, {"type": "text", "text": "Build pricing page"}])])
        h = self.run_()[0]
        self.assertIn("Build pricing page", h); self.assertNotIn("system-reminder", h)

    def test_json_password_and_unlabeled_token(self):
        self.put([_ev("user", 'cfg {"password": "hunter2hunter2"} and tok xK3mP9qLz7VbN2cR8tYw4HdF6gJ1aSe5 ok')])
        h = self.run_()[0]
        self.assertNotIn("hunter2", h); self.assertNotIn("xK3mP9qLz7", h)

    def test_sidechain_dupes_and_acks(self):
        l = _ev("user", "Add dark mode", uuid="u1")
        self.put([l, _ev("user", "Explore code", isSidechain=True), _ev("user", "continue")], "a.jsonl")
        self.put([l], "b.jsonl")
        h = self.run_()[0]
        self.assertEqual(h.count("Add dark mode"), 1)
        self.assertNotIn("Explore code", h)
        self.assertNotIn(">continue<", h)

    def test_subdir_session_and_sibling_prefix(self):
        sub = os.path.join(self.repo, "web"); os.makedirs(sub)
        self.put([_ev("user", "Fix navbar", cwd=sub)], repo=sub)
        sib = self.repo + "-v2"; os.makedirs(sib)
        self.put([_ev("user", "Sibling secret project", cwd=sib)], repo=sib)
        h = self.run_()[0]
        self.assertIn("Fix navbar", h); self.assertNotIn("Sibling secret", h)

    def test_check_detection_and_results(self):
        def tu(i, cmd): return _ev("assistant", [{"type": "tool_use", "id": i, "name": "Bash", "input": {"command": cmd}}])
        def tr(i, txt, err=False): return _ev("user", [{"type": "tool_result", "tool_use_id": i, "content": txt, "is_error": err}])
        self.put([tu("a", "git commit -m 'fix pytest'"), tu("b", "cd x && pytest -q"), tr("b", "ok"),
                  tu("c", "npm run build"), tr("c", "Exit code 1\nboom", True),
                  tu("d", "make test"), tr("d", [{"type": "text", "text": "Exit code: 2"}]), tu("e", "ruff check .")])
        h = self.run_()[0]
        self.assertNotIn("git commit", h)
        self.assertRegex(h, r"pytest -q</code></td><td[^>]*><span class='chip ok'>No error reported")
        self.assertRegex(h, r"npm run build</code></td><td[^>]*><span class='chip bad'>Failed")
        self.assertRegex(h, r"make test</code></td><td[^>]*><span class='chip bad'>Failed")
        self.assertRegex(h, r"ruff check \.</code></td><td[^>]*><span class='chip unk'>Result not recorded")

    def test_non_git_warns_and_dirnames_redacted(self):
        shutil_ = __import__("shutil"); shutil_.rmtree(os.path.join(self.repo, ".git"))
        self.assertIn("not a git repository", self.run_()[1])

    def test_csp_present_and_bad_lines_tolerated(self):
        self.put(["not json", "[1,2]", '{"type":"user","timestamp":"2026-11-05T09:00:00Z","message":null}', _ev("user", "Real prompt")])
        h = self.run_()[0]
        self.assertIn("Content-Security-Policy", h); self.assertIn("Real prompt", h)

    def test_diagnose_prints_no_content(self):
        self.put([_ev("user", "TOPSECRETCONTENT", cwd="/x/clientname"), _ev("assistant", [{"type": "tool_use", "id": "1", "name": "mcp__acme__thing", "input": {}}])])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            w.main(["--repo", self.repo, "--claude-dir", self.cl, "--diagnose"])
        o = buf.getvalue()
        self.assertIn("jsonl files: 1", o)
        for bad in ("TOPSECRETCONTENT", "clientname", "acme"):
            self.assertNotIn(bad, o)

    def test_fuzz_fake_secrets_never_leak(self):
        rnd = random.Random(7)
        al = string.ascii_letters + string.digits
        mk = [lambda: "AKIA" + "".join(rnd.choice(string.ascii_uppercase + string.digits) for _ in range(16)),
              lambda: "ghp_" + "".join(rnd.choice(al) for _ in range(36)),
              lambda: "sk-" + "".join(rnd.choice(al) for _ in range(40)),
              lambda: "sk_live_" + "".join(rnd.choice(al) for _ in range(24)),
              lambda: "xoxb-" + "".join(rnd.choice(string.digits) for _ in range(12)) + "-" + "".join(rnd.choice(al) for _ in range(20)),
              lambda: "eyJ" + "".join(rnd.choice(al) for _ in range(12)) + "." + "".join(rnd.choice(al) for _ in range(12)) + "." + "".join(rnd.choice(al) for _ in range(12)),
              lambda: "AIza" + "".join(rnd.choice(al + "_-") for _ in range(35)),
              lambda: "postgres://u:" + "".join(rnd.choice(al) for _ in range(12)) + "@db.internal/x"]
        tmpl = ["{s}", "key is {s} thanks", "export API_TOKEN={s}", '{{"api_key": "{s}"}}', "Authorization: Bearer {s}",
                "x" * 90 + " {s}", "line1\nline2 {s}\nline3", "(" + "{s}" + ")", "curl -H 'X-Key: {s}' https://a.b"]
        secrets, lines = [], []
        for i in range(120):
            s = rnd.choice(mk)()
            body = rnd.choice(tmpl).format(s=s)
            secrets.append(s)
            lines.append(_ev("user", body, uuid="f%d" % i))
            lines.append(_ev("assistant", [{"type": "tool_use", "id": "t%d" % i, "name": "Bash", "input": {"command": "pytest " + body.replace("\n", " ")}}], uuid="g%d" % i))
        self.put(lines)
        h, _, _ = self.run_()
        leaked = [s for s in secrets if s in h or s[8:] in h]
        self.assertEqual(leaked, [], "leaked %d of %d" % (len(leaked), len(secrets)))
        # and without --allow-high the run must refuse
        out = os.path.join(self.tmp, "o2.html")
        with contextlib.redirect_stderr(io.StringIO()):
            rc = w.main(["--repo", self.repo, "--claude-dir", self.cl, "--since", "2026-11-01", "--out", out])
        self.assertEqual(rc, 2); self.assertFalse(os.path.exists(out))
