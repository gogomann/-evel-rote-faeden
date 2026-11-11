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

## Fehlersuche
- **KI-Läufe**: jeder Auftrag mit Weg, Modell, Ausweich-Modellen, Fehlern (Rohantwort nur mit Backstage).
- **Prüfung**: Lücken und automatische Konsistenzprüfung (zwei Orte gleichzeitig, Reisezeit, tote Figuren).
- **Protokoll**: jede Änderung mit Herkunft (du, KI, System).
- Server-Log beim Start per Doppelklick im Terminalfenster, sonst `/tmp/story_world.log`.

## Tests
`python3 -m unittest discover -s tests -v` – laufen ohne Netz und ohne echte KI (simulierte Anbieter).
