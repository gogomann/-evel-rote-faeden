"""KI-Anbieter: beliebig viele Anbieter, Schlüsselprüfung, Modelle laden, Modellketten je Aufgabe.

Konfiguration liegt in story_world.config.json (Projektordner, per .gitignore ausgeschlossen, Dateirechte 0600)
oder unter dem Pfad aus STORY_CONFIG. Nur Python-Standardbibliothek.
Entfernte Anbieter werden nicht gelöscht, sondern unter "archiv" aufbewahrt.
"""

from __future__ import annotations

import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.RLock()

PRESETS = [
    {"id": "openrouter", "name": "OpenRouter", "type": "openai", "base_url": "https://openrouter.ai/api/v1",
     "needs_key": True, "key_url": "https://openrouter.ai/settings/keys",
     "info": "Ein Schlüssel für Hunderte Modelle vieler Anbieter (Claude, GPT, Gemini, Llama …). "
             "Guthaben aufladen, Schlüssel erstellen, fertig. Ideal für den Einstieg."},
    {"id": "openai", "name": "OpenAI", "type": "openai", "base_url": "https://api.openai.com/v1",
     "needs_key": True, "key_url": "https://platform.openai.com/api-keys",
     "info": "GPT-Modelle. Abgerechnet wird über Guthaben im OpenAI-Plattformkonto (nicht ChatGPT Plus)."},
    {"id": "anthropic", "name": "Anthropic (Claude)", "type": "anthropic", "base_url": "https://api.anthropic.com/v1",
     "needs_key": True, "key_url": "https://console.anthropic.com/settings/keys",
     "info": "Claude-Modelle. Konto in der Anthropic Console mit Guthaben (nicht das Claude-Abo)."},
    {"id": "gemini", "name": "Google Gemini", "type": "openai",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "needs_key": True, "key_url": "https://aistudio.google.com/apikey",
     "info": "Gemini-Modelle über Google AI Studio. Es gibt ein kostenloses Kontingent."},
    {"id": "mistral", "name": "Mistral AI", "type": "openai", "base_url": "https://api.mistral.ai/v1",
     "needs_key": True, "key_url": "https://console.mistral.ai/api-keys",
     "info": "Europäischer Anbieter (Frankreich)."},
    {"id": "groq", "name": "Groq", "type": "openai", "base_url": "https://api.groq.com/openai/v1",
     "needs_key": True, "key_url": "https://console.groq.com/keys",
     "info": "Sehr schnelle Antworten mit offenen Modellen."},
    {"id": "deepseek", "name": "DeepSeek", "type": "openai", "base_url": "https://api.deepseek.com/v1",
     "needs_key": True, "key_url": "https://platform.deepseek.com/api_keys",
     "info": "Günstige, starke Modelle."},
    {"id": "xai", "name": "xAI (Grok)", "type": "openai", "base_url": "https://api.x.ai/v1",
     "needs_key": True, "key_url": "https://console.x.ai",
     "info": "Grok-Modelle."},
    {"id": "together", "name": "Together AI", "type": "openai", "base_url": "https://api.together.xyz/v1",
     "needs_key": True, "key_url": "https://api.together.ai/settings/api-keys",
     "info": "Viele offene Modelle zu günstigen Preisen."},
    {"id": "ollama", "name": "Ollama (lokal)", "type": "openai", "base_url": "http://localhost:11434/v1",
     "needs_key": False, "key_url": "https://ollama.com/download",
     "info": "Läuft auf deinem Rechner, kostenlos, kein Schlüssel. Ollama installieren und ein Modell laden, "
             "z. B. im Terminal: ollama pull llama3.1"},
    {"id": "lmstudio", "name": "LM Studio (lokal)", "type": "openai", "base_url": "http://localhost:1234/v1",
     "needs_key": False, "key_url": "https://lmstudio.ai",
     "info": "Lokale Modelle mit Oberfläche. In LM Studio unter „Developer“ den lokalen Server starten."},
    {"id": "custom", "name": "Eigenes Gateway (OpenAI-kompatibel)", "type": "openai", "base_url": "",
     "needs_key": False, "key_url": "",
     "info": "LiteLLM, vLLM, LocalAI oder jedes andere OpenAI-kompatible Gateway. Die Adresse endet meist auf /v1."},
]
PRESET_BY_ID = {p["id"]: p for p in PRESETS}

