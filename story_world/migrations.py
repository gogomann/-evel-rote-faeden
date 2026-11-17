"""Versionierte Schema-Migrationen über PRAGMA user_version.

Version 1 = Basisschema aus schema.sql.
Version 2 = Verwaltung: Herkunft/Sichtbarkeit, Steckbrief-Felder, Sprachen,
            Impulse, KI-Vorschläge, Änderungsprotokoll, Welt-Metadaten.
Version 3 = Erzählregeln: Technik & Phänomene, Folgen mit Vorausblick, Titel und Perspektive.
Version 4 = Einschübe & Sammelsurium (offener Pool kleiner Extras ohne feste Regeln).
Version 5 = KI-Läufe: dauerhaftes Protokoll jedes KI-Auftrags (Auftrag, Schritte, Fortschritt, Ergebnis).
Version 6 = Maßstab (Atom … Galaxie): Spalte massstab für Stränge und Ereignisse; Regionen direkt in einem
            System werden zu System-Bereichen (Gürtel, Kreise), damit die Ortsordnung stimmt.
Version 7 = Figuren entwickeln: Firmen & Organisationen, Jobs & Laufbahn, Familie & Beziehungen;
            Figuren erhalten „Lebt in“, Völker „Heimat (Ort)“.
Version 8 = Folgen-Pipeline: Folgen mit Zusammenfassung, Status, Wortzahl, Plan und Prüfbericht.
Version 9 = Zeit, Reisen, Hörbuch, Nachrichten: Kalender-Umrechnung (Epoche, Jahreslänge, Namen), Entfernungen als
            pflegbare Datensätze, Geschwindigkeit/Vorbereitung je Technik, Aussprache-Lexikon, Qualitätswerte und
            Audiodatei je Folge, Nachrichtenquellen und -meldungen. Die alte Tabelle location_distances bleibt erhalten.
Version 10 = Genres mit Regeln (Konventionen, Spannung, Tabus, Ton, Altersfreigabe) samt Vorlagen; Genre je Strang/Folge.
Version 11 = Altersfreigabe je Folge.
Version 12 = Qualität: jeder KI-Aufruf mit Prompt (komprimiert) und Antwort (ai_calls), Szenarien je Folge
             (scenario_sets), Überraschungsstufe je Genre und Strang.

Version 18 = Aussprache-Lexikon: Schreibvarianten, Groß-/Kleinschreibung egal, Sprache des Worts, Lautschrift (IPA).

Vor jeder Schemaänderung einer Datei mit Inhalt wird automatisch eine
Sicherung per SQLite-Online-Backup angelegt.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .database import initialize

LATEST_VERSION = 18

# Schemaänderungen bestehender Welten seit Programmstart – für den Hinweis in der Oberfläche nach einem Update.
REPORTS: list = []

# Tabellen, die Herkunft (created_by) und Sichtbarkeit (visibility) erhalten.
TRACKED_TABLES = (
    "peoples", "calendars", "characters", "locations", "threads",
    "events", "mysteries", "codes", "world_rules", "knowledge",
)

_V2_COLUMNS = {
    "peoples": [("signs", "TEXT"), ("goals", "TEXT"), ("relations", "TEXT"), ("development", "TEXT")],
    "characters": [("role", "TEXT"), ("description", "TEXT")],
    "locations": [
        ("kind", "TEXT"),
        ("parent_id", "INTEGER REFERENCES locations(id)"),
        ("description", "TEXT"),
    ],
    "threads": [("title", "TEXT"), ("premise", "TEXT"), ("status", "TEXT NOT NULL DEFAULT 'geplant'")],
    "events": [("title", "TEXT"), ("description", "TEXT"), ("important", "INTEGER NOT NULL DEFAULT 0")],
}

_V2_TABLES = """
CREATE TABLE IF NOT EXISTS languages (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    people_id INTEGER REFERENCES peoples(id),
    description TEXT,
    sound TEXT,
    script TEXT,
    created_by TEXT NOT NULL DEFAULT 'nutzer' CHECK (created_by IN ('nutzer', 'ki', 'system')),
    visibility TEXT NOT NULL DEFAULT 'offen' CHECK (visibility IN ('offen', 'backstage'))
);
CREATE TABLE IF NOT EXISTS impulses (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'sonstiges',
    status TEXT NOT NULL DEFAULT 'neu'
        CHECK (status IN ('neu', 'in_arbeit', 'vorschlag', 'eingearbeitet', 'verworfen', 'fehler')),
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY,
    impulse_id INTEGER REFERENCES impulses(id),
    task TEXT NOT NULL,
    model TEXT,
    summary TEXT,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offen'
        CHECK (status IN ('offen', 'uebernommen', 'verworfen')),
    result TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor TEXT NOT NULL CHECK (actor IN ('nutzer', 'ki', 'system')),
    action TEXT NOT NULL,
    table_name TEXT,
    row_id INTEGER,
    backstage INTEGER NOT NULL DEFAULT 0,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS world_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_impulses_status ON impulses(status);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""


_V3_TECHNOLOGIES = """
CREATE TABLE IF NOT EXISTS technologies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT,
    description TEXT,
    rules TEXT,
    cost TEXT,
    people_id INTEGER REFERENCES peoples(id),
    location_id INTEGER REFERENCES locations(id),
    first_world_time REAL,
    created_by TEXT NOT NULL DEFAULT 'nutzer' CHECK (created_by IN ('nutzer', 'ki', 'system')),
    visibility TEXT NOT NULL DEFAULT 'offen' CHECK (visibility IN ('offen', 'backstage'))
)
"""

_V3_EPISODES = """
CREATE TABLE episodes_v3 (
    id INTEGER PRIMARY KEY,
    release_nr INTEGER NOT NULL UNIQUE,
    thread_id INTEGER NOT NULL REFERENCES threads(id),
    world_start REAL NOT NULL,
    world_end REAL NOT NULL CHECK (world_end >= world_start),
    type TEXT NOT NULL CHECK (type IN ('gegenwart', 'rueckblende', 'vorausblick', 'parallel')),
    text TEXT,
    end_handoff TEXT,
    title TEXT,
    perspective_of_episode_id INTEGER REFERENCES episodes(id)
)
"""


def _columns(connection: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _tables(connection: sqlite3.Connection) -> set:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def current_version(connection: sqlite3.Connection) -> int:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version == 0 and "peoples" in _tables(connection):
        return 1  # Basisschema ohne Versionsnummer (Stand vor Migrationen)
    return version


def has_content(connection: sqlite3.Connection) -> bool:
    for table in _tables(connection):
        if table.startswith("sqlite_"):
            continue
        if connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
            return True
    return False


def backup(connection: sqlite3.Connection, db_path: Path, label: str) -> Path:
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = backup_dir / f"{db_path.stem}-{label}-{stamp}.sqlite3"
    with sqlite3.connect(target) as dest:
        connection.backup(dest)
    dest.close()
    return target


def _migrate_to_2(connection: sqlite3.Connection) -> None:
    for table in TRACKED_TABLES:
        existing = _columns(connection, table)
        if "created_by" not in existing:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN created_by TEXT NOT NULL DEFAULT 'nutzer' "
                "CHECK (created_by IN ('nutzer', 'ki', 'system'))"
            )
        if "visibility" not in existing:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN visibility TEXT NOT NULL DEFAULT 'offen' "
                "CHECK (visibility IN ('offen', 'backstage'))"
            )
    for table, columns in _V2_COLUMNS.items():
        existing = _columns(connection, table)
        for name, ddl in columns:
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    for statement in _V2_TABLES.split(";"):
        if statement.strip():
            connection.execute(statement)


