# Evel • Rote Fäden – fortlaufende Sci-Fi-Welt (Hörbuch/Lesestoff)

## Ziel
Ein automatisiertes System erzeugt täglich neue Folgen einer zusammenhängenden
Sci-Fi-Welt mit Menschen und außerirdischen Völkern. Verschiedene LLM-Anbieter
dürfen schreiben, ohne dass Leser/Hörer Stilbrüche merken.

## Rolle des Nutzers
- Nutzer ist **nur Hörer/Leser**, kein Autor. Er will überrascht werden.
- Er legt nur den Rahmen fest (Genre, Ton, No-Gos) und gibt gelegentlich Wünsche ab.
- Backstage-Daten (Rätsel, Wahrheiten) sind für den Nutzer standardmäßig verborgen (Spoilerschutz).

## Dateien
- WELT_REGELN.md: Physik, Kalender, Völker
- ERZAEHLREGELN.md: Erzählregeln (Zweck, Zeit/Perspektive, Technik & Phänomene, Nachrichten)
- ZEIT_UND_STRAENGE.md: Zeitachsen, Ebenen, Ripples
- PIPELINE.md: Agenten und täglicher Ablauf
- BETRIEB.md: Betrieb, Zeitplan, Sicherung, Fehlersuche
- DATENMODELL.md: Datenbank
- HOERBUCH.md: Audio-Produktion
- OFFENE_PUNKTE.md: ungeklärte Fragen
- prozess.html: interaktive Übersicht, wie eine Folge entsteht (im Browser öffnen)

## Auftrag an die PC-KI
1. Alle Dateien lesen.
2. Umsetzungsplan mit Meilensteinen erstellen (MVP zuerst).
3. Tech-Stack bestätigen oder begründet ändern.
4. Rückfragen nur zu OFFENE_PUNKTE.md stellen. Nichts dazuerfinden, was hier fixiert ist

## Installation auf einem neuen Rechner (Mac oder Windows)

Evel • Rote Fäden braucht nur **Python 3.9 oder neuer** – keine Zusatzpakete, keine Datenbank-Installation, kein Docker.

1. **Python**: Mac – `python3 --version` im Terminal; fehlt es, bietet macOS die Installation an (oder python.org).
   Windows – von https://www.python.org/downloads/ installieren, dabei **„Add python.exe to PATH“** ankreuzen.
2. **Evel • Rote Fäden holen**: `git clone https://codeberg.org/gogomann/evel-rote-faeden.git` oder auf Codeberg als ZIP herunterladen und entpacken.
3. **Starten**: Mac – Doppelklick auf `Story World starten.command` (beim ersten Mal ggf. Rechtsklick → Öffnen).
   Windows – Doppelklick auf `Story World starten.bat`. Der Browser öffnet http://127.0.0.1:8765.
4. **Einrichten**: Welt anlegen, unter Einstellungen einen KI-Anbieter eintragen (siehe „KI einrichten“).

Beim ersten Start entstehen im Projektordner automatisch `welten/` sowie die lokalen Dateien für Einstellungen,
Profile und Qualität. Sie gehören nur diesem Rechner und sind per `.gitignore` vom Repository ausgeschlossen.
**Umzug mit Daten**: Einstellungen → Sicherung → „Export & Umzug“. Erst den **Autor** exportieren (Erzählprofile,
eigene Texte, Stimmen), dann die **Welten** – oder „Alles“. Auf dem neuen Rechner in derselben Reihenfolge importieren.
Ein Welt-Export bringt alle Stimmen der Welt mit; Texte als Basis sind dort nur als Auszüge enthalten und bleiben
verborgen, wenn der Mensch (Profil-ID) auf dem Zielrechner nicht bekannt ist. Exporte liegen in `exporte/`.
Alternativ von Hand: `welten/`, `story_world.config.json`, `story_world.profiles.json`, `story_world.stimmen.json`,
`profile_texte/` und `story_world.qualitaet.sqlite3` in die neue Installation legen.

