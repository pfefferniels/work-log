"""Reading the JSON Lines files that Claude Code and Codex write."""

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path


def records(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8", errors="replace") as lines:
        yield from filter(None, map(parse_line, lines))


def parse_line(line: str) -> dict | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None  # a line cut short when the program was interrupted
    return record if isinstance(record, dict) else None


def timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
