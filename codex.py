"""Codex CLI sessions: the thread index in ~/.codex/state_5.sqlite plus one rollout file per thread."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from itertools import chain
from pathlib import Path

from jsonl import records, timestamp
from session import Session
from shell import commit_calls, patched_files
from timeline import Activity, Event, Prompt, Reply, ToolCall, build_turns

CODEX = Path.home() / ".codex"
SHELL_CALLS = frozenset({"exec_command", "shell", "shell_command", "local_shell_call"})


@dataclass(frozen=True)
class Thread:
    id: str
    rollout: Path
    cwd: str
    title: str
    model: str
    parent: str | None


def sessions() -> list[Session]:
    found = threads()
    return [
        session
        for thread in found if thread.parent is None
        if (session := read(thread, [child for child in found if child.parent == thread.id]))
    ]


def threads() -> list[Thread]:
    database = CODEX / "state_5.sqlite"
    if not database.exists():
        return []
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as db:
        rows = db.execute("select id, rollout_path, cwd, title, model, source from threads").fetchall()
    return [
        Thread(id, rollout_path(path), cwd or "", title or "", model or "", parent_thread(source))
        for id, path, cwd, title, model, source in rows
    ]


def rollout_path(path: str) -> Path:
    return Path(path) if Path(path).is_absolute() else CODEX / path


def parent_thread(source: str | None) -> str | None:
    """Subagent threads name their parent in a JSON `source`; top-level threads have a plain one like `cli`."""
    try:
        spawn = json.loads(source or "")["subagent"]["thread_spawn"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    return spawn.get("parent_thread_id")


def read(thread: Thread, children: list[Thread]) -> Session | None:
    if not thread.rollout.exists():
        return None
    existing = [child for child in children if child.rollout.exists()]
    events = [
        *chain.from_iterable(rollout_events(record, thread.model, typed=True) for record in records(thread.rollout)),
        *chain.from_iterable(
            rollout_events(record, child.model or thread.model, typed=False)
            for child in existing for record in records(child.rollout)
        ),
    ]
    turns = build_turns(events)
    return Session("Codex", thread.id, thread.title, thread.cwd, False, (), turns) if turns else None


def rollout_events(record: dict, model: str, typed: bool) -> Iterator[Event]:
    at = timestamp(record.get("timestamp"))
    if at is None:
        return
    payload = record.get("payload") or {}
    match record.get("type"), payload.get("type"):
        case "event_msg", "user_message" if typed and (text := str(payload.get("message") or "").strip()):
            yield Prompt(at, text)
        case "event_msg", "token_count":
            usage = (payload.get("info") or {}).get("last_token_usage") or {}
            yield Reply(at, f"codex:{at.isoformat()}", model, usage.get("output_tokens") or 0)
        case "response_item", "function_call" | "custom_tool_call" | "local_shell_call":
            yield from tool_events(at, payload)
        case _:
            yield Activity(at)


def tool_events(at: datetime, payload: dict) -> Iterator[Event]:
    name = payload.get("name") or payload.get("type") or ""
    text = call_text(payload)
    if name == "apply_patch" or "*** Begin Patch" in text:
        yield from (ToolCall(at, "apply_patch", path) for path in patched_files(text))
    else:
        yield ToolCall(at, name)
    if name in SHELL_CALLS or payload.get("type") == "local_shell_call":
        yield from commit_calls(at, text)


def call_text(payload: dict) -> str:
    """The command or patch of a tool call, whichever of Codex's argument shapes it came in."""
    if isinstance(payload.get("input"), str):
        return payload["input"]
    arguments = payload.get("arguments") or payload.get("action") or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
    if not isinstance(arguments, dict):
        return ""
    command = arguments.get("cmd") or arguments.get("command") or ""
    return " ".join(map(str, command)) if isinstance(command, list) else str(command)
