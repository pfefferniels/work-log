#!/usr/bin/env python3
"""Extract session data from Codex CLI SQLite + rollout files for a given project path."""

import json
import sys
import os
import sqlite3
from datetime import datetime


def format_tokens(total):
    if total < 1000:
        return f"{total}"
    elif total < 1_000_000:
        return f"~{total / 1000:.0f}k"
    else:
        return f"~{total / 1_000_000:.1f}M"


def extract_user_messages(rollout_path):
    """Parse user messages from a Codex rollout JSONL file."""
    msgs = []
    if not os.path.exists(rollout_path):
        return msgs
    with open(rollout_path) as fh:
        for line in fh:
            try:
                obj = json.loads(line.strip())
                if obj.get("type") == "response_item":
                    payload = obj.get("payload", {})
                    if payload.get("role") == "user":
                        for part in payload.get("content", []):
                            if isinstance(part, dict):
                                text = part.get("text", "")
                                if text.startswith("<") or text.startswith("#"):
                                    continue
                                text = text.strip()
                                if text and text not in ("q", "quit"):
                                    msgs.append(text)
            except (json.JSONDecodeError, KeyError):
                pass
    return msgs


MODEL_DISPLAY = {
    "gpt-5.3-codex": "GPT-5.3",
    "gpt-5.4": "GPT-5.4",
    "gpt-4o": "GPT-4o",
    "o3": "o3",
    "o1": "o1",
}


def extract_model(rollout_path):
    """Extract model name from rollout file turn_context events."""
    if not os.path.exists(rollout_path):
        return ""
    with open(rollout_path) as fh:
        for line in fh:
            try:
                obj = json.loads(line.strip())
                if obj.get("type") == "turn_context":
                    model = obj.get("payload", {}).get("model", "")
                    if model:
                        return MODEL_DISPLAY.get(model, model)
            except (json.JSONDecodeError, KeyError):
                pass
    return ""


def main():
    if len(sys.argv) < 2:
        print("Usage: extract_codex_sessions.py <project-cwd-pattern> [additional-cwd-pattern ...]", file=sys.stderr)
        print("  e.g.: extract_codex_sessions.py mpm-desk mpmify", file=sys.stderr)
        sys.exit(1)

    cwd_patterns = sys.argv[1:]
    codex_home = os.path.expanduser("~/.codex")
    db_path = os.path.join(codex_home, "state_5.sqlite")

    if not os.path.exists(db_path):
        print("[]")
        return

    db = sqlite3.connect(db_path)

    where_clauses = " OR ".join(f"cwd LIKE '%{p}%'" for p in cwd_patterns)
    rows = db.execute(f"""
        SELECT id, created_at, updated_at, tokens_used, cwd, rollout_path
        FROM threads
        WHERE {where_clauses}
        ORDER BY created_at
    """).fetchall()

    sessions = []
    for tid, created, updated, tokens, cwd, rollout in rows:
        rollout_path = rollout if os.path.isabs(rollout) else os.path.join(codex_home, rollout)

        user_msgs = extract_user_messages(rollout_path)
        if not user_msgs:
            continue

        model = extract_model(rollout_path)
        created_dt = datetime.fromtimestamp(created)
        updated_dt = datetime.fromtimestamp(updated)

        sessions.append({
            "session_id": tid,
            "first_ts": created_dt.isoformat(),
            "last_ts": updated_dt.isoformat(),
            "model": model,
            "tokens": format_tokens(tokens),
            "tokens_raw": tokens,
            "message_count": len(user_msgs),
            "user_messages": [m[:300] for m in user_msgs],
        })

    print(json.dumps(sessions, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
