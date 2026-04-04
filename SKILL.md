---
name: work-log
description: Summarize LLM coding session history as a topic-oriented docx table
---

Summarize all LLM coding session files (Claude Code + Codex) for the current project directory into a topic-oriented table documenting the work timeline. The unit of one row is a **work topic**, not a session — a single session may produce multiple entries, and work on the same topic across sessions should be merged into one entry.

## Workflow

### Step 1: Extract session data

#### Claude Code sessions

Run the extraction script. Replace `<session-dir>` with `~/.claude/projects/<project-path>/` and `<current-session-id>` with this session's ID (from the JSONL filename):

```
python3 ~/.claude/skills/document/extract_sessions.py <session-dir> <current-session-id>
```

This outputs JSON with timestamps, model name, token usage, message counts, and user messages for each non-trivial session.

#### Codex sessions (if ~/.codex exists)

Run the Codex extraction script with one or more cwd patterns that match the project:

```
python3 ~/.claude/skills/document/extract_codex_sessions.py <cwd-pattern> [additional-patterns...]
```

Example: `python3 ~/.claude/skills/document/extract_codex_sessions.py mpm-desk mpmify`

This queries `~/.codex/state_5.sqlite` and parses rollout JSONL files for user messages and model info.

### Step 2: Review, cluster by topic, and curate

Review the extracted data from both sources and **cluster by work topic**, not by session:
- Identify distinct topics/tasks across all sessions (e.g. "Instruction Popover", "Performance Optimization", "CORS Debugging")
- A single session covering multiple topics → split into separate entries
- The same topic worked on across multiple sessions → merge into one entry with a date range
- Exclude purely technical work (only commit & push, port conflicts, running tests without context)
- Attribute user messages and tokens to each topic (estimate when a session covers multiple topics)
- Use the `model` field from extraction output for the "modell" column

### Step 3: Write summaries and generate DOCX

For each topic, create an entry with:
- **nr**: Sequential number
- **datum**: German date format (DD.MM.YYYY). For multi-day topics use ranges (e.g. 06.–07.03.2026)
- **modell**: Model name from extraction (e.g. "Opus 4.6", "GPT-5.3")
- **umfang**: Combo of user message count and tokens, e.g. "8 / ~45k" (header already labels the units)
- **summary**: Max 10 words. Keep technical terms untranslated (e.g. Subsequence Matcher, LLM-Diff, Mood Chord)
- **note** (optional, use sparingly): Brief italic explanatory detail — only include when the summary alone would be unclear to a reader unfamiliar with the project (e.g. explaining *why* something was done, or clarifying an ambiguous technical term). Most entries should have NO note. When in doubt, leave it out.

Order entries by descending complexity (token count as primary sort key) so the most substantial work appears first.

Write the curated JSON array to a temp file (avoids shell encoding issues with umlauts and special characters), then pass it to the generation script:

```
python3 ~/.claude/skills/document/generate_docx.py <project_name> <output_path> /tmp/sessions.json
```

## Output format

- Heading: "Arbeitsverlauf – LLM-Coding × <project name>"
- Font: Garamond throughout
- Table style: "List Table 1 Light" (Listentabelle 1 Hell) with columns: Nr., Datum, Modell, Umfang (Nachr. / Tokens), Zusammenfassung
- Modell column: model display name (e.g. "Opus 4.6", "GPT-5.3")
- Umfang column: message count + token count (e.g. "8 / ~45k") — header already explains the units, so keep cell values short
- Summary column: 9pt font; explanatory notes: 8pt italic gray
- Footer: total entry count, date range, project name
- Use proper German umlauts (ä, ö, ü, ß) — do NOT use ae/oe/ue substitutions
- Save to the project root directory
