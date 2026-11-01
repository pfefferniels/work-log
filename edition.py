"""The edition: every prompt in scope, in full and lightly emended, as one Markdown file per day.

Replies are left out; the figures of each turn stand in for them. Pasted passages are shown collapsed and never
emended. The readings an emendation replaced are kept only in emendations.json.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import groupby
from operator import attrgetter
from pathlib import Path

from dossier import Selection, Scope, figures, tilde
from emendation import Entry, digest, emended
from history import Link
from pastes import Pastes, Segment
from render import model_name
from session import Session, Turn

README = """\
# Prompts

The prompts given to coding agents (Claude Code, Codex) in the course of the work, one file per day and \
project. The agents' replies are left out. For each prompt, the active time (pauses of five minutes or more \
excluded), the number of tool calls and file edits, and the output tokens of the reply (thinking included, and \
given separately where the transcript records it) indicate how much work followed.

## Editorial principles

- Prompts are given as a clean reading text. Many were dictated or typed in haste. A small language model \
corrected misspellings, dictation errors, missing or doubled words, faulty grammar and punctuation, and wrote out \
colloquial contractions ("wanna" as "want to"). A script admits only small, local corrections of words that occur \
in the prompt, so that no correction rewords a passage. Every corrected or added word and punctuation mark stands \
in square brackets; where a mark was removed, the word it stood on is bracketed.
- Interjections, fillers, exclamations of frustration and emoticons ("hm", "oh damn it", ":D") are omitted and \
marked with [...]. The script admits an omission only when every omitted word is such an exclamation.
- Capitalization, established abbreviations and the mix of languages are left as typed.
- `emendations.json` lists every correction and omission as a pair of the words as typed and their correction, \
with the model that proposed it. The original reading of a bracketed passage, and the place of an omission, can \
be found there.
- Pasted passages are shown collapsed and left uncorrected. Only pastes of several lines can be recognized; \
shorter ones are treated as typed.
- Square brackets that were part of a prompt as typed cannot be told apart from editorial ones; \
`emendations.json` settles such cases.
- Access tokens and keys are replaced by `[credential withheld]`.
"""

CREDENTIAL = re.compile(
    r"\b(?:npm_[A-Za-z0-9]{36}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_\w{22,}|sk-[A-Za-z0-9_-]{20,}"
    r"|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]{10,})\b"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.S,
)


@dataclass(frozen=True)
class Placed:
    """A turn as it appears in the edition."""

    session: Session
    number: int
    turn: Turn
    segments: tuple[Segment, ...]

    @property
    def day(self) -> date:
        return self.turn.start.astimezone().date()


def placed(selection: Selection, pastes: Pastes) -> list[Placed]:
    found = (
        Placed(s, number, turn, pastes.segments(turn.prompt, turn.start) if turn.prompt else ())
        for s in selection.sessions for number, turn in enumerate(s.turns)
    )
    return sorted(found, key=lambda p: p.turn.start)


def typed_texts(turns: Sequence[Placed]) -> list[str]:
    return [segment.text for p in turns for segment in p.segments if not segment.pasted]


def write(directory: Path, scope: Scope, selection: Selection, turns: Sequence[Placed],
          entries: dict[str, Entry]) -> list[Path]:
    folder = directory / re.sub(r"[^\w.-]+", "-", scope.name)
    folder.mkdir(parents=True, exist_ok=True)
    readme = directory / "README.md"
    if not readme.exists():
        readme.write_text(README, encoding="utf-8")
    links = {key: list(group) for key, group in groupby(
        sorted(selection.links, key=attrgetter("session", "turn")), key=attrgetter("session", "turn"))}
    days = [(day, list(group)) for day, group in groupby(turns, key=attrgetter("day"))]
    paths = [folder / f"{day.isoformat()}.md" for day, _ in days]
    for path, (day, day_turns) in zip(paths, days):
        path.write_text(day_file(day, scope, day_turns, selection.linked, links, entries), encoding="utf-8")
    return paths


def day_file(day: date, scope: Scope, turns: Sequence[Placed], linked: frozenset[str], links: dict,
             entries: dict[str, Entry]) -> str:
    """Sessions in the order of their first turn that day, each with its turns of that day."""
    first = {p.session.id: p.turn.start for p in reversed(turns)}
    ordered = sorted(turns, key=lambda p: (first[p.session.id], p.turn.start))
    sessions = [list(group) for _, group in groupby(ordered, key=lambda p: p.session.id)]
    return "\n\n".join([
        f"# {day.isoformat()} · {scope.name}",
        *(session_section(group, group[0].session.id in linked, links, entries) for group in sessions),
    ]) + "\n"


def session_section(turns: Sequence[Placed], linked: bool, links: dict, entries: dict[str, Entry]) -> str:
    s = turns[0].session
    models = sorted({model_name(model) for p in turns for model in p.turn.models})
    details = " · ".join(filter(None, [
        f"session {s.id}", ", ".join(models), tilde(s.cwd) or ", ".join(s.repos), "" if linked else "no commit in scope",
    ]))
    return "\n\n".join([
        f"## {clock(turns[0].turn)} · {s.source}",
        details,
        *(turn_section(p, links.get((s.id, p.number), []), entries) for p in turns),
    ])


def turn_section(p: Placed, links: Sequence[Link], entries: dict[str, Entry]) -> str:
    return "\n\n".join(filter(None, [
        f"**{clock(p.turn)}** · {figures(p.turn)}",
        *(segment_block(segment, entries) for segment in p.segments),
        "" if p.segments else "> (no prompt)",
        "\n".join(f"- commit {l.commit.short} · {l.commit.repo} · {l.commit.subject}"
                  for l in sorted(links, key=lambda l: l.commit.authored)),
    ]))


def segment_block(segment: Segment, entries: dict[str, Entry]) -> str:
    if segment.pasted:
        return collapsed(f"pasted text, {lines(segment.text)}", quoted(segment.text))
    return quoted(reading(segment.text, entries))


def reading(text: str, entries: dict[str, Entry]) -> str:
    entry = entries.get(digest(text))
    return emended(text, entry.emendations).text if entry else text


def quoted(text: str) -> str:
    return "\n".join(f"> {line}".rstrip() for line in withheld(text).replace("<", "&lt;").splitlines())


def withheld(text: str) -> str:
    return CREDENTIAL.sub("[credential withheld]", text)


def collapsed(summary: str, quoted_body: str) -> str:
    return f"<details><summary>{summary}</summary>\n\n{quoted_body}\n\n</details>"


def lines(text: str) -> str:
    count = len(text.splitlines())
    return f"{count} line" if count == 1 else f"{count} lines"


def clock(turn: Turn) -> str:
    return turn.start.astimezone().strftime("%H:%M")
