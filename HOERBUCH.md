# Hörbuch-Produktion

- Eingabe: Segmentiertes JSON (narrator/character).
- TTS (z. B. ElevenLabs/Azure) oder eigene Sprecher aus dem Studio.
- Feste Stimme pro Figur (Voice-Profile). Erzähler hat eine konstante Stimme.
- Aussprache-Lexikon für außerirdische Namen (SSML/Phoneme).
- Leitmotiv pro Volk und Strang. Rückblenden mit eigenem Klangbild.
- Folgenlänge einheitlich.
- Ansage der Zeit über Kalendernamen, nicht Tageszahlen.
- Automatisches Mastering (Lautstärke, Musik).
- Das Ende einer Folge gleicht inhaltlich dem Beginn der nächsten (Überlappung).

## Eigene TTS-Server (story_world/tts.py)

- Einstellungen → TTS-Server: beliebig viele Server (OpenAI-kompatibel wie Phonon, Pocket TTS, OmniVoice; oder Piper HTTP).
  „Prüfen & Stimmen laden“ holt Stimmen (mit Sprache/Geschlecht, falls der Server sie meldet) und Modelle. Entfernte Server liegen im Archiv.
- Je Folge: Modus „Hörspiel“ (jede Figur eigene Stimme) oder „Hörbuch“ (eine Stimme liest alles).
  Besetzung (Sprecher → Server|Stimme) gilt für die ganze Welt; Figuren ohne Wahl bekommen reihum eine freie Stimme derselben Sprache vom Server des Erzählers.
- Vertonen: Text an Satzgrenzen in Stücke ≤ „max. Zeichen“ → Server → Zwischenspeicher `welten/audio/<welt>/_tts_cache` → eine WAV (mono, 16 bit).
  Ergebnis `Folge_NNN_<Titel>_TTS.mp3` mit ID3-Tags (mit `lame`/`ffmpeg`; sonst `_TTS.wav`) plus `.json` mit der Besetzung;
  die WAV liegt dann in `_wav`, ältere Ergebnisse wandern nach `_alt`.
- Kommandozeile: `python3 -m story_world vertonen <welt> <folge-nr> [--modus hoerbuch|hoerspiel]`.
- JSON-Export: Sind TTS-Server eingerichtet, enthält er `quelle: tts-server`, `modus`, `server` (Name, URL, Modell, max. Zeichen – nie Schlüssel), `sprecher` und je Segment `server`, `stimme`, `sprache`.
- Vorlesen im Browser und die macOS-Vertonung („Hörbuch erzeugen“) sind davon unberührt.

## Mitgelieferter Libra-TTS-Server (story_world/libra.py, zusatz/libra-tts)

- Liegt im Programmpaket. Einrichten über die Systemprüfung beim Start, Einstellungen → TTS-Server → „Einrichten“ oder
  `python3 -m story_world libra einrichten`: Python ≥ 3.10 suchen, `zusatz/libra-tts/.venv` anlegen, `installer.py`
  (Pakete + Modell nach `models/`, Backend mlx/cuda/onnx automatisch).
- Startet mit der Oberfläche im Hintergrund (127.0.0.1, freier Port ab 8880, Sprache de), Ausgabe in `_update/libra.log`,
  Prozessnummer in `_update/libra.pid`; beendet sich mit Story World bzw. über „Story World beenden“.
  `python3 -m story_world libra status|starten|stoppen`.
- Trägt sich als TTS-Server „Libra-TTS (mitgeliefert)“ ein (Preset `libra`, Feld `mitgeliefert`). Archivieren = nicht mehr starten.
- Update: Server-Code wird wie jede Programmdatei ersetzt, `.venv/`, `models/`, `server.conf` sind geschützt.
  Neue `requirements.txt`/`installer.py`/`download_model.py` → beim nächsten Start Nachinstallation; neuer Server-Code → Neustart des Servers.

## Hörspiel-Regie (story_world/regie.py)

- Server mit Stilen/Geräuschen erkennt „Prüfen & Stimmen laden“ an `GET /v1/audio/voices` → `styles`, `tags` (Feld `regie`
  am Server); schon eingetragene eigene Server werden beim Vertonen bzw. Öffnen der Folge einmal nachgefragt.
