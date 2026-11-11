"""SQLite-Zugriff und zeitbezogene, explizit begrenzte Kanonabfragen."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema)


def character_at(connection: sqlite3.Connection, character_id: int, world_time: float) -> dict:
    """Return only recorded status, presence and knowledge valid at world_time.

    Absence of a recorded status or location means unknown, not dead or absent.
    This is not a complete world snapshot or an authorization boundary.
    """
    character = connection.execute(
        "SELECT id, name, people_id FROM characters WHERE id = ?", (character_id,)
    ).fetchone()
    if character is None:
        raise ValueError(f"Unbekannte Figur: {character_id}")
    status = connection.execute(
        "SELECT status FROM character_status_history WHERE character_id = ? AND world_time <= ? "
        "ORDER BY world_time DESC LIMIT 1", (character_id, world_time)
    ).fetchone()
    locations = connection.execute(
        "SELECT l.id, l.name FROM character_presence p JOIN locations l ON l.id = p.location_id "
        "WHERE p.character_id = ? AND p.world_start <= ? AND (p.world_end IS NULL OR p.world_end > ?) "
        "ORDER BY l.id", (character_id, world_time, world_time)
    ).fetchall()
    knowledge = connection.execute(
        "SELECT content, since_world_time, source, status FROM knowledge "
        "WHERE character_id = ? AND since_world_time <= ? ORDER BY since_world_time, id",
        (character_id, world_time),
    ).fetchall()
    return {
        "character": dict(character),
        "status": status["status"] if status else "unbekannt",
        "locations": [dict(row) for row in locations],
        "knowledge": [dict(row) for row in knowledge],
    }


def presence_conflicts(connection: sqlite3.Connection) -> list[dict]:
    """Find overlapping presence at different locations; interval ends are exclusive."""
    rows = connection.execute(
        "SELECT a.character_id, a.id AS first_presence_id, b.id AS second_presence_id "
        "FROM character_presence a JOIN character_presence b "
        "ON a.character_id = b.character_id AND a.id < b.id AND a.location_id <> b.location_id "
        "AND (a.world_end IS NULL OR b.world_start < a.world_end) "
        "AND (b.world_end IS NULL OR a.world_start < b.world_end) "
        "ORDER BY a.character_id, a.id, b.id"
    ).fetchall()
    return [dict(row) for row in rows]


def eligible_ripples(connection: sqlite3.Connection, thread_id: int, world_time: float) -> list[dict]:
    rows = connection.execute(
        "SELECT id, source_event_id, earliest_world_time, effect FROM ripples "
        "WHERE target_thread_id = ? AND done = 0 AND earliest_world_time <= ? "
        "ORDER BY earliest_world_time, id", (thread_id, world_time)
    ).fetchall()
    return [dict(row) for row in rows]
