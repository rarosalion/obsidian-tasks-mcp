import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from obsidian_tasks_mcp.server import build_server
from obsidian_tasks_mcp.vault import ConflictError


def test_registers_every_tool_with_read_only_hints(service):
    tools = {t.name: t for t in asyncio.run(build_server(service).list_tools())}
    assert set(tools) == {
        "list_boards",
        "list_tasks",
        "get_task",
        "audit_boards",
        "create_task",
        "move_task",
        "update_subtask",
        "add_subtask",
        "append_log",
        "set_task_fields",
    }
    for name in ("list_boards", "list_tasks", "get_task", "audit_boards"):
        assert tools[name].annotations.read_only_hint is True
    assert not tools["move_task"].annotations or not tools["move_task"].annotations.read_only_hint


def test_expected_failures_reach_the_caller_as_tool_errors(service):
    server = build_server(service)
    with pytest.raises(ToolError, match="no card matching"):
        asyncio.run(server.call_tool("get_task", {"title": "nothing"}))


def test_conflicts_surface_as_tool_errors(service, vault):
    def always_conflict(doc, new_text):
        raise ConflictError(doc.path)

    vault.write = always_conflict
    with pytest.raises(ToolError, match="ConflictError"):
        asyncio.run(
            build_server(service).call_tool("move_task", {"title": "Alpha Task", "to_lane": "Done"})
        )