| Funktion | Mac | Windows |
|---|---|---|
| Oberfläche, Welten, KI-Anbieter, Folgen, MCP | ✓ | ✓ |
| Hörbuch über TTS-Server (WAV) | ✓ | ✓ |
| „▶ Vorlesen“ im Browser | ✓ | ✓ |
| „🎧 Hörbuch erzeugen“ mit Systemstimmen (`say`/`afconvert`) | ✓ | – (Knopf meldet das; TTS-Server nutzen) |
| Import .rtf | ✓ (textutil) | ✓ (einfacher eingebauter Leser) |
| Import .pdf | mit `pdftotext` (brew install poppler) | mit `pdftotext` (poppler, im PATH) |

## Starten

Nur Python 3.9+ nötig, keine Zusatzpakete. (Windows: `py -3` statt `python3`.)

```bash
python3 -m story_world            # Oberfläche auf http://127.0.0.1:8765 (öffnet den Browser)
python3 -m unittest discover -s tests -v
```

Oder per Doppelklick auf `Story World starten.command` (Mac) bzw. `Story World starten.bat` (Windows). Läuft Evel • Rote Fäden schon, öffnet ein zweiter Start nur den Browser. Weitere Befehle: `python3 -m story_world neu "Name"` (Welt per Kommandozeile), `python3 -m story_world migrate datei.sqlite3`
(ältere Datenbank auf aktuelles Schema bringen, mit automatischer Sicherung), `python3 -m story_world ui --port 8800 --kein-browser`.

### KI einrichten
Alles in der Oberfläche unter **Einstellungen** – nichts von Hand in Dateien:
1. **KI-Anbieter → „+ Anbieter hinzufügen“**: Vorauswahl für OpenRouter, OpenAI, Anthropic, Google Gemini, Mistral, Groq,
   DeepSeek, xAI, Together, Ollama (lokal), LM Studio (lokal) oder ein eigenes OpenAI-kompatibles Gateway (z. B. LiteLLM).
   Jede Vorauswahl bringt Adresse und Kurzanleitung mit. Beliebig viele Anbieter möglich.
2. Schlüssel einfügen → **„Speichern & prüfen“** → **„Modelle laden“**. Modelle werden vom Anbieter geholt; von Hand ergänzen nur im Ausnahmefall.
3. **Modelle je Aufgabe**: pro Aufgabe (Standard, Weltenbau, Lücken, Einschübe, später Autor/Prüfer/Lektor) eine 1., 2. und 3. Wahl –
   auch über Anbieter hinweg. Fällt die 1. Wahl aus, springt automatisch die nächste ein. „Testen“ zeigt, welches Modell antwortet.

Schlüssel liegen nur lokal in `story_world.config.json` (Dateirechte 0600, per .gitignore ausgeschlossen) und werden in der
Oberfläche nie vollständig angezeigt. Entfernte Anbieter landen im Archiv und lassen sich wiederherstellen.
Für Skripte/CI gibt es weiterhin `STORY_LLM_BASE_URL`, `STORY_LLM_MODEL`, `STORY_LLM_API_KEY` (erscheint als Anbieter „Umgebungsvariablen“).

### Folgen und eigenständige Geschichten
Reiter **Geschichten** → bestehende Geschichte weitererzählen, neue Geschichte in einem Genre beginnen oder „Planer entscheidet“;
dazu Wunsch, Länge, Altersfreigabe (legst du fest, die Genre-Vorgabe steht nur als Info daneben), Stimme und **Form**:
- **Folge der Reihe**: knüpft an die vorige Folge an, endet mit Ruhepunkt und Überleitung.
- **Eigenständige Geschichte**: für Hörer, die die Welt nicht kennen – Entrée nur mit den Weltdetails, die diese Geschichte
  braucht (der Planer legt sie im Feld `entree` fest), keine Anspielungen auf Vorwissen, geschlossenes Ende ohne Überleitung.
  Der Prüfer meldet Unverständliches als „Neuling:“. Die Geschichte wird trotzdem wie jede Folge in den Kanon eingetragen.

