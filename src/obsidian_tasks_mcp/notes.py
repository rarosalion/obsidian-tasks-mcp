"""Reading and editing task notes that follow the card template.

A task note has flat frontmatter and top-level `# Heading` sections (Summary, Subtasks, Detailed
Plan, Questions to Consider, Running Log). All edits are line-based so anything they do not
touch is preserved exactly.
"""

import re
from dataclasses import dataclass

from . import frontmatter

REQUIRED_SECTIONS = ("Summary", "Subtasks", "Detailed Plan", "Questions to Consider")
FRONTMATTER_KEYS = ("Due By", "Assigned to", "Planned by", "Tags", "Completed On")

DEFAULT_TEMPLATE = """---
Due By:
Assigned to:
Planned by:
Tags:
Completed On:
---
# Summary

# Subtasks

- [ ]

# Detailed Plan

# Questions to Consider

# Running Log
"""

_HEADING = re.compile(r"^# (.+?)\s*$")
_CHECKBOX = re.compile(r"^- \[([ xX])\] ?(.*)$")
_COMMENT = re.compile(r"%%.*?%%", re.DOTALL)
_TAG = re.compile(r"^[\w/-]+$")
_DONE_SUFFIX = re.compile(r"\s*\(done \d{4}-\d{2}-\d{2}[^)]*\)\s*$")


@dataclass
class Subtask:
    index: int
    checked: bool
    text: str
    line: int


def _section_range(lines: list[str], name: str) -> tuple[int, int] | None:
    """Return (heading line, first line of the next heading or end) for a section."""
    wanted = name.lower()
    start = None
    for i, line in enumerate(lines):
        match = _HEADING.match(line)
        if not match:
            continue
        if start is not None:
            return start, i
        if match.group(1).lower() == wanted:
            start = i
    return (start, len(lines)) if start is not None else None


def section(text: str, name: str) -> str | None:
    lines = text.split("\n")
    found = _section_range(lines, name)
    if not found:
        return None
    return "\n".join(lines[found[0] + 1 : found[1]]).strip("\n")


def headings(text: str) -> list[str]:
    return [m.group(1) for line in text.split("\n") if (m := _HEADING.match(line))]


def subtasks(text: str) -> list[Subtask]:
    lines = text.split("\n")
    found = _section_range(lines, "Subtasks")
    if not found:
        return []
    result = []
    for i in range(found[0] + 1, found[1]):
        match = _CHECKBOX.match(lines[i])
        if match:
            result.append(
                Subtask(len(result) + 1, match.group(1).lower() == "x", match.group(2), i)
            )
    return result


def progress(text: str) -> tuple[int, int]:
    real = [s for s in subtasks(text) if s.text.strip()]
    return sum(s.checked for s in real), len(real)


def _resolve(text: str, ref: int | str) -> Subtask:
    items = subtasks(text)
    if isinstance(ref, str) and ref.strip().isdigit():
        ref = int(ref)
    if isinstance(ref, int):
        if not 1 <= ref <= len(items):
            raise ValueError(f"subtask {ref} does not exist ({len(items)} subtasks)")
        return items[ref - 1]
    matches = [s for s in items if ref.lower() in s.text.lower()]
    if len(matches) != 1:
        raise ValueError(
            f"{ref!r} matches {len(matches)} subtasks; use a longer text or its 1-based index"
        )
    return matches[0]


def set_subtask(text: str, ref: int | str, checked: bool, note: str, today: str) -> str:
    target = _resolve(text, ref)
    lines = text.split("\n")
    body = _DONE_SUFFIX.sub("", target.text)
    if checked:
        suffix = f" (done {today}: {note})" if note else f" (done {today})"
        body += suffix
    lines[target.line] = f"- [{'x' if checked else ' '}] {body}"
    return "\n".join(lines)


