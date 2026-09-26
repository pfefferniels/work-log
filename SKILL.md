---
name: work-log
description: Document LLM-assisted coding as the researcher's intentions that led to git commits, rendered as a LaTeX table
---

The work log documents AI use in research code as a list of **intentions**: goals the researcher pursued with a coding agent that ended in at least one git commit. Each row names one intention, its period, the model, the mode and active time of the work, and the commits that realized it.

The sources are every local Claude Code transcript (all project directories, subagents included), Codex sessions, and Claude Code cloud sessions. Only the researcher's prompts, timestamps, reply sizes and tool-call inputs are read, never tool output or reply text. Sessions are tied to commits by commit subject and author date, not by directory, so renamed project folders and code moved between repositories are handled.

## 1. Build the dossier

The scope is the repository of the current working directory unless the user names others. Fetch first, so that commits made in cloud sessions are visible locally:

```
git -C <repo> fetch --all --quiet
python3 ~/.claude/skills/work-log/worklog.py dossier [--repo PATH ...] [--all] [--name NAME] [--since YYYY-MM-DD]
```

- `--repo` is repeatable; `--all` takes every repository a session ever ran in.
- `--name` sets the project name in the heading (default: the repository names).
- The first run parses all transcripts (about 20 s for 12 GB); later runs reuse a cache in `~/.cache/work-log/`.
- If the command is denied because it reads the Claude Code OAuth token from the keychain (needed for cloud sessions), run it again with `--no-cloud` and tell the user which permission rule would allow it (see README).

The command prints the paths of `overview.md` and `part-NN.md` in its run directory. The overview lists the scope, how many commits were linked to sessions and how, notes about skipped sources, deleted transcripts, and the commits that might stem from them. Each part lists sessions chronologically: every turn (one prompt of the researcher and the work until the next) with its label, time, tool calls, edits, output tokens, the prompt, and the commits it produced.

## 2. Identify the intentions

Read the overview, then every part. With more than one part, give each part to a subagent in parallel, pasting this section ("Identify the intentions") into its instructions, and ask for draft intentions in the JSON format below plus a note on intentions that seem to continue into a neighbouring part. Then merge the drafts yourself: join drafts that pursue the same goal across part boundaries, and even out granularity and wording.

### What counts as an intention

An intention is a goal the researcher pursued with the agent, as they would explain it to a colleague: "Ich wollte …". Read it off the prompts. What the model did and what the commit messages say help to name it, but they are evidence, not the unit.

List an intention only if at least one of its turns produced a commit in scope. Conversations that ended without a commit are left out, unless they were the early part of an intention that later led to one; then their turns join that intention.

### Granularity

Aim for the level at which the researcher decided what to work on next.

- A new intention begins when the researcher turns to a goal that would make sense on its own, even had the previous one never been pursued. Corrections, follow-up requests, fixes of what was just built, reviews, tests and "commit and push" belong to the intention they serve.
- An intention can span sessions. Merge when a later session continues the same goal: an explicit continuation ("weiter mit", "continue", "as discussed"), the same issue or feature named, a plan made in one session and carried out in another, parallel sessions or agents working on parts of one goal. Sessions marked "no commit in scope" join an intention only when they clearly pursue it.
- An intention can take up part of a session. Long sessions often hold several; split where the goal changes.
- Too coarse: the phrase could be a project title ("mpm-desk weiterentwickeln"), or it needs "und" to join goals that are unrelated.
- Too fine: the phrase names one step of a larger goal ("Button-Farbe anpassen" within a UI rework), unless that step was all the researcher wanted at the time.
- Issue bullets and numbered tasks are separate intentions when each is a goal of its own, and one intention when they are steps toward one result.
- Housekeeping (renaming, README, dependency updates, merges) joins the intention it served. It stands alone only when the researcher pursued it for its own sake; related chores then share one row ("Skill veröffentlicht und eingerichtet").
- A commit may appear in several intentions when it bundles their results, which is common when a session ends with one "commit and push". Each turn belongs to one intention. A turn that genuinely served two may be listed in both, and its time is split between them.
- Turns that belong to no intention (unrelated questions, abandoned attempts) are simply not assigned.

As a rough calibration, an intention spans a few to a few dozen turns and one to a handful of commits. A row with dozens of commits or a single short turn deserves a second look, though neither is wrong in itself.

### Wording

German, in the past tense as a participle phrase of 3–10 words, stating the goal from the researcher's side, not what the model did. Every listed intention led to a commit, so the past form fits. Verb-centred, no Nominalstil. Technical terms may stay English. Examples: "Undo und Redo im Editor ermöglicht", "Kontinuierliche Pedaldaten im Alignment berücksichtigt", "Abbildung zur Rollenproduktion nach neuer Vorlage umgesetzt".

### Reconstructed intentions

If the overview lists deleted transcripts together with commits made in that period, group those commits by the goal their subjects suggest and add them as intentions with `"reconstructed": true` and no turns. Their period becomes "vor dem" plus the date of their earliest commit; model and extent stay empty.

### Format

Write `intentions.json` into the run directory:

```json
{"intentions": [
  {"intention": "Undo und Redo im Editor ermöglicht", "turns": ["S12.3-9", "S15"], "commits": ["4f2a9c1", "9b1e0d2"]},
  {"intention": "Tempokurven aus MIDI-Dateien abgeleitet", "turns": ["S20.1-4"], "commits": ["a1b2c3d"], "mode": "explorativ"},
  {"intention": "Regionen per Drag & Drop verschiebbar gemacht", "reconstructed": true, "commits": ["7a9e8f4", "41de2f9"]}
]}
```

Turns are referenced as `S12` (whole session), `S12.3` (one turn) or `S12.3-9` (a range). Commits are the short hashes from the dossier.

The renderer computes the mode from the turns: **autonom** at 25 or more tool calls per prompt, **explorativ** when fewer than 5 % of tool calls edit files, **dialogisch** otherwise. Set `mode` only when the prompts clearly contradict the computed one.

## 3. Render

```
python3 ~/.claude/skills/work-log/worklog.py render <run-dir> --output <project-root>/arbeitsverlauf.tex
```

- If it reports problems in `intentions.json`, fix them and render again.
- Every warning about a linked commit in no intention needs a decision: assign the commit, or leave it out only when the linked turn clearly did not contribute (e.g. a match by edited files that is a coincidence).
- If `pdflatex` is available, render once more with `--standalone --output <run-dir>/preview.tex` and compile it there to check that the table sets without errors.

The output is a fragment for `\input` into a thesis and needs `\usepackage{booktabs,longtable,array}`. Rows are ordered by active time, reconstructed rows last. Where Zeitraum, Modell, Modus or Commits repeat the row above, the cell stays empty so that both read as one.

Finally tell the user the output path, the number of intentions and the period, and anything left out: skipped sources, linked commits not assigned, and how many commits in scope had no session.
