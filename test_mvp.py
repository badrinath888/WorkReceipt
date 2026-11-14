"""MVP audit regressions: check detection, project association, git, report honesty, robustness, HTML safety."""
import contextlib, html.parser, io, json, os, re, subprocess, sys, tempfile, time, unittest
import workreceipt as w

HERE = os.path.dirname(os.path.abspath(__file__))


def _e(t, c, ts="2026-11-05T09:00:00Z", **kw):
    return json.dumps({"type": t, "timestamp": ts, "message": {"role": t, "content": c}, **kw})


def _tu(i, cmd, ts="2026-11-05T09:00:00Z"):
    return _e("assistant", [{"type": "tool_use", "id": i, "name": "Bash", "input": {"command": cmd}}], ts)


def _tr(i, txt="ok", err=None, ts="2026-11-05T09:00:30Z"):
    b = {"type": "tool_result", "tool_use_id": i, "content": txt}
    if err is not None:
        b["is_error"] = err
    return _e("user", [b], ts)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "proj")
        os.makedirs(self.repo)
        self.env = dict(os.environ, GIT_AUTHOR_NAME="Ann", GIT_AUTHOR_EMAIL="a@x.io", GIT_COMMITTER_NAME="Ann", GIT_COMMITTER_EMAIL="a@x.io")
        self.git("init", "-q")
        self.cl = os.path.join(self.tmp, "c")

    def git(self, *a, date=None, author=None):
        e = dict(self.env)
        if date:
            e["GIT_AUTHOR_DATE"] = e["GIT_COMMITTER_DATE"] = date
        if author:
            e["GIT_AUTHOR_NAME"] = author
        subprocess.run(["git", "-C", self.repo, *a], check=True, capture_output=True, env=e)

    def commit(self, name, msg, date, author=None, content="x\n"):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(content)
        self.git("add", ".")
        self.git("commit", "-qm", msg, date=date, author=author)

    def put(self, lines, name="s.jsonl", repo=None):
        d = os.path.join(self.cl, "projects", w.encode_project_dir(repo or self.repo))
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w") as f:
            f.write("\n".join(lines) + "\n")

    def run_(self, *extra, allow=True):
        out = os.path.join(self.tmp, "o.html")
        err = io.StringIO()
        args = ["--repo", self.repo, "--claude-dir", self.cl, "--since", "2026-11-01", "--out", out] + (["--allow-high"] if allow else [])
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = w.main(args + list(extra))
        if os.path.exists(out):
            with open(out) as f:
                return f.read(), err.getvalue(), rc
        return "", err.getvalue(), rc


class Checks(unittest.TestCase):
    def test_detection(self):
        yes = ["pytest", "cd x && pytest -q", "bash -c \"pytest -q\"", "bash -lc 'cd web && npm test'", "swift test",
               "xcodebuild test -scheme A", "FOO=1 python3 -m pytest", "time npm run build", "echo hi; make test", "dotnet test"]
        no = ["git commit -m \"fix; pytest\"", "echo 'pytest'", "git commit -m 'run npm test'", "ls | grep pytest",
              "git log --oneline", "echo \"a && make test\""]
        for c in yes:
            self.assertTrue(w.is_check(c), c)
        for c in no:
            self.assertFalse(w.is_check(c), c)


class Association(Base):
    def test_encoding_collision_and_foreign_edits(self):
        other = os.path.join(self.tmp, "pro", "j"); os.makedirs(other)   # '/tmp/x/proj' vs '/tmp/x/pro/j' style collisions
        self.put([_e("user", "Mine one", cwd=self.repo, uuid="1"),
                  _e("user", "Not mine (other cwd)", cwd=other, uuid="2"),
                  _e("assistant", [{"type": "tool_use", "id": "e1", "name": "Edit", "input": {"file_path": os.path.join(other, "z.py")}}], cwd=other, uuid="3")])
        h, err, rc = self.run_()
        self.assertIn("Mine one", h); self.assertNotIn("Not mine", h)
        self.assertIn("another project directory", err)

    def test_relative_edit_path_marks_unrerun_check(self):
        self.put([_tu("a", "pytest -q", "2026-11-05T09:00:00Z"), _tr("a", "ok", None, "2026-11-05T09:00:05Z"),
                  _e("assistant", [{"type": "tool_use", "id": "e", "name": "Edit", "input": {"file_path": "src/a.py"}}], "2026-11-05T09:10:00Z", cwd=self.repo),
                  _tu("b", "npm test", "2026-11-05T09:20:00Z"), _tr("b", "ok", None, "2026-11-05T09:20:05Z")])
        h = self.run_()[0]
        self.assertRegex(h, r"pytest -q</code> — <span class=ok>no error reported</span> <span class=unk>\(files were edited after this check; not re-run since\)")
        self.assertRegex(h, r"npm test</code> — <span class=ok>no error reported</span></li>")

    def test_tool_use_result_records_are_not_requests(self):
        self.put([_e("user", "Output text that looks like a prompt", toolUseResult={"stdout": "x"}), _e("user", "Real ask")])
        h = self.run_()[0]
        self.assertIn("Real ask", h); self.assertNotIn("looks like a prompt", h)


