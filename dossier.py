"""The dossier: the sessions in scope as sequences of the researcher's prompts, with the commits they led to.

Claude reads the dossier to identify intentions. `index.json` next to it lets the renderer compute periods,
active time and mode from the turns an intention names, so no number in the work log is estimated.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import accumulate, groupby
from operator import attrgetter, itemgetter
from pathlib import Path

from claude_code import Tombstones, project_dir
from history import Commit, Link, Repository
from render import model_name
from session import Session, Turn

PROMPT_LIMIT = 600
PART_LIMIT = 120_000
ONE_DAY = timedelta(days=1)


@dataclass(frozen=True)
class Scope:
    name: str
    repositories: tuple[Repository, ...]
    since: datetime | None


@dataclass(frozen=True)
class Selection:
    sessions: tuple[Session, ...]
    linked: frozenset[str]
    commits: tuple[Commit, ...]
    links: tuple[Link, ...]
    tombstones: tuple[Tombstones, ...]


def select(scope: Scope, sessions: Sequence[Session], commits: Sequence[Commit], links: Sequence[Link],
           tombstones: Sequence[Tombstones]) -> Selection:
    """Sessions with a commit in scope, plus sessions without one that ran where the scope's code lives."""
    linked = frozenset(link.session for link in links)
    roots = code_locations(scope, [s for s in sessions if s.id in linked])
    slugs = {slug for repository in scope.repositories for slug in repository.slugs}
    context = [
        s for s in sessions
        if s.id not in linked and not s.headless
        and (inside(s.cwd, roots) or slugs & set(s.repos))
        and (scope.since is None or s.end >= scope.since)
    ]
    chosen = sorted([*(s for s in sessions if s.id in linked), *context], key=attrgetter("start"))
    directories = {project_dir(str(root)) for root in roots}
    worktrees = tuple(f"{project_dir(str(r.path))}--claude-worktrees-" for r in scope.repositories)
    return Selection(
        tuple(chosen), linked, tuple(commits), tuple(links),
        tuple(t for t in tombstones if t.project_dir in directories or t.project_dir.startswith(worktrees)),
    )


def code_locations(scope: Scope, linked: Sequence[Session]) -> frozenset[Path]:
    """The repositories, and the directories linked sessions ran in that no longer exist: former names of them.

    Other existing directories belong to other projects, even when a session there committed into the scope.
    """
    gone = {Path(s.cwd) for s in linked if s.cwd and not Path(s.cwd).exists()}
    return frozenset({repository.path for repository in scope.repositories} | gone)


def inside(cwd: str, roots: frozenset[Path]) -> bool:
    return bool(cwd) and any(Path(cwd) == root or root in Path(cwd).parents for root in roots)


def write(directory: Path, scope: Scope, selection: Selection, notes: Sequence[str]) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob("part-*.md"):
        stale.unlink()
    labels = {s.id: f"S{number}" for number, s in enumerate(selection.sessions, 1)}
    by_turn = {key: list(group) for key, group in groupby(
        sorted(selection.links, key=attrgetter("session", "turn")), key=attrgetter("session", "turn"))}
    blocks = [session_block(s, labels[s.id], s.id in selection.linked, by_turn) for s in selection.sessions]
    parts = packed(blocks, PART_LIMIT)
    paths = [directory / f"part-{number:02}.md" for number in range(1, len(parts) + 1)]
    for path, part in zip(paths, parts):
        path.write_text("\n".join(part), encoding="utf-8")
    overview_path = directory / "overview.md"
    overview_path.write_text(overview(scope, selection, notes, paths, parts), encoding="utf-8")
    (directory / "index.json").write_text(
        json.dumps(index(scope, selection, labels), ensure_ascii=False, indent=1), encoding="utf-8")
    return [overview_path, *paths]


