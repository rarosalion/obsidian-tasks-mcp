# obsidian-tasks-mcp

An [MCP](https://modelcontextprotocol.io) server that manages tasks on [Obsidian Kanban](https://github.com/obsidian-community/obsidian-kanban) boards and the task notes behind their cards. It talks to your vault through the [Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) plugin, so it needs no Obsidian plugin of its own and works against any vault that plugin can reach, including a headless Obsidian instance.

A generic vault MCP server can read and patch files, but keeping a board tidy takes several careful edits: create the note from the template, add the card in the right lane, tick the checkbox, stamp the completion date, avoid clobbering a concurrent edit. This server does each of those in one tool call.

## Requirements

- Obsidian with the **Local REST API** plugin, version 5.0 or newer (needed for conditional writes).
- The **Kanban** plugin, with each board a markdown file whose frontmatter has `kanban-plugin: board`.
- Python 3.12 or newer.

## Configuration

| Variable | Required | Meaning |
| --- | --- | --- |
| `OBSIDIAN_API_URL` | yes | Base URL of the Local REST API, for example `http://localhost:27123`. |
| `OBSIDIAN_API_KEY` | yes | The plugin's API key. |
| `OBSIDIAN_TASKS_DEFAULT_BOARD` | no | Board (file name without `.md`) used when a tool call does not name one. With exactly one board in the vault it is picked automatically. |

Boards are discovered by their `kanban-plugin: board` frontmatter. Each board's own Kanban settings supply the note folder (`new-note-folder`) and the note template (`new-note-template`); without a template a built-in one is used. A board with no `new-note-folder` cannot create tasks, so notes never land in the vault root by accident.

### Claude Code

```
claude mcp add obsidian-tasks \
  --env OBSIDIAN_API_URL=http://localhost:27123 \
  --env OBSIDIAN_API_KEY=... \
  -- uvx --from git+https://github.com/rarosalion/obsidian-tasks-mcp obsidian-tasks-mcp
```

## Tools

| Tool | What it does |
| --- | --- |
| `list_boards` | Boards with their lanes and card counts. |
| `list_tasks` | Cards with lane, checkbox, due date, assignee, tags and subtask progress. Filter by board, lane, `overdue`, `assigned_to` or `tag`. Done, Cancelled and Archive lanes are hidden unless named or `include_closed` is set. |
| `get_task` | One task's lane, frontmatter, sections and numbered subtasks. |
| `create_task` | Writes a task note from the template and adds its card, on top of the lane by default or at the bottom with `priority="low"`. |
| `move_task` | Moves a card between lanes. Moving to Done ticks it and stamps `Completed On`; moving out of Done unticks it. |
| `update_subtask` | Ticks or unticks a subtask by number or text, appending a dated note. |
| `add_subtask` | Adds a subtask to a note. |
| `append_log` | Adds a dated entry to the note's Running Log. |
| `set_task_fields` | Sets `Due By`, `Assigned to`, `Planned by`, `Tags` (a list) or `Completed On`. |
| `delete_task` | Permanently removes a task's card and, by default, its note. Refuses when other notes link to the note (that would leave broken links) unless `force` is set; `delete_note=false` removes only the card; the note is kept if another card still links to it. To keep a record of an abandoned task, move it to a Cancelled lane instead. |
| `audit_boards` | Read-only drift report: boards with no `new-note-folder`, notes with no card, cards whose note is missing, duplicate cards, checkboxes that disagree with their lane, started tasks still in To Do, and notes that do not follow the template. |

Recording work on a task that sits in a To Do lane (a ticked subtask or a log entry) moves it to In Progress, or to Blocked when the caller passes `blocked=true`. Cards in any other lane are never moved automatically.

## Conventions

Lanes are recognised by name, case-insensitively: To Do, In Progress, Blocked or Waiting (or Blocked, Waiting), Done (or Complete), and Cancelled or Archive (which never carry a ticked checkbox). Other lanes are left alone. Cards link to their note with a wikilink, `- [ ] [[Task title]]`.

A task note has flat frontmatter (`Due By`, `Assigned to`, `Planned by`, `Tags`, `Completed On`) and top-level sections `# Summary`, `# Subtasks`, `# Detailed Plan`, `# Questions to Consider` and `# Running Log`. `%% ... %%` comments in the template are dropped from new notes. `Tags` is written as a YAML block list (one `  - tag` line each), because Obsidian only treats that form as a list; a comma-separated string is read for compatibility but reported by `audit_boards` as `tags_not_list`.

## Safety

Every write reads the file's version token first and sends it back with the change. If the file changed in between (for instance you edited the board in Obsidian), the write is refused and retried against the fresh content, so concurrent edits are never overwritten. Board edits are line-based: lanes, cards and the Kanban settings block that a call does not touch are left exactly as they were. The REST API adds a trailing newline to a file that lacked one when it is rewritten.

## Development

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The tests use an in-memory vault and synthetic boards, so they need no running Obsidian.
