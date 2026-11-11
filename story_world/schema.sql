PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS calendars (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    conversion_description TEXT,
    cycle_names TEXT
);
CREATE TABLE IF NOT EXISTS peoples (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    origin TEXT,
    body_rules TEXT,
    culture TEXT,
    calendar_id INTEGER REFERENCES calendars(id),
    status TEXT
);
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    people_id INTEGER REFERENCES peoples(id),
    voice_id TEXT
);
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    level TEXT CHECK (level IN ('makro', 'meso', 'mikro'))
);
CREATE TABLE IF NOT EXISTS location_distances (
    from_location_id INTEGER NOT NULL REFERENCES locations(id),
    to_location_id INTEGER NOT NULL REFERENCES locations(id),
    distance REAL NOT NULL CHECK (distance >= 0),
    PRIMARY KEY (from_location_id, to_location_id),
    CHECK (from_location_id <> to_location_id)
);
CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY,
    level TEXT NOT NULL CHECK (level IN ('makro', 'meso', 'mikro')),
    location_id INTEGER REFERENCES locations(id),
    pov_id INTEGER REFERENCES characters(id),
    world_time_cursor REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    release_nr INTEGER NOT NULL UNIQUE,
    thread_id INTEGER NOT NULL REFERENCES threads(id),
    world_start REAL NOT NULL,
    world_end REAL NOT NULL CHECK (world_end >= world_start),
    type TEXT NOT NULL CHECK (type IN ('gegenwart', 'rueckblende', 'parallel')),
    text TEXT,
    end_handoff TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    world_time REAL NOT NULL,
    location_id INTEGER REFERENCES locations(id),
    outcome TEXT,
    scale TEXT,
    cause_event_id INTEGER REFERENCES events(id)
);
CREATE TABLE IF NOT EXISTS event_participants (
    event_id INTEGER NOT NULL REFERENCES events(id),
    character_id INTEGER NOT NULL REFERENCES characters(id),
    PRIMARY KEY (event_id, character_id)
);
-- Half-open intervals permit a character to leave one place exactly when arriving at another.
CREATE TABLE IF NOT EXISTS character_presence (
    id INTEGER PRIMARY KEY,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    location_id INTEGER NOT NULL REFERENCES locations(id),
    world_start REAL NOT NULL,
    world_end REAL CHECK (world_end IS NULL OR world_end > world_start)
);
CREATE TABLE IF NOT EXISTS character_status_history (
    id INTEGER PRIMARY KEY,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    world_time REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('lebt', 'tot', 'unbekannt')),
    UNIQUE (character_id, world_time)
);
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    content TEXT NOT NULL,
    since_world_time REAL NOT NULL,
    source TEXT NOT NULL CHECK (length(trim(source)) > 0),
    status TEXT NOT NULL CHECK (status IN ('wahr', 'geglaubt', 'geruecht', 'irrtum'))
);
CREATE TABLE IF NOT EXISTS mysteries (
    id INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    truth TEXT,
    status TEXT NOT NULL CHECK (status IN ('offen', 'angedeutet', 'bestaetigt', 'aufgeloest')),
    seed_episode_id INTEGER REFERENCES episodes(id),
    max_episodes INTEGER CHECK (max_episodes IS NULL OR max_episodes > 0)
);
CREATE TABLE IF NOT EXISTS codes (
    id INTEGER PRIMARY KEY,
    people_id INTEGER REFERENCES peoples(id),
    kind TEXT NOT NULL,
    meaning TEXT,
    appearances TEXT,
    resolved INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1))
);
CREATE TABLE IF NOT EXISTS ripples (
    id INTEGER PRIMARY KEY,
    source_event_id INTEGER NOT NULL REFERENCES events(id),
    target_thread_id INTEGER NOT NULL REFERENCES threads(id),
    earliest_world_time REAL NOT NULL,
    effect TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0, 1))
);
CREATE TABLE IF NOT EXISTS world_rules (
    id INTEGER PRIMARY KEY,
    rule TEXT NOT NULL,
    category TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_presence_character_time ON character_presence(character_id, world_start, world_end);
CREATE INDEX IF NOT EXISTS idx_status_character_time ON character_status_history(character_id, world_time);
CREATE INDEX IF NOT EXISTS idx_knowledge_character_time ON knowledge(character_id, since_world_time);
CREATE INDEX IF NOT EXISTS idx_ripples_thread_time ON ripples(target_thread_id, done, earliest_world_time);
