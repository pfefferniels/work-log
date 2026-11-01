"""Corrections of slips in typed prompts: proposed by a small model, checked and marked by code.

The model only proposes pairs of a reading (the words as typed) and its correction. A proposal is kept when
its reading occurs after the previous one and it changes no more than a few words, so the edited text differs
from the typed one only inside square brackets.
"""

import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
from functools import partial, reduce
from itertools import takewhile
from pathlib import Path

DEFAULT_MODEL = "claude-haiku-5-5"
MIN_WORDS = 3
MAX_READING_WORDS = 4
MAX_ADDED_WORDS = 2
BATCH_SIZE = 25
WORKERS = 4

INSTRUCTIONS = """\
You correct slips in prompts a researcher typed or dictated to a coding agent. The prompts will be published \
as a record of the researcher's AI use, so a correction must be small and certain.

Correct only:
- misspelled words: "lke" -> "like", "parantheses" -> "parentheses", "Sitzungverlauf" -> "Sitzungsverlauf"
- a word missing for the sentence to be read: "would like share" -> "would like to share"
- doubled words: "the the" -> "the", unless one of them is a slip for another word: "go the the thing" -> "go to the thing"
- dictation or typing errors where the intended word is certain from context: "lke the share" -> "like to share"

Leave as written:
- informal register, fillers, interjections and abbreviations (hm, näh, btw, ofc, u)
- capitalization, punctuation and missing commas
- the mix of German and English, including German words in English sentences
- sentence fragments, ellipses, and grammar that is unusual but intelligible
- slash commands, code, file paths, URLs, identifiers, and anything in quotation marks
- every case where the intended word is not certain

For each correction give `reading`, the words exactly as they stand in the prompt (one to four words, enough to \
locate them), and `correction`, the words that replace them. List corrections in the order they occur. \
Most prompts need none; return an empty list for them, and an entry for every prompt id."""

SCHEMA = json.dumps({
    "type": "object",
    "properties": {"prompts": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "corrections": {"type": "array", "items": {
                "type": "object",
                "properties": {"reading": {"type": "string"}, "correction": {"type": "string"}},
                "required": ["reading", "correction"],
            }},
        },
        "required": ["id", "corrections"],
    }}},
    "required": ["prompts"],
})


class ModelFailed(Exception):
    pass


@dataclass(frozen=True)
class Emendation:
    reading: str
    correction: str


@dataclass(frozen=True)
class Entry:
    model: str
    emendations: tuple[Emendation, ...]


@dataclass(frozen=True)
class Emended:
    text: str
    rejected: tuple[Emendation, ...]


@dataclass(frozen=True)
class Checked:
    text: str
    kept: tuple[Emendation, ...]
    rejected: tuple[Emendation, ...]


@dataclass(frozen=True)
class Cursor:
    done: str
    rest: str
    rejected: tuple[Emendation, ...]


def emended(text: str, emendations: Iterable[Emendation]) -> Emended:
    end = reduce(advance, emendations, Cursor("", text, ()))
    return Emended(end.done + end.rest, end.rejected)


def advance(cursor: Cursor, emendation: Emendation) -> Cursor:
    found = located(emendation.reading, cursor.rest) if admissible(emendation) else None
    if found is None:
        return replace(cursor, rejected=(*cursor.rejected, emendation))
    return Cursor(cursor.done + cursor.rest[:found.start()] + bracketed(emendation), cursor.rest[found.end():],
                  cursor.rejected)


def admissible(emendation: Emendation) -> bool:
    reading, correction = emendation.reading.split(), emendation.correction.split()
    return (0 < len(reading) <= MAX_READING_WORDS and 0 < len(correction) <= len(reading) + MAX_ADDED_WORDS
            and reading != correction)


def located(reading: str, text: str) -> re.Match | None:
    return re.search(r"(?<!\w)" + r"\s+".join(map(re.escape, reading.split())) + r"(?!\w)", text)