_V4_SNIPPETS = """
CREATE TABLE IF NOT EXISTS snippets (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT,
    kind TEXT,
    status TEXT NOT NULL DEFAULT 'offen',
    thread_id INTEGER REFERENCES threads(id),
    location_id INTEGER REFERENCES locations(id),
    people_id INTEGER REFERENCES peoples(id),
    used_in_episode_id INTEGER REFERENCES episodes(id),
    created_by TEXT NOT NULL DEFAULT 'nutzer' CHECK (created_by IN ('nutzer', 'ki', 'system')),
    visibility TEXT NOT NULL DEFAULT 'offen' CHECK (visibility IN ('offen', 'backstage'))
)
"""


_V5_RUNS = """
CREATE TABLE IF NOT EXISTS ai_runs (
    id INTEGER PRIMARY KEY,
    art TEXT NOT NULL,
    ziel TEXT,
    aufgabe TEXT,
    status TEXT NOT NULL DEFAULT 'laeuft' CHECK (status IN ('laeuft', 'fertig', 'fehler', 'abgebrochen')),
    progress INTEGER NOT NULL DEFAULT 0,
    steps TEXT NOT NULL DEFAULT '[]',
    auftrag TEXT,
    prompt TEXT,
    response TEXT,
    model TEXT,
    proposal_id INTEGER REFERENCES proposals(id),
    impulse_id INTEGER REFERENCES impulses(id),
    error TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    duration REAL
)
"""


