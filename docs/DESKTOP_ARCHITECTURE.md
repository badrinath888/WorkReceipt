# Desktop architecture decision (M1)

**Chosen: B — native macOS window (pywebview / WKWebView) hosting the existing UI, served by the existing Python engine on a loopback port, packaged with PyInstaller into a `.app` + `.dmg`.**

| Option | Verdict |
|---|---|
| A. SwiftUI shell + bundled Python | Best native feel, but needs a Swift rewrite of every screen and an IPC layer; slowest, highest maintenance. Rejected for v1. |
| B. WKWebView shell + bundled Python | Reuses `app_core.py`, `workreceipt_app.py`, `ui/`. Small (~30–40 MB), no Chromium bundled, native file dialogs via `window.create_file_dialog`. **Chosen.** |
| C. Electron/Tauri | Electron ships ~150 MB Chromium for no requirement we have. Tauri needs a Rust toolchain plus a Python sidecar. Rejected. |

## Process model
One process. `desktop/main.py` starts the stdlib HTTP server (`workreceipt_app.H`) on `127.0.0.1:<random free port>` in a daemon thread, opens a pywebview window at that URL, and on window close calls `server.shutdown()` + `server_close()`. No child processes, so nothing can be orphaned.

## Security
- Loopback only; Host-header check and per-launch random token on every POST (existing).
- Native dialogs are exposed through a tiny `js_api` (`pick_folder`, `reveal`) that returns paths only to the page served by this app.
- Navigation is restricted to the app's own origin; external links open in the default browser.
- No telemetry, no network calls, no cloud account.

## Known gaps
- PDF export currently needs Chrome (`app_core.to_pdf`). Packaged builds must replace this with WKWebView `createPDF` (M6).
- Signing/notarization needs an Apple Developer ID; builds are unsigned until then.
- Developed on Linux: the macOS bundle is **not validated** until built and run on a Mac.
