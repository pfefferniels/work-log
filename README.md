# work-log

Wird Künstliche Intelligenz im wissenschaftlichen Kontext verwendet, so muss ihre genaue Verwendungsweise nachgewiesen werden. Klassischerweise sehen die meisten Regeln vor, dass der genaue Prompt und der gesamte sich daran anschließende Chatverlauf angehängt wird. Diese Vorgehensweise ist allerdings beim Einsatz von Coding-Agenten wie Claude Code oder Codex nicht zielführend, da die Ausgaben in ihrem Umfang einerseits kaum durchschaubar sind und andererseits nicht jede Nachricht in ihrem genauen Wortlaut für die Dokumentation relevant ist. Der vorliegende Skill versucht dieses Problem zu lösen, indem sämtliche Sitzungen thematisch und ihrem Umfang nach tabellarisch zusammengefasst werden. Die so produzierte Übersicht kann anschließend als Referenz wissenschaftlichen Arbeiten angehängt werden.

Der Skill produziert ein Word-Dokument aus den Coding-Sessions, die lokal gefunden wurden (Claude Code und OpenAI Codex). Themen werden sitzungsübergreifend zusammengefasst. Das Word-Dokument enthält folgende Spalten:


| Nr. | Datum | Modell | Modus und Umfang | Commits |
|-----|-------|--------|----------------|---------|

- **Datum**: einzelner Tag oder Zeitraum (z.B. "22.–23.03.2026")
- **Modell**: Das verwendete Sprachmodell (z.B. "Opus 4.6" oder "GPT-5.4")
- **Modus und Umfang**: Aktive Arbeitszeit und Interaktionsmodus (z.B. "iterativ, ~30\u00a0min"). Die vier Modi sind: *dialogisch* (viel Hin und Her), *autonom* (Modell arbeitet selbstständig), *explorativ* (Recherche, keine Änderungen), *iterativ* (wiederholte Versuch-Fehler-Zyklen). Pausen über 5 Minuten werden nicht mitgezählt.
- **Commits**: Kurze Themenzeile (3–5 Wörter, verbal formuliert, aus den Commit-Messages abgeleitet) sowie die zugehörigen Commit-Hashes.

Die Einträge sind nach absteigender Komplexität sortiert.

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

## Hinweis: Session-Dateien aufbewahren

Claude Code löscht JSONL-Sitzungsdateien standardmäßig nach 30 Tagen. Um die Dateien dauerhaft zu behalten, in `~/.claude/settings.json` hinzufügen:

```json
{
  "cleanupPeriodDays": 99999
}
```


## Requirements

- Python 3
- `python-docx` (auto-installed if missing)
