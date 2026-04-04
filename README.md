# work-log

A Claude Code skill that generates a DOCX work log from LLM coding sessions (Claude Code + OpenAI Codex). Instead of listing sessions chronologically, it clusters work by **topic** — splitting multi-topic sessions and merging cross-session work on the same topic.

## Output

A DOCX table with columns:

| Nr. | Datum | Modell | Umfang | Zusammenfassung |
|-----|-------|--------|--------|-----------------|

- **Datum**: date or range (e.g. "22.–23.03.2026")
- **Modell**: which model was used (e.g. "Opus 4.6", "GPT-5.4")
- **Umfang**: user message count + token count (e.g. "8 Nachr. / ~45k")
- **Zusammenfassung**: topic summary + optional italic note

Entries are sorted by descending complexity (token count).

## Installation

Copy or symlink into your Claude Code skills directory:

```bash
# Clone
git clone https://github.com/pfefferniels/work-log.git

# Symlink into Claude Code skills
ln -s "$(pwd)/work-log" ~/.claude/skills/work-log
```

Or copy the files directly:

```bash
cp -r work-log ~/.claude/skills/work-log
```

## Usage

In Claude Code, run:

```
/work-log
```

The skill will:
1. Extract session data from Claude Code JSONL files and (if present) Codex SQLite
2. Cluster sessions by topic
3. Generate a styled DOCX with Garamond font and "List Table 1 Light" table style

## Requirements

- Python 3
- `python-docx` (auto-installed if missing)

## Data Sources

- **Claude Code**: `~/.claude/projects/<project-path>/*.jsonl`
- **Codex CLI**: `~/.codex/state_5.sqlite` + rollout JSONL files