TASKS = [
    ("standard", "Standard", "Wird genutzt, wenn eine Aufgabe keine eigenen Modelle hat."),
    ("weltenbau", "Weltenbau", "Impulse und Nachrichten in die Welt einarbeiten."),
    ("luecken", "Lücken füllen", "Fehlende Steckbrief-Angaben ergänzen."),
    ("einschuebe", "Einschübe & Sammelsurium", "Kleine Extras, die eingestreut werden, wenn zu wenig passiert."),
    ("planer", "Folgen planen", "Wählt Strang, Zeit, Figuren und Kapitelablauf der nächsten Folge."),
    ("autor", "Folgen schreiben", "Schreibt die Folge Kapitel für Kapitel."),
    ("pruefer", "Kontinuität prüfen", "Sollte ein anderes Modell als der Autor sein."),
    ("lektor", "Lektorat", "Immer dasselbe Modell für einheitlichen Stil."),
    ("archivar", "Archivar", "Trägt neue Fakten, Figuren und Zeitstand nach der Folge in den Kanon ein."),
    ("profil", "Erzählprofil", "Wertet das Interview aus und verdichtet es zur Erzählstimme eines Menschen."),
    ("thema", "Thema wählen (Kaskade)", "Erste Ebene der Kaskade: wählt Strang, Thema und Beteiligte aus einem kompakten Überblick."),
    ("erwartung", "Hörer-Erwartung", "Sieht nur, was der Hörer kennt, und schreibt auf, was er als Nächstes erwartet."),
    ("bewerter", "Szenarien bewerten", "Misst Kanonpassung und Überraschung der Szenarien – möglichst ein anderes Modell als der Planer."),
    ("richter", "Qualitäts-Richter", "Bewertet Texte im Prüfstand und im Modellvergleich (läuft mit Temperatur 0)."),
]
# Werte je Aufgabe (Expertenmodus). Fehlt ein Wert, gilt der Standard des Aufrufers.
TASK_PARAMS = {"temperatur": (0.0, 2.0)}
TASK_IDS = [t[0] for t in TASKS]
MAX_CHAIN = 3


class ProviderError(RuntimeError):
    pass


# ---------------------------------------------------------------- Konfigurationsdatei

def config_path() -> Path:
    return Path(os.environ.get("STORY_CONFIG", ROOT / "story_world.config.json"))


def _migrate_legacy(cfg: dict) -> dict:
    legacy = cfg.pop("llm", None)
    if legacy and legacy.get("base_url") and not cfg.get("providers"):
        pid = "p_" + uuid.uuid4().hex[:8]
        cfg["providers"] = [{"id": pid, "preset": "custom", "name": "Eigenes Gateway (übernommen)", "type": "openai",
                             "base_url": legacy["base_url"], "api_key": legacy.get("api_key", ""),
                             "models": [legacy["model"]] if legacy.get("model") else [], "status": "ungeprueft"}]
        if legacy.get("model"):
            cfg.setdefault("tasks", {})["standard"] = [{"provider": pid, "model": legacy["model"]}]
    return cfg


def load() -> dict:
    with _LOCK:
        path = config_path()
        cfg = {}
        if path.exists():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                # Kaputte Datei nicht überschreiben, sondern beiseitelegen
                path.rename(path.with_suffix(f".defekt-{int(time.time())}.json"))
                cfg = {}
        cfg = _migrate_legacy(cfg)
        cfg.setdefault("providers", [])
        cfg.setdefault("archiv", [])
        cfg.setdefault("tasks", {})
        cfg.setdefault("theme", {"active": "hell", "eigen": {}})
        return cfg


