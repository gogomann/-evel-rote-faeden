"""Mitgelieferter Libra-TTS-Server (zusatz/libra-tts): einrichten, nach Updates nachziehen, mit Story World starten.

- Einrichten: Systemprüfung beim ersten Start einer Version (Rückfrage im Startfenster), Einstellungen → TTS-Server
  („Einrichten“) oder `python3 -m story_world libra einrichten`. Sucht Python ≥ 3.10, legt zusatz/libra-tts/.venv an
  und führt installer.py aus (Pakete + Sprachmodell, ca. 1–2 GB; Backend mlx/cuda/onnx wählt der Installer).
- Update: Das Programm-Update ersetzt den Server-Code wie jede andere Programmdatei; .venv/, models/ und server.conf
  fasst es nie an (update.PROTECTED_*). Ändern sich requirements.txt, installer.py oder download_model.py, installiert
  der nächste Start nach (nachziehen); ändert sich der Server-Code, startet der laufende Server neu.
- Start: Story World startet den Server im Hintergrund (nur 127.0.0.1, Standardsprache de) und beendet ihn mit.
  Er erscheint unter Einstellungen → TTS-Server als „Libra-TTS (mitgeliefert)“ (Stile + Geräusch-Tags für die
  Hörspiel-Regie). Archiviert man ihn dort, startet er nicht mehr.

Zustand: _update/libra.json, Prozessnummer _update/libra.pid, Server-Ausgabe _update/libra.log. Nur Standardbibliothek.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "zusatz" / "libra-tts"
STATE_DIR = ROOT / "_update"
NAME = "Libra-TTS (mitgeliefert)"
HOST = "127.0.0.1"
LANG = "de"
PORT_DEFAULT = 8880
PORTS = range(8880, 8900)
START_TIMEOUT = 300
INSTALL_TIMEOUT = 3 * 3600
LOG_MAX = 5 * 1024 * 1024
INSTALL_FILES = ("requirements.txt", "installer.py", "download_model.py")
# Was beim Einrichten (einmalig) aus dem Netz kommt – für Startfenster, Oberfläche, Update-Hinweis und README
DOWNLOAD_QUELLEN = ("Sprachmodell von Hugging Face (huggingface.co/Ekam/Libra-TTS), Python-Pakete von pypi.org "
                    "(mit NVIDIA-Grafikkarte zusätzlich PyTorch von download.pytorch.org)")
DOWNLOAD_GROESSE = ("ca. 1,3 GB auf einem Mac mit Apple-Chip, ca. 2 GB auf Windows/Intel-Mac (Prozessor), "
                    "mit NVIDIA-Grafikkarte bis ca. 4 GB")


def hinweis_zeilen() -> list:
    """Deutlicher Hinweis vor dem Einrichten (Startfenster), höchstens ~76 Zeichen je Zeile."""
    return ["ZUSATZFUNKTION (optional): Libra-TTS – Hörspiel-Stimmen offline",
            "8 Stimmen, Sprechstile (warm, sad, whispering …), Geräusche (<sigh> …).",
            "",
            "Dafür ist EINMALIG ein größerer Download nötig:",
            "  • Mac mit Apple-Chip:        ca. 1,3 GB",
            "  • Windows / Intel-Mac (CPU): ca. 2 GB",
            "  • mit NVIDIA-Grafikkarte:    bis ca. 4 GB",
            "Quelle:",
            "  • Sprachmodell:  Hugging Face (huggingface.co/Ekam/Libra-TTS)",
            "  • Python-Pakete: pypi.org (NVIDIA: zusätzlich download.pytorch.org)",
            "",
            "Nur beim ersten Einrichten – Updates von Evel laden das nicht erneut.",
            "Danach automatisch eingebunden: startet mit Evel, steht unter TTS-Server.",
            "Evel funktioniert auch ohne. Später: Einstellungen → TTS-Server → Einrichten."]


PYTHON_HINT = ("Libra-TTS braucht Python 3.10 oder neuer (https://www.python.org/downloads/). Danach Story World neu "
               "starten oder: python3 -m story_world libra einrichten")

_LOCK = threading.RLock()
_PROC: subprocess.Popen | None = None
_ATEXIT = False


class LibraError(RuntimeError):
    pass


# ---------------------------------------------------------------- Zustand

def _state_file() -> Path:
    return STATE_DIR / "libra.json"


def _pid_file() -> Path:
    return STATE_DIR / "libra.pid"


def _load() -> dict:
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(**changes) -> dict:
    data = _load()
    data.update(changes)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _state_file().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, _state_file())
    except OSError:
        pass
    return data


def _fingerprint(paths: list) -> str:
    digest = hashlib.sha1()
    for path in sorted(paths):
        if path.is_file():
            digest.update(path.relative_to(DIR).as_posix().encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def install_fp() -> str:
    """Ändert sich, wenn ein Update neue Pakete oder ein anderes Modell braucht."""
    return _fingerprint([DIR / name for name in INSTALL_FILES])


def code_fp() -> str:
    """Ändert sich, wenn ein Update den Server-Code ersetzt (laufenden Server dann neu starten)."""
    files = [DIR / "server.py", DIR / "download_model.py", DIR / "web" / "index.html"]
    files += list((DIR / "libra_tts").glob("*.py")) if (DIR / "libra_tts").is_dir() else []
    return _fingerprint(files)


# ---------------------------------------------------------------- Einrichten

def vorhanden() -> bool:
    return (DIR / "server.py").is_file() and (DIR / "installer.py").is_file()


def venv_python() -> Path:
    return DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _model_ready() -> bool:
    return (DIR / "models" / "Libra-TTS" / "config.json").is_file()


def eingerichtet() -> bool:
    return vorhanden() and venv_python().exists() and _model_ready()


def braucht_nachinstallation() -> bool:
    return eingerichtet() and _load().get("eingerichtet") != install_fp()


def _py_ok(cmd: list) -> bool:
    try:
        result = subprocess.run(cmd + ["-c", "import sys; sys.exit(sys.version_info < (3, 10))"],
                                capture_output=True, timeout=30)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def python_fuer_libra() -> list | None:
    """Befehl eines Python ≥ 3.10 (wie install.sh/install.bat: neuere Versionen zuerst) oder None."""
    candidates: list = []
    if os.name == "nt":
        if shutil.which("py"):
            candidates += [["py", f"-3.{minor}"] for minor in (13, 12, 11, 10)] + [["py", "-3"]]
        if shutil.which("python"):
            candidates.append([shutil.which("python")])
    else:
        for name in ("python3.13", "python3.12", "python3.11", "python3.10"):
            found = shutil.which(name) or next(
                (p for p in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}",
                             f"/Library/Frameworks/Python.framework/Versions/{name[6:]}/bin/{name}") if Path(p).exists()),
                None)
            if found:
                candidates.append([found])
        candidates.append([sys.executable])
        if shutil.which("python3"):
            candidates.append([shutil.which("python3")])
    seen = set()
    for cmd in candidates:
        key = tuple(cmd)
        if key in seen:
            continue
        seen.add(key)
        if _py_ok(cmd):
            return cmd
    return None


def _run_installer(echo) -> bool:
    echo("  Installiere Pakete und lade das Sprachmodell (ca. 1–2 GB, je nach Leitung einige Minuten) …")
    try:
        result = subprocess.run([str(venv_python()), str(DIR / "installer.py")], cwd=str(DIR), timeout=INSTALL_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        echo(f"  ✗ Installation nicht möglich: {exc}")
        return False
    if result.returncode != 0 or not _model_ready():
        echo(f"  ✗ Einrichtung fehlgeschlagen (Code {result.returncode}). Erneut versuchen: "
             "python3 -m story_world libra einrichten")
        return False
    _save(eingerichtet=install_fp(), eingerichtet_am=time.strftime("%Y-%m-%d %H:%M"))
    return True


def einrichten(echo=print) -> bool:
    """Python-Umgebung anlegen und installer.py ausführen (Ausgabe im Startfenster). True bei Erfolg."""
    with _LOCK:
        if not vorhanden():
            echo("  Libra-TTS fehlt im Programmordner (zusatz/libra-tts).")
            return False
        if not venv_python().exists():
            python = python_fuer_libra()
            if not python:
                echo(f"  {PYTHON_HINT}")
                return False
            echo(f"  Lege die Python-Umgebung an ({' '.join(python)}) …")
            try:
                result = subprocess.run(python + ["-m", "venv", str(DIR / ".venv")], cwd=str(DIR), timeout=600)
            except (OSError, subprocess.SubprocessError) as exc:
                echo(f"  ✗ Python-Umgebung nicht angelegt: {exc}")
                return False
            if result.returncode != 0 or not venv_python().exists():
                echo(f"  ✗ Python-Umgebung nicht angelegt (Code {result.returncode}).")
                return False
            _save(python=" ".join(python))
        stoppen()
        ok = _run_installer(echo)
        if ok:
            echo("  ✓ Libra-TTS eingerichtet.")
        return ok


def nachziehen(echo=print) -> bool | None:
    """Nach einem Update: neue Pakete/Modelldateien nachinstallieren. None = nichts zu tun."""
    with _LOCK:
        if not braucht_nachinstallation():
            return None
        echo("Libra-TTS: neue Version – Pakete werden nachinstalliert …")
        stoppen()
        ok = _run_installer(echo)
        if ok:
            echo("  ✓ Libra-TTS ist aktuell.")
        return ok


# ---------------------------------------------------------------- Prozess

def _health(port: int, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/health", timeout=timeout) as resp:
            data = json.loads(resp.read(10000).decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("status") == "ok" and "backend" in data else None


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name != "nt":  # wie der Server selbst: alte Verbindungen (TIME_WAIT) blockieren den Port nicht
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((HOST, port))
            return True
        except OSError:
            return False


def _alive(pid) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True,
                                 timeout=15).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return str(pid) in out
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True
    except OSError:
        return False
    try:  # eigener, schon beendeter Kindprozess (Zombie) gilt nicht als laufend
        done, _ = os.waitpid(int(pid), os.WNOHANG)
        return done == 0
    except ChildProcessError:
        return True
    except OSError:
        return True


def _is_ours(pid, port) -> bool:
    """Gehört die gespeicherte Prozessnummer wirklich zu unserem Libra-Server? (Nummern werden wiederverwendet.)"""
    if not _alive(pid):
        return False
    if os.name == "nt":
        return bool(port) and _health(int(port)) is not None
    try:
        command = subprocess.run(["ps", "-p", str(int(pid)), "-o", "command="], capture_output=True, text=True,
                                 timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "server.py" in command and "libra-tts" in command


def _kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(40):
        time.sleep(0.25)
        if not _alive(pid):
            return
    try:
        os.kill(pid, signal.SIGKILL)
        _alive(pid)  # Zombie einsammeln
    except OSError:
        pass


def laeuft() -> dict | None:
    """Läuft unser Server (Prozess vorhanden)? {pid, port, code, start, bereit}"""
    info = _load().get("laeuft") or {}
    if not info.get("pid") or not _is_ours(info["pid"], info.get("port")):
        return None
    return dict(info, bereit=_health(int(info["port"])) is not None)


def stoppen() -> bool:
    """Unseren Server beenden (auch einen, den eine frühere Story-World-Sitzung gestartet hat)."""
    global _PROC
    with _LOCK:
        stopped = False
        if _PROC is not None and _PROC.poll() is None:
            _PROC.terminate()
            try:
                _PROC.wait(10)
            except subprocess.TimeoutExpired:
                _PROC.kill()
            stopped = True
        else:
            info = _load().get("laeuft") or {}
            if info.get("pid") and _is_ours(info["pid"], info.get("port")):
                _kill(int(info["pid"]))
                stopped = True
        _PROC = None
        _save(laeuft=None)
        try:
            _pid_file().unlink()
        except OSError:
            pass
        return stopped


def _beim_beenden() -> None:
    """atexit: nur den Server beenden, den dieser Prozess gestartet hat."""
    if _PROC is not None and _PROC.poll() is None:
        try:
            stoppen()
        except Exception:
            pass


def _choose_port() -> int:
    preferred = int(_load().get("port") or PORT_DEFAULT)
    if _port_free(preferred):
        return preferred
    for port in PORTS:
        if _port_free(port):
            return port
    raise LibraError(f"Kein freier Port zwischen {PORTS[0]} und {PORTS[-1]} für Libra-TTS.")


def _log_handle():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = STATE_DIR / "libra.log"
    if log.exists() and log.stat().st_size > LOG_MAX:
        os.replace(log, log.with_suffix(".log.1"))
    return open(log, "ab")


def starten() -> dict:
    """Server starten (oder den laufenden weiterbenutzen). Neuer Server-Code → Neustart."""
    global _PROC, _ATEXIT
    with _LOCK:
        if not eingerichtet():
            raise LibraError("Libra-TTS ist noch nicht eingerichtet (Einstellungen → TTS-Server → „Einrichten“).")
        current = laeuft()
        if current and current.get("code") == code_fp():
            return current
        if current:
            stoppen()
        port = _choose_port()
        env = dict(os.environ, PYTHONUNBUFFERED="1", HF_HUB_DISABLE_TELEMETRY="1")
        env.pop("PYTHONPATH", None)
        cmd = [str(venv_python()), str(DIR / "server.py"), "--port", str(port), "--host", HOST, "--lang", LANG]
        with _log_handle() as log:
            log.write(f"\n==== Start {time.strftime('%Y-%m-%d %H:%M:%S')} Port {port}\n".encode("utf-8"))
            log.flush()
            _PROC = subprocess.Popen(cmd, cwd=str(DIR), stdout=log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, env=env)
        info = {"pid": _PROC.pid, "port": port, "code": code_fp(), "start": time.time()}
        _save(laeuft=info, port=port)
        try:
            _pid_file().write_text(str(_PROC.pid), encoding="ascii")
        except OSError:
            pass
        if not _ATEXIT:
            atexit.register(_beim_beenden)
            _ATEXIT = True
        return dict(info, bereit=False)


def url(port: int | None = None) -> str:
    return f"http://{HOST}:{port or _load().get('port') or PORT_DEFAULT}"


def _log_tail(lines: int = 8) -> str:
    try:
        text = (STATE_DIR / "libra.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return " | ".join(line.strip() for line in text.strip().splitlines()[-lines:] if line.strip())


def bereit(timeout: float = START_TIMEOUT) -> str:
    """Server starten, falls nötig, und warten, bis er antwortet (Modell laden dauert). Liefert die Adresse."""
    info = starten()
    port = int(info["port"])
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _health(port):
            return url(port)
        if _PROC is not None and _PROC.poll() is not None:
            raise LibraError(f"Libra-TTS hat sich beendet (Code {_PROC.returncode}). Log: {_log_tail()}")
        time.sleep(1.0)
    raise LibraError(f"Libra-TTS antwortet nach {int(timeout)} s nicht. Log: {_log_tail()}")


# ---------------------------------------------------------------- Eintrag unter Einstellungen → TTS-Server

def archiviert() -> bool:
    from . import tts
    cfg = tts._cfg()
    return not any(s.get("mitgeliefert") for s in cfg["tts_server"]) and any(s.get("mitgeliefert") for s in cfg["tts_archiv"])


def eintrag() -> dict | None:
    from . import tts
    return next((s for s in tts.servers() if s.get("mitgeliefert")), None)


def eintragen(address: str) -> str:
    """TTS-Server-Eintrag anlegen bzw. Adresse anpassen; Stimmen, Stile und Tags laden."""
    from . import tts
    entry = eintrag()
    if entry is None:
        sid = tts.add_server({"preset": "libra", "name": NAME, "base_url": address})
        tts._set_state(sid, mitgeliefert=True)
        entry = tts.get_server(sid)
    elif entry.get("base_url") != address:
        tts.update_server(entry["id"], {"base_url": address})
        entry = tts.get_server(entry["id"])
    if entry.get("status") != "ok" or not entry.get("stimmen") or not entry.get("regie"):
        tts.verify(entry["id"])
    return entry["id"]


def sicherstellen(echo=print, timeout: float = START_TIMEOUT) -> str | None:
    """Beim Start der Oberfläche (im Hintergrund): eingerichtet und nicht archiviert → starten, eintragen."""
    if not eingerichtet() or archiviert():
        return None
    try:
        address = bereit(timeout)
        sid = eintragen(address)
    except Exception as exc:  # darf Story World nie aufhalten
        echo(f"Libra-TTS nicht verfügbar: {exc}")
        return None
    echo(f"Libra-TTS bereit: {address}")
    return sid


def status() -> dict:
    running = laeuft()
    entry = eintrag()
    return {"vorhanden": vorhanden(), "eingerichtet": eingerichtet(), "nachinstallation": braucht_nachinstallation(),
            "laeuft": bool(running), "bereit": bool(running and running.get("bereit")),
            "adresse": url(running["port"]) if running else None, "server_id": entry["id"] if entry else None,
            "archiviert": archiviert() if vorhanden() else False,
            "eingerichtet_am": _load().get("eingerichtet_am"),
            "download": {"groesse": DOWNLOAD_GROESSE, "quellen": DOWNLOAD_QUELLEN}}
