"""TTS-Server: beliebig viele eigene Sprach-Server, Stimmen laden, Besetzung, Folgen vertonen.

Server-Arten:
- "openai": OpenAI-kompatibel (POST /v1/audio/speech, Stimmen über /v1/audio/voices bzw. /v1/voices) –
  z. B. Phonon, Pocket TTS, OmniVoice-Server, Kokoro-FastAPI. Ein optionales Feld „language“ wird mitgeschickt,
  wenn die Stimme oder der Server eine Sprache hat.
- "piper": Piper-HTTP-Server (GET /voices, POST / mit {"text", "voice"}).
- "elevenlabs": ElevenLabs (GET /v1/voices, POST /v1/text-to-speech/{voice}?output_format=pcm_24000 → PCM in WAV).
- "google": Google Cloud Text-to-Speech (GET /v1/voices, POST /v1/text:synthesize, LINEAR16).
- "azure": Microsoft Azure Speech (GET /cognitiveservices/voices/list, POST /cognitiveservices/v1 mit SSML).

Vorauswahlen (PRESETS) wie bei den KI-Anbietern: Art, Adresse, Modell und Stückgröße sind vorbereitet, meist fehlt nur der
Schlüssel. Cloud-Anbieter bekommen den Text der Folge; die eigenen Server im Heimnetz bleiben die Alternative.

Konfiguration liegt wie die KI-Anbieter in story_world.config.json (Schlüssel "tts_server", entfernte unter "tts_archiv",
nichts wird gelöscht). Besetzung je Welt (Sprecher → Server|Stimme) und Einstellungen je Folge (Hörspiel = mehrere
Stimmen, Hörbuch = eine Stimme für alles) stehen in world_meta.

Hörspiel-Regie (regie.py): Kann ein Server Sprechstile und Geräusch-Tags (Libra-TTS: /v1/audio/voices meldet
„styles“ und „tags“), legt die KI je Absatz Stil, Stilwechsel und Tags fest; sie gehen als „style“ und im Text an den
Server (ein Absatz mit Stilwechseln = mehrere Anfragen). Ein Tempo („pace“) wird nie gesetzt. Neue Takes einzelner
Absätze gehen als „seed“ mit. Stufe je Folge: aus, dezent, lebendig. Der mitgelieferte Libra-Server (libra.py) wird automatisch eingetragen.

Vertonung: Text je Absatz an Satzgrenzen in Stücke ≤ max_zeichen zerlegen → Server → WAV-Stücke (Zwischenspeicher
_tts_cache, ein Neustart macht dort weiter) → eine WAV-Datei (mono, 16 bit, Abtastrate des ersten Stücks) → mit
lame/ffmpeg eine MP3 mit ID3-Tags (mp3.py; die WAV wandert dann nach _wav). Ältere
Ergebnisse werden nach _alt verschoben, nicht gelöscht.
Nur Python-Standardbibliothek.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
from array import array
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from . import episodes, mp3, providers, runs, service, worlds

TYPES = {
    "openai": {"name": "OpenAI-kompatibel",
               "info": "POST /v1/audio/speech – z. B. Phonon, Pocket TTS, OmniVoice-Server, Kokoro-FastAPI. "
                       "Adresse ohne /v1 genügt, z. B. http://192.168.1.50:8012"},
    "piper": {"name": "Piper (HTTP)",
              "info": "Piper-HTTP-Server (python3 -m piper.http_server). Adresse z. B. http://192.168.1.50:5000"},
    "elevenlabs": {"name": "ElevenLabs", "info": "ElevenLabs-API (api.elevenlabs.io), Schlüssel im Kopf xi-api-key."},
    "google": {"name": "Google Cloud TTS", "info": "Google Cloud Text-to-Speech (texttospeech.googleapis.com) mit API-Schlüssel."},
    "azure": {"name": "Microsoft Azure Speech",
              "info": "Azure Speech, Adresse mit Region, z. B. https://westeurope.tts.speech.microsoft.com"},
}

# Meistgenutzte Anbieter als Vorauswahl – wie bei den KI-Anbietern. "custom" bleibt der Weg für eigene Server.
PRESETS = [
    {"id": "elevenlabs", "name": "ElevenLabs", "typ": "elevenlabs", "base_url": "https://api.elevenlabs.io",
     "modell": "eleven_multilingual_v2", "max_zeichen": 2000, "needs_key": True, "cloud": True,
     "key_url": "https://elevenlabs.io/app/settings/api-keys",
     "info": "Sehr natürliche Stimmen, viele Sprachen, eigene und geklonte Stimmen aus deinem Konto. "
             "Kostenloses Kontingent, danach Abo nach Zeichen. Schlüssel braucht Lesezugriff auf Stimmen und Modelle."},
    {"id": "openai", "name": "OpenAI TTS", "typ": "openai", "base_url": "https://api.openai.com",
     "modell": "gpt-4o-mini-tts", "max_zeichen": 2000, "needs_key": True, "cloud": True,
     "key_url": "https://platform.openai.com/api-keys",
     "info": "Feste Stimmen (alloy, nova, onyx …), sprechen auch Deutsch. Abrechnung über das OpenAI-Plattformkonto."},
    {"id": "google", "name": "Google Cloud TTS", "typ": "google", "base_url": "https://texttospeech.googleapis.com",
     "modell": "", "sprache": "de", "max_zeichen": 1500, "needs_key": True, "cloud": True,
     "key_url": "https://console.cloud.google.com/apis/credentials",
     "info": "Hunderte Stimmen (Chirp 3 HD, Neural2, WaveNet). Im Google-Cloud-Projekt „Cloud Text-to-Speech API“ "
             "aktivieren und einen API-Schlüssel anlegen. Großes Gratis-Kontingent je Monat."},
    {"id": "azure", "name": "Microsoft Azure Speech", "typ": "azure",
     "base_url": "https://westeurope.tts.speech.microsoft.com", "modell": "", "sprache": "de", "max_zeichen": 2000,
     "needs_key": True, "cloud": True,
     "key_url": "https://portal.azure.com/#create/Microsoft.CognitiveServicesSpeechServices",
     "info": "Viele Neural-Stimmen, auch deutsche. Speech-Ressource anlegen, Schlüssel 1 kopieren; die Region "
             "(z. B. westeurope, germanywestcentral) steht in der Adresse. Gratis-Stufe F0 verfügbar."},
    {"id": "libra", "name": "Libra-TTS (Stile & Geräusche)", "typ": "openai", "base_url": "http://127.0.0.1:8880",
     "modell": "tts-1", "sprache": "de", "max_zeichen": 600, "needs_key": False, "cloud": False,
     "key_url": "https://huggingface.co/Ekam/Libra-TTS",
     "info": "Liegt Story World bei (zusatz/libra-tts) und startet automatisch mit, sobald es eingerichtet ist. "
             "8 Stimmen, 12 Sprechstile (warm, sad, whispering …) und Geräusche wie <sigh> oder <laugh> – die "
             "Hörspiel-Regie nutzt sie. Läuft offline. Hier nur für einen Libra-Server auf einem anderen Rechner."},
    {"id": "kokoro", "name": "Kokoro-FastAPI (lokal)", "typ": "openai", "base_url": "http://localhost:8880",
     "modell": "kokoro", "max_zeichen": 400, "needs_key": False, "cloud": False,
     "key_url": "https://github.com/remsky/Kokoro-FastAPI",
     "info": "Läuft auf deinem Rechner oder im Heimnetz, kostenlos, kein Schlüssel. Docker-Start siehe Link."},
    {"id": "piper", "name": "Piper (lokal)", "typ": "piper", "base_url": "http://localhost:5000",
     "modell": "", "max_zeichen": 400, "needs_key": False, "cloud": False,
     "key_url": "https://github.com/OHF-Voice/piper1-gpl",
     "info": "Schnell und kostenlos, auch auf schwacher Hardware. Start: python3 -m piper.http_server -m de_DE-thorsten-medium"},
    {"id": "custom", "name": "Eigener Server (OpenAI-kompatibel)", "typ": "openai", "base_url": "",
     "modell": "", "max_zeichen": 400, "needs_key": False, "cloud": False, "key_url": "",
     "info": "Phonon, Pocket TTS, OmniVoice, LocalAI oder jeder andere Server mit POST /v1/audio/speech. "
             "Adresse ohne /v1 genügt, z. B. http://192.168.1.50:8012"},
]
PRESET_BY_ID = {p["id"]: p for p in PRESETS}

# OpenAI hat keine Stimmenliste über die API – die festen Stimmen stehen hier (sprechen alle Sprachen).
OPENAI_VOICES = [("alloy", None), ("ash", "male"), ("ballad", "male"), ("coral", "female"), ("echo", "male"),
                 ("fable", "male"), ("nova", "female"), ("onyx", "male"), ("sage", "female"), ("shimmer", "female"),
                 ("verse", "male"), ("marin", "female"), ("cedar", "male")]
ELEVEN_PCM_RATE = 24000
MODI = {"hoerspiel": "Hörspiel – jede Figur eigene Stimme", "hoerbuch": "Hörbuch – eine Stimme liest alles"}
DEFAULT_MAX_CHARS = 400
SSML_TYPES = ("azure", "google")  # Aussprache-Lexikon mit Sprache/IPA als <lang>/<phoneme>; sonst die Sprechfassung
DEFAULT_TIMEOUT = 300
PAUSE_SEGMENT_SAME = 0.45
PAUSE_SEGMENT_CHANGE = 0.3
PAUSE_CHUNK = 0.12
RETRIES = 2


class TTSError(RuntimeError):
    pass


# ---------------------------------------------------------------- Konfiguration (app-weit)

def _cfg() -> dict:
    cfg = providers.load()
    cfg.setdefault("tts_server", [])
    cfg.setdefault("tts_archiv", [])
    return cfg


def servers(cfg: dict | None = None) -> list:
    return list((cfg or _cfg())["tts_server"])


def get_server(sid: str, cfg: dict | None = None) -> dict:
    for s in servers(cfg):
        if s["id"] == sid:
            return s
    raise LookupError("TTS-Server nicht gefunden.")


def public_server(s: dict) -> dict:
    out = {k: v for k, v in s.items() if k != "api_key"}
    out["api_key_maskiert"] = providers.mask(s.get("api_key", ""))
    out["api_key_gesetzt"] = bool(s.get("api_key"))
    out["typ_name"] = TYPES.get(s.get("typ"), {}).get("name", s.get("typ"))
    out["preset_name"] = PRESET_BY_ID.get(s.get("preset") or "custom", {}).get("name", "")
    out["cloud"] = bool(PRESET_BY_ID.get(s.get("preset") or "custom", {}).get("cloud"))
    out["stimmen_anzahl"] = len(s.get("stimmen") or [])
    return out


def public_settings() -> dict:
    cfg = _cfg()
    return {"server": [public_server(s) for s in cfg["tts_server"]],
            "archiv": [public_server(s) for s in cfg["tts_archiv"]],
            "typen": [{"id": k, **v} for k, v in TYPES.items()], "presets": PRESETS, "modi": MODI,
            "standard_max_zeichen": DEFAULT_MAX_CHARS}


def _clean_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    for suffix in ("/audio/speech", "/audio/voices", "/voices", "/models", "/text-to-speech", "/text:synthesize",
                   "/cognitiveservices/voices/list", "/cognitiveservices/v1"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    if not url.startswith(("http://", "https://")):
        raise ValueError("Bitte eine gültige Adresse eintragen (beginnt mit http:// oder https://).")
    return url


def _int(value, low: int, high: int, label: str, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        raise ValueError(f"{label} muss eine Zahl sein.")
    if not low <= number <= high:
        raise ValueError(f"{label} bitte zwischen {low} und {high}.")
    return number


def _apply_fields(s: dict, data: dict) -> None:
    if "name" in data and str(data["name"]).strip():
        s["name"] = str(data["name"]).strip()[:80]
    if "base_url" in data:
        url = _clean_url(data["base_url"])
        if url != s.get("base_url"):
            s["base_url"], s["status"] = url, "ungeprueft"
    if "typ" in data:
        if data["typ"] not in TYPES:
            raise ValueError("Unbekannte Server-Art.")
        s["typ"] = data["typ"]
    if "modell" in data:
        s["modell"] = str(data["modell"] or "").strip()[:120]
    if "sprache" in data:
        s["sprache"] = str(data["sprache"] or "").strip()[:20]
    if "max_zeichen" in data:
        s["max_zeichen"] = _int(data["max_zeichen"], 50, 5000, "Maximale Zeichen je Anfrage", DEFAULT_MAX_CHARS)
    if "timeout" in data:
        s["timeout"] = _int(data["timeout"], 10, 3600, "Zeitlimit", DEFAULT_TIMEOUT)
    if data.get("api_key"):
        s["api_key"] = str(data["api_key"]).strip()
    if data.get("api_key_entfernen"):
        s["api_key"] = ""


def add_server(data: dict) -> str:
    preset = PRESET_BY_ID.get(data.get("preset") or "custom")
    if preset is None:
        raise ValueError("Unbekannte Vorauswahl.")
    s = {"id": "t_" + uuid.uuid4().hex[:8], "preset": preset["id"], "name": "", "typ": data.get("typ") or preset["typ"],
         "base_url": "", "api_key": "", "modell": preset.get("modell", ""), "sprache": preset.get("sprache", ""),
         "max_zeichen": preset.get("max_zeichen") or DEFAULT_MAX_CHARS, "timeout": DEFAULT_TIMEOUT,
         "stimmen": [], "modelle": [], "status": "ungeprueft"}
    data = dict(data)
    if not str(data.get("base_url") or "").strip():
        if not preset["base_url"]:
            raise ValueError("Bitte die Adresse des Servers eintragen.")
        data["base_url"] = preset["base_url"]
    if data.get("preset") and not str(data.get("name") or "").strip():
        data["name"] = preset["name"]
    _apply_fields(s, data)
    s["name"] = s["name"] or s["base_url"].split("//", 1)[-1]
    with providers._LOCK:
        cfg = _cfg()
        cfg["tts_server"].append(s)
        providers.save(cfg)
    return s["id"]


def update_server(sid: str, data: dict) -> dict:
    with providers._LOCK:
        cfg = _cfg()
        for s in cfg["tts_server"]:
            if s["id"] == sid:
                _apply_fields(s, data)
                providers.save(cfg)
                return public_server(s)
    raise LookupError("TTS-Server nicht gefunden.")


def archive_server(sid: str) -> None:
    """Nicht löschen: ins Archiv verschieben (wiederherstellbar)."""
    with providers._LOCK:
        cfg = _cfg()
        moved = [s for s in cfg["tts_server"] if s["id"] == sid]
        if not moved:
            raise LookupError("TTS-Server nicht gefunden.")
        moved[0]["archiviert_am"] = time.strftime("%Y-%m-%d %H:%M")
        cfg["tts_server"] = [s for s in cfg["tts_server"] if s["id"] != sid]
        cfg["tts_archiv"].append(moved[0])
        providers.save(cfg)


def restore_server(sid: str) -> None:
    with providers._LOCK:
        cfg = _cfg()
        moved = [s for s in cfg["tts_archiv"] if s["id"] == sid]
        if not moved:
            raise LookupError("Archivierter TTS-Server nicht gefunden.")
        moved[0].pop("archiviert_am", None)
        cfg["tts_archiv"] = [s for s in cfg["tts_archiv"] if s["id"] != sid]
        cfg["tts_server"].append(moved[0])
        providers.save(cfg)


def _set_state(sid: str, **fields) -> None:
    with providers._LOCK:
        cfg = _cfg()
        for s in cfg["tts_server"]:
            if s["id"] == sid:
                s.update(fields)
                providers.save(cfg)
                return


# ---------------------------------------------------------------- HTTP

def _api_base(s: dict) -> str:
    base = s["base_url"]
    if s.get("typ") in ("openai", "elevenlabs", "google") and not base.endswith("/v1"):
        base += "/v1"
    return base


def _auth(s: dict) -> dict:
    key = s.get("api_key")
    if not key:
        return {}
    typ = s.get("typ")
    if typ == "elevenlabs":
        return {"xi-api-key": key}
    if typ == "google":
        return {"X-Goog-Api-Key": key}
    if typ == "azure":
        return {"Ocp-Apim-Subscription-Key": key}
    return {"Authorization": f"Bearer {key}"}


def _http(s: dict, method: str, path: str, body=None, timeout: int | None = None, headers: dict | None = None) -> tuple:
    """body: dict (wird JSON) oder fertige Bytes (Content-Type dann über headers)."""
    url = _api_base(s) + path
    extra = headers or {}
    headers = {"User-Agent": "StoryWorld/1", "Accept": "*/*"}
    data = None
    if isinstance(body, (bytes, bytearray)):
        data = bytes(body)
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    headers.update(_auth(s))
    headers.update(extra)
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    context = providers._ssl_context() if url.startswith("https://") else None
    try:
        with urllib.request.urlopen(request, timeout=timeout or s.get("timeout") or DEFAULT_TIMEOUT,
                                    context=context) as resp:
            return resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise TTSError(f"{s.get('name')}: HTTP {exc.code} bei {path} – {detail}")
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise TTSError(f"{s.get('name')}: nicht erreichbar ({url}) – {reason}")


def _json(s: dict, path: str, timeout: int = 15):
    raw, _ = _http(s, "GET", path, timeout=timeout)
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        raise TTSError(f"{s.get('name')}: {path} liefert kein JSON.")


def _voice(vid, name=None, lang=None, gender=None) -> dict:
    return {"id": str(vid), "name": str(name or vid), "sprache": (lang or "").replace("_", "-") or None,
            "geschlecht": gender or None}


def parse_voices(payload) -> list:
    """Stimmenlisten der üblichen Server-Formate vereinheitlichen: [{id, name, sprache, geschlecht}]."""
    out: dict = {}

    def add(v: dict) -> None:
        if v["id"] and v["id"] not in out:
            out[v["id"]] = v

    def from_item(item, lang=None) -> None:
        if isinstance(item, str):
            add(_voice(item, lang=lang))
        elif isinstance(item, dict):
            vid = item.get("id") or item.get("voice_id") or item.get("name") or item.get("voice")
            language = item.get("language") or item.get("lang") or lang
            if isinstance(language, dict):
                language = language.get("code") or language.get("name")
            if isinstance(language, list):
                language = language[0] if language else None
            add(_voice(vid, item.get("name") or vid, language, item.get("gender") or item.get("geschlecht")))

    if isinstance(payload, list):
        for item in payload:
            from_item(item)
    elif isinstance(payload, dict):
        details = payload.get("details_by_language")
        if isinstance(details, dict):
            for lang, items in details.items():
                for item in items or []:
                    from_item(item, lang)
        by_lang = payload.get("by_language")
        if isinstance(by_lang, dict):
            for lang, items in by_lang.items():
                for item in items or []:
                    from_item(item, lang)
        for key in ("data", "voices"):
            if isinstance(payload.get(key), list):
                for item in payload[key]:
                    from_item(item)
        if not out and all(isinstance(v, dict) for v in payload.values()) and payload:
            for vid, item in payload.items():  # Piper: {"de_DE-thorsten-medium": {...}}
                from_item(dict(item, id=vid))
    return list(out.values())


def _gender(value) -> str | None:
    value = str(value or "").lower()
    return {"female": "female", "f": "female", "male": "male", "m": "male"}.get(value) or (value or None)


def _lang_filter(s: dict, voices: list) -> list:
    """Bei Anbietern mit Hunderten Stimmen nur die eingestellte Sprache behalten (Feld „Sprache“, z. B. de)."""
    want = (s.get("sprache") or "").lower().split("-")[0]
    if not want:
        return voices
    return [v for v in voices if not v.get("sprache") or v["sprache"].lower().split("-")[0] == want]


def _voices_elevenlabs(s: dict) -> list:
    payload = _json(s, "/voices")
    out = []
    for item in (payload.get("voices") if isinstance(payload, dict) else None) or []:
        labels = item.get("labels") or {}
        # ElevenLabs-Stimmen sprechen mehrsprachig; Sprache nur setzen, wenn ausdrücklich angegeben
        lang = labels.get("language") or None
        name = item.get("name") or item.get("voice_id")
        extra = ", ".join(x for x in (labels.get("accent"), item.get("category") if item.get("category") not in
                                      (None, "premade") else None) if x)
        out.append(_voice(item.get("voice_id"), f"{name} – {extra}" if extra else name, lang, _gender(labels.get("gender"))))
    return [v for v in out if v["id"] and v["id"] != "None"]


def _voices_google(s: dict) -> list:
    want = (s.get("sprache") or "").strip()
    payload = _json(s, "/voices" + (f"?languageCode={urllib.parse.quote(want)}" if want else ""), timeout=30)
    out = []
    for item in (payload.get("voices") if isinstance(payload, dict) else None) or []:
        codes = item.get("languageCodes") or []
        out.append(_voice(item.get("name"), item.get("name"), codes[0] if codes else None, _gender(item.get("ssmlGender"))))
    return _lang_filter(s, out)


def _voices_azure(s: dict) -> list:
    payload = _json(s, "/cognitiveservices/voices/list", timeout=30)
    out = []
    for item in payload if isinstance(payload, list) else []:
        locale = item.get("Locale")
        name = item.get("LocalName") or item.get("DisplayName") or item.get("ShortName")
        out.append(_voice(item.get("ShortName"), f"{name} ({locale})" if locale else name, locale, _gender(item.get("Gender"))))
    return _lang_filter(s, out)


def fetch_voices(s: dict) -> list:
    typ = s.get("typ")
    if typ == "elevenlabs":
        found = _voices_elevenlabs(s)
    elif typ == "google":
        found = _voices_google(s)
    elif typ == "azure":
        found = _voices_azure(s)
    elif s.get("preset") == "openai":
        _json(s, "/models")  # prüft den Schlüssel; Stimmen sind fest
        found = [_voice(vid, vid, None, gender) for vid, gender in OPENAI_VOICES]
    else:
        found = None
    if found is not None:
        if not found:
            raise TTSError(f"{s.get('name')}: keine Stimmen gefunden" + (f" für Sprache „{s['sprache']}“." if s.get("sprache") else "."))
        return found
    paths = ["/audio/voices", "/voices"] if typ == "openai" else ["/voices"]
    errors = []
    for path in paths:
        try:
            found = parse_voices(_json(s, path))
            if found:
                return found
        except TTSError as exc:
            errors.append(str(exc))
    raise TTSError(errors[-1] if errors else f"{s.get('name')}: keine Stimmen gefunden.")


def fetch_models(s: dict) -> list:
    if s.get("typ") not in ("openai", "elevenlabs"):
        return []
    try:
        payload = _json(s, "/models")
    except TTSError:
        return []
    if s.get("typ") == "elevenlabs":
        return [m.get("model_id") for m in payload if isinstance(m, dict) and m.get("model_id")
                and m.get("can_do_text_to_speech", True)] if isinstance(payload, list) else []
    items = payload.get("data", []) if isinstance(payload, dict) else payload
    models = [m.get("id") for m in items if isinstance(m, dict) and m.get("id")]
    if s.get("preset") == "openai":
        models = [m for m in models if "tts" in m]
    return models


_LANG_NAMES = {"german": "de", "english": "en", "french": "fr", "italian": "it", "portuguese": "pt", "spanish": "es",
               "dutch": "nl", "polish": "pl", "russian": "ru", "japanese": "ja", "chinese": "zh"}


def detect_language(s: dict) -> str | None:
    """Sprache des aktiven Modells, wenn der Server sie meldet (z. B. Pocket TTS: GET /v1/model → active.value)."""
    if s.get("typ") != "openai":
        return None
    try:
        payload = _json(s, "/model", timeout=8)
    except TTSError:
        return None
    active = payload.get("active") if isinstance(payload, dict) else None
    value = str((active or {}).get("value") or "").lower().split("_")[0]
    return _LANG_NAMES.get(value) or (value if len(value) == 2 else None)


def fetch_regie(s: dict) -> dict | None:
    """Kann der Server Sprechstile und Geräusch-Tags? (Libra-TTS: GET /v1/audio/voices → styles, paces, tags)"""
    if s.get("typ") != "openai" or s.get("preset") == "openai":
        return None
    try:
        payload = _json(s, "/audio/voices")
    except TTSError:
        return None
    return _regie_from(payload)


def _regie_from(payload) -> dict | None:
    if not isinstance(payload, dict):
        return None
    styles = [str(x) for x in payload.get("styles") or [] if isinstance(x, str)]
    tags = [str(x) for x in payload.get("tags") or [] if isinstance(x, str) and x.startswith("<")]
    if not styles and not tags:
        return None
    paces = [str(x) for x in payload.get("paces") or [] if isinstance(x, str)] or ["slow", "fast"]
    return {"stile": styles, "tempi": paces, "tags": tags}


def ensure_regie(server_ids) -> None:
    """Server, die noch nie auf Stile/Geräusche geprüft wurden (z. B. vor dieser Funktion eingetragen), jetzt einmal
    fragen und das Ergebnis speichern. Nicht erreichbar → beim nächsten Mal erneut."""
    for sid in server_ids or []:
        try:
            s = get_server(sid)
        except LookupError:
            continue
        if "regie" in s or s.get("typ") != "openai" or s.get("preset") == "openai":
            continue
        try:
            payload = _json(s, "/audio/voices", timeout=8)
        except TTSError:
            continue
        _set_state(sid, regie=_regie_from(payload))


def verify(sid: str) -> dict:
    """Verbindung prüfen und Stimmen (und Modelle, Stile/Geräusche) laden."""
    s = get_server(sid)
    if PRESET_BY_ID.get(s.get("preset") or "custom", {}).get("needs_key") and not s.get("api_key"):
        message = "Für diesen Anbieter fehlt noch der API-Schlüssel."
        _set_state(sid, status="fehler", last_error=message, geprueft_am=time.strftime("%Y-%m-%d %H:%M"))
        return {"ok": False, "fehler": message}
    try:
        voices = fetch_voices(s)
        models = fetch_models(s)
    except TTSError as exc:
        _set_state(sid, status="fehler", last_error=str(exc)[:500], geprueft_am=time.strftime("%Y-%m-%d %H:%M"))
        return {"ok": False, "fehler": str(exc)}
    fields = {"status": "ok", "last_error": "", "stimmen": voices, "modelle": models, "regie": fetch_regie(s),
              "geprueft_am": time.strftime("%Y-%m-%d %H:%M"),
              "sprache_erkannt": None if any(v.get("sprache") for v in voices) else detect_language(s)}
    if not s.get("modell") and models:
        fields["modell"] = models[0]
    _set_state(sid, **fields)
    return {"ok": True, "stimmen": len(voices), "modelle": models, "regie": bool(fields["regie"])}


def _voice_info(s: dict, voice: str) -> dict:
    for v in s.get("stimmen") or []:
        if v["id"] == voice:
            return v
    return _voice(voice)


def language_of(s: dict, voice: str) -> str | None:
    return _voice_info(s, voice).get("sprache") or s.get("sprache") or s.get("sprache_erkannt") or None


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    """Rohes PCM (mono, 16 bit, little endian) in einen WAV-Kopf packen."""
    pcm = pcm[: len(pcm) - len(pcm) % 2]
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<I", 16) + fmt
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def _locale_of(voice: str, language: str | None) -> str:
    """Google/Azure: Sprache steckt im Stimmennamen (de-DE-Neural2-A, de-DE-KatjaNeural)."""
    parts = voice.split("-")
    if len(parts) >= 3 and 2 <= len(parts[0]) <= 3:
        return f"{parts[0]}-{parts[1]}"
    return language or "de-DE"


def _not_audio(s: dict, raw: bytes, ctype: str) -> TTSError:
    hint = raw[:200].decode("utf-8", "replace") if "json" in ctype or raw[:1] in (b"{", b"[") else ctype
    return TTSError(f"{s.get('name')}: keine Audio-Antwort ({hint}).")


def synth(s: dict, text: str, voice: str, language: str | None = None, extra: dict | None = None) -> bytes:
    """Ein Stück Text sprechen lassen; liefert WAV-Bytes. extra: Zusatzfelder der Regie (style, pace) – nur an
    OpenAI-kompatible eigene Server (OpenAI selbst lehnt unbekannte Felder ab)."""
    typ = s.get("typ")
    if typ == "elevenlabs":
        model = s.get("modell") or "eleven_multilingual_v2"
        body = {"text": text, "model_id": model}
        if language and s.get("sprache"):
            body["language_code"] = language.split("-")[0]  # Modelle ohne Unterstützung ignorieren das Feld
        raw, ctype = _http(s, "POST", f"/text-to-speech/{urllib.parse.quote(voice, safe='')}"
                                      f"?output_format=pcm_{ELEVEN_PCM_RATE}", body)
        if raw[:1] in (b"{", b"[") or "json" in ctype:
            raise _not_audio(s, raw, ctype)
        return raw if raw[:4] == b"RIFF" else pcm_to_wav(raw, ELEVEN_PCM_RATE)
    if typ == "google":
        from .audio import has_ssml, to_ssml
        source = {"ssml": f"<speak>{to_ssml(text)}</speak>"} if has_ssml(text) else {"text": text}
        body = {"input": source, "voice": {"languageCode": _locale_of(voice, language), "name": voice},
                "audioConfig": {"audioEncoding": "LINEAR16"}}
        raw, ctype = _http(s, "POST", "/text:synthesize", body)
        try:
            audio = base64.b64decode(json.loads(raw.decode("utf-8"))["audioContent"])
        except (ValueError, KeyError, TypeError):
            raise _not_audio(s, raw, ctype)
        return audio if audio[:4] == b"RIFF" else pcm_to_wav(audio, 24000)
    if typ == "azure":
        from .audio import to_ssml
        locale = _locale_of(voice, language)
        ssml = (f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{locale}'>"
                f"<voice name='{xml_escape(voice, {chr(39): '&apos;'})}'>"
                f"{to_ssml(text, allow_lang='multilingual' in voice.lower())}</voice></speak>")
        raw, ctype = _http(s, "POST", "/cognitiveservices/v1", ssml.encode("utf-8"),
                           headers={"Content-Type": "application/ssml+xml",
                                    "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm"})
    elif typ == "piper":
        raw, ctype = _http(s, "POST", "/", {"text": text, "voice": voice})
    else:
        body = {"model": s.get("modell") or "tts-1", "input": text, "voice": voice, "response_format": "wav"}
        if language and s.get("preset") != "openai":  # OpenAI lehnt unbekannte Felder ab
            body["language"] = language.split("-")[0]
        if extra and s.get("preset") != "openai":
            body.update({k: v for k, v in extra.items() if v})
        raw, ctype = _http(s, "POST", "/audio/speech", body)
    if raw[:4] != b"RIFF":
        hint = raw[:200].decode("utf-8", "replace") if "json" in ctype or raw[:1] in (b"{", b"[") else ctype
        raise TTSError(f"{s.get('name')}: keine WAV-Antwort ({hint}).")
    return raw


# ---------------------------------------------------------------- WAV

def decode_wav(data: bytes) -> tuple:
    """WAV (PCM 8/16/24/32 bit oder Float 32/64, auch Streaming-Kopf mit Länge 0xFFFFFFFF) → (Rate, mono int16)."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise TTSError("Keine WAV-Datei.")
    pos, fmt, pcm = 12, None, None
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        body = pos + 8
        if cid == b"fmt ":
            tag, channels, rate, _, _, bits = struct.unpack_from("<HHIIHH", data, body)
            if tag == 0xFFFE and size >= 26:
                tag = struct.unpack_from("<H", data, body + 24)[0]
            fmt = (tag, channels, rate, bits)
        elif cid == b"data":
            end = len(data) if size in (0, 0xFFFFFFFF) or body + size > len(data) else body + size
            pcm = data[body:end]
            break
        if size == 0xFFFFFFFF:
            break
        pos = body + size + (size & 1)
    if fmt is None or pcm is None:
        raise TTSError("WAV ohne fmt- oder data-Block.")
    tag, channels, rate, bits = fmt
    width = bits // 8
    frame = width * max(channels, 1)
    pcm = pcm[: len(pcm) - len(pcm) % frame] if frame else pcm
    if tag == 1 and bits == 16:
        samples = array("h")
        samples.frombytes(pcm)
        if sys.byteorder == "big":
            samples.byteswap()
    elif tag == 1 and bits == 8:
        samples = array("h", ((b - 128) << 8 for b in pcm))
    elif tag == 1 and bits == 24:
        samples = array("h", (int.from_bytes(pcm[i:i + 3], "little", signed=True) >> 8 for i in range(0, len(pcm), 3)))
    elif tag == 1 and bits == 32:
        wide = array("i")
        wide.frombytes(pcm)
        if sys.byteorder == "big":
            wide.byteswap()
        samples = array("h", (x >> 16 for x in wide))
    elif tag == 3 and bits in (32, 64):
        floats = array("f" if bits == 32 else "d")
        floats.frombytes(pcm)
        if sys.byteorder == "big":
            floats.byteswap()
        samples = array("h", (int(32767 * (1.0 if x > 1.0 else -1.0 if x < -1.0 else x)) for x in floats))
    else:
        raise TTSError(f"WAV-Format nicht unterstützt (Format {tag}, {bits} bit).")
    if channels > 1:
        samples = samples[::channels]  # erster Kanal
    return rate, samples


