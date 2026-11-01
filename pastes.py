"""Pasted passages in prompts, recovered from Claude Code's prompt history.

Transcripts store a prompt with its pastes expanded. ~/.claude/history.jsonl keeps it as displayed, with a
placeholder for every paste of several lines; shorter pastes leave no trace and count as typed.
"""

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import chain, pairwise
from operator import attrgetter
from pathlib import Path

from jsonl import records

HISTORY = Path.home() / ".claude" / "history.jsonl"
PLACEHOLDER = re.compile(r"\[Pasted text #\d+(?: \+\d+ lines)?\]")
WINDOW = timedelta(minutes=2)


@dataclass(frozen=True)
class Segment:
    text: str
    pasted: bool


@dataclass(frozen=True)
class Displayed:
    """A prompt with pastes as it appeared in the input box, as a pattern whose groups are the pastes."""

    at: datetime
    pattern: re.Pattern


@dataclass(frozen=True)
class Pastes:
    displayed: tuple[Displayed, ...]

    def segments(self, prompt: str, at: datetime) -> tuple[Segment, ...]:
        moments = [d.at for d in self.displayed]
        nearby = self.displayed[bisect_left(moments, at - WINDOW):bisect_right(moments, at + WINDOW)]
        match = next(filter(None, (d.pattern.fullmatch(prompt) for d in nearby)), None)
        return split(prompt, match) if match else (Segment(prompt, False),)


def load() -> Pastes:
    if not HISTORY.exists():
        return Pastes(())
    found = (
        Displayed(moment(record["timestamp"]), pattern(record["display"]))
        for record in records(HISTORY)
        if isinstance(record.get("display"), str) and PLACEHOLDER.search(record["display"])
        and isinstance(record.get("timestamp"), (int, float))
    )
    return Pastes(tuple(sorted(found, key=attrgetter("at"))))


def moment(milliseconds: float) -> datetime:
    return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)


def pattern(display: str) -> re.Pattern:
    return re.compile("(.+?)".join(map(loose, PLACEHOLDER.split(display.strip()))), re.S)


def loose(typed: str) -> str:
    """The typed words, matched across any change in whitespace the transcript made."""
    return r"\s*" + r"\s+".join(map(re.escape, typed.split())) + r"\s*"


def split(prompt: str, match: re.Match) -> tuple[Segment, ...]:
    bounds = [0, *chain.from_iterable(match.span(group) for group in range(1, match.re.groups + 1)), len(prompt)]
    pieces = (Segment(prompt[start:end].strip(), number % 2 == 1) for number, (start, end) in enumerate(pairwise(bounds)))
    return tuple(piece for piece in pieces if piece.text)
