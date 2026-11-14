"""Regression tests: Claude Code session artifacts must not become client-facing work items."""
import contextlib, io, json, os, re, subprocess, tempfile, unittest
import workreceipt as w

GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
CONT = ("This session is being continued from a previous conversation that ran out of context. "
        "The conversation is summarized below:\nAnalysis:\nThe user asked for X ...")


def _e(t, c, ts="2026-11-05T09:00:00Z", **kw):
    return json.dumps({"type": t, "timestamp": ts, "message": {"role": t, "content": c}, **kw})


class Artifacts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "proj")
        os.makedirs(self.repo)
        subprocess.run(["git", "-C", self.repo, "init", "-q"])
        self.cl = os.path.join(self.tmp, "c")

    def put(self, lines):
        d = os.path.join(self.cl, "projects", w.encode_project_dir(self.repo))
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "s.jsonl"), "w").write("\n".join(lines) + "\n")

    def report(self, allow_high=True):
        out = os.path.join(self.tmp, "o.html")
        err = io.StringIO()
        args = ["--repo", self.repo, "--claude-dir", self.cl, "--since", "2026-11-01", "--out", out]
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = w.main(args + (["--allow-high"] if allow_high else []))
        return (open(out).read() if os.path.exists(out) else ""), err.getvalue(), rc

    def items(self, lines):
        self.put(lines)
        h = self.report()[0]
        return [re.sub(r"&[a-z]+;", "", t) for t in re.findall(r"<li><span contenteditable>(.*?)</span> <span class=small>\(", h)]

    # --- artifacts that must disappear ---
    def test_empty_paste_markers_dropped(self):
        self.assertEqual(self.items([_e("user", '<pasted_content id="d2ea">'), _e("user", '<pasted_content id="d2ea"/>'),
                                     _e("user", '<pasted_content id="d2ea"></pasted_content>')]), [])

    def test_wrapped_body_is_the_request_not_the_tag(self):
        body = '<pasted_content id="d2ea">\nAdd CSV export to the assets page\nmore detail\n</pasted_content>'
        self.assertEqual(self.items([_e("user", body), _e("user", [{"type": "text", "text": body}], ts="2026-11-05T09:01:00Z"),
                                     _e("user", '<pasted_content id="d2ea">\nAdd CSV export to the assets page', ts="2026-11-05T09:02:00Z")]),
                         ["Add CSV export to the assets page"] * 3)

    def test_wrapped_system_text_still_skipped(self):
        self.assertEqual(self.items([_e("user", '<pasted_content id="a">\n' + CONT + '\n</pasted_content>'),
                                     _e("user", '<pasted_content id="b">\n<task-notification>x</task-notification>\n</pasted_content>')]), [])

    def test_task_notification_envelope_skipped_but_real_text_kept(self):
        n = "<task-notification>\n<task-id>b1x</task-id>\n<status>completed</status>\n<summary>done</summary>\n</task-notification>"
        got = self.items([_e("user", n, ts="2026-11-05T09:01:00Z"),
                          _e("user", [{"type": "text", "text": n}, {"type": "text", "text": "Now deploy the fix"}], ts="2026-11-05T09:02:00Z"),
                          _e("user", "Check why the task-notification tag shows up in reports", ts="2026-11-05T09:03:00Z")])
        self.assertEqual(got, ["Now deploy the fix", "Check why the task-notification tag shows up in reports"])

    def test_bracket_placeholders_only(self):
        self.assertEqual(self.items([_e("user", "[Pasted text #1 +40 lines]"), _e("user", "[Image #2]")]), [])

    def test_continuation_summary_by_text_and_by_flag(self):
        got = self.items([_e("user", CONT), _e("user", [{"type": "text", "text": CONT}]),
                          _e("user", "Anything at all", isCompactSummary=True),
                          _e("user", "transcript only", isVisibleInTranscriptOnly=True)])
        self.assertEqual(got, [])

    def test_cli_launch_and_bash_mode(self):
        got = self.items([_e("user", "claude --dangerously-skip-permissions"), _e("user", "claude"),
                          _e("user", "<bash-input>ls</bash-input>"), _e("user", "<bash-stdout>x</bash-stdout>")])
        self.assertEqual(got, [])

    # --- genuine requests that must survive ---
    def test_real_requests_survive(self):
        want = ["Make claude --dangerously-skip-permissions optional in the launcher",
                "Add a pasted_content field to the upload form",
                "Summarize this session for the changelog",
                "Continue the migration to Postgres"]
        self.assertEqual(self.items([_e("user", t, ts="2026-11-05T09:0%d:00Z" % i) for i, t in enumerate(want)]), want)

    def test_instruction_next_to_wrapper_is_kept_and_wrapper_dropped(self):
        w1 = '<pasted_content id="d2ea">\nFix the crash shown above\nboom\n</pasted_content>'
        w2 = 'Fix the checkout total\n<pasted_content id="x1">\nlog line\n</pasted_content>'
        w3 = "Refactor this [Pasted text #2 +10 lines]"
        w4 = [{"type": "text", "text": CONT}, {"type": "text", "text": "Now add dark mode"}]
        got = self.items([_e("user", w1, ts="2026-11-05T09:01:00Z"), _e("user", w2, ts="2026-11-05T09:02:00Z"),
                          _e("user", w3, ts="2026-11-05T09:03:00Z"), _e("user", w4, ts="2026-11-05T09:04:00Z")])
        self.assertEqual(got, ["Fix the crash shown above", "Fix the checkout total", "Refactor this", "Now add dark mode"])

    # --- reporting honesty ---
    def test_report_says_requested_not_completed(self):
        self.put([_e("user", "Add login form")])
        h = self.report()[0]
        self.assertIn("Work requested", h)
        self.assertNotIn("What was done", h)
        self.assertIn("does not mean the work was completed", h)

    def test_skips_are_reported_not_silent(self):
        self.put([_e("user", CONT), _e("user", "claude --dangerously-skip-permissions"), _e("user", "Real task")])
        err = self.report()[1]
        self.assertIn("skipped", err)
        self.assertIn("continuation summary", err)
        self.assertIn("terminal command", err)

    # --- security unchanged ---
    def test_redaction_still_applies_next_to_wrapper(self):
        self.put([_e("user", 'Fix it, token=' + GH + '\n<pasted_content id="a">\nstuff\n</pasted_content>')])
        h, _, rc = self.report()
        self.assertNotIn(GH, h)
        self.assertIn("Fix it", h)
        self.assertEqual(self.report(allow_high=False)[2], 2)

    def test_secret_inside_wrapped_body_is_masked_and_blocks(self):
        k = "AKIA" + "ABCDEFGHIJKLMNOP"
        self.put([_e("user", '<pasted_content id="a">\nUse AWS_KEY=' + k + ' for the upload\n</pasted_content>')])
        self.assertNotIn(k, self.report()[0])
        self.assertEqual(self.report(allow_high=False)[2], 2)

    def test_diagnose_reports_classes_without_content(self):
        self.put([_e("user", CONT), _e("user", "TOPSECRETCONTENT do work"), _e("user", "x", isCompactSummary=True),
                  _e("user", '<pasted_content id="zz">\nTOPSECRETCONTENT\n</pasted_content>'),
                  _e("user", "<task-notification>q</task-notification>"), _e("user", "<weird-tag>q</weird-tag>")])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            w.main(["--repo", self.repo, "--claude-dir", self.cl, "--diagnose"])
        o = buf.getvalue()
        self.assertIn("user prompt: kept: 3", o)
        self.assertIn("user text block starts <tag>: task-notification: 1", o)
        self.assertIn("user text block starts <tag>: weird-tag: 1", o)
        self.assertIn("pasted_content wrapper: closed, has body: 1", o)
        self.assertIn("user prompt: skipped continuation summary: 1", o)
        self.assertNotIn("TOPSECRETCONTENT", o)


if __name__ == "__main__":
    unittest.main()