def resample(samples: array, src: int, dst: int) -> array:
    """Lineare Umrechnung der Abtastrate (nur nötig, wenn Server unterschiedliche Raten liefern)."""
    if src == dst or not samples:
        return samples
    count = int(len(samples) * dst / src)
    step, last = src / dst, len(samples) - 1
    out = array("h", bytes(2 * count))
    for i in range(count):
        x = i * step
        j = int(x)
        a = samples[j]
        b = samples[j + 1] if j < last else a
        out[i] = int(a + (b - a) * (x - j))
    return out


# ---------------------------------------------------------------- Text zerlegen

_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_CLAUSE = re.compile(r"(?<=[,;:–—])\s+")


def chunk_text(text: str, limit: int) -> list:
    """An Satzgrenzen in Stücke ≤ limit zerlegen; überlange Sätze an Kommas, notfalls an Wortgrenzen."""
    text = " ".join((text or "").split())
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    pieces = []
    for sentence in _SENTENCE.split(text):
        if len(sentence) <= limit:
            pieces.append(sentence)
            continue
        for clause in _CLAUSE.split(sentence):
            while len(clause) > limit:
                cut = clause.rfind(" ", 0, limit)
                cut = cut if cut > limit // 3 else limit
                start = clause.rfind("\uE000", 0, cut)  # Aussprache-Platzhalter (audio.apply_lexicon) nie zerteilen
                if start > clause.rfind("\uE001", 0, cut):
                    cut = start if start > 0 else (clause.find("\uE001", cut) + 1 or limit)
                pieces.append(clause[:cut].strip())
                clause = clause[cut:].strip()
            if clause:
                pieces.append(clause)
    chunks, current = [], ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) > limit:
            chunks.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------- Besetzung und Folgen-Einstellungen (je Welt)

