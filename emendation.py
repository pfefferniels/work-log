"""Corrections of typed prompts into a clean reading text: proposed by a small model, checked and marked by code.

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
from difflib import SequenceMatcher
from functools import partial, reduce
from itertools import takewhile
from pathlib import Path

DEFAULT_MODEL = "claude-haiku-5-5"
RULES = 2
MIN_WORDS = 3
MAX_READING_WORDS = 4
MAX_ADDED_WORDS = 2
MAX_OMITTED_WORDS = 4
OMISSION_MARK = "[...]"
EXCLAMATION = (r"h+ä+h*|h+m+|ä+h+m*|e+h*m+|u+h*m+|u+h+|n+ä+h*|o+h+|a+h+|aha|omg|wtf|lol|(?:ha)+h?|(?:he)+h?"
               r"|g+r+|gr+m+p+f+|ar+g+h+|u+g+h+"
               r"|(?:god)?damn(?: it)?|shit|fuck(?: it)?|verdammt(?: nochmal)?|mist|schei(?:ß|ss)e"
               r"|[:;=xX][-'^o]?[()\[\]dDpPoO/\\|3*]+|\^\^|<3|[\U0001F300-\U0001FAFF☀-➿️]+")
PUNCTUATION = r"[\s,.;:!?…]*"
OMITTABLE = re.compile(rf"{PUNCTUATION}(?:{EXCLAMATION})(?:{PUNCTUATION}(?:{EXCLAMATION}))*{PUNCTUATION}", re.I)
BATCH_SIZE = 25
WORKERS = 4

INSTRUCTIONS = """\
You edit prompts a researcher typed or dictated to a coding agent into a clean reading text. The prompts will \
be published as a record of the researcher's AI use, so every change must be small and leave the meaning as it is.

Correct:
- misspelled words: "lke" -> "like", "parantheses" -> "parentheses", "Sitzungverlauf" -> "Sitzungsverlauf"
- dictation or typing errors where the intended word is certain from context: "lke the share" -> "like to share"
- doubled words: "the the" -> "the", unless one of them is a slip for another word: "go the the thing" -> "go to the thing"
- wrong grammar: agreement, verb forms, articles, prepositions, missing words: "it make sense" -> "it makes sense", \
"would like share" -> "would like to share", "in it's own" -> "in its own", "keine Grund" -> "keinen Grund"
- colloquial contractions and chat spellings, written out: "wanna" -> "want to", "gonna" -> "going to", \
"dunno" -> "don't know", "cause" meaning because -> "because", "u" -> "you", "ofc" -> "of course"
- missing or wrong punctuation: commas, full stops, question marks, apostrophes: "yes go ahead" -> "yes, go ahead", \
"what do you think." -> "what do you think?", "dont" -> "don't". Give the word before the mark, and the word \
after it where that helps to locate it, as `reading`.

Omit interjections, fillers and exclamations of frustration that carry no content: "hä", "hm", "ähm", "ehm", \
"uhm", "um" (only as a filler, never the German preposition), "näh", "oh", "ah", "aha", "omg", "grmpf", "argh", \
"ugh", "grrrr", "haha", "lol", "damn it", "oh damn it", "shit", "fuck", "wtf", "verdammt", "mist", "scheiße", and \
emoticons and emoji such as ":D", ":)", ";-)", "^^". Omit them only where they stand apart from the sentence, \
never where the word is part of it. For an omission give the exclamation together with the punctuation right \
after it as `reading` ("hm," or "oh damn it," or ":D") and an empty string as `correction`.

Leave as written:
- established abbreviations such as btw, afaik, e.g., ok, okay
- capitalization, also after a corrected full stop
- the mix of German and English, including German words in English sentences
- sentence fragments and ellipses that can be read
- slash commands, code, file paths, URLs, identifiers, and anything in quotation marks
- every case where the intended wording is not certain

