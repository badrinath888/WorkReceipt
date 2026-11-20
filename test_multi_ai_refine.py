"""PR #3 refinement (TDD): per-request provider attribution, conservative cross-provider dedup, Client-Safe e2e with Codex+OpenCode, version.
SYNTHETIC data only: every secret/path/host below is made up."""
import json, os, re, shutil, subprocess, tempfile, unittest
from datetime import datetime, timezone

import app_core as core, workreceipt as w
from test_client_safe import PERIOD, draft, item, texts_of
from test_phase1 import disp
from test_providers import mkrepo

T = "2026-03-02T10:00:00Z"
MS = int(datetime(2026, 3, 2, 10, tzinfo=timezone.utc).timestamp() * 1000)
AKIA = "AKIAQWERTYUIOPASDFGH"
HAS_PDF = bool(core.chrome_path() and shutil.which("pdftotext") and shutil.which("pdfinfo"))


def codex_log(d, repo, prompts, name="rollout-cx-9f3a.jsonl"):
    p = os.path.join(d, "codex", "sessions", "2026", "03", "02"); os.makedirs(p, exist_ok=True)
    ev = [{"timestamp": T, "type": "session_meta", "payload": {"cwd": repo, "model_provider": "openai-zeta"}}]
    ev += [{"timestamp": ts, "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": t}]}} for ts, t in prompts]
    open(os.path.join(p, name), "w").write("\n".join(map(json.dumps, ev)) + "\n")
    return os.path.join(d, "codex")


def opencode_log(d, repo, prompts, sid="ses_oc_77b1"):
    st = os.path.join(d, "oc", "storage")
    for x in (f"session/p1", f"message/{sid}"):
        os.makedirs(os.path.join(st, x), exist_ok=True)
    wr = lambda rel, o: (os.makedirs(os.path.dirname(os.path.join(st, rel)), exist_ok=True), open(os.path.join(st, rel), "w").write(json.dumps(o)))
    wr(f"session/p1/{sid}.json", {"id": sid, "directory": repo})
    for i, (ms, t) in enumerate(prompts):
        wr(f"message/{sid}/msg_{i}.json", {"id": f"msg_{sid}_{i}", "role": "user", "time": {"created": ms}})
        wr(f"part/msg_{sid}_{i}/prt_1.json", {"type": "text", "text": t})
    return os.path.join(d, "oc")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name; self.repo = mkrepo(self.d)

    def settings(self, cx=None, oc=None):
        return dict(core.DEFAULTS, claude_dir=os.path.join(self.d, "none"), codex_dir=cx or os.path.join(self.d, "nocx"), opencode_dir=oc or os.path.join(self.d, "nooc"),
                    out_dir=os.path.join(self.d, "out"), providers={"claude": False, "codex": bool(cx), "opencode": bool(oc)})

    def build(self, s):
        return core.build({"repo": self.repo}, s)


class Attribution(Base):
    def test_each_request_carries_its_provider(self):
        s = self.settings(codex_log(self.d, self.repo, [(T, "Add login page")]), opencode_log(self.d, self.repo, [(MS + 60000, "Fix the parser")]))
        items = self.build(s)["ctx"]["items"]
        self.assertEqual([(i["source"], i["sources"]) for i in items], [("Codex CLI", ["Codex CLI"]), ("OpenCode", ["OpenCode"])])

    def test_private_report_and_ui_payload_show_the_source_per_request(self):
        s = self.settings(codex_log(self.d, self.repo, [(T, "Add login page")]))
        b = self.build(s)
        self.assertIn("Codex CLI", w.render(b["ctx"]).split("<h2><span class=n>2</span>")[0])      # inside the Work requested section
        self.assertEqual(core.summary(b)["requests"][0]["source"], "Codex CLI")
        self.assertIn("source", open(os.path.join(os.path.dirname(__file__), "ui", "app.js"), encoding="utf-8").read().split("function vSettings")[0])


class Dedup(Base):
    def merged(self, cx, oc):
        return self.build(self.settings(codex_log(self.d, self.repo, cx), opencode_log(self.d, self.repo, oc)))["ctx"]["items"]

    def test_identical_request_at_the_same_instant_in_two_tools_is_one_item_with_both_sources(self):
        (it,) = self.merged([(T, "Add login page")], [(MS, "Add login page")])
        self.assertEqual(it["sources"], ["Codex CLI", "OpenCode"])

    def test_similar_text_is_never_merged(self):
        self.assertEqual(len(self.merged([(T, "Add login page")], [(MS, "Add login page.")])), 2)
        self.assertEqual(len(self.merged([(T, "Add login page")], [(MS, "Add the login page")])), 2)

    def test_same_text_at_different_times_is_never_merged(self):
        self.assertEqual(len(self.merged([(T, "Add login page")], [(MS + 1000, "Add login page")])), 2)

    def test_repeats_inside_one_provider_are_never_merged(self):
        self.assertEqual(len(self.merged([(T, "Run it again"), (T, "Run it again")], [(MS + 5000, "Other")])), 3)


