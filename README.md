# work-log

A Claude Code skill that documents LLM-assisted coding as a LaTeX table, intended as an appendix for academic work that requires documentation of AI usage.

When AI is used in an academic context, its exact usage must be documented. The common approach, appending the full prompt and chat history, does not work well with coding agents like Claude Code or Codex, whose output is voluminous and mostly irrelevant for this purpose. This skill lists the **intentions** of the researcher instead: the goals pursued with the agent that ended in at least one git commit. An intention may span several sessions or occupy only part of one.

| Nr. | Zeitraum | Intention | Modell | Modus | Umfang | Commits |
|-----|----------|-----------|--------|-------|--------|---------|

- **Zeitraum**: first to last day of work on the intention, e.g. "22.–23.3.2026"
- **Intention**: the goal, phrased in the past tense from the researcher's side, e.g. "Undo und Redo im Editor ermöglicht"
- **Modell**: the models that did the work, e.g. "Opus 4.6"
- **Modus**: *dialogisch* (back and forth), *autonom* (at least 25 tool calls per prompt) or *explorativ* (under 5 % of tool calls edit files)
- **Umfang**: active time, e.g. "~30 min". Pauses of five minutes or more are not counted.
- **Commits**: short hashes of the commits that realized the intention

Rows are sorted by active time. Where Zeitraum, Modell, Modus or Commits repeat the row above, the cell is left empty so that the two read as one. Commits from sessions whose transcripts Claude Code has already deleted can be listed in a separate block, reconstructed from the commit messages.

## How it works

1. **Harvest.** All local Claude Code transcripts (every project directory, subagents included), Codex sessions and Claude Code cloud sessions are reduced to turns: one prompt of the researcher and the work until the next one. Only the prompts, timestamps, reply sizes and tool-call inputs are read, never tool output or reply text. Results are cached in `~/.cache/work-log/`.
2. **Link.** Each `git commit` the agent ran is matched against the history of the repositories in scope by subject and author date, which survive renamed folders, rebases and squash merges. Commits made by hand are matched by time and edited files.
3. **Dossier.** The sessions in scope are written out as sequences of prompts with the commits they led to.
4. **Intentions.** Claude reads the dossier and groups turns into intentions (the guidance is in `SKILL.md`).
5. **Render.** Periods, active time, models and modes are computed from the turns each intention names, and the table is written as LaTeX.

Identifying intentions remains a judgement. The period and active time are computed, but they rest on that grouping.

## Installation

```bash
git clone https://github.com/pfefferniels/work-log.git
ln -s "$(pwd)/work-log" ~/.claude/skills/work-log
```

## Usage

In Claude Code, inside the repository to document:

```
/work-log
```

The result is `arbeitsverlauf.tex`, a fragment for `\input` that needs `\usepackage{booktabs,longtable,array}`. The skill can also cover several repositories, or every repository you have worked in.

The scripts can be run directly:

```bash
python3 worklog.py dossier --repo ~/Projects/a --repo ~/Projects/b --name "Dissertation"
python3 worklog.py render ~/.cache/work-log/runs/Dissertation --output arbeitsverlauf.tex
```

## Publishing the prompts

The prompts themselves can be published alongside the table, for instance in a repository of their own:

```bash
python3 worklog.py prompts --repo ~/Projects/a --out ~/Projects/prompts
```

This writes one Markdown file per day into a folder named after the scope. Each prompt appears in full. The reply is left out, and the figures of the turn stand in for it: active time, tool calls, file edits and output tokens, with thinking tokens where the transcript records them.

Prompts are often dictated or typed in haste. A small model (Haiku 5.5 by default) turns them into a clean reading text: it corrects misspellings, dictation errors, faulty grammar and punctuation, writes out colloquial contractions, and omits interjections, exclamations of frustration and emoticons. The script admits only small, local corrections of words that occur in the prompt (at most four words replaced and two added, in order), so that no correction rewords a passage, and an omission only when every omitted word is such an exclamation. Corrected or added words and punctuation marks stand in square brackets, and omissions are marked with `[...]`. Admitted changes are kept in `emendations.json` in the output directory, which records the original reading of every bracketed passage and every omission. A passage goes to the model again only when these rules change (`RULES` in `emendation.py`), so a later run otherwise leaves published text unchanged. To reject a correction, delete it from its entry and run again.

Pasted passages are recognized through Claude Code's prompt history (`~/.claude/history.jsonl`), which marks pastes of several lines. They are shown collapsed and never corrected. Shorter pastes leave no trace there and are treated as typed.

If the output directory has no `README.md`, one stating these editorial principles is written. The model reads each passage without the rest of the session, so its corrections deserve a look before publication.

## Cloud sessions

Cloud sessions are read from an undocumented beta API (see `cloud-sessions-api.md`) with the OAuth token Claude Code keeps in the macOS keychain. Claude Code's auto mode blocks such access by default. To allow it for this skill, add a rule to `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": ["Bash(python3 ~/.claude/skills/work-log/worklog.py:*)"]
  }
}
```

Without it, run the dossier with `--no-cloud`.

## Preserving session files

Claude Code deletes transcripts after 30 days by default. To keep them, add to `~/.claude/settings.json`:

```json
{
  "cleanupPeriodDays": 99999
}
```

## Requirements

- Python 3.11 or later, git, macOS (for the keychain; the local sources work elsewhere)
- A LaTeX installation with `booktabs`, `longtable` and `array` to typeset the table
