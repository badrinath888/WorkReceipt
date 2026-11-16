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

- Folder-picker fix (reported on a real M1 Mac: Settings "Choose…" did nothing). Root cause (from pywebview 5.4 source, webview/util.py get_functions): the bridge builder recurses into every PUBLIC non-callable attribute of the js_api object; `Api.window` (the pywebview Window) was public, so building `window.pywebview.api` traversed the Window/Cocoa object graph and the API never appeared; the JS then silently did nothing (`native()` false, no message). Fix: `Api._window` (private); `ping()`; page loaded with `?shell=desktop`; JS waits for `pywebviewready` (picker buttons disabled until the bridge answers), clear error if it never arrives (15 s) or the dialog throws, silent on cancel; each Choose auto-saves settings so the path persists. Not yet confirmed on the Mac. Tests: test_desktop.Bridge (3), e2e 6-9 (stubbed bridge, delayed install, cancel, failure, timeout, persistence, Add Project). Suite: 170.

- Mac validation round 1 (user, M1 Pro): launch, discovery, demo, Git analysis, Studio, preview, privacy approval, HTML export OK. Fixes (v0.4.0, NOT yet re-tested on the Mac):
  - PDF failed. Real WebKit cause cannot be observed from Linux; reviewed pdf_mac.py and fixed the probable causes: (a) delegate/window/web view kept only by a local closure, WKWebView holds its delegate weakly so `didFinishNavigation` could never fire (-> timeout); (b) imports outside the try block on the main thread left the caller waiting the full timeout; (c) print view had zero frame and the window was never ordered in; (d) malformed print-callback selector signature. Rewrote: module-level job registry, staged pipeline (setup/load/print/render/paginate/verify) with sanitized per-stage errors shown in the UI and written to `<home>/pdf-last-error.txt`; paginated print job, with fallback = whole-page createPDF sliced into Letter-proportioned pages via PDFKit. HTML is kept only when PDF genuinely fails. Input is the already-redacted HTML; JS off; no baseURL; nothing else written.
  - Open report did nothing: with the old broken js_api bridge the page fell back to `window.open`, which WKWebView ignores; and the Python side ignored `open` failures. Now the page sends only a file NAME; `core.resolve_report` maps it to a history record (rejects anything else, missing files, symlinks, unreadable files); `open`/`open -R` errors are returned and shown as toasts; Studio banner has Open report / Show in Finder / Open PDF.
  - Review dialog redesigned (radio group, separate "Required acknowledgement", disabled-state explanation, distinct Cancel, in-place updates keep keyboard focus, focus trap); behaviour/security unchanged.
  - Polish: pill hover/active, sun/moon icon, Overview Refresh + refresh on window focus (20 s throttle), preview opens at top, wider monospace path fields, About shows real data dir and version (0.4.0).
- Tests: 182 pass on Linux (new: resolve/open/reveal success, missing, permission, symlink, traversal; pdf_mac failure handling with fake AppHelper; PDF reason plumbing and no-leak; Playwright real-click tests for dialog, open/reveal, theme, pills, refresh, preview scroll, settings). Linux does NOT validate WebKit/PDF/open on macOS.

## Next
- Re-run docs/MAC_VALIDATION.md (Round 2 section) on the Mac on a Mac; fix whatever fails (pdf_mac.py and menu are the riskiest). Then M7 website, M8 release.

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


## v0.4.1 — application-wide interaction audit + native transport rewrite
- Native dialogs/open/Finder moved from pywebview JS bridge to local HTTP `/api/native/*` (see INTERACTION_AUDIT.md). Menu uses `run_js`. `desktop-diag.json` + Settings → Diagnostics added.
- `test_interaction_audit.py` exercises every screen with real clicks; 69 matrix rows: PASS 60, FAIL 0, BLOCKED 9 (macOS-only). 201 tests pass on Linux.
- NOT verified on macOS: the real native host, Cocoa dialogs, Finder/open, PDF, menu bar, drag-drop. Procedure: MAC_VALIDATION.md Round 3.


## v0.5.0 — premium HTML/PDF report redesign
- New report layout (docs/PDF_DESIGN.md), no truncation, print-first pagination CSS. Mac PDF: slicing fallback removed, PDFKit verify added.
- test_pdf_quality.py renders real PDFs (short 2p, medium 7p, long 159p, long-strings, empty, mixed, redaction, colours) and checks every page. Old markup-bound tests updated.
- NOT verified: packaged macOS PDF generation (see MAC_VALIDATION.md Round 4).


## v0.5.1 — Mac PDF "verify: could not be read back" + export result card
- Root cause (high confidence, from code, NOT yet confirmed on a Mac): v0.5.0's PDFKit verifier called `PDFDocument.documentWithURL_`, which PyObjC does not expose, so it always got None and rejected a valid WebKit PDF. The print job itself had succeeded (the signature/size check ran before and passed).
- Fix: `alloc().initWithURL_`; verifier failures fall back to a byte-level page/MediaBox check; a verifier that cannot run => "unverified", never a rejection. Only positive defects (bad signature, wrong page size, clipped text, no text) reject. `pdf-last-diag.txt` (flags only) written every attempt; core re-validates the PDF signature for every backend.
- UI: compact export card with success / partial (warning, no PDF actions, optional technical details) / failure (retry) states, file names only, no paths.
- Not verified on macOS. See MAC_VALIDATION.md Round 5.


## v0.6.0 — Client-Safe Mode
- See docs/CLIENT_SAFE_MODE.md. New `client_safe.py`, `/api/client/*`, Report Studio client flow (default), developer reports marked PRIVATE, history records carry `mode`.
- 295 tests pass on Linux (229 baseline + 66 new). NOT verified on macOS (MAC_VALIDATION.md Round 6).
