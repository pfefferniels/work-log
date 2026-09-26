"""Commits of the repositories in scope, and the session turns that produced them.

Links rest on the commit itself (subject and author date), never on directory names:
projects get renamed and code moves between repositories, but a commit keeps its subject and author date
through renames, rebases and history rewrites.
"""

import re
import subprocess
from bisect import bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import groupby, takewhile
from operator import attrgetter, itemgetter
from pathlib import Path

from session import CommitCall, Session, Turn

COMMIT_DELAY = (timedelta(minutes=-5), timedelta(minutes=30))
MERGE_DELAY = timedelta(days=60)
MANUAL_COMMIT_DELAY = timedelta(hours=1)
PR_NUMBER = re.compile(r"\s*\(#\d+\)$")
LIST_MARKER = re.compile(r"^\s*[*-]\s+")
REMOTE_SLUG = re.compile(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$")


@dataclass(frozen=True)
class Repository:
    path: Path
    name: str
    slugs: tuple[str, ...]

    @classmethod
    def containing(cls, path: Path) -> "Repository":
        """The main repository of `path`, also when `path` lies in one of its worktrees."""
        common = Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
        root = common.parent if common.name == ".git" else common
        remotes = git(root, "remote", "-v").split()
        return cls(root, root.name, tuple(sorted({m.group(1) for m in map(REMOTE_SLUG.search, remotes) if m})))


@dataclass(frozen=True)
class Commit:
    repo: str
    hash: str
    authored: datetime
    subject: str
    body: str
    files: tuple[str, ...]
    on_head: bool

    @property
    def short(self) -> str:
        return self.hash[:7]


@dataclass(frozen=True)
class Link:
    commit: Commit
    session: str
    turn: int
    evidence: str


def git(path: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(path), *arguments], capture_output=True, text=True, check=True).stdout


def commits(repository: Repository) -> list[Commit]:
    head = frozenset(git(repository.path, "rev-list", "HEAD").split())
    log = git(repository.path, "log", "--branches", "--remotes", "--tags", "--name-only",
              "--format=%x1e%H%x1f%aI%x1f%s%x1f%b%x1f")
    return distinct(parse_commit(repository.name, record, head) for record in log.split("\x1e") if record.strip())


def parse_commit(repo: str, record: str, head: frozenset[str]) -> Commit:
    hash, authored, subject, body, files = record.split("\x1f", 4)
    return Commit(repo, hash, datetime.fromisoformat(authored), subject, body.strip(),
                  tuple(filter(None, files.splitlines())), hash in head)


def distinct(found: Iterable[Commit]) -> list[Commit]:
    """One commit per subject and author date: rebased or cherry-picked copies count once, preferably from HEAD."""
    identity = attrgetter("subject", "authored")
    return [min(copies, key=lambda c: not c.on_head) for _, copies in groupby(sorted(found, key=identity), key=identity)]


def link(sessions: Sequence[Session], scope: Sequence[Commit]) -> list[Link]:
    by_subject = index(scope, lambda c: [normalized(c.subject)])
    by_body_line = index(scope, lambda c: [normalized(LIST_MARKER.sub("", line)) for line in c.body.splitlines()])
    calls = [(s.id, i, call) for s in sessions for i, t in enumerate(s.turns) for call in t.commit_calls if call.subject]
    candidates = [
        (commit, Link(commit, session, turn, evidence), abs(commit.authored - call.at))
        for session, turn, call in calls
        for commit, evidence in matches(call, by_subject, by_body_line)
    ]
    by_commit = groupby(sorted(candidates, key=lambda c: (c[0].hash, c[1].evidence != "subject", c[2])),
                        key=lambda c: c[0].hash)
    claimed = [next(group)[1] for _, group in by_commit]
    linked = {found.commit.hash for found in claimed}
    return [*claimed, *manual_links([c for c in scope if c.hash not in linked], sessions)]


def matches(call: CommitCall, by_subject: dict, by_body_line: dict) -> list[tuple[Commit, str]]:
    """The commit a `git commit` call made, or the merge that later carried it into the history."""
    subject = normalized(call.subject)
    direct = [c for c in by_subject.get(subject, []) if COMMIT_DELAY[0] <= c.authored - call.at <= COMMIT_DELAY[1]]
    if direct:
        return [(min(direct, key=lambda c: abs(c.authored - call.at)), "subject")]
    merged = [c for c in [*by_subject.get(subject, []), *by_body_line.get(subject, [])]
              if timedelta() <= c.authored - call.at <= MERGE_DELAY]
    return [(min(merged, key=attrgetter("authored")), "merged")] if merged else []


def manual_links(unlinked: Sequence[Commit], sessions: Sequence[Session]) -> list[Link]:
    """Commits made by hand after a turn edited the same files."""
    editing = sorted(((t, s.id, i) for s in sessions for i, t in enumerate(s.turns) if t.files), key=lambda e: e[0].start)
    starts = [turn.start for turn, _, _ in editing]
    return [
        Link(commit, session, turn_index, "files")
        for commit in unlinked
        if (found := last_editing_turn(commit, editing, bisect_right(starts, commit.authored)))
        for _, session, turn_index in [found]
    ]


def last_editing_turn(commit: Commit, editing: Sequence[tuple[Turn, str, int]], before: int) -> tuple[Turn, str, int] | None:
    earlier = (editing[i] for i in range(before - 1, -1, -1))
    recent = takewhile(lambda e: e[0].start >= commit.authored - timedelta(days=1), earlier)
    return next((e for e in recent if commit.authored <= e[0].end + MANUAL_COMMIT_DELAY and touches(e[0], commit)), None)


def touches(turn: Turn, commit: Commit) -> bool:
    """Edited paths are absolute or relative to wherever the session ran; commit paths are relative to the root."""
    return any(f"/{path.lstrip('/')}".endswith(f"/{file}") for path in turn.files for file in commit.files)


def normalized(subject: str) -> str:
    return " ".join(PR_NUMBER.sub("", subject).split())


def index(found: Iterable[Commit], keys: Callable[[Commit], list[str]]) -> dict[str, list[Commit]]:
    pairs = sorted(((key, commit) for commit in found for key in filter(None, keys(commit))), key=itemgetter(0))
    return {key: [commit for _, commit in group] for key, group in groupby(pairs, key=itemgetter(0))}
