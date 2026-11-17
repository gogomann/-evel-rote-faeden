"""Systemprüfung beim Start: Sind die Zusatzprogramme da (MP3-Encoder, macOS-Stimmen)? Fehlendes wird – nach
Rückfrage im Startfenster – automatisch installiert, soweit das ohne Technikwissen geht:

- macOS mit Homebrew: `brew install lame`
- Windows mit winget: `winget install Gyan.FFmpeg`
- sonst: verständlicher Hinweis, was zu tun ist.

Gefragt wird nur beim ersten Start einer Version (nach dem Entpacken bzw. nach einem Update); danach wird nur
noch kurz gemeldet, was fehlt. Der Stand liegt in _update/systempruefung.json.
`python3 -m story_world system` prüft jederzeit erneut und bietet die Installation wieder an.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, mp3

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "_update" / "systempruefung.json"


def _install_command() -> tuple:
    """(Befehl oder None, Hinweis) für den MP3-Encoder auf diesem System."""
    system = platform.system()
    if system == "Darwin":
        brew = shutil.which("brew") or next((p for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
                                             if Path(p).exists()), None)
        if brew:
            return [brew, "install", "lame"], "Installation mit Homebrew: brew install lame"
        return None, ("Homebrew fehlt. Einmalig installieren (Anleitung: https://brew.sh), danach im Terminal: "
                      "brew install lame – oder Story World erneut starten.")
    if system == "Windows":
        if shutil.which("winget"):
            return (["winget", "install", "-e", "--id", "Gyan.FFmpeg", "--accept-source-agreements",
                     "--accept-package-agreements"], "Installation mit winget: Gyan.FFmpeg")
        return None, "FFmpeg von https://www.gyan.dev/ffmpeg/builds/ installieren oder winget nachrüsten (Microsoft Store: „App Installer“)."
    return None, "Bitte das Paket „lame“ oder „ffmpeg“ über die Paketverwaltung installieren (z. B. sudo apt install lame)."


def check() -> list:
    """Liste der Prüfpunkte: {id, name, wofuer, ok, detail, installierbar}."""
    enc = mp3.encoder()
    cmd, hint = _install_command()
    items = [{
        "id": "mp3", "name": "MP3-Encoder (lame oder ffmpeg)", "wofuer": "Vertonung als MP3 mit ID3-Tags",
        "ok": enc is not None, "detail": f"{enc[0]} ({enc[1]})" if enc else hint, "installierbar": bool(cmd) and enc is None,
    }]
    if platform.system() == "Darwin":
        say = shutil.which("say")
        items.append({"id": "say", "name": "macOS-Stimmen (say)", "wofuer": "Vertonung mit den Systemstimmen",
                      "ok": bool(say), "detail": say or "Fehlt – Vertonung über TTS-Server geht trotzdem.",
                      "installierbar": False})
    return items


def install(item_id: str = "mp3") -> bool:
    """Fehlendes installieren (Ausgabe läuft im Startfenster mit). True, wenn es danach gefunden wird."""
    if item_id != "mp3":
        return False
    cmd, hint = _install_command()
    if not cmd:
        print(f"  {hint}")
        return False
    print(f"  {hint} … (das kann ein paar Minuten dauern)")
    try:
        result = subprocess.run(cmd, timeout=1800)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  Installation nicht möglich: {exc}")
        return False
    ok = result.returncode == 0 and mp3.available()
    print("  ✓ Installiert." if ok else f"  ✗ Installation hat nicht geklappt (Code {result.returncode}). {hint}")
    return ok


def _load() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    try:
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def _ask(question: str) -> bool:
    if not sys.stdin or not sys.stdin.isatty():
        return False
    try:
        answer = input(f"{question} [J/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("", "j", "ja", "y", "yes")


def run(force: bool = False) -> list:
    """Beim Start: prüfen, beim ersten Start einer Version Fehlendes zur Installation anbieten, Stand speichern."""
    state = _load()
    first = force or state.get("version") != __version__
    items = check()
    missing = [i for i in items if not i["ok"]]
    if first:
        print(f"Systemprüfung (Version {__version__}):")
        for i in items:
            print(f"  {'✓' if i['ok'] else '✗'} {i['name']} – {i['detail'] if not i['ok'] else 'vorhanden'}")
        for i in missing:
            if i["installierbar"] and _ask(f"„{i['name']}“ fehlt ({i['wofuer']}). Jetzt automatisch installieren?"):
                install(i["id"])
        items = check()
    elif missing:
        print("Hinweis: " + "; ".join(f"{i['name']} fehlt ({i['wofuer']})" for i in missing)
              + " – erneut prüfen: python3 -m story_world system")
    _save({"version": __version__, "geprueft_am": time.strftime("%Y-%m-%d %H:%M"),
           "ergebnis": [{k: i[k] for k in ("id", "ok", "detail")} for i in items]})
    return items
