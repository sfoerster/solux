from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class TLDR:
    bullets: list[str]


@dataclass
class OutlineItem:
    start: str | None
    heading: str
    points: list[str]


@dataclass
class Quote:
    text: str
    speaker: str | None = None
    timestamp: str | None = None


@dataclass
class NotesSection:
    key_ideas: list[str]
    quotes: list[Quote]
    actions: list[str]


@dataclass
class FullSummary:
    tldr: TLDR
    outline: list[OutlineItem]
    notes: NotesSection

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
