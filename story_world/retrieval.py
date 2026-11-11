"""Suche nach älteren, passenden Folgen und Fakten für die Pipeline (Retrieval).

Lexikalisch mit SQLite FTS5 (in-memory, bei jedem Aufruf frisch aufgebaut – die Datenmengen sind klein), ohne FTS5
mit einfacher Wortzählung. Zeitlich gefiltert (nur was bis zur Weltzeit galt) und spoilergefiltert (Backstage nur auf Wunsch).
"""

from __future__ import annotations

import re
import sqlite3

from . import service

STOP = set("der die das und oder aber ein eine einer eines dem den des im in am an auf aus bei mit nach von vor zu zum zur "
           "ist sind war waren wird werden hat haben nicht auch noch nur sich sie er es wir ihr man als wie so dass".split())


def _terms(text: str) -> list:
    return [w for w in re.findall(r"\w{3,}", (text or "").lower()) if w not in STOP][:40]


def _documents(conn: sqlite3.Connection, until: float | None, reveal: bool) -> list:
    docs = []
    for row in conn.execute("SELECT release_nr, title, summary, world_start FROM episodes WHERE status = 'fertig' "
                            "AND summary IS NOT NULL"):
        if until is None or (row[3] or 0) <= until:
            docs.append(("folge", f"Folge {row[0]}: {row[1]}", row[2] or ""))
    for table in ("events", "knowledge"):
        for row in service.list_rows(conn, table, reveal)["rows"]:
            when = row.get("world_time") if table == "events" else row.get("since_world_time")
            if until is not None and when is not None and when > until:
                continue
            text = " ".join(str(row.get(k) or "") for k in ("title", "description", "outcome", "content", "source"))
            docs.append((table, row["__title"], text))
    return docs


def search(conn: sqlite3.Connection, query: str, until: float | None = None, reveal: bool = False, limit: int = 8) -> list:
    terms = _terms(query)
    docs = _documents(conn, until, reveal)
    if not terms or not docs:
        return []
    try:
        mem = sqlite3.connect(":memory:")
        mem.execute("CREATE VIRTUAL TABLE d USING fts5(kind, title, body)")
        mem.executemany("INSERT INTO d VALUES (?, ?, ?)", docs)
        match = " OR ".join(f'"{t}"' for t in terms)
        rows = mem.execute("SELECT kind, title, snippet(d, 2, '', '', ' … ', 24) FROM d WHERE d MATCH ? "
                           "ORDER BY bm25(d) LIMIT ?", (match, limit)).fetchall()
        mem.close()
        return [{"art": r[0], "titel": r[1], "auszug": r[2]} for r in rows]
    except sqlite3.OperationalError:  # SQLite ohne FTS5
        scored = []
        for kind, title, body in docs:
            haystack = f"{title} {body}".lower()
            score = sum(haystack.count(t) for t in terms)
            if score:
                scored.append((score, kind, title, body[:200]))
        scored.sort(key=lambda x: -x[0])
        return [{"art": k, "titel": t, "auszug": b} for _, k, t, b in scored[:limit]]
