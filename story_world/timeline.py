"""Zeit, Reisen und Konsistenz.

- Kalender-Schnittstelle: Master-Weltzeit → Jahres- und Zyklusnamen eines Volkskalenders (nie Tageszahlen).
- Zeitreise-Abfrage: Weltzustand zu einem Zeitpunkt – nur Fakten, die damals galten.
- Reisen: kürzeste bekannte Entfernung zwischen zwei Orten und Reisezeit je Antrieb/Phänomen.
- Konsistenzprüfung: Figur an zwei Orten, Reisezeit unterschritten, tote Figuren in der Gegenwart.
"""

from __future__ import annotations

import heapq
import json
import math
import re
import sqlite3

from . import service

ORDINALS = ("erster", "zweiter", "dritter", "vierter", "fünfter", "sechster", "siebter", "achter", "neunter",
            "zehnter", "elfter", "zwölfter")


# ---------------------------------------------------------------- Kalender

def _names(text) -> list:
    return [n.strip() for n in re.split(r"[\n;]+", text or "") if n.strip()]


def convert(calendar: dict, world_time: float) -> dict | None:
    """Rechnet eine Master-Weltzeit in einen Volkskalender um. None, wenn Epoche/Jahreslänge fehlen."""
    epoch, length = calendar.get("epoch"), calendar.get("year_length")
    if epoch is None or not length or length <= 0:
        return None
    years = (float(world_time) - float(epoch)) / float(length)
    year_index = math.floor(years)
    cycle_names = _names(calendar.get("cycle_names"))
    year_names = _names(calendar.get("year_names"))
    cycles = int(calendar.get("cycles_per_year") or len(cycle_names) or 1)
    cycle_index = min(cycles - 1, math.floor((years - year_index) * cycles))
    year_label = year_names[year_index % len(year_names)] if year_names else f"im {year_index}. Jahr"
    if cycle_names:
        cycle_label = cycle_names[cycle_index % len(cycle_names)]
    else:
        cycle_label = (ORDINALS[cycle_index] if cycle_index < len(ORDINALS) else f"{cycle_index + 1}.") + " Zyklus"
    return {"kalender": calendar.get("name"), "jahr": year_index, "zyklus": cycle_index + 1,
            "text": f"{year_label}, {cycle_label}"}


def format_all(conn: sqlite3.Connection, world_time: float, reveal: bool = False) -> list:
    rows = service.list_rows(conn, "calendars", reveal)["rows"]
    out = []
    for cal in rows:
        result = convert(cal, world_time)
        out.append({"id": cal["id"], "kalender": cal["name"],
                    "text": result["text"] if result else None,
                    "fehlt": None if result else "Epoche und Jahreslänge fehlen"})
    return out


# ---------------------------------------------------------------- Weltzustand zu einem Zeitpunkt

def world_state(conn: sqlite3.Connection, world_time: float, reveal: bool = False) -> dict:
    """Nur was zum Zeitpunkt galt: Vergangenheit ist kanon-gesperrt, Zukunft bleibt verborgen."""
    t = float(world_time)
    chars = service.list_rows(conn, "characters", reveal)["rows"]
    visible = {c["id"] for c in chars}
    locations = {r["id"]: r["name"] for r in service.list_rows(conn, "locations", reveal)["rows"]}
    figures = []
    for c in chars:
        status = conn.execute("SELECT status FROM character_status_history WHERE character_id = ? AND world_time <= ? "
                              "ORDER BY world_time DESC LIMIT 1", (c["id"], t)).fetchone()
        presence = conn.execute(
            "SELECT location_id FROM character_presence WHERE character_id = ? AND world_start <= ? "
            "AND (world_end IS NULL OR world_end > ?) ORDER BY world_start DESC LIMIT 1", (c["id"], t, t)).fetchone()
        place = presence[0] if presence else c.get("location_id")
        jobs = [j["__title"] for j in service.list_rows(conn, "jobs", reveal)["rows"]
                if j["character_id"] == c["id"] and (j.get("from_world_time") is None or j["from_world_time"] <= t)
                and (j.get("to_world_time") is None or j["to_world_time"] > t)]
        knows = conn.execute("SELECT COUNT(*) FROM knowledge WHERE character_id = ? AND since_world_time <= ?"
                             + ("" if reveal else " AND visibility = 'offen'"), (c["id"], t)).fetchone()[0]
        figures.append({"id": c["id"], "name": c["name"], "status": status[0] if status else "unbekannt",
                        "ort": locations.get(place, "unbekannt") if place else "unbekannt", "jobs": jobs, "wissen": knows})
    events = [e for e in service.list_rows(conn, "events", reveal)["rows"] if e.get("world_time") is not None
              and e["world_time"] <= t]
    relations = [r["__title"] for r in service.list_rows(conn, "character_relations", reveal)["rows"]
                 if (r.get("since_world_time") is None or r["since_world_time"] <= t)
                 and r["character_id"] in visible and r["other_id"] in visible]
    techs = [x["name"] for x in service.list_rows(conn, "technologies", reveal)["rows"]
             if x.get("first_world_time") is None or x["first_world_time"] <= t]
    episodes = conn.execute("SELECT release_nr, title FROM episodes WHERE status = 'fertig' AND world_start <= ? "
                            "ORDER BY world_start", (t,)).fetchall()
    return {
        "weltzeit": t,
        "kalender": format_all(conn, t, reveal),
        "figuren": figures,
        "ereignisse": [{"weltzeit": e["world_time"], "titel": e["__title"], "ort": e.get("location_id__name")}
                       for e in sorted(events, key=lambda e: e["world_time"])][-30:],
        "beziehungen": relations,
        "technik": techs,
        "folgen_bis_hier": [dict(r) for r in episodes],
    }


