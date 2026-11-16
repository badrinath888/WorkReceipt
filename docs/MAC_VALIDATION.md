# macOS validation checklist (NOT yet performed)
Development so far ran on Linux. None of the items below has been verified on a Mac. Run on an M-series Mac with no Python/Chrome installed, then record results in docs/STATE.md.

1. `./desktop/build_macos.sh` completes; `dist/WorkReceipt.app` and `dist/WorkReceipt-<version>.dmg` exist; icon shows in Finder/Dock.
2. Mount the DMG, drag to Applications, launch from Spotlight. Window opens, min size ~960x640, no orphan: after quit, `pgrep -fl WorkReceipt` is empty and `lsof -iTCP -sTCP:LISTEN | grep WorkReceipt` is empty.
3. Menu bar (File, View) items work; ⌘1–5, ⌘, ⌘O ⌘R ⌘P ⌘E work (⌘C/⌘V work in text fields).
4. Onboarding: demo project; and a real folder via the native dialog; Settings "Choose…" dialogs; drag a folder onto the window (needs `pywebviewFullPath`).
5. **PDF**: export the demo with an approved review. Open the PDF: paginated, text selectable, contains `[REDACTED…]`, no secret strings (`pdftotext`/Preview search). Check `desktop/pdf_mac.py` print-job path; if it only produces a one-page PDF, the fallback ran: fix pagination.
6. Show in Finder / Open only on exported reports; delete report removes files.
7. Permissions: deny folder access, confirm the message; move/delete a project folder, confirm "folder missing"; read-only reports folder, confirm error. Rename `git` off PATH/CLT absent: confirm the Git message.
8. Data locations: settings/history in `~/Library/Application Support/WorkReceipt`; nothing written inside the .app.
9. Dark mode follows system. Quit/relaunch keeps settings, projects, reports list.
10. Signing: set `SIGN_IDENTITY`, `codesign --verify --deep --strict`, `spctl -a -vv dist/WorkReceipt.app`; notarize with `NOTARY_PROFILE`, `xcrun stapler validate`.

## Round 2 (after the first Mac test: PDF, Open report, review dialog)
Run on the Mac after rebuilding (v0.4.0):
1. **PDF**: approve the demo review, Export. Expect no "PDF could not be created" notice and a `.pdf` next to the `.html`. Open it: multiple Letter pages (the demo is long enough), text selectable, only `[REDACTED…]` markers. If it fails, the notice now shows `Reason: <stage>: <detail>` (stages: import, setup, load, print, render, paginate, verify, timeout) and the same line is in `~/Library/Application Support/WorkReceipt/pdf-last-error.txt`. Send me that line. If pages are cut mid-line the slicing fallback ran (print job failed); that is a quality issue to report, not a crash.
2. **Open report** (Report Studio banner and Reports screen) opens the HTML in the default browser; **Show in Finder** reveals it; **Open PDF** opens the PDF. Delete the file in Finder, click Open again: expect "That report file no longer exists…".
3. Review dialog: Confirm stays disabled until a choice AND the acknowledgement are set; Tab/arrow/Space work; focus ring visible; Esc closes.
4. Sidebar moon/sun icon toggles theme; date pills show hover/active; Overview Refresh; preview opens at top; Settings paths readable; About shows the Application Support path and v0.4.0.


## Round 3: one consolidated procedure (v0.4.1)
1. Rebuild (`desktop/build_macos.sh`), open the app. Settings → **Diagnostics** must say *Native services: ready*, with window "created", shown "yes".
   If it says "not responding", send me `~/Library/Application Support/WorkReceipt/desktop-diag.json` (absent = the window never fired *shown*; present with
   `available:false` = window created but not shown) — nothing else is needed.
2. Settings: **Choose…** for both folders → NSOpenPanel opens, picked path fills the field and is saved; cancel changes nothing.
3. Projects/Overview: **Add project** picker; drag a folder onto the window.
4. Menu bar File/View items and ⌘O/⌘R/⌘P/⌘E/⌘1–5/⌘, work.
5. Export a report (review all high items first): HTML and PDF are created; **Open report**, **PDF**, **Show in Finder** work from Studio and Reports; delete the file, then Open → "no longer exists" toast.
6. Resize/fullscreen, ⌘Q leaves no running process (`pgrep -fl WorkReceipt`).


## Round 4: PDF (v0.5.0) — Mac-only checks
1. Export a report with 30+ requests/commits. The PDF must open in Preview with **multiple US Letter pages** (⌘I → size 8.5 × 11 in), selectable/searchable text, 0.75in margins, no line cut at a page edge, table headers repeating, no heading alone at a page bottom.
2. If export shows "HTML saved, PDF could not be created", send `~/Library/Application Support/WorkReceipt/pdf-last-error.txt` (stage + reason only). Stage `verify` means the print job produced a wrongly sized/clipped PDF (the file is deleted rather than shipped).
3. Compare content with the HTML: same project, client, period, requests, commits, checks, sign-off block.