def _migrate_to_6(connection: sqlite3.Connection) -> None:
    for table in ("threads", "events"):
        if "massstab" not in _columns(connection, table):
            connection.execute(f"ALTER TABLE {table} ADD COLUMN massstab TEXT")
    # „Region“ ist jetzt eine geografische Stufe unterhalb von Land. Regionen, die direkt in einem System liegen
    # (Asteroidengürtel, Kuipergürtel …), sind System-Bereiche und gehören zur Ebene makro.
    rows = connection.execute(
        "SELECT id, name, level FROM locations WHERE kind = 'region' "
        "AND parent_id IN (SELECT id FROM locations WHERE kind = 'system')").fetchall()
    for row in rows:
        connection.execute("UPDATE locations SET kind = 'systembereich', level = 'makro' WHERE id = ?", (row[0],))
        connection.execute(
            "INSERT INTO audit_log (actor, action, table_name, row_id, detail) VALUES ('system', 'migration', 'locations', ?, ?)",
            (row[0], f"{row[1]}: Art region → systembereich, Ebene {row[2] or '—'} → makro (Maßstab)"))


_V7_TABLES = """
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT,
    location_id INTEGER REFERENCES locations(id),
    people_id INTEGER REFERENCES peoples(id),
    description TEXT,
    created_by TEXT NOT NULL DEFAULT 'nutzer' CHECK (created_by IN ('nutzer', 'ki', 'system')),
    visibility TEXT NOT NULL DEFAULT 'offen' CHECK (visibility IN ('offen', 'backstage'))
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    title TEXT NOT NULL,
    organization_id INTEGER REFERENCES organizations(id),
    location_id INTEGER REFERENCES locations(id),
    from_world_time REAL,
    to_world_time REAL,
    description TEXT,
    created_by TEXT NOT NULL DEFAULT 'nutzer' CHECK (created_by IN ('nutzer', 'ki', 'system')),
    visibility TEXT NOT NULL DEFAULT 'offen' CHECK (visibility IN ('offen', 'backstage')),
    CHECK (to_world_time IS NULL OR from_world_time IS NULL OR to_world_time >= from_world_time)
);
CREATE TABLE IF NOT EXISTS character_relations (
    id INTEGER PRIMARY KEY,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    kind TEXT NOT NULL,
    other_id INTEGER NOT NULL REFERENCES characters(id),
    since_world_time REAL,
    description TEXT,
    created_by TEXT NOT NULL DEFAULT 'nutzer' CHECK (created_by IN ('nutzer', 'ki', 'system')),
    visibility TEXT NOT NULL DEFAULT 'offen' CHECK (visibility IN ('offen', 'backstage')),
    CHECK (character_id <> other_id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_character ON jobs(character_id);
CREATE INDEX IF NOT EXISTS idx_relations_character ON character_relations(character_id);
CREATE INDEX IF NOT EXISTS idx_relations_other ON character_relations(other_id)
"""


def _migrate_to_7(connection: sqlite3.Connection) -> None:
    for table, column in (("characters", "location_id"), ("peoples", "home_location_id")):
        if column not in _columns(connection, table):
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER REFERENCES locations(id)")
    for statement in _V7_TABLES.split(";"):
        if statement.strip():
            connection.execute(statement)


_V8_EPISODE_COLUMNS = (
    ("summary", "TEXT"), ("status", "TEXT NOT NULL DEFAULT 'fertig'"), ("word_count", "INTEGER"),
    ("plan", "TEXT"), ("check_report", "TEXT"), ("run_id", "INTEGER"), ("created_at", "TEXT"),
)


def _migrate_to_8(connection: sqlite3.Connection) -> None:
    existing = _columns(connection, "episodes")
    for name, ddl in _V8_EPISODE_COLUMNS:
        if name not in existing:
            connection.execute(f"ALTER TABLE episodes ADD COLUMN {name} {ddl}")