Die Pipeline:
**Planer** (Strang, Zeit, Figuren, Kapitel; legt Fehlendes selbst an) → **Autor** (Kapitel für Kapitel) →
**Kontinuitätsprüfer** → **Lektor** → **Archivar** (Zusammenfassung, Zeit-Cursor, neue Fakten in den Kanon).
Der Text steht im Format `[Erzähler] …` / `[Name] …` – direkt nutzbar fürs Hörbuch („Als Text für das Audiobook Studio“).
Die Leseansicht kann mit den Systemstimmen vorlesen. Modelle je Schritt unter Einstellungen → Modelle je Aufgabe.
Standard-Länge (Einstellungen → Diese Welt): 8000 Wörter ≈ 60 Minuten. Scheitern Prüfer, Lektor oder Archivar,
bleibt die Folge trotzdem erhalten; bricht der Autor ab, wird der bisherige Text als Entwurf gesichert.

### Schreibstil (Stimmen)
Reiter **Schreibstil**: Eine **Stimme** ist der virtuelle Autor einer Folge – „schreibt wie Stanisław Lem“ (bekannter Autor,
nur Stilbeschreibung, nie Originaltext), „schreibt wie Ralf“ (eigene Texte als Basis, kurze Auszüge als Stilanker) oder frei
beschrieben. Die KI erstellt daraus einen **Stil-Steckbrief** (11 Felder, alles änderbar); **Regler** (Satzlänge, Bildsprache,
Dialoganteil, Humor, Tempo, Nähe zum Vorbild) und verbindliche **Hinweise** justieren ihn. Eine **Probe** zeigt die Stimme in
einer kurzen Szene der Welt, lässt sich als Hörbuch mit einer TTS-Stimme vorlesen und wird nach Freigabe zum Stilanker und
messbaren Maßstab.
- Gilt für Folge, Geschichte oder Welt – Vorrang in dieser Reihenfolge. Stimmen liegen außerhalb der Welten in
  `story_world.stimmen.json` (nicht in Git) und sind in jeder Welt nutzbar.
- Ein gemeinsamer Maßstab für alle Rollen: Planer, Autor und Lektor schreiben nach dem Steckbrief, der Prüfer prüft dagegen
  (inkl. Messwerten) und meldet „Stil:“-Befunde, die Stil-Messung vergleicht mit den eigenen Texten bzw. der freigegebenen Probe.
- Ist eine Stimme gesetzt, liefert das Erzählprofil nur noch Publikum, Genres und Tabus.
- Feinjustieren gehört dazu: Ein zu eng formulierter Steckbrief klingt hölzern – Regler, Hinweise und Probe sind dafür da.

### Menschen, Erzählprofil und Genres

- **Deine Seite** (👤 oben rechts): Einschätzung der KI (Erzählprofil), die Befragung und deine **Texte als Basis**.
  Texte einfügen oder hochladen (txt, md, html, docx, odt, epub, rtf, pdf mit `pdftotext`). Als Stilprobe markiert, prägen
  sie das Erzählprofil; „In Welt einlesen“ macht daraus abschnittsweise Kanon-Vorschläge für eine Welt. Texte anderer Autoren
  als **„fremder Text“** markieren – sie sind nie Stilprobe und nie Basis einer Stimme.
- Beim Start fragt Evel • Rote Fäden, wer gerade bedient (kein Login): bekannte Menschen mit „zuletzt genutzt“ oder „Neuer Mensch“.
- Neue Menschen führen ein kurzes Interview (12 indirekte Fragen, Stilproben). Die KI verdichtet es zum **Erzählprofil**
  (Stimme, Rhythmus, Humor, Motive, Werte, innere Motivation, Tabus) und stellt gezielte Nachfragen. Alles änderbar unter
  Einstellungen → Menschen & Profile. Gespeichert nur lokal in `story_world.profiles.json` (0600, nicht in Git).