def save(cfg: dict) -> None:
    with _LOCK:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _env_provider() -> dict | None:
    base = os.environ.get("STORY_LLM_BASE_URL")
    if not base:
        return None
    model = os.environ.get("STORY_LLM_MODEL", "")
    return {"id": "env", "preset": "custom", "name": "Umgebungsvariablen", "type": "openai", "base_url": base,
            "api_key": os.environ.get("STORY_LLM_API_KEY", ""), "models": [model] if model else [],
            "status": "ungeprueft", "readonly": True}


def all_providers(cfg: dict | None = None) -> list:
    cfg = cfg or load()
    providers = list(cfg["providers"])
    env = _env_provider()
    if env:
        providers.append(env)
    return providers


def get_provider(pid: str, cfg: dict | None = None) -> dict:
    for p in all_providers(cfg):
        if p["id"] == pid:
            return p
    raise LookupError("Anbieter nicht gefunden.")


def mask(key: str) -> str:
    if not key:
        return ""
    return key[:4] + "…" + key[-4:] if len(key) > 10 else "…" + key[-2:]


def public_provider(p: dict) -> dict:
    out = {k: v for k, v in p.items() if k != "api_key"}
    out["api_key_maskiert"] = mask(p.get("api_key", ""))
    out["api_key_gesetzt"] = bool(p.get("api_key"))
    out["models_count"] = len(p.get("models") or [])
    preset = PRESET_BY_ID.get(p.get("preset"), {})
    out["preset_name"] = preset.get("name", "")
    return out


def public_settings() -> dict:
    cfg = load()
    return {
        "providers": [public_provider(p) for p in all_providers(cfg)],
        "archiv": [public_provider(p) for p in cfg["archiv"]],
        "presets": PRESETS,
        "tasks": [{"id": t[0], "label": t[1], "info": t[2], "kette": cfg["tasks"].get(t[0], []),
                   "werte": cfg.get("task_params", {}).get(t[0], {})} for t in TASKS],
        "theme": cfg["theme"],
        "config_datei": str(config_path()),
        "eingerichtet": bool(resolve_chain("standard", cfg) or any(resolve_chain(t, cfg) for t in TASK_IDS)),
    }


# ---------------------------------------------------------------- Anbieter verwalten

def _clean_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/models"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    return url


def add_provider(data: dict) -> str:
    preset = PRESET_BY_ID.get(data.get("preset") or "custom")
    if preset is None:
        raise ValueError("Unbekannte Vorauswahl.")
    base_url = _clean_url(data.get("base_url") or preset["base_url"])
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("Bitte eine gültige Adresse eintragen (beginnt mit http:// oder https://).")
    provider = {
        "id": "p_" + uuid.uuid4().hex[:8], "preset": preset["id"], "type": preset["type"],
        "name": (data.get("name") or preset["name"]).strip(), "base_url": base_url,
        "api_key": (data.get("api_key") or "").strip(), "models": [], "status": "ungeprueft",
    }
    with _LOCK:
        cfg = load()
        cfg["providers"].append(provider)
        save(cfg)
    return provider["id"]


def update_provider(pid: str, data: dict) -> dict:
    with _LOCK:
        cfg = load()
        for p in cfg["providers"]:
            if p["id"] == pid:
                if "name" in data and data["name"].strip():
                    p["name"] = data["name"].strip()
                if "base_url" in data:
                    url = _clean_url(data["base_url"])
                    if not url.startswith(("http://", "https://")):
                        raise ValueError("Bitte eine gültige Adresse eintragen.")
                    if url != p["base_url"]:
                        p["base_url"], p["status"] = url, "ungeprueft"
                if data.get("api_key"):  # leer = Schlüssel behalten
                    p["api_key"], p["status"] = data["api_key"].strip(), "ungeprueft"
                if data.get("api_key_entfernen"):
                    p["api_key"], p["status"] = "", "ungeprueft"
                if "manuelles_modell" in data and data["manuelles_modell"].strip():
                    model = data["manuelles_modell"].strip()
                    if model not in p["models"]:
                        p["models"].insert(0, model)
                save(cfg)
                return public_provider(p)
    raise LookupError("Anbieter nicht gefunden oder nicht änderbar.")


