"""Claude Code transcripts in ~/.claude/projects, reduced to prompts, reply sizes and tool calls.

Tool results and reply texts are never read: the work log only needs what the researcher asked for,
how much the assistant did in response, and which commits it made.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from itertools import chain
from pathlib import Path

from jsonl import records, timestamp
from session import Session
from shell import commit_calls
from timeline import EDIT_TOOLS, Activity, Aside, Event, Prompt, Reply, ToolCall, build_turns

PROJECTS = Path.home() / ".claude" / "projects"
SHELL_TOOLS = frozenset({"Bash", "PowerShell"})
NOT_TYPED = (
    "<local-command", "<task-notification", "<system-reminder", "<bash-", "Caveat:",
    "[Request interrupted", "This session is being continued", "Base directory for this skill",
)
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
COMMAND_NAME = re.compile(r"<command-name>/?([^<]+)</command-name>")
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
SETTINGS_COMMANDS = frozenset({
    "add-dir", "agents", "clear", "compact", "config", "context", "cost", "doctor", "effort", "exit",
    "export", "fast", "help", "hooks", "ide", "login", "logout", "mcp", "memory", "model", "output-style",
    "permissions", "plugin", "plugins", "privacy-settings", "release-notes", "rename", "resume", "rewind",
    "sandbox", "status", "statusline", "tasks", "terminal-setup", "theme", "todos", "upgrade", "usage", "vim",
})


@dataclass(frozen=True)
class Title:
    text: str


@dataclass(frozen=True)
class Place:
    cwd: str
    entrypoint: str


@dataclass(frozen=True)
class Transcript:
    """A session file together with the transcripts of the subagents it started."""

    main: Path
    subagents: tuple[Path, ...]

    def signature(self) -> str:
        return "|".join(f"{stat.st_size}:{stat.st_mtime_ns}" for stat in map(Path.stat, (self.main, *self.subagents)))


@dataclass(frozen=True)
class Tombstones:
    """Sessions whose transcript Claude Code deleted, leaving only their side directory behind."""

    project_dir: str
    count: int
    first: datetime
    last: datetime


def transcripts() -> list[Transcript]:
    return [
        Transcript(path, tuple(sorted((path.parent / path.stem).glob("**/*.jsonl"))))
        for path in sorted(PROJECTS.glob("*/*.jsonl"))
    ]


def tombstones() -> list[Tombstones]:
    return [
        Tombstones(directory.name, len(births), min(births), max(births))
        for directory in sorted(PROJECTS.iterdir()) if directory.is_dir()
        if (births := [created(orphan) for orphan in orphans(directory)])
    ]


def orphans(directory: Path) -> list[Path]:
    return [
        entry for entry in directory.iterdir()
        if entry.is_dir() and SESSION_ID.fullmatch(entry.name) and not (directory / f"{entry.name}.jsonl").exists()
    ]


def created(path: Path) -> datetime:
    stat = path.stat()
    return datetime.fromtimestamp(getattr(stat, "st_birthtime", stat.st_mtime)).astimezone()


def project_dir(cwd: str) -> str:
    """The name Claude Code gives the transcript directory of a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def read(transcript: Transcript) -> Session | None:
    events = [
        *chain.from_iterable(map(main_events, records(transcript.main))),
        *chain.from_iterable(agent_events(record) for path in transcript.subagents for record in records(path)),
    ]
    turns = build_turns(event for event in events if not isinstance(event, (Title, Place)))
    if not turns:
        return None
    places = [event for event in events if isinstance(event, Place)]
    titles = [event.text for event in events if isinstance(event, Title)]
    return Session(
        source="Claude Code",
        id=transcript.main.stem,
        title=titles[-1] if titles else "",
        cwd=places[0].cwd if places else "",
        headless=any(place.entrypoint == "sdk-cli" for place in places),
        repos=(),
        turns=turns,
    )


def main_events(record: dict) -> Iterator[Event | Title | Place]:
    if record.get("type") == "ai-title" and record.get("aiTitle"):
        yield Title(record["aiTitle"])
    if record.get("cwd"):
        yield Place(record["cwd"], record.get("entrypoint") or "")
    yield from timed_events(record, typed=True)


def agent_events(record: dict) -> Iterator[Event]:
    return timed_events(record, typed=False)


def timed_events(record: dict, typed: bool) -> Iterator[Event]:
    at = timestamp(record.get("timestamp"))
    if at is None:
        return
    match record.get("type"):
        case "user" if typed and (text := typed_text(record)):
            yield Prompt(at, text)
        case "assistant":
            yield from reply_events(record.get("message") or {}, at)
        case "queue-operation" if typed and (text := absorbed_text(record)):
            yield Aside(at, text)
        case _:
            yield Activity(at)


def typed_text(record: dict) -> str | None:
    """The text of a prompt the researcher wrote, or None for tool results, notifications and injected context."""
    if record.get("isMeta") or record.get("isSidechain") or record.get("isCompactSummary"):
        return None
    if record.get("promptSource") == "system" or (record.get("origin") or {}).get("kind") == "task-notification":
        return None
    text = message_text(record.get("message") or {})
    if not text or text.startswith(NOT_TYPED):
        return None
    if text.startswith("<command-"):
        return slash_command(text)
    return text


def message_text(message: dict) -> str | None:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return None
    parts = [part for part in content if isinstance(part, dict)]
    if any(part.get("type") == "tool_result" for part in parts):
        return None
    text = "\n".join(part.get("text", "") for part in parts if part.get("type") == "text").strip()
    images = any(part.get("type") == "image" for part in parts)
    return text or ("[image]" if images else None)


def slash_command(text: str) -> str | None:
    name = COMMAND_NAME.search(text)
    if not name or name.group(1).strip() in SETTINGS_COMMANDS:
        return None
    arguments = COMMAND_ARGS.search(text)
    return f"/{name.group(1).strip()} {arguments.group(1).strip() if arguments else ''}".strip()


def absorbed_text(record: dict) -> str | None:
    """Text typed during a running turn and folded into it instead of starting a new one."""
    if record.get("operation") != "remove" or record.get("reason") != "absorbed_mid_turn":
        return None
    content = record.get("content")
    if not isinstance(content, str) or content.lstrip().startswith("<"):
        return None
    return content.strip() or None


def reply_events(message: dict, at: datetime) -> Iterator[Event]:
    model = message.get("model") or ""
    usage = message.get("usage") or {}
    yield Reply(at, message.get("id") or at.isoformat(), "" if model == "<synthetic>" else model,
                usage.get("output_tokens") or 0)
    uses = [part for part in message.get("content") or [] if isinstance(part, dict) and part.get("type") == "tool_use"]
    yield from (ToolCall(at, use.get("name", ""), edited_path(use)) for use in uses)
    yield from shell_commits(at, uses)


def edited_path(use: dict) -> str | None:
    arguments = use.get("input") or {}
    return (arguments.get("file_path") or arguments.get("notebook_path")) if use.get("name") in EDIT_TOOLS else None


def shell_commits(at: datetime, uses: Iterable[dict]) -> Iterator[Event]:
    commands = ((use.get("input") or {}).get("command") for use in uses if use.get("name") in SHELL_TOOLS)
    return chain.from_iterable(commit_calls(at, command) for command in commands if isinstance(command, str))