def bracketed(emendation: Emendation) -> str:
    """The correction with its changed words in brackets; a dropped word brackets its surviving neighbour."""
    reading, correction = emendation.reading.split(), emendation.correction.split()
    head = shared_length(reading, correction)
    tail = shared_length(reading[head:][::-1], correction[head:][::-1])
    if head + tail == len(correction):
        head, tail = (head - 1, tail) if head else (head, tail - 1)
    changed = correction[head:len(correction) - tail]
    return " ".join([*correction[:head], f"[{' '.join(changed)}]", *correction[len(correction) - tail:]])


def shared_length(first: Sequence[str], second: Sequence[str]) -> int:
    return sum(1 for _ in takewhile(lambda pair: pair[0] == pair[1], zip(first, second)))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def worth_reading(text: str) -> bool:
    return len(text.split()) >= MIN_WORDS


def load(path: Path) -> dict[str, Entry]:
    if not path.exists():
        return {}
    stored = json.loads(path.read_text(encoding="utf-8"))
    return {key: Entry(value["model"], tuple(Emendation(**e) for e in value["emendations"]))
            for key, value in stored.items()}


def save(path: Path, entries: dict[str, Entry]) -> None:
    stored = {key: asdict(entry) for key, entry in sorted(entries.items())}
    path.write_text(json.dumps(stored, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def complete(path: Path, texts: Iterable[str], model: str) -> int:
    """Emend every text not yet in the apparatus at `path`, saving after each batch; returns the proposals rejected."""
    entries = load(path)
    pending = sorted({text for text in texts if worth_reading(text) and digest(text) not in entries})
    if not pending:
        return 0
    batches = [pending[start:start + BATCH_SIZE] for start in range(0, len(pending), BATCH_SIZE)]
    print(f"Emending {len(pending)} passages in {len(batches)} batches with {model}", file=sys.stderr, flush=True)
    rejected = 0
    for results in proposed(batches, model):
        entries |= {digest(result.text): Entry(model, result.kept) for result in results}
        rejected += sum(len(result.rejected) for result in results)
        save(path, entries)
    return rejected


def proposed(batches: Sequence[Sequence[str]], model: str) -> Iterator[list[Checked]]:
    """The checked proposals for each batch, in order; the model reads up to WORKERS batches at once."""
    with ThreadPoolExecutor(WORKERS) as pool:
        for batch, proposals in zip(batches, pool.map(partial(propose, model=model), batches)):
            yield list(map(checked, batch, proposals))


def checked(text: str, offered: tuple[Emendation, ...]) -> Checked:
    rejected = emended(text, offered).rejected
    return Checked(text, tuple(e for e in offered if e not in rejected), rejected)


def propose(texts: Sequence[str], model: str) -> list[tuple[Emendation, ...]]:
    ids = [f"p{number}" for number in range(len(texts))]
    payload = json.dumps([{"id": id, "text": text} for id, text in zip(ids, texts)], ensure_ascii=False)
    done = subprocess.run(
        ["claude", "-p", "--model", model, "--tools", "", "--no-session-persistence", "--strict-mcp-config",
         "--setting-sources", "", "--system-prompt", INSTRUCTIONS, "--output-format", "json", "--json-schema", SCHEMA],
        input=payload, capture_output=True, text=True, timeout=900,
    )
    answers = {item["id"]: item["corrections"] for item in structured(done)["prompts"]}
    return [tuple(Emendation(c["reading"], c["correction"]) for c in answers.get(id, [])) for id in ids]


def structured(done: subprocess.CompletedProcess) -> dict:
    if done.returncode != 0:
        raise ModelFailed(done.stderr.strip() or done.stdout.strip()[:500])
    reply = json.loads(done.stdout)
    if reply.get("is_error") or not isinstance(reply.get("structured_output"), dict):
        raise ModelFailed(str(reply.get("result") or "no structured output"))
    return reply["structured_output"]
