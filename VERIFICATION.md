# WorkReceipt v0.2 verification report (2026-11-14)
Environment: Linux, Python 3.13, git, headless Chrome. **No access to the author's Mac or real logs.**

| Area | Evidence | Result |
|---|---|---|
| Existing suite (15) + artifact regressions (14) | unittest | pass |
| New MVP regressions (14): quote-aware check detection, wrappers (`bash -c`), swift/xcodebuild/dotnet, cwd association incl. encoding collision, relative edit paths, stale-check flag, toolUseResult, outcome accuracy, git author filter + independent numstat, malformed/binary logs, CLI errors, 30k-record speed, HTML injection (all fields), empty report, redaction-by-section, validate_local content-free | unittest | pass |
| Install | `pip install .` in a fresh venv, `workreceipt --help`, error exit code | pass |
| PDF | headless Chrome print-to-PDF of a 40-item report (3 pages, text extractable) | pass |
| Real Claude Code logs / macOS | not accessible here | UNVERIFIED (run validate_local.py) |

Changes vs v0.1: paste wrappers unwrapped (36 real requests recovered, per user's run); task-notification/toolUseResult excluded; all records filtered by cwd; folders from git; "passed" -> "no error reported"; stale-check marker; `--git-author`; quote-aware command splitting (fixed `git commit -m "x; pytest"` false positive); CLI input validation; redaction hits reported per section; report "Basis" section; print CSS.

## v0.2.1 addendum
Found from the user's real run: 64 checks detected but the report listed only the first 40 (fixed: summary + latest 40 + omitted count); stale flag ignored later sessions and shell edits (fixed); preview could not show masked checks (fixed, with `⚑`); redaction scanned prompt lines that are never exported, inflating blocking hits (fixed: first line only). New `final_review.py` (content-free). 48/48 tests. Still unverified here: real-log behavior of v0.2.1; what the unknown fields and the 4 masks are (final_review.py answers both locally).

## v0.2.2 addendum (stabilization)
Cause of 64/64 stale: rule flagged any check with any later edit anywhere. Replaced by superseded/edited/possible/current (tests: superseded runs not flagged, observed vs shell-only distinguished, no later change = no flag). `last-prompt` handled as cache (known type, not ingested, duplicate analysis with truncation + paste markers + skipped-record matches). Detection review extended with overlap accounting and yes/no exposure checks (report / repo files / git history); never prints values (test asserts the token and its prefix never appear). Empty-repo bug fixed. 55/55 tests on Linux with synthetic fixtures. NOT verified: real-log behavior of v0.2.2, what the 3 values are, whether any `last-prompt` text is unique. **Beta readiness is not claimed while credential-like detections are unresolved.**

## v0.2.3 addendum
Defect (software): v0.2.2 final review flagged any 20+ char string outside user records (hashes, ids, signatures, system/tool text) as a possible missing request. Fixed in final_review.py only; tests: metadata kinds classed by reason, genuine unmatched queued prompts still reported, request count unaffected by queue/last-prompt copies, no content printed. 58/58 tests (Linux, synthetic). Personal decisions (credentials, report review) are NOT software checks and remain with the user.

## v0.2.4 addendum
Defect (software): replayed API payloads (system prompt, tools, assistant/tool messages) could surface as "missing user requests". Fix: role/block-type classification in final_review.py only. Tests: blob judged by role, serialized blob, no change to request count, genuine unmatched queued prompt still REVIEW. 61/61 (Linux, synthetic). The real shape of api-request-blob records was not available here; the classifier is generic (role + content), so run the one command and report any REVIEW line.
