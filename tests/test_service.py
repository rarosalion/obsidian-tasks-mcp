import pytest

from obsidian_tasks_mcp import frontmatter, notes
from obsidian_tasks_mcp.board import Board
from obsidian_tasks_mcp.service import lane_kind
from obsidian_tasks_mcp.vault import ConflictError, ExistsError
from tests.conftest import BOARD


def lane_titles(vault, lane):
    board = Board.parse(vault.files["Board.md"])
    return [c.title for c in board.lane(lane).cards]


def test_lane_kind():
    assert lane_kind("To Do") == "todo"
    assert lane_kind("In Progress") == "progress"
    assert lane_kind("Blocked or Waiting") == "blocked"
    assert lane_kind("Done") == "done"
    assert lane_kind("Archive") == "closed"
    assert lane_kind("Long-Term") == "other"


def test_list_boards(service):
    boards = service.list_boards()
    assert boards[0]["board"] == "Board"
    assert boards[0]["lanes"][0] == {"name": "To Do", "cards": 2}


def test_list_tasks_hides_closed_lanes_by_default(service):
    titles = {t["title"] for t in service.list_tasks()}
    assert "Alpha Task" in titles
    assert "Epsilon Task" not in titles
    assert "Epsilon Task" in {t["title"] for t in service.list_tasks(lane="Done")}


def test_list_tasks_details_and_filters(service):
    by_title = {t["title"]: t for t in service.list_tasks()}
    assert by_title["Alpha Task"]["subtasks"] == "0/2"
    assert by_title["Alpha Task"]["assigned_to"] == "Sam"
    assert [t["title"] for t in service.list_tasks(overdue=True)] == ["Beta Task"]
    assert service.list_tasks(assigned_to="nobody") == []
    assert len(service.list_tasks(lane="To Do")) == 2


def test_get_task(service):
    task = service.get_task("alpha task")
    assert task["lane"] == "To Do"
    assert task["note_path"] == "Tasks/Alpha Task.md"
    assert task["subtask_items"][0] == {"index": 1, "checked": False, "text": "First step"}
    assert task["sections"]["Summary"] == "Does a thing."


def test_get_task_without_note_and_unknown(service):
    assert service.get_task("Plain card")["has_note"] is False
    with pytest.raises(ValueError, match="no card matching"):
        service.get_task("Nope")
    with pytest.raises(ValueError, match="ambiguous"):
        service.get_task("Task")


def test_create_task_puts_card_on_top_with_note(service, vault):
    result = service.create_task(
        "New Thing", summary="Why.", subtasks=["A", "B"], assigned_to="Sam", due_by="2026-10-01"
    )
    assert result["note_path"] == "Tasks/New Thing.md"
    assert lane_titles(vault, "To Do")[0] == "New Thing"
    text = vault.files["Tasks/New Thing.md"]
    assert "%%" not in text
    assert frontmatter.get(text, "Planned by") == "Claude"
    assert frontmatter.get(text, "Due By") == "2026-10-01"
    assert [s.text for s in notes.subtasks(text)] == ["A", "B"]
    assert notes.problems(text) == []


def test_create_task_low_priority_goes_to_bottom(service, vault):
    service.create_task("Later", priority="low")
    assert lane_titles(vault, "To Do")[-1] == "Later"


def test_create_task_other_lane(service, vault):
    service.create_task("Started", lane="in progress")
    assert lane_titles(vault, "In Progress")[0] == "Started"


def test_create_task_rejects_bad_input(service):
    with pytest.raises(ValueError, match="title"):
        service.create_task("Bad/Title")
    with pytest.raises(ValueError, match="already exists"):
        service.create_task("alpha task")
    with pytest.raises(ValueError, match="no lane"):
        service.create_task("X", lane="Nowhere")


def test_create_task_requires_a_note_folder(service, vault):
    vault.files["Board.md"] = BOARD.replace(',"new-note-folder":"Tasks"', "")
    with pytest.raises(ValueError, match="new-note-folder"):
        service.create_task("Rootless")
    assert "Rootless.md" not in vault.files
    assert "Rootless" not in Board.parse(vault.files["Board.md"]).lane("To Do").cards