def archive_provider(pid: str) -> None:
    """Nicht löschen: in das Archiv verschieben (wiederherstellbar)."""
    with _LOCK:
        cfg = load()
        keep = [p for p in cfg["providers"] if p["id"] != pid]
        moved = [p for p in cfg["providers"] if p["id"] == pid]
        if not moved:
            raise LookupError("Anbieter nicht gefunden oder nicht änderbar.")
        moved[0]["archiviert_am"] = time.strftime("%Y-%m-%d %H:%M")
        cfg["providers"], cfg["archiv"] = keep, cfg["archiv"] + moved
        save(cfg)


def restore_provider(pid: str) -> None:
    with _LOCK:
        cfg = load()
        moved = [p for p in cfg["archiv"] if p["id"] == pid]
        if not moved:
            raise LookupError("Archivierter Anbieter nicht gefunden.")
        moved[0].pop("archiviert_am", None)
        cfg["archiv"] = [p for p in cfg["archiv"] if p["id"] != pid]
        cfg["providers"].append(moved[0])
        save(cfg)


def _set_state(pid: str, **fields) -> None:
    with _LOCK:
        cfg = load()
        for p in cfg["providers"]:
            if p["id"] == pid:
                p.update(fields)
                save(cfg)
                return


# ---------------------------------------------------------------- HTTP

def _headers(p: dict) -> dict:
    headers = {"Content-Type": "application/json", "User-Agent": "StoryWorld/1"}
    key = p.get("api_key", "")
    if p["type"] == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
        if key:
            headers["x-api-key"] = key
    elif key:
        headers["Authorization"] = f"Bearer {key}"
    if p.get("preset") == "openrouter":
        headers["X-Title"] = "Story World"
    return headers


_HTTP_HINTS = {401: "Schlüssel ungültig oder fehlt.", 403: "Schlüssel hat keine Berechtigung.",
               404: "Adresse oder Modell nicht gefunden – Adresse prüfen.",
               402: "Kein Guthaben mehr.", 429: "Limit erreicht oder kein Guthaben – später erneut versuchen."}


def _http_error(exc: urllib.error.HTTPError) -> ProviderError:
    detail = exc.read().decode("utf-8", "replace")[:300]
    return ProviderError(f"{_HTTP_HINTS.get(exc.code, 'Anbieter meldet einen Fehler.')} (HTTP {exc.code}) {detail}")


# Python von python.org bringt ohne „Install Certificates.command“ keine Stammzertifikate mit.
# Dann auf certifi (falls installiert) oder die Zertifikatsbündel des Betriebssystems zurückgreifen.
_CA_FALLBACKS = ("/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
                 "/etc/pki/tls/certs/ca-bundle.crt", "/opt/homebrew/etc/openssl@3/cert.pem",
                 "/usr/local/etc/openssl@3/cert.pem")
_SSL_CONTEXT: ssl.SSLContext | None = None


def _ssl_context() -> ssl.SSLContext:
    global _SSL_CONTEXT
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT
    context = ssl.create_default_context()
    if not context.cert_store_stats().get("x509_ca"):
        candidates = []
        try:
            import certifi  # optional
            candidates.append(certifi.where())
        except ImportError:
            pass
        candidates.extend(_CA_FALLBACKS)
        for path in candidates:
            if os.path.isfile(path):
                try:
                    context.load_verify_locations(cafile=path)
                except (ssl.SSLError, OSError):
                    continue
                if context.cert_store_stats().get("x509_ca"):
                    break
    _SSL_CONTEXT = context
    return context