# ---------------------------------------------------------------- Reisen

def _graph(conn: sqlite3.Connection) -> dict:
    graph: dict = {}
    for row in conn.execute("SELECT from_location_id, to_location_id, distance FROM distances"):
        graph.setdefault(row[0], []).append((row[1], float(row[2])))
        graph.setdefault(row[1], []).append((row[0], float(row[2])))
    return graph


def _lineage(conn: sqlite3.Connection, location_id: int) -> list:
    """Ort selbst und alle größeren Orte, in denen er liegt (vom Kleinen zum Großen)."""
    parents = {r[0]: r[1] for r in conn.execute("SELECT id, parent_id FROM locations")}
    chain, seen = [], set()
    while location_id is not None and location_id not in seen:
        seen.add(location_id)
        chain.append(location_id)
        location_id = parents.get(location_id)
    return chain


def shortest(conn: sqlite3.Connection, start: int, goal: int) -> tuple:
    """Kürzeste bekannte Entfernung (Dijkstra). Ein Ort „erbt“ die Entfernungen der größeren Orte, in denen er liegt –
    aber nur bis unterhalb des gemeinsamen größeren Orts (zwei Planeten im selben System sind nicht 0 entfernt).
    Gibt (Entfernung, Pfad) oder (None, [])."""
    up_a, up_b = _lineage(conn, start), _lineage(conn, goal)
    if goal in up_a or start in up_b:
        return 0.0, [start, goal] if start != goal else [start]
    common = set(up_a) & set(up_b)
    sources = [n for n in up_a if n not in common]
    targets = {n for n in up_b if n not in common}
    graph = _graph(conn)
    queue = [(0.0, n) for n in sources]
    best, prev = {n: 0.0 for n in sources}, {}
    heapq.heapify(queue)
    while queue:
        dist, node = heapq.heappop(queue)
        if node in targets:
            path = [node]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            path.reverse()
            # Anfangs- und Endort im Pfad sichtbar machen
            if path[0] != start:
                path.insert(0, start)
            if path[-1] != goal:
                path.append(goal)
            return dist, path
        if dist > best.get(node, math.inf):
            continue
        for nxt, d in graph.get(node, []):
            nd = dist + d
            if nd < best.get(nxt, math.inf):
                best[nxt], prev[nxt] = nd, node
                heapq.heappush(queue, (nd, nxt))
    return None, []


def _movers(conn: sqlite3.Connection, reveal: bool = True) -> list:
    return [t for t in service.list_rows(conn, "technologies", reveal)["rows"] if t.get("speed")]


def travel(conn: sqlite3.Connection, start: int, goal: int, reveal: bool = False) -> dict:
    distance, path = shortest(conn, start, goal)
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM locations")}
    result = {"von": names.get(start), "nach": names.get(goal), "entfernung": distance,
              "pfad": [names.get(p, f"#{p}") for p in path], "reisezeiten": []}
    if distance is None:
        result["hinweis"] = "Keine Verbindung bekannt – Entfernungen unter Welt → Entfernungen pflegen."
        return result
    for tech in _movers(conn, reveal):
        hours = (tech.get("prep_time") or 0) + distance / tech["speed"] if distance else 0.0
        result["reisezeiten"].append({"technik": tech["name"], "dauer": round(hours, 3)})
    result["reisezeiten"].sort(key=lambda r: r["dauer"])
    if not result["reisezeiten"]:
        result["hinweis"] = "Keine Technik mit Reisegeschwindigkeit eingetragen (Technik & Phänomene → Geschwindigkeit)."
    return result


