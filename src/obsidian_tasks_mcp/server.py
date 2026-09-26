import functools
import logging
import os
import sys

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from .service import TaskService
from .vault import RestVault, VaultError

INSTRUCTIONS = """Manage tasks on Obsidian Kanban boards and their task notes.

A task is a card on a board plus a note that follows a fixed template. Prefer these tools to
editing the board or note files directly: they keep the template, the card's lane and checkbox,
and the completion date consistent, and refuse to overwrite concurrent edits.

Use priority="low" on create_task or move_task to put a card at the bottom of its lane; the default
is the top. Recording work on a task (a ticked subtask or a log entry) moves a card from To Do to
In Progress, or to Blocked if you pass blocked=true because blocked was the only step possible.
"""


def build_service() -> TaskService:
    url = os.environ.get("OBSIDIAN_API_URL")
    key = os.environ.get("OBSIDIAN_API_KEY")
    if not url or not key:
        sys.exit("OBSIDIAN_API_URL and OBSIDIAN_API_KEY must be set.")
    return TaskService(RestVault(url, key), os.environ.get("OBSIDIAN_TASKS_DEFAULT_BOARD"))


def _surface_errors(tool):
    """Turn expected failures into tool errors so the caller sees the real message."""

    @functools.wraps(tool)
    def wrapper(*args, **kwargs):
        try:
            return tool(*args, **kwargs)
        except (ValueError, VaultError) as error:
            raise ToolError(f"{type(error).__name__}: {error}") from error
        except httpx.HTTPError as error:
            raise ToolError(f"The Obsidian REST API request failed: {error}") from error

    return wrapper


READ_ONLY = ToolAnnotations(read_only_hint=True)
DESTRUCTIVE = ToolAnnotations(destructive_hint=True)

TOOLS = (
    (
        "list_boards",
        "List the Kanban boards in the vault with their lanes and card counts.",
        READ_ONLY,
    ),
    (
        "list_tasks",
        "List task cards with lane, checkbox, due date, assignee, tags and subtask progress "
        "(e.g. 3/7). Filter by board, lane, overdue, assigned_to or tag. Done, Cancelled and "
        "Archive lanes are hidden unless named in lane or include_closed is true.",
        READ_ONLY,
    ),
    (
        "get_task",
        "Get one task's lane, frontmatter, note sections and numbered subtasks. The title is "
        "the card's title; a unique partial match is accepted.",
        READ_ONLY,
    ),
    (
        "audit_boards",
        "Read-only report of board drift: boards with no new-note-folder, notes with no card, "
        "cards linking to a missing note, "
        "duplicate cards, checkboxes that disagree with their lane, started tasks still in "
        "To Do, open-lane notes that do not follow the template, and notes (in any lane) whose "
        "Tags are a plain string instead of a YAML list. Cards without a link are "
        "not reported. Fix findings with the other tools.",
        READ_ONLY,
    ),
    (
        "create_task",
        "Create a task: write its note from the board's template and add its card, in one call. "
        'The card goes on top of the lane by default; use priority="low" to put it at the '
        "bottom. Refuses if a card or note with that title already exists.",
        None,
    ),
    (
        "move_task",
        "Move a task's card to another lane (top of the lane by default, or the bottom with "
        'priority="low"). Moving to Done ticks the card and stamps Completed On; moving out '
        "of Done unticks it.",
        None,
    ),
    (
        "update_subtask",
        "Tick or untick a subtask, identified by its 1-based number or a unique piece of its "
        "text, adding a dated note when ticking. Ticking on a card in To Do moves it to In "
        "Progress, or to Blocked or Waiting when blocked is true.",
        None,
    ),
    (
        "add_subtask",
        "Add a subtask to a task note, optionally after an existing one. Planning only; it "
        "does not move the card.",
        None,
    ),
    (
        "append_log",
        "Add a dated entry to a task note's Running Log. Like a ticked subtask, it moves a "
        "card in To Do to In Progress (or Blocked or Waiting when blocked is true).",
        None,
    ),
    (
        "set_task_fields",
        "Set the frontmatter fields Due By, Assigned to, Planned by, Tags or Completed On on "
        "a task note. Tags is a list of strings, written as a YAML block list. Fields left out "
        "are unchanged.",
        None,
    ),
    (
        "delete_task",
        "Permanently delete a task: remove its card and, by default, its note. Use it for "
        "mistakes, duplicates and scratch tasks; to keep a record of an abandoned task, "
        "move_task it to Cancelled instead. Refuses if other notes link to the note, since "
        "that would leave broken links, unless force is true. delete_note=false removes only "
        "the card. The note is kept when another card still links to it.",
        DESTRUCTIVE,
    ),
)


def build_server(service: TaskService) -> MCPServer:
    server = MCPServer("obsidian-tasks", instructions=INSTRUCTIONS)
    for name, description, annotations in TOOLS:
        server.add_tool(
            _surface_errors(getattr(service, name)),
            name=name,
            description=description,
            annotations=annotations,
        )
    return server


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    build_server(build_service()).run()


if __name__ == "__main__":
    main()