def _open(p: dict, method: str, path: str, body: dict | None, timeout: int):
    url = p["base_url"].rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers=_headers(p), method=method)
    try:
        if url.startswith("https://"):
            return urllib.request.urlopen(request, timeout=timeout, context=_ssl_context())
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise _http_error(exc)
    except urllib.error.URLError as exc:
        raise ProviderError(f"Anbieter nicht erreichbar ({url}): {exc.reason}")
    except (TimeoutError, OSError) as exc:
        raise ProviderError(f"Zeitüberschreitung oder Netzwerkfehler: {exc}")


def _request(p: dict, method: str, path: str, body: dict | None = None, timeout: int = 30) -> dict:
    response = _open(p, method, path, body, timeout)
    try:
        with response:
            raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}
    except (TimeoutError, OSError) as exc:
        raise ProviderError(f"Zeitüberschreitung oder Netzwerkfehler: {exc}")
    except ValueError:
        raise ProviderError("Anbieter hat keine gültige JSON-Antwort geliefert.")


def _text_of(p: dict, data: dict, info: dict | None = None) -> str:
    info = {} if info is None else info
    try:
        if p["type"] == "anthropic":
            info["finish"] = data.get("stop_reason")
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        choice = data["choices"][0]
        message = choice["message"]
        info["finish"] = choice.get("finish_reason")
        info["reasoning"] = len(message.get("reasoning_content") or message.get("reasoning") or "")
        return message.get("content") or ""
    except (KeyError, IndexError, TypeError):
        raise ProviderError("Unerwartete Antwortstruktur des Anbieters.")


def _delta_of(p: dict, event: dict) -> str:
    if p["type"] == "anthropic":
        if event.get("type") == "content_block_delta":
            return (event.get("delta") or {}).get("text") or ""
        return ""
    try:
        return (event["choices"][0].get("delta") or {}).get("content") or ""
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""


def _note(p: dict, event: dict, info: dict | None) -> None:
    """Merkt Ende-Grund und Länge der reinen Überlegung (Reasoning-Modelle) für verständliche Fehler."""
    if info is None or not isinstance(event, dict):
        return
    try:
        if p["type"] == "anthropic":
            if event.get("type") == "message_delta":
                info["finish"] = (event.get("delta") or {}).get("stop_reason") or info.get("finish")
            return
        choice = event["choices"][0]
        delta = choice.get("delta") or {}
        info["reasoning"] = info.get("reasoning", 0) + len(delta.get("reasoning_content") or delta.get("reasoning") or "")
        info["finish"] = choice.get("finish_reason") or info.get("finish")
    except (KeyError, IndexError, TypeError, AttributeError):
        return


def _stream(p: dict, path: str, body: dict, timeout: int, on_chunk, info: dict | None = None) -> str:
    """Server-Sent Events lesen; liefert der Anbieter kein Streaming, wird die normale Antwort genommen."""
    response = _open(p, "POST", path, dict(body, stream=True), timeout)
    parts = []
    try:
        with response:
            if "text/event-stream" not in response.headers.get("Content-Type", ""):
                return _text_of(p, json.loads(response.read().decode("utf-8")), info)
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except ValueError:
                    continue
                if isinstance(event, dict) and event.get("error"):
                    raise ProviderError(f"Anbieter meldet einen Fehler im Stream: {str(event['error'])[:300]}")
                _note(p, event, info)
                piece = _delta_of(p, event)
                if piece:
                    parts.append(piece)
                    on_chunk(piece)
    except (TimeoutError, OSError) as exc:
        raise ProviderError(f"Verbindung während der Antwort abgebrochen: {exc}")
    except ValueError:
        raise ProviderError("Anbieter hat keine gültige Antwort geliefert.")
    return "".join(parts)


