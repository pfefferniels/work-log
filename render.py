"""Render the intentions as a LaTeX table; every number in it is computed from the dossier index."""

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from itertools import groupby
from operator import attrgetter, itemgetter
from pathlib import Path

EXPLORATORY_EDIT_SHARE = 0.05
AUTONOMOUS_CALLS_PER_PROMPT = 25
MODES = ("dialogisch", "autonom", "explorativ")
TURN_REFERENCE = re.compile(r"(S\d+)(?:\.(\d+)(?:-(\d+))?)?")
CLAUDE_MODEL = re.compile(r"claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?(?:\[.*\])?")
GPT_MODEL = re.compile(r"gpt-(\d+(?:\.\d+)?)(?:-.*)?")
LATEX_SPECIALS = str.maketrans({
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{",
    "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "<": r"\textless{}", ">": r"\textgreater{}",
})


@dataclass(frozen=True)
class Column:
    name: str
    width: float
    align: str
    joins_repeats: bool


COLUMNS = (
    Column("Nr.", 0.05, "raggedleft", False),
    Column("Zeitraum", 0.13, "raggedright", True),
    Column("Intention", 0.28, "raggedright", False),
    Column("Modell", 0.11, "raggedright", True),
    Column("Modus", 0.11, "raggedright", True),
    Column("Umfang", 0.10, "raggedright", False),
    Column("Commits", 0.22, "raggedright", True),
)


class InvalidIntentions(Exception):
    def __init__(self, problems: Sequence[str]):
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


@dataclass(frozen=True)
class Intention:
    text: str
    turns: tuple[str, ...]
    commits: tuple[str, ...]
    mode: str | None = None
    reconstructed: bool = False


@dataclass(frozen=True)
class Row:
    intention: str
    first: date
    last: date
    models: tuple[str, ...]
    mode: str
    active_seconds: float
    commits: tuple[tuple[str, tuple[str, ...]], ...]
    reconstructed: bool

    @property
    def period(self) -> str:
        """Each date unbreakable, with a line break allowed only after the dash of a range."""
        if self.reconstructed:
            return rf"vor dem \mbox{{{german_date(self.first)}}}"
        *opening, closing = period_parts(self.first, self.last)
        return "".join(rf"\mbox{{{part}--}}\allowbreak" for part in opening) + rf"\mbox{{{closing}}}"


def load_intentions(path: Path) -> list[Intention]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Intention(item["intention"], tuple(item.get("turns", [])), tuple(item.get("commits", [])),
                  item.get("mode"), bool(item.get("reconstructed")))
        for item in (data["intentions"] if isinstance(data, dict) else data)
    ]


def rows(index: dict, intentions: Sequence[Intention]) -> tuple[list[Row], list[str]]:
    """The table rows, and warnings about linked work that no intention accounts for."""
    if problems := [*reference_problems(intentions, index), *consistency_problems(intentions, index)]:
        raise InvalidIntentions(problems)
    resolved = [(i, expanded_turns(i, index), resolved_commits(i, index)) for i in intentions]
    shares = Counter(key for _, keys, _ in resolved for key in keys)
    return [row(i, keys, hashes, index, shares) for i, keys, hashes in resolved], warnings(index, resolved, shares)


def reference_problems(intentions: Sequence[Intention], index: dict) -> list[str]:
    return [
        *(problem for i in intentions for reference in i.turns if (problem := turn_problem(reference, index))),
        *(problem for i in intentions for prefix in i.commits if (problem := commit_problem(prefix, index))),
    ]


def consistency_problems(intentions: Sequence[Intention], index: dict) -> list[str]:
    return [
        *(f"{i.text!r} has no commit" for i in intentions if not i.commits),
        *(f"{i.text!r} names no turns" for i in intentions if not i.turns and not i.reconstructed),
        *(f"{i.text!r} is reconstructed but names turns" for i in intentions if i.turns and i.reconstructed),
        *(f"{i.text!r}: mode must be one of {', '.join(MODES)}" for i in intentions if i.mode not in (None, *MODES)),
    ]


def turn_numbers(reference: str, index: dict) -> tuple[str, range] | None:
    match = TURN_REFERENCE.fullmatch(reference.strip())
    if not match or match.group(1) not in index["sessions"]:
        return None
    session, first, last = match.groups()
    count = len(index["sessions"][session]["turns"])
    numbers = range(1, count + 1) if first is None else range(int(first), int(last or first) + 1)
    return (session, numbers) if numbers and numbers[0] >= 1 and numbers[-1] <= count else None


