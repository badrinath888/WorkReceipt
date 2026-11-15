# Visual app (v0.3.1 — one continuous scrolling page)

    python3 workreceipt_app.py        # opens http://127.0.0.1:8765 — local only, stdlib only

Screens: Overview, Projects, Report Studio, Privacy Center, Settings. The app reads `~/.claude` and your repository
on this computer and never uploads them. Export of a report is blocked, in the UI **and on the server**, until each
high-severity masked value has been reviewed. Try it without real data:

    python3 examples/make_demo_workspace.py /tmp/wr-demo
    WORKRECEIPT_CLAUDE_DIR=/tmp/wr-demo/claude python3 workreceipt_app.py

The CLI below is unchanged. See DESIGN_SPEC.md for the visual system.

# WorkReceipt (v0.2, local beta candidate)

Turns your Claude Code sessions + git history into a client-readable HTML report (print to PDF).
Local only: no network, no LLM, no dependencies (Python 3.9+, git).

## Install / run
    python3 workreceipt.py --repo /path/to/project --since 2026-11-01 --preview       # review first, writes nothing
    python3 workreceipt.py --repo /path/to/project --since 2026-11-01 --until 2026-11-14 --client "Acme" --author "Your Name" --out report.html
    # optional: pip install .   ->  `workreceipt ...`
`--preview` also lists every check and commit subject as it would appear, with `⚑` on any line where something was masked, so you can review masks without ever seeing the original value.
Open report.html in a browser, edit titles inline, then Print -> Save as PDF (tested with headless Chrome).

## What the report claims (and does not)
- **Work requested**: prompts you typed in Claude Code for this repo. A request is NOT proof of completion.
- **Changes delivered**: git commits in the period (all authors unless `--git-author "Name"`). This is the evidence of delivered work.
- **Verification**: test/lint/build commands recorded in the logs and the outcome the tool recorded: `no error reported`, `failed`, or `result not recorded`. They are not re-run. Each check also gets a state from the logs: *re-run later* (same command ran again), *files were edited after this check; not re-run since* (an Edit/Write tool use came later = observed), *shell commands that may change files ran after* (possible, not observed), or no flag. Edits made outside Claude Code are invisible. The report lists the 40 most recent checks and says how many earlier ones were omitted.
- Session activity from other folders (same-prefix siblings, path-encoding collisions, edits outside the repo) is excluded and counted on stderr.

## Safety
- Redaction masks known token formats, `key=value`/JSON secrets, emails, IPs, home paths, long mixed-case random strings, plus `--redact-term` words. Best-effort: **read the report before sending**.
- If any high-severity secret was masked the report is NOT written (exit 2). Run `--preview`, read the masked titles (stderr shows which section had hits), rotate real secrets, then re-run with `--allow-high`.
- Only prompt titles (first line), check commands, commit subjects and folder names are exported. File contents and tool outputs never are. HTML is escaped and has a no-network CSP.
- Pasted text inside `<pasted_content>` wrappers is treated as your own prompt (its first line is the title) and is redacted like any other text.

## Validate on your Mac (ONE command)
    python3 validate_local.py --repo /path/to/AssetHandoff --since YYYY-MM-DD
Runs all tests, content-free log diagnostics, an independent git cross-check, report generation in a temp folder, an output audit, and the final review: unknown log fields (names only, and whether cache-like records such as `last-prompt` duplicate real prompts), each high-severity detection's value class plus whether that value appears in the finished report / your repo files / your git history (yes/no only), stale-check evidence, and report-section separation.
Prints PASS / NEEDS REVIEW / FAIL and saves `validation_summary.txt` (counts, field names and labels only; safe to share). Never prints prompts, commands or values; modifies nothing in your project or `~/.claude`.

## Other flags
`--diagnose` (log structure, no content), `--redact-term WORD` (repeatable), `--claude-dir`, `--allow-high`, `--git-author PATTERN`.

## Known limitations
Titles are the first line of each prompt (can be long/low-level; edit in the browser). Client/project names are not auto-detected (use `--redact-term`). Unquoted prose like `token: refresh` can trigger the secret rule (fails closed). Base64 secrets containing `/` can evade the entropy rule. Check detection covers common runners (pytest, npm/yarn/pnpm, cargo, go, mvn, gradle, swift, xcodebuild, dotnet, make, ruff, eslint, tsc...) not custom scripts. `git log` follows the current branch only. Windows is untested.

## Reviewing high-severity findings (v0.3.3)

The Privacy Center lists every individual detection inside a grouped finding, with its source (check, request or commit), line and column,
length, and redacted surrounding lines. Values stay masked. **Reveal value** fetches that one value from your local logs through the local
server (token required, explicit confirmation, `no-store`); it is shown only in an on-screen dialog that hides itself after 20 seconds, and is
never logged, cached, stored in the browser or written to a report. **Review** records your decision (real / dummy / unsure) with an
acknowledgement; every choice keeps the value masked in the report, and nothing is approved automatically from a variable name or placeholder text.
Export is blocked, on the server too, until every high-severity detection has a decision. Limits: decisions last for the session only; texts over
400 KB are reviewed as a single unit without reveal; a value that no longer exists in your logs cannot be revealed.

## Automated privacy analysis (v0.3.5)

Every high-severity detection is classified from the matched text itself, never from the variable name. A detection is **cleared automatically**
only when a narrow syntax rule shows it holds no secret: a short name plus closing code syntax (e.g. `tok)[0]`), a variable or environment
reference (`$MY_TOKEN`, `os.environ[`), a code reference (`self.token`, `get_token()`), a snake_case variable passed inside a call, a delimited
placeholder (`<your-token>`), or an exact AWS documentation example. Cleared detections stay masked in every report and can be shown, with the
reason, via "Show N automatically cleared". Everything else stays actionable and blocks export until you review it: provider-format keys,
random-looking values, custom terms, and dummy-looking values (labelled "likely dummy" or "likely test fixture", with evidence, but never cleared).
Classification states evidence and a confidence level; it never claims a value is real or fake with certainty. Known limits: the rules assume
code syntax, so unquoted `login(password=correct_horse_staple)` is treated as a variable reference; passwords under 6 characters are below the
scanner's own threshold; the masked span is deliberately conservative and can include trailing syntax such as `)[0]`.
