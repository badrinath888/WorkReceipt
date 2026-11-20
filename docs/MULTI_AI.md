# Multi-AI support (v0.7.0)

Reports are built from a provider-independent activity model (see `providers.py`): per session, prompts, checks, edited files and shell edits. Every adapter returns that shape, and all text goes through the same redaction and Client-Safe Mode pipeline as before.

| Provider | Status | Notes |
|---|---|---|
| Git only | supported | Turn every provider off in Settings > AI tools. Report says no AI logs were read. |
| Claude Code | supported | Default. |
| Codex CLI | **experimental** | Rollout JSONL under `<codex_dir>/sessions`. Verified against synthetic fixtures only. |
| OpenCode | **experimental** | `storage/session|message|part` layout. Verified against synthetic fixtures only. |
| Cursor | **not supported** | No documented, stable local transcript format. Integration boundary: implement `load(dir, repo, since, until, skipped)` returning the activity model and register it in `providers.LOADERS`. |

Defaults: only Claude Code is on; Codex and OpenCode are opt-in, so nothing is read from a tool the user did not enable. A failing adapter is counted in the skipped summary and never blocks other providers or the Git section.
Projects discovered by several tools are merged by path.
