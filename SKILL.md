---
name: work-log
description: Summarize LLM coding session history as a topic-oriented docx table
---

Summarize all LLM coding session files (Claude Code + Codex) for the current project directory into a topic-oriented table documenting the work timeline. The unit of one row is a **work topic**, not a session — a single session may produce multiple entries, and work on the same topic across sessions should be merged into one entry.

## Workflow

### Step 1: Extract session data (parallel agents)

Launch **two agents in parallel** to extract Claude Code and Codex sessions simultaneously:

#### Agent 1: Claude Code sessions

Run the extraction script. Replace `<session-dir>` with `~/.claude/projects/<project-path>/` and `<current-session-id>` with this session's ID (from the JSONL filename):

```
python3 ~/.claude/skills/work-log/extract_sessions.py <session-dir> <current-session-id>
```

This outputs JSON with `sessions` (timestamps, model name, active time, token usage, message counts, user messages) and optionally `tombstones` (count and date range of sessions whose JSONL files were deleted by Claude Code's cleanup). Active time is computed by summing gaps between consecutive messages that are under 5 minutes (longer gaps are treated as pauses).

#### Agent 2: Codex sessions (if ~/.codex exists)

Run the Codex extraction script with one or more cwd patterns that match the project:

```
python3 ~/.claude/skills/work-log/extract_codex_sessions.py <cwd-pattern> [additional-patterns...]
```

Example: `python3 ~/.claude/skills/work-log/extract_codex_sessions.py mpm-desk mpmify`

This queries `~/.codex/state_5.sqlite` and parses rollout JSONL files for user messages, model info, and active time (using the same 5-minute pause threshold as Claude Code).

Wait for both agents to complete, then proceed with the combined results.

#### Git log extraction (run alongside the agents above)

Extract the project's git history covering the same time range as the sessions:

```
git log --format="%h %aI %s" --all --since="<earliest-session-date>"
```

### Step 2: Review, cluster by topic, and curate

Review the extracted data from both sources and **cluster by work topic**, not by session:
- Identify distinct topics/tasks across all sessions (e.g. "Instruction Popover", "Performance Optimization", "CORS Debugging")
- A single session covering multiple topics → split into separate entries
- The same topic worked on across multiple sessions → merge into one entry with a date range
- Exclude purely technical work (only commit & push, port conflicts, running tests without context)
- Attribute active time to each topic: for multi-session topics, **sum** the active time from all contributing sessions. When a single session covers multiple topics, estimate proportionally.
- Determine the interaction mode for each topic: **dialogisch**, **autonom**, or **explorativ** — based on the ratio of user/assistant messages and tool call patterns (reads vs. writes)
- Use the `model` field from extraction output for the "modell" column

**Associate commits with topics:** Match commits from the git log to topics based on:
1. Timestamp overlap (commit author date falls within a session's time range)
2. Content match (commit message relates to the session's topic)
3. **Important:** If changes were coded in session A but committed in session B, attribute the commit to session A (where the work was done), not session B. Use the session content (user messages, tool calls) to determine where work actually happened.

Topics that resulted in no commits may be omitted or kept with an empty commits list — use judgment based on whether the work is worth documenting.

### Step 3: Write summaries and generate DOCX

For each topic, create an entry with:
- **nr**: Sequential number
- **datum**: German date format without leading zeros (D.M.YYYY). For multi-day topics use ranges (e.g. 6.–7.3.2026).
- **modell**: Model name from extraction (e.g. "Opus 4.6", "GPT-5.3")
- **umfang**: Interaction mode and active time, e.g. "autonom, ~30\u00a0min". The three modes are:
  - **dialogisch** — lots of back-and-forth, user actively steering, corrections
  - **autonom** — model works independently, few user messages, long runs with many tool calls
  - **explorativ** — reading, searching, investigating; few or no edits/writes
- **topic**: 3–5 words, in **German**, verb-centered (no Nominalstil). Derived from the associated commit messages. Keep technical terms in English (same rules as before). Examples: "Popover-Logik überarbeitet", "CORS-Fehler behoben", "Drag & Drop eingebaut" — not "Überarbeitung der Popover-Logik".
- **commits**: List of short commit hashes (7 chars) associated with this topic. Empty list if no commits resulted from the work.

Order entries by descending active time so the most substantial work appears first.

**Tombstones:** If the extraction reported tombstones, use the tombstone date range and the git log to find commits that aren't already attributed to a reconstructed session. Cluster these commits by topic (derived from commit messages) and add a special entry at the end of the JSON array:
```json
{
  "type": "tombstones",
  "count": 12,
  "entries": [
    {"nr": 8, "datum": "vor dem 1.3.2026", "topic": "CORS-Fehler behoben", "commits": ["abc1234"]},
    {"nr": 9, "datum": "vor dem 15.3.2026", "topic": "Drag & Drop eingebaut", "commits": ["def5678", "ghi9012"]}
  ]
}
```
Each entry gets its own `datum` — use "vor dem [date]" where the date is the author date of the earliest commit in that topic group (the work must have happened before the commit). The generate script renders Nr., Datum, and Commits per-row, while Modell and Umfang/Modus are merged across all tombstone rows showing the session count and "(unbekannt)".

Write the curated JSON array to a temp file (avoids shell encoding issues with umlauts and special characters), then pass it to the generation script:

```
python3 ~/.claude/skills/work-log/generate_docx.py <project_name> <output_path> /tmp/sessions.json
```

## Output format

- Heading: "Arbeitsverlauf – LLM-Coding × <project name>"
- Font: Garamond throughout
- Table style: "List Table 1 Light" (Listentabelle 1 Hell) with columns: Nr., Datum, Modell, Modus und Umfang, Commits
- Modell column: model display name (e.g. "Opus 4.6", "GPT-5.3")
- Modus und Umfang column: interaction mode + active time (e.g. "autonom, ~30\u00a0min")
- Commits column: topic line in 9pt Garamond, then commit hashes in 8pt gray monospace (Courier New)
- Footer: total entry count, date range, project name
- Use proper German umlauts (ä, ö, ü, ß) — do NOT use ae/oe/ue substitutions
- Save to the project root directory