_V9_COLUMNS = {
    "calendars": [("epoch", "REAL"), ("year_length", "REAL"), ("cycles_per_year", "INTEGER"), ("year_names", "TEXT")],
    "technologies": [("speed", "REAL"), ("prep_time", "REAL")],
    "episodes": [("metrics", "TEXT"), ("audio_path", "TEXT")],
}
_V9_TABLES = """
CREATE TABLE IF NOT EXISTS distances (
    id INTEGER PRIMARY KEY,
    from_location_id INTEGER NOT NULL REFERENCES locations(id),
    to_location_id INTEGER NOT NULL REFERENCES locations(id),
    distance REAL NOT NULL CHECK (distance >= 0),
    note TEXT,
    created_by TEXT NOT NULL DEFAULT 'nutzer' CHECK (created_by IN ('nutzer', 'ki', 'system')),
    visibility TEXT NOT NULL DEFAULT 'offen' CHECK (visibility IN ('offen', 'backstage')),
    CHECK (from_location_id <> to_location_id)
);
CREATE TABLE IF NOT EXISTS pronunciations (
    id INTEGER PRIMARY KEY,
    term TEXT NOT NULL,
    spoken TEXT NOT NULL,
    note TEXT,
    created_by TEXT NOT NULL DEFAULT 'nutzer' CHECK (created_by IN ('nutzer', 'ki', 'system')),
    visibility TEXT NOT NULL DEFAULT 'offen' CHECK (visibility IN ('offen', 'backstage'))
);
CREATE TABLE IF NOT EXISTS news_sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1,
    last_fetch TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY,
    source_id INTEGER REFERENCES news_sources(id),
    guid TEXT NOT NULL UNIQUE,
    title TEXT,
    link TEXT,
    published TEXT,
    summary TEXT,
    impulse_id INTEGER REFERENCES impulses(id),
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_distances_from ON distances(from_location_id);
CREATE INDEX IF NOT EXISTS idx_distances_to ON distances(to_location_id)
"""


def _migrate_to_9(connection: sqlite3.Connection) -> None:
    for table, columns in _V9_COLUMNS.items():
        existing = _columns(connection, table)
        for name, ddl in columns:
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    for statement in _V9_TABLES.split(";"):
        if statement.strip():
            connection.execute(statement)
    # Bisherige Entfernungen übernehmen (alte Tabelle bleibt unangetastet erhalten)
    connection.execute(
        "INSERT INTO distances (from_location_id, to_location_id, distance) "
        "SELECT from_location_id, to_location_id, distance FROM location_distances")


_V10_GENRES = """
CREATE TABLE IF NOT EXISTS genres (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    rules TEXT,
    tension TEXT,
    taboos TEXT,
    tone TEXT,
    age_rating TEXT,
    created_by TEXT NOT NULL DEFAULT 'nutzer' CHECK (created_by IN ('nutzer', 'ki', 'system')),
    visibility TEXT NOT NULL DEFAULT 'offen' CHECK (visibility IN ('offen', 'backstage'))
)
"""


def _migrate_to_10(connection: sqlite3.Connection) -> None:
    from .genres import PRESETS
    connection.execute(_V10_GENRES)
    for table in ("threads", "episodes"):
        if "genre_id" not in _columns(connection, table):
            connection.execute(f"ALTER TABLE {table} ADD COLUMN genre_id INTEGER REFERENCES genres(id)")
    for g in PRESETS:
        connection.execute(
            "INSERT OR IGNORE INTO genres (name, description, rules, tension, taboos, tone, age_rating, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'system')",
            (g["name"], g["description"], g["rules"], g["tension"], g["taboos"], g["tone"], g["age_rating"]))


def _migrate_to_11(connection: sqlite3.Connection) -> None:
    """Altersfreigabe je Folge – legt der Autor beim Erstellen fest."""
    if "age_rating" not in _columns(connection, "episodes"):
        connection.execute("ALTER TABLE episodes ADD COLUMN age_rating TEXT")


