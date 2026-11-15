# WorkReceipt desktop build — STATE
Baseline: v0.3.5 (30af059). Spec: desktop product build (M1–M8).

## Done
- M1: architecture decision (docs/DESKTOP_ARCHITECTURE.md); desktop/main.py (pywebview shell, random loopback port, clean shutdown, folder-picker/reveal API); desktop/build_macos.sh (PyInstaller .app + .dmg, unsigned); test_desktop.py.

- M2+M3: sidebar desktop UI (Overview, Projects, Report Studio, Privacy Center, Reports, Settings) replacing the scrolling page; state (project, edits, reviews, preview) lives in one JS object and survives navigation. First-run onboarding (3 steps, demo project or native folder pick). Native folder picker via window.pywebview.api (typed-path fallback in browsers); drag-drop of folders (needs pywebviewFullPath, webview only); add/remove/refresh projects (remove only hides, never deletes); missing-folder handling; Reports library (search, date filter, open, show in Finder, delete with confirm); Settings (appearance, folder pickers, author, privacy/storage info, manual-update workflow). Backend: core.all_projects/add_project/remove_project/enable_demo/delete_report + /api/project/*, /api/demo, /api/report/delete. Export gate unchanged and re-verified in e2e.
- Tests: test_e2e_desktop.py (Playwright + Chrome, synthetic data; pywebview bridge is a JS stub).

## Next (M4/M5)
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