def _parse_models(payload) -> list:
    items = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else payload
    names = []
    for item in items or []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            name = item.get("id") or item.get("name")
            if name:
                names.append(name.replace("models/", "", 1) if name.startswith("models/") else name)
    return sorted(set(names), key=str.lower)


def fetch_models(p: dict) -> list:
    path = "/models?limit=1000" if p["type"] == "anthropic" else "/models"
    return _parse_models(_request(p, "GET", path))


def verify(pid: str) -> dict:
    """Prüft, ob Adresse und Schlüssel funktionieren."""
    p = get_provider(pid)
    preset = PRESET_BY_ID.get(p.get("preset"), {})
    if preset.get("needs_key") and not p.get("api_key"):
        raise ProviderError("Für diesen Anbieter fehlt noch der API-Schlüssel.")
    try:
        if p.get("preset") == "openrouter":
            info = _request(p, "GET", "/key").get("data", {})
            remaining = info.get("limit_remaining")
            message = "Schlüssel gültig." + (f" Restguthaben-Limit: {remaining}" if remaining is not None else "")
        else:
            count = len(fetch_models(p))
            message = f"Verbindung steht ({count} Modelle verfügbar)."
    except ProviderError as exc:
        if p["id"] != "env":
            _set_state(pid, status="fehler", last_error=str(exc), checked_at=time.strftime("%Y-%m-%d %H:%M"))
        raise
    if p["id"] != "env":
        _set_state(pid, status="ok", last_error="", checked_at=time.strftime("%Y-%m-%d %H:%M"))
    return {"ok": True, "meldung": message}


def load_models(pid: str) -> dict:
    p = get_provider(pid)
    models = fetch_models(p)
    if not models:
        raise ProviderError("Der Anbieter hat keine Modelle gemeldet.")
    if p["id"] != "env":
        manual = [m for m in p.get("models", []) if m not in models]
        _set_state(pid, models=manual + models, status="ok", last_error="",
                   models_geladen=time.strftime("%Y-%m-%d %H:%M"))
    return {"anzahl": len(models)}


# ---------------------------------------------------------------- Aufgaben & Ketten

def set_chain(task: str, chain: list) -> list:
    if task not in TASK_IDS:
        raise ValueError("Unbekannte Aufgabe.")
    clean = []
    for entry in chain[:MAX_CHAIN]:
        if isinstance(entry, dict) and entry.get("provider") and (entry.get("model") or "").strip():
            clean.append({"provider": entry["provider"], "model": entry["model"].strip()})
    with _LOCK:
        cfg = load()
        cfg["tasks"][task] = clean
        save(cfg)
    return clean


def set_task_params(task: str, params: dict) -> dict:
    """Werte je Aufgabe, z. B. Temperatur. Leerer Wert = Standard des Aufrufers."""
    if task not in TASK_IDS:
        raise ValueError("Unbekannte Aufgabe.")
    clean = {}
    for key, (low, high) in TASK_PARAMS.items():
        value = params.get(key)
        if value in (None, ""):
            continue
        try:
            number = float(str(value).replace(",", "."))
        except ValueError:
            raise ValueError(f"{key} muss eine Zahl sein.")
        if not low <= number <= high:
            raise ValueError(f"{key} bitte zwischen {low:g} und {high:g}.")
        clean[key] = number
    with _LOCK:
        cfg = load()
        cfg.setdefault("task_params", {})[task] = clean
        save(cfg)
    return clean


def task_param(task: str, key: str, default=None, cfg: dict | None = None):
    cfg = cfg or load()
    return cfg.get("task_params", {}).get(task, {}).get(key, default)


def resolve_chain(task: str, cfg: dict | None = None) -> list:
    cfg = cfg or load()
    ids = {p["id"]: p for p in all_providers(cfg)}
    for name in (task, "standard"):
        chain = [(ids[e["provider"]], e["model"]) for e in cfg["tasks"].get(name, []) if e.get("provider") in ids]
        if chain:
            return chain
    env = ids.get("env")
    if env and env["models"]:
        return [(env, env["models"][0])]
    return []


