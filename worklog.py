#!/usr/bin/env python3
"""Document LLM-assisted coding as the intentions of the researcher that led to commits.

  worklog.py dossier [--repo PATH]... [--all] [--name NAME] [--since YYYY-MM-DD] [--no-cloud] [--out DIR]
  worklog.py render DIR --output FILE.tex [--standalone]
"""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime
from operator import attrgetter
from pathlib import Path

import claude_code
import dossier
import history
import render
from harvest import CACHE, harvest
from history import Repository
from session import Session


def main() -> int:
    arguments = parser().parse_args()
    return arguments.run(arguments)


def parser() -> argparse.ArgumentParser:
    commands = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subcommands = commands.add_subparsers(required=True)

    collect = subcommands.add_parser("dossier", help="collect sessions and commits into a dossier to read")
    collect.add_argument("--repo", action="append", type=Path, default=[], help="repository in scope (repeatable)")
    collect.add_argument("--all", action="store_true", help="every repository a session ran in")
    collect.add_argument("--name", help="project name for the heading")
    collect.add_argument("--since", type=since, help="leave out commits before this date")
    collect.add_argument("--no-cloud", action="store_true", help="skip cloud sessions")
    collect.add_argument("--out", type=Path, help="directory for the dossier")
    collect.set_defaults(run=run_dossier)

    table = subcommands.add_parser("render", help="render DIR/intentions.json as a LaTeX table")
    table.add_argument("directory", type=Path)
    table.add_argument("--output", type=Path, required=True)
    table.add_argument("--standalone", action="store_true", help="a complete document instead of an \\input fragment")
    table.set_defaults(run=run_render)
    return commands


def since(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone()


def run_dossier(arguments: argparse.Namespace) -> int:
    found = harvest(include_cloud=not arguments.no_cloud)
    repositories = discovered(found.sessions) if arguments.all else in_scope(arguments.repo or [Path.cwd()])
    name = arguments.name or ("alle Repositorien" if arguments.all else ", ".join(r.name for r in repositories))
    commits = history.distinct(
        c for r in repositories for c in history.commits(r) if not arguments.since or c.authored >= arguments.since
    )
    links = history.link(found.sessions, commits)
    scope = dossier.Scope(name, tuple(repositories), arguments.since)
    selection = dossier.select(scope, found.sessions, commits, links, claude_code.tombstones())
    directory = arguments.out or CACHE / "runs" / re.sub(r"[^\w.-]+", "-", name)
    written = dossier.write(directory, scope, selection, found.notes)
    print(f"{len(selection.sessions)} sessions, {len(commits)} commits, {len({l.commit.hash for l in links})} linked")
    print(*written, sep="\n")
    return 0


def in_scope(paths: Sequence[Path]) -> list[Repository]:
    return list({r.path: r for r in map(Repository.containing, paths)}.values())


def discovered(sessions: Sequence[Session]) -> list[Repository]:
    places = sorted({Path(s.cwd) for s in sessions if s.cwd and not s.headless})
    found = {r.path: r for r in map(repository_or_none, filter(Path.is_dir, places)) if r}
    return sorted(found.values(), key=attrgetter("name"))


def repository_or_none(path: Path) -> Repository | None:
    try:
        return Repository.containing(path)
    except subprocess.CalledProcessError:
        return None


def run_render(arguments: argparse.Namespace) -> int:
    index = json.loads((arguments.directory / "index.json").read_text(encoding="utf-8"))
    intentions = render.load_intentions(arguments.directory / "intentions.json")
    try:
        rows, warnings = render.rows(index, intentions)
    except render.InvalidIntentions as invalid:
        print("intentions.json needs fixing:", *invalid.problems, sep="\n  ", file=sys.stderr)
        return 1
    name = index["scope"]["name"]
    fragment = render.table(rows, name, sum(t["count"] for t in index["tombstones"]))
    arguments.output.write_text(render.standalone(fragment, name) if arguments.standalone else fragment, encoding="utf-8")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"{len(rows)} intentions written to {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