class Results(Base):
    def test_outcomes_not_inferred(self):
        self.put([_tu("a", "pytest"), _tu("b", "ruff check ."), _tr("b", "Exit code 1\nboom", True),
                  _tu("c", "make test"), _tr("c", "Exit code: 0"), _tr("zzz", "Exit code 1", True),   # result for an unknown id
                  _tu("d", "npm run lint"), _tr("d", "ok", False)])
        h = self.run_()[0]
        self.assertRegex(h, r"pytest</code> — <span class=unk>result not recorded")
        self.assertRegex(h, r"ruff check \.</code> — <span class=bad>failed")
        self.assertRegex(h, r"make test</code> — <span class=ok>no error reported")
        self.assertRegex(h, r"npm run lint</code> — <span class=ok>no error reported")
        self.assertNotIn(">passed<", h)


class Git(Base):
    def test_author_filter_and_counts_and_folders(self):
        self.commit("src/a.py", "Ann work", "2026-11-05T10:00:00", content="a\nb\n")
        self.commit("docs/n.md", "Bob work", "2026-11-06T10:00:00", author="Bob", content="n\n")
        self.commit("old.py", "Too early", "2026-10-01T10:00:00")
        h, err, rc = self.run_()
        self.assertIn("<b>2</b>commits", h); self.assertIn("2 author(s)", h)
        self.assertIn("<code>src</code>", h); self.assertIn("<code>docs</code>", h)
        h2 = self.run_("--git-author", "Ann")[0]
        self.assertIn("<b>1</b>commits", h2); self.assertIn("filtered by author", h2); self.assertNotIn("Bob work", h2)
        self.assertIn("<b>+2 / −0</b>lines", h2)

    def test_totals_match_independent_numstat(self):
        self.commit("a.py", "one", "2026-11-02T10:00:00", content="1\n2\n3\n")
        self.commit("b.py", "two", "2026-11-03T23:30:00", content="1\n")
        since = w.datetime(2026, 11, 1, tzinfo=w.LOCAL_TZ)
        commits, files, ins, dele, na = w.git_summary(self.repo, since, None)
        tot = 0
        for h, _, _ in commits:
            out = subprocess.run(["git", "-C", self.repo, "show", "--numstat", "--format=", h], capture_output=True, text=True).stdout
            tot += sum(int(l.split("\t")[0]) for l in out.splitlines() if l)
        self.assertEqual((len(commits), ins, na), (2, tot, 1))


