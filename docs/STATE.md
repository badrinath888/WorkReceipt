# WorkReceipt desktop build — STATE
Baseline: v0.3.5 (30af059). Spec: desktop product build (M1–M8).

## Done
- M1: architecture decision (docs/DESKTOP_ARCHITECTURE.md); desktop/main.py (pywebview shell, random loopback port, clean shutdown, folder-picker/reveal API); desktop/build_macos.sh (PyInstaller .app + .dmg, unsigned); test_desktop.py.

## Next (M2)
- Wire UI to window.pywebview.api.pick_folder (replace typed paths); replace Chrome-based PDF (app_core.to_pdf) with WKWebView createPDF in packaged app.
- Then M3 screens (Onboarding, Overview, Projects, Report Studio, Privacy Center, Reports, Settings) — restructure ui/ into sidebar navigation.
- Privacy audit: unquoted-credential auto-clear in test_classify.py/app_core classifier (M5).

## Tested
Linux, Python 3.13: full unittest suite passes (baseline) + test_desktop (2). 
NOT tested: any macOS run, pywebview window, PyInstaller build, dmg.

## Blockers
- No macOS in this environment: .app/.dmg unbuilt and unvalidated. 
- Signing/notarization needs Apple Developer ID (not available).