def packed(blocks: Sequence[str], limit: int) -> list[list[str]]:
    """Consecutive blocks grouped into parts of roughly `limit` characters, keeping the chronological order."""
    offsets = accumulate((len(block) for block in blocks[:-1]), initial=0)
    numbered = zip((offset // limit for offset in offsets), blocks)
    return [[block for _, block in group] for _, group in groupby(numbered, key=itemgetter(0))]


def session_block(s: Session, label: str, linked: bool, by_turn: dict) -> str:
    models = sorted({model_name(model) for turn in s.turns for model in turn.models})
    heading = " · ".join(filter(None, [
        f"## {label}", s.source, tilde(s.cwd) or ", ".join(s.repos), f"{stamp(s.start)} – {stamp(s.end)}",
    ]))
    details = " · ".join(filter(None, [
        f"title: {s.title}" if s.title else "", f"models: {', '.join(models)}" if models else "",
        "headless" if s.headless else "", "" if linked else "no commit in scope",
    ]))
    turns = [turn_block(turn, f"{label}.{number}", by_turn.get((s.id, number - 1), []))
             for number, turn in enumerate(s.turns, 1)]
    return "\n".join([heading, details, "", *turns, ""])


def turn_block(turn: Turn, label: str, links: Sequence[Link]) -> str:
    facts = f"{turn.active_seconds // 60} min, {turn.tool_calls} tools ({turn.edits} edits), {turn.output_tokens // 1000}k tokens"
    lines = [f"**{label}** {stamp(turn.start)} · {facts}", f"> {shortened(turn.prompt) or '(no prompt)'}"]
    commits = [f"- commit {l.commit.short} · {l.commit.repo} · {stamp(l.commit.authored)} · {l.commit.subject} ({l.evidence})"
               for l in sorted(links, key=lambda l: l.commit.authored)]
    return "\n".join([*lines, *commits, ""])


def overview(scope: Scope, selection: Selection, notes: Sequence[str], paths: Sequence[Path],
             parts: Sequence[Sequence[str]]) -> str:
    linked_hashes = {link.commit.hash for link in selection.links}
    unlinked = sorted((c for c in selection.commits if c.hash not in linked_hashes), key=attrgetter("authored"))
    orphaned = [c for c in unlinked if any(t.first.date() <= c.authored.date() <= t.last.date() + ONE_DAY
                                           for t in selection.tombstones)]
    evidence = {kind: sum(1 for l in selection.links if l.evidence == kind) for kind in ("subject", "merged", "files")}
    part_lines = [f"- {path.name}: {len(part)} sessions, {sum(map(len, part)) // 1000}k characters"
                  for path, part in zip(paths, parts)]
    return "\n".join([
        f"# Work-log dossier: {scope.name}",
        "",
        *(f"- repository {r.name}: {tilde(str(r.path))}" for r in scope.repositories),
        f"- since: {scope.since.date() if scope.since else 'beginning'}",
        f"- sessions: {len(selection.sessions)} ({len(selection.linked)} with commits in scope)",
        f"- commits: {len(selection.commits)}, linked to a turn: {len(linked_hashes)} "
        f"(by subject {evidence['subject']}, via merge {evidence['merged']}, by edited files {evidence['files']})",
        *(f"- note: {note}" for note in notes),
        "",
        "## Parts",
        *part_lines,
        "",
        "## Deleted transcripts",
        *(f"- {t.count} sessions in {t.project_dir}, created {t.first.date()} – {t.last.date()}"
          for t in selection.tombstones),
        "",
        "## Commits without a session, made while transcripts were later deleted",
        *(f"- {stamp(c.authored)} {c.short} {c.repo}: {c.subject}" for c in orphaned),
        "",
        f"{len(unlinked) - len(orphaned)} further commits have no session and fall outside those periods.",
        "",
    ])


def index(scope: Scope, selection: Selection, labels: dict[str, str]) -> dict:
    return {
        "scope": {"name": scope.name, "repositories": [r.name for r in scope.repositories]},
        "sessions": {labels[s.id]: {"id": s.id, "source": s.source, "turns": [turn_facts(t) for t in s.turns]}
                     for s in selection.sessions},
        "commits": {c.hash: {"repo": c.repo, "authored": c.authored.isoformat(), "subject": c.subject}
                    for c in selection.commits},
        "links": [{"commit": l.commit.hash, "turn": f"{labels[l.session]}.{l.turn + 1}", "evidence": l.evidence}
                  for l in selection.links if l.session in labels],
        "tombstones": [{"project_dir": t.project_dir, "count": t.count, "first": t.first.isoformat(),
                        "last": t.last.isoformat()} for t in selection.tombstones],
    }


def turn_facts(turn: Turn) -> dict:
    return {
        "start": turn.start.isoformat(), "end": turn.end.isoformat(), "active_seconds": turn.active_seconds,
        "output_tokens": turn.output_tokens, "models": list(turn.models), "tool_calls": turn.tool_calls,
        "edits": turn.edits, "prompted": bool(turn.prompt),
    }


def shortened(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= PROMPT_LIMIT else f"{flat[:PROMPT_LIMIT]}… [+{len(flat) - PROMPT_LIMIT} characters]"


def stamp(moment: datetime) -> str:
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def tilde(path: str) -> str:
    home = str(Path.home())
    return f"~{path[len(home):]}" if path.startswith(home) else path