class _BudgetUsedUp(ProviderError):
    """Reasoning-Modell hat das Token-Budget mit Nachdenken verbraucht, ohne zu antworten."""


_ADAPT: dict = {}
_BUDGET: dict = {}  # (Anbieter-URL, Modell) -> gelerntes Token-Budget  # (Anbieter-URL, Modell) -> gelernte Anpassungen, z. B. max_completion_tokens


def _adapt(body: dict, error: str) -> str | None:
    """Passt die Anfrage an, wenn der Anbieter einen Parameter ablehnt. Gibt die Anpassung zurück oder None."""
    low = error.lower()
    if "max_completion_tokens" in low and "max_tokens" in body:
        body["max_completion_tokens"] = body.pop("max_tokens")
        return "max_completion_tokens"
    if "temperature" in low and ("unsupported" in low or "not support" in low) and "temperature" in body:
        body.pop("temperature")
        return "ohne_temperature"
    if "response_format" in body:
        body.pop("response_format")  # manche Modelle kennen den JSON-Modus nicht (wie bisher: jeder 400er)
        return "ohne_json_modus"
    return None


def _chat_once(p: dict, model: str, messages: list, json_mode: bool, max_tokens: int, temperature: float,
               timeout: int, on_chunk=None, log=None) -> str:
    key = (p.get("base_url"), model)
    if p["type"] == "anthropic":
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        rest = [m for m in messages if m["role"] != "system"]
        path = "/messages"
        body = {"model": model, "system": system, "messages": rest, "max_tokens": max_tokens, "temperature": temperature}
    else:
        path = "/chat/completions"
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        for change in _ADAPT.get(key, ()):
            if change == "max_completion_tokens" and "max_tokens" in body:
                body["max_completion_tokens"] = body.pop("max_tokens")
            elif change == "ohne_temperature":
                body.pop("temperature", None)
            elif change == "ohne_json_modus":
                body.pop("response_format", None)

    budget_key = "max_tokens"
    for change in _ADAPT.get(key, ()):
        if change == "max_completion_tokens" and p["type"] != "anthropic":
            budget_key = "max_completion_tokens"
    if _BUDGET.get(key, 0) > body.get(budget_key, 0):
        body[budget_key] = _BUDGET[key]  # gelernt: dieses Modell braucht mehr Platz zum Nachdenken

    def send(b):
        info = {}
        text = (_stream(p, path, b, timeout, on_chunk, info) if on_chunk
                else _text_of(p, _request(p, "POST", path, b, timeout), info))
        why = []
        if info.get("finish"):
            why.append(f"Ende-Grund „{info['finish']}“")
        if info.get("reasoning"):
            why.append(f"{info['reasoning']:,} Zeichen Überlegung".replace(",", "."))
        cut = info.get("finish") in ("length", "max_tokens")
        if cut and (not text.strip() or json_mode or info.get("reasoning")):
            raise _BudgetUsedUp(("Leere Antwort" if not text.strip() else "Antwort abgeschnitten")
                                + f" ({', '.join(why)}) – das Token-Budget war zu klein.")
        if not text.strip():
            raise ProviderError("Leere Antwort" + (f" ({', '.join(why)})" if why else "") + ".")
        return text

    raised = None
    for _ in range(5):
        try:
            return send(body)
        except _BudgetUsedUp as exc:
            budget_key = "max_completion_tokens" if "max_completion_tokens" in body else "max_tokens"
            if raised or int(body.get(budget_key, 0)) >= 64000:
                raise ProviderError(str(exc))
            raised = exc
            body[budget_key] = min(64000, int(body[budget_key]) * 4)
            _BUDGET[key] = body[budget_key]
            if log:
                log(f"{exc} Neuer Versuch mit größerem Budget ({body[budget_key]:,} Token)".replace(",", "."), "warnung")
        except ProviderError as exc:
            if raised and "HTTP 400" in str(exc):
                _BUDGET.pop(key, None)  # Anbieter erlaubt kein so großes Budget
                raise ProviderError(f"{raised} Größeres Budget lehnt der Anbieter ab: {str(exc)[:200]}")
            if "HTTP 400" not in str(exc) or p["type"] == "anthropic":
                raise
            change = _adapt(body, str(exc))
            if not change:
                raise
            _ADAPT.setdefault(key, set()).add(change)
            if log:
                log(f"Modell lehnt Parameter ab – angepasst ({change}), neuer Versuch", "warnung")
    return send(body)


