"""Kontext-Kaskade: statt den ganzen Kanon in jeden KI-Aufruf zu kippen, bekommt jede Ebene nur, was sie braucht.

Ebene 1 – Thema (makro):      kompakter Überblick (Stränge, Völker, große Orte, offene Rätsel, letzte Folgen, Namensliste)
Ebene 2 – Handlungslinie:     vollständige Datensätze der in Ebene 1 gewählten Beteiligten samt Umfeld
Ebene 3 – Szene (Autor):      nur Besetzung, Orte und Technik der Folge, Wissen bis zum Zeitpunkt
Prüfer und Archivar:          Datensätze, die im Text erwähnt werden, plus Namensverzeichnis gegen Doppelungen

Welche Datensätze dazugehören, entscheidet der Code (über Kennungen), nicht die KI.
"""

from __future__ import annotations

import json
import sqlite3

from . import service

ALWAYS = ("world_rules",)
FOCUS_TABLES = ("characters", "locations", "peoples", "technologies", "organizations", "threads", "events", "snippets")


def _rows(conn: sqlite3.Connection, table: str, where: str = "", params: tuple = ()) -> list:
    cfg = service.ENTITIES[table]
    cols = ["id"] + [f[0] for f in cfg["fields"]] + ["visibility"]
    out = []
    for r in conn.execute(f"SELECT {', '.join(cols)} FROM {table} {where} ORDER BY id", params):
        out.append({k: v for k, v in dict(r).items() if not service._empty(v)})
    return out