For each change give `reading`, the words exactly as they stand in the prompt (one to four words, enough to \
locate them), and `correction`, the words that replace them. List changes in the order they occur. \
Many prompts need none; return an empty list for them, and an entry for every prompt id."""

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
    rules: int = 1


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
    if omission(emendation):
        return omitted(cursor, found)
    return Cursor(cursor.done + cursor.rest[:found.start()] + bracketed(emendation), cursor.rest[found.end():],
                  cursor.rejected)


def omitted(cursor: Cursor, found: re.Match) -> Cursor:
    """An omission leaves the mark in its place; omissions in a row share one."""
    between, rest = cursor.rest[:found.start()], cursor.rest[found.end():]
    if not between.strip() and cursor.done.endswith(OMISSION_MARK):
        return Cursor(cursor.done, rest, cursor.rejected)
    return Cursor(cursor.done + between + OMISSION_MARK, rest, cursor.rejected)


def omission(emendation: Emendation) -> bool:
    return not emendation.correction.split()


def admissible(emendation: Emendation) -> bool:
    reading, correction = emendation.reading.split(), emendation.correction.split()
    if not correction:
        return (0 < len(reading) <= MAX_OMITTED_WORDS
                and OMITTABLE.fullmatch(emendation.reading) is not None)
    return (0 < len(reading) <= MAX_READING_WORDS and len(correction) <= len(reading) + MAX_ADDED_WORDS
            and reading != correction)


def located(reading: str, text: str) -> re.Match | None:
    """The reading as whole words: a word character at either end may not continue a longer word."""
    words = reading.split()
    before = r"(?<!\w)" if re.match(r"\w", words[0]) else ""
    after = r"(?!\w)" if re.search(r"\w$", words[-1]) else ""
    return re.search(before + r"\s+".join(map(re.escape, words)) + after, text)


def bracketed(emendation: Emendation) -> str:
    """The correction with its changed words, and the changed punctuation of the others, in brackets. A dropped
    word brackets its surviving neighbour."""
    reading, correction = emendation.reading.split(), emendation.correction.split()
    letters, corrected = list(map(bare, reading)), list(map(bare, correction))
    head = shared_length(letters, corrected)
    tail = shared_length(letters[head:][::-1], corrected[head:][::-1])
    if letters != corrected and head + tail == len(correction):
        head, tail = (head - 1, tail) if head else (head, tail - 1)
    changed = correction[head:len(correction) - tail]
    before = map(repunctuated, reading[:head], correction[:head])
    after = map(repunctuated, reading[len(reading) - tail:], correction[len(correction) - tail:])
    return " ".join([*before, *([f"[{' '.join(changed)}]"] if changed else []), *after])


def repunctuated(typed: str, corrected: str) -> str:
    """The corrected word with each added or changed mark in brackets; a removed mark brackets the whole word."""
    steps = SequenceMatcher(None, typed, corrected, autojunk=False).get_opcodes()
    if any(step == "delete" for step, *_ in steps):
        return f"[{corrected}]"
    return "".join(corrected[start:end] if step == "equal" else f"[{corrected[start:end]}]"
                   for step, _, _, start, end in steps)


def bare(word: str) -> str:
    return re.sub(r"\W", "", word)


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
    return {key: Entry(value["model"], tuple(Emendation(**e) for e in value["emendations"]), value.get("rules", 1))
            for key, value in stored.items()}


def save(path: Path, entries: dict[str, Entry]) -> None:
    stored = {key: asdict(entry) for key, entry in sorted(entries.items())}
    path.write_text(json.dumps(stored, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def complete(path: Path, texts: Iterable[str], model: str) -> int:
    """Emend every text the apparatus at `path` lacks under the current rules, saving after each batch; returns the
    proposals rejected."""
    entries = load(path)
    pending = sorted({text for text in texts if worth_reading(text) and outdated(entries.get(digest(text)))})
    if not pending:
        return 0
    batches = [pending[start:start + BATCH_SIZE] for start in range(0, len(pending), BATCH_SIZE)]
    print(f"Emending {len(pending)} passages in {len(batches)} batches with {model}", file=sys.stderr, flush=True)
    rejected = 0
    for results in proposed(batches, model):
        entries |= {digest(result.text): Entry(model, result.kept, RULES) for result in results}
        rejected += sum(len(result.rejected) for result in results)
        save(path, entries)
    return rejected


def outdated(entry: Entry | None) -> bool:
    return entry is None or entry.rules < RULES


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
