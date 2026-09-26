import re

_FENCE = re.compile(r"\A---[ \t]*\n(.*?\n)?---[ \t]*(?:\n|\Z)", re.DOTALL)
_NULLS = {"null", "~"}
_CONTINUATION = re.compile(r"^(\s+\S|-\s)")


def split(text: str) -> tuple[str, str]:
    """Split a note into its raw frontmatter block (fences included) and its body."""
    match = _FENCE.match(text)
    if not match:
        return "", text
    return text[: match.end()], text[match.end() :]


def get(text: str, key: str) -> str | None:
    """Read a flat `Key: value` frontmatter entry, or None when absent or a YAML null."""
    front, _ = split(text)
    for line in front.splitlines():
        head, sep, value = line.partition(":")
        if sep and head.strip().lower() == key.lower():
            value = value.strip()
            return None if value.lower() in _NULLS else value
    return None


def _entry_span(lines: list[str], key: str) -> tuple[int, int] | None:
    """Find the line range of a key and any indented or `- item` lines that continue it."""
    for index, line in enumerate(lines[1:-1], start=1):
        head, sep, _ = line.partition(":")
        if sep and not line[:1].isspace() and head.strip().lower() == key.lower():
            end = index + 1
            while end < len(lines) - 1 and _CONTINUATION.match(lines[end]):
                end += 1
            return index, end
    return None


def _replace_entry(text: str, key: str, entry: list[str]) -> str:
    front, body = split(text)
    if not front:
        return "---\n" + "".join(entry) + "---\n" + body
    lines = front.splitlines(keepends=True)
    span = _entry_span(lines, key)
    if span:
        lines[span[0] : span[1]] = entry
    else:
        lines[len(lines) - 1 : len(lines) - 1] = entry
    return "".join(lines) + body


def set_value(text: str, key: str, value: str) -> str:
    """Set a flat frontmatter entry in place, adding it before the closing fence if missing."""
    return _replace_entry(text, key, [f"{key}: {value}".rstrip() + "\n"])


def set_list(text: str, key: str, items: list[str]) -> str:
    """Set an entry to a YAML block list, the only form Obsidian treats as a list."""
    return _replace_entry(text, key, [f"{key}:\n", *(f"  - {item}\n" for item in items)])


def get_list(text: str, key: str) -> list[str]:
    """Read an entry as a list from a block list, an inline list or a comma string."""
    front, _ = split(text)
    lines = front.splitlines(keepends=True)
    span = _entry_span(lines, key) if front else None
    if not span:
        return []
    inline = lines[span[0]].partition(":")[2].strip()
    if inline.lower() in _NULLS:
        return []
    if inline:
        raw = inline[1:-1] if inline.startswith("[") and inline.endswith("]") else inline
        parts = raw.split(",")
    else:
        parts = [line.strip()[1:] for line in lines[span[0] + 1 : span[1]] if line.strip()]
    return [part.strip().strip("\"'") for part in parts if part.strip().strip("\"'")]


def is_plain_string(text: str, key: str) -> bool:
    """True when the entry is a non-empty scalar, such as a comma string, not a list."""
    front, _ = split(text)
    lines = front.splitlines(keepends=True)
    span = _entry_span(lines, key) if front else None
    if not span:
        return False
    inline = lines[span[0]].partition(":")[2].strip()
    return bool(inline) and inline.lower() not in _NULLS and not inline.startswith("[")