def _meta_json(conn: sqlite3.Connection, key: str, default):
    row = conn.execute("SELECT value FROM world_meta WHERE key = ?", (key,)).fetchone()
    try:
        return json.loads(row[0]) if row and row[0] else default
    except ValueError:
        return default


def cast(conn: sqlite3.Connection) -> dict:
    """Sprecher → „server_id|stimme“ (gilt für alle Folgen der Welt)."""
    return _meta_json(conn, "tts.besetzung", {})


def set_cast(conn: sqlite3.Connection, changes: dict) -> dict:
    current = cast(conn)
    for speaker, ref in (changes or {}).items():
        speaker = str(speaker).strip()
        if not speaker:
            continue
        if ref:
            _split_ref(ref)
            current[speaker] = str(ref)
        else:
            current.pop(speaker, None)
    service.set_meta(conn, "tts.besetzung", json.dumps(current, ensure_ascii=False))
    return current


def episode_settings(conn: sqlite3.Connection, episode_id: int) -> dict:
    from . import regie
    data = _meta_json(conn, f"tts.folge.{episode_id}", {})
    return {"modus": data.get("modus") if data.get("modus") in MODI else "hoerspiel", "stimme": data.get("stimme") or "",
            "regie": data.get("regie") if data.get("regie") in regie.STUFEN else regie.STANDARD_STUFE}