def fastest_time(conn: sqlite3.Connection, start: int, goal: int) -> float | None:
    distance, _ = shortest(conn, start, goal)
    movers = _movers(conn)
    if distance is None or not movers:
        return None
    if distance == 0:
        return 0.0
    return min((t.get("prep_time") or 0) + distance / t["speed"] for t in movers)


# ---------------------------------------------------------------- Konsistenzprüfung

def _visible(conn, table: str, row_id, reveal: bool) -> bool:
    if reveal:
        return True
    row = conn.execute(f"SELECT visibility FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return bool(row) and row[0] == "offen"


def check(conn: sqlite3.Connection, reveal: bool = False) -> dict:
    issues, hidden = [], 0
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM characters")}
    places = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM locations")}

    def add(char_id, kind, severity, text):
        nonlocal hidden
        if not _visible(conn, "characters", char_id, reveal):
            hidden += 1
            return
        issues.append({"art": kind, "schwere": severity, "figur": names.get(char_id, f"#{char_id}"), "text": text})

    # 1. Figur an zwei Orten gleichzeitig
    from .database import presence_conflicts
    for c in presence_conflicts(conn):
        add(c["character_id"], "Ort", "hoch", "ist zur selben Zeit an zwei Orten (Aufenthalte "
            f"#{c['first_presence_id']} und #{c['second_presence_id']}).")

    # 2. Reisezeit unterschritten
    rows = conn.execute("SELECT character_id, location_id, world_start, world_end FROM character_presence "
                        "ORDER BY character_id, world_start").fetchall()
    for a, b in zip(rows, rows[1:]):
        if a[0] != b[0] or a[1] == b[1] or a[3] is None:
            continue
        gap = b[2] - a[3]
        needed = fastest_time(conn, a[1], b[1])
        if needed is not None and gap < needed - 1e-9:
            add(a[0], "Reise", "hoch", f"reist von {places.get(a[1])} nach {places.get(b[1])} in {gap:g}, "
                f"schnellstens möglich sind {needed:g} Weltzeit-Einheiten.")

    # 3. Tote Figuren in der Gegenwart
    deaths = conn.execute("SELECT character_id, MIN(world_time) FROM character_status_history WHERE status = 'tot' "
                          "GROUP BY character_id").fetchall()
    for char_id, died in deaths:
        alive_later = conn.execute("SELECT MIN(world_time) FROM character_status_history WHERE character_id = ? "
                                   "AND status = 'lebt' AND world_time > ?", (char_id, died)).fetchone()[0]
        until = alive_later if alive_later is not None else math.inf
        later = conn.execute("SELECT COUNT(*) FROM character_presence WHERE character_id = ? AND world_start > ? "
                             "AND world_start < ?", (char_id, died, until)).fetchone()[0]
        later += conn.execute("SELECT COUNT(*) FROM knowledge WHERE character_id = ? AND since_world_time > ? "
                              "AND since_world_time < ?", (char_id, died, until)).fetchone()[0]
        if later:
            add(char_id, "Status", "hoch", f"ist seit Weltzeit {died:g} tot, taucht danach aber noch {later}× auf.")
        for ep in conn.execute("SELECT release_nr, title, world_start, plan, type FROM episodes WHERE world_start > ?",
                               (died,)):
            plan = json.loads(ep[3]) if ep[3] else None
            ids = [f.get("id") for f in (plan or {}).get("figuren", []) if isinstance(f, dict)]
            if char_id in ids and ep[4] not in ("rueckblende",) and ep[2] < until:
                add(char_id, "Status", "hoch", f"spielt in Folge {ep[0]} „{ep[1]}“ mit, ist zu der Zeit aber tot.")

    # 4. Jobs außerhalb der Lebenszeit
    for char_id, died in deaths:
        n = conn.execute("SELECT COUNT(*) FROM jobs WHERE character_id = ? AND from_world_time > ?",
                         (char_id, died)).fetchone()[0]
        if n:
            add(char_id, "Status", "mittel", f"beginnt nach ihrem Tod (Weltzeit {died:g}) noch {n} Job(s).")
    return {"probleme": issues, "verborgen": hidden}
