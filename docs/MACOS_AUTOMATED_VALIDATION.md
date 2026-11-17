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


## First Mac run (macOS 27.2, 23 PASS / 5 FAIL) and what was found
| Failed stage | Root cause | Class | Fix |
|---|---|---|---|
| Native HTML/PDF export: `validation ['metadata']` | The PDF metadata rule rejected an empty Creator/Producer. WKWebView/Quartz PDFs carry a Producer but no Creator; PDFKit reports the missing field as `""`, which did not match the engine-string pattern. Most likely cause (inferred from the code; the exact fields were not in the report). | Product defect (macOS compatibility) | `client_safe.pdf_metadata_problems`: an empty Creator/Producer is allowed. Every other rule is unchanged (Title empty or the report title, Author/Subject/Keywords/other fields empty, no private term or local account/machine name anywhere). Refusals name the field (`metadata_author`...), never the value. |
| Source app and packaged app: `approval was refused` | Finding ids are salted per process (`app_core._SALT`), so the harness computed its Privacy-Center review in its own process and the launched app saw every high finding as unreviewed (`reason=findings`). Reproduced on Linux with a second process. | Test-harness defect; the refusal was correct, expected security behaviour | `wrv.review_via_api`: review through the app under test's own `/api/preview`, as the UI does. Approval is still required: dropping one decision is refused again (tested). |
| Regression suite: 8 failed, 26 skipped | The failing test names were not in the report. Known defects fixed: native-host call assertions raced the page's request (fixed sleeps / immediate reads) in the browser tests. The 26 skips are consistent with poppler not being installed. | Test defects + missing dependency | Polling `settle()`; the report now lists every failing test with its first error line (`failed-tests.txt` in the sandbox). |
| Client-Safe browser stage FAIL with 12 passed | The stage requires all of its tests to pass: 13 ran, 12 passed, one failed. It was not named. The client export in that suite runs Chrome + the pypdf fallback when poppler is absent, so it is the first suspect, but this is unconfirmed. | Unconfirmed; now diagnosable | The failing browser test is named in the stage detail. |
| (skips) | Skipped Client-Safe / PDF-quality / browser / script tests counted as coverage. | Harness gap | `no critical tests were skipped` is a required check; Chrome and poppler discovery adds Homebrew dirs to PATH and prints `brew install poppler` / `brew install --cask google-chrome`. |

### If something still fails, send these (all synthetic, safe to paste)
1. The saved `validation-results/macos-validation-*.txt` (failing tests and PDF metadata fields are in it; values that are not allowed are shown only as lengths).
2. `failed-tests.txt` and `logs/pytest.log` from the sandbox directory printed at the end (kept on failure).
3. Output of `python scripts/pdfkit_check.py <exported.pdf> --html <exported.html>`.


## Second Mac run: root causes and fixes (v0.6.1, code commit 20ac8a1)
Everything below was reproduced or reasoned from code on Linux. **None of it is macOS-verified until you re-run the validation on a Mac.**

| Finding | Root cause | Fix |
|---|---|---|
| `native: private text in PDF metadata is detected` (validator got `[]`) | The validator rejects any Title that is not empty or the report title, so it can only return `[]` if the Title it was given was empty or allowed. The harness injected the title via the HTML `<title>`; whether WKWebView copies that into the PDF was never checked, and PDFKit/the extractor might also not return it. From Linux the exact stage that lost it cannot be proven. | The harness now injects the private Title/Author/Subject/Keywords directly into the real WKWebView PDF and reports each stage (written / read by PDFKit / product / independent). The product validator also reads the PDF Info dictionary from the file bytes, so a field the extractor drops is still refused. Checks are not weakened. A diagnostic row states whether WKWebView copies `<title>` at all. |
| `PdfError: verify: the PDF has no selectable text` (optional probe) | The verifier needs 20 text characters; the probe page had 10. Not related to real exports. | Longer probe text. |
| Packaged `.app`: `export refused: validation ['metadata']` | Most likely a build from before the metadata fix: the version number (0.6.0) never changed, so nothing could tell. Not provable from Linux. | Builds embed a source fingerprint (`buildinfo.py`); the harness runs `WorkReceipt --build-info` and the running app reports its fingerprint. A stale or unidentifiable app is a required FAIL and is not launched. Version is now 0.6.1. |
| `test_client_safe_ui::test_full_flow...` timeout | No poppler, so PDF read-back used pypdf, which glues the footer page number to the footer name (`1workreceipt`); the extra-text check refused the export. Reproduced on Linux by hiding poppler. | Tokens made only of digits and footer words are footer text. Any other extra text is still refused. |
| `test_2_workflow_state...` (e2e and audit) | Test assumption: on macOS Ctrl+A moves the caret to the line start, so "select all" did not select and the original text stayed. Consistent with the symptom, not observed on a Mac. | Test uses Cmd+A on macOS and asserts the selection first. |
| `test_onboarding` Finish setup | Real defect: the dialog closed before the setting was saved. | Save first, then close; regression test with a slow save fails on the old code. |
| 26 skips | poppler missing (Linux with poppler hidden gives exactly 26). | Preflight warning; the PDF security tests are a named release gate. |

### Release approval needs
1. `brew install poppler` and Chrome installed. Without poppler the run cannot PASS.
2. A packaged app built from this checkout. `scripts/validate_macos.sh --rebuild` rebuilds first.
3. A macOS run with every required check PASS. Linux `--selftest` output is never macOS validation.

### Re-run on your Mac (one command)
```bash
cd /path/to/WorkReceipt && git checkout feature/client-safe-mode && git pull && brew install poppler && scripts/validate_macos.sh --rebuild
```