def set_episode_settings(conn: sqlite3.Connection, episode_id: int, data: dict) -> dict:
    current = episode_settings(conn, episode_id)
    if "modus" in data:
        if data["modus"] not in MODI:
            raise ValueError("Unbekannter Modus.")
        current["modus"] = data["modus"]
    if "stimme" in data:
        if data["stimme"]:
            _split_ref(data["stimme"])
        current["stimme"] = data["stimme"] or ""
    if "regie" in data:
        from . import regie
        if data["regie"] not in regie.STUFEN:
            raise ValueError("Unbekannte Regie-Stufe.")
        current["regie"] = data["regie"]
    service.set_meta(conn, f"tts.folge.{episode_id}", json.dumps(current, ensure_ascii=False))
    return current


def _split_ref(ref: str) -> tuple:
    if not isinstance(ref, str) or "|" not in ref:
        raise ValueError("Stimme bitte als Server|Stimme angeben.")
    sid, voice = ref.split("|", 1)
    return sid, voice


def plan(conn: sqlite3.Connection, episode_id: int, cfg: dict | None = None) -> dict:
    """Wer spricht was mit welcher Stimme. Figuren ohne Besetzung bekommen reihum Stimmen vom Server des Erzählers
    (gleiche Sprache, ohne bereits vergebene Stimmen)."""
    cfg = cfg or _cfg()
    by_id = {s["id"]: s for s in servers(cfg)}
    ep = episodes.get_episode(conn, episode_id)
    settings = episode_settings(conn, episode_id)
    besetzung = cast(conn)

    def usable(ref):
        if not ref:
            return None
        sid, voice = _split_ref(ref)
        return (sid, voice) if sid in by_id and voice else None

    narrator = usable(besetzung.get(episodes.NARRATOR))
    assigned: dict = {}
    if settings["modus"] == "hoerbuch":
        single = usable(settings["stimme"]) or narrator
        for seg in ep["segmente"]:
            if seg["sprecher"] not in assigned:
                assigned[seg["sprecher"]] = (single, "folge" if usable(settings["stimme"]) else "besetzung")
    else:
        taken = {v for v in (usable(r) for r in besetzung.values()) if v}
        pool = []
        if narrator:
            server = by_id[narrator[0]]
            lang = language_of(server, narrator[1])
            pool = [(server["id"], v["id"]) for v in server.get("stimmen") or []
                    if (server["id"], v["id"]) not in taken and v["id"] != "default"
                    and (not lang or not v.get("sprache") or v["sprache"].split("-")[0] == lang.split("-")[0])]
        turn = 0
        for seg in ep["segmente"]:
            speaker = seg["sprecher"]
            if speaker in assigned:
                continue
            if seg["typ"] == "narrator":
                assigned[speaker] = (narrator, "besetzung")
            elif usable(besetzung.get(speaker)):
                assigned[speaker] = (usable(besetzung[speaker]), "besetzung")
            elif pool:
                assigned[speaker] = (pool[turn % len(pool)], "automatisch")
                turn += 1
            else:
                assigned[speaker] = (narrator, "erzaehler")
    sprecher, missing = {}, []
    for speaker, (ref, source) in assigned.items():
        if not ref:
            missing.append(speaker)
            sprecher[speaker] = {"server": None, "stimme": None, "sprache": None, "quelle": "fehlt"}
            continue
        server = by_id[ref[0]]
        sprecher[speaker] = {"server": ref[0], "stimme": ref[1], "stimme_name": _voice_info(server, ref[1])["name"],
                             "sprache": language_of(server, ref[1]), "quelle": source}
    segmente = [dict(seg, server=sprecher[seg["sprecher"]]["server"], stimme=sprecher[seg["sprecher"]]["stimme"],
                     sprache=sprecher[seg["sprecher"]]["sprache"]) for seg in ep["segmente"]]
    used = {v["server"] for v in sprecher.values() if v["server"]}
    return {"folge": ep["release_nr"], "titel": ep["title"], "form": ep.get("form") or "folge",
            "modus": settings["modus"], "einstellung": settings,
            "sprecher": sprecher, "fehlt": missing, "segmente": segmente,
            "server": {sid: {"name": by_id[sid]["name"], "typ": by_id[sid]["typ"], "url": by_id[sid]["base_url"],
                             "modell": by_id[sid].get("modell") or None,
                             "max_zeichen": by_id[sid].get("max_zeichen") or DEFAULT_MAX_CHARS} for sid in sorted(used)}}


