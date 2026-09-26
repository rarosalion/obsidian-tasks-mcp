from obsidian_tasks_mcp import frontmatter


def test_split_and_get():
    text = "---\nDue By: 2026-01-01\nTags:\n---\n# Body\n"
    front, body = frontmatter.split(text)
    assert front == "---\nDue By: 2026-01-01\nTags:\n---\n"
    assert body == "# Body\n"
    assert frontmatter.get(text, "due by") == "2026-01-01"
    assert frontmatter.get(text, "Tags") == ""
    assert frontmatter.get(text, "Missing") is None


def test_no_frontmatter():
    assert frontmatter.split("# Body\n") == ("", "# Body\n")
    assert frontmatter.get("# Body\n", "x") is None


def test_split_keeps_blank_lines_inside_fence():
    text = "---\n\nkanban-plugin: board\n\n---\n\n## To Do\n"
    front, body = frontmatter.split(text)
    assert front == "---\n\nkanban-plugin: board\n\n---\n"
    assert body == "\n## To Do\n"


def test_set_value_replaces_and_adds():
    text = "---\nDue By:\nTags: a\n---\n# Body\n"
    assert frontmatter.set_value(text, "Due By", "2026-02-03") == (
        "---\nDue By: 2026-02-03\nTags: a\n---\n# Body\n"
    )
    assert frontmatter.set_value(text, "Owner", "Sam") == (
        "---\nDue By:\nTags: a\nOwner: Sam\n---\n# Body\n"
    )


def test_set_value_creates_frontmatter():
    assert frontmatter.set_value("# Body\n", "Key", "v") == "---\nKey: v\n---\n# Body\n"


def test_get_treats_yaml_null_as_absent():
    text = "---\nDue By: null\nTags: ~\nAssigned to: Sam\n---\nbody\n"
    assert frontmatter.get(text, "Due By") is None
    assert frontmatter.get(text, "Tags") is None
    assert frontmatter.get(text, "Assigned to") == "Sam"
