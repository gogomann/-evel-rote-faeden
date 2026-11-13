"""Programm-Update über Codeberg-Releases (nur Python-Standardbibliothek).

Ablauf:
1. Prüfen: Codeberg-API `releases/latest` (gibt es kein Release: höchster Tag `vX.Y.Z`).
2. Installieren: ZIP nach `_update/` laden, sicher entpacken, Version im Paket gegen das Release prüfen.
   Ersetzt werden nur Programmdateien, die sich wirklich geändert haben. Die alte Fassung jeder ersetzten oder
   entfallenen Datei kommt nach `_old/update-<alt>-nach-<neu>-<zeit>/` – gelöscht wird nichts.
   Nutzerdaten (Welten, Einstellungen, Profile, Stimmen, Texte, Exporte, SQLite-Dateien) werden nie angefasst.
   Geht unterwegs etwas schief, wird der alte Stand wiederhergestellt.
3. Neustart: Danach passt `migrations.migrate` beim Öffnen jeder Welt das Schema an (mit Sicherung).

Ein Ordner mit `.git/` (Entwicklerstand) wird nie per Update überschrieben – dort `git pull`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from . import __version__

ROOT = Path(__file__).resolve().parent.parent
REPO = os.environ.get("STORY_UPDATE_REPO", "gogomann/evel-rote-faeden")
WEB = os.environ.get("STORY_UPDATE_WEB", "https://codeberg.org").rstrip("/")
API = f"{WEB}/api/v1"
CHANGELOG = "AENDERUNGEN.md"
MAX_DOWNLOAD = 200 * 1024 * 1024
MAX_UNPACKED = 500 * 1024 * 1024
AUTO_INTERVAL = 20 * 3600

# Nie überschreiben, nie verschieben – egal was im Paket steht.
PROTECTED_DIRS = {"welten", "exporte", "profile_texte", "_old", "_update", ".git", "__pycache__",
                  "unsloth-tmp", "_gedaechtnis"}
PROTECTED_NAMES = {".mcp.json", ".DS_Store", "Thumbs.db"}
PROTECTED_TOP = re.compile(r"^story_world\.[^/]+\.(json|tmp)$|^story_world\.[^/]+\.defekt-.*$")
PROTECTED_SUFFIX = re.compile(r"\.sqlite3(-journal|-wal|-shm)?$|\.update-tmp$")

_LOCK = threading.Lock()


class UpdateError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- Hilfen

def parse_version(text: str) -> tuple:
    """'v1.2.3' / '1.2' / '1.2.3-beta' → (1, 2, 3)."""
    core = str(text or "").strip().lstrip("vV").split("-")[0].split("+")[0]
    nums = [int(n) for n in re.findall(r"\d+", core)[:3]]
    if not nums:
        raise UpdateError(f"Unbekanntes Versionsformat: {text!r}")
    return tuple(nums + [0] * (3 - len(nums)))


def version_text(text: str) -> str:
    return ".".join(str(n) for n in parse_version(text))


def is_dev(root: Path = ROOT) -> bool:
    return (root / ".git").exists()


def protected(rel: str) -> bool:
    path = PurePosixPath(rel)
    if any(part in PROTECTED_DIRS for part in path.parts):
        return True
    if path.name in PROTECTED_NAMES or PROTECTED_SUFFIX.search(path.name):
        return True
    return len(path.parts) == 1 and bool(PROTECTED_TOP.match(path.name))


def _state_dir(root: Path) -> Path:
    path = root / "_update"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _state(root: Path) -> dict:
    return _read_json(_state_dir(root) / "zustand.json")


def _save_state(root: Path, **changes) -> dict:
    state = _state(root)
    state.update(changes)
    _write_json(_state_dir(root) / "zustand.json", state)
    return state


def _same(a: Path, b: Path) -> bool:
    if not a.is_file() or not b.is_file() or a.stat().st_size != b.stat().st_size:
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(1 << 16), fb.read(1 << 16)
            if x != y:
                return False
            if not x:
                return True


def _files(base: Path) -> list:
    out = []
    for path in base.rglob("*"):
        if path.is_file() and not path.is_symlink():
            rel = path.relative_to(base).as_posix()
            if not protected(rel):
                out.append(rel)
    return sorted(out)


def read_package_version(init_file: Path) -> str:
    match = re.search(r"""^__version__\s*=\s*["']([^"']+)["']""", init_file.read_text(encoding="utf-8"), re.M)
    if not match:
        raise UpdateError("Im Paket fehlt die Versionsangabe (story_world/__init__.py).")
    return match.group(1)


def changelog_sections(root: Path, after: str | None, upto: str) -> list:
    """Abschnitte aus AENDERUNGEN.md mit after < Version <= upto, neueste zuerst."""
    path = root / CHANGELOG
    if not path.exists():
        return []
    low = parse_version(after) if after else (-1,)
    high = parse_version(upto)
    out, current = [], None
    for line in path.read_text(encoding="utf-8").splitlines():
        head = re.match(r"^##\s+v?(\d+(?:\.\d+){0,2})\b(.*)$", line)
        if head:
            ver = parse_version(head.group(1))
            current = {"version": version_text(head.group(1)), "titel": line[2:].strip(), "text": []} \
                if low < ver <= high else None
            if current:
                out.append(current)
        elif current is not None:
            current["text"].append(line)
    for section in out:
        section["text"] = "\n".join(section["text"]).strip()
    return sorted(out, key=lambda s: parse_version(s["version"]), reverse=True)


# ---------------------------------------------------------------- Prüfen

def _get_json(url: str, timeout: int = 15):
    from .providers import _ssl_context
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": f"EvelRoteFaeden/{__version__} (Update)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            return json.loads(response.read(4_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise UpdateError(f"Codeberg antwortet mit Fehler {exc.code}.", 502)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f"Codeberg nicht erreichbar: {getattr(exc, 'reason', exc)}", 502)


def _archive_url(tag: str) -> str:
    return f"{WEB}/{REPO}/archive/{tag}.zip"


def check(root: Path = ROOT) -> dict:
    """Neueste veröffentlichte Version auf Codeberg ermitteln und mit der laufenden vergleichen."""
    found = None
    release = _get_json(f"{API}/repos/{REPO}/releases/latest")
    if release and release.get("tag_name") and not release.get("draft"):
        zips = [a.get("browser_download_url") for a in release.get("assets") or []
                if str(a.get("name", "")).lower().endswith(".zip") and a.get("browser_download_url")]
        found = {"tag": release["tag_name"], "notizen": release.get("body") or "",
                 "titel": release.get("name") or release["tag_name"],
                 "veroeffentlicht": release.get("published_at") or "",
                 "zip": zips[0] if zips else (release.get("zipball_url") or _archive_url(release["tag_name"]))}
    else:
        tags = _get_json(f"{API}/repos/{REPO}/tags?limit=50") or []
        versioned = []
        for tag in tags:
            name = str(tag.get("name", ""))
            if re.match(r"^v?\d+(\.\d+){0,2}$", name):
                versioned.append((parse_version(name), tag))
        if versioned:
            _, tag = max(versioned, key=lambda x: x[0])
            found = {"tag": tag["name"], "notizen": "", "titel": tag["name"], "veroeffentlicht": "",
                     "zip": tag.get("zipball_url") or _archive_url(tag["name"])}
    result = {"aktuell": __version__, "entwickler": is_dev(root), "geprueft": time.strftime("%Y-%m-%d %H:%M")}
    if not found:
        result.update({"neueste": None, "neuer": False})
    else:
        latest = version_text(found["tag"])
        result.update({"neueste": latest, "neuer": parse_version(latest) > parse_version(__version__), **found})
    _save_state(root, letzte_pruefung=time.time(),
                verfuegbar={k: result.get(k) for k in ("neueste", "tag", "titel", "notizen")} if result["neuer"] else None)
    return result


def auto_check(root: Path = ROOT) -> None:
    """Beim Start höchstens alle ~20 h still prüfen (abschaltbar). Fehler bleiben still."""
    state = _state(root)
    if not state.get("automatisch", True) or time.time() - float(state.get("letzte_pruefung") or 0) < AUTO_INTERVAL:
        return
    try:
        check(root)
    except Exception:
        pass


def set_auto(enabled: bool, root: Path = ROOT) -> dict:
    _save_state(root, automatisch=bool(enabled))
    return {"automatisch": bool(enabled)}


# ---------------------------------------------------------------- Laden & Entpacken

def download(url: str, target: Path) -> Path:
    if not url.startswith(WEB + "/"):
        raise UpdateError("Download-Adresse liegt nicht auf Codeberg – abgebrochen.")
    from .providers import _ssl_context
    request = urllib.request.Request(url, headers={"User-Agent": f"EvelRoteFaeden/{__version__} (Update)"})
    part = target.with_name(target.name + ".part")
    try:
        with urllib.request.urlopen(request, timeout=60, context=_ssl_context()) as response, open(part, "wb") as fh:
            size = 0
            while True:
                chunk = response.read(1 << 16)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise UpdateError("Download zu groß – abgebrochen.")
                fh.write(chunk)
    except urllib.error.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Download fehlgeschlagen (Fehler {exc.code}).", 502)
    except (urllib.error.URLError, OSError) as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"Download fehlgeschlagen: {getattr(exc, 'reason', exc)}", 502)
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    os.replace(part, target)
    return target


def extract(zip_path: Path, dest: Path) -> Path:
    """Sicher entpacken (keine absoluten Pfade, kein '..', keine Links) und Paketwurzel liefern."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise UpdateError("Die heruntergeladene Datei ist kein gültiges ZIP.")
    with archive:
        infos = archive.infolist()
        if sum(i.file_size for i in infos) > MAX_UNPACKED:
            raise UpdateError("Paket entpackt zu groß – abgebrochen.")
        for info in infos:
            name = info.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
                raise UpdateError(f"Unsicherer Pfad im Paket: {info.filename}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UpdateError(f"Verknüpfung im Paket nicht erlaubt: {info.filename}")
            if not parts:
                continue
            target = dest.joinpath(*parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            mode = (info.external_attr >> 16) & 0o777
            if mode & 0o111 or target.suffix in (".command", ".sh"):
                target.chmod(0o755)
    roots = sorted({p.parent.parent for p in dest.rglob("story_world/__init__.py")},
                   key=lambda p: len(p.relative_to(dest).parts))
    if not roots or len(roots[0].relative_to(dest).parts) > 2:
        raise UpdateError("Im Paket wurde kein Evel-Programm gefunden (story_world/ fehlt).")
    return roots[0]


# ---------------------------------------------------------------- Installieren

def install_from_zip(zip_path: Path, root: Path = ROOT, notes: str = "", tag: str = "") -> dict:
    """Programmdateien aus einem Release-ZIP übernehmen. Nutzerdaten bleiben unberührt."""
    if is_dev(root):
        raise UpdateError("Dieser Ordner ist ein Git-Entwicklerstand – dort bitte mit „git pull“ aktualisieren.", 409)
    if not _LOCK.acquire(blocking=False):
        raise UpdateError("Es läuft bereits ein Update.", 409)
    try:
        return _install(Path(zip_path), root, notes, tag)
    finally:
        _LOCK.release()


def _install(zip_path: Path, root: Path, notes: str, tag: str) -> dict:
    work = _state_dir(root)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    staging = work / f"entpackt-{stamp}"
    if staging.exists():
        shutil.rmtree(staging)
    try:
        package = extract(zip_path, staging)
        new_version = read_package_version(package / "story_world" / "__init__.py")
        if tag and parse_version(new_version) != parse_version(tag):
            raise UpdateError(f"Paket meldet Version {new_version}, das Release heißt {tag} – abgebrochen.")
        old_version = read_package_version(root / "story_world" / "__init__.py") \
            if (root / "story_world" / "__init__.py").exists() else "0"
        if parse_version(new_version) <= parse_version(old_version):
            raise UpdateError(f"Version {new_version} ist nicht neuer als die installierte {old_version}.", 409)

        new_files = _files(package)
        changed = [rel for rel in new_files if not _same(package / rel, root / rel)]
        manifest = _read_json(work / "manifest.json").get("dateien")
        if manifest is None:  # erstes Update: Programmordner gelten vollständig als Programm
            manifest = [rel for sub in ("story_world", "tests") if (root / sub).is_dir()
                        for rel in (f"{sub}/{r}" for r in _files(root / sub))]
        keep = set(new_files)
        removed = [rel for rel in manifest if rel not in keep and not protected(rel) and (root / rel).is_file()]

        backup = root / "_old" / f"update-{old_version}-nach-{new_version}-{stamp}"
        replaced, created, moved = [], [], []
        try:
            for rel in changed:
                dst = root / rel
                if dst.exists():
                    (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dst, backup / rel)
                    replaced.append(rel)
                else:
                    created.append(rel)
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_name(dst.name + ".update-tmp")
                shutil.copy2(package / rel, tmp)
                os.replace(tmp, dst)
            for rel in removed:
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(root / rel), str(backup / rel))
                moved.append(rel)
        except Exception as exc:
            _rollback(root, backup, replaced, created, moved)
            raise UpdateError(f"Update abgebrochen, der alte Stand ist wiederhergestellt: {exc}", 500)

        _write_json(work / "manifest.json", {"version": new_version, "dateien": new_files})
        report = {"von": old_version, "nach": new_version, "tag": tag or f"v{new_version}", "zeit": stamp,
                  "notizen": notes, "geaendert": len(replaced), "neu": len(created), "entfallen": len(moved),
                  "sicherung": backup.relative_to(root).as_posix() if (replaced or moved) else None}
        _write_json(work / "installiert.json", report)
        _save_state(root, verfuegbar=None)
        return report
    finally:
        shutil.rmtree(staging, ignore_errors=True)  # nur die entpackte Kopie; das ZIP bleibt in _update/


def _rollback(root: Path, backup: Path, replaced: list, created: list, moved: list) -> None:
    for rel in moved:
        if (backup / rel).exists():
            shutil.move(str(backup / rel), str(root / rel))
    for rel in replaced:
        if (backup / rel).exists():
            shutil.copy2(backup / rel, root / rel)
    for rel in created:  # neu angelegte Dateien nicht löschen, sondern beiseitelegen
        if (root / rel).exists():
            target = backup / "_abgebrochen" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(root / rel), str(target))


