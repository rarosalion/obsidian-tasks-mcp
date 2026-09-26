import datetime
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from . import frontmatter, notes
from .board import Board, Card, Lane
from .vault import ConflictError, Document, NotFoundError, Vault

_TODO = ("to do", "todo", "backlog")
_PROGRESS = ("in progress", "doing")
_BLOCKED = ("blocked or waiting", "blocked", "waiting")
_DONE = ("done", "complete", "completed")
_CLOSED = ("cancelled", "canceled", "archive", "archived")
_BAD_TITLE = re.compile(r'[\\/:*?"<>|#^\[\]]')
_ATTEMPTS = 3
_WORKERS = 8


def lane_kind(name: str) -> str:
    lowered = name.strip().lower()
    for kind, names in (
        ("todo", _TODO),
        ("progress", _PROGRESS),
        ("blocked", _BLOCKED),
        ("done", _DONE),
        ("closed", _CLOSED),
    ):
        if lowered in names:
            return kind
    return "other"


@dataclass
class Hit:
    board: str
    lane: str
    card: Card
    settings: dict

    @property
    def kind(self) -> str:
        return lane_kind(self.lane)


class TaskService:
    def __init__(
        self,
        vault: Vault,
        default_board: str | None = None,
        today: Callable[[], str] | None = None,
    ):
        self.vault = vault
        self.default_board = default_board
        self._today = today or (lambda: datetime.date.today().isoformat())

    def _board_paths(self) -> list[str]:
        return sorted(self.vault.find_boards())

    def _pick_board(self, name: str | None) -> str:
        paths = self._board_paths()
        wanted = name or self.default_board
        if wanted:
            for path in paths:
                stem = path.rsplit("/", 1)[-1].removesuffix(".md")
                if wanted.lower() in (path.lower(), stem.lower()):
                    return path
            raise ValueError(f"no board named {wanted!r}; boards are {self._names(paths)}")
        if len(paths) == 1:
            return paths[0]
        raise ValueError(f"specify a board; boards are {self._names(paths)}")

    @staticmethod
    def _names(paths: list[str]) -> list[str]:
        return [p.rsplit("/", 1)[-1].removesuffix(".md") for p in paths]

    def _edit(self, path: str, mutate: Callable[[str], str]) -> None:
        for attempt in range(_ATTEMPTS):
            doc = self.vault.read(path)
            try:
                self.vault.write(doc, mutate(doc.text))
                return
            except ConflictError:
                if attempt == _ATTEMPTS - 1:
                    raise

    def _edit_board(self, path: str, mutate: Callable[[Board], Any]) -> Any:
        result: dict[str, Any] = {}

        def apply(text: str) -> str:
            board = Board.parse(text)
            result["value"] = mutate(board)
            return board.render()

        self._edit(path, apply)
        return result.get("value")

    def _load_board(self, path: str) -> tuple[Document, Board]:
        doc = self.vault.read(path)
        return doc, Board.parse(doc.text)

    def _folder(self, settings: dict) -> str:
        return str(settings.get("new-note-folder") or "").strip("/")

    def _note_path(self, link: str, folders: list[str]) -> str | None:
        for folder in folders:
            candidate = f"{folder}/{link}.md" if folder else f"{link}.md"
            if self.vault.exists(candidate):
                return candidate
        found = self.vault.find_by_name(link)
        return found[0] if found else None

    def _locate(self, title: str, board: str | None) -> Hit:
        paths = [self._pick_board(board)] if board else self._board_paths()
        hits: list[Hit] = []
        partial: list[Hit] = []
        wanted = title.strip().lower()
        for path in paths:
            _, parsed = self._load_board(path)
            settings = parsed.settings()
            for lane in parsed.lanes:
                for card in lane.cards:
                    hit = Hit(path, lane.name, card, settings)
                    if card.title.lower() == wanted:
                        hits.append(hit)
                    elif wanted in card.title.lower():
                        partial.append(hit)
        matches = hits or partial
        if not matches:
            raise ValueError(f"no card matching {title!r}")
        if len(matches) > 1:
            where = [f"{self._names([h.board])[0]}/{h.lane}: {h.card.title}" for h in matches]
            raise ValueError(f"{title!r} is ambiguous: {where}")
        return matches[0]

    def _card_note(self, hit: Hit) -> str | None:
        link = hit.card.link
        return self._note_path(link, [self._folder(hit.settings), ""]) if link else None

    def _lane_named(self, board: Board, name: str) -> Lane:
        lane = board.lane(name)
        if lane is None:
            raise ValueError(f"no lane {name!r}; lanes are {[lane.name for lane in board.lanes]}")
        return lane

    def list_boards(self) -> list[dict]:
        result = []
        for path in self._board_paths():
            _, parsed = self._load_board(path)
            result.append(
                {
                    "board": self._names([path])[0],
                    "path": path,
                    "lanes": [{"name": la.name, "cards": len(la.cards)} for la in parsed.lanes],
                }
            )
        return result

    def _read_note(self, path: str | None) -> str | None:
        if not path:
            return None
        try:
            return self.vault.read(path, consistent=False).text
        except NotFoundError:
            return None

    def list_tasks(
        self,
        board: str | None = None,
        lane: str | None = None,
        overdue: bool = False,
        assigned_to: str | None = None,
        tag: str | None = None,
        include_closed: bool = False,
    ) -> list[dict]:
        paths = [self._pick_board(board)] if board else self._board_paths()
        hits: list[Hit] = []
        for path in paths:
            _, parsed = self._load_board(path)
            settings = parsed.settings()
            for la in parsed.lanes:
                if lane and la.name.lower() != lane.lower():
                    continue
                if not lane and not include_closed and lane_kind(la.name) in ("done", "closed"):
                    continue
                hits.extend(Hit(path, la.name, card, settings) for card in la.cards)
        with ThreadPoolExecutor(_WORKERS) as pool:
            texts = list(pool.map(lambda h: self._read_note(self._card_note(h)), hits))
        today = self._today()
        result = []
        for hit, text in zip(hits, texts, strict=True):
            entry = self._summary(hit, text)
            if assigned_to and (entry.get("assigned_to") or "").lower() != assigned_to.lower():
                continue
            if tag and tag.lower() not in (entry.get("tags") or "").lower():
                continue
            due = entry.get("due_by")
            if overdue and not (due and due < today and hit.kind not in ("done", "closed")):
                continue
            result.append(entry)
        return result

    def _summary(self, hit: Hit, text: str | None) -> dict:
        entry: dict[str, Any] = {
            "title": hit.card.title,
            "board": self._names([hit.board])[0],
            "lane": hit.lane,
            "checked": hit.card.checked,
            "has_note": text is not None,
        }
        if text is not None:
            done, total = notes.progress(text)
            entry["subtasks"] = f"{done}/{total}"
            for key, name in (
                ("due_by", "Due By"),
                ("assigned_to", "Assigned to"),
                ("tags", "Tags"),
                ("completed_on", "Completed On"),
            ):
                entry[key] = frontmatter.get(text, name) or None
        return entry

    def get_task(self, title: str, board: str | None = None) -> dict:
        hit = self._locate(title, board)
        path = self._card_note(hit)
        text = self._read_note(path)
        entry = self._summary(hit, text)
        entry["title"] = hit.card.title
        entry["note_path"] = path
        if text is not None:
            entry["sections"] = {
                name: notes.section(text, name) or "" for name in notes.headings(text)
            }
            entry["subtask_items"] = [
                {"index": s.index, "checked": s.checked, "text": s.text}
                for s in notes.subtasks(text)
            ]
        return entry

    def create_task(
        self,
        title: str,
        summary: str = "",
        subtasks: list[str] | None = None,
        board: str | None = None,
        lane: str = "To Do",
        priority: str = "normal",
        detailed_plan: str = "",
        questions: list[str] | None = None,
        assigned_to: str = "",
        planned_by: str = "Claude",
        due_by: str = "",
        tags: str = "",
    ) -> dict:
        title = title.strip()
        if not title or _BAD_TITLE.search(title):
            raise ValueError('the title must be non-empty and free of \\ / : * ? " < > | # ^ [ ]')
        path = self._pick_board(board)
        _, parsed = self._load_board(path)
        target = self._lane_named(parsed, lane)
        settings = parsed.settings()
        for other in self._board_paths():
            _, other_board = self._load_board(other)
            if other_board.find(title):
                raise ValueError(f"a card called {title!r} already exists on {other}")
        folder = self._folder(settings)
        if not folder:
            raise ValueError(
                f"{self._names([path])[0]} has no new-note-folder setting; set it in the Kanban "
                "plugin's board settings so new notes do not land in the vault root"
            )
        note_path = f"{folder}/{title}.md"
        template = None
        if settings.get("new-note-template"):
            try:
                template = self.vault.read(str(settings["new-note-template"])).text
            except NotFoundError:
                template = None
        text = notes.render_new(
            template,
            fields={
                "Due By": due_by,
                "Assigned to": assigned_to,
                "Planned by": planned_by,
                "Tags": tags,
            },
            summary=summary,
            subtask_items=subtasks or [],
            detailed_plan=detailed_plan,
            questions=questions or [],
        )
        self.vault.create(note_path, text)
        checked = lane_kind(target.name) == "done"
        self._edit_board(
            path,
            lambda b: b.add_card(
                self._lane_named(b, lane),
                Card(checked, f"[[{title}]]"),
                bottom=priority == "low",
            ),
        )
        return {
            "title": title,
            "board": self._names([path])[0],
            "lane": target.name,
            "note_path": note_path,
        }

    def _move(self, hit: Hit, to_lane: str, bottom: bool) -> dict:
        def mutate(b: Board) -> str:
            source, card = self._find_card(b, hit.card.title)
            target = self._lane_named(b, to_lane)
            if source is target:
                return target.name
            b.remove_card(source, card)
            card.set_checked(lane_kind(target.name) == "done")
            b.add_card(target, card, bottom=bottom)
            return target.name

        landed = self._edit_board(hit.board, mutate)
        result = {
            "title": hit.card.title,
            "board": self._names([hit.board])[0],
            "from": hit.lane,
            "to": landed,
        }
        if lane_kind(landed) == "done" and hit.kind != "done":
            path = self._card_note(hit)
            if path:
                result["completed_on"] = self._stamp_completed(path)
        return result

    def _find_card(self, board: Board, title: str) -> tuple[Lane, Card]:
        found = board.find(title)
        if len(found) != 1:
            raise ValueError(f"expected exactly one card {title!r}, found {len(found)}")
        return found[0]

    def _stamp_completed(self, path: str) -> str | None:
        stamped: dict[str, str | None] = {}

        def apply(text: str) -> str:
            current = frontmatter.get(text, "Completed On")
            if current:
                stamped["value"] = current
                return text
            stamped["value"] = self._today()
            return frontmatter.set_value(text, "Completed On", self._today())

        self._edit(path, apply)
        return stamped.get("value")

    def move_task(
        self, title: str, to_lane: str, board: str | None = None, priority: str = "normal"
    ) -> dict:
        return self._move(self._locate(title, board), to_lane, bottom=priority == "low")

    def _lane_for_progress(self, hit: Hit, blocked: bool) -> str | None:
        _, parsed = self._load_board(hit.board)
        wanted = "blocked" if blocked else "progress"
        for lane in parsed.lanes:
            if lane_kind(lane.name) == wanted:
                return lane.name
        return None

    def _auto_progress(self, hit: Hit, blocked: bool) -> str | None:
        if hit.kind != "todo":
            return None
        lane = self._lane_for_progress(hit, blocked)
        if not lane:
            return None
        self._move(hit, lane, bottom=False)
        return lane

    def _note_for(self, title: str, board: str | None) -> tuple[Hit, str]:
        hit = self._locate(title, board)
        path = self._card_note(hit)
        if not path:
            raise ValueError(f"{hit.card.title!r} has no task note")
        return hit, path

    def update_subtask(
        self,
        title: str,
        subtask: int | str,
        checked: bool = True,
        note: str = "",
        board: str | None = None,
        blocked: bool = False,
    ) -> dict:
        hit, path = self._note_for(title, board)
        final: dict[str, str] = {}

        def apply(text: str) -> str:
            out = notes.set_subtask(text, subtask, checked, note, self._today())
            final["text"] = out
            return out

        self._edit(path, apply)
        done, total = notes.progress(final["text"])
        result: dict[str, Any] = {"title": hit.card.title, "subtasks": f"{done}/{total}"}
        if checked:
            moved = self._auto_progress(hit, blocked)
            if moved:
                result["moved_to"] = moved
            if total and done == total:
                result["all_subtasks_done"] = True
        return result

    def add_subtask(
        self, title: str, text: str, after: int | str | None = None, board: str | None = None
    ) -> dict:
        hit, path = self._note_for(title, board)
        final: dict[str, str] = {}

        def apply(current: str) -> str:
            final["text"] = notes.add_subtask(current, text, after)
            return final["text"]

        self._edit(path, apply)
        done, total = notes.progress(final["text"])
        return {"title": hit.card.title, "subtasks": f"{done}/{total}"}

    def append_log(
        self, title: str, entry: str, board: str | None = None, blocked: bool = False
    ) -> dict:
        hit, path = self._note_for(title, board)
        self._edit(path, lambda text: notes.append_log(text, entry, self._today()))
        result: dict[str, Any] = {"title": hit.card.title}
        moved = self._auto_progress(hit, blocked)
        if moved:
            result["moved_to"] = moved
        return result

    def set_task_fields(
        self,
        title: str,
        board: str | None = None,
        due_by: str | None = None,
        assigned_to: str | None = None,
        planned_by: str | None = None,
        tags: str | None = None,
        completed_on: str | None = None,
    ) -> dict:
        hit, path = self._note_for(title, board)
        changes = {
            "Due By": due_by,
            "Assigned to": assigned_to,
            "Planned by": planned_by,
            "Tags": tags,
            "Completed On": completed_on,
        }
        applied = {k: v for k, v in changes.items() if v is not None}

        def apply(text: str) -> str:
            for key, value in applied.items():
                text = frontmatter.set_value(text, key, value)
            return text

        self._edit(path, apply)
        return {"title": hit.card.title, "updated": applied}

    def delete_task(
        self,
        title: str,
        board: str | None = None,
        delete_note: bool = True,
        force: bool = False,
    ) -> dict:
        hit = self._locate(title, board)
        path = self._card_note(hit)
        result: dict[str, Any] = {
            "title": hit.card.title,
            "board": self._names([hit.board])[0],
            "lane": hit.lane,
            "card_removed": True,
        }
        remove_note = False
        if path and delete_note:
            shared = sum(
                len(self._load_board(b)[1].find(hit.card.title)) for b in self._board_paths()
            )
            if shared > 1:
                result["note_kept"] = "another card links to the same note"
            else:
                boards = set(self._board_paths())
                others = [
                    p for p in self.vault.find_linking_to(path) if p != path and p not in boards
                ]
                if others and not force:
                    raise ValueError(
                        f"{path} is linked from {others}; deleting it would leave broken links. "
                        "Pass force=True to delete anyway, or delete_note=False to keep the note."
                    )
                remove_note = True
                if others:
                    result["broken_links_left_in"] = others
        elif path:
            result["note_kept"] = path

        def remove(board: Board) -> None:
            lane, card = self._find_card(board, hit.card.title)
            board.remove_card(lane, card)

        self._edit_board(hit.board, remove)
        if remove_note and path:
            self.vault.delete(path)
            result["note_deleted"] = path
        return result

    def audit_boards(self, include_closed: bool = False, limit: int = 50) -> dict:
        boards = {p: self._load_board(p)[1] for p in self._board_paths()}
        folders = sorted({self._folder(b.settings()) for b in boards.values()} - {""})
        listing = {p.lower(): p for folder in folders for p in self.vault.list_folder(folder)}
        report: dict[str, list] = {
            "boards_missing_note_folder": [
                self._names([p])[0] for p, b in boards.items() if not self._folder(b.settings())
            ],
            "orphan_notes": [],
            "broken_links": [],
            "duplicate_cards": [],
            "checkbox_mismatch": [],
            "started_but_in_todo": [],
            "template_problems": [],
        }
        seen: dict[str, list[str]] = {}
        linked: dict[str, tuple[Hit, str]] = {}
        for path, parsed in boards.items():
            settings = parsed.settings()
            board_name = self._names([path])[0]
            for lane in parsed.lanes:
                kind = lane_kind(lane.name)
                for card in lane.cards:
                    hit = Hit(path, lane.name, card, settings)
                    seen.setdefault(card.title.lower(), []).append(f"{board_name}/{lane.name}")
                    if kind == "done" and not card.checked:
                        report["checkbox_mismatch"].append(
                            f"{card.title}: unchecked in {lane.name}"
                        )
                    if kind not in ("done", "closed") and card.checked:
                        report["checkbox_mismatch"].append(f"{card.title}: checked in {lane.name}")
                    if not card.link:
                        continue
                    folder = self._folder(settings)
                    resolved = None
                    for candidate in (f"{folder}/{card.link}.md", f"{card.link}.md"):
                        resolved = listing.get(candidate.lower())
                        if resolved:
                            break
                    if not resolved:
                        found = self.vault.find_by_name(card.link)
                        resolved = found[0] if found else None
                    if not resolved:
                        report["broken_links"].append(
                            f"{card.title}: no note for [[{card.link}]] ({board_name}/{lane.name})"
                        )
                        continue
                    linked[resolved.lower()] = (hit, resolved)
        for name, places in seen.items():
            if len(places) > 1:
                report["duplicate_cards"].append(f"{name}: {places}")
        with ThreadPoolExecutor(_WORKERS) as pool:
            texts = list(pool.map(lambda item: self._read_note(item[1]), linked.values()))
        for (hit, _path), text in zip(linked.values(), texts, strict=True):
            if text is None:
                continue
            title = hit.card.title
            found = notes.problems(text)
            if found and (include_closed or hit.kind not in ("done", "closed")):
                report["template_problems"].append(f"{title}: {'; '.join(found)}")
            if hit.kind == "todo" and notes.progress(text)[0] > 0:
                report["started_but_in_todo"].append(title)
        for lowered, path in listing.items():
            if lowered not in linked:
                report["orphan_notes"].append(path)
        result: dict[str, Any] = {"clean": not any(report.values())}
        for key, items in report.items():
            if items:
                result[key] = items[:limit]
                if len(items) > limit:
                    result[f"{key}_truncated"] = f"{len(items) - limit} more not shown"
        return result
