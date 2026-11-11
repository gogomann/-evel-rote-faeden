"""Fachliche Dienste: Entitäten, Spoilerfilter, Lücken, Impulse, KI-Vorschläge.

Spoilerregel (serverseitig, fail-closed):
- Zeilen mit visibility='backstage' werden ohne ausdrückliches reveal nicht ausgegeben.
- Geheime Felder (z. B. mysteries.truth, codes.meaning) werden ohne reveal nie ausgegeben.
- Verweise auf verborgene Zeilen erscheinen nur als "verborgen".

Kanonregel für KI-Vorschläge:
- Die KI darf anlegen und leere Felder ergänzen. Vorhandene Werte werden nie überschrieben.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

VIS = ("offen", "backstage")
ACTORS = ("nutzer", "ki", "system")

# Maßstab vom Kleinsten zum Größten (Vorgabe des Nutzers, siehe ZEIT_UND_STRAENGE.md). Die Reihenfolge ist der Rang:
# Ein Ort liegt immer in einem Ort höheren Rangs. Jede Stufe gehört fest zu einer Grob-Ebene (makro/meso/mikro).
MASSSTAB = (
    ("atom", "Atom", "mikro"),
    ("wellen_strahlen", "Wellen & Strahlen", "mikro"),
    ("viren", "Viren", "mikro"),
    ("bakterien", "Bakterien", "mikro"),
    ("tiere", "Tiere", "mikro"),
    ("menschen", "Menschen (Einzelperson)", "mikro"),
    ("liebende", "Liebende", "mikro"),
    ("familie", "Familie", "mikro"),
    ("gemeinschaft", "Gemeinschaft", "mikro"),
    ("wohnung", "Wohnung", "mikro"),
    ("etage", "Etage", "mikro"),
    ("haus", "Haus", "mikro"),
    ("strasse", "Straße", "mikro"),
    ("bezirk", "Umgebung / Bezirk", "mikro"),
    ("stadtteil", "Stadtteil", "meso"),
    ("stadt", "Stadt", "meso"),
    ("gemeinde", "Gemeinde", "meso"),
    ("region", "Region", "meso"),
    ("land", "Land", "meso"),
    ("kontinent", "Kontinent", "meso"),
    ("planet", "Planet", "meso"),
    ("systembereich", "System-Bereich (z. B. innerer Kreis, Gürtel)", "makro"),
    ("system", "System", "makro"),
    ("spiralarm_segment", "Spiralarm-Segment", "makro"),
    ("spiralarm", "Spiralarm", "makro"),
    ("galaxie", "Galaxie", "makro"),
)
MASSSTAB_RANG = {key: rank for rank, (key, _, _) in enumerate(MASSSTAB)}
MASSSTAB_EBENE = {key: level for key, _, level in MASSSTAB}
MASSSTAB_LABEL = {key: label for key, label, _ in MASSSTAB}
# Ortsarten: räumliche Stufen ab Wohnung aufwärts, dazu Sonderarten mit festem Rang
# (ein Mond liegt im Planeten, ein Dorf in einer Gemeinde) und freie Arten ohne Rang.
ORT_SONDERARTEN = {"mond": (MASSSTAB_RANG["planet"] - 0.5, "meso", "Mond"),
                   "dorf": (MASSSTAB_RANG["stadt"], "mikro", "Dorf")}
ORT_FREIE_ARTEN = ("station", "schiff", "sonstiges")
ORT_ARTEN = (tuple(reversed([k for k, _, _ in MASSSTAB[MASSSTAB_RANG["wohnung"]:]]))
             + tuple(ORT_SONDERARTEN) + ORT_FREIE_ARTEN)
# Familie & Beziehungen: „Figur ist <art> von Bezugsfigur“. Gegenrichtung für die Anzeige aus Sicht der Bezugsfigur.
RELATION_KINDS = ("elternteil", "kind", "partner", "geschwister", "grosselternteil", "enkel", "verwandt",
                  "freund", "kollege", "mentor", "schueler", "rivale", "sonstiges")
RELATION_INVERSE = {"elternteil": "kind", "kind": "elternteil", "grosselternteil": "enkel", "enkel": "grosselternteil",
                    "mentor": "schueler", "schueler": "mentor"}
FAMILY_KINDS = {"elternteil", "kind", "partner", "geschwister", "grosselternteil", "enkel", "verwandt"}
# Wo die Grob-Ebene aus dem Maßstab folgt: Tabelle -> (Quellspalte, Ebenenspalte)
EBENE_AUS = {"locations": ("kind", "level"), "threads": ("massstab", "level"), "events": ("massstab", "scale")}


def ort_rang(kind: Any) -> float | None:
    """Rang einer Ortsart; None = freie Art (Station, Schiff, Sonstiges) oder keine Art."""
    if kind in ORT_SONDERARTEN:
        return ORT_SONDERARTEN[kind][0]
    return MASSSTAB_RANG.get(kind) if kind in ORT_ARTEN else None


def ebene_fuer(stufe: Any) -> str | None:
    if stufe in ORT_SONDERARTEN:
        return ORT_SONDERARTEN[stufe][1]
    return MASSSTAB_EBENE.get(stufe)


def stufe_label(stufe: Any) -> str:
    if stufe in ORT_SONDERARTEN:
        return ORT_SONDERARTEN[stufe][2]
    return MASSSTAB_LABEL.get(stufe) or (str(stufe) if stufe else "ohne Art")

# Feld: (spalte, label, typ, pflicht, geheim)
# typ: text | textarea | number | bool | ref:<tabelle> | select:a,b,c
ENTITIES: dict[str, dict[str, Any]] = {
    "peoples": {
        "label": "Völker", "singular": "Volk", "title": "name",
        "fields": [
            ("name", "Name", "text", True, False),
            ("origin", "Herkunft", "textarea", False, False),
            ("body_rules", "Körper & Folgeregeln", "textarea", False, False),
            ("culture", "Kultur", "textarea", False, False),
            ("calendar_id", "Kalender", "ref:calendars", False, False),
            ("signs", "Zeichen / Codes", "textarea", False, False),
            ("goals", "Ziele", "textarea", False, False),
            ("relations", "Beziehungen", "textarea", False, False),
            ("development", "Entwicklungsstatus (Bevölkerung, Technik, Ressourcen)", "textarea", False, False),
            ("status", "Status", "text", False, False),
            ("home_location_id", "Heimat (Ort)", "ref:locations", False, False),
        ],
        # Steckbrief laut WELT_REGELN.md
        "gaps": ["origin", "body_rules", "culture", "calendar_id", "signs", "goals", "relations", "development"],
    },
    "calendars": {
        "label": "Kalender", "singular": "Kalender", "title": "name",
        "fields": [
            ("name", "Name", "text", True, False),
            ("conversion_description", "Umrechnung zum Master-Kalender", "textarea", False, False),
            ("epoch", "Jahr 0 beginnt bei Weltzeit", "number", False, False),
            ("year_length", "Länge eines Jahres (Weltzeit-Einheiten)", "number", False, False),
            ("cycles_per_year", "Zyklen pro Jahr", "number", False, False),
            ("year_names", "Jahresnamen (je Zeile einer, wiederholen sich reihum)", "textarea", False, False),
            ("cycle_names", "Zyklusnamen (je Zeile einer) und Feste", "textarea", False, False),
        ],
        "gaps": ["conversion_description", "epoch", "year_length", "cycle_names"],
    },
    "languages": {
        "label": "Sprachen", "singular": "Sprache", "title": "name",
        "fields": [
            ("name", "Name", "text", True, False),
            ("people_id", "Volk", "ref:peoples", False, False),
            ("description", "Beschreibung", "textarea", False, False),
            ("sound", "Klang / Aussprache", "textarea", False, False),
            ("script", "Schrift", "textarea", False, False),
        ],
        "gaps": ["people_id", "description", "sound"],
    },
    "locations": {
        "label": "Orte & Welten", "singular": "Ort", "title": "name",
        "fields": [
            ("name", "Name", "text", True, False),
            ("kind", "Art (Maßstab)", "select:" + ",".join(ORT_ARTEN), False, False),
            ("level", "Ebene (folgt aus der Art)", "select:makro,meso,mikro", False, False),
            ("parent_id", "Liegt in (größerer Ort)", "ref:locations", False, False),
            ("description", "Beschreibung", "textarea", False, False),
        ],
        "gaps": ["kind", "level", "description"],
    },
    "technologies": {
        "label": "Technik & Phänomene", "singular": "Technik/Phänomen", "title": "name",
        "fields": [
            ("name", "Name", "text", True, False),
            ("kind", "Art", "select:antrieb,portal,wurmloch,tuer,kommunikation,energie,werkzeug,phaenomen,sonstiges", False, False),
            ("description", "Beschreibung", "textarea", False, False),
            ("rules", "Regeln & Grenzen", "textarea", False, False),
            ("cost", "Preis / Risiko", "textarea", False, False),
            ("people_id", "Genutzt / gekannt von Volk", "ref:peoples", False, False),
            ("location_id", "Ort", "ref:locations", False, False),
            ("first_world_time", "Erstes Auftreten (Weltzeit)", "number", False, False),
            ("speed", "Reisegeschwindigkeit (Entfernungseinheiten je Weltzeit-Einheit)", "number", False, False),
            ("prep_time", "Vorbereitungszeit je Reise (Weltzeit-Einheiten)", "number", False, False),
        ],
        # Laut ERZAEHLREGELN.md: Regeln müssen festgehalten werden, damit nichts verloren geht.
        "gaps": ["kind", "description", "rules"],
    },
    "distances": {
        "label": "Entfernungen", "singular": "Entfernung", "title": "note",
        "title_fmt": "{from_location_id__name} ↔ {to_location_id__name}: {distance}",
        "fields": [
            ("from_location_id", "Von", "ref:locations", True, False),
            ("to_location_id", "Nach", "ref:locations", True, False),
            ("distance", "Entfernung (Einheit frei, aber einheitlich)", "number", True, False),
            ("note", "Notiz", "text", False, False),
        ],
        "gaps": [],
    },
    "pronunciations": {
        "label": "Aussprache-Lexikon", "singular": "Aussprache", "title": "term",
        "title_fmt": "{term} → {spoken}",
        "fields": [
            ("term", "Wort / Name", "text", True, False),
            ("spoken", "So wird es gesprochen", "text", True, False),
            ("note", "Notiz (z. B. Betonung)", "text", False, False),
        ],
        "gaps": [],
    },
    "characters": {
        "label": "Figuren", "singular": "Figur", "title": "name",
        "fields": [
            ("name", "Name", "text", True, False),
            ("people_id", "Volk", "ref:peoples", False, False),
            ("role", "Rolle", "text", False, False),
            ("location_id", "Lebt in (Ort)", "ref:locations", False, False),
            ("description", "Beschreibung", "textarea", False, False),
            ("voice_id", "Stimme (Hörbuch)", "text", False, False),
        ],
        "gaps": ["people_id", "role", "location_id", "description"],
    },
    "character_relations": {
        "label": "Familie & Beziehungen", "singular": "Beziehung", "title": "kind",
        "title_fmt": "{character_id__name} ist {kind} von {other_id__name}",
        "fields": [
            ("character_id", "Figur", "ref:characters", True, False),
            ("kind", "ist … von", "select:" + ",".join(RELATION_KINDS), True, False),
            ("other_id", "Bezugsfigur", "ref:characters", True, False),
            ("since_world_time", "Seit (Weltzeit)", "number", False, False),
            ("description", "Beschreibung", "textarea", False, False),
        ],
        "gaps": [],
    },
    "organizations": {
        "label": "Firmen & Organisationen", "singular": "Organisation", "title": "name",
        "fields": [
            ("name", "Name", "text", True, False),
            ("kind", "Art (z. B. Firma, Behörde, Flotte, Schule, Verein)", "text", False, False),
            ("location_id", "Sitz (Ort)", "ref:locations", False, False),
            ("people_id", "Volk", "ref:peoples", False, False),
            ("description", "Beschreibung", "textarea", False, False),
        ],
        "gaps": ["kind", "location_id", "description"],
    },
    "jobs": {
        "label": "Jobs & Laufbahn", "singular": "Job", "title": "title",
        "title_fmt": "{character_id__name}: {title}",
        "fields": [
            ("character_id", "Figur", "ref:characters", True, False),
            ("title", "Tätigkeit / Position", "text", True, False),
            ("organization_id", "Bei (Firma / Organisation)", "ref:organizations", False, False),
            ("location_id", "Ort", "ref:locations", False, False),
            ("from_world_time", "Von (Weltzeit)", "number", False, False),
            ("to_world_time", "Bis (Weltzeit, leer = aktuell)", "number", False, False),
            ("description", "Aufgaben, Fähigkeiten, Entwicklung", "textarea", False, False),
        ],
        "gaps": ["description"],
    },
    "genres": {
        "label": "Genres", "singular": "Genre", "title": "name",
        "fields": [
            ("name", "Name", "text", True, False),
            ("description", "Kern", "textarea", False, False),
            ("rules", "Regeln / Konventionen", "textarea", False, False),
            ("tension", "Spannungsbogen und Tempo", "textarea", False, False),
            ("tone", "Ton", "text", False, False),
            ("taboos", "Tabus (⚠ nicht jedes Modell hält sich daran – Verstöße erscheinen als Warnung an der Folge)",
             "textarea", False, False),
            ("age_rating", "Vorgabe Altersfreigabe (du legst sie beim Erstellen fest)", "select:alle,ab 6,ab 12,ab 16,ab 18", False, False),
            ("abweichung", "Überraschung (0 eng · 1 Nebenwege · 2 Wendung · 3 Bruch)", "select:0,1,2,3", False, False),
        ],
        "gaps": ["rules"],
    },
    "threads": {
        "label": "Stränge", "singular": "Strang", "title": "title",
        "fields": [
            ("title", "Titel", "text", True, False),
            ("level", "Ebene", "select:makro,meso,mikro", True, False),
            ("massstab", "Maßstab", "select:" + ",".join(k for k, _, _ in MASSSTAB), False, False),
            ("status", "Status", "select:geplant,aktiv,ruhend,beendet", False, False),
            ("premise", "Prämisse", "textarea", False, False),
            ("genre_id", "Genre", "ref:genres", False, False),
            ("location_id", "Ort", "ref:locations", False, False),
            ("pov_id", "POV-Figur", "ref:characters", False, False),
            ("world_time_cursor", "Zeit-Cursor (Weltzeit)", "number", True, False),
            ("abweichung", "Überraschung (0 eng · 1 Nebenwege · 2 Wendung · 3 Bruch)", "select:0,1,2,3", False, False),
        ],
        "gaps": ["premise", "location_id", "pov_id"],
    },
    "events": {
        "label": "Ereignisse & Termine", "singular": "Ereignis", "title": "title",
        "fields": [
            ("title", "Titel", "text", True, False),
            ("world_time", "Weltzeit", "number", True, False),
            ("important", "Wichtiger Termin", "bool", False, False),
            ("location_id", "Ort", "ref:locations", False, False),
            ("description", "Beschreibung", "textarea", False, False),
            ("outcome", "Ergebnis", "textarea", False, False),
            ("scale", "Skala", "select:makro,meso,mikro", False, False),
            ("massstab", "Maßstab", "select:" + ",".join(k for k, _, _ in MASSSTAB), False, False),
            ("cause_event_id", "Ursache", "ref:events", False, False),
        ],
        "gaps": ["location_id", "description"],
    },
    "snippets": {
        "label": "Einschübe & Sammelsurium", "singular": "Einschub", "title": "title",
        "fields": [
            ("title", "Titel", "text", True, False),
            ("content", "Inhalt", "textarea", False, False),
            ("kind", "Art (frei, z. B. Socializing, Alltag, Wissen, Humor)", "text", False, False),
            ("status", "Status", "select:offen,verwendet,verworfen", False, False),
            ("thread_id", "Passt zu Strang", "ref:threads", False, False),
            ("location_id", "Ort", "ref:locations", False, False),
            ("people_id", "Volk", "ref:peoples", False, False),
        ],
        "gaps": [],  # bewusst ohne feste Regeln
    },
    "knowledge": {
        "label": "Wissen", "singular": "Wissenseintrag", "title": "content",
        "fields": [
            ("character_id", "Figur", "ref:characters", True, False),
            ("content", "Inhalt", "textarea", True, False),
            ("since_world_time", "Seit Weltzeit", "number", True, False),
            ("source", "Quelle", "text", True, False),
            ("status", "Status", "select:wahr,geglaubt,geruecht,irrtum", True, False),
        ],
        "gaps": [],
    },
    "mysteries": {
        "label": "Rätsel", "singular": "Rätsel", "title": "description",
        "default_visibility_ki": "backstage",
        "fields": [
            ("description", "Rätsel", "textarea", True, False),
            ("status", "Status", "select:offen,angedeutet,bestaetigt,aufgeloest", True, False),
            ("truth", "Wahrheit (geheim)", "textarea", False, True),
            ("max_episodes", "Max. Folgen offen", "number", False, False),
        ],
        "gaps": ["truth"],
    },
    "codes": {
        "label": "Codes & Zeichen", "singular": "Code", "title": "kind",
        "default_visibility_ki": "backstage",
        "fields": [
            ("kind", "Art / Erscheinung", "text", True, False),
            ("people_id", "Volk", "ref:peoples", False, False),
            ("meaning", "Bedeutung (geheim)", "textarea", False, True),
            ("appearances", "Erscheinungen", "textarea", False, False),
            ("resolved", "Aufgelöst", "bool", False, False),
        ],
        "gaps": ["meaning"],
    },
    "world_rules": {
        "label": "Weltregeln", "singular": "Regel", "title": "rule",
        "fields": [
            ("rule", "Regel", "textarea", True, False),
            ("category", "Kategorie", "text", True, False),
        ],
        "gaps": [],
    },
}

IMPULSE_KINDS = ("welt", "volk", "strang", "figur", "ort", "technik", "ereignis", "nachricht", "regel", "wunsch", "text",
                 "sonstiges")

SETTINGS = {
    # OFFENE_PUNKTE.md Nr. 7: keine regelmäßige menschliche Freigabe; Vorschläge mit Rückfragen bleiben offen.
    "auto_uebernehmen": "1",
    # OFFENE_PUNKTE.md Nr. 6: Hörbuchfolgen ungefähr 60 Minuten ≈ 8000 Wörter (ca. 135 Wörter pro Minute)
    "folge_woerter": "8000",
    # Täglicher Lauf (Nachrichten abrufen → einarbeiten → Folge erzeugen)
    "auto_folge": "0",
    "auto_uhrzeit": "20:00",
    "nachrichten_pro_tag": "2",
    # Hörbuch: Stimme des Erzählers (macOS-Stimme, leer = erste deutsche Stimme) und Sprechtempo (Wörter pro Minute)
    "erzaehler_stimme": "",
    "sprechtempo": "150",
    # Genre, das gilt, wenn Folge und Strang keins vorgeben (id aus „Genres“, leer = keins)
    "standard_genre": "",
    # Kontext für die KI: "voll" = ganzer Kanon in jedem Aufruf, "kaskade" = Thema → Beteiligte → Szene (kontext.py)
    "kontext_modus": "voll",
    # Überraschung: Abweichung von der Vorgabe 0 eng · 1 Nebenwege · 2 Wendung · 3 Bruch (Folge > Strang > Genre > Welt)
    "abweichung": "0",
    # Anzahl Szenarien je Folge (1 = wie bisher, 2–3 = Bewerter wählt bzw. du wählst)
    "szenarien": "1",
    "min_kanon": "6",
    "ziel_ueberraschung": "",
    "szenario_wahl": "automatisch",
}
BOOL_SETTINGS = {"auto_uebernehmen", "auto_folge"}
INT_SETTINGS = {"folge_woerter": (500, 20000, "Folgenlänge"), "nachrichten_pro_tag": (0, 10, "Nachrichten pro Tag"),
                "sprechtempo": (80, 260, "Sprechtempo"), "abweichung": (0, 3, "Überraschung"),
                "szenarien": (1, 3, "Anzahl Szenarien"), "min_kanon": (0, 10, "Mindest-Kanonpassung")}
CHOICE_SETTINGS = {"kontext_modus": ("voll", "kaskade"), "szenario_wahl": ("automatisch", "ich")}


class ValidationError(ValueError):
    pass


# ---------------------------------------------------------------- Hilfen

def _entity(table: str) -> dict:
    if table not in ENTITIES:
        raise ValidationError(f"Unbekannter Bereich: {table}")
    return ENTITIES[table]


def _field_map(table: str) -> dict:
    return {f[0]: f for f in _entity(table)["fields"]}


def _secret_fields(table: str) -> set:
    return {f[0] for f in _entity(table)["fields"] if f[4]}


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _title(table: str, row: dict) -> str:
    value = row.get(_entity(table)["title"])
    text = str(value) if not _empty(value) else f"#{row.get('id')}"
    return text if len(text) <= 80 else text[:77] + "…"


def audit(conn: sqlite3.Connection, actor: str, action: str, table: str | None = None,
          row_id: int | None = None, detail: str | None = None, backstage: bool = False) -> None:
    conn.execute(
        "INSERT INTO audit_log (actor, action, table_name, row_id, backstage, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (actor, action, table, row_id, 1 if backstage else 0, detail),
    )


def _coerce(table: str, column: str, value: Any) -> Any:
    _, label, ftype, required, _ = _field_map(table)[column]
    if isinstance(value, str):
        value = value.strip()
    if _empty(value):
        if required:
            raise ValidationError(f"„{label}“ ist ein Pflichtfeld.")
        return None
    if ftype == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValidationError(f"„{label}“ muss eine Zahl sein.")
    if ftype == "bool":
        return 1 if value in (1, True, "1", "true", "on", "ja") else 0
    if ftype.startswith("ref:"):
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"„{label}“ verweist auf keinen gültigen Datensatz.")
    if ftype.startswith("select:"):
        options = ftype.split(":", 1)[1].split(",")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(int(value)) if float(value).is_integer() else str(value)  # KI liefert 1 statt "1"
        if value not in options:
            raise ValidationError(f"„{label}“ muss eins von {', '.join(options)} sein.")
    return value


def _check_ref(conn: sqlite3.Connection, table: str, column: str, value: Any) -> None:
    ftype = _field_map(table)[column][2]
    if value is None or not ftype.startswith("ref:"):
        return
    target = ftype.split(":", 1)[1]
    if not conn.execute(f"SELECT 1 FROM {target} WHERE id = ?", (value,)).fetchone():
        raise ValidationError(f"„{_field_map(table)[column][1]}“: Datensatz #{value} existiert nicht.")


# ---------------------------------------------------------------- Maßstab-Regeln

def _derive_level(table: str, data: dict, current: Any = None) -> dict:
    """Die Grob-Ebene folgt aus dem Maßstab. Beim reinen Lückenfüllen greift der Schutz vorhandener Werte
    (update_row only_empty); passt die Ebene dann nicht, meldet _check_level den Widerspruch."""
    if table not in EBENE_AUS:
        return data
    source, target = EBENE_AUS[table]
    merged = {**(dict(current) if current is not None else {}), **data}
    level = ebene_fuer(str(merged.get(source) or "").strip())
    if level:
        data = dict(data, **{target: level})
    return data


def _check_level(table: str, row: dict) -> None:
    if table not in EBENE_AUS:
        return
    source, target = EBENE_AUS[table]
    level = ebene_fuer(row.get(source))
    if level and not _empty(row.get(target)) and row[target] != level:
        raise ValidationError(f"„{stufe_label(row[source])}“ gehört zur Ebene {level}, nicht {row[target]}.")


def _check_location_hierarchy(conn: sqlite3.Connection, row_id: int | None, kind: Any, parent_id: Any) -> None:
    """Ein Ort liegt nur in einem größeren Ort und enthält nur kleinere. Freie Arten sind ausgenommen."""
    rang = ort_rang(kind)
    if parent_id is not None:
        seen, cursor = set(), parent_id
        while cursor is not None and cursor not in seen:
            if cursor == row_id:
                raise ValidationError("„Liegt in“ ergibt einen Kreis: Ein Ort kann nicht in sich selbst liegen.")
            seen.add(cursor)
            up = conn.execute("SELECT parent_id FROM locations WHERE id = ?", (cursor,)).fetchone()
            cursor = up["parent_id"] if up else None
        parent = conn.execute("SELECT name, kind FROM locations WHERE id = ?", (parent_id,)).fetchone()
        parent_rang = ort_rang(parent["kind"]) if parent else None
        if rang is not None and parent_rang is not None and parent_rang <= rang:
            raise ValidationError(
                f"Ein Ort der Art „{stufe_label(kind)}“ kann nicht in „{parent['name']}“ "
                f"({stufe_label(parent['kind'])}) liegen – der übergeordnete Ort muss größer sein.")
    if row_id is not None and rang is not None:
        for child in conn.execute("SELECT name, kind FROM locations WHERE parent_id = ?", (row_id,)):
            child_rang = ort_rang(child["kind"])
            if child_rang is not None and child_rang >= rang:
                raise ValidationError(
                    f"„{child['name']}“ ({stufe_label(child['kind'])}) liegt hier drin – "
                    f"dafür ist „{stufe_label(kind)}“ zu klein.")


# ---------------------------------------------------------------- Lesen

def _visible_ids(conn: sqlite3.Connection, table: str) -> set:
    return {r[0] for r in conn.execute(f"SELECT id FROM {table} WHERE visibility = 'offen'")}


def _ref_names(conn: sqlite3.Connection, reveal: bool) -> dict:
    names = {}
    for table in ENTITIES:
        title = ENTITIES[table]["title"]
        rows = conn.execute(f"SELECT id, {title} AS t, visibility FROM {table}").fetchall()
        names[table] = {
            r["id"]: (_title(table, {"id": r["id"], title: r["t"]})
                      if reveal or r["visibility"] == "offen" else "🔒 verborgen")
            for r in rows
        }
    return names


def _project(table: str, row: dict, reveal: bool, refs: dict) -> dict:
    out = dict(row)
    if not reveal:
        for secret in _secret_fields(table):
            if secret in out:
                out[secret] = None
                out[f"{secret}__hidden"] = not _empty(row.get(secret))
    for column, _, ftype, _, _ in _entity(table)["fields"]:
        if ftype.startswith("ref:") and out.get(column) is not None:
            out[f"{column}__name"] = refs[ftype.split(":", 1)[1]].get(out[column], f"#{out[column]}")
    missing = [c for c in _entity(table)["gaps"] if _empty(row.get(c))]
    if not reveal:
        missing = [c for c in missing if c not in _secret_fields(table)]
    out["__missing"] = missing
    out["__title"] = _title(table, row)
    fmt = _entity(table).get("title_fmt")
    if fmt:
        out["__title"] = fmt.format_map(_FmtDefault({k: v for k, v in out.items() if not _empty(v)}))
    return out


class _FmtDefault(dict):
    def __missing__(self, key: str) -> str:
        return "?"


def list_rows(conn: sqlite3.Connection, table: str, reveal: bool = False) -> dict:
    _entity(table)
    rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
    hidden = sum(1 for r in rows if r["visibility"] != "offen")
    if not reveal:
        rows = [r for r in rows if r["visibility"] == "offen"]
    refs = _ref_names(conn, reveal)
    return {"rows": [_project(table, r, reveal, refs) for r in rows], "hidden": hidden if not reveal else 0}


def get_row(conn: sqlite3.Connection, table: str, row_id: int, reveal: bool = False) -> dict:
    _entity(table)
    row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if row is None or (not reveal and row["visibility"] != "offen"):
        raise LookupError("Datensatz nicht gefunden.")
    return _project(table, dict(row), reveal, _ref_names(conn, reveal))


def stats(conn: sqlite3.Connection) -> dict:
    out = {}
    for table, cfg in ENTITIES.items():
        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        visible = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE visibility='offen'").fetchone()[0]
        out[table] = {"label": cfg["label"], "offen": visible, "backstage": total - visible}
    out["episodes"] = {"label": "Folgen", "offen": conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0], "backstage": 0}
    return out


def gaps(conn: sqlite3.Connection, reveal: bool = False) -> dict:
    items, hidden = [], 0
    for table, cfg in ENTITIES.items():
        if not cfg["gaps"]:
            continue
        labels = {f[0]: f[1] for f in cfg["fields"]}
        secrets = _secret_fields(table)
        for r in conn.execute(f"SELECT * FROM {table} ORDER BY id"):
            row = dict(r)
            missing = [c for c in cfg["gaps"] if _empty(row.get(c))]
            if not missing:
                continue
            if not reveal and (row["visibility"] != "offen" or set(missing) <= secrets):
                hidden += 1
                continue
            shown = missing if reveal else [c for c in missing if c not in secrets]
            items.append({
                "table": table, "table_label": cfg["label"], "id": row["id"],
                "title": _title(table, row), "missing": [labels[c] for c in shown],
                "created_by": row["created_by"],
            })
    return {"items": items, "hidden": hidden}


# ---------------------------------------------------------------- Schreiben (Nutzer)

def create_row(conn: sqlite3.Connection, table: str, data: dict, actor: str = "nutzer",
               visibility: str = "offen", reveal: bool = False) -> int:
    fields = _field_map(table)
    data = _derive_level(table, dict(data))
    values = {}
    for column, spec in fields.items():
        if spec[4] and not reveal and actor == "nutzer":
            continue  # geheime Felder nur im Backstage-Modus
        if column in data:
            values[column] = _coerce(table, column, data[column])
        elif spec[3]:
            raise ValidationError(f"„{spec[1]}“ ist ein Pflichtfeld.")
    for column, value in values.items():
        _check_ref(conn, table, column, value)
    _check_level(table, values)
    if table == "locations":
        _check_location_hierarchy(conn, None, values.get("kind"), values.get("parent_id"))
    if visibility not in VIS:
        raise ValidationError("Ungültige Sichtbarkeit.")
    values["created_by"] = actor
    values["visibility"] = visibility
    columns = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    try:
        cur = conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(values.values()))
    except sqlite3.IntegrityError as exc:
        raise ValidationError(_integrity_message(exc))
    audit(conn, actor, "anlegen", table, cur.lastrowid, backstage=visibility == "backstage")
    return cur.lastrowid


def update_row(conn: sqlite3.Connection, table: str, row_id: int, data: dict, actor: str = "nutzer",
               reveal: bool = False, only_empty: bool = False) -> dict:
    """Ändert nur übermittelte, erlaubte Felder. only_empty=True füllt nur Lücken."""
    fields = _field_map(table)
    current = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if current is None or (not reveal and actor == "nutzer" and current["visibility"] != "offen"):
        raise LookupError("Datensatz nicht gefunden.")
    data = _derive_level(table, dict(data), current)
    changes, skipped = {}, []
    for column, value in data.items():
        if column not in fields:
            continue
        if fields[column][4] and not reveal and actor == "nutzer":
            continue  # verdeckte Werte bleiben unangetastet
        coerced = _coerce(table, column, value)
        if only_empty and not _empty(current[column]):
            if coerced != current[column]:
                skipped.append(column)
            continue
        if coerced != current[column]:
            _check_ref(conn, table, column, coerced)
            changes[column] = coerced
    if "visibility" in data and actor == "nutzer" and reveal and data["visibility"] in VIS:
        if data["visibility"] != current["visibility"]:
            changes["visibility"] = data["visibility"]
    merged = {**dict(current), **changes}
    if set(EBENE_AUS.get(table, ())) & set(changes):
        _check_level(table, merged)
    if table == "locations" and ({"kind", "parent_id"} & set(changes)):
        _check_location_hierarchy(conn, row_id, merged.get("kind"), merged.get("parent_id"))
    if changes:
        assignments = ", ".join(f"{c} = ?" for c in changes)
        try:
            conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", (*changes.values(), row_id))
        except sqlite3.IntegrityError as exc:
            raise ValidationError(_integrity_message(exc))
        audit(conn, actor, "ergaenzen" if only_empty else "aendern", table, row_id,
              detail=", ".join(fields[c][1] if c in fields else c for c in changes),
              backstage=current["visibility"] == "backstage" or any(fields.get(c, (0, 0, 0, 0, False))[4] for c in changes))
    return {"changed": list(changes), "skipped": skipped}


def delete_row(conn: sqlite3.Connection, table: str, row_id: int, reveal: bool = False) -> None:
    _entity(table)
    current = conn.execute(f"SELECT visibility FROM {table} WHERE id = ?", (row_id,)).fetchone()
    if current is None or (not reveal and current["visibility"] != "offen"):
        raise LookupError("Datensatz nicht gefunden.")
    try:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    except sqlite3.IntegrityError:
        raise ValidationError("Löschen nicht möglich: Andere Datensätze verweisen noch hierauf.")
    audit(conn, "nutzer", "loeschen", table, row_id, backstage=current["visibility"] == "backstage")


def _integrity_message(exc: Exception) -> str:
    text = str(exc)
    if "UNIQUE" in text:
        return "Ein Datensatz mit diesem Namen existiert bereits."
    if "FOREIGN KEY" in text:
        return "Verweis auf einen nicht vorhandenen Datensatz."
    if "CHECK" in text:
        return "Ein Wert liegt außerhalb der erlaubten Auswahl."
    return "Speichern nicht möglich (Datenbankregel verletzt)."


# ---------------------------------------------------------------- Impulse

def create_impulse(conn: sqlite3.Connection, title: str, content: str, kind: str = "sonstiges") -> int:
    if _empty(title) or _empty(content):
        raise ValidationError("Titel und Inhalt sind Pflicht.")
    if kind not in IMPULSE_KINDS:
        raise ValidationError("Unbekannte Impuls-Art.")
    cur = conn.execute("INSERT INTO impulses (title, content, kind) VALUES (?, ?, ?)",
                       (title.strip(), content.strip(), kind))
    audit(conn, "nutzer", "impuls", "impulses", cur.lastrowid, detail=title.strip())
    return cur.lastrowid


def set_impulse_status(conn: sqlite3.Connection, impulse_id: int, status: str, error: str | None = None) -> None:
    conn.execute("UPDATE impulses SET status = ?, last_error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                 (status, error, impulse_id))


def list_impulses(conn: sqlite3.Connection) -> list:
    return [dict(r) for r in conn.execute("SELECT * FROM impulses ORDER BY id DESC")]


# ---------------------------------------------------------------- KI-Vorschläge

def _op_visibility(op: dict) -> str:
    table = op.get("tabelle")
    default = ENTITIES.get(table, {}).get("default_visibility_ki", "offen")
    vis = op.get("sichtbarkeit", default)
    return vis if vis in VIS else default


_ACTIONS = ("anlegen", "ergaenzen")
_VIS_KEYS = ("sichtbarkeit", "visibility")
# Schlüssel, die Modelle statt der deutschen Namen verwenden
_OP_KEYS = {"aktion": ("action", "operation", "op"),
            "tabelle": ("table", "tabel", "table_name", "entity", "bereich"),
            "felder": ("fields", "values", "werte", "daten", "data"),
            "sichtbarkeit": ("visibility",)}


def repair_payload(payload: dict) -> list:
    """Behebt typische Kleinfehler schwächerer Modelle im Vorschlag (in place). Gibt Notizen zurück.
    Tippfehler bei Aktion/Tabelle/Feldnamen werden nur bei eindeutiger Ähnlichkeit korrigiert."""
    import difflib
    notes = []
    ops = payload.get("operationen") if isinstance(payload, dict) else None
    if not isinstance(ops, list):
        return notes
    for i, op in enumerate(ops, 1):
        if not isinstance(op, dict):
            continue
        for key, aliases in _OP_KEYS.items():
            alias = next((a for a in aliases if a in op), None) if key not in op else None
            if alias:
                op[key] = op.pop(alias)
                notes.append(f"Operation {i}: Schlüssel {alias!r} → {key!r}")
        if "aktion" not in op:  # Form {"anlegen": "threads", ...}
            for act in _ACTIONS:
                if isinstance(op.get(act), str) and "tabelle" not in op:
                    op["aktion"], op["tabelle"] = act, op.pop(act)
                    notes.append(f"Operation {i}: {act!r} als Aktion erkannt")
                    break
        action = op.get("aktion")
        if isinstance(action, str) and action not in _ACTIONS:
            fix = action.strip().lower().replace("ä", "ae")
            match = fix if fix in _ACTIONS else (difflib.get_close_matches(fix, _ACTIONS, 1, 0.75) or [None])[0]
            if match:
                op["aktion"] = match
                notes.append(f"Operation {i}: Aktion {action!r} → {match!r}")
        table = op.get("tabelle")
        if isinstance(table, str) and table not in ENTITIES:
            match = (difflib.get_close_matches(table.strip().lower(), list(ENTITIES), 1, 0.85) or [None])[0]
            if match:
                op["tabelle"] = match
                notes.append(f"Operation {i}: Tabelle {table!r} → {match!r}")
        felder, table = op.get("felder"), op.get("tabelle")
        if not isinstance(felder, dict) or table not in ENTITIES:
            continue
        known = set(_field_map(table))
        for key in [k for k in felder if k not in known]:
            if key in _VIS_KEYS:  # Sichtbarkeit gehört an die Operation, nicht in die Felder
                value = felder.pop(key)
                if value in VIS and "sichtbarkeit" not in op:
                    op["sichtbarkeit"] = value
                notes.append(f"Operation {i}: Feld {key!r} an die Operation verschoben")
                continue
            match = (difflib.get_close_matches(key, sorted(known - set(felder)), 1, 0.85) or [None])[0]
            if match:
                felder[match] = felder.pop(key)
                notes.append(f"Operation {i}: Feld {key!r} → {match!r}")
    return notes


def validate_payload(payload: dict) -> list:
    """Prüft Struktur eines KI-Vorschlags. Gibt Fehlerliste zurück (leer = ok)."""
    errors = []
    if not isinstance(payload, dict):
        return ["Vorschlag ist kein JSON-Objekt."]
    repair_payload(payload)
    ops = payload.get("operationen")
    if not isinstance(ops, list) or not ops:
        return ["Vorschlag enthält keine Operationen."]
    refs = set()
    for i, op in enumerate(ops, 1):
        if not isinstance(op, dict):
            errors.append(f"Operation {i}: kein Objekt.")
            continue
        action, table, felder = op.get("aktion"), op.get("tabelle"), op.get("felder")
        if action not in ("anlegen", "ergaenzen"):
            errors.append(f"Operation {i}: unbekannte Aktion {action!r}"
                          + (" (Schlüssel 'aktion' fehlt; erwartet 'anlegen' oder 'ergaenzen')." if action is None else "."))
        if table not in ENTITIES:
            errors.append(f"Operation {i}: unbekannte Tabelle {table!r}"
                          + (" (Schlüssel 'tabelle' fehlt)." if table is None else "."))
            continue
        if not isinstance(felder, dict) or not felder:
            errors.append(f"Operation {i}: keine Felder.")
            continue
        unknown = set(felder) - set(_field_map(table))
        if unknown:
            errors.append(f"Operation {i}: unbekannte Felder {sorted(unknown)} für {table}.")
        if action == "anlegen" and op.get("ref"):
            refs.add(str(op["ref"]))
        if action == "ergaenzen" and not isinstance(op.get("id"), int):
            errors.append(f"Operation {i}: 'ergaenzen' braucht eine numerische id.")
    return errors


def _resolve(value: Any, created: dict) -> Any:
    if isinstance(value, str) and value.startswith("@"):
        key = value[1:]
        if key not in created:
            raise ValidationError(f"Verweis {value} nicht verfügbar (Ziel fehlt oder ist fehlgeschlagen).")
        return created[key]
    return value


def store_proposal(conn: sqlite3.Connection, task: str, payload: dict, model: str | None,
                   impulse_id: int | None = None) -> int:
    summary = str(payload.get("zusammenfassung") or "").strip() or "(ohne Zusammenfassung)"
    cur = conn.execute(
        "INSERT INTO proposals (impulse_id, task, model, summary, payload) VALUES (?, ?, ?, ?, ?)",
        (impulse_id, task, model, summary, json.dumps(payload, ensure_ascii=False)),
    )
    audit(conn, "ki", "vorschlag", "proposals", cur.lastrowid, detail=task)
    return cur.lastrowid


def _describe_op(op: dict, reveal: bool, refs: dict, new_refs: dict) -> dict:
    table = op.get("tabelle")
    vis = _op_visibility(op)
    hidden = vis == "backstage" and not reveal
    fields = dict(op.get("felder") or {})
    known = table in ENTITIES
    secrets = _secret_fields(table) if known else set()
    labels = _field_map(table) if known else {}
    shown = []
    for key, value in fields.items():
        if key in secrets and not reveal:
            value = "🔒"
        elif key in labels and labels[key][2].startswith("ref:"):
            target = labels[key][2].split(":", 1)[1]
            if isinstance(value, str) and value.startswith("@"):
                value = new_refs.get(value[1:], value) + " (neu)"
            elif isinstance(value, int):
                value = refs.get(target, {}).get(value, f"#{value}")
        shown.append({"label": labels[key][1] if key in labels else key, "wert": value})
    target_name = None
    if op.get("aktion") == "ergaenzen" and known and isinstance(op.get("id"), int):
        target_name = refs.get(table, {}).get(op["id"], f"#{op['id']}")
    return {
        "aktion": op.get("aktion"),
        "tabelle": table,
        "tabelle_label": ENTITIES.get(table, {}).get("singular", table),
        "id": op.get("id"),
        "ziel": target_name,
        "sichtbarkeit": vis,
        "verborgen": hidden,
        "felder": None if hidden else shown,
    }


def list_proposals(conn: sqlite3.Connection, reveal: bool = False) -> list:
    out = []
    refs = _ref_names(conn, reveal)
    for r in conn.execute("SELECT * FROM proposals ORDER BY id DESC"):
        row = dict(r)
        payload = json.loads(row.pop("payload"))
        raw_ops = [op for op in payload.get("operationen", []) if isinstance(op, dict)]
        new_refs = {}
        for op in raw_ops:
            if op.get("ref") and op.get("tabelle") in ENTITIES:
                if _op_visibility(op) == "backstage" and not reveal:
                    new_refs[str(op["ref"])] = "🔒 verborgen"
                else:
                    title_col = ENTITIES[op["tabelle"]]["title"]
                    new_refs[str(op["ref"])] = str((op.get("felder") or {}).get(title_col, op["ref"]))
        ops = [_describe_op(op, reveal, refs, new_refs) for op in raw_ops]
        row["operationen"] = [o for o in ops if not o["verborgen"]]
        row["verborgen"] = sum(1 for o in ops if o["verborgen"])
        row["rueckfragen"] = payload.get("rueckfragen") or []
        row["fehler"] = validate_payload(payload) if row["status"] == "offen" else []
        row["result"] = json.loads(row["result"]) if row.get("result") else None
        out.append(row)
    return out


def apply_proposal(conn: sqlite3.Connection, proposal_id: int) -> dict:
    """Übernimmt einen Vorschlag. Jede Operation ist für sich gekapselt: Ein Fehler betrifft nur sie
    (und Operationen, die per @ref auf sie verweisen), nicht den Rest. Vorhandene Werte werden nie überschrieben."""
    row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise LookupError("Vorschlag nicht gefunden.")
    if row["status"] != "offen":
        raise ValidationError("Vorschlag wurde bereits entschieden.")
    payload = json.loads(row["payload"])
    errors = validate_payload(payload)
    if errors:
        raise ValidationError("Vorschlag ungültig: " + " ".join(errors))
    report = _apply_operations(conn, payload["operationen"])
    if report["angelegt"] == 0 and report["ergaenzt"] == 0 and report["fehlgeschlagen"]:
        raise ValidationError("Keine Operation ließ sich übernehmen: " + " ".join(report["hinweise"]))
    conn.execute(
        "UPDATE proposals SET status='uebernommen', result=?, decided_at=CURRENT_TIMESTAMP WHERE id=?",
        (json.dumps(report, ensure_ascii=False), proposal_id),
    )
    if row["impulse_id"]:
        set_impulse_status(conn, row["impulse_id"], "eingearbeitet")
    audit(conn, "nutzer", "uebernehmen", "proposals", proposal_id)
    return report


def check_operations(conn: sqlite3.Connection, operations: list) -> dict:
    """Probelauf: führt die Operationen aus und nimmt alles wieder zurück. Liefert denselben Bericht wie
    apply_proposal plus „fehler_refs“ (ref → Grund) – so sieht der Planer vor dem Speichern, was scheitern würde."""
    errors = validate_payload({"operationen": operations})
    if errors:
        return {"angelegt": 0, "ergaenzt": 0, "uebersprungen": 0, "fehlgeschlagen": len(operations),
                "hinweise": errors, "refs": {}, "fehler_refs": {}}
    conn.execute("SAVEPOINT probelauf")
    try:
        return _apply_operations(conn, operations)
    finally:
        conn.execute("ROLLBACK TO probelauf")
        conn.execute("RELEASE probelauf")


def _apply_operations(conn: sqlite3.Connection, operations: list) -> dict:
    created: dict = {}
    report = {"angelegt": 0, "ergaenzt": 0, "uebersprungen": 0, "fehlgeschlagen": 0, "hinweise": [], "refs": created,
              "fehler_refs": {}}
    for number, op in enumerate(operations, 1):
        table = op["tabelle"]
        label = f"{ENTITIES[table]['singular']} (Operation {number})"
        conn.execute("SAVEPOINT op")
        try:
            data = {k: _resolve(v, created) for k, v in op["felder"].items()}
            if op["aktion"] == "anlegen":
                new_id = create_row(conn, table, data, actor="ki", visibility=_op_visibility(op))
                if op.get("ref"):
                    created[str(op["ref"])] = new_id
                report["angelegt"] += 1
            else:
                result = update_row(conn, table, op["id"], data, actor="ki", reveal=True, only_empty=True)
                if result["changed"]:
                    report["ergaenzt"] += 1
                if result["skipped"]:
                    report["uebersprungen"] += len(result["skipped"])
                    report["hinweise"].append(f"{label}: vorhandene Werte nicht überschrieben.")
            conn.execute("RELEASE op")
        except (ValidationError, LookupError, sqlite3.DatabaseError, ValueError, TypeError) as exc:
            conn.execute("ROLLBACK TO op")
            conn.execute("RELEASE op")
            report["fehlgeschlagen"] += 1
            hidden = _op_visibility(op) == "backstage"
            report["hinweise"].append(f"{label}: übersprungen – " + ("(verborgen)" if hidden else str(exc).strip("'\"")))
            if op.get("ref"):
                report["fehler_refs"][str(op["ref"])] = str(exc).strip("'\"")
    return report


def reject_proposal(conn: sqlite3.Connection, proposal_id: int) -> None:
    row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise LookupError("Vorschlag nicht gefunden.")
    if row["status"] != "offen":
        raise ValidationError("Vorschlag wurde bereits entschieden.")
    conn.execute("UPDATE proposals SET status='verworfen', decided_at=CURRENT_TIMESTAMP WHERE id=?", (proposal_id,))
    if row["impulse_id"]:
        open_left = conn.execute(
            "SELECT 1 FROM proposals WHERE impulse_id=? AND status='offen'", (row["impulse_id"],)
        ).fetchone()
        if not open_left:
            set_impulse_status(conn, row["impulse_id"], "neu")
    audit(conn, "nutzer", "verwerfen", "proposals", proposal_id)


# ---------------------------------------------------------------- Kanon-Export für die KI

def canon_snapshot(conn: sqlite3.Connection) -> dict:
    """Vollständiger Kanon inkl. Backstage – NUR für die KI, nie an die Oberfläche."""
    out = {}
    for table, cfg in ENTITIES.items():
        cols = ["id"] + [f[0] for f in cfg["fields"]] + ["visibility"]
        rows = []
        for r in conn.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY id"):
            rows.append({k: v for k, v in dict(r).items() if not _empty(v)})
        out[table] = rows
    return out


def search(conn: sqlite3.Connection, query: str, reveal: bool = False, limit: int = 100) -> list:
    """Volltextsuche über alle Bereiche; Geheimfelder und Backstage nur mit reveal."""
    query = (query or "").strip()
    if len(query) < 2:
        return []
    needle = f"%{query}%"
    hits = []
    for table, cfg in ENTITIES.items():
        cols = [f[0] for f in cfg["fields"]
                if (f[2] in ("text", "textarea") or f[2].startswith("select:")) and (reveal or not f[4])]
        if not cols:
            continue
        where = " OR ".join(f"{c} LIKE ?" for c in cols)
        sql = f"SELECT * FROM {table} WHERE ({where})"
        if not reveal:
            sql += " AND visibility = 'offen'"
        for r in conn.execute(sql + " ORDER BY id LIMIT ?", (*[needle] * len(cols), limit)):
            row = dict(r)
            field = next(c for c in cols if row.get(c) and query.lower() in str(row[c]).lower())
            text = str(row[field])
            pos = text.lower().find(query.lower())
            snippet = ("…" if pos > 40 else "") + text[max(0, pos - 40):pos + 80] + ("…" if pos + 80 < len(text) else "")
            hits.append({"table": table, "table_label": cfg["label"], "id": row["id"],
                         "title": _title(table, row), "snippet": snippet})
    return hits[:limit]


# ---------------------------------------------------------------- Dossiers (alles zu einem Ort / einer Figur)

def _rows(conn: sqlite3.Connection, reveal: bool, *tables: str) -> dict:
    return {t: list_rows(conn, t, reveal)["rows"] for t in tables}


def _mentions(rows: list, name: str, columns: tuple) -> list:
    needle = (name or "").strip().lower()
    if len(needle) < 3:
        return []
    return [r for r in rows if any(needle in str(r.get(c) or "").lower() for c in columns)]


def location_dossier(conn: sqlite3.Connection, location_id: int, reveal: bool = False) -> dict:
    """Ort mit Pfad, Unterorten und allem, was im Ort oder einem seiner Unterorte liegt."""
    place = get_row(conn, "locations", location_id, reveal)
    data = _rows(conn, reveal, "locations", "peoples", "characters", "organizations", "jobs", "threads",
                 "events", "snippets", "technologies")
    by_id = {r["id"]: r for r in data["locations"]}
    children: dict = {}
    for r in data["locations"]:
        children.setdefault(r.get("parent_id"), []).append(r)
    area, stack = set(), [location_id]
    while stack:
        current = stack.pop()
        if current not in area:
            area.add(current)
            stack.extend(c["id"] for c in children.get(current, []))
    path, cursor, seen = [], place.get("parent_id"), set()
    while cursor in by_id and cursor not in seen:
        seen.add(cursor)
        path.insert(0, {"id": cursor, "name": by_id[cursor]["name"], "kind": by_id[cursor].get("kind")})
        cursor = by_id[cursor].get("parent_id")

    def inside(rows: list, col: str = "location_id") -> list:
        return [r for r in rows if r.get(col) in area]

    orgs = inside(data["organizations"])
    org_ids = {o["id"] for o in orgs}
    return {
        "ort": place, "pfad": path, "art": stufe_label(place.get("kind")),
        "unterorte": sorted(children.get(location_id, []), key=lambda r: (-(ort_rang(r.get("kind")) or 0), r["name"])),
        "unterorte_gesamt": len(area) - 1,
        "voelker": inside(data["peoples"], "home_location_id"),
        "figuren": inside(data["characters"]),
        "organisationen": orgs,
        "jobs": [j for j in data["jobs"] if j.get("location_id") in area or j.get("organization_id") in org_ids],
        "straenge": inside(data["threads"]),
        "ereignisse": sorted(inside(data["events"]), key=lambda r: r.get("world_time") or 0),
        "einschuebe": inside(data["snippets"]),
        "technik": inside(data["technologies"]),
    }


def character_dossier(conn: sqlite3.Connection, character_id: int, reveal: bool = False) -> dict:
    """Figur mit Laufbahn, Familie und Beziehungen, Firmen, Geschichten und Wissen."""
    person = get_row(conn, "characters", character_id, reveal)
    data = _rows(conn, reveal, "character_relations", "jobs", "organizations", "threads", "events", "snippets",
                 "knowledge")
    # "art" = was die andere Figur für diese Figur ist („Tavi ist Elternteil von Mira“ → bei Mira: Tavi = Elternteil).
    family, relations = [], []
    for r in data["character_relations"]:
        if r["other_id"] == character_id:
            kind, other, other_name = r["kind"], r["character_id"], r.get("character_id__name")
        elif r["character_id"] == character_id:
            kind = RELATION_INVERSE.get(r["kind"], r["kind"])
            other, other_name = r["other_id"], r.get("other_id__name")
        else:
            continue
        if not reveal and other_name == "🔒 verborgen":
            continue
        entry = {"beziehung_id": r["id"], "art": kind, "figur_id": other, "name": other_name,
                 "seit": r.get("since_world_time"), "beschreibung": r.get("description")}
        (family if kind in FAMILY_KINDS else relations).append(entry)
    jobs = sorted([j for j in data["jobs"] if j["character_id"] == character_id],
                  key=lambda j: (j.get("from_world_time") is None, j.get("from_world_time") or 0))
    org_ids = {j.get("organization_id") for j in jobs}
    pov = [t for t in data["threads"] if t.get("pov_id") == character_id]
    pov_ids = {t["id"] for t in pov}
    name = person.get("name")
    return {
        "figur": person,
        "familie": family,
        "beziehungen": relations,
        "jobs": jobs,
        "organisationen": [o for o in data["organizations"] if o["id"] in org_ids],
        "straenge_pov": pov,
        "erwaehnt": {
            "straenge": [t for t in _mentions(data["threads"], name, ("title", "premise")) if t["id"] not in pov_ids],
            "ereignisse": _mentions(data["events"], name, ("title", "description", "outcome")),
            "einschuebe": _mentions(data["snippets"], name, ("title", "content")),
        },
        "wissen": [k for k in data["knowledge"] if k["character_id"] == character_id],
    }


def audit_entries(conn: sqlite3.Connection, reveal: bool = False, limit: int = 200) -> list:
    query = "SELECT * FROM audit_log"
    if not reveal:
        query += " WHERE backstage = 0"
    query += " ORDER BY id DESC LIMIT ?"
    return [dict(r) for r in conn.execute(query, (limit,))]


def meta(conn: sqlite3.Connection) -> dict:
    out = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM world_meta")
           if not r["key"].startswith("setting.")}
    out["einstellungen"] = {k: setting(conn, k) for k in SETTINGS}
    return out


def setting(conn: sqlite3.Connection, key: str) -> str:
    value = conn.execute("SELECT value FROM world_meta WHERE key = ?", (f"setting.{key}",)).fetchone()
    return value[0] if value else SETTINGS[key]


def set_setting(conn: sqlite3.Connection, key: str, value) -> None:
    if key not in SETTINGS:
        raise ValidationError("Unbekannte Einstellung.")
    if key in BOOL_SETTINGS:
        value = "1" if value in (True, "1", 1, "true", "on") else "0"
    elif key in INT_SETTINGS:
        low, high, label = INT_SETTINGS[key]
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            raise ValidationError(f"{label} muss eine Zahl sein.")
        if not low <= number <= high:
            raise ValidationError(f"{label} bitte zwischen {low} und {high}.")
        value = str(number)
    elif key in CHOICE_SETTINGS:
        if value not in CHOICE_SETTINGS[key]:
            raise ValidationError(f"Erlaubt sind: {', '.join(CHOICE_SETTINGS[key])}.")
    elif key == "ziel_ueberraschung":
        value = str(value or "").strip().replace(",", ".")
        if value:
            try:
                if not 0 <= float(value) <= 10:
                    raise ValueError
            except ValueError:
                raise ValidationError("Ziel-Überraschung bitte zwischen 0 und 10 (leer = aus der Stufe).")
    elif key == "standard_genre":
        value = str(value or "").strip()
        if value and not (value.isdigit() and conn.execute("SELECT 1 FROM genres WHERE id = ?", (int(value),)).fetchone()):
            raise ValidationError("Unbekanntes Genre.")
    elif key == "auto_uhrzeit":
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(value or "")):
            raise ValidationError("Uhrzeit bitte als HH:MM, z. B. 20:30.")
    set_meta(conn, f"setting.{key}", str(value))


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO world_meta (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