def turn_problem(reference: str, index: dict) -> str | None:
    return None if turn_numbers(reference, index) else f"unknown turn reference {reference!r}"


def expanded_turns(intention: Intention, index: dict) -> tuple[str, ...]:
    found = [turn_numbers(reference, index) for reference in intention.turns]
    return tuple(dict.fromkeys(f"{session}.{number}" for session, numbers in found for number in numbers))


def matching_commits(prefix: str, index: dict) -> list[str]:
    wanted = prefix.strip().lower()
    return [full for full in index["commits"] if full.startswith(wanted)] if len(wanted) >= 4 else []


def unique_commit(prefix: str, index: dict) -> str | None:
    found = matching_commits(prefix, index)
    return found[0] if len(found) == 1 else None


def commit_problem(prefix: str, index: dict) -> str | None:
    found = matching_commits(prefix, index)
    return None if len(found) == 1 else f"commit {prefix!r} is {'ambiguous' if found else 'not in scope'}"


def resolved_commits(intention: Intention, index: dict) -> tuple[str, ...]:
    return tuple(dict.fromkeys(unique_commit(prefix, index) for prefix in intention.commits))


def row(intention: Intention, keys: Sequence[str], hashes: Sequence[str], index: dict, shares: Counter) -> Row:
    facts = [(turn_facts(key, index), 1 / shares[key]) for key in keys]
    commits = [index["commits"][full] | {"hash": full} for full in hashes]
    days = [*(local_date(c["authored"]) for c in commits), *(local_date(f[k]) for f, _ in facts for k in ("start", "end"))]
    return Row(
        intention=intention.text,
        first=min(days),
        last=max(days),
        models=tuple(name for name, _ in Counter(model_name(m) for f, _ in facts for m in f["models"]).most_common()),
        mode="" if intention.reconstructed else intention.mode or mode(facts),
        active_seconds=sum(f["active_seconds"] * share for f, share in facts),
        commits=grouped(commits, several_repositories=len(index["scope"]["repositories"]) > 1),
        reconstructed=intention.reconstructed,
    )


def turn_facts(key: str, index: dict) -> dict:
    session, number = key.split(".")
    return index["sessions"][session]["turns"][int(number) - 1]


def mode(facts: Sequence[tuple[dict, float]]) -> str:
    prompts = sum(share for f, share in facts if f["prompted"]) or 1
    calls = sum(f["tool_calls"] * share for f, share in facts)
    edits = sum(f["edits"] * share for f, share in facts)
    if not calls or edits / calls < EXPLORATORY_EDIT_SHARE:
        return "explorativ"
    return "autonom" if calls / prompts >= AUTONOMOUS_CALLS_PER_PROMPT else "dialogisch"


