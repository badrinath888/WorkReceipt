"""v0.7.0 multi-provider tests. Synthetic fixtures only; Codex/OpenCode layouts are experimental (see providers.py)."""
import json, os, subprocess, tempfile, unittest
from datetime import datetime, timezone

import app_core as core
import providers as P
import workreceipt as w

T = "2026-03-02T10:00:00Z"


def mkrepo(d):
    r = os.path.join(d, "proj"); os.makedirs(r)
    g = lambda *a: subprocess.run(["git", "-C", r, *a], check=True, capture_output=True)
    g("init", "-q"); g("config", "user.email", "a@b.c"); g("config", "user.name", "A")
    open(os.path.join(r, "a.txt"), "w").write("x"); g("add", "."); g("-c", "commit.gpgsign=false", "commit", "-qm", "Add feature")
    return r


def codex(d, r):
    p = os.path.join(d, "codex", "sessions", "2026", "03", "02"); os.makedirs(p)
    ev = [{"timestamp": T, "type": "session_meta", "payload": {"cwd": r}},
          {"timestamp": T, "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Add login page"}]}},
          {"timestamp": T, "type": "response_item", "payload": {"type": "function_call", "name": "shell", "call_id": "c1", "arguments": json.dumps({"command": ["pytest", "-q"]})}},
          {"timestamp": T, "type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": json.dumps({"metadata": {"exit_code": 0}})}},
          {"timestamp": T, "type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch", "input": "*** Update File: a.txt\n"}}]
    open(os.path.join(p, "rollout-1.jsonl"), "w").write("\n".join(map(json.dumps, ev)) + "\nnot json\n")
    other = [{"timestamp": T, "type": "session_meta", "payload": {"cwd": "/elsewhere"}}, ev[1]]
    open(os.path.join(p, "rollout-2.jsonl"), "w").write("\n".join(map(json.dumps, other)))
    return os.path.join(d, "codex")


def opencode(d, r):
    st = os.path.join(d, "oc", "storage")
    for x in ("session/p1", "message/ses_1", "part/msg_1", "part/msg_2"):
        os.makedirs(os.path.join(st, x))
    ms = int(datetime(2026, 3, 2, 10, tzinfo=timezone.utc).timestamp() * 1000)
    wr = lambda rel, o: open(os.path.join(st, rel), "w").write(json.dumps(o))
    wr("session/p1/ses_1.json", {"id": "ses_1", "directory": r})
    wr("message/ses_1/msg_1.json", {"id": "msg_1", "role": "user", "time": {"created": ms}})
    wr("message/ses_1/msg_2.json", {"id": "msg_2", "role": "assistant", "time": {"created": ms + 1}})
    wr("part/msg_1/prt_1.json", {"type": "text", "text": "Fix the parser"})
    wr("part/msg_2/prt_1.json", {"type": "tool", "tool": "bash", "state": {"status": "error", "input": {"command": "npm test"}}})
    wr("part/msg_2/prt_2.json", {"type": "tool", "tool": "edit", "state": {"input": {"filePath": os.path.join(r, "a.txt")}}})
    return os.path.join(d, "oc")


class T7(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); d = self.tmp.name
        self.repo = mkrepo(d)
        self.s = dict(core.DEFAULTS, claude_dir=os.path.join(d, "none"), codex_dir=codex(d, self.repo), opencode_dir=opencode(d, self.repo),
                      providers={"claude": False, "codex": True, "opencode": True})
    tearDown = lambda self: self.tmp.cleanup()

    def test_codex(self):
        (s,) = P.load_codex(self.s["codex_dir"], self.repo, None, None)
        self.assertEqual(s["provider"], "codex")
        self.assertEqual([p["text"] for p in s["prompts"]], ["Add login page"])
        self.assertEqual(s["checks"][0]["ok"], True)
        self.assertEqual(len(s["files"]), 1)

    def test_opencode(self):
        (s,) = P.load_opencode(self.s["opencode_dir"], self.repo, None, None)
        self.assertEqual([p["text"] for p in s["prompts"]], ["Fix the parser"])
        self.assertEqual(s["checks"][0]["ok"], False)
        self.assertEqual(len(s["files"]), 1)

    def test_multi_provider_build_and_discovery(self):
        b = core.build({"repo": self.repo}, self.s)
        self.assertEqual(b["ctx"]["n_items"], 2)
        self.assertEqual(b["ctx"]["tools"], ["Codex CLI", "OpenCode"])
        ps = core.all_projects(self.s)
        self.assertEqual([(p["sessions"], sorted(p["providers"])) for p in ps if p["path"] == self.repo], [(2, ["codex", "opencode"])])

    def test_git_only(self):
        self.s["providers"] = {"claude": False, "codex": False, "opencode": False}
        b = core.build({"repo": self.repo}, self.s)
        self.assertEqual((b["ctx"]["n_items"], b["ctx"]["n_commits"], b["ctx"]["tools"]), (0, 1, []))
        self.assertIn("Git-only", w.render(b["ctx"]))

    def test_redaction_applies_to_every_provider(self):
        p = os.path.join(self.s["codex_dir"], "sessions", "2026", "03", "02", "rollout-1.jsonl")
        ev = {"timestamp": T, "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "use key sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}]}}
        open(p, "a").write(json.dumps(ev) + "\n")
        b = core.build({"repo": self.repo}, self.s)
        self.assertNotIn("AAAAAAAAAAAAAAAA", repr(b["ctx"]))
        self.assertTrue(b["findings"])

    def test_broken_adapter_isolated(self):
        self.s["providers"]["codex"] = True
        P.LOADERS["codex"], orig = (lambda *a, **k: 1 / 0), P.LOADERS["codex"]
        try:
            sk = core.Counter(); out = P.load_all(self.s, self.repo, None, None, sk)
        finally:
            P.LOADERS["codex"] = orig
        self.assertEqual(len(out), 1)                       # OpenCode still loaded
        self.assertEqual(sk["codex adapter error"], 1)

    def test_settings_roundtrip_defaults_claude_only(self):
        self.assertEqual(P.enabled({}), ["claude"])
        self.assertEqual(core.DEFAULTS["providers"], {"claude": True, "codex": False, "opencode": False})


if __name__ == "__main__":
    unittest.main()