def install(root: Path = ROOT) -> dict:
    """Prüfen, neueste Version laden und installieren."""
    if is_dev(root):
        raise UpdateError("Dieser Ordner ist ein Git-Entwicklerstand – dort bitte mit „git pull“ aktualisieren.", 409)
    info = check(root)
    if not info.get("neuer"):
        raise UpdateError(f"Keine neuere Version vorhanden (installiert: {__version__}).", 409)
    target = _state_dir(root) / f"evel-rote-faeden-{info['tag']}.zip"
    download(info["zip"], target)
    return install_from_zip(target, root, info.get("notizen", ""), info["tag"])


# ---------------------------------------------------------------- Nach dem Update

def status(root: Path = ROOT) -> dict:
    from . import migrations
    state = _state(root)
    seen = state.get("gesehen_version")
    if seen is None:  # erster Start mit Update-Funktion: still merken, kein Banner
        state = _save_state(root, gesehen_version=__version__)
        seen = __version__
    installed = _read_json(root / "_update" / "installiert.json")
    out = {"version": __version__, "entwickler": is_dev(root), "automatisch": state.get("automatisch", True),
           "neustart_automatisch": sys.platform != "win32", "migrationen": list(migrations.REPORTS),
           "verfuegbar": None, "neu": None,
           "wartet_auf_neustart": bool(installed.get("nach")) and parse_version(installed["nach"]) > parse_version(__version__)}
    available = state.get("verfuegbar") or {}
    if available.get("neueste") and parse_version(available["neueste"]) > parse_version(__version__):
        out["verfuegbar"] = available
    if parse_version(seen) < parse_version(__version__):
        out["neu"] = {"von": seen, "nach": __version__, "abschnitte": changelog_sections(root, seen, __version__),
                      "notizen": installed.get("notizen", "") if installed.get("nach") == __version__ else "",
                      "sicherung": installed.get("sicherung") if installed.get("nach") == __version__ else None}
    return out


def acknowledge(root: Path = ROOT) -> dict:
    from . import migrations
    _save_state(root, gesehen_version=__version__)
    del migrations.REPORTS[:]
    return {"ok": True}


def restart(port: int, delay: float = 0.8) -> None:
    """Prozess durch eine frische Instanz ersetzen (macOS/Linux). Unter Windows: Fenster schließen und neu starten."""
    if sys.platform == "win32":
        raise UpdateError("Unter Windows bitte das Story-World-Fenster schließen und neu starten.")
    time.sleep(delay)
    sys.stdout.flush()
    sys.stderr.flush()
    os.chdir(ROOT)
    os.execv(sys.executable, [sys.executable, "-m", "story_world", "ui", "--port", str(port), "--kein-browser"])
