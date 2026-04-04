#!/usr/bin/env python3
"""Extract session data from Codex CLI SQLite + rollout files for a given project path."""

import json
import sys
import os
import sqlite3
from datetime import datetime


PAUSE_THRESHOLD_SECONDS = 300  # 5 minutes


def format_active_time(minutes):
    if minutes < 1:
        return "<1\u00a0min"
    elif minutes < 60:
        return f"~{minutes}\u00a0min"
    else:
        return f"~{minutes / 60:.1f}\u00a0h"


def compute_active_minutes(rollout_path):
    """Sum gaps between consecutive event timestamps under the pause threshold."""
    if not os.path.exists(rollout_path):
        return 0
    timestamps = []
    with open(rollout_path) as fh:
        for line in fh:
            try:
                obj = json.loads(line.strip())
                ts = obj.get("timestamp")
                if ts:
                    timestamps.append(ts)
            except (json.JSONDecodeError, KeyError):
                pass
    if len(timestamps) < 2:
        return 0
    parsed = sorted(datetime.fromisoformat(t.replace("Z", "+00:00")) for t in timestamps)
    total_seconds = 0
    for i in range(1, len(parsed)):
        delta = (parsed[i] - parsed[i - 1]).total_seconds()
        if delta < PAUSE_THRESHOLD_SECONDS:
            total_seconds += delta
    return round(total_seconds / 60)


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
        active_mins = compute_active_minutes(rollout_path)

        sessions.append({
            "session_id": tid,
            "first_ts": created_dt.isoformat(),
            "last_ts": updated_dt.isoformat(),
            "model": model,
            "active_time": format_active_time(active_mins),
            "active_minutes": active_mins,
            "tokens_raw": tokens,
            "message_count": len(user_msgs),
            "user_messages": [m[:300] for m in user_msgs],
        })

    print(json.dumps(sessions, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
