# Phase 1 validation — v0.3.2 (synthetic data only)

Nothing below used real Claude Code logs, real repositories or real credentials. Synthetic tests do not prove real-data behaviour.

## Tested (99 unit tests + 38 browser checks)
Project discovery/selection · session parsing and Git integration · wording accuracy · title editing · HTML/PDF export · redaction and export blocking · empty / malformed / non-Git / corrupt inputs · a 1,500-request / 1,500-commit / 500-check report · server security · hostile text in the UI.

## Failed and fixed (all confirmed by a reproducing test; the new tests fail or hang on the old code)
1. **Hang (critical):** the "secret assignment", "email" and "URL credentials" patterns were quadratic. One 80 KB line of dotted/hyphenated text (minified code, long URLs) froze the report. Matches are unchanged; time is now linear (every rule < 0.5 s on 240 KB adversarial input).
2. **Crash on malformed logs:** an odd `uuid` / tool id (list or object), a directory named `*.jsonl`, or a non-object first line made the whole report/discovery fail. Such records are now skipped (unreadable files are counted in "skipped").
3. **Edit mis-targeting:** title edits were keyed by list position, so a log that changed after loading could put an edit on another request. Edits are now keyed to the request and dropped (with a notice) if it is gone.
4. **Approval reuse:** a review tick was bound to rule + position, so a *different* secret landing in the same slot could inherit it. Ids now cover the content (salted per run); any change requires a fresh review.
5. Smaller: blank custom terms masked every space; same-second exports overwrote each other; PDF path was not URL-encoded (`#`, `%`); an unwritable reports folder gave a raw error.

## Passed without changes
Prefix/sibling project exclusion · titles are verbatim prompt text, no "completed/passed" claims · commit counts equal `git rev-list --count` · period and author filters (option-injection safe) · check outcomes ("failed" / "no error reported" / "result not recorded") · every report section masked, nothing sensitive in any API payload, file name or the page · export refused (UI and server) until every high finding is reviewed · token + Host checks, no CORS, no path traversal, 2 MB body cap · hostile HTML in titles, commits, folder names, client/author never executes in the UI or report.

## Remaining blockers / limits
- **Not validated on real data** (see below). Real logs may contain shapes the synthetic fixtures do not.
- Titles are only the first line of each prompt, so a short first line can under-describe a request (limitation, not invention).
- Redaction is best-effort; custom terms and a read-through are the safeguard. Findings approved by you still need *your* judgement.
- Review ids reset when the app restarts (by design). Windows, Python 3.9/3.10 execution and very old Git remain untested.
- `validate_local.py` still reports NEEDS REVIEW whenever a high-severity value exists; that is intended.

## Real-data validation on your Mac (about 10 minutes)
```
git clone https://github.com/badrinath888/WorkReceipt.git   # or: cd WorkReceipt && git pull
cd WorkReceipt
python3 validate_local.py --repo /path/to/AssetHandoff --since YYYY-MM-DD
```
1. Expect all PASS except the credential REVIEW line. Paste only `validation_summary.txt` (counts/labels, no content) if anything FAILs.
2. `python3 workreceipt_app.py` → Projects: your AssetHandoff folder is listed, session count looks right → pick a period → **Load activity**.
3. Report Studio: request count matches your earlier 36; commits match `git log --oneline | wc -l` for the period; edit two titles → **Preview**.
4. Privacy Center: read each high-severity row's masked line. For each real credential: rotate it. Only then tick **reviewed**.
5. Add `--redact-term` equivalents (client/project names) under Privacy Center → confirm they vanish from the preview.
6. **Export report** → open the HTML and PDF, read them top to bottom, then send nothing you have not read.
7. Quit and restart the app: previously ticked reviews must be required again.
