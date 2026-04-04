# work-log

A Claude Code skill that summarizes LLM coding sessions (Claude Code + Codex) into a topic-oriented Word document, suitable as an appendix for academic work that requires documentation of AI usage.

When AI is used in an academic context, its exact usage must be documented. The common approach — appending the full prompt and chat history — doesn't work well with coding agents like Claude Code or Codex, where outputs are voluminous and not every message is relevant. This skill solves that by summarizing all sessions into a compact table grouped by topic.

The generated Word document contains the following columns:

| Nr. | Datum | Modell | Modus und Umfang | Commits |
|-----|-------|--------|------------------|---------|

- **Datum**: Single date or range (e.g. "22.–23.03.2026")
- **Modell**: The language model used (e.g. "Opus 4.6" or "GPT-5.3")
- **Modus und Umfang**: Active working time and interaction mode (e.g. "autonom, ~30 min"). The three modes are: *dialogisch* (back-and-forth, user steering), *autonom* (model works independently), *explorativ* (reading/searching, no changes). Pauses over 5 minutes are excluded.
- **Commits**: Short topic line (3–5 words, derived from commit messages) and associated commit hashes.

Entries are sorted by descending active time.

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

## Note: Preserving session files

Claude Code deletes session JSONL files after 30 days by default. To keep them indefinitely, add to `~/.claude/settings.json`:

```json
{
  "cleanupPeriodDays": 99999
}
```

## Requirements

- Python 3
- `python-docx` (auto-installed if missing)
