# ADR-001: Programm-Update per Knopf über Codeberg-Releases

**Status:** Accepted (umgesetzt in v0.1.0, Commit `cc91a37`)
**Datum:** 13.11.2026
**Deciders:** Ralf

## Context

Evel • Rote Fäden (Story_world) wird als ZIP von Codeberg (`gogomann/evel-rote-faeden`) verteilt und lokal betrieben: Python ≥ 3.9, nur Standardbibliothek, SQLite, Weboberfläche auf `127.0.0.1:8765`, Start per `.command` (macOS) bzw. `.bat` (Windows).

Rahmenbedingungen:

- Zielnutzer haben **null Programmierkenntnisse**. Installation und Updates müssen ohne Terminal, Git oder Paketmanager gehen.
- **Programm und Nutzerdaten liegen im selben Ordner** (`welten/`, `exporte/`, `profile_texte/`, `story_world.*.json`, `*.sqlite3`). Ein Update darf Daten nie anfassen.
- Grundsatz **„nichts löschen“**: Ersetztes wandert nach `_old/`.
- **Mac und Windows** sollen gleichermaßen funktionieren.
- Schemaänderungen laufen über vorwärtsgerichtete Migrationen (`PRAGMA user_version`) mit automatischer Sicherung beim Öffnen einer Welt.
- Ein Ein-Personen-Projekt ohne Budget für Code-Signing oder Build-Infrastruktur.

## Decision

Die App aktualisiert sich selbst über **Einstellungen → Update** (zusätzlich per CLI `python3 -m story_world update`):

1. **Prüfen:** Codeberg-API `releases/latest`, ersatzweise der höchste Tag `vX.Y.Z`. Beim Start erfolgt höchstens alle 20 h eine stille Prüfung (abschaltbar).
2. **Laden:** Release-ZIP nach `_update/` (nur von Codeberg-URLs, TLS, max. 200 MB).
3. **Entpacken:** in ein Staging-Verzeichnis, ohne absolute Pfade, `..` oder Symlinks. Die `__version__` im Paket muss zum Release-Tag passen und neuer sein als die installierte Version.
4. **Installieren:** Nur geänderte Programmdateien werden ersetzt (`.update-tmp` + `os.replace`). Alte und entfallene Dateien wandern nach `_old/update-<alt>-nach-<neu>-<zeit>/`. Geschützte Pfade (Deny-List) werden nie berührt. Bei einer Exception läuft ein Rollback.
5. **Neustart:** auf Mac/Linux per Knopf (`os.execv`), auf Windows durch Schließen und neu Starten. Install und Neustart sind gesperrt, solange KI-Aufträge laufen.
6. **Nach dem Neustart:** Ein Hinweis zeigt die Abschnitte aus `AENDERUNGEN.md` und die erfolgten Migrationen.
7. Ein **Entwicklerordner mit `.git/`** wird nie überschrieben. Dort gilt `git pull`.
8. **Fallback:** Ein neues ZIP lässt sich weiterhin manuell in denselben Ordner entpacken, weil das ZIP keine Daten enthält.

## Options Considered

### Option A: Self-Updater in der App über Codeberg-Releases (gewählt)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Mittel: ca. 440 Zeilen `update.py`, Tests vorhanden |
| Cost | 0 € |
| Scalability | Ausreichend: anonyme API-Abfrage max. 1×/20 h je Installation |
| Team familiarity | Hoch: reines Python, bestehender Stack |

**Pros:** ein Klick für Laien; keine zusätzlichen Abhängigkeiten; dateigenaue Sicherung in `_old/`; Daten sind geschützt; Changelog in der App; funktioniert auf Mac und Windows.
**Cons:** Integrität hängt allein an TLS + Codeberg-Konto; kein atomarer Austausch; kein Rückweg per Knopf; Windows ohne Auto-Neustart.

### Option B: Nur manuelles ZIP (Status vor v0.1.0)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Niedrig |
| Cost | 0 € |
| Scalability | Skaliert nicht mit der Nutzerzahl (Support-Aufwand) |
| Team familiarity | Hoch |

**Pros:** kein Code; volle Kontrolle beim Nutzer.
**Cons:** Laien entpacken oft in den falschen Ordner oder überschreiben/duplizieren ihn; keine Sicherung alter Dateien; niemand erfährt, dass es ein Update gibt.

### Option C: Git-basiert (`git pull` per Knopf)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Niedrig im Code, hoch in der Installation |
| Cost | 0 € |
| Scalability | Gut |
| Team familiarity | Hoch |

**Pros:** echte Versionierung, triviales Zurückrollen.
**Cons:** Git ist auf Windows nicht vorhanden und auf macOS erst nach der Xcode-CLT-Installation; Merge-Konflikte sind für Laien unlösbar; scheitert damit an der Kernanforderung.

### Option D: Native App (PyInstaller/Briefcase + Sparkle/WinSparkle)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Hoch: Build-Pipeline je OS, Notarisierung |
| Cost | Apple Developer Program + Windows-Code-Signing-Zertifikat, jährlich |
| Scalability | Sehr gut |
| Team familiarity | Gering |