# ---------------------------------------------------------------- Vertonen

def output_dir(slug: str) -> Path:
    path = worlds.worlds_dir() / "audio" / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def _target(slug: str, nr: int, title: str | None) -> Path:
    safe = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_-]+", "_", title or "Folge").strip("_")
    return output_dir(slug) / f"Folge_{nr:03d}_{safe}_TTS.wav"


def output_file(conn: sqlite3.Connection, slug: str, episode_id: int) -> Path | None:
    row = conn.execute("SELECT release_nr, title FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if row is None:
        raise LookupError("Folge nicht gefunden.")
    path = _target(slug, row[0], row[1])
    if path.with_suffix(".mp3").exists():
        return path.with_suffix(".mp3")
    return path if path.exists() else None


def _set_aside(path: Path) -> None:
    """Vorhandenes Ergebnis nicht überschreiben, sondern nach _alt verschieben."""
    if path.exists():
        old = path.parent / "_alt"
        old.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(path.stat().st_mtime))
        path.replace(old / f"{path.stem}_{stamp}{path.suffix}")


def _cached_chunk(cache: Path, s: dict, text: str, voice: str, language: str | None, speak,
                  extra: dict | None = None) -> bytes:
    ident = [s["base_url"], s.get("typ"), s.get("modell"), voice, language, text] + ([extra] if extra else [])
    key = hashlib.sha1(json.dumps(ident, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    path = cache / f"{key}.wav"
    if path.exists():
        return path.read_bytes()
    error = None
    for attempt in range(RETRIES + 1):
        try:
            data = speak(s, text, voice, language, extra) if extra else speak(s, text, voice, language)
            decode_wav(data)  # prüfen, bevor es in den Zwischenspeicher geht
            tmp = path.with_name(f"{path.stem}.{threading.get_ident()}.tmp")
            tmp.write_bytes(data)
            tmp.replace(path)  # atomar: Vertonung und Einzel-Absatz können parallel dieselbe Datei schreiben
            return data
        except TTSError as exc:
            error = exc
            time.sleep(1.5 * (attempt + 1))
    raise error


def speak_single(segments: list, ref: str, target: Path, words: list | None = None, speak=None,
                 cfg: dict | None = None) -> dict:
    """Kurzen Text mit EINER Stimme vertonen (Hörbuch-Modus), z. B. die Probe einer Schreibstil-Stimme.
    segments: Texte in Lesereihenfolge. Ein vorhandenes Ergebnis wird nach _alt verschoben, nicht überschrieben."""
    from . import audio
    speak = speak or synth
    sid, voice = _split_ref(ref)
    server = get_server(sid, cfg)
    language = language_of(server, voice)
    limit = int(server.get("max_zeichen") or DEFAULT_MAX_CHARS)
    ssml = server.get("typ") in SSML_TYPES
    parts = [chunk_text(audio.apply_lexicon(t, words or [], ssml), limit) for t in segments if (t or "").strip()]
    if not parts:
        raise TTSError("Kein Text zum Vorlesen.")
    target.parent.mkdir(parents=True, exist_ok=True)
    cache = target.parent.parent / "_tts_cache"
    cache.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".teil.wav")
    writer, rate, pieces = None, None, 0
    try:
        for n, chunks in enumerate(parts):
            if writer is not None and n:
                writer.writeframes(bytes(2 * int(rate * PAUSE_SEGMENT_SAME)))
            for index, chunk in enumerate(chunks):
                src, samples = decode_wav(_cached_chunk(cache, server, chunk, voice, language, speak))
                if writer is None:
                    rate = src
                    writer = wave.open(str(partial), "wb")
                    writer.setnchannels(1)
                    writer.setsampwidth(2)
                    writer.setframerate(rate)
                samples = resample(samples, src, rate)
                if sys.byteorder == "big":
                    samples.byteswap()
                if index:
                    writer.writeframes(bytes(2 * int(rate * PAUSE_CHUNK)))
                writer.writeframes(samples.tobytes())
                pieces += 1
    finally:
        if writer is not None:
            writer.close()
    _set_aside(target)
    partial.replace(target)
    return {"server": server.get("name"), "stimme": voice, "stimme_name": _voice_info(server, voice)["name"],
            "stuecke": pieces, "abtastrate": rate}


def _segment_pieces(s: dict, parts: list, words: list) -> list:
    """Teile eines Absatzes → [(Stücke ≤ max_zeichen, Zusatzfelder)]; Tags überstehen Lexikon und Zerlegen."""
    from . import audio, regie
    limit = int(s.get("max_zeichen") or DEFAULT_MAX_CHARS)
    out = []
    for text, extra in parts:
        chunks = chunk_text(audio.apply_lexicon(regie.schuetzen(text), words, s.get("typ") in SSML_TYPES), limit)
        out.append(([regie.zurueck(c) for c in chunks], extra))
    return out


TEILE = "_teile"
_TEIL_NAME = re.compile(r"^\d{4}-t\d{1,4}-[0-9a-f]{10}\.wav$")


def segment_file(slug: str, episode_id: int, name: str) -> Path:
    if not _TEIL_NAME.match(name or ""):
        raise LookupError("Ungültiger Dateiname.")
    path = output_dir(slug) / TEILE / str(int(episode_id)) / name
    if not path.is_file():
        raise LookupError("Diesen Take gibt es (noch) nicht als Datei.")
    return path


def segment_take(conn: sqlite3.Connection, slug: str, episode_id: int, nr: int, take: int | None = None,
                 neu: bool = False, waehlen: bool = False, speak=None, cfg: dict | None = None,
                 job_id: int | None = None) -> dict:
    """Einen Absatz einzeln sprechen (zum Anhören) – gewählter Take, ein bestimmter Take oder ein neuer (neu=True).
    Die Stücke landen im selben Zwischenspeicher wie beim Zusammenfügen; die WAV je Take liegt unter
    _teile/<folge>/ und bleibt erhalten (Takes sind frei wählbar und tauschbar)."""
    from . import audio, regie
    speak = speak or synth
    own_cfg = cfg is None
    cfg = cfg or _cfg()
    by_id = {s["id"]: s for s in servers(cfg)}
    p = plan(conn, episode_id, cfg)
    if not 1 <= int(nr) <= len(p["segmente"]):
        raise LookupError(f"Absatz {nr} gibt es nicht.")
    seg = p["segmente"][int(nr) - 1]
    if not seg.get("server"):
        raise TTSError(f"Keine Stimme für {seg['sprecher']}.")
    if own_cfg:
        if by_id[seg["server"]].get("mitgeliefert"):
            from . import libra
            try:
                libra.eintragen(libra.bereit())
            except Exception as exc:
                raise TTSError(f"Libra-TTS (mitgeliefert) ist nicht bereit: {exc}")
        ensure_regie(p["server"])
        cfg = _cfg()
        by_id = {s["id"]: s for s in servers(cfg)}
        p = plan(conn, episode_id, cfg)
        seg = p["segmente"][int(nr) - 1]
    s = by_id[seg["server"]]
    caps = regie.faehig(s)
    stufe = p["einstellung"]["regie"]
    if caps and stufe != "aus" and regie.gueltig(conn, episode_id) is None:  # einmal KI-Regie für die ganze Folge
        regie.sicherstellen(conn, episode_id, stufe, regie.vereinigen([regie.faehig(by_id[x]) for x in p["server"]]),
                            job_id=job_id)
    if neu:
        if not caps:
            raise TTSError("Neue Takes gehen nur mit Servern, die einen Seed kennen (z. B. Libra-TTS).")
        take = regie.take_neu(conn, episode_id, int(nr))
    elif take is not None and waehlen:
        regie.take_waehlen(conn, episode_id, int(nr), int(take))
    data = regie.gueltig(conn, episode_id)
    chosen, all_takes = regie.takes(data, int(nr) - 1)
    use = chosen if take is None else int(take)
    if use not in all_takes:
        raise ValueError(f"Absatz {nr}: Take {use + 1} gibt es nicht.")
    parts = regie.teile_fuer_segment(data, int(nr) - 1, s, seg["text"], nur_take=stufe == "aus", take=use)
    pieces = _segment_pieces(s, parts, audio.lexicon(conn))
    cache = output_dir(slug) / "_tts_cache"
    cache.mkdir(parents=True, exist_ok=True)
    ident = hashlib.sha1(json.dumps([s["base_url"], s.get("modell"), seg["stimme"], seg["sprache"], pieces],
                                    ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    target = output_dir(slug) / TEILE / str(int(episode_id)) / f"{int(nr):04d}-t{use}-{ident}.wav"
    rate, frames = None, 0
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".teil.wav")
        writer = None
        try:
            for chunks, extra in pieces:
                for chunk in chunks:
                    src, samples = decode_wav(_cached_chunk(cache, s, chunk, seg["stimme"], seg["sprache"], speak, extra))
                    if writer is None:
                        rate = src
                        writer = wave.open(str(partial), "wb")
                        writer.setnchannels(1)
                        writer.setsampwidth(2)
                        writer.setframerate(rate)
                    else:
                        writer.writeframes(bytes(2 * int(rate * PAUSE_CHUNK)))
                    samples = resample(samples, src, rate)
                    if sys.byteorder == "big":
                        samples.byteswap()
                    writer.writeframes(samples.tobytes())
        finally:
            if writer is not None:
                writer.close()
        partial.replace(target)
    with wave.open(str(target), "rb") as fh:
        rate, frames = fh.getframerate(), fh.getnframes()
    return {"nr": int(nr), "take": use, "gewaehlt": regie.takes(regie.gueltig(conn, episode_id), int(nr) - 1)[0],
            "takes": regie.takes(regie.gueltig(conn, episode_id), int(nr) - 1)[1], "datei": target.name,
            "sekunden": round(frames / rate, 1) if rate else 0}


_RUNNING: set = set()
_RUNNING_LOCK = threading.Lock()


def is_rendering(slug: str, episode_id: int) -> bool:
    with _RUNNING_LOCK:
        return (slug, int(episode_id)) in _RUNNING


def render(conn: sqlite3.Connection, slug: str, episode_id: int, job_id: int | None = None, speak=None,
           cfg: dict | None = None, as_mp3: bool | None = None) -> Path:
    """Folge über die TTS-Server vertonen. speak/cfg sind für Tests austauschbar.
    as_mp3: None = MP3, wenn lame/ffmpeg vorhanden; False = nur WAV.
    Je Folge läuft höchstens eine Vertonung (gleiche Teil- und Zieldateien)."""
    key = (slug, int(episode_id))
    with _RUNNING_LOCK:
        if key in _RUNNING:
            raise TTSError("Diese Folge wird gerade schon vertont – bitte warten, bis der Lauf fertig ist.")
        _RUNNING.add(key)
    try:
        return _render(conn, slug, episode_id, job_id, speak, cfg, as_mp3)
    finally:
        with _RUNNING_LOCK:
            _RUNNING.discard(key)


def _render(conn: sqlite3.Connection, slug: str, episode_id: int, job_id: int | None, speak, cfg: dict | None,
            as_mp3: bool | None) -> Path:
    from . import audio, regie  # Aussprache-Lexikon und Pausen wie bei der macOS-Vertonung

    speak = speak or synth
    own_cfg = cfg is None
    cfg = cfg or _cfg()
    by_id = {s["id"]: s for s in servers(cfg)}
    p = plan(conn, episode_id, cfg)
    if own_cfg and any(by_id[sid].get("mitgeliefert") for sid in p["server"]):
        from . import libra  # mitgelieferter Server: starten bzw. abwarten, Adresse (Port) aktualisieren
        try:
            libra.eintragen(libra.bereit())
        except Exception as exc:
            raise TTSError(f"Libra-TTS (mitgeliefert) ist nicht bereit: {exc}")
        cfg = _cfg()
        by_id = {s["id"]: s for s in servers(cfg)}
        p = plan(conn, episode_id, cfg)
    if own_cfg and any("regie" not in by_id[sid] for sid in p["server"]):
        ensure_regie(p["server"])  # Stile/Geräusche erkennen, auch ohne erneutes „Prüfen“
        cfg = _cfg()
        by_id = {s["id"]: s for s in servers(cfg)}
    if not p["segmente"]:
        raise TTSError("Die Folge enthält keinen Text.")
    if p["fehlt"]:
        raise TTSError("Keine Stimme für: " + ", ".join(p["fehlt"]) + ". Bitte Erzähler-Stimme bzw. Hörbuch-Stimme wählen.")
    words = audio.lexicon(conn)
    first_voice = next((p["sprecher"][seg["sprecher"]] for seg in p["segmente"] if seg["typ"] == "narrator"),
                       p["sprecher"][p["segmente"][0]["sprecher"]])
    intro = {"sprecher": episodes.NARRATOR, "typ": "narrator",
             "text": f"{p['titel'] or ''}." if p.get("form") == "geschichte" else f"Folge {p['folge']}. {p['titel'] or ''}.",
             "server": first_voice["server"], "stimme": first_voice["stimme"], "sprache": first_voice["sprache"]}
    caps = regie.vereinigen([regie.faehig(by_id[sid]) for sid in p["server"]])
    notes: list = []
    direction = regie.sicherstellen(conn, episode_id, p["einstellung"]["regie"], caps, job_id=job_id,
                                    log=notes.append) if caps else None
    takes = direction or (regie.gueltig(conn, episode_id) if caps else None)  # neue Takes gelten auch ohne Regie
    items, spoken_segments = [], []  # items: (Segment, Stücke, Zusatzfelder, erster Teil des Absatzes?)
    for n, seg in enumerate([intro] + p["segmente"]):
        s = by_id[seg["server"]]
        parts = regie.teile_fuer_segment(takes, n - 1, s, seg["text"], nur_take=direction is None) if n \
            else [(seg["text"], {})]
        if n:  # fürs Begleit-JSON: Text mit Geräusch-Tags und Stil, so wie gesprochen
            spoken_segments.append(dict(seg, **regie.sprechfassung(parts, seg["text"])))
        for k, (chunks, extra) in enumerate(_segment_pieces(s, parts, words)):
            items.append((seg, chunks, extra, k == 0))
    total = sum(len(c) for _, c, _, _ in items) or 1
    conn.commit()  # Protokoll schreibt über eine eigene Verbindung
    run = runs.Run(conn, "Hörbuch (TTS-Server)", f"Folge {p['folge']}: {p['titel'] or ''}", "audio",
                   f"Folge {p['folge']} über TTS-Server vertonen – {MODI[p['modus']]}, {len(p['segmente'])} Absätze, "
                   f"{total} Stücke", job_id=job_id)
    cache = output_dir(slug) / "_tts_cache"
    cache.mkdir(exist_ok=True)
    target = _target(slug, p["folge"], p["titel"])
    partial = target.with_suffix(".teil.wav")
    try:
        run.step("Stimmen: " + ", ".join(f"{k} → {by_id[v['server']]['name']}/{v.get('stimme_name') or v['stimme']}"
                                          for k, v in p["sprecher"].items() if v["server"]), 2)
        for note in notes:
            run.step(note, None, "warnung")
        if direction:
            styled = sum(1 for _, _, extra, _ in items if extra.get("style"))
            tags = sum(len(regie._TAG.findall(c)) for _, chunks, _, _ in items for c in chunks)
            run.step(f"Regie ({regie.STUFEN.get(direction.get('stufe'), 'von Hand').split(' –')[0]}): "
                     f"{styled} Teile mit Sprechstil, {tags} Geräusche", 2)
        retakes = sum(1 for e in (takes or {}).get("segmente") or [] if e.get("take"))
        if retakes:
            run.step(f"{retakes} Absätze mit gewähltem anderem Take; schon Gesprochenes kommt aus dem Zwischenspeicher", 2)
        done, rate, writer, previous = 0, None, None, None
        try:
            for seg, chunks, extra, first in items:
                s = by_id[seg["server"]]
                if writer is not None and previous is not None:
                    if not first:  # Stilwechsel im selben Absatz: nur kurze Pause
                        pause = PAUSE_CHUNK
                    else:
                        pause = PAUSE_SEGMENT_SAME if seg["sprecher"] == previous else PAUSE_SEGMENT_CHANGE
                    writer.writeframes(bytes(2 * int(rate * pause)))
                for index, chunk in enumerate(chunks):
                    src, samples = decode_wav(_cached_chunk(cache, s, chunk, seg["stimme"], seg["sprache"], speak, extra))
                    if writer is None:
                        rate = src
                        writer = wave.open(str(partial), "wb")
                        writer.setnchannels(1)
                        writer.setsampwidth(2)
                        writer.setframerate(rate)
                    samples = resample(samples, src, rate)
                    if sys.byteorder == "big":
                        samples.byteswap()
                    if index:
                        writer.writeframes(bytes(2 * int(rate * PAUSE_CHUNK)))
                    writer.writeframes(samples.tobytes())
                    done += 1
                    if done % max(1, total // 25) == 0 or done == total:
                        run.step(f"{done}/{total} Stücke gesprochen", 3 + int(92 * done / total))
                previous = seg["sprecher"]
        finally:
            if writer is not None:
                writer.close()
        _set_aside(target)
        partial.replace(target)
        final = target
        if as_mp3 is None:
            as_mp3 = mp3.available()
        if as_mp3:
            ep = episodes.get_episode(conn, episode_id)
            speakers = [first_voice.get("stimme_name") or first_voice["stimme"]] + \
                       [v.get("stimme_name") or v["stimme"] for v in p["sprecher"].values() if v["server"]]
            final = mp3.from_wav(target, target.with_suffix(".mp3"), mp3.episode_tags(conn, ep, speakers, p["modus"]))
            quarantine = output_dir(slug) / "_wav"
            quarantine.mkdir(exist_ok=True)
            _set_aside(quarantine / target.name)
            target.replace(quarantine / target.name)  # WAV nicht löschen, sondern beiseitelegen
            run.step("MP3 mit ID3-Tags gespeichert", 98)
        else:
            _set_aside(target.with_suffix(".mp3"))  # ältere MP3 würde sonst statt der neuen WAV ausgeliefert
        target.with_suffix(".json").write_text(json.dumps(
            {k: v for k, v in p.items() if k != "segmente"} | {"datei": final.name, "erstellt": time.strftime("%Y-%m-%d %H:%M"),
                                                              "abtastrate": rate, "stuecke": total,
                                                              "regie": regie.zusammenfassung(conn, episode_id),
                                                              "segmente": spoken_segments},
            ensure_ascii=False, indent=1), encoding="utf-8")
        relative = str(final.relative_to(worlds.worlds_dir()))
        run.step(f"Hörbuch gespeichert: {relative}", 100, "ok")
        run.finish("fertig")
        return final
    except Exception as exc:
        run.step(f"Abgebrochen: {exc} – bereits gesprochene Stücke liegen im Zwischenspeicher, ein neuer Start macht dort weiter.",
                 None, "fehler")
        run.finish("fehler", error=str(exc)[:1000])
        raise