def complete(messages: list, task: str = "standard", json_mode: bool = True, max_tokens: int = 8000,
             temperature: float | None = None, timeout: int = 300, log=None, on_chunk=None, chain: list | None = None,
             record=None, fixed_temperature: bool = False) -> tuple:
    """Probiert die Modelle der Aufgabe der Reihe nach (1., 2., 3. Wahl). Gibt (Text, 'Anbieter · Modell').
    log(text, level) meldet jeden Schritt, on_chunk(text) die mitlaufende Antwort, record(modell, messages, text,
    fehler, sekunden) protokolliert jeden einzelnen Aufruf. Die Temperatur kommt aus den Werten je Aufgabe, sonst aus
    dem Aufrufer, sonst 0,8 – außer fixed_temperature (Tests, Richter)."""
    log = log or (lambda *a, **k: None)
    if not fixed_temperature:
        temperature = task_param(task, "temperatur", temperature)
    temperature = 0.8 if temperature is None else float(temperature)
    chain = chain if chain is not None else resolve_chain(task)
    seen, unique = set(), []
    for entry in chain:  # dasselbe Modell zweimal in der Kette bringt nichts
        ident = (entry[0].get("id") or entry[0].get("base_url"), entry[1])
        if ident not in seen:
            seen.add(ident)
            unique.append(entry)
    chain = unique
    if not chain:
        raise ProviderError("Keine KI eingerichtet. Einstellungen → KI-Anbieter und Modelle je Aufgabe.")
    errors = []
    for number, (provider, model) in enumerate(chain, 1):
        label = f"{provider['name']} · {model}"
        log(f"{number}. Wahl: Anfrage an {label} – warte auf Antwort", "info")
        started = time.time()
        try:
            text = _chat_once(provider, model, messages, json_mode, max_tokens, temperature, timeout, on_chunk,
                              lambda t, lvl="info": log(f"{label}: {t}", lvl))
            log(f"Antwort von {label}: {len(text):,} Zeichen in {time.time() - started:.1f} s".replace(",", "."), "ok")
            if record:
                record(label, messages, text, None, time.time() - started)
            return text, label
        except ProviderError as exc:
            if record:
                record(label, messages, None, str(exc), time.time() - started)
            errors.append(f"{label}: {exc}")
            more = " – nächste Wahl springt ein" if number < len(chain) else ""
            log(f"{number}. Wahl fehlgeschlagen ({label}): {exc}{more}", "fehler")
    raise ProviderError("Alle Modelle der Aufgabe sind fehlgeschlagen:\n" + "\n".join(errors))


def test_chain(task: str) -> dict:
    text, used = complete([{"role": "system", "content": "Antworte nur mit JSON."},
                           {"role": "user", "content": 'Antworte mit {"ok": true}.'}],
                          task, max_tokens=50, temperature=0, timeout=60, fixed_temperature=True)
    return {"ok": True, "modell": used, "antwort": text[:200]}


def save_theme(theme: dict) -> dict:
    active = theme.get("active", "hell")
    eigen = {k: v for k, v in (theme.get("eigen") or {}).items()
             if isinstance(k, str) and isinstance(v, str) and len(v) <= 32}
    with _LOCK:
        cfg = load()
        cfg["theme"] = {"active": active, "eigen": eigen}
        save(cfg)
    return cfg["theme"]
