import pytest

from obsidian_tasks_mcp import frontmatter, notes
from tests.conftest import TEMPLATE, note


def test_subtasks_and_progress():
    text = note("- [x] One\n- [ ] Two\n  - [ ] not top level")
    assert [(s.index, s.checked, s.text) for s in notes.subtasks(text)] == [
        (1, True, "One"),
        (2, False, "Two"),
    ]
    assert notes.progress(text) == (1, 2)


def test_progress_ignores_the_empty_placeholder():
    assert notes.progress(note("- [ ]")) == (0, 0)


def test_set_subtask_by_index_and_text():
    text = note()
    done = notes.set_subtask(text, 2, True, "shipped it", "2026-09-25")
    assert "- [x] Second step (done 2026-09-25: shipped it)" in done
    assert notes.set_subtask(text, "first", True, "", "2026-09-25").count("(done 2026-09-25)") == 1
    assert notes.set_subtask(text, "2", True, "", "2026-09-25") == notes.set_subtask(
        text, 2, True, "", "2026-09-25"
    )


def test_uncheck_strips_the_done_suffix():
    text = notes.set_subtask(note(), 1, True, "n", "2026-09-25")
    assert "- [ ] First step\n" in notes.set_subtask(text, 1, False, "", "2026-09-26")


def test_set_subtask_errors():
    with pytest.raises(ValueError, match="does not exist"):
        notes.set_subtask(note(), 9, True, "", "d")
    with pytest.raises(ValueError, match="matches 2"):
        notes.set_subtask(note(), "step", True, "", "d")
    with pytest.raises(ValueError, match="matches 0"):
        notes.set_subtask(note(), "nothing", True, "", "d")


def test_add_subtask_replaces_placeholder_then_appends():
    once = notes.add_subtask(note("- [ ]"), "Only", None)
    assert [s.text for s in notes.subtasks(once)] == ["Only"]
    twice = notes.add_subtask(once, "Next", None)
    assert [s.text for s in notes.subtasks(twice)] == ["Only", "Next"]
    middle = notes.add_subtask(note(), "Between", 1)
    assert [s.text for s in notes.subtasks(middle)] == ["First step", "Between", "Second step"]


def test_append_log_in_existing_and_missing_section():
    logged = notes.append_log(note(), "did a thing", "2026-09-25")
    assert logged.endswith("# Running Log\n\n- 2026-09-25: did a thing\n")
    again = notes.append_log(logged, "and another", "2026-09-26")
    assert again.endswith("- 2026-09-25: did a thing\n- 2026-09-26: and another\n")
    bare = notes.append_log("---\nA: b\n---\n# Summary\n\nx\n", "entry", "2026-09-25")
    assert bare.endswith("# Running Log\n\n- 2026-09-25: entry\n")


def test_render_new_from_template_strips_comments():
    text = notes.render_new(
        TEMPLATE,
        fields={"Assigned to": "Sam", "Planned by": "Claude", "Due By": "", "Tags": "x, y"},
        summary="Do the work.",
        subtask_items=["One", "Two"],
        detailed_plan="",
        questions=["Which way?"],
    )
    assert "%%" not in text
    assert frontmatter.get(text, "Assigned to") == "Sam"
    assert frontmatter.get(text, "Due By") == ""
    assert frontmatter.get(text, "Tags") == "x, y"
    assert notes.section(text, "Summary") == "Do the work."
    assert [s.text for s in notes.subtasks(text)] == ["One", "Two"]
    assert notes.section(text, "Questions to Consider") == "- [ ] Which way?"
    assert notes.headings(text) == [
        "Summary",
        "Subtasks",
        "Detailed Plan",
        "Questions to Consider",
        "Running Log",
    ]
    assert notes.problems(text) == []


def test_render_new_default_template_and_placeholder():
    text = notes.render_new(
        None, fields={}, summary="", subtask_items=[], detailed_plan="", questions=[]
    )
    assert notes.problems(text) == []
    assert notes.progress(text) == (0, 0)
    assert "- [ ]\n" in text


def test_problems_reports_deviations():
    assert notes.problems("just text\n") == [
        "missing frontmatter",
        "missing section 'Summary'",
        "missing section 'Subtasks'",
        "missing section 'Detailed Plan'",
        "missing section 'Questions to Consider'",
    ]
    partial = "---\nDue By:\n---\n# Summary\n"
    found = notes.problems(partial)
    assert "frontmatter is missing 'Assigned to'" in found
    assert "missing section 'Subtasks'" in found
