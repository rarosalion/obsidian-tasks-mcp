import hashlib

import pytest

from obsidian_tasks_mcp import frontmatter
from obsidian_tasks_mcp.service import TaskService
from obsidian_tasks_mcp.vault import ConflictError, Document, ExistsError, NotFoundError

BOARD = """---

kanban-plugin: board

---

## To Do

- [ ] [[Alpha Task]]

- [ ] [[Beta Task]]


## In Progress

- [ ] [[Gamma Task]]
\t- [ ] nested checklist item


## Blocked or Waiting

- [ ] [[Delta Task]]


## Long-Term

- [ ] [[Someday Task]]


## Done

**Complete**
- [x] [[Epsilon Task]]
- [ ] [[Zeta Task]]
- [x] Plain card without a note


## Cancelled

- [ ] [[Missing Note]]


***

## Archive

- [ ] [[Old Task]]

%% kanban:settings
```
{"kanban-plugin":"board","new-note-template":"Templates/Card.md","new-note-folder":"Tasks"}
```
%%"""

TEMPLATE = """---
Due By:
Assigned to:
Planned by:
Tags:
Completed On:
---
%% Guidance comment that must not be copied into new notes. %%
# Summary
%% Another
multi-line comment. %%

# Subtasks
%% Checklist guidance. %%
- [ ]

# Detailed Plan
%% Plan guidance. %%

# Questions to Consider
%% Questions guidance. %%

# Running Log
%% Log guidance. %%
"""


def note(
    subtasks: str = "- [ ] First step\n- [ ] Second step",
    completed: str = "",
    due: str = "",
    assigned: str = "Sam",
) -> str:
    return (
        f"---\nDue By: {due}\nAssigned to: {assigned}\nPlanned by: Claude\nTags:\n"
        f"Completed On: {completed}\n---\n# Summary\n\nDoes a thing.\n\n"
        f"# Subtasks\n\n{subtasks}\n\n"
        "# Detailed Plan\n\n# Questions to Consider\n\n# Running Log\n"
    )


FILES = {
    "Board.md": BOARD,
    "Templates/Card.md": TEMPLATE,
    "Tasks/Alpha Task.md": note(),
    "Tasks/Beta Task.md": note(due="2020-01-01"),
    "Tasks/Gamma Task.md": note(),
    "Tasks/Delta Task.md": note(),
    "Tasks/Someday Task.md": note(),
    "Tasks/Epsilon Task.md": note("- [x] First step", completed="2026-01-02"),
    "Tasks/Zeta Task.md": note("- [x] First step"),
    "Tasks/Old Task.md": "no frontmatter here\n",
    "Tasks/Stray Note.md": note(),
}


class FakeVault:
    def __init__(self, files: dict[str, str]):
        self.files = dict(files)
        self.before_write = None

    @staticmethod
    def _version(text: str) -> str:
        return hashlib.sha1(text.encode()).hexdigest()[:8]

    def read(self, path: str, consistent: bool = True) -> Document:
        if path not in self.files:
            raise NotFoundError(path)
        return Document(path, self.files[path], self._version(self.files[path]))

    def write(self, doc: Document, new_text: str) -> None:
        if new_text == doc.text:
            return
        if self.before_write:
            hook, self.before_write = self.before_write, None
            hook(self)
        if self._version(self.files[doc.path]) != doc.version:
            raise ConflictError(doc.path)
        self.files[doc.path] = new_text if new_text.endswith("\n") else new_text + "\n"

    def create(self, path: str, text: str) -> None:
        if path in self.files:
            raise ExistsError(path)
        self.files[path] = text

    def exists(self, path: str) -> bool:
        return path in self.files

    def list_folder(self, folder: str) -> list[str]:
        prefix = folder.strip("/") + "/"
        return sorted(p for p in self.files if p.startswith(prefix) and "/" not in p[len(prefix) :])

    def find_boards(self) -> list[str]:
        return [p for p, t in self.files.items() if frontmatter.get(t, "kanban-plugin") == "board"]

    def find_by_name(self, name: str) -> list[str]:
        return [p for p in self.files if p.rsplit("/", 1)[-1] == f"{name}.md"]

    def find_linking_to(self, path: str) -> list[str]:
        stem = path.rsplit("/", 1)[-1].removesuffix(".md")
        return [p for p, text in self.files.items() if f"[[{stem}]]" in text]

    def delete(self, path: str) -> None:
        if path not in self.files:
            raise NotFoundError(path)
        del self.files[path]


@pytest.fixture
def vault() -> FakeVault:
    return FakeVault(FILES)


@pytest.fixture
def service(vault: FakeVault) -> TaskService:
    return TaskService(vault, default_board="Board", today=lambda: "2026-09-25")