def add_subtask(text: str, item: str, after: int | str | None = None) -> str:
    lines = text.split("\n")
    found = _section_range(lines, "Subtasks")
    if not found:
        raise ValueError("the note has no Subtasks section")
    existing = subtasks(text)
    placeholder = [s for s in existing if not s.text.strip()]
    if placeholder and len(placeholder) == len(existing):
        lines[placeholder[0].line] = f"- [ ] {item}"
        return "\n".join(lines)
    if after is not None:
        position = _resolve(text, after).line + 1
    elif existing:
        position = existing[-1].line + 1
    else:
        position = found[0] + 1
        lines.insert(position, "")
        position += 1
    lines.insert(position, f"- [ ] {item}")
    return "\n".join(lines)


def append_log(text: str, entry: str, today: str) -> str:
    line = f"- {today}: {entry}"
    lines = text.split("\n")
    found = _section_range(lines, "Running Log")
    if not found:
        return text.rstrip("\n") + f"\n\n# Running Log\n\n{line}\n"
    end = found[1]
    while end > found[0] + 1 and not lines[end - 1].strip():
        end -= 1
    if end == found[0] + 1:
        lines[found[0] + 1 : found[1]] = ["", line, ""] if found[1] < len(lines) else ["", line]
    else:
        lines.insert(end, line)
    out = "\n".join(lines)
    return out if out.endswith("\n") else out + "\n"


def _replace_body(lines: list[str], name: str, body: list[str]) -> list[str]:
    found = _section_range(lines, name)
    if not found:
        return lines
    start, end = found
    at_end = end == len(lines)
    block = ["", *body, ""] if body else [""]
    if at_end and body:
        block = ["", *body]
    return lines[: start + 1] + block + lines[end:]


def normalize_tags(tags: list[str]) -> list[str]:
    """Trim tags, drop a leading `#`, remove empties and duplicates, and reject unusable ones."""
    result: list[str] = []
    for raw in tags:
        tag = raw.strip().lstrip("#").strip()
        if not tag:
            continue
        if not _TAG.match(tag):
            raise ValueError(
                f"invalid tag {raw!r}: tags may only contain letters, numbers, _, - and /; "
                "pass each tag as a separate list item"
            )
        if tag.lower() not in {t.lower() for t in result}:
            result.append(tag)
    return result


def render_new(
    template: str | None,
    *,
    fields: dict[str, str],
    summary: str,
    subtask_items: list[str],
    detailed_plan: str,
    questions: list[str],
    tags: list[str] | None = None,
) -> str:
    text = _COMMENT.sub("", template or DEFAULT_TEMPLATE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    for key, value in fields.items():
        if value:
            text = frontmatter.set_value(text, key, value)
    if tags:
        text = frontmatter.set_list(text, "Tags", normalize_tags(tags))
    lines = text.rstrip("\n").split("\n")
    lines = _replace_body(lines, "Summary", summary.strip().split("\n") if summary.strip() else [])
    tasks = [f"- [ ] {item}" for item in subtask_items] or ["- [ ]"]
    lines = _replace_body(lines, "Subtasks", tasks)
    plan = detailed_plan.strip().split("\n") if detailed_plan.strip() else []
    lines = _replace_body(lines, "Detailed Plan", plan)
    lines = _replace_body(lines, "Questions to Consider", [f"- [ ] {q}" for q in questions])
    return "\n".join(lines).rstrip("\n") + "\n"


def problems(text: str) -> list[str]:
    """List deviations from the card template, empty when the note conforms."""
    found = []
    front, _ = frontmatter.split(text)
    if not front:
        found.append("missing frontmatter")
    else:
        found += [
            f"frontmatter is missing {key!r}"
            for key in FRONTMATTER_KEYS
            if frontmatter.get(text, key) is None
        ]
    present = {h.lower() for h in headings(text)}
    found += [
        f"missing section {name!r}" for name in REQUIRED_SECTIONS if name.lower() not in present
    ]
    return found
