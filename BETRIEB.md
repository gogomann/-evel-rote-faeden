# Betrieb

## Starten
- Doppelklick auf `Story World starten.command` (Mac) / `Story World starten.bat` (Windows) oder `python3 -m story_world` → http://127.0.0.1:8765
- Nur lokal erreichbar (127.0.0.1). Welten, Sicherungen, Hörbücher und Schlüssel liegen im Projektordner und sind per
  `.gitignore` ausgeschlossen – sie enthalten Backstage-Geheimnisse.

## Abendlicher Ablauf
1. **Täglicher Lauf** (Einstellungen → Diese Welt → Täglicher Lauf): zur eingestellten Uhrzeit
   Nachrichten abrufen → als Impulse der Art `nachricht` einarbeiten → nächste Folge erzeugen.
   Jeder Schritt ist gekapselt: Eine kaputte Nachrichtenquelle verhindert die Folge nicht.
2. **Folge hören**: Reiter Folgen → Folge öffnen → „🎧 Hörbuch erzeugen“ (macOS-Stimmen) oder „▶ Vorlesen“.
3. **Freigabe nur gezielt**: Findet der Prüfer schwere Probleme, wartet die Folge auf deine Freigabe
   (Reiter Folgen → „Freigeben“). Sonst läuft alles ohne Rückfrage (OFFENE_PUNKTE.md Nr. 7).
   KI-Vorschläge mit Rückfragen bleiben unter „Vorschläge“ offen.

## Ohne geöffnete Oberfläche (macOS, launchd)
Der eingebaute Zeitplan läuft nur, solange Story World geöffnet ist. Für einen festen Lauf um 20:00 ohne Oberfläche:

```xml
<!-- ~/Library/LaunchAgents/de.storyworld.taeglich.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>de.storyworld.taeglich</string>
  <key>WorkingDirectory</key><string>/PFAD/ZU/Story_world</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>-m</string><string>story_world</string>
    <string>taeglich</string><string>WELT-SLUG</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/tmp/story_world_taeglich.log</string>
  <key>StandardErrorPath</key><string>/tmp/story_world_taeglich.log</string>
</dict></plist>
```
Laden mit `launchctl load ~/Library/LaunchAgents/de.storyworld.taeglich.plist`. Wenn der eingebaute Zeitplan und launchd
beide aktiv sind, verhindert der Datumsvermerk `auto_letzter_lauf` einen zweiten Lauf am selben Tag nur im eingebauten
Zeitplan – also besser nur eins von beiden nutzen.

## Ohne geöffnete Oberfläche (Windows, Aufgabenplanung)
Aufgabenplanung → „Einfache Aufgabe erstellen“ → täglich 20:00 → Programm `py`, Argumente `-3 -m story_world taeglich WELT-SLUG`,
„Starten in“ = Projektordner. Auch hier nur eins von beiden nutzen (eingebauter Zeitplan oder Aufgabenplanung).

## Sicherung und Wiederherstellung
- Vor jeder Schemaänderung automatisch, sonst Einstellungen → Sicherung → „Sicherung jetzt anlegen“ (`welten/backups/`).
- Wiederherstellen: Einstellungen → Sicherung → „Als neue Welt öffnen“. Die aktuelle Welt und die Sicherung bleiben
  unverändert; die wiederhergestellte Welt wird auf Integrität und Fremdschlüssel geprüft.
- Nichts wird gelöscht: Überholtes kommt nach `_old/`, ersetzte Audio-WAVs nach `welten/audio/<welt>/_wav/`,
  entfernte KI-Anbieter ins Archiv der Einstellungen, Nachrichtenquellen werden deaktiviert statt gelöscht.

## Update
- Einstellungen → Update: prüft Codeberg (`releases/latest`, sonst höchster Tag `vX.Y.Z`), zeigt die Release-Notizen,
  lädt das ZIP nach `_update/` und ersetzt nur Programmdateien, die sich geändert haben. Alte Fassungen und entfallene
  Dateien → `_old/update-<alt>-nach-<neu>-<zeit>/`. Nutzerdaten (`welten/`, `exporte/`, `profile_texte/`,
  `story_world.*.json`, `*.sqlite3`) werden nie angefasst. Schlägt etwas fehl, wird der alte Stand wiederhergestellt.
- Während KI-Aufträge laufen, sind Installieren und Neustart gesperrt. Neustart: Mac/Linux per Knopf (Seite lädt von selbst neu),
  Windows: Fenster schließen und neu starten. Der MCP-Server in Claude nutzt den neuen Stand erst nach einem Neustart von Claude.
- Nach dem Neustart zeigt ein Hinweis, was neu ist (`AENDERUNGEN.md`) und welche Welten ein neues Schema bekommen haben.
- Beim Start wird höchstens einmal am Tag still nach Updates gesehen (abschaltbar unter Einstellungen → Update).
- Ein Ordner mit `.git/` (Entwicklerstand) wird nie per Update überschrieben – dort `git pull`.

### Neue Version veröffentlichen
1. `__version__` in `story_world/__init__.py` erhöhen (z. B. `0.2.0`) und in `AENDERUNGEN.md` einen Abschnitt `## 0.2.0 – …` ergänzen.
2. Schemaänderungen nur als neue Migration in `migrations.py` (`LATEST_VERSION` + `_migrate_to_N`), nie bestehende ändern.
3. Committen, Tag setzen und pushen: `git tag v0.2.0 && git push origin main v0.2.0`.
4. Auf Codeberg zum Tag ein Release anlegen; der Beschreibungstext erscheint im Update-Dialog. Tag und `__version__` müssen
   übereinstimmen, sonst bricht das Update ab.

## Export und Umzug
- Einstellungen → Sicherung → „Export & Umzug“: **Welt** (Kanon, Folgen, Nachvollzug, alle genutzten Stimmen mit
  Steckbrief, Reglern, Probe und Maßstab; Texte als Basis nur als Stilanker/Maßstab-Auszug; eingearbeitete
  Text-Abschnitte ohne Inhalt), **Autor** (Erzählprofile, eigene Texte vollständig, alle Stimmen), **Alles**.
- Import legt Welten immer neu an (nichts wird überschrieben). Gleiche Profil-ID → Texte sichtbar; fremde Profil-ID →
  Basis und offene Text-Abschnitte liegen verborgen, die KI nutzt sie trotzdem. Kommt der Mensch später per
  Autor-Import dazu, wird alles sichtbar.
- „Fremder Text“ (Texte als Basis): Text eines anderen Autors – nie Stilprobe, nie Basis einer Stimme.
- Verweist eine Welt auf eine Stimme, die es auf dem Rechner nicht gibt, meldet das Protokoll eine Warnung.

## Fehlersuche
- **KI-Läufe**: jeder Auftrag mit Weg, Modell, Ausweich-Modellen, Fehlern (Rohantwort nur mit Backstage).
- **Prüfung**: Lücken und automatische Konsistenzprüfung (zwei Orte gleichzeitig, Reisezeit, tote Figuren).
- **Protokoll**: jede Änderung mit Herkunft (du, KI, System).
- Server-Log beim Start per Doppelklick im Terminalfenster, sonst `/tmp/story_world.log`.

## Tests
`python3 -m unittest discover -s tests -v` – laufen ohne Netz und ohne echte KI (simulierte Anbieter).