- **Genres** (Welt → Genres) mit Regeln, Spannungsbogen, Ton, Tabus und Altersfreigabe; Vorlagen inkl. „Grusel für Kinder“.
  Genre je Folge, je Strang oder als Standard der Welt. Planer, Autor und Lektor schreiben im Genre und in der Stimme des
  Menschen. Tabu-Verstöße meldet der Prüfer nur als ⚠-Warnung an der Folge (nicht jedes Modell hält sich daran);
  verweigert ein Modell den Text, springt die nächste Wahl unter „Modelle je Aufgabe → Autor“ ein.

### Zeit, Reisen, Prüfung
- **Zeit & Reisen**: Zeitreise-Abfrage (Weltzustand zu einem Zeitpunkt, Kalendernamen statt Zahlen) und Reiserechner.
- **Prüfung**: Lücken + automatische Konsistenzprüfung (zwei Orte gleichzeitig, Reisezeit, tote Figuren).

### Hörbuch und täglicher Lauf
- „🎧 Hörbuch erzeugen“ vertont eine Folge mit den macOS-Stimmen (`say` + `afconvert`, .m4a), Player in der Leseansicht.
  Erzähler-Stimme und Tempo unter Einstellungen → Diese Welt, Figuren-Stimmen am Feld „Stimme (Hörbuch)“,
  Aussprache fremder Namen im Aussprache-Lexikon. Für andere TTS-Systeme: Segmente als JSON exportieren.
- Täglicher Lauf (Nachrichten → Impulse → Folge) und Nachrichtenquellen unter Einstellungen → Diese Welt. Betrieb: BETRIEB.md.

### KI-Läufe
Jeder KI-Auftrag wird dauerhaft in der Welt protokolliert (Reiter **KI-Läufe**): Fortschrittsbalken (auch oben in der Kopfleiste),
der **Auftrag** an die KI, der **Weg** mit Uhrzeit (Kontext, welches Modell, Ausweich bei Fehlern, Prüfung, Übernahme) und das
**Ergebnis**. Die Antwort der KI läuft live mit (Streaming). Live-Antwort, Rohantwort und vollständiger Prompt können
Geheimnisse enthalten und sind nur mit „Backstage“ sichtbar.

**Nachvollzug** (Karte im Lauf, live während des Laufs): je Schritt, welche Gewichtung hineinging (Stimme, Form,
Überraschungsstufe, Genre, Länge, Modelle), welche Frage an die KI ging und was zurückkam, wie bewertet wurde (Regel und
Grenze) und ob durchgelassen ✔, eingegriffen ✋, gewarnt ⚠ oder auf dich gewartet 👤 wurde – z. B. Szenario-Bewertung,
Korrekturrunden, Modellwechsel, jeder Prüfer-Befund, was der Lektor geändert hat, Qualitätswerte, Freigabe. Änderungen an der
Welt sind dem Lauf zugeordnet. Läufe von vorher werden aus den vorhandenen Daten zusammengesetzt und als „rekonstruiert“ markiert.

### Export & Umzug
Einstellungen → Sicherung → „Export & Umzug“: **Welt** (Kanon, Folgen, Nachvollzug und alle Stimmen der Welt; Texte als Basis
nur als Auszüge, eingelesene Texte, die schon im Kanon stecken, ohne Inhalt), **Autor** (Erzählprofile, eigene Texte vollständig,
alle Stimmen) oder **Alles**. Import legt Welten immer neu an. Die Profil-ID entscheidet über die Sichtbarkeit: Ist der Mensch
auf dem Zielrechner bekannt, sind seine Texte sichtbar – sonst liegen sie verborgen und werden trotzdem genutzt; kommt er später
per Autor-Import dazu, wird alles sichtbar. „Verborgen“ gilt für die Oberfläche – die ZIP-Datei selbst ist nicht verschlüsselt.

### Darstellung
Einstellungen → Darstellung: Hell, Dunkel, Bunt oder ein eigenes Theme mit allen Farben (Akzent, KI-Farbe, Erfolg/Warnung/Fehler …)
und Live-Vorschau.

