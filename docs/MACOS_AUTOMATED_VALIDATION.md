# Automated macOS validation

```bash
cd /path/to/WorkReceipt && git checkout feature/client-safe-mode && git pull && scripts/validate_macos.sh
```
Quit WorkReceipt first (it would otherwise change the real-data fingerprint), stay logged in with the screen unlocked (a window opens briefly), and have network for the one-time `pip install`. Options: `--keep` keeps the temp sandbox, `--quick` skips the regression suite (the run is then reported INCOMPLETE, never PASS). Exit code: 0 PASS, 1 a required check failed, 2 incomplete. The report is also saved to `validation-results/` (git-ignored).

## What it does
| # | Stage | Where it runs |
|---|---|---|
| 1 | Temp sandbox + synthetic hostile workspace (fake credentials, internal hosts, private terms). Real app data and reports folders are fingerprinted before and after; any change is a FAIL. Nothing reads `~/.claude`. | `validate_macos.sh`, `wrv.py` |
| 2 | Existing regression and security suite (`pytest`, unmodified assertions). Fails if the Client-Safe backend (>=30) or browser (>=10) tests did not actually run. Skips are listed with reasons. | `validate_macos.sh`, `wrv_report.py` |
| 3 | Complete client workflow over the real HTTP routes: preview, approve, export HTML + PDF; preview byte-identical to the file; history marked client. | `wrv.workflow` |
| 4 | PDF produced by the app's own WKWebView path (`desktop.main.install_native_backends`, same wiring as the app); producer must be Quartz/WebKit, not Chrome. | `macos_native.py` (real AppKit loop) |
| 5 | Independent PDFKit check (does not reuse the product's validator): text vs HTML, no extra or missing text, metadata allowlist, annotations, forbidden objects, invisible-text render mode, Letter size. | `pdfkit_check.py` (usable by hand: `python scripts/pdfkit_check.py file.pdf --html file.html`) |
| 6 | Canary scan (credential, internal host/service, private repo, path, user, unapproved client, file and commit text) over HTML, PDF text, PDF metadata, file names, API responses, history. | `wrv.workflow` |
| 7 | Approval invalidation (8 content edits, period change, weakened review, expired token), forged/replayed/malformed tokens, 13 unsafe drafts blocked at preview/approve/export, requests without the page token or from a foreign Host refused, nothing written on any refusal. | `wrv.workflow`, `macos_native.py` |
| 8 | Fail-closed and teeth checks on real WKWebView PDFs: inspector returning nothing or raising blocks export; injected hidden text, private PDF title and links must be caught by BOTH the product validator and the independent checker; tampered HTML rejected. | `macos_native.py` |
| 9 | Live app: launches `desktop/main.py` (and `dist/WorkReceipt.app` if built, or `WR_APP_BIN`) against the sandbox; waits for the native window; loopback-only listener; a real window of at least minimum size exists; app uses the sandbox data folder and reports native status; stages 3, 6, 7 repeat against the live app; clean shutdown with no leftover process or port. | `macos_app.py` |

## What was tested where
- **Tested on Linux** (`--selftest`: Chrome and poppler stand in for WebKit and PDFKit; every selftest line is labelled "not macOS evidence", and the final line says "SELFTEST PASS ... NOT macOS validation"): sandbox and real-data fingerprint, the shared workflow and all negative cases, the independent checker's logic, the report and exit codes, the full regression suite. Mutation check: disabling `token_valid` and `validate_pdf` makes 9 stages FAIL, so the checks have teeth. `test_validation_scripts.py` keeps the checker, report logic and script syntax under the normal suite.
- **Written but NOT executed until you run it on a Mac**: the PyObjC/AppKit event loop, `pdf_mac.render_pdf` through the harness, PDFKit reads in `pdfkit_check.py`, the live-app launch (`lsof`, `CGWindowListCopyWindowInfo`, SIGTERM shutdown), and the packaged-app branch. On Linux these stages report BLOCKED (exit 2), never PASS.

## Limits
- The window's rendered contents are not inspected (that needs Screen Recording permission); the window is verified to exist at the right size, serve the app, and answer the native-status bridge.
- Native dialogs (folder picker, Open, Show in Finder) are not automated.
- A heuristic cannot see confidential facts written as ordinary prose; this validates the controls, not your wording.
- If a pre-existing test fails on macOS it is reported as a FAIL, not skipped.