class Robustness(Base):
    def test_malformed_logs_dont_crash(self):
        good = _e("user", "Real work")
        self.put(['{"type":"user","timestamp":"2026-11-05T09:00:00Z","message":{"content":"trunc', "\x00\x01garbage", "",
                  '{"type":"user","message":{"content":"no timestamp"}}', '{"type":"user","timestamp":"bad","message":{"content":"bad ts"}}',
                  _e("user", None), _e("user", [None, 3, {"type": "text"}, {"type": "text", "text": None}]),
                  _e("assistant", "not a list"), _e("assistant", [{"type": "tool_use", "name": "Bash", "input": "str"}]), good])
        with open(os.path.join(self.cl, "projects", w.encode_project_dir(self.repo), "bin.jsonl"), "wb") as f:
            f.write(b"\xff\xfe\x00 not utf8 \xc3\x28\n")
        h, err, rc = self.run_()
        self.assertEqual(rc, 0); self.assertIn("Real work", h)
        for bad in ("no timestamp", "bad ts"):
            self.assertNotIn(bad, h)

    def test_cli_errors(self):
        def cli(*a):
            with contextlib.redirect_stderr(io.StringIO()):
                return w.main(list(a))
        self.assertEqual(cli("--repo", os.path.join(self.tmp, "nope")), 1)
        self.assertEqual(cli("--repo", self.repo, "--since", "2026-11-09", "--until", "2026-11-01"), 1)
        self.assertEqual(cli("--repo", self.repo, "--since", "11/01/2026"), 1)
        self.assertEqual(cli("--repo", self.repo, "--claude-dir", self.cl, "--out", os.path.join(self.tmp, "no", "dir", "r.html")), 1)

    def test_large_log_is_fast(self):
        lines = [_e("user", "Task %d" % i, "2026-11-05T09:%02d:%02dZ" % (i // 60 % 60, i % 60), uuid="u%d" % i) if i % 5 == 0
                 else _e("assistant", [{"type": "text", "text": "x" * 200}], uuid="u%d" % i) for i in range(30000)]
        self.put(lines)
        t = time.time()
        self.assertEqual(self.run_()[2], 0)
        self.assertLess(time.time() - t, 20)


class Tags(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.seen, self.bad = set(), []

    def handle_starttag(self, tag, attrs):
        self.seen.add(tag)
        for k, _ in attrs:
            if k.startswith("on"):
                self.bad.append((tag, k))


class Html(Base):
    def test_every_injection_point_is_escaped(self):
        evil = '<img src=x onerror=alert(1)><script>alert(1)</script>'
        self.commit("a.py", "Subject " + evil, "2026-11-05T10:00:00")
        self.put([_e("user", "Do " + evil), _tu("a", "npm test " + evil), _tr("a", "ok", False)])
        out = self.run_("--client", evil, "--author", evil)[0]
        p = Tags(); p.feed(out)
        self.assertEqual(p.bad, [])
        self.assertTrue(p.seen <= {"meta", "title", "style", "h1", "h2", "div", "b", "ol", "ul", "li", "span", "p", "code"}, p.seen)
        self.assertIn("Content-Security-Policy", out)

    def test_empty_report_is_well_formed(self):
        out = self.run_()[0]
        self.assertNotIn("<ol><p>", out)
        self.assertIn("No session activity", out)

    def test_redaction_summary_by_section(self):
        k = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
        self.put([_e("user", "Use token=" + k), _tu("a", "pytest --token=" + k)])
        err = self.run_()[1]
        self.assertIn("by report section", err); self.assertIn("work requests", err); self.assertIn("checks", err)


class ValidateScript(Base):
    def test_validate_local_runs_and_is_content_free(self):
        self.commit("src/a.py", "Secret client subject", "2026-11-05T10:00:00")
        self.put([_e("user", "Build TOPSECRETFEATURE for Initech", cwd=self.repo), _tu("a", "pytest -q"), _tr("a", "ok", False)])
        r = subprocess.run([sys.executable, os.path.join(HERE, "validate_local.py"), "--repo", self.repo, "--claude-dir", self.cl,
                            "--since", "2026-11-01", "--skip-unit-tests", "--summary-out", os.path.join(self.tmp, "sum.txt")],
                           capture_output=True, text=True)
        o = r.stdout
        self.assertRegex(o, r"OVERALL: (PASS|NEEDS REVIEW)")
        for leak in ("TOPSECRETFEATURE", "Initech", "Secret client subject"):
            self.assertNotIn(leak, o + r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "sum.txt")))
        self.assertEqual(r.returncode in (0, 3), True, o + r.stderr)


class Review(Base):
    def test_stale_states_are_evidence_specific(self):
        # pytest runs 3x (first two superseded); lint ran once before an observed edit (edited); build ran once before only a shell change (possible)
        self.put([_tu("a", "pytest -q", "2026-11-05T09:00:00Z"), _tr("a", "ok", None, "2026-11-05T09:00:05Z"),
                  _tu("b", "pytest -q", "2026-11-05T10:00:00Z"), _tr("b", "ok", None, "2026-11-05T10:00:05Z"),
                  _tu("l", "ruff check .", "2026-11-05T10:30:00Z"), _tr("l", "ok", None, "2026-11-05T10:30:05Z"),
                  _tu("n", "npm run build", "2026-11-05T11:45:00Z"), _tr("n", "ok", None, "2026-11-05T11:45:05Z"),
                  _tu("s", "sed -i 's/a/b/' src/x.py", "2026-11-05T11:50:00Z"),
                  _tu("c", "pytest -q", "2026-11-05T12:00:00Z"), _tr("c", "ok", None, "2026-11-05T12:00:05Z")], "one.jsonl")
        self.put([_e("assistant", [{"type": "tool_use", "id": "e", "name": "Edit", "input": {"file_path": os.path.join(self.repo, "z.py")}}],
                     "2026-11-05T11:30:00Z", cwd=self.repo)], "two.jsonl")
        sess, _ = w.load_sessions(self.cl, self.repo, None, None)
        got = [(c["cmd"], st) for c, st in w.check_states(sess)]
        self.assertEqual([st for _, st in got], ["superseded", "superseded", "edited", "possible", "current"])
        h = self.run_()[0]
        self.assertIn("2 were re-run later; 1 were followed by file edits and not re-run; 1 by shell commands that may have changed files and not re-run; 1 have no later change recorded", h)
        self.assertEqual(h.count("(re-run later)"), 2); self.assertEqual(h.count("files were edited after"), 1)

    def test_no_later_change_means_no_flag(self):
        self.put([_e("assistant", [{"type": "tool_use", "id": "e", "name": "Edit", "input": {"file_path": os.path.join(self.repo, "z.py")}}], "2026-11-05T08:00:00Z", cwd=self.repo),
                  _tu("a", "pytest -q", "2026-11-05T09:00:00Z"), _tr("a", "ok", None, "2026-11-05T09:00:05Z")])
        h = self.run_()[0]
        self.assertNotIn("edited after", h); self.assertNotIn("re-run later)", h); self.assertIn("1 have no later change recorded", h)

    def test_redirects_and_devnull_are_not_edits(self):
        self.assertFalse(w.MODIFY_RX.search("pytest 2>&1 | tail"))
        self.assertFalse(w.MODIFY_RX.search("ls > /dev/null"))
        self.assertTrue(w.MODIFY_RX.search("echo x > out.txt")); self.assertTrue(w.MODIFY_RX.search("git checkout -- a.py"))

    def test_many_checks_summary_and_latest_shown(self):
        ls = []
        for i in range(45):
            ls += [_tu("t%d" % i, "pytest -k case%d" % i, "2026-11-05T09:%02d:00Z" % i), _tr("t%d" % i, "ok", None, "2026-11-05T09:%02d:30Z" % i)]
        self.put(ls)
        h = self.run_()[0]
        self.assertIn("45 check command(s) recorded", h); self.assertIn("5 earliest check(s) are omitted", h)
        self.assertIn("case44", h); self.assertNotIn("case0<", h)

    def test_preview_shows_masked_checks_without_secret(self):
        k = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
        self.put([_tu("a", "API_TOKEN=%s npm test" % k), _tr("a", "ok", None), _e("user", "Do it\nsecond line token=%s" % k, ts="2026-11-05T09:01:00Z")])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            w.main(["--repo", self.repo, "--claude-dir", self.cl, "--since", "2026-11-01", "--preview"])
        o = out.getvalue()
        self.assertNotIn(k, o + err.getvalue()); self.assertIn("\u2691", o); self.assertIn("[REDACTED", o); self.assertIn("npm test", o)
        self.assertIn("by report section: checks", err.getvalue()); self.assertNotIn("work requests", err.getvalue().split("by report section")[1])   # 2nd prompt line is never exported

    def test_final_review_is_content_free_and_classifies(self):
        self.commit("a.py", "Initech roadmap", "2026-11-05T10:00:00")
        real = "aB3dE5gH7jK9mN2pQ4sT6vX8zC1fL0wY"
        self.put([_e("user", "Build INITECHFEATURE"), _tu("a", "TOKEN=$MY_TOKEN npm test"), _tr("a", "ok", None),
                  _tu("b", "npm test --api-key=%s" % real), _tr("b", "ok", None),
                  _e("queue-operation", None, operation="enqueue", content="please also add the QUEUEDREQUESTTEXT feature"),
                  _e("assistant", [{"type": "tool_use", "id": "m", "name": "mcp__initech__thing", "input": {}}])])
        r = subprocess.run([sys.executable, os.path.join(HERE, "final_review.py"), "--repo", self.repo, "--claude-dir", self.cl, "--since", "2026-11-01"],
                           capture_output=True, text=True)
        o = r.stdout + r.stderr
        for leak in ("INITECHFEATURE", "QUEUEDREQUESTTEXT", real, "Initech", "MY_TOKEN", "initech"):
            self.assertNotIn(leak, o)
        self.assertIn("matches NO user record", o); self.assertIn("queue-operation[enqueue].content=1", o); self.assertNotIn("queue-operation.timestamp", o)
        self.assertIn("variable/env reference", o); self.assertIn("random-looking", o)
        self.assertIn("mcp__*", o); self.assertIn("OVERALL: NEEDS REVIEW", o)
        self.assertNotIn("[FAIL  ]", o)


class Stabilization(Base):
    def run_review(self, *extra):
        r = subprocess.run([sys.executable, os.path.join(HERE, "final_review.py"), "--repo", self.repo, "--claude-dir", self.cl, "--since", "2026-11-01", *extra],
                           capture_output=True, text=True)
        return r.stdout + r.stderr

    def test_last_prompt_is_a_known_cache_type_and_not_a_request(self):
        self.put([_e("user", "Add CSV export to the assets page", uuid="u1"),
                  json.dumps({"type": "last-prompt", "lastPrompt": "Add CSV export to the assets page", "sessionId": "s"})])
        h = self.run_()[0]
        self.assertIn("<b>1</b>work requests", h)                       # not counted twice
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            w.main(["--repo", self.repo, "--claude-dir", self.cl, "--diagnose"])
        self.assertIn("type=last-prompt: 1", buf.getvalue()); self.assertNotIn("type=other", buf.getvalue()); self.assertNotIn("key=other", buf.getvalue())

    def test_last_prompt_duplicates_are_classified_without_content(self):
        long_ = "Please refactor the asset handoff exporter so it streams rows instead of loading everything " * 3
        cont = "This session is being continued from a previous conversation that ran out of context. Summary follows."
        self.put([_e("user", long_, uuid="u1"), _e("user", cont, uuid="u2"),
                  json.dumps({"type": "last-prompt", "lastPrompt": long_[:60]}),                    # truncated cache of a kept request
                  json.dumps({"type": "last-prompt", "lastPrompt": cont}),                          # cache of a skipped record
                  json.dumps({"type": "last-prompt", "lastPrompt": "A request that appears in no user record at all"})])
        o = self.run_review()
        self.assertIn("last-prompt.lastPrompt: 2 distinct value(s): duplicate of a kept request 1, of a skipped record 0, matches no user record 1", o)
        self.assertIn("Claude Code system text (command / reminder / continuation envelope)=1", o)   # the cached continuation summary is system text, not a request
        self.assertIn("[REVIEW] prompt-style text outside user records that matches NO user record", o)
        for leak in ("asset handoff", "no user record at all", "refactor"):
            self.assertNotIn(leak, o)

    def test_empty_git_repo_is_not_reported_as_non_git(self):
        self.put([_e("user", "First task")])
        h, err, rc = self.run_()
        self.assertEqual(rc, 0); self.assertNotIn("not a git repository", err); self.assertIn("No commits found", h)

    def test_last_prompt_all_duplicates_passes(self):
        txt = "Build the dashboard filter for overdue handoffs"
        self.put([_e("user", txt, uuid="u1"), json.dumps({"type": "last-prompt", "lastPrompt": txt}),
                  _e("user", "<pasted_content id=\"a\">\nFix the export crash on empty rows\n</pasted_content>", uuid="u2"),
                  json.dumps({"type": "last-prompt", "lastPrompt": "[Pasted text #1 +3 lines] Fix the export crash on empty rows"})])
        o = self.run_review()
        self.assertIn("[PASS  ] every prompt-style field outside user records duplicates text", o)

    def test_overlapping_rules_are_one_value_and_exposure_checked(self):
        tok = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
        self.commit("cfg.txt", "add config", "2026-11-05T10:00:00", content="token " + tok + "\n")      # the value is committed in the repo
        self.put([_tu("a", "API_TOKEN=%s npm test" % tok), _tr("a", "ok", None)])
        o = self.run_review()
        self.assertIn("rule hit(s)", o)
        self.assertIn("overlapping a value another rule had already masked", o)
        self.assertIn("1 distinct value(s)", o)
        self.assertIn("in finished report: no; in repo files: YES; in git history: YES", o)
        self.assertIn("looks like a real credential AND is in your repo/history", o)
        self.assertNotIn(tok, o); self.assertNotIn(tok[:12], o)

    def test_validate_local_includes_final_review(self):
        self.put([_e("user", "Do the thing")])
        r = subprocess.run([sys.executable, os.path.join(HERE, "validate_local.py"), "--repo", self.repo, "--claude-dir", self.cl, "--since", "2026-11-01",
                            "--skip-unit-tests", "--summary-out", os.path.join(self.tmp, "s.txt")], capture_output=True, text=True)
        self.assertIn("section order", r.stdout)
        self.assertIn("final review follows", r.stdout); self.assertRegex(r.stdout, r"OVERALL: (PASS|NEEDS REVIEW)")


class ReviewNoise(Base):
    def run_review(self):
        r = subprocess.run([sys.executable, os.path.join(HERE, "final_review.py"), "--repo", self.repo, "--claude-dir", self.cl, "--since", "2026-11-01"],
                           capture_output=True, text=True)
        return r.stdout + r.stderr

    def test_hashes_ids_signatures_system_text_are_metadata_not_missing_requests(self):
        sysprompt = "You are Claude Code, an interactive CLI tool that helps users with software engineering tasks. " * 5
        recs = [_e("user", "Add the export button to the assets page", uuid="u1"),
                json.dumps({"type": "attachment", "attachment": {"type": "skill_listing", "content": sysprompt}}),
                json.dumps({"type": "attachment", "attachment": {"type": "deferred_tools_delta", "addedLines": ["Tool X: does a thing with files and folders"]}}),
                json.dumps({"type": "attachment", "attachment": {"type": "hook_success", "content": "hook finished with exit code zero and no output"}}),
                json.dumps({"type": "progress", "messageId": "a" * 40, "toolUseID": "toolu_01ABCDEFGHIJKLMNOPQRSTUV", "signature": "Eq" + "A1b2" * 20,
                            "sha": "0123456789abcdef" * 3, "data": {"text": "x" * 25}}),
                json.dumps({"type": "ai-title", "aiTitle": "A generated session title that is long enough"}),
                json.dumps({"type": "queue-operation", "operation": "dequeue", "content": "Add the export button to the assets page"}),
                json.dumps({"type": "queue-operation", "operation": "enqueue", "content": "Add the export button to the assets page too please"}),
                json.dumps({"type": "last-prompt", "lastPrompt": "Add the export button to the assets page"})]
        self.put(recs)
        o = self.run_review()
        self.assertIn("[PASS  ] every prompt-style field outside user records duplicates text", o)
        self.assertNotIn("[REVIEW]", o.split("high-severity")[0])
        self.assertIn("no whitespace: id / hash / signature / token-like", o)
        self.assertIn("attachment of a non-prompt kind (skill_listing)", o)
        self.assertIn("queue bookkeeping record (dequeue)", o)
        for leak in ("Claude Code, an interactive", "export button", "generated session title"):
            self.assertNotIn(leak, o)

    def test_genuinely_unmatched_queued_prompt_is_still_reported(self):
        self.put([_e("user", "Add the export button", uuid="u1"),
                  json.dumps({"type": "queue-operation", "operation": "enqueue", "content": "Also rename the handoff table to assets_handoff"}),
                  json.dumps({"type": "attachment", "attachment": {"type": "queued_command", "prompt": "Then update the changelog for this release"}})])
        o = self.run_review()
        self.assertIn("[REVIEW] prompt-style text outside user records that matches NO user record", o)
        self.assertIn("queue-operation[enqueue].content=1", o); self.assertIn("attachment.attachment.prompt=1", o)
        for leak in ("rename the handoff", "changelog"):
            self.assertNotIn(leak, o)

    def test_prompt_count_unchanged_by_alternate_sources(self):
        self.put([_e("user", "Add the export button", uuid="u1"), _e("user", "Fix the CSV header order", uuid="u2"),
                  json.dumps({"type": "queue-operation", "operation": "enqueue", "content": "Fix the CSV header order"}),
                  json.dumps({"type": "last-prompt", "lastPrompt": "Fix the CSV header order"})])
        self.assertIn("<b>2</b>work requests", self.run_()[0])


class RequestBlob(Base):
    SYS = "You are Claude Code, Anthropic's official CLI for Claude. Follow the instructions below carefully. " * 4

    def payload(self):
        return {"model": "m", "system": [{"type": "text", "text": self.SYS}],
                "tools": [{"name": "Bash", "description": "Executes a given bash command in a persistent shell session " * 3}],
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "Add the export button to the assets page"}]},
                    {"role": "assistant", "content": [{"type": "text", "text": "I will add the export button now and then run the tests."},
                                                      {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q"}}]},
                    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "collected 12 items, all of them passed in 0.4s"}]},
                    {"role": "user", "content": [{"type": "text", "text": "<system-reminder>Remember the project conventions documented in CLAUDE.md</system-reminder>"}]},
                    {"role": "system", "content": "A system role message that is definitely not typed by the user at all"},
                    {"role": "user", "content": [{"type": "text", "text": "Injected context block describing the repository layout and recent changes"}]}]}

    def review(self, recs):
        self.put(recs)
        r = subprocess.run([sys.executable, os.path.join(HERE, "final_review.py"), "--repo", self.repo, "--claude-dir", self.cl, "--since", "2026-11-01"],
                           capture_output=True, text=True)
        return r.stdout + r.stderr

    def check(self, o):
        self.assertNotIn("[REVIEW] prompt-style", o)                                       # roles decide: nothing here is a missing request
        self.assertIn("[PASS  ] every prompt-style field outside user records duplicates text", o)
        self.assertIn("message with role 'assistant' (not user-authored)", o)
        self.assertIn("message with role 'system' (not user-authored)", o)
        self.assertIn("system prompt / tool definitions (not user-authored)", o)
        self.assertIn("user-role text: system/command text", o)                             # the <system-reminder> block
        self.assertIn("[INFO  ] user-role text inside replayed API payloads with no matching user record", o)
        self.assertIn("api-request-blob.body.messages[].message[user]=1", o)               # only the one injected, unmatched user-role text
        for leak in ("Claude Code, Anthropic", "export button", "Executes a given bash", "tests", "CLAUDE.md", "Injected context", "collected 12"):
            self.assertNotIn(leak, o)

    def test_blob_content_is_judged_by_role(self):
        o = self.review([_e("user", "Add the export button to the assets page", uuid="u1"),
                         json.dumps({"type": "api-request-blob", "body": self.payload()})])
        self.check(o)

    def test_serialized_blob_is_parsed_the_same_way(self):
        o = self.review([_e("user", "Add the export button to the assets page", uuid="u1"),
                         json.dumps({"type": "api-request-blob", "blob": json.dumps({"body": self.payload()})})])
        self.assertNotIn("[REVIEW] prompt-style", o); self.assertIn("message with role 'assistant'", o)
        self.assertIn("api-request-blob.blob.<json>.body.messages[].message[user]=1", o)

    def test_blob_does_not_change_the_request_count_or_hide_real_gaps(self):
        recs = [_e("user", "Add the export button to the assets page", uuid="u1"), json.dumps({"type": "api-request-blob", "body": self.payload()}),
                json.dumps({"type": "queue-operation", "operation": "enqueue", "content": "A genuinely separate typed instruction nobody logged"})]
        o = self.review(recs)
        self.assertIn("[REVIEW] prompt-style text outside user records that matches NO user record", o)
        self.assertIn("queue-operation[enqueue].content=1", o); self.assertNotIn("api-request-blob.body", o.split("[REVIEW]")[1].split("\n")[0])
        self.assertIn("<b>1</b>work requests", self.run_()[0])


if __name__ == "__main__":
    unittest.main()
