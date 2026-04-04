# work-log

Wird Künstliche Intelligenz im wissenschaftlichen Kontext verwendet, so muss ihre genaue Verwendungsweise nachgewiesen werden. Klassischerweise sehen die meisten Regeln vor, dass der genaue Prompt und der gesamte sich daran anschließende Chatverlauf angehängt wird. Diese Vorgehensweise ist allerdings beim Einsatz von Coding-Agenten wie Claude Code oder Codex nicht zielführend, da die Ausgaben in ihrem Umfang einerseits kaum durchschaubar sind und andererseits nicht jede Nachricht in ihrem genauen Wortlaut für die Dokumentation relevant ist. Der vorliegende Skill versucht dieses Problem zu lösen, indem sämtliche Sitzungen thematisch und ihrem Umfang nach tabellarisch zusammengefasst werden. Die so produzierte Übersicht kann anschließend als Referenz wissenschaftlichen Arbeiten angehängt werden.

Der Skill produziert ein Word-Dokument aus den Coding-Sessions, die lokal gefunden wurden (Claude Code und OpenAI Codex). Themen werden sitzungsübergreifend zusammengefasst. Das Word-Dokument enthält folgende Spalten:


| Nr. | Datum | Modell | Umfang (Nachr. / Tokens) | Zusammenfassung |
|-----|-------|--------|--------------------------|-----------------|

- **Datum**: einzelner Tag oder Zeitraum (z.B. "22.–23.03.2026")
- **Modell**: Das verwendete Sprachmodell (z.B. "Opus 4.6" oder "GPT-5.4")
- **Umfang**: Anzahl der Nachrichten sowie der verwendeten Tokens (e.g. "8 / ~45k"). Dadurch soll die Komplexität und das "Hin- und Her" einer Sitzung beschrieben werden.
- **Zusammenfassung**. Bei komplexeren Bearbeitungen kann noch eine kleine Notiz hinzugefügt werden.

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

## Requirements

- Python 3
- `python-docx` (auto-installed if missing)