- Beim Vertonen legt die KI (Aufgabe „regie“) je Absatz den Anfangsstil und einen Sprechtext fest – in Abschnitten von
  höchstens 30 Absätzen. Der Sprechtext enthält Geräusch-Tags (`<sigh>` …) und Stilwechsel `[documentary]`, `[warm]`,
  `[neutral]` mitten im Absatz: Menschen sprechen je nach Inhalt anders (Persönliches warm, Zahlen/Erklärungen dokumentarisch).
  Jeder Teil geht mit eigenem `style` an den Server; zwischen Teilen eines Absatzes nur eine kurze Pause.
- Tempo: Die KI setzt keins (normal), der Stil bringt sein Tempo mit. Ein im Editor von Hand gesetztes `slow`/`fast`
  geht als `pace` an den Server (für alle Teile des Absatzes) und bleibt auch bei neuer KI-Regie erhalten.
- Umformulieren von Hand: Im Editor darf der Sprechtext auch andere Wörter oder einen umgebauten Satz haben – nur fürs
  Hörspiel (Vertonung, JSON-Export mit zusätzlichem `originaltext`); Folgentext, Anzeige und Kanon bleiben im Original.
  „↺ Original“ setzt den Folgentext wieder ein. Ändert sich der Folgentext selbst, gilt die Regie nicht mehr (alte Fassung in `….vorher`).
- Prüfung bei der KI: Ohne Tags und Stilwechsel muss exakt der Originaltext herauskommen, sonst gilt das Original; nur bekannte Tags,
  höchstens 1 (dezent) bzw. 3 (lebendig) Gefühls-Tags je Absatz. Ein gescheiterter Abschnitt bleibt neutral, ohne KI neutral.
- Atmen setzt der Code nach der KI (`regie.atmen`): `<breath>` vor einem Satz, sobald seit dem letzten Atmer/Tag genug
  gesprochen wurde (dezent 220, lebendig 150 Zeichen) oder vor sehr langen Sätzen; „lebendig“ auch zu Beginn langer Absätze;
  bei Angst/Aufregung einmal `<heavy breath>`. Atem-Tags zählen nicht gegen die Obergrenze.
- Gespeichert in `world_meta` `tts.regie.<folge>` (vorige Fassung `….vorher`), gültig solange der Folgentext gleich ist.
  Von Hand geänderte Regie überschreibt die KI nicht. Der Folgentext selbst (Anzeige, Kanon) bekommt nie Tags.
- Regie-Editor (Expertenmodus): Leiste mit Geräuschen, Stilwechseln, Tabellenfilter und „Ausgewählte neu vertonen“ bleibt
  oben stehen, nur die Absätze scrollen; Sprechtext ist immer mit dem Text gefüllt und direkt änderbar; jede Zelle speichert
  beim Verlassen bzw. beim Einfügen selbst.
- Takes je Absatz (`tts.segment_take`): ▶ spricht nur diesen Absatz (gewählter Take, aus dem Zwischenspeicher, falls schon
  gesprochen) und spielt ihn ab; 🔁 nimmt einen neuen Take auf (neuer `seed`); das Auswahlfeld tauscht den Take fürs
  Zusammenfügen. „Ausgewählte neu sprechen“ nimmt für die angehakten Absätze je einen neuen Take auf – sonst nichts.
  Jeder Take liegt als WAV unter `welten/audio/<welt>/_teile/<folge>/` und bleibt erhalten. Erst „Hörspiel
  zusammenfügen (MP3)“ (`tts.render`) baut aus den gewählten Takes die Datei; schon Gesprochenes kommt aus `_tts_cache`.
- An den Server gehen `style`, ggf. `seed` und der Sprechtext; Tags überstehen Aussprache-Lexikon und Zerlegen. Server ohne
  diese Fähigkeit bekommen den Originaltext.
- JSON-Export und Begleit-JSON neben der MP3 (`…_TTS.json`, Feld `segmente`): je Segment `text` mit den Geräusch-Tags
  (so wie gesprochen), `stil` (Anfangsstil) und bei Stilwechseln `teile` [{text, stil}]; oben `regie` (Zusammenfassung).
