import functools
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


def build_server(service: TaskService) -> MCPServer:
    server = MCPServer("obsidian-tasks", instructions=INSTRUCTIONS)
    read_only = ToolAnnotations(readOnlyHint=True)
    for tool in (service.list_boards, service.list_tasks, service.get_task, service.audit_boards):
        server.add_tool(_surface_errors(tool), annotations=read_only)
    for tool in (
        service.create_task,
        service.move_task,
        service.update_subtask,
        service.add_subtask,
        service.append_log,
        service.set_task_fields,
    ):
        server.add_tool(_surface_errors(tool))
    return server


def main() -> None:
    build_server(build_service()).run()


if __name__ == "__main__":
    main()