class ClientSafeE2E(Base):
    SECRET_PROMPT = f"Wire zq-ledger-db behind vortex-mesh using {AKIA} in /Users/quill-zed/work/zq-secret-app/src/pay.py"
    CANARIES = {"aws key": AKIA, "internal db": "zq-ledger-db", "internal svc": "vortex-mesh", "local user": "quill-zed", "abs path": "/zq-secret-app/",
                "codex": "codex", "opencode": "opencode", "codex session": "rollout-cx-9f3a", "oc session": "ses_oc_77b1", "provider meta": "openai-zeta", "tool label": "codex cli"}

    def flow(self):
        s = self.settings(codex_log(self.d, self.repo, [(T, self.SECRET_PROMPT)]), opencode_log(self.d, self.repo, [(MS + 60000, "Polish the zq-ledger-db report screen")]))
        o = {"repo": self.repo, "since": "2026-03-01"}
        b = core.build(o, s); ap = disp(b["findings"])
        commits = [c[0] for c in b["ctx"]["commits"]]
        return s, o, b, ap, commits

    def no_leaks(self, text, label):
        for k, v in self.CANARIES.items():
            self.assertNotIn(v.lower(), text.lower(), f"{k} leaked {label}")

    def test_private_evidence_does_hold_the_canaries(self):                           # the test below is not vacuous
        s, o, b, ap, commits = self.flow()
        priv = w.render(b["ctx"]) + json.dumps(b["findings"])
        self.assertIn("Codex CLI", priv); self.assertTrue(b["findings"])

    def test_html_and_pdf_export_leaks_nothing_private(self):
        s, o, b, ap, commits = self.flow()
        d = draft([item("Built the payment screen", status="delivered", commits=commits[:1]), item("Polished the reporting screen")], verification={"mode": "none"})
        pv = core.client_preview(o, d, ap, s); self.assertTrue(pv["ok"], pv)
        t = core.client_approve(o, d, ap, {"privacy_review": True, "content_hash": pv["content_hash"]}, s)["token"]
        r = core.client_export(o, d, ap, t, HAS_PDF, s); self.assertTrue(r["ok"], r)
        html = texts_of(r["html_path"]); self.assertEqual(html, pv["html"]); self.no_leaks(html, "in html")
        self.assertIn("Built the payment screen", html)
        if HAS_PDF:
            self.assertTrue(r["pdf_path"] and not r["pdf_failed"], r)
            self.no_leaks(subprocess.run(["pdftotext", "-layout", r["pdf_path"], "-"], capture_output=True, text=True).stdout, "in pdf text")
            self.no_leaks(subprocess.run(["pdfinfo", r["pdf_path"]], capture_output=True, text=True).stdout, "in pdf metadata")
        self.no_leaks(json.dumps(core.history()), "in history")
        self.no_leaks(" ".join(os.listdir(s["out_dir"])), "in file names")

    def test_unreviewed_provider_findings_block_export(self):
        s, o, b, ap, commits = self.flow()
        d = draft([item("Built the payment screen")]); pv = core.client_preview(o, d, ap, s)
        t = core.client_approve(o, d, ap, {"privacy_review": True, "content_hash": pv["content_hash"]}, s)["token"]
        r = core.client_export(o, d, {}, t, False, s)
        self.assertEqual(r["reason"], "findings"); self.assertFalse(os.path.isdir(s["out_dir"]) and os.listdir(s["out_dir"]))


class Version(unittest.TestCase):
    def test_version_is_0_7_0_everywhere(self):
        root = os.path.dirname(os.path.abspath(__file__))
        py = re.search(r'^version\s*=\s*"([^"]+)"', open(os.path.join(root, "pyproject.toml")).read(), re.M).group(1)
        self.assertEqual((core.VERSION, py), ("0.7.0", "0.7.0"))
        self.assertIn("v0.7.0", open(os.path.join(root, "docs", "MULTI_AI.md")).read())


if __name__ == "__main__":
    unittest.main()
