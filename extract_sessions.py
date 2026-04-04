#!/usr/bin/env python3
"""Extract session data from Claude Code JSONL files for a given project path."""

import json
import sys
import os
import glob
from datetime import datetime

PAUSE_THRESHOLD_SECONDS = 300  # 5 minutes


def parse_session(filepath):
    timestamps = []
    user_msgs = []
    total_input = 0
    total_output = 0
    models = set()

    with open(filepath, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") == "file-history-snapshot":
                ts = obj.get("snapshot", {}).get("timestamp")
                if ts:
                    timestamps.append(ts)

            msg = obj.get("message", {})
            ts = msg.get("timestamp")
            if ts:
                timestamps.append(ts)

            model = msg.get("model", "")
            if model and model != "<synthetic>":
                models.add(model)

            usage = msg.get("usage", {})
            if usage:
                total_input += usage.get("input_tokens", 0)
                total_output += usage.get("output_tokens", 0)

            if obj.get("type") == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    user_msgs.append(content.strip())
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            user_msgs.append(part["text"].strip())

    timestamps = [t for t in timestamps if t]
    model = format_model(models)
    active_mins = compute_active_minutes(timestamps)
    return timestamps, user_msgs, total_input + total_output, model, active_mins


def compute_active_minutes(timestamps):
    """Sum gaps between consecutive timestamps that are under the pause threshold."""
    if len(timestamps) < 2:
        return 0
    parsed = sorted(datetime.fromisoformat(t) for t in timestamps)
    total_seconds = 0
    for i in range(1, len(parsed)):
        delta = (parsed[i] - parsed[i - 1]).total_seconds()
        if delta < PAUSE_THRESHOLD_SECONDS:
            total_seconds += delta
    return round(total_seconds / 60)


def format_active_time(minutes):
    if minutes < 1:
        return "<1\u00a0min"
    elif minutes < 60:
        return f"~{minutes}\u00a0min"
    else:
        return f"~{minutes / 60:.1f}\u00a0h"


MODEL_DISPLAY = {
    "claude-opus-4-6": "Opus 4.6",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
}


def format_model(models):
    """Convert raw model IDs to display names."""
    if not models:
        return ""
    display = set()
    for m in models:
        display.add(MODEL_DISPLAY.get(m, m))
    return " + ".join(sorted(display))


def is_trivial(user_msgs):
    """Check if a session contains only commands/trivial content."""
    substantive = []
    for m in user_msgs:
        if any(tag in m for tag in [
            "<command-name>", "<local-command", "<task-notification>",
            "Base directory for this skill"
        ]):
            continue
        if m.strip() in ("[Request interrupted by user]", "[Request interrupted by user for tool use]"):
            continue
        substantive.append(m)
    return len(substantive) == 0, substantive


def format_tokens(total):
    if total < 1000:
        return f"{total}"
    elif total < 1_000_000:
        return f"~{total / 1000:.0f}k"
    else:
        return f"~{total / 1_000_000:.1f}M"


def main():
    if len(sys.argv) < 2:
        print("Usage: extract_sessions.py <session-dir> [current-session-id]", file=sys.stderr)
        sys.exit(1)

    session_dir = sys.argv[1]
    current_session = sys.argv[2] if len(sys.argv) > 2 else None

    files = sorted(glob.glob(os.path.join(session_dir, "*.jsonl")))
    sessions = []

    for filepath in files:
        session_id = os.path.basename(filepath).replace(".jsonl", "")
        if current_session and session_id == current_session:
            continue

        timestamps, user_msgs, total_tokens, model, active_mins = parse_session(filepath)
        trivial, substantive = is_trivial(user_msgs)

        if trivial or not timestamps:
            continue

        first_ts = min(timestamps)
        last_ts = max(timestamps)

        sessions.append({
            "session_id": session_id,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "model": model,
            "active_time": format_active_time(active_mins),
            "active_minutes": active_mins,
            "tokens_raw": total_tokens,
            "message_count": len(substantive),
            "user_messages": [m[:300] for m in substantive],
        })

    sessions.sort(key=lambda s: s["first_ts"])

    # Detect tombstones: directories without matching JSONL files
    jsonl_ids = {os.path.basename(f).replace(".jsonl", "") for f in files}
    if current_session:
        jsonl_ids.add(current_session)
    all_dirs = [
        d for d in os.listdir(session_dir)
        if os.path.isdir(os.path.join(session_dir, d))
        and d not in ("__pycache__",)
    ]
    orphaned = [d for d in all_dirs if d not in jsonl_ids]

    tombstones = None
    if orphaned:
        timestamps = []
        for d in orphaned:
            dir_path = os.path.join(session_dir, d)
            stat = os.stat(dir_path)
            try:
                ts = stat.st_birthtime  # macOS
            except AttributeError:
                ts = stat.st_mtime
            timestamps.append(datetime.fromtimestamp(ts))
        timestamps.sort()
        tombstones = {
            "count": len(orphaned),
            "first_ts": timestamps[0].isoformat(),
            "last_ts": timestamps[-1].isoformat(),
        }

    output = {"sessions": sessions}
    if tombstones:
        output["tombstones"] = tombstones
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
