from obsidian_tasks_mcp.board import Board, Card
from tests.conftest import BOARD


def test_round_trip_is_lossless():
    assert Board.parse(BOARD).render() == BOARD
    assert Board.parse(BOARD + "\n").render() == BOARD + "\n"


def test_lanes_and_cards():
    board = Board.parse(BOARD)
    assert [lane.name for lane in board.lanes][:3] == ["To Do", "In Progress", "Blocked or Waiting"]
    gamma = board.find("gamma task")[0][1]
    assert gamma.extra == ["\t- [ ] nested checklist item"]
    assert [c.title for c in board.lane("done").cards] == [
        "Epsilon Task",
        "Zeta Task",
        "Plain card without a note",
    ]
    assert board.lane("done").cards[0].checked


def test_settings():
    assert Board.parse(BOARD).settings()["new-note-folder"] == "Tasks"
    assert Board.parse("## Lane\n").settings() == {}


def test_add_card_top_and_bottom():
    board = Board.parse(BOARD)
    lane = board.lane("To Do")
    board.add_card(lane, Card(False, "[[Top]]"))
    board.add_card(lane, Card(False, "[[Bottom]]"), bottom=True)
    assert [c.title for c in lane.cards] == ["Top", "Alpha Task", "Beta Task", "Bottom"]
    text = board.render()
    assert "- [ ] [[Top]]\n- [ ] [[Alpha Task]]\n" in text
    assert "- [ ] [[Beta Task]]\n- [ ] [[Bottom]]\n" in text


def test_add_card_only_touches_its_lane():
    board = Board.parse(BOARD)
    board.add_card(board.lane("Blocked or Waiting"), Card(False, "[[New]]"))
    changed = board.render().replace("- [ ] [[New]]\n", "")
    assert changed == BOARD


def test_add_card_into_done_goes_after_label():
    board = Board.parse(BOARD)
    done = board.lane("Done")
    board.add_card(done, Card(True, "[[New]]"))
    assert "**Complete**\n- [x] [[New]]\n- [x] [[Epsilon Task]]" in board.render()


def test_add_card_to_empty_lane():
    board = Board.parse("## A\n\n## B\n")
    board.add_card(board.lane("A"), Card(False, "[[X]]"))
    assert board.render() == "## A\n\n- [ ] [[X]]\n\n\n## B\n"
    tight = Board.parse("## A\n## B\n")
    tight.add_card(tight.lane("A"), Card(False, "[[X]]"))
    assert tight.render() == "## A\n\n- [ ] [[X]]\n\n\n## B\n"


def test_add_card_to_last_lane_without_trailing_newline():
    board = Board.parse("## A")
    board.add_card(board.lane("A"), Card(False, "[[X]]"))
    assert board.render() == "## A\n\n- [ ] [[X]]"


def test_remove_card_keeps_everything_else():
    board = Board.parse(BOARD)
    lane, card = board.find("Delta Task")[0]
    board.remove_card(lane, card)
    assert board.render() == BOARD.replace("- [ ] [[Delta Task]]\n", "")


def test_set_checked_rewrites_only_that_line():
    board = Board.parse(BOARD)
    _, card = board.find("Zeta Task")[0]
    card.set_checked(True)
    assert board.render() == BOARD.replace("- [ ] [[Zeta Task]]", "- [x] [[Zeta Task]]")


def test_wikilink_variants():
    assert Card(False, "[[Note|Alias]] extra").link == "Note"
    assert Card(False, "[[Note#Heading]]").title == "Note"
    assert Card(False, "Just text").title == "Just text"


def test_add_card_to_empty_lane_goes_below_its_label():
    board = Board.parse("## Done\n\n**Complete**\n\n\n## Next\n")
    board.add_card(board.lane("Done"), Card(True, "[[X]]"))
    assert board.render() == "## Done\n\n**Complete**\n- [x] [[X]]\n\n\n## Next\n"


def test_add_card_to_empty_lane_before_separator_and_settings():
    board = Board.parse("## A\n\n\n***\n\n## B\n\n%% kanban:settings\n```\n{}\n```\n%%")
    board.add_card(board.lane("A"), Card(False, "[[X]]"))
    assert board.render().startswith("## A\n\n- [ ] [[X]]\n\n\n***\n")
    last = Board.parse("## B\n\n%% kanban:settings\n```\n{}\n```\n%%")
    last.add_card(last.lane("B"), Card(False, "[[X]]"))
    assert last.render().startswith("## B\n\n- [ ] [[X]]\n\n%% kanban:settings")