**Pros:** kein vorinstalliertes Python nötig; signierte Updates; vertrautes App-Verhalten.
**Cons:** hoher Dauer-Aufwand für ein Ein-Personen-Projekt; ohne Signatur blockieren Gatekeeper und SmartScreen; Daten müssten in Nutzerverzeichnisse umziehen.

## Trade-off Analysis

- **Einfachheit für Laien vs. Integritätsschutz:** Option A vertraut TLS und dem Codeberg-Konto. Wer das Konto übernimmt, kann Code auf alle Installationen ausrollen. Echte Signaturen (Ed25519) sind mit der reinen Standardbibliothek nicht umsetzbar, eine Prüfsumme in den Release-Notizen hätte denselben Vertrauensanker. Bei kleiner Nutzerzahl ist das akzeptiert. Gegenmaßnahme: 2FA auf dem Codeberg-Konto.
- **Dateiweiser Austausch vs. Verzeichnis-Swap:** Der dateiweise Austausch minimiert Änderungen und hält `_old/` klein. Der Rollback greift aber nur bei einer Exception. Stürzt der Prozess mitten im Kopieren ab (Stromausfall, Kill), bleibt ein Mischstand ohne Erkennung zurück. Startet die App dann nicht mehr, ist der Update-Knopf unerreichbar. Ein Swap von `story_world/` per zwei Renames wäre nahezu atomar.
- **Vorwärts-Migrationen vs. Downgrade:** Weil Migrationen das Schema nur vorwärts ändern, reicht das Zurückkopieren aus `_old/` allein nicht. Eine ältere Programmversion trifft dann auf ein neueres Schema. Ein Rückweg müsste die Migrations-Sicherungen der Welten mit einbeziehen.
- **Deny-List für Nutzerdaten:** Das Risiko ist gering, weil nur Dateien aus dem Paket bzw. dem Manifest angefasst werden. Alle aktuellen Datenpfade (`welten`, `exporte`, `profile_texte`, `story_world.*.json`, `*.sqlite3`) sind abgedeckt. Neue Datenpfade müssen aber bewusst in `PROTECTED_*` aufgenommen werden.

## Consequences

**Wird einfacher:**
- Updates für Nutzer ohne Technikwissen: ein Klick, dann Neustart.
- Veröffentlichen: `__version__` erhöhen, `AENDERUNGEN.md` ergänzen, Tag + Release auf Codeberg (siehe `BETRIEB.md`).
- Nachvollziehbarkeit: `_update/installiert.json`, `_update/manifest.json` und `_old/update-…`.

**Wird schwieriger / ist Pflicht:**
- Tag und `__version__` müssen exakt übereinstimmen, sonst bricht das Update ab (gewollt).
- Schemaänderungen nur als neue Migration, nie bestehende ändern.
- Das Release-ZIP darf nie Nutzerdaten enthalten.
- Der MCP-Server in Claude Desktop nutzt den neuen Stand erst nach einem Neustart von Claude.

**Später erneut prüfen:**
- Unterbrochene Installation: Erkennung und automatische Reparatur beim Start.
- Rückweg zur Vorversion (inkl. Schema).
- Mindest-Python-Version: Ein Paket, das ein neueres Python braucht, wird derzeit ohne Prüfung installiert und startet danach nicht.
- Windows: Ersetzen der gerade laufenden `Story World starten.bat`. Ich bin mir nicht sicher, ob das praktisch Probleme macht: `cmd.exe` liest Batch-Dateien zeilenweise per Byte-Offset neu ein und könnte nach Strg+C → „N“ in der neuen Datei an falscher Stelle weiterlesen. Auf macOS ist das unkritisch, weil `os.replace` eine neue Inode anlegt und bash die alte offen hält.
- Wechsel auf Option D, falls die Nutzerzahl deutlich wächst oder Python-Installation zur Hürde wird.

## Action Items

1. [ ] 2FA auf dem Codeberg-Konto `gogomann` aktivieren bzw. bestätigen.
2. [ ] Journal-Marker: vor dem ersten Kopiervorgang `_update/laufend.json` (von/nach/Liste) schreiben und nach Erfolg entfernen. Beim Start: Marker vorhanden → Rollback aus `_old/…` und Hinweis in der UI. Die Prüfung gehört in die Start-Skripte oder in ein minimales Modul, das selbst nicht per Update ersetzt wird.
3. [ ] Mindest-Python im Paket hinterlegen (z. B. `__min_python__` in `__init__.py`) und vor der Installation gegen `sys.version_info` prüfen.
4. [ ] Notfall-Rückweg: `python3 -m story_world update --zurueck` stellt den letzten Stand aus `_old/update-…` wieder her und nennt die Migrations-Sicherungen der betroffenen Welten. Mindestens als Anleitung in `BETRIEB.md`.
5. [ ] Windows-Test: Update bei laufender `.bat`, danach Strg+C → „N“. Bei Problemen die `.bat` vom Austausch ausnehmen und erst beim nächsten Start ersetzen.
6. [ ] Erstes echtes Update 0.1.0 → 0.2.0 auf einem frischen ZIP-Stand durchspielen (Mac und Windows), inkl. Schemamigration einer Welt.
