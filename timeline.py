"""Fold the events of a transcript into turns, one per prompt the researcher typed."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import accumulate, groupby, pairwise
from operator import attrgetter, itemgetter

from session import CommitCall, Turn

PAUSE = timedelta(minutes=5)
EDIT_TOOLS = frozenset({"Edit", "MultiEdit", "Write", "NotebookEdit", "apply_patch"})


@dataclass(frozen=True)
class Prompt:
    at: datetime
    text: str


@dataclass(frozen=True)
class Aside:
    """A message typed while the assistant was still working on the current turn."""

    at: datetime
    text: str


@dataclass(frozen=True)
class Reply:
    at: datetime
    message_id: str
    model: str
    output_tokens: int


@dataclass(frozen=True)
class ToolCall:
    at: datetime
    name: str
    path: str | None = None


@dataclass(frozen=True)
class Activity:
    at: datetime


Event = Prompt | Aside | Reply | ToolCall | CommitCall | Activity


def build_turns(events: Iterable[Event]) -> tuple[Turn, ...]:
    ordered = sorted(events, key=attrgetter("at"))
    unanswered = {group[0] for group in split_at_prompts(ordered)[:-1] if not has_reply(group)}
    groups = split_at_prompts([Activity(event.at) if event in unanswered else event for event in ordered])
    previous_ends = [None, *(group[-1].at for group in groups[:-1])]
    return tuple(
        make_turn(group, previous_end)
        for group, previous_end in zip(groups, previous_ends)
        if isinstance(group[0], Prompt) or any(isinstance(event, (ToolCall, CommitCall)) for event in group)
    )


def split_at_prompts(ordered: Sequence[Event]) -> list[list[Event]]:
    turn_numbers = accumulate(isinstance(event, Prompt) for event in ordered)
    return [[event for _, event in group] for _, group in groupby(zip(turn_numbers, ordered), key=itemgetter(0))]


def has_reply(group: Sequence[Event]) -> bool:
    """A prompt without reply was interrupted or sent again; the prompt after it carries the intention."""
    return not isinstance(group[0], Prompt) or any(isinstance(event, (Reply, ToolCall)) for event in group)


def make_turn(events: Sequence[Event], previous_end: datetime | None) -> Turn:
    tools = [event for event in events if isinstance(event, ToolCall)]
    edits = [tool for tool in tools if tool.name in EDIT_TOOLS]
    replies = [event for event in events if isinstance(event, Reply)]
    times = [event.at for event in events]
    return Turn(
        start=times[0],
        end=times[-1],
        prompt="\n".join(event.text for event in events if isinstance(event, (Prompt, Aside))),
        active_seconds=round(active_time([previous_end, *times] if previous_end else times).total_seconds()),
        output_tokens=output_tokens(replies),
        models=tuple(sorted({reply.model for reply in replies if reply.model})),
        tool_calls=len(tools),
        edits=len(edits),
        files=tuple(sorted({edit.path for edit in edits if edit.path})),
        commit_calls=tuple(event for event in events if isinstance(event, CommitCall)),
    )


def active_time(times: Sequence[datetime]) -> timedelta:
    """Time between consecutive events, leaving out pauses."""
    return sum((later - earlier for earlier, later in pairwise(times) if later - earlier < PAUSE), timedelta())


def output_tokens(replies: Iterable[Reply]) -> int:
    """A streamed reply can be logged as several lines of one message, so count each message once."""
    by_message = groupby(sorted(replies, key=attrgetter("message_id")), key=attrgetter("message_id"))
    return sum(max(reply.output_tokens for reply in group) for _, group in by_message)
