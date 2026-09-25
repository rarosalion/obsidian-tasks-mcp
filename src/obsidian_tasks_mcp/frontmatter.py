import re

_FENCE = re.compile(r"\A---[ \t]*\n(.*?\n)?---[ \t]*(?:\n|\Z)", re.DOTALL)


def split(text: str) -> tuple[str, str]:
    """Split a note into its raw frontmatter block (fences included) and its body."""
    match = _FENCE.match(text)
    if not match:
        return "", text
    return text[: match.end()], text[match.end() :]


def get(text: str, key: str) -> str | None:
    """Read a flat `Key: value` frontmatter entry, or None when absent."""
    front, _ = split(text)
    for line in front.splitlines():
        head, sep, value = line.partition(":")
        if sep and head.strip().lower() == key.lower():
            return value.strip()
    return None


def set_value(text: str, key: str, value: str) -> str:
    """Set a flat frontmatter entry in place, adding it before the closing fence if missing."""
    front, body = split(text)
    if not front:
        return f"---\n{key}: {value}\n---\n{body}"
    lines = front.splitlines(keepends=True)
    entry = f"{key}: {value}".rstrip() + "\n"
    for index, line in enumerate(lines[1:-1], start=1):
        head, sep, _ = line.partition(":")
        if sep and head.strip().lower() == key.lower():
            lines[index] = entry
            return "".join(lines) + body
    lines.insert(len(lines) - 1, entry)
    return "".join(lines) + body
