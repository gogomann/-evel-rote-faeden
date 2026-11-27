# Libra-TTS Server (OpenAI-kompatibel)

Lokaler Text-to-Speech-Server auf Basis von [Ekam/Libra-TTS](https://huggingface.co/Ekam/Libra-TTS):
16 Sprachen, 8 Stimmen, 12 Sprechstile, 24 kHz. Spricht die OpenAI-Audio-API (`POST /v1/audio/speech`),
d. h. jedes Tool mit „OpenAI TTS“-Unterstützung kann ihn nutzen – nur die Base-URL umstellen.

Alles liegt in diesem Ordner: Python-Umgebung (`.venv`), Modell (`models/`), Einstellungen (`server.conf`).

## 1. Installieren (einmalig)

Voraussetzung: Python 3.10 oder neuer ([python.org](https://www.python.org/downloads/)).

| System | Befehl |
|---|---|
| macOS / Linux | `./install.sh` |
| Windows | `install.bat` (Doppelklick) |

Das Backend wird automatisch gewählt:
- **Mac mit Apple Silicon** → `mlx` (GPU)
- **NVIDIA-Grafikkarte** (RTX 20xx oder neuer) → `cuda`
- **sonst** → `onnx` (CPU)

Erzwingen: `./install.sh --backend onnx`. Japanisch zusätzlich: `--ja`.
Download: ca. 1 GB (mlx/cuda) bzw. 1,7 GB (onnx). Danach läuft alles offline.

## 2. Starten

```bash
./start.sh            # Port aus server.conf (Standard 8880)
./start.sh 9000       # anderer Port
./start.sh 9000 --lang de --voice bob
```
Windows: `start.bat` bzw. `start.bat 9000 --lang de`.

Weitere Optionen: `--host 127.0.0.1` (nur lokal), `--api-key GEHEIM`, `--format wav`.
Dauerhaft einstellen: `server.conf` bearbeiten.

> **Wichtig für Deutsch:** Mit `LANG=auto` wird lateinische Schrift als *Englisch* gelesen.
> Für deutsche Texte `LANG=de` in `server.conf` setzen oder pro Anfrage `"lang": "de"` mitschicken.

## 3. Benutzen

### Web-Oberfläche
Im Browser öffnen: **http://localhost:8880/** (bzw. der gewählte Port).
Text einfügen, Sprache, Stimme und Format wählen, *Sprechen* (oder Strg/⌘ + Enter), anhören, herunterladen.
Unter *Weitere Einstellungen*: Stil, Tempo, Seed, Variation, Satzpause, API-Schlüssel, alle Geräusch-Tags
(Klick fügt ein), Stilnamen (Klick kopiert) sowie fertige JSON-, curl- und Python-Aufrufe mit den aktuellen
Einstellungen zum Kopieren. Die Einstellungen bleiben im Browser gespeichert.

### API
In Tools mit OpenAI-TTS-Unterstützung:
- **Base-URL:** `http://<rechner>:8880/v1`
- **API-Key:** beliebig (oder der in `server.conf` gesetzte)
- **Modell:** `tts-1` / `libra-tts`

```bash
curl http://localhost:8880/v1/audio/speech -H "Content-Type: application/json" \
  -d '{"model":"tts-1","input":"Es war einmal ...","voice":"bob","lang":"de","response_format":"mp3"}' \
  -o szene01.mp3
```

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8880/v1", api_key="egal")
r = client.audio.speech.create(model="tts-1", voice="nina", input="Hallo!",
                               extra_body={"lang": "de", "style": "cheerful"})
open("hallo.mp3", "wb").write(r.content)
```

### Parameter von `/v1/audio/speech`

| Feld | Bedeutung |
|---|---|
| `input` | Text (beliebig lang, wird satzweise gelesen) |
| `voice` | `nina sofia aliya maya` (w) · `omar jon bob sam` (m) – OpenAI-Namen (`alloy`, `onyx`, …) werden umgemappt |
| `response_format` | `mp3` `wav` `flac` `opus` `pcm` (`aac` nur mit ffmpeg) |
| `instructions` | enthält es einen Stilnamen (z. B. „whispering“), wird der Stil genutzt |
| `speed` | ≤ 0.85 → langsam, ≥ 1.15 → schnell (wirkt nur zusammen mit einem Stil) |
| `lang` | `de en fr es it pt ru zh ja ko ar hi pa bn ur id` oder `auto` |
| `style` | `warm cheerful excited sad frightened calm serious wry tender whispering dramatic documentary` |
| `pace` | `slow` / `fast` (nur mit Stil) |
| `seed` | gleicher Text + gleicher Seed = gleiches Audio (Standard 0) |
| `temperature` | Variation (Standard 0.5) |
| `gap` | Pause zwischen Sätzen in Sekunden (Standard 0.3) |

`lang`, `style`, `pace`, `seed`, `temperature`, `gap` sind Erweiterungen – im OpenAI-Python-Client über `extra_body`.

**Geräusch-Tags im Text:** `<laugh> <chuckle> <giggle> <sigh> <gasp> <breath> <short pause> <long pause> <cough> <yawn> <sob> <cry> <groan> <shout>` u. a. – Liste unter `GET /v1/audio/voices`.

### Weitere Endpunkte
- `GET /health` – Status
- `GET /v1/models` – Modellliste
- `GET /v1/audio/voices` – Stimmen, Sprachen, Stile, Tags

## Grenzen
- **Kein Voice-Cloning:** Das Modell kennt nur die 8 eingebauten Stimmen (feste Sprecher-Token, kein Sprach-Encoder).
- Anfragen werden nacheinander abgearbeitet (ein Modell im Speicher).

## Lizenz
Libra-TTS (Code in `libra_tts/` und Modell) steht unter Apache 2.0 – siehe `libra_tts/LICENSE`.
