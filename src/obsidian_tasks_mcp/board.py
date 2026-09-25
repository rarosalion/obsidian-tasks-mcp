"""Lossless parsing and editing of Obsidian Kanban plugin boards.

A board is a markdown file whose `## Heading` lines are lanes and whose top-level checklist
items are cards. Every line of the file is kept as-is, so an edit only changes the lines it
touches: other lanes, non-card lines and the trailing settings block survive byte for byte.
"""

import json
import re
from dataclasses import dataclass, field

from . import frontmatter

_LANE = re.compile(r"^## (.+?)\s*$")
_CARD = re.compile(r"^- \[([ xX])\] ?(.*)$")
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
_MARKERS = ("%%", "***", "---", "```")
_SETTINGS = re.compile(r"^%% kanban:settings\s*\n```\n(.*?)\n```\n%%", re.DOTALL | re.MULTILINE)


@dataclass
class Card:
    checked: bool
    text: str
    extra: list[str] = field(default_factory=list)
    raw: str | None = None

    def set_checked(self, checked: bool) -> None:
        self.checked = checked
        self.raw = None

    @property
    def link(self) -> str | None:
        match = _WIKILINK.search(self.text)
        return match.group(1).strip() if match else None

    @property
    def title(self) -> str:
        return self.link or self.text.strip()

    def lines(self) -> list[str]:
        if self.raw is not None:
            return [self.raw, *self.extra]
        mark = "x" if self.checked else " "
        return [f"- [{mark}] {self.text}".rstrip(), *self.extra]


@dataclass
class Lane:
    name: str
    items: list[str | Card]

    @property
    def cards(self) -> list[Card]:
        return [item for item in self.items if isinstance(item, Card)]


@dataclass
class Board:
    front: str
    preamble: list[str]
    lanes: list[Lane]
    ends_with_newline: bool

    @classmethod
    def parse(cls, text: str) -> "Board":
        front, body = frontmatter.split(text)
        lines = body.split("\n")
        ends_with_newline = body.endswith("\n")
        if ends_with_newline:
            lines.pop()
        preamble: list[str] = []
        lanes: list[Lane] = []
        current: list[str | Card] | None = None
        for line in lines:
            match = _LANE.match(line)
            if match:
                lanes.append(Lane(match.group(1), [line]))
                current = lanes[-1].items
            elif current is None:
                preamble.append(line)
            else:
                _add_line(current, line)
        return cls(front, preamble, lanes, ends_with_newline)

    def render(self) -> str:
        lines = list(self.preamble)
        for lane in self.lanes:
            for item in lane.items:
                lines.extend(item.lines() if isinstance(item, Card) else [item])
        text = self.front + "\n".join(lines)
        return text + "\n" if self.ends_with_newline else text

    def lane(self, name: str) -> Lane | None:
        wanted = name.strip().lower()
        for lane in self.lanes:
            if lane.name.lower() == wanted:
                return lane
        return None

    def find(self, title: str) -> list[tuple[Lane, Card]]:
        wanted = title.strip().lower()
        return [
            (lane, card)
            for lane in self.lanes
            for card in lane.cards
            if card.title.lower() == wanted
        ]

    def add_card(self, lane: Lane, card: Card, *, bottom: bool = False) -> None:
        cards = [i for i, item in enumerate(lane.items) if isinstance(item, Card)]
        if cards:
            index = cards[-1] + 1 if bottom else cards[0]
        else:
            if len(lane.items) < 2 or lane.items[1] != "":
                lane.items.insert(1, "")
            index = 2
            while index < len(lane.items) and _is_label(lane.items[index]):
                index += 1
        lane.items.insert(index, card)
        if not cards:
            wanted = 2 if lane is not self.lanes[-1] else 1
            after = index + 1
            trailing = 0
            while after + trailing < len(lane.items) and lane.items[after + trailing] == "":
                trailing += 1
            if after + trailing < len(lane.items) or lane is not self.lanes[-1]:
                lane.items[after:after] = [""] * max(0, wanted - trailing)

    def remove_card(self, lane: Lane, card: Card) -> None:
        for index, item in enumerate(lane.items):
            if item is card:
                del lane.items[index]
                return
        raise ValueError("card is not in the lane")

    def settings(self) -> dict:
        match = _SETTINGS.search(self.render())
        if not match:
            return {}
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}


def _is_label(item: "str | Card") -> bool:
    return isinstance(item, str) and bool(item.strip()) and not item.startswith(_MARKERS)


def _add_line(items: list, line: str) -> None:
    match = _CARD.match(line)
    if match:
        items.append(Card(match.group(1).lower() == "x", match.group(2), raw=line))
        return
    if line[:1] in (" ", "\t") and line.strip() and items and isinstance(items[-1], Card):
        items[-1].extra.append(line)
        return
    items.append(line)