def test_create_task_refuses_to_overwrite_an_existing_note(service, vault):
    with pytest.raises(ExistsError):
        service.create_task("Stray Note")
    assert "Stray Note" not in Board.parse(vault.files["Board.md"]).lane("To Do").cards


def test_move_task_top_by_default_and_low_priority(service, vault):
    result = service.move_task("Alpha Task", "In Progress")
    assert result["from"] == "To Do" and result["to"] == "In Progress"
    assert lane_titles(vault, "In Progress") == ["Alpha Task", "Gamma Task"]
    service.move_task("Beta Task", "in progress", priority="low")
    assert lane_titles(vault, "In Progress")[-1] == "Beta Task"


def test_move_task_keeps_nested_lines_and_other_lanes(service, vault):
    service.move_task("Gamma Task", "Blocked or Waiting")
    text = vault.files["Board.md"]
    assert "- [ ] [[Gamma Task]]\n\t- [ ] nested checklist item" in text
    assert text.split("## Done")[1].rstrip("\n") == BOARD.split("## Done")[1]


def test_move_to_done_checks_card_and_stamps_completed_on(service, vault):
    result = service.move_task("Alpha Task", "Done")
    assert result["completed_on"] == "2026-09-25"
    assert "- [x] [[Alpha Task]]" in vault.files["Board.md"]
    assert frontmatter.get(vault.files["Tasks/Alpha Task.md"], "Completed On") == "2026-09-25"


def test_move_to_done_keeps_an_existing_completion_date(service, vault):
    vault.files["Tasks/Beta Task.md"] = frontmatter.set_value(
        vault.files["Tasks/Beta Task.md"], "Completed On", "2025-05-05"
    )
    assert service.move_task("Beta Task", "Done")["completed_on"] == "2025-05-05"


def test_move_to_done_stamps_over_a_yaml_null(service, vault):
    vault.files["Tasks/Alpha Task.md"] = vault.files["Tasks/Alpha Task.md"].replace(
        "Completed On:", "Completed On: null"
    )
    assert service.move_task("Alpha Task", "Done")["completed_on"] == "2026-09-25"
    assert frontmatter.get(vault.files["Tasks/Alpha Task.md"], "Completed On") == "2026-09-25"


def test_move_out_of_done_unchecks_and_keeps_date(service, vault):
    service.move_task("Epsilon Task", "In Progress")
    assert "- [ ] [[Epsilon Task]]" in vault.files["Board.md"]
    assert frontmatter.get(vault.files["Tasks/Epsilon Task.md"], "Completed On") == "2026-01-02"


def test_move_to_cancelled_stays_unchecked(service, vault):
    service.move_task("Epsilon Task", "Cancelled")
    assert "- [ ] [[Epsilon Task]]" in vault.files["Board.md"]


def test_move_card_without_a_note(service, vault):
    result = service.move_task("Plain card", "To Do")
    assert "completed_on" not in result
    assert "Plain card without a note" in lane_titles(vault, "To Do")


def test_move_to_same_lane_is_a_no_op(service, vault):
    before = vault.files["Board.md"]
    service.move_task("Alpha Task", "To Do")
    assert vault.files["Board.md"] == before


def test_move_unknown_lane(service):
    with pytest.raises(ValueError, match="no lane"):
        service.move_task("Alpha Task", "Nowhere")


def test_update_subtask_moves_todo_card_to_in_progress(service, vault):
    result = service.update_subtask("Alpha Task", 1, note="done it")
    assert result["subtasks"] == "1/2"
    assert result["moved_to"] == "In Progress"
    assert lane_titles(vault, "In Progress")[0] == "Alpha Task"
    assert "- [x] First step (done 2026-09-25: done it)" in vault.files["Tasks/Alpha Task.md"]


def test_update_subtask_blocked(service, vault):
    result = service.update_subtask("Alpha Task", "second", blocked=True)
    assert result["moved_to"] == "Blocked or Waiting"
    assert lane_titles(vault, "Blocked or Waiting")[0] == "Alpha Task"


def test_update_subtask_does_not_move_cards_outside_todo(service, vault):
    assert "moved_to" not in service.update_subtask("Someday Task", 1)
    assert lane_titles(vault, "Long-Term") == ["Someday Task"]


def test_update_subtask_reports_when_everything_is_done(service):
    service.update_subtask("Alpha Task", 1)
    assert service.update_subtask("Alpha Task", 2)["all_subtasks_done"] is True