def _short(text, limit: int = 160) -> str:
    text = str(text or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def name_index(conn: sqlite3.Connection) -> dict:
    """Alle Namen mit id je Bereich – damit niemand etwas doppelt anlegt."""
    out = {}
    for table in ("characters", "locations", "peoples", "technologies", "organizations", "threads", "events",
                  "languages", "calendars", "mysteries", "codes"):
        title = service.ENTITIES[table]["title"]
        out[table] = [[r[0], _short(r[1], 60)] for r in conn.execute(f"SELECT id, {title} FROM {table} ORDER BY id")]
    return out


def overview(conn: sqlite3.Connection) -> dict:
    """Ebene 1: kompakter Überblick über die ganze Welt (wenige zehntausend Zeichen statt des ganzen Kanons)."""
    threads = [{"id": r["id"], "titel": r["title"], "ebene": r["level"], "status": r["status"],
                "praemisse": _short(r["premise"], 240), "weltzeit": r["world_time_cursor"], "genre_id": r["genre_id"]}
               for r in conn.execute("SELECT * FROM threads ORDER BY id")]
    peoples = [{"id": r[0], "name": r[1], "kern": _short(r[2], 120)}
               for r in conn.execute("SELECT id, name, COALESCE(culture, origin) FROM peoples ORDER BY id")]
    big = [{"id": r[0], "name": r[1], "art": r[2], "in": r[3]} for r in conn.execute(
        "SELECT id, name, kind, parent_id FROM locations WHERE level IN ('makro', 'meso') OR level IS NULL ORDER BY id")]
    mysteries = [{"id": r[0], "raetsel": _short(r[1], 200), "status": r[2], "wahrheit": _short(r[3], 200)}
                 for r in conn.execute("SELECT id, description, status, truth FROM mysteries WHERE status != 'aufgeloest'")]
    important = [{"id": r[0], "titel": r[1], "weltzeit": r[2]} for r in conn.execute(
        "SELECT id, title, world_time FROM events WHERE important = 1 ORDER BY world_time DESC LIMIT 20")]
    snippets = [{"id": r[0], "titel": r[1], "art": r[2]} for r in conn.execute(
        "SELECT id, title, kind FROM snippets WHERE status = 'offen' ORDER BY id")]
    figures = [{"id": r[0], "name": r[1], "rolle": _short(r[2], 60), "volk_id": r[3]} for r in conn.execute(
        "SELECT id, name, role, people_id FROM characters ORDER BY id")]
    techs = [[r[0], r[1]] for r in conn.execute("SELECT id, name FROM technologies ORDER BY id")]
    orgs = [[r[0], r[1]] for r in conn.execute("SELECT id, name FROM organizations ORDER BY id")]
    return {"straenge": threads, "voelker": peoples, "grosse_orte": big, "figuren_kurz": figures,
            "technik_kurz": techs, "organisationen_kurz": orgs,
            "offene_raetsel": mysteries, "wichtige_termine": important, "offene_einschuebe": snippets,
            "weltregeln": [r[0] for r in conn.execute("SELECT rule FROM world_rules ORDER BY id")]}


def _ids(value) -> set:
    out = set()
    for v in value or []:
        if isinstance(v, dict):
            v = v.get("id")
        if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
            out.add(int(v))
    return out


def focus(conn: sqlite3.Connection, ids: dict, until: float | None = None) -> dict:
    """Ebene 2/3: vollständige Datensätze der Beteiligten samt Umfeld (Volk, Ort mit Pfad, Beziehungen, Jobs, Wissen)."""
    want = {t: _ids(ids.get(t)) for t in FOCUS_TABLES}
    chars = _rows(conn, "characters", f"WHERE id IN ({','.join('?' * len(want['characters']))})",
                  tuple(want["characters"])) if want["characters"] else []
    for c in chars:
        if c.get("people_id"):
            want["peoples"].add(c["people_id"])
        if c.get("location_id"):
            want["locations"].add(c["location_id"])
    threads = _rows(conn, "threads", f"WHERE id IN ({','.join('?' * len(want['threads']))})",
                    tuple(want["threads"])) if want["threads"] else []
    for t in threads:
        if t.get("location_id"):
            want["locations"].add(t["location_id"])
        if t.get("pov_id") and t["pov_id"] not in want["characters"]:
            want["characters"].add(t["pov_id"])
            chars += _rows(conn, "characters", "WHERE id = ?", (t["pov_id"],))
    cids = tuple(c["id"] for c in chars)
    marks = ",".join("?" * len(cids))
    relations = _rows(conn, "character_relations", f"WHERE character_id IN ({marks}) OR other_id IN ({marks})",
                      cids + cids) if cids else []
    jobs = _rows(conn, "jobs", f"WHERE character_id IN ({marks})", cids) if cids else []
    for j in jobs:
        if j.get("organization_id"):
            want["organizations"].add(j["organization_id"])
    knowledge = []
    if cids:
        knowledge = _rows(conn, "knowledge", f"WHERE character_id IN ({marks})"
                          + (" AND since_world_time <= ?" if until is not None else ""),
                          cids + ((float(until),) if until is not None else ()))
    # Ortspfad nach oben (Mond → Planet → System …), damit Lage und Maßstab stimmen
    places = set(want["locations"])
    for lid in list(places):
        seen = set()
        cursor = lid
        while cursor and cursor not in seen:
            seen.add(cursor)
            places.add(cursor)
            row = conn.execute("SELECT parent_id FROM locations WHERE id = ?", (cursor,)).fetchone()
            cursor = row[0] if row else None
    out = {"figuren": chars, "beziehungen": relations, "jobs": jobs, "wissen": knowledge, "straenge": threads}
    for table, key, extra in (("locations", "orte", places), ("peoples", "voelker", want["peoples"]),
                              ("technologies", "technik", want["technologies"]),
                              ("organizations", "organisationen", want["organizations"]),
                              ("events", "ereignisse", want["events"]), ("snippets", "einschuebe", want["snippets"])):
        if extra:
            out[key] = _rows(conn, table, f"WHERE id IN ({','.join('?' * len(extra))})", tuple(extra))
    if out.get("voelker"):
        pids = tuple(p["id"] for p in out["voelker"])
        out["sprachen"] = _rows(conn, "languages", f"WHERE people_id IN ({','.join('?' * len(pids))})", pids)
        cals = tuple({p["calendar_id"] for p in out["voelker"] if p.get("calendar_id")})
        if cals:
            out["kalender"] = _rows(conn, "calendars", f"WHERE id IN ({','.join('?' * len(cals))})", cals)
    if threads:
        tids = tuple(t["id"] for t in threads)
        out["ripples"] = [dict(r) for r in conn.execute(
            f"SELECT id, effect, earliest_world_time, done FROM ripples WHERE target_thread_id IN "
            f"({','.join('?' * len(tids))})", tids)]
    for table in ALWAYS:
        out[table] = _rows(conn, table)
    out["raetsel"] = _rows(conn, "mysteries", "WHERE status != 'aufgeloest'")
    out["codes"] = _rows(conn, "codes")
    if until is not None:
        out["ereignisse_bis_jetzt"] = [{"id": r[0], "titel": r[1], "weltzeit": r[2]} for r in conn.execute(
            "SELECT id, title, world_time FROM events WHERE world_time <= ? ORDER BY world_time DESC LIMIT 25",
            (float(until),))]
    return {k: v for k, v in out.items() if v}


def mentioned(conn: sqlite3.Connection, text: str) -> dict:
    """Kennungen aller Datensätze, deren Name im Text vorkommt (für Prüfer und Archivar)."""
    low = (text or "").lower()
    out: dict = {}
    for table in ("characters", "locations", "peoples", "technologies", "organizations", "threads", "events"):
        title = service.ENTITIES[table]["title"]
        for rid, name in conn.execute(f"SELECT id, {title} FROM {table}"):
            name = str(name or "").strip().lower()
            if len(name) >= 3 and name in low:
                out.setdefault(table, []).append(rid)
            elif table == "characters" and name:
                first = name.split()[0]  # Figuren werden oft nur mit Vornamen genannt
                if len(first) >= 4 and (f" {first}" in f" {low}" or f"[{first}" in low):
                    out.setdefault(table, []).append(rid)
    return out


def merge_ids(*parts: dict) -> dict:
    out: dict = {}
    for p in parts:
        for k, v in (p or {}).items():
            out.setdefault(k, set()).update(_ids(v))
    return {k: sorted(v) for k, v in out.items()}


def text_overview(conn: sqlite3.Connection) -> str:
    return _dump(overview(conn))


def text_focus(conn: sqlite3.Connection, ids: dict, until: float | None = None) -> str:
    return _dump(focus(conn, ids, until))


def text_index(conn: sqlite3.Connection) -> str:
    return _dump(name_index(conn))