### Ablauf
1. **Welt anlegen** – jede Welt ist eine eigene SQLite-Datei in `welten/`. Optional mit Startbestand aus WELT_REGELN.md.
2. **Impuls eingeben** – Grundidee, Volk, Ort, Informationsstrang oder Wunsch. Was du setzt, ist Kanon.
3. **KI anwerfen** – sie liest Projektdokumente + kompletten Kanon und schickt einen Vorschlag.
4. **Übernehmen oder verwerfen** – atomar. Die KI legt nur Neues an oder füllt leere Felder; deine Werte werden nie überschrieben.
5. **Lücken** – fehlende Steckbrief-Angaben werden automatisch erkannt und können gezielt von der KI gefüllt werden.
6. **Einschübe & Sammelsurium** – offener Pool kleiner Extras (Socializing, Alltag, Wissen …) ohne feste Regeln, für Phasen,
   in denen zu wenig passiert. Von Hand oder per „KI: Sammelsurium auffüllen“.

Fehler bleiben lokal: Jede Vorschlags-Operation wird einzeln übernommen – eine fehlerhafte Operation (und was direkt auf ihr aufbaut)
wird übersprungen und gemeldet, der Rest kommt trotzdem in die Welt. KI-Aufträge laufen getrennt voneinander.

### Schnittstellen für KI
**MCP (für Claude Desktop, Claude Code und andere MCP-Clients)** – nur Standardbibliothek, Start über `story_world_mcp.py`.
Für Claude Code `mcp.example.json` nach `.mcp.json` kopieren und den Pfad anpassen. Für Claude Desktop in `claude_desktop_config.json` unter `mcpServers` eintragen (Windows: `"command": "py"`, `"args": ["-3", "C:\\…\\story_world_mcp.py"]`):

```json
"story-world": {
  "command": "python3",
  "args": ["/PFAD/ZU/evel-rote-faeden/story_world_mcp.py"]
}
```

Werkzeuge: `anleitung`, `welten_liste`, `welt_anlegen`, `welt_uebersicht`, `kanon_lesen`, `suchen`, `luecken_liste`,
`impuls_anlegen` (auch `art: nachricht`), `impulse_liste`, `vorschlag_einreichen`, `vorschlaege_liste`,
`vorschlag_entscheiden`, `ki_luecken_fuellen`. Eine externe KI kann damit selbst Weltenbauer sein: Sie reicht Vorschläge
im selben Format ein, die genauso geprüft werden (nur anlegen und leere Felder füllen).

**HTTP-API (lokal)** – solange die Oberfläche läuft, z. B. für Skripte auf demselben Rechner. Schreibende Aufrufe brauchen den Header `X-Story-World: 1`:

```bash
curl -X POST http://127.0.0.1:8765/api/w/hauptwelt/impulses -H 'X-Story-World: 1' -H 'Content-Type: application/json' \
  -d '{"title": "Schlagzeile", "content": "Kern der Nachricht …", "kind": "nachricht", "ki_sofort": true}'
```

### Freigabe
Laut OFFENE_PUNKTE.md Nr. 7 werden KI-Vorschläge standardmäßig automatisch übernommen. Hat die KI Rückfragen, bleibt der
Vorschlag offen und erscheint unter „Vorschläge“. Umschaltbar je Welt unter „Einstellungen“.

### Spoilerschutz
Jeder Datensatz hat Herkunft (`du`/`KI`) und Sichtbarkeit (`offen`/`backstage`). Rätselwahrheiten und Code-Bedeutungen
sind Geheimfelder; Rätsel und Codes der KI sind standardmäßig backstage. Gefiltert wird serverseitig – in Listen, Suche,
Lücken, Vorschlägen und Protokoll. „🔒 Spoilerschutz an“ oben rechts schaltet bewusst auf Backstage um.

### Sicherheit (lokal)
Server nur auf 127.0.0.1, Host-Prüfung, Schreibzugriffe nur mit eigenem Header und passendem Origin (kein CSRF aus fremden Tabs).
Datenbanken und Sicherungen (`welten/`, `welten/backups/`) enthalten Backstage-Geheimnisse und sind per .gitignore ausgeschlossen.

### Archiv statt Löschen
Nicht mehr benötigte Dateien wandern nach `_old/` (mit Datum und Grund), statt gelöscht zu werden.
