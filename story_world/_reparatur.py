"""Reparatur nach einem unterbrochenen Update (Stromausfall, Absturz, Kill).

Bewusst minimal: nur Standardbibliothek, keine Importe aus dem Paket. So läuft es auch dann, wenn ein
abgebrochenes Update einen Mischstand aus alten und neuen Programmdateien hinterlassen hat.

Ablauf:
- `update._install` schreibt vor dem ersten Kopiervorgang `_update/laufend.json` (Journal: von/nach/Dateilisten/PID)
  und räumt es nach Erfolg weg (es wandert als `update.json` in den Sicherungsordner).
- Beim Import von `story_world` ruft `__init__.py` `beim_start()` auf. Liegt ein verwaistes Journal vor
  (Prozess lebt nicht mehr oder Journal älter als 10 Minuten), wird der alte Stand aus `_old/update-…`
  wiederhergestellt. Neu angelegte Dateien kommen nach `…/_abgebrochen/` – gelöscht wird nichts.
- Ergebnis: `_update/reparatur.json`; die Oberfläche zeigt daraus einen Hinweis.

Das Journal-Format muss über Versionen hinweg stabil bleiben (alte und neue Fassung dieser Datei lesen es).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = "laufend.json"
REPORT = "reparatur.json"
TMP_SUFFIX = ".update-tmp"
STALE_AFTER = 600  # Sekunden; ein echtes Update kopiert nur wenige Sekunden


def copy_atomic(src: Path, dst: Path) -> None:
    """Kopie, die nie halb geschrieben sichtbar ist (Zieldatei ist danach alt oder neu, nie kaputt)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + TMP_SUFFIX)
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _alive(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():  # eigener Prozess: Wir starten gerade, ein Update läuft hier nicht
        return False
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _abandoned(journal: dict) -> bool:
    started = float(journal.get("start") or 0)
    if time.time() - started > STALE_AFTER:
        return True
    return not _alive(int(journal.get("pid") or 0))


def _aside(root: Path, rel: str, target: Path) -> bool:
    """Datei aus dem Programmordner nach `target` verschieben (statt löschen)."""
    src = root / rel
    if not src.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = target.with_name(f"{target.name}.{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.move(str(src), str(target))
    return True


def repair(root: Path = ROOT) -> dict | None:
    """Verwaistes Update-Journal abarbeiten. Gibt den Bericht zurück oder None, wenn nichts zu tun war."""
    work = root / "_update"
    marker = work / MARKER
    if not marker.exists():
        return None
    try:
        journal = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        journal = None
    if isinstance(journal, dict) and not _abandoned(journal):
        return None  # ein anderer Prozess installiert gerade
    claimed = work / f"laufend.reparatur-{os.getpid()}.json"
    try:
        os.replace(marker, claimed)  # nur ein Prozess gewinnt
    except OSError:
        return None
    if not isinstance(journal, dict) or not journal.get("sicherung"):
        report = {"zeit": time.strftime("%Y-%m-%d %H:%M"), "fehler": "Update-Journal unlesbar – bitte von Hand prüfen.",
                  "journal": claimed.name, "gesehen": False}
        write_json(work / REPORT, report)
        return report

    backup = root / journal["sicherung"]
    aside = backup / "_abgebrochen"
    restored, set_aside = [], []
    for rel in journal.get("entfallen") or []:
        if (backup / rel).exists() and not (root / rel).exists():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(backup / rel), str(root / rel))
            restored.append(rel)
    for rel in journal.get("ersetzen") or []:
        if (backup / rel).is_file():  # fehlt die Sicherung, wurde die Datei nie angefasst
            copy_atomic(backup / rel, root / rel)
            restored.append(rel)
    for rel in journal.get("neu") or []:
        if _aside(root, rel, aside / rel):
            set_aside.append(rel)
    for rel in list(journal.get("ersetzen") or []) + list(journal.get("neu") or []):
        _aside(root, rel + TMP_SUFFIX, aside / (rel + TMP_SUFFIX))

    backup.mkdir(parents=True, exist_ok=True)
    os.replace(claimed, backup / "abgebrochen.json")
    report = {"zeit": time.strftime("%Y-%m-%d %H:%M"), "von": journal.get("von"), "nach": journal.get("nach"),
              "wiederhergestellt": len(restored), "beiseitegelegt": len(set_aside),
              "sicherung": journal["sicherung"], "gesehen": False}
    write_json(work / REPORT, report)
    return report


def beim_start(root: Path = ROOT) -> None:
    """Beim Programmstart aufrufen. Darf den Start nie verhindern; Meldungen nur auf stderr (MCP nutzt stdout)."""
    try:
        report = repair(root)
    except Exception as exc:  # noqa: BLE001
        print(f"Story World: Reparatur nach unterbrochenem Update fehlgeschlagen: {exc}", file=sys.stderr)
        return
    if report and not report.get("fehler"):
        print(f"Story World: Unterbrochenes Update {report['von']} → {report['nach']} erkannt, "
              f"Stand {report['von']} wiederhergestellt ({report['sicherung']}).", file=sys.stderr)
    elif report:
        print(f"Story World: {report['fehler']}", file=sys.stderr)
