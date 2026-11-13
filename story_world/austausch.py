"""Export und Import: Welt, Autor oder alles – als eine ZIP-Datei für den Umzug auf einen anderen Rechner.

Welt-Export: Welt-Datenbank (Kanon, Folgen, Nachvollzug, Stimmen-Verweise) + jede Stimme, die die Welt nutzt, vollständig
(Steckbrief, Regler, Hinweise, Probe, Maßstab) + bei Stimmen „wie ein Mensch“ statt der Volltexte nur Stilanker und
Maßstab-Auszug („Basis“). Eingearbeitete Text-Impulse (Abschnitte eingelesener Texte) werden ohne Inhalt exportiert,
ebenso die Prompts der Läufe, die sie eingelesen haben – der Kanon, der daraus entstand, bleibt vollständig.
Noch nicht eingearbeitete Text-Impulse gehen mit Inhalt mit, damit die Arbeit ohne Bruch weitergeht.

Autor-Export: Erzählprofile, eigene Texte (vollständig), alle Stimmen.

Import: Welten werden immer als neue Welt angelegt (nichts wird überschrieben). Basis-Texte und Text-Impulse sind nur
sichtbar, wenn ihr Besitzer (Profil-ID) auf diesem Rechner existiert – sonst liegen sie verborgen und werden trotzdem
benutzt. Kommt der Besitzer später per Autor-Import dazu, wird alles wieder sichtbar.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
import zlib
from pathlib import Path

from . import migrations, profiles, service, stimmen, worlds

ROOT = Path(__file__).resolve().parent.parent
FORMAT = "storyworld-export"
VERSION = 1
HIDDEN_NOTE = "[🔒 Inhalt verborgen – Text eines anderen Autors]"
MAX_IMPORT = 4 * 1024 ** 3


class ExchangeError(RuntimeError):
    pass


def export_dir() -> Path:
    path = Path(os.environ.get("STORY_EXPORTS", ROOT / "exporte"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def list_exports() -> list:
    out = []
    for p in sorted(export_dir().glob("*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        out.append({"datei": p.name, "groesse": p.stat().st_size,
                    "zeit": time.strftime("%Y-%m-%d %H:%M", time.localtime(p.stat().st_mtime))})
    return out


def export_file(name: str) -> Path:
    folder = export_dir().resolve()
    path = (folder / name).resolve()
    if path.parent != folder or path.suffix != ".zip" or not path.exists():
        raise LookupError("Export nicht gefunden.")
    return path


# ---------------------------------------------------------------- Welt

def _voice_ids(conn: sqlite3.Connection) -> list:
    ids = set()
    try:
        ids.add(service.setting(conn, "stimme"))
        for table in ("threads", "episodes"):
            ids |= {r[0] for r in conn.execute(f"SELECT DISTINCT stimme_id FROM {table} WHERE stimme_id IS NOT NULL")}
    except sqlite3.OperationalError:
        pass
    return sorted(i for i in ids if i)


def _text_owners(slug: str) -> dict:
    """Titel eingelesener Texte → (Besitzer, Text-id, fremd) – für Impulse aus der Zeit vor der Herkunftsspalte."""
    out = {}
    for p in profiles.list_profiles()["profiles"]:
        for t in p.get("texte", []) + p.get("texte_archiv", []):
            if any(e.get("welt") == slug for e in t.get("eingelesen", [])):
                out[t["titel"]] = (p["id"], t["id"], bool(t.get("fremd")))
    return out


def _prepare_world_copy(db: Path, slug: str) -> dict:
    """Arbeitet nur auf der Kopie: Herkunft der Text-Impulse nachtragen, Inhalte eingearbeiteter Abschnitte leeren."""
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    owners = _text_owners(slug)
    report = {"text_impulse_ohne_inhalt": 0, "text_impulse_mit_inhalt": 0, "laeufe_ohne_prompt": 0}
    try:
        for row in conn.execute("SELECT id, title, status, besitzer FROM impulses WHERE kind = 'text'").fetchall():
            if not row["besitzer"]:
                base = row["title"].split(" – Teil ")[0]
                if base in owners:
                    owner, tid, foreign = owners[base]
                    conn.execute("UPDATE impulses SET besitzer = ?, quelle_text = ?, fremd = ? WHERE id = ?",
                                 (owner, tid, 1 if foreign else 0, row["id"]))
            if row["status"] in ("eingearbeitet", "verworfen"):
                conn.execute("UPDATE impulses SET content = ?, content_verborgen = NULL WHERE id = ?",
                             ("[Abschnitt eines eingelesenen Textes – Inhalt nicht exportiert, das Weltwissen daraus "
                              "steht im Kanon]", row["id"]))
                report["text_impulse_ohne_inhalt"] += 1
                runs = [r[0] for r in conn.execute("SELECT id FROM ai_runs WHERE impulse_id = ?", (row["id"],))]
                for run_id in runs:
                    conn.execute("UPDATE ai_runs SET auftrag = ?, prompt = NULL, response = NULL WHERE id = ?",
                                 ("[Abschnitt eines eingelesenen Textes – nicht exportiert]", run_id))
                    conn.execute("UPDATE ai_calls SET messages = ?, response = NULL WHERE run_id = ?",
                                 (zlib.compress(json.dumps([{"role": "user", "content": "[nicht exportiert]"}]).encode()),
                                  run_id))
                    report["laeufe_ohne_prompt"] += 1
            else:
                report["text_impulse_mit_inhalt"] += 1
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    return report


def _snapshot(slug: str, target: Path) -> None:
    with worlds.open_world(slug) as conn:  # bringt die Welt aufs aktuelle Schema
        dest = sqlite3.connect(target)
        try:
            conn.backup(dest)
        finally:
            dest.close()


def _add_world(zf: zipfile.ZipFile, slug: str, prefix: str, audio: bool, tmp: Path) -> dict:
    db = tmp / f"{slug}.sqlite3"
    _snapshot(slug, db)
    report = _prepare_world_copy(db, slug)
    conn = sqlite3.connect(db)
    try:
        voice_ids = _voice_ids(conn)
        name = dict(conn.execute("SELECT key, value FROM world_meta").fetchall()).get("name", slug)
        schema = migrations.current_version(conn)
    finally:
        conn.close()
    voices, missing = [], []
    for vid in voice_ids:
        v = stimmen.get(vid) or next((x for x in stimmen.all_raw()["archiv"] if x["id"] == vid), None)
        if v:
            voices.append(stimmen.export_copy(v))
        else:
            missing.append(vid)
    zf.write(db, f"{prefix}welt.sqlite3")
    zf.writestr(f"{prefix}stimmen.json", json.dumps({"stimmen": voices}, ensure_ascii=False, indent=1))
    files = 0
    if audio:
        folder = worlds.worlds_dir() / "audio" / slug
        if folder.exists():
            for f in folder.rglob("*"):
                rel = f.relative_to(folder)
                if f.is_file() and rel.parts[0] not in ("_tts_cache", "_wav"):
                    zf.write(f, f"{prefix}audio/{rel.as_posix()}")
                    files += 1
    meta = {"slug": slug, "name": name, "schema": schema, "stimmen": [v["id"] for v in voices],
            "stimmen_fehlen": missing, "audio_dateien": files, **report}
    zf.writestr(f"{prefix}welt.json", json.dumps(meta, ensure_ascii=False, indent=1))
    return meta


def _manifest(typ: str, extra: dict) -> str:
    return json.dumps({"format": FORMAT, "version": VERSION, "typ": typ, "exportiert": time.strftime("%Y-%m-%d %H:%M"),
                       **extra}, ensure_ascii=False, indent=1)


def export_world(slug: str, audio: bool = False) -> dict:
    worlds.path_for(slug)
    target = export_dir() / f"welt-{slug}-{_stamp()}.zip"
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        meta = _add_world(zf, slug, "", audio, Path(tmp))
        zf.writestr("manifest.json", _manifest("welt", {"welten": [meta]}))
    return {"datei": target.name, "groesse": target.stat().st_size, "welt": meta}


# ---------------------------------------------------------------- Autor

def _add_author(zf: zipfile.ZipFile, prefix: str) -> dict:
    data = profiles._load()
    zf.writestr(f"{prefix}profiles.json", json.dumps(data, ensure_ascii=False, indent=1))
    texts = 0
    for p in data["profiles"] + data["archiv"]:
        for t in p.get("texte", []) + p.get("texte_archiv", []):
            try:
                body = profiles.read_text(p["id"], t["id"])
            except LookupError:
                continue
            zf.writestr(f"{prefix}texte/{p['id']}/{t['id']}.txt", body)
            texts += 1
    voices = stimmen.all_raw()
    zf.writestr(f"{prefix}stimmen.json", json.dumps(voices, ensure_ascii=False, indent=1))
    return {"profile": [{"id": p["id"], "name": p["name"]} for p in data["profiles"]], "texte": texts,
            "stimmen": len(voices["stimmen"]) + len(voices["archiv"])}


def export_author() -> dict:
    target = export_dir() / f"autor-{_stamp()}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        meta = _add_author(zf, "autor/")
        zf.writestr("manifest.json", _manifest("autor", {"autor": meta}))
    return {"datei": target.name, "groesse": target.stat().st_size, "autor": meta}


def export_all(audio: bool = False) -> dict:
    target = export_dir() / f"alles-{_stamp()}.zip"
    metas = []
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        author = _add_author(zf, "autor/")
        for w in worlds.list_worlds():
            metas.append(_add_world(zf, w["slug"], f"welten/{w['slug']}/", audio, Path(tmp)))
        zf.writestr("manifest.json", _manifest("alles", {"autor": author, "welten": metas}))
    return {"datei": target.name, "groesse": target.stat().st_size, "autor": author, "welten": metas}


# ---------------------------------------------------------------- Import

def _safe_names(zf: zipfile.ZipFile) -> None:
    total = 0
    for info in zf.infolist():
        name = info.filename
        if name.startswith("/") or ".." in Path(name).parts or "\\" in name:
            raise ExchangeError(f"Unsichere Datei im Export: {name}")
        total += info.file_size
    if total > MAX_IMPORT:
        raise ExchangeError("Export zu groß.")


def _local_profile_ids() -> set:
    data = profiles._load()
    return {p["id"] for p in data["profiles"] + data["archiv"]}


def _import_author(zf: zipfile.ZipFile, prefix: str) -> dict:
    incoming = json.loads(zf.read(f"{prefix}profiles.json"))
    report = {"profile_neu": [], "profile_vorhanden": [], "texte_neu": 0, "stimmen": {}, "freigeschaltet": 0}
    with profiles._LOCK:
        data = profiles._load()
        known = {p["id"]: p for p in data["profiles"] + data["archiv"]}
        for section in ("profiles", "archiv"):
            for p in incoming.get(section, []):
                if not str(p.get("id", "")).startswith("u_"):
                    continue
                local = known.get(p["id"])
                if local is None:
                    data[section].append(p)
                    known[p["id"]] = p
                    report["profile_neu"].append(p.get("name"))
                    continue
                report["profile_vorhanden"].append(p.get("name"))
                have = {t["id"] for t in local.get("texte", []) + local.get("texte_archiv", [])}
                for key in ("texte", "texte_archiv"):
                    for t in p.get(key, []):
                        if t["id"] not in have:
                            local.setdefault(key, []).append(t)
        profiles._save(data)
    for info in zf.infolist():
        if not info.filename.startswith(f"{prefix}texte/") or info.is_dir():
            continue
        parts = Path(info.filename).parts
        pid, name = parts[-2], parts[-1]
        if not (pid.startswith("u_") and name.startswith("t_") and name.endswith(".txt")):
            continue
        target = profiles.text_dir(pid) / name
        if not target.exists():
            fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(zf.read(info))
            report["texte_neu"] += 1
    voices = json.loads(zf.read(f"{prefix}stimmen.json"))
    local = _local_profile_ids()
    for v in voices.get("stimmen", []) + voices.get("archiv", []):
        state = stimmen.import_voice(v, local, "Autor-Import")
        report["stimmen"][state] = report["stimmen"].get(state, 0) + 1
    for pid in local:
        report["freigeschaltet"] += stimmen.unhide_owner(pid) + _unhide_worlds(pid)
    return report


def _unhide_worlds(pid: str) -> int:
    count = 0
    for w in worlds.list_worlds():
        try:
            with worlds.open_world(w["slug"]) as conn:
                cur = conn.execute("UPDATE impulses SET content = content_verborgen, content_verborgen = NULL "
                                   "WHERE besitzer = ? AND content_verborgen IS NOT NULL", (pid,))
                count += cur.rowcount
        except Exception:  # noqa: BLE001 – eine kaputte Welt darf den Import nicht stoppen
            continue
    return count


def _free_slug(slug: str) -> str:
    if not worlds.path_for(slug).exists():
        return slug
    return worlds.slugify(f"{slug[:28]}-import-{_stamp()}")


def _import_world(zf: zipfile.ZipFile, prefix: str) -> dict:
    meta = json.loads(zf.read(f"{prefix}welt.json"))
    slug = _free_slug(worlds.slugify(meta.get("slug") or meta.get("name") or "welt"))
    target = worlds.path_for(slug)
    with zf.open(f"{prefix}welt.sqlite3") as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst)
    local = _local_profile_ids()
    report = {"slug": slug, "name": meta.get("name"), "stimmen": {}, "verborgen": 0, "audio": 0}
    voices = json.loads(zf.read(f"{prefix}stimmen.json")).get("stimmen", [])
    for v in voices:
        state = stimmen.import_voice(v, local, f"Welt-Import „{meta.get('name') or slug}“")
        report["stimmen"][state] = report["stimmen"].get(state, 0) + 1
    with worlds.open_world(slug) as conn:  # prüft und migriert
        check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise ExchangeError(f"Welt-Datenbank beschädigt: {check}")
        if slug != meta.get("slug"):
            service.set_meta(conn, "name", f"{meta.get('name') or slug} (Import)")
        for row in conn.execute("SELECT id, besitzer, fremd FROM impulses WHERE kind = 'text' "
                                "AND content_verborgen IS NULL AND status NOT IN ('eingearbeitet', 'verworfen')").fetchall():
            if row[1] not in local:  # fremder Besitzer → Inhalt ins verborgene Feld
                conn.execute("UPDATE impulses SET content_verborgen = content, content = ? WHERE id = ?",
                             (HIDDEN_NOTE, row[0]))
                report["verborgen"] += 1
        if slug != meta.get("slug"):
            old = f"audio/{meta.get('slug')}/"
            conn.execute("UPDATE episodes SET audio_path = 'audio/' || ? || '/' || substr(audio_path, ?) "
                         "WHERE audio_path LIKE ?", (slug, len(old) + 1, old + "%"))
        service.audit(conn, "system", "import", detail=f"Welt-Import aus „{meta.get('name')}“ ({meta.get('slug')})")
    folder = worlds.worlds_dir() / "audio" / slug
    for info in zf.infolist():
        if info.filename.startswith(f"{prefix}audio/") and not info.is_dir():
            rel = Path(info.filename).relative_to(f"{prefix}audio")
            dest = folder / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                with zf.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
                report["audio"] += 1
    return report


def import_package(path: Path) -> dict:
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ExchangeError("Keine gültige Export-Datei (ZIP).")
    with zf:
        _safe_names(zf)
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except KeyError:
            raise ExchangeError("Keine Story-World-Exportdatei (manifest.json fehlt).")
        if manifest.get("format") != FORMAT:
            raise ExchangeError("Keine Story-World-Exportdatei.")
        if int(manifest.get("version", 0)) > VERSION:
            raise ExchangeError("Export stammt aus einer neueren Version – bitte Story World aktualisieren.")
        out = {"typ": manifest["typ"], "autor": None, "welten": []}
        if manifest["typ"] in ("autor", "alles"):
            out["autor"] = _import_author(zf, "autor/")
        if manifest["typ"] == "welt":
            out["welten"].append(_import_world(zf, ""))
        elif manifest["typ"] == "alles":
            for w in manifest.get("welten", []):
                out["welten"].append(_import_world(zf, f"welten/{w['slug']}/"))
        return out
