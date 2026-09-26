"""A coding session reduced to what the work log needs: the researcher's prompts and when work happened."""

import json
from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(frozen=True)
class CommitCall:
    """A `git commit` the assistant ran. `subject` is None when the message came from an editor or a file."""

    at: datetime
    subject: str | None


@dataclass(frozen=True)
class Turn:
    """One prompt of the researcher and everything that happened until the next one."""

    start: datetime
    end: datetime
    prompt: str
    active_seconds: int
    output_tokens: int
    models: tuple[str, ...]
    tool_calls: int
    edits: int
    files: tuple[str, ...]
    commit_calls: tuple[CommitCall, ...]


@dataclass(frozen=True)
class Session:
    source: str
    id: str
    title: str
    cwd: str
    headless: bool
    repos: tuple[str, ...]
    turns: tuple[Turn, ...]

    @property
    def start(self) -> datetime:
        return self.turns[0].start

    @property
    def end(self) -> datetime:
        return max(turn.end for turn in self.turns)


def dumps(session: Session) -> str:
    return json.dumps(asdict(session), default=datetime.isoformat, ensure_ascii=False)


def loads(text: str) -> Session:
    data = json.loads(text)
    return Session(**data | {"repos": tuple(data["repos"]), "turns": tuple(map(_turn, data["turns"]))})


def _turn(data: dict) -> Turn:
    return Turn(**data | {
        "start": datetime.fromisoformat(data["start"]),
        "end": datetime.fromisoformat(data["end"]),
        "models": tuple(data["models"]),
        "files": tuple(data["files"]),
        "commit_calls": tuple(
            CommitCall(datetime.fromisoformat(call["at"]), call["subject"]) for call in data["commit_calls"]
        ),
    })