def grouped(commits: Sequence[dict], several_repositories: bool) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Short hashes in order of authoring, per repository; the repository is named only when the scope has several."""
    ordered = sorted(commits, key=itemgetter("repo", "authored"))
    return tuple(
        (repo if several_repositories else "", tuple(c["hash"][:7] for c in group))
        for repo, group in groupby(ordered, key=itemgetter("repo"))
    )


def warnings(index: dict, resolved: Sequence, shares: Counter) -> list[str]:
    used = {full for _, _, hashes in resolved for full in hashes}
    missing = [link for link in index["links"] if link["commit"] not in used]
    shared = sorted(key for key, count in shares.items() if count > 1)
    return [
        *(f"linked commit {l['commit'][:7]} ({l['turn']}: {index['commits'][l['commit']]['subject']!r}) is in no intention"
          for l in missing),
        *([f"turns in several intentions, their time is split evenly: {', '.join(shared)}"] if shared else []),
    ]


def model_name(model_id: str) -> str:
    if claude := CLAUDE_MODEL.fullmatch(model_id):
        family, major, minor = claude.groups()
        return f"{family.capitalize()} {major}{f'.{minor}' if minor else ''}"
    if gpt := GPT_MODEL.fullmatch(model_id):
        return f"GPT-{gpt.group(1)}"
    return model_id


def local_date(moment: str) -> date:
    return datetime.fromisoformat(moment).astimezone().date()


def german_date(day: date) -> str:
    return f"{day.day}.{day.month}.{day.year}"


def period(first: date, last: date) -> str:
    return "--".join(period_parts(first, last))


def period_parts(first: date, last: date) -> tuple[str, ...]:
    if first == last:
        return (german_date(first),)
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.day}.", german_date(last)
    if first.year == last.year:
        return f"{first.day}.{first.month}.", german_date(last)
    return german_date(first), german_date(last)


def extent(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return r"$<$1\,min"
    if minutes < 60:
        return rf"$\sim${minutes}\,min"
    return rf"$\sim${minutes / 60:.1f}\,h".replace(".", ",")


def latex(text: str) -> str:
    return text.translate(LATEX_SPECIALS)


def table(all_rows: Sequence[Row], scope_name: str, tombstone_count: int) -> str:
    regular = sorted((r for r in all_rows if not r.reconstructed), key=attrgetter("active_seconds"), reverse=True)
    reconstructed = sorted((r for r in all_rows if r.reconstructed), key=attrgetter("first"))
    header = line([column.name for column in COLUMNS])
    summary = r" \textbar{} ".join(filter(None, [
        f"{len(all_rows)} Intentionen",
        period(min(r.first for r in all_rows), max(r.last for r in all_rows)) if all_rows else "",
        f"Projekt: {latex(scope_name)}",
    ]))
    return "\n".join([
        f"% Arbeitsverlauf – LLM-Coding × {scope_name}, erzeugt mit work-log",
        r"% Benötigt \usepackage{booktabs,longtable,array}",
        r"{\small\setlength{\tabcolsep}{4pt}",
        r"\begin{longtable}{@{}" + "".join(
            column_spec(column, separators=1 if number in (0, len(COLUMNS) - 1) else 2)
            for number, column in enumerate(COLUMNS)
        ) + "@{}}",
        r"\toprule", header, r"\midrule", r"\endfirsthead",
        r"\toprule", header, r"\midrule", r"\endhead",
        r"\bottomrule", r"\endlastfoot",
        *map(line, joined([cells(number, r) for number, r in enumerate(regular, 1)])),
        *(reconstructed_note(tombstone_count) if reconstructed else []),
        *map(line, joined([cells(number, r) for number, r in enumerate(reconstructed, len(regular) + 1)])),
        r"\end{longtable}",
        rf"\par\noindent{{\footnotesize {summary}\par}}",
        "}",
        "",
    ])


def reconstructed_note(tombstone_count: int) -> list[str]:
    sessions = f"{tombstone_count} Sitzungen, deren Verlauf gelöscht wurde" if tombstone_count else "Sitzungen ohne erhaltenen Verlauf"
    return [r"\midrule",
            rf"\multicolumn{{{len(COLUMNS)}}}{{@{{}}p{{\linewidth}}@{{}}}}{{\footnotesize\itshape Rekonstruiert aus "
            rf"Commits: {sessions}; Modell, Modus und Umfang unbekannt.}} \\"]


def column_spec(column: Column, separators: int) -> str:
    """A share of the line width; the outer columns lose one column separator to `@{}`, the inner ones two."""
    return rf">{{\{column.align}\arraybackslash}}p{{\dimexpr {column.width}\linewidth-{separators}\tabcolsep\relax}}"


def cells(number: int, r: Row) -> list[str]:
    return [
        str(number), r.period, latex(r.intention), r"\newline ".join(map(latex, r.models)),
        r.mode, "" if r.reconstructed else extent(r.active_seconds), commit_cell(r),
    ]


def joined(rows_cells: Sequence[list[str]]) -> list[list[str]]:
    """A cell that repeats the one above it is left empty, so that the two read as one cell."""
    return [
        ["" if column.joins_repeats and cell == above else cell for column, cell, above in zip(COLUMNS, current, previous)]
        for previous, current in zip([[None] * len(COLUMNS), *rows_cells], rows_cells)
    ]


def line(row_cells: Sequence[str]) -> str:
    return " & ".join(row_cells) + r" \\"


def commit_cell(r: Row) -> str:
    lines = [f"{latex(repo)}: {', '.join(hashes)}" if repo else ", ".join(hashes) for repo, hashes in r.commits]
    return r"{\footnotesize\ttfamily " + r"\newline ".join(lines) + "}"


def standalone(fragment: str, scope_name: str) -> str:
    return "\n".join([
        r"\documentclass[a4paper,11pt]{article}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage[margin=2.5cm]{geometry}",
        r"\usepackage{booktabs,longtable,array}",
        r"\IfFileExists{ebgaramond.sty}{\usepackage{ebgaramond}}{\usepackage{lmodern}}",
        r"\pagestyle{empty}",
        r"\begin{document}",
        rf"\section*{{Arbeitsverlauf -- LLM-Coding $\times$ {latex(scope_name)}}}",
        fragment,
        r"\end{document}",
        "",
    ])
