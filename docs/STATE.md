# WorkReceipt desktop build — STATE
Baseline: v0.3.5 (30af059). Spec: desktop product build (M1–M8).

## Done
- M1: architecture decision (docs/DESKTOP_ARCHITECTURE.md); desktop/main.py (pywebview shell, random loopback port, clean shutdown, folder-picker/reveal API); desktop/build_macos.sh (PyInstaller .app + .dmg, unsigned); test_desktop.py.

- M2+M3: sidebar desktop UI (Overview, Projects, Report Studio, Privacy Center, Reports, Settings) replacing the scrolling page; state (project, edits, reviews, preview) lives in one JS object and survives navigation. First-run onboarding (3 steps, demo project or native folder pick). Native folder picker via window.pywebview.api (typed-path fallback in browsers); drag-drop of folders (needs pywebviewFullPath, webview only); add/remove/refresh projects (remove only hides, never deletes); missing-folder handling; Reports library (search, date filter, open, show in Finder, delete with confirm); Settings (appearance, folder pickers, author, privacy/storage info, manual-update workflow). Backend: core.all_projects/add_project/remove_project/enable_demo/delete_report + /api/project/*, /api/demo, /api/report/delete. Export gate unchanged and re-verified in e2e.
- Tests: test_e2e_desktop.py (Playwright + Chrome, synthetic data; pywebview bridge is a JS stub).

- M5 (privacy hardening): FIXED unsafe auto-clear. Vulnerabilities: (1) snake_case value + closing paren (`login(password=correct_horse_staple)`) cleared as "variable passed to a function"; (2) attribute paths (`config.x`, `self.x`) and (3) calls with arguments (`get_x(secret)`) cleared as code references; (4) quoted `<Tr0ub4dor3>` cleared as template placeholder. Detection gaps: `--password VALUE`/`--token VALUE`, `curl -u user:pass` were not masked at all; `passphrase` keyword missing. Fixes: (1)-(3) now never auto-clear (low-confidence, human review); placeholders only when every word is placeholder vocabulary; new rules "secret option" and "curl user:password" (high); `passphrase` keyword. Still auto-cleared (narrow): published vendor example constants, env-var references (`${X}`, `$UPPER_SNAKE`, process.env.X, os.environ[), `<your_api_key>`-style placeholders, <6-char name + closing syntax (below scanner minimum). Cleared values stay masked in every export.
- Tests: test_m5_security.py (kwarg/attr/call/JSON/shell/YAML/fixture cases, hostile + 600 KB records, approval invalidation on changed value, forged dispositions, no leakage in API/errors/data folder, CLI vs preview vs export). test_classify.py updated: `secret_key)[1]` now needs review (3 of 4 bridge fragments still cleared).

- M6 (packaging infra, UNTESTED ON MAC): PDF without Chrome: `core.PDF_BACKEND` hook; desktop/pdf_mac.py renders the already-redacted exported HTML in an offscreen WKWebView (JS off, no baseURL) via a save-to-file print job (fallback single-page createPDF); Chrome remains the dev/CLI fallback; failed PDF never loses the HTML (`pdf_failed`). Native File/View menu + Cmd shortcuts (shared `window.wrCommand`); icon (desktop/icon, .icns built by script via sips/iconutil); PyInstaller spec with version metadata from app_core.VERSION; entitlements (hardened runtime, no network); build_macos.sh (venv, icns, .app, DMG with /Applications link, optional codesign+notarize via SIGN_IDENTITY/NOTARY_PROFILE env, sha256, honest "NOT notarized"); macOS data in ~/Library/Application Support/WorkReceipt, reports in ~/Documents/WorkReceipt Reports (legacy ~/.workreceipt copied once); clearer errors (permission, moved/deleted project, Git missing, unwritable reports folder). docs/INSTALL.md, docs/MAC_VALIDATION.md.
- Tests: test_packaging.py (config, no credentials in script, minimal entitlements, menu commands exist, data dirs, PDF backend gets only redacted HTML after approval, real Chrome PDF masked via pdftotext, error messages, Finder reveal restricted); e2e keyboard shortcuts. Full suite: 163 tests.

## Next
- Run docs/MAC_VALIDATION.md on a Mac; fix whatever fails (pdf_mac.py and menu are the riskiest). Then M7 website, M8 release.

## (older) Next (M4/M6)
- M4: report metadata audit, PDF without Chrome (WKWebView createPDF). M6: packaging on a Mac.
- Residual privacy risks: `$UPPER_SNAKE` literal password would be auto-cleared (still masked); passwords shorter than scanner minimum are not detected; secrets without a keyword/known format/entropy are not detected; `-p value` flags not covered; classification is advisory and cannot read intent.

## (older) Next (M4/M5)
- M4: report metadata audit (no secrets), safe file naming review, PDF without Chrome (WKWebView createPDF) -> M6.
- M5 (do first): classifier audit — unquoted credential vs code-variable reference auto-clear (test_classify.py).
- Known gaps: log-dir override is global (Settings), not per project; Dock/menu bar items and app icon not done; keyboard shortcuts not added.

## Superseded old list (M2)
- Wire UI to window.pywebview.api.pick_folder (replace typed paths); replace Chrome-based PDF (app_core.to_pdf) with WKWebView createPDF in packaged app.
- Then M3 screens (Onboarding, Overview, Projects, Report Studio, Privacy Center, Reports, Settings) — restructure ui/ into sidebar navigation.
- Privacy audit: unquoted-credential auto-clear in test_classify.py/app_core classifier (M5).

## Tested
Linux, Python 3.13, Chrome via Playwright: full suite 136 tests pass (130 baseline + test_desktop 2 + e2e 4). Old examples/browser_test_*.py target the previous single-page UI and are stale.
NOT tested: any macOS run, real pywebview/WKWebView window (bridge only stubbed), native dialogs, drag-drop paths, PyInstaller build, dmg.

## Blockers
- No macOS in this environment: .app/.dmg unbuilt and unvalidated. 
- Signing/notarization needs Apple Developer ID (not available).
