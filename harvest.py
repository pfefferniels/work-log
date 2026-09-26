"""Collect the sessions of every source, reusing what earlier runs already parsed."""

import os
import sqlite3
import sys
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from operator import attrgetter
from pathlib import Path

import claude_code
import cloud
import codex
import session
from session import Session

CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "work-log"
PARSER_VERSION = "2"


@dataclass(frozen=True)
class Harvest:
    sessions: tuple[Session, ...]
    notes: tuple[str, ...]


def harvest(include_cloud: bool) -> Harvest:
    with cache() as db:
        local = claude_code_sessions(db)
        remote, notes = cloud_sessions(db) if include_cloud else ([], ["Cloud sessions left out (--no-cloud)."])
    ordered = sorted([*local, *codex.sessions(), *remote], key=attrgetter("start"))
    return Harvest(tuple(without_copies(ordered)), tuple(notes))


def without_copies(ordered: Sequence[Session]) -> list[Session]:
    """Resumed and forked sessions repeat turns of the session they came from; each turn counts once, where it began."""
    owner = {(turn.start, turn.prompt): s.id for s in reversed(ordered) for turn in s.turns}
    trimmed = (replace(s, turns=tuple(t for t in s.turns if owner[t.start, t.prompt] == s.id)) for s in ordered)
    return [s for s in trimmed if s.turns]


@contextmanager
def cache() -> Iterator[sqlite3.Connection]:
    CACHE.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(CACHE / "sessions.sqlite")) as db:
        db.execute("create table if not exists parsed (key text primary key, signature text, session text)")
        with db:
            yield db


def claude_code_sessions(db: sqlite3.Connection) -> list[Session]:
    found = {f"claude-code:{t.main}": t for t in claude_code.transcripts()}
    signatures = {key: f"{PARSER_VERSION}|{t.signature()}" for key, t in found.items()}
    known = dict(db.execute("select key, signature from parsed where key like 'claude-code:%'"))
    stale = [key for key in found if known.get(key) != signatures[key]]
    report(f"Claude Code: {len(found)} transcripts, {len(stale)} to parse")
    with ProcessPoolExecutor() as pool:
        parsed = pool.map(parse_transcript, (found[key] for key in stale), chunksize=16)
        store(db, ((key, signatures[key], text) for key, text in zip(stale, parsed)))
    return cached(db, found)


def parse_transcript(transcript: claude_code.Transcript) -> str | None:
    found = claude_code.read(transcript)
    return session.dumps(found) if found else None


def cloud_sessions(db: sqlite3.Connection) -> tuple[list[Session], list[str]]:
    known = dict(db.execute("select key, signature from parsed where key like 'cloud:%'"))
    try:
        current = refresh_cloud(db, known)
    except (cloud.CloudUnavailable, OSError) as error:
        stored = cached(db, known)
        return stored, [f"Cloud sessions could not be refreshed ({error}); {len(stored)} taken from the cache."]
    return cached(db, current), []


def refresh_cloud(db: sqlite3.Connection, known: dict[str, str]) -> dict[str, dict]:
    client = cloud.Client(cloud.keychain_token())
    summaries = {f"cloud:{summary['id']}": summary for summary in client.summaries()}
    signatures = {key: f"{PARSER_VERSION}|{summary.get('last_event_at')}" for key, summary in summaries.items()}
    stale = [key for key in summaries if known.get(key) != signatures[key]]
    report(f"Cloud: {len(summaries)} sessions, {len(stale)} to fetch")
    store(db, ((key, signatures[key], dumps_or_none(cloud.read(client, summaries[key]))) for key in stale))
    return summaries


def store(db: sqlite3.Connection, rows: Iterable[tuple[str, str, str | None]]) -> None:
    db.executemany("insert or replace into parsed values (?, ?, ?)", rows)


def cached(db: sqlite3.Connection, wanted: dict) -> list[Session]:
    """Sessions of the sources that still exist; entries of deleted transcripts stay unused in the cache."""
    rows = db.execute("select key, session from parsed where session is not null")
    return [session.loads(text) for key, text in rows if key in wanted]


def dumps_or_none(found: Session | None) -> str | None:
    return session.dumps(found) if found else None


def report(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
