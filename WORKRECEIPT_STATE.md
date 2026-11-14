# WorkReceipt: state (2026-11-14, v0.2.4)

## Product
Local CLI: Claude Code JSONL (`~/.claude/projects/<encoded-repo>/*.jsonl`) + git -> redacted, client-readable HTML report (print to PDF). Python 3.9+ stdlib, no network/LLM. Hypothesis: $29 one-time, freelancers/agencies, US. Constraints: solo, part-time, $0 budget. No landing page/payments until real-log validation passes.

## Report semantics (do not blur)
Work requested = developer prompts (not proof of completion). Changes delivered = git commits (evidence). Verification = recorded check commands + recorded outcome (`no error reported` / `failed` / `result not recorded`), flagged if files were edited afterwards; never labelled "passed".

## Files
workreceipt.py | test_workreceipt.py (15) | test_artifacts.py (14) | test_mvp.py (31) | validate_local.py | final_review.py | pyproject.toml | README.md | VERIFICATION.md. Tests: `python3 -m unittest -q` (61).

## Prompt classification (structure first)
`user_prompt` -> skip record flags (isMeta, isSidechain, isCompactSummary, isVisibleInTranscriptOnly, toolUseResult) when it has text; per block: unwrap `<pasted_content>` markers (body kept as the user's prompt), then drop continuation-summary text, Claude Code envelope tags (`<command-`, `<local-command`, `<system-reminder`, `<bash-*`, `<task-notification`, `<ide_`, hooks, interrupts), marker-only blocks, bare `claude --flags`, acknowledgements. Skips are counted on stderr.
Real-log evidence (user-reported, AssetHandoff): 3 JSONL files, 2,932 records, 36 requests kept after unwrapping paste wrappers, 15 commits, 70 checks, high-severity masks present and awaiting human review.

## Project association
Every record's `cwd` must be under the repo (realpath) for exact AND prefix project dirs; edits count only inside the repo; folder list comes from git, not edits.

## Real-world result (user, macOS, AssetHandoff, v0.2): 43/43 tests, 3 files, 2,932 records, 0 unparseable, 36 requests, git totals verified, 64 checks, no internal tags/absolute paths in report, 4 high masks in checks, unknown structures flagged NEEDS REVIEW (names not yet known).

## v0.2.1 changes after that run
Report lists latest 40 of N checks with a summary (was silently first 40 of 64); stale flag now cross-session and includes file-modifying shell commands; `--preview` shows masked checks/commits (⚑); only the exported first line of a prompt is scanned/counted for redaction; `final_review.py` added.

## Real-world result (user, macOS, v0.2.1 final review): 36 requests, report structure/disclaimers PASS, 4 high detections on 3 distinct values (value classes not yet reported), all 64 checks flagged stale, text fields outside user records incl. last-prompt.lastPrompt. NEEDS REVIEW.

## v0.2.2 changes (this pass)
- Stale: now per check, evidence-based states: superseded (same command re-run later) / edited (observed Edit/Write later, not re-run) / possible (shell commands only) / current. v0.2.1 flagged every check that had any later edit (=> 64/64).
- `last-prompt` is a known cache type (not a request, never ingested). final_review compares every text field outside user records against real user text (prefix match, handles truncation/paste markers) and reports duplicate-of-kept / duplicate-of-skipped / matches-nothing counts.
- Detections: final_review mirrors the real rule order (overlap = one value, several rules), classes each value and checks (yes/no) whether it is in the finished report, repo files, git history. Never downgraded automatically; every random-looking value stays NEEDS REVIEW.
- Bug: a repo with no commits was reported as "not a git repository".
- validate_local.py now runs final_review: ONE command.

## v0.2.3 (review logic only; workreceipt.py byte-identical to v0.2.2)
final_review now treats ids/hashes/signatures/titles/system+tool text/non-prompt attachments/queue bookkeeping as metadata (counted by reason, never "missing requests"). Only prompt-style fields (content, prompt, lastPrompt, text, message...) outside user records are compared with real user text. queue-operation[enqueue] and attachment.*prompt* remain plausible alternate sources and are reported if they match no user record. Parser/request count (36) not changed: no evidence-based reason to ingest alternate sources.

## v0.2.4 (review logic only; workreceipt.py byte-identical to v0.2.3, 36 requests unchanged)
final_review is role-aware: any dict with role+content is a chat message; only role=user text blocks can be user-authored (assistant/system/tool roles, tool_use/tool_result blocks, `system`/`tools` definitions, serialized-JSON "blob" strings are parsed and judged the same way). User-role text inside replayed API payloads (`api-request-blob` etc.) with no matching user record is INFO (payload copy or system-injected context; typed prompts always have their own user record), never REVIEW. Direct sources (queue-operation[enqueue].content, last-prompt, queued_command prompt) that match no user record remain REVIEW.

## FROZEN: v0.2.4 is the beta candidate. Only change for confirmed defects found by real users.

## BETA GATE (not met until the user confirms): no random-looking detection unresolved (rotated, or confirmed placeholder in --preview); final review shows no 'matches NO user record' fields (or those are explained).

## Verified (synthetic fixtures, Linux, Python 3.13)
61/61 tests; pip install in a clean venv; headless-Chrome print to PDF; every injection point escaped; malformed/binary/truncated logs; 30k-record log < 20 s; validate_local.py runs and leaks no content.

## NOT verified
Real-log behavior of the v0.2 changes (cwd filter, check wrappers, toolUseResult flag, `is_error` conventions) and macOS runtime; whether high-severity masks on AssetHandoff are true secrets or false positives; real client usefulness; Windows.

## Known limitations
See README. Main ones: first-line titles, no client-name auto-detection, redaction is best-effort, custom test scripts undetected.

## Next
Run `python3 validate_local.py --repo <AssetHandoff> --since <date>` on the Mac; share `validation_summary.txt`. If PASS/NEEDS REVIEW is acceptable: review masked titles, then limited beta (3-5 freelancers). Do not add features before that.
