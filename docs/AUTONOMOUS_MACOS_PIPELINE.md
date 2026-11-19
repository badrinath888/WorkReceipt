# Autonomous macOS pipeline

`.github/workflows/macos-validation.yml` runs `./scripts/validate_macos.sh --rebuild` on a GitHub-hosted `macos-latest` (Apple Silicon, GUI session). Details of the stages: `MACOS_AUTOMATED_VALIDATION.md`.

- **Triggers:** PRs to `main`, pushes to `feature/**`, manual dispatch. One run per ref (newer cancels older); 45 min timeout.
- **Security:** `contents: read` only, `pull_request` (never `pull_request_target`), no secrets, no merge/deploy/release.
- **Pass/fail:** the script's exit code is the job result (0 pass; 1 failed check; 2 blocked/incomplete). Nothing is skipped or marked non-fatal.
- **Diagnostics (always uploaded, 14 days):** artifact `macos-validation-<run id>` = report, `results.jsonl`, junit, logs, `context.txt` (commit, runner OS/arch/image). Synthetic sandbox data only. The job summary shows the report.
- **Reproduce:** `./scripts/validate_macos.sh --rebuild --keep`.

## Status

Run 44589291820 (commit 3da3497, macOS 26.7.2 arm64): **71 PASS, 0 FAIL, 0 BLOCKED, 0 SKIP.** https://github.com/badrinath888/WorkReceipt/actions/runs/44589291820

History: the first run (44577348379) failed the script-run "approve and export" stages. A diagnostic probe showed Creator was `'Python'`, taken from the host `Python.app` `CFBundleName` (not the process name; `setProcessName` has no effect). `desktop/pdf_mac.py:_stamp_creator` now sets the in-memory `CFBundleName` to the fixed product name before the print job. The Creator allowlist is unchanged (`test_pdf_creator_stamp.py` asserts `Python` is still refused). macOS has no `timeout(1)`; use step `timeout-minutes`.
