# Autonomous macOS pipeline

`.github/workflows/macos-validation.yml` runs `./scripts/validate_macos.sh --rebuild` on a GitHub-hosted `macos-latest` (Apple Silicon, GUI session). Details of the stages: `MACOS_AUTOMATED_VALIDATION.md`.

- **Triggers:** PRs to `main`, pushes to `feature/**`, manual dispatch. One run per ref (newer cancels older); 45 min timeout.
- **Security:** `contents: read` only, `pull_request` (never `pull_request_target`), no secrets, no merge/deploy/release.
- **Pass/fail:** the script's exit code is the job result (0 pass; 1 failed check; 2 blocked/incomplete). Nothing is skipped or marked non-fatal.
- **Diagnostics (always uploaded, 14 days):** artifact `macos-validation-<run id>` = report, `results.jsonl`, junit, logs, `context.txt` (commit, runner OS/arch/image). Synthetic sandbox data only. The job summary shows the report.
- **Reproduce:** `./scripts/validate_macos.sh --rebuild --keep`.

## Status (run 44577348379, commit c34f414, macOS 26.7.2 arm64)

CI triggered and completed: **FAILED, correctly.** All stages ran; the packaged app passed everything. Two required checks failed (`native:` and `source app: approve and export HTML + PDF`): on this runner the script-run PDF gets Creator = a 6-letter string (`not_an_engine_string`), which `client_safe.py` refuses (only engine names or exactly `WorkReceipt` are allowed). Not fixed here: accepting another Creator value is a privacy-validator decision, not a CI change. Assertions are unchanged.
