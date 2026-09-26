# obsidian-tasks-mcp

MCP server (Python, `mcp` SDK 2.x `MCPServer`) that manages Obsidian Kanban boards and their task notes through the Local REST API plugin. See [README.md](README.md) for the tools and conventions.

## Public repository

This repo is public. Never commit hostnames, domains, IP addresses, API keys, or note and board titles from a real vault. Configuration comes from environment variables only; tests use synthetic boards (see `tests/conftest.py`). Deployment wiring for a particular environment belongs in that environment's own repo.

## Layout

- `src/obsidian_tasks_mcp/vault.py` - the `Vault` protocol and `RestVault`, the only code that talks HTTP. Conditional writes use the document-map `version` as `ifMatch`; a 412 becomes `ConflictError`.
- `board.py` - lossless Kanban board parser. Each `Card` keeps its raw line so untouched cards render byte for byte.
- `notes.py` - task-note sections, subtasks, running log and new-note rendering from the template.
- `frontmatter.py` - flat `Key: value` frontmatter helpers (the templates use nothing more).
- `service.py` - `TaskService`, one method per tool. Every mutation goes through `_edit`, which re-reads and retries on `ConflictError`, so mutation callbacks must be safe to run more than once.
- `server.py` - MCP wiring. `_surface_errors` converts expected failures to `ToolError`; without it the SDK hides the message behind "Error executing tool".
- `tests/` - `FakeVault` in `conftest.py` mimics the REST API, including its trailing-newline behaviour.

## Behaviours worth knowing

- A body-only change is written with an atomic `PATCH` on the document root; a frontmatter change falls back to a version check followed by `PUT`, which leaves a very small race window.
- `PATCH` on the document root appends a trailing newline when the file lacked one.
- `delete_task` is the only destructive tool. It checks for other notes linking to the note (`Vault.find_linking_to`, a JsonLogic search over `links`) before removing anything, and removes the card before deleting the note so a failure leaves at worst an orphaned note.
- Adding a subtask does not count as starting a task, so it never moves a card; a ticked subtask or a log entry does.
- A board with no `new-note-folder` setting cannot create tasks: `create_task` raises instead of writing to the vault root, and `audit_boards` lists such boards under `boards_missing_note_folder`.
- `Tags` is always written as a YAML block list (one `  - tag` line each), because Obsidian only treats that form as tags. `create_task` and `set_task_fields` take a list and reject any item containing anything but letters, numbers, `_`, `-` and `/`. Reads also accept an inline list or a comma string so legacy notes still parse, and `audit_boards` reports those as `tags_not_list`. `frontmatter.set_value` and `set_list` replace a key's indented continuation lines along with the key, so rewriting a list never leaves orphaned items.

## Commands

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