def test_unchecking_a_subtask_does_not_move_the_card(service, vault):
    service.update_subtask("Epsilon Task", 1, checked=False)
    assert "moved_to" not in service.update_subtask("Alpha Task", 1, checked=False)
    assert lane_titles(vault, "To Do")[0] == "Alpha Task"


def test_add_subtask_does_not_move_the_card(service, vault):
    result = service.add_subtask("Alpha Task", "Third step")
    assert result["subtasks"] == "0/3"
    assert "moved_to" not in result
    assert lane_titles(vault, "To Do")[0] == "Alpha Task"


def test_append_log_moves_todo_card(service, vault):
    result = service.append_log("Alpha Task", "started poking at it")
    assert result["moved_to"] == "In Progress"
    assert "- 2026-09-25: started poking at it" in vault.files["Tasks/Alpha Task.md"]


def test_note_edits_need_a_note(service):
    with pytest.raises(ValueError, match="no task note"):
        service.append_log("Plain card", "x")


def test_set_task_fields(service, vault):
    result = service.set_task_fields("Alpha Task", due_by="2026-12-01", tags=["net", "#ops"])
    assert result["updated"] == {"Due By": "2026-12-01", "Tags": ["net", "ops"]}
    text = vault.files["Tasks/Alpha Task.md"]
    assert frontmatter.get(text, "Due By") == "2026-12-01"
    assert frontmatter.get(text, "Assigned to") == "Sam"
    assert frontmatter.get_list(text, "Tags") == ["net", "ops"]
    assert "Tags:\n  - net\n  - ops\n" in text
    assert service.get_task("Alpha Task")["tags"] == ["net", "ops"]
    assert [t["title"] for t in service.list_tasks(tag="OPS")] == ["Alpha Task"]
    assert service.list_tasks(tag="op") == []


def test_set_task_fields_rejects_comma_string_tags(service):
    with pytest.raises(ValueError, match="invalid tag"):
        service.set_task_fields("Alpha Task", tags=["net, ops"])


def test_audit_flags_plain_string_tags_in_any_lane(service, vault):
    assert "tags_not_list" not in service.audit_boards()
    text = vault.files["Tasks/Alpha Task.md"]
    vault.files["Tasks/Alpha Task.md"] = frontmatter.set_value(text, "Tags", "a, b")
    assert service.audit_boards()["tags_not_list"] == ["Alpha Task"]


def test_conflicting_write_is_retried_against_fresh_content(service, vault):
    def intervene(v):
        v.files["Board.md"] = v.files["Board.md"].replace(
            "- [ ] [[Beta Task]]", "- [ ] [[Beta Task]]\n- [ ] [[Concurrent Card]]"
        )

    vault.before_write = intervene
    service.move_task("Alpha Task", "In Progress")
    text = vault.files["Board.md"]
    assert "[[Concurrent Card]]" in text
    assert lane_titles(vault, "In Progress")[0] == "Alpha Task"


def test_persistent_conflict_raises(service, vault):
    original = vault.write

    def always_conflict(doc, new_text):
        raise ConflictError(doc.path)

    vault.write = always_conflict
    with pytest.raises(ConflictError):
        service.move_task("Alpha Task", "In Progress")
    vault.write = original


def test_audit_reports_problems(service):
    report = service.audit_boards()
    assert report["clean"] is False
    assert "Tasks/Stray Note.md" in report["orphan_notes"]
    assert any("Missing Note" in item for item in report["broken_links"])
    assert any("Zeta Task: unchecked in Done" in item for item in report["checkbox_mismatch"])
    assert "done_missing_completed_on" not in report
    assert "template_problems" not in report
    assert "Alpha Task" not in report.get("started_but_in_todo", [])


def test_audit_flags_board_without_note_folder(service, vault):
    assert "boards_missing_note_folder" not in service.audit_boards()
    vault.files["Board.md"] = BOARD.replace(',"new-note-folder":"Tasks"', "")
    assert service.audit_boards()["boards_missing_note_folder"] == ["Board"]


def test_audit_flags_started_task_in_todo(service, vault):
    vault.files["Tasks/Alpha Task.md"] = note_with_done()
    assert "Alpha Task" in service.audit_boards()["started_but_in_todo"]


