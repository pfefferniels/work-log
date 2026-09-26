"""Claude Code sessions that ran in the cloud (claude.ai/code), read through the sessions API.

The endpoints are undocumented and in beta; cloud-sessions-api.md records what is known about them.
"""

import json
import ssl
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from claude_code import reply_events, typed_text
from jsonl import timestamp
from session import Session
from timeline import Activity, Event, Prompt, build_turns

API = "https://api.anthropic.com/v1/code/sessions"
HEADERS = {"anthropic-version": "2023-06-01", "anthropic-beta": "ccr-byoc-2025-07-29"}
WORK_EVENTS = frozenset({"user", "assistant", "result", "system", "tool_progress"})
SYSTEM_CERTIFICATES = Path("/etc/ssl/cert.pem")


class CloudUnavailable(Exception):
    pass


def tls_context() -> ssl.SSLContext:
    """The python.org builds for macOS come without CA certificates, so trust the system's as well."""
    context = ssl.create_default_context()
    if SYSTEM_CERTIFICATES.exists():
        context.load_verify_locations(SYSTEM_CERTIFICATES)
    return context


def keychain_token() -> str:
    found = subprocess.run(
        ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
        capture_output=True, text=True,
    )
    if found.returncode != 0:
        raise CloudUnavailable("no Claude Code credentials in the macOS keychain")
    try:
        return json.loads(found.stdout)["claudeAiOauth"]["accessToken"]
    except (json.JSONDecodeError, KeyError) as error:
        raise CloudUnavailable("the keychain entry holds no OAuth access token") from error


@dataclass(frozen=True)
class Client:
    token: str

    def get(self, path: str, **query: str | int) -> dict:
        request = Request(f"{API}{path}?{urlencode(query)}", headers=HEADERS | {"Authorization": f"Bearer {self.token}"})
        with urlopen(request, timeout=30, context=tls_context()) as response:
            return json.load(response)

    def pages(self, path: str, limit: int) -> Iterator[dict]:
        """Every item of a listing, following `next_cursor` until the server stops sending one."""
        page = self.get(path, limit=limit)
        yield from page.get("data", [])
        while page.get("data") and page.get("next_cursor"):
            page = self.get(path, limit=limit, cursor=page["next_cursor"])
            yield from page.get("data", [])

    def summaries(self) -> list[dict]:
        return list(self.pages("", limit=100))

    def events(self, session_id: str) -> Iterator[dict]:
        return self.pages(f"/{session_id}/events", limit=200)


def read(client: Client, summary: dict) -> Session | None:
    turns = build_turns(event for raw in client.events(summary["id"]) for event in work_events(raw))
    if not turns:
        return None
    outcomes = (summary.get("config") or {}).get("outcomes") or []
    repos = tuple(outcome["git_info"]["repo"] for outcome in outcomes if (outcome.get("git_info") or {}).get("repo"))
    return Session("Claude Code (Cloud)", summary["id"], summary.get("title") or "", "", False, repos, turns)


def work_events(raw: dict) -> Iterator[Event]:
    """Events that show work on the session; page views and suggestions arrive later and would stretch it."""
    kind = raw.get("event_type")
    payload = raw.get("payload") or {}
    at = timestamp(payload.get("timestamp")) or timestamp(raw.get("created_at"))
    if kind not in WORK_EVENTS or at is None:
        return
    match kind:
        case "user" if not payload.get("parent_tool_use_id") and (text := typed_text(payload)):
            yield Prompt(at, text)
        case "assistant":
            yield from reply_events(payload.get("message") or {}, at)
        case _:
            yield Activity(at)
