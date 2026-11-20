# Client-Safe Mode (v0.6.0)

Two report modes. **Developer View** is private evidence (marked "PRIVATE · not for clients"). **Client-Safe View** is the default for anything shared.

## Architecture
- `client_safe.py` owns everything client-facing and never imports `app_core`. A separate `ClientReport` model (dataclasses `ClientReport`, `ClientItem`, `Verification`) with explicit allowlisted fields; `public()` raises if a field is added without being approved.
- The client report is built only from text the developer typed and approved, plus server-computed counts. Raw prompts, diffs, paths, commit messages, file names and findings never enter it. Unknown draft keys are dropped; unapproved items are dropped.
- `render_client()` is the only client template. The preview iframe shows the exact bytes that get exported.
- API: `/api/client/preview`, `/api/client/approve`, `/api/client/export` (token header required; failures return fixed reason codes, never content).

## Flow (Report Studio)
Private evidence → Prepare client summary → Privacy review → Client preview → Export.
"Use as starting point" copies private text into an **unapproved** draft; nothing is auto-approved.

## Safeguards
1. **Screening** blocks (never auto-edits) secrets, URLs/hosts, paths, file names, commit-like hex, commands/backticks, env vars, markup, private terms (NFKC/squeeze-aware), local user/host names.
2. **"Delivered"** wording needs commit ids verified against current Git history, or an explicit preparer attestation; exports show only counts.
3. **Two independent approvals**: Privacy Center finding review (unreviewed findings block the client review step) and complete-report approval (checkbox + server-issued HMAC token bound to content hash, repo, period, findings fingerprint; 4h TTL). Any edit invalidates it.
4. **Final-artifact validation** before anything is written to the output folder: HTML exactly equals a fresh render with tag/attribute allowlist, no comments/links/scripts, and screened text; PDF metadata, annotations/links, extracted text vs HTML (hidden-text check), raw structure. File names come only from the approved display name. Any failure blocks export; a PDF-generation failure alone keeps the validated HTML.

## Limitations (read these)
- Screening is heuristic. It cannot detect confidential facts written as plain prose (e.g. an architecture description) or Cyrillic homoglyph spellings of private terms. **The human preview and approval is the real control.**
- Chrome-generated PDFs carry a producer/UA string in metadata (allowed by pattern). Creator may also be exactly the product name `WorkReceipt` (a bundled macOS app names itself in the print job; unconfirmed on a Mac). Refusals report field, classification and reason only.
- Not verified on macOS: PDFKit `desktop/pdf_mac.extract_facts`, WKWebView PDF, native dialogs. If the Mac inspector returns nothing, export is blocked (fail closed).

## Tests
`test_client_safe.py` (backend adversarial: model, wording, screening, HTML/PDF tampering, approvals, e2e canaries, migration, API) and `test_client_safe_ui.py` (real Playwright clicks). Full suite: 295 pass on Linux.
