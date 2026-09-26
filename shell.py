"""Recognize `git commit` in shell commands and edited files in patches."""

import re
from datetime import datetime

from session import CommitCall

GIT_COMMIT = re.compile(r"\bgit(?:\s+-[Cc]\s+(?:\"[^\"]*\"|'[^']*'|\S+))*\s+commit\b")
HEREDOC_MESSAGE = re.compile(
    r"""(?:(?:^|\s)(?:-[a-zA-Z]*m|--message)(?:\s+|=)"?\$\(cat\s+|(?:^|\s)(?:-F|--file)(?:\s+|=)-\s+)"""
    r"""<<-?\s*(['"]?)(\w+)\1[^\n]*\n(.*?)\n\s*\2\b""",
    re.S,
)
MESSAGE = re.compile(r"""(?:^|\s)(?:-[a-zA-Z]*m|--message)(?:\s+|=)(?:"((?:[^"\\]|\\.)*)"|'([^']*)'|([^\s;&|]+))""")
PATCHED_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)


def commit_calls(at: datetime, command: str) -> list[CommitCall]:
    matches = list(GIT_COMMIT.finditer(command))
    ends = [match.start() for match in matches[1:]] + [len(command)]
    return [CommitCall(at, commit_subject(command[match.end():end])) for match, end in zip(matches, ends)]


def commit_subject(arguments: str) -> str | None:
    if heredoc := HEREDOC_MESSAGE.search(arguments):
        return first_line(heredoc.group(3))
    if message := MESSAGE.search(arguments):
        double_quoted, single_quoted, bare = message.groups()
        if double_quoted is not None:
            return first_line(double_quoted.replace('\\"', '"'))
        return first_line(single_quoted if single_quoted is not None else bare)
    return None


def first_line(text: str) -> str | None:
    return next((line.strip() for line in text.splitlines() if line.strip()), None)


def patched_files(patch: str) -> list[str]:
    return [path.strip() for path in PATCHED_FILE.findall(patch)]
