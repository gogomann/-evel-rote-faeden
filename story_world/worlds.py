"""Mehrere Welten: jede Welt ist eine eigene SQLite-Datei im Ordner welten/."""

from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from . import service
from .database import connect
from .migrations import migrate
from .seed import seed_from_rules

ROOT = Path(__file__).resolve().parent.parent
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


def worlds_dir() -> Path:
    path = Path(os.environ.get("STORY_WORLDS_DIR", ROOT / "welten"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify(name: str) -> str:
    text = name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:48] or "welt"


def path_for(slug: str) -> Path:
    if not SLUG_RE.match(slug):
        raise service.ValidationError("Ungültiger Weltname.")
    return worlds_dir() / f"{slug}.sqlite3"


@contextmanager
def open_world(slug: str):
    path = path_for(slug)
    if not path.exists():
        raise LookupError("Welt nicht gefunden.")
    conn = connect(path)
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        migrate(conn, path)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_worlds() -> list:
    out = []
    for path in sorted(worlds_dir().glob("*.sqlite3")):
        slug = path.stem
        if not SLUG_RE.match(slug):
            continue
        name, description = slug, ""
        try:
            with open_world(slug) as conn:
                m = service.meta(conn)
                name = m.get("name", slug)
                description = m.get("beschreibung", "")
        except (sqlite3.DatabaseError, RuntimeError) as exc:
            description = f"Fehler beim Öffnen: {exc}"
        out.append({"slug": slug, "name": name, "beschreibung": description})
    return out


def create_world(name: str, description: str = "", seed: bool = True) -> str:
    if not name or not name.strip():
        raise service.ValidationError("Name der Welt fehlt.")
    slug = slugify(name)
    path = path_for(slug)
    if path.exists():
        raise service.ValidationError(f"Eine Welt „{slug}“ existiert bereits.")
    conn = connect(path)
    try:
        migrate(conn, path)
        service.set_meta(conn, "name", name.strip())
        service.set_meta(conn, "beschreibung", (description or "").strip())
        if seed:
            seed_from_rules(conn)
        service.audit(conn, "nutzer", "welt_angelegt", detail=name.strip())
        conn.commit()
    except Exception:
        conn.close()
        path.unlink(missing_ok=True)
        raise
    conn.close()
    return slug


# ---------------------------------------------------------------- Sicherungen

def list_backups() -> list:
    folder = worlds_dir() / "backups"
    if not folder.exists():
        return []
    out = []
    for path in sorted(folder.glob("*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        out.append({"datei": path.name, "groesse": stat.st_size,
                    "zeit": __import__("time").strftime("%Y-%m-%d %H:%M", __import__("time").localtime(stat.st_mtime))})
    return out


def restore_backup(filename: str) -> str:
    """Stellt eine Sicherung als NEUE Welt wieder her – das Original und die Sicherung bleiben unverändert."""
    folder = (worlds_dir() / "backups").resolve()
    source = (folder / filename).resolve()
    if source.parent != folder or source.suffix != ".sqlite3" or not source.exists():
        raise service.ValidationError("Sicherung nicht gefunden.")
    import time as _time
    base = slugify(source.stem)[:30]
    slug = slugify(f"{base}-wiederhergestellt-{_time.strftime('%Y%m%d-%H%M%S')}")
    target = path_for(slug)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
        check = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise service.ValidationError(f"Sicherung ist beschädigt: {check}")
    finally:
        src.close()
        dst.close()
    with open_world(slug) as conn:
        problems = conn.execute("PRAGMA foreign_key_check").fetchall()
        name = service.meta(conn).get("name", base)
        service.set_meta(conn, "name", f"{name} (wiederhergestellt {_time.strftime('%d.%m. %H:%M')})")
        service.audit(conn, "nutzer", "wiederherstellung", detail=f"{filename}; Fremdschlüsselprobleme: {len(problems)}")
    return slug