def test_audit_flags_duplicates_and_stray_checks(service, vault):
    vault.files["Board.md"] = vault.files["Board.md"].replace(
        "## In Progress\n", "## In Progress\n\n- [x] [[Alpha Task]]\n"
    )
    report = service.audit_boards()
    assert any(item.startswith("alpha task") for item in report["duplicate_cards"])
    assert any("Alpha Task: checked in In Progress" in i for i in report["checkbox_mismatch"])


def test_board_selection(vault):
    from obsidian_tasks_mcp.service import TaskService

    vault.files["Other.md"] = "---\nkanban-plugin: board\n---\n\n## Home\n\n- [ ] Paint fence\n"
    strict = TaskService(vault, today=lambda: "2026-09-25")
    with pytest.raises(ValueError, match="specify a board"):
        strict.create_task("Anything")
    assert [t["title"] for t in strict.list_tasks(board="other")] == ["Paint fence"]
    with pytest.raises(ValueError, match="no board named"):
        strict.list_tasks(board="nope")


def note_with_done():
    from tests.conftest import note

    return note("- [x] First step (done 2026-09-01)\n- [ ] Second step")


def test_audit_template_problems_are_one_line_per_open_note(service, vault):
    vault.files["Tasks/Alpha Task.md"] = "no structure\n"
    problems = service.audit_boards()["template_problems"]
    assert len(problems) == 1 and problems[0].startswith("Alpha Task: missing frontmatter")
    closed = service.audit_boards(include_closed=True)["template_problems"]
    assert any(item.startswith("Old Task") for item in closed)


def test_audit_caps_long_lists(service, vault):
    for n in range(5):
        vault.files[f"Tasks/Stray {n}.md"] = "x\n"
    report = service.audit_boards(limit=2)
    assert len(report["orphan_notes"]) == 2
    assert report["orphan_notes_truncated"].endswith("more not shown")


def test_audit_ignores_cards_without_a_link(service, vault):
    report = service.audit_boards()
    assert not any(
        "Plain card" in item
        for items in report.values()
        if isinstance(items, list)
        for item in items
    )
    assert not any("Plain card" in item for item in report["broken_links"])


def test_delete_task_removes_card_and_note(service, vault):
    before = vault.files["Board.md"]
    result = service.delete_task("Delta Task")
    assert result["note_deleted"] == "Tasks/Delta Task.md"
    assert "Tasks/Delta Task.md" not in vault.files
    assert vault.files["Board.md"].rstrip("\n") == before.replace("- [ ] [[Delta Task]]\n", "")


def test_delete_task_can_keep_the_note(service, vault):
    result = service.delete_task("Delta Task", delete_note=False)
    assert result["note_kept"] == "Tasks/Delta Task.md"
    assert "Tasks/Delta Task.md" in vault.files
    assert "Delta Task" not in lane_titles(vault, "Blocked or Waiting")


def test_delete_task_without_a_note_only_removes_the_card(service, vault):
    result = service.delete_task("Plain card")
    assert "note_deleted" not in result and "note_kept" not in result
    assert "Plain card without a note" not in lane_titles(vault, "Done")


def test_delete_task_refuses_when_other_notes_link_to_it(service, vault):
    vault.files["Tasks/Alpha Task.md"] += "\nSee also [[Beta Task]].\n"
    with pytest.raises(ValueError, match="broken links"):
        service.delete_task("Beta Task")
    assert "Tasks/Beta Task.md" in vault.files
    assert "Beta Task" in lane_titles(vault, "To Do")
    result = service.delete_task("Beta Task", force=True)
    assert result["broken_links_left_in"] == ["Tasks/Alpha Task.md"]
    assert "Tasks/Beta Task.md" not in vault.files


def test_delete_task_keeps_a_note_another_card_still_uses(service, vault):
    vault.files["Other.md"] = "---\nkanban-plugin: board\n---\n\n## Home\n\n- [ ] [[Alpha Task]]\n"
    result = service.delete_task("Alpha Task", board="Board")
    assert result["note_kept"] == "another card links to the same note"
    assert "Tasks/Alpha Task.md" in vault.files


def test_delete_task_unknown(service):
    with pytest.raises(ValueError, match="no card matching"):
        service.delete_task("Nope")
