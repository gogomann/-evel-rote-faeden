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
