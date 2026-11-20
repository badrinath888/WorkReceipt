"""Guards the macOS CI workflow config (text-level; no YAML dependency)."""
import os, unittest
W = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".github", "workflows", "macos-validation.yml")).read()
W = "\n".join(l.split("  #")[0] for l in W.splitlines() if not l.lstrip().startswith("#")) + "\n"   # ignore comments


class CIWorkflow(unittest.TestCase):
    def test_runs_the_full_harness_unweakened(self):
        self.assertIn("./scripts/validate_macos.sh --rebuild", W)
        self.assertNotIn("--quick", W)
        step = W.split("- name: Full native validation")[1].split("- name:")[0]       # the gating step is never non-fatal
        self.assertNotIn("continue-on-error", step)
        self.assertNotIn("|| true\n      - name: Full", W)

    def test_triggers_and_safety(self):
        for s in ("pull_request:", "workflow_dispatch:", "branches: [main]", "feature/**"): self.assertIn(s, W)
        self.assertNotIn("pull_request_target", W)
        self.assertIn("permissions:\n  contents: read", W)
        self.assertNotIn("write", W.split("permissions:")[1].split("concurrency:")[0])
        self.assertIn("cancel-in-progress: true", W); self.assertIn("timeout-minutes:", W)

    def test_diagnostics_always_uploaded_and_no_real_data(self):
        self.assertIn("if: always()\n        uses: actions/upload-artifact", W)
        for bad in ("~/.claude", "Library/Application Support"): self.assertNotIn(bad, W)


if __name__ == "__main__":
    unittest.main()