_V12_CALLS = """
CREATE TABLE IF NOT EXISTS ai_calls (
    id INTEGER PRIMARY KEY,
    run_id INTEGER REFERENCES ai_runs(id),
    step TEXT,
    task TEXT,
    model TEXT,
    ok INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    messages BLOB,
    response TEXT,
    prompt_chars INTEGER,
    response_chars INTEGER,
    seconds REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
_V12_SCENARIOS = """
CREATE TABLE IF NOT EXISTS scenario_sets (
    id INTEGER PRIMARY KEY,
    run_id INTEGER REFERENCES ai_runs(id),
    status TEXT NOT NULL DEFAULT 'offen' CHECK (status IN ('offen', 'gewaehlt', 'verworfen')),
    params TEXT,
    erwartung TEXT,
    szenarien TEXT,
    bewertungen TEXT,
    gewaehlt INTEGER,
    episode_id INTEGER REFERENCES episodes(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _migrate_to_12(connection: sqlite3.Connection) -> None:
    connection.execute(_V12_CALLS)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_calls_run ON ai_calls(run_id)")
    connection.execute(_V12_SCENARIOS)
    for table in ("genres", "threads"):
        if "abweichung" not in _columns(connection, table):
            connection.execute(f"ALTER TABLE {table} ADD COLUMN abweichung INTEGER")
    if "scenario_set_id" not in _columns(connection, "episodes"):
        connection.execute("ALTER TABLE episodes ADD COLUMN scenario_set_id INTEGER")


_V13_EVENTS = """
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES ai_runs(id),
    call_id INTEGER REFERENCES ai_calls(id),
    phase TEXT NOT NULL,
    art TEXT NOT NULL,
    titel TEXT NOT NULL,
    eingaben TEXT,
    regel TEXT,
    ergebnis TEXT,
    ausgang TEXT NOT NULL DEFAULT 'info' CHECK (ausgang IN ('info', 'ok', 'warnung', 'eingriff', 'mensch', 'fehler')),
    backstage INTEGER NOT NULL DEFAULT 0,
    sekunden REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _migrate_to_13(connection: sqlite3.Connection) -> None:
    """Entscheidungsprotokoll je Lauf (Nachvollzug) und Lauf-Bezug im Änderungsprotokoll."""
    connection.execute(_V13_EVENTS)
    connection.execute("CREATE INDEX IF NOT EXISTS idx_events_run ON run_events(run_id)")
    if "run_id" not in _columns(connection, "audit_log"):
        connection.execute("ALTER TABLE audit_log ADD COLUMN run_id INTEGER")


def _migrate_to_14(connection: sqlite3.Connection) -> None:
    """Stimme (virtueller Autor, story_world.stimmen.json) je Geschichte und je Folge."""
    for table in ("threads", "episodes"):
        if "stimme_id" not in _columns(connection, table):
            connection.execute(f"ALTER TABLE {table} ADD COLUMN stimme_id TEXT")


def _migrate_to_15(connection: sqlite3.Connection) -> None:
    """Herkunft von Text-Impulsen (wessen Text, welcher Text, fremd?) und verborgener Inhalt nach Import."""
    cols = _columns(connection, "impulses")
    for name, sql in (("besitzer", "TEXT"), ("quelle_text", "TEXT"), ("fremd", "INTEGER NOT NULL DEFAULT 0"),
                      ("content_verborgen", "TEXT")):
        if name not in cols:
            connection.execute(f"ALTER TABLE impulses ADD COLUMN {name} {sql}")


def _migrate_to_16(connection: sqlite3.Connection) -> None:
    """Form einer Ausgabe: Folge der Reihe oder eigenständige Geschichte (für Hörer ohne Vorwissen)."""
    if "form" not in _columns(connection, "episodes"):
        connection.execute("ALTER TABLE episodes ADD COLUMN form TEXT NOT NULL DEFAULT 'folge'")


def _migrate_to_17(connection: sqlite3.Connection) -> None:
    """Figuren: Vorname, Nachname, Geschlecht. Beziehungen: Grund, Bruch (Weltzeit) und Grund des Bruchs."""
    cols = _columns(connection, "characters")
    for name in ("first_name", "last_name", "gender"):
        if name not in cols:
            connection.execute(f"ALTER TABLE characters ADD COLUMN {name} TEXT")
    # Bestehende Namen aufteilen: erstes Wort = Vorname, Rest = Nachname (nur wo noch nichts eingetragen ist)
    for row_id, name in connection.execute(
            "SELECT id, name FROM characters WHERE first_name IS NULL AND last_name IS NULL").fetchall():
        parts = str(name or "").split(None, 1)
        if parts:
            connection.execute("UPDATE characters SET first_name = ?, last_name = ? WHERE id = ?",
                               (parts[0], parts[1] if len(parts) > 1 else None, row_id))
    cols = _columns(connection, "character_relations")
    for name, sql in (("reason", "TEXT"), ("ended_world_time", "REAL"), ("break_reason", "TEXT")):
        if name not in cols:
            connection.execute(f"ALTER TABLE character_relations ADD COLUMN {name} {sql}")


def _migrate_to_18(connection: sqlite3.Connection) -> None:
    """Aussprache-Lexikon: Schreibvarianten, Groß-/Kleinschreibung egal, Sprache des Worts, Lautschrift (IPA)."""
    cols = _columns(connection, "pronunciations")
    for name, sql in (("variants", "TEXT"), ("ignore_case", "INTEGER NOT NULL DEFAULT 0"),
                      ("language", "TEXT"), ("ipa", "TEXT")):
        if name not in cols:
            connection.execute(f"ALTER TABLE pronunciations ADD COLUMN {name} {sql}")


def _migrate_to_3(connection: sqlite3.Connection) -> None:
    connection.execute(_V3_TECHNOLOGIES)
    if "perspective_of_episode_id" not in _columns(connection, "episodes"):
        # CHECK-Bedingung lässt sich in SQLite nur durch Neuaufbau erweitern (Verfahren laut sqlite.org/lang_altertable).
        connection.execute(_V3_EPISODES)
        connection.execute(
            "INSERT INTO episodes_v3 (id, release_nr, thread_id, world_start, world_end, type, text, end_handoff) "
            "SELECT id, release_nr, thread_id, world_start, world_end, type, text, end_handoff FROM episodes"
        )
        connection.execute("DROP TABLE episodes")
        connection.execute("ALTER TABLE episodes_v3 RENAME TO episodes")
    problems = connection.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise RuntimeError(f"Fremdschlüsselprüfung nach Migration fehlgeschlagen: {problems[:5]}")


def migrate(connection: sqlite3.Connection, db_path: Path | None = None) -> dict:
    """Bringt die Datenbank auf LATEST_VERSION. Gibt Bericht zurück."""
    version = current_version(connection)
    report = {"from": version, "to": version, "backup": None}
    if version > LATEST_VERSION:
        raise RuntimeError(
            f"Datenbank hat Schema-Version {version}, diese Software kennt nur bis {LATEST_VERSION}."
        )
    if version == LATEST_VERSION:
        return report
    if db_path is not None and has_content(connection):
        report["backup"] = str(backup(connection, db_path, f"vor-v{LATEST_VERSION}"))
    if version < 1:
        initialize(connection)  # executescript committet selbst; legt nur fehlende Tabellen an
    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN")
        if version < 2:
            _migrate_to_2(connection)
        if version < 3:
            _migrate_to_3(connection)
        if version < 4:
            connection.execute(_V4_SNIPPETS)
        if version < 5:
            connection.execute(_V5_RUNS)
            connection.execute("CREATE INDEX IF NOT EXISTS idx_runs_started ON ai_runs(started_at)")
        if version < 6:
            _migrate_to_6(connection)
        if version < 7:
            _migrate_to_7(connection)
        if version < 8:
            _migrate_to_8(connection)
        if version < 9:
            _migrate_to_9(connection)
        if version < 10:
            _migrate_to_10(connection)
        if version < 11:
            _migrate_to_11(connection)
        if version < 12:
            _migrate_to_12(connection)
        if version < 13:
            _migrate_to_13(connection)
        if version < 14:
            _migrate_to_14(connection)
        if version < 15:
            _migrate_to_15(connection)
        if version < 16:
            _migrate_to_16(connection)
        if version < 17:
            _migrate_to_17(connection)
        if version < 18:
            _migrate_to_18(connection)
        connection.execute(f"PRAGMA user_version = {LATEST_VERSION}")
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")
    report["to"] = LATEST_VERSION
    if db_path is not None and version >= 1:
        REPORTS.append({"datei": Path(db_path).name, "von": version, "nach": LATEST_VERSION, "sicherung": report["backup"]})
    return report
