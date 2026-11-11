# Datenmodell (SQLite)

SQLite ersetzt PostgreSQL auf Wunsch des Nutzers. Basisschema in `story_world/schema.sql` (Version 1), Erweiterungen in `story_world/migrations.py` (Version 2, über `PRAGMA user_version`).

- `peoples`: id, name, herkunft, koerper_regeln, kultur, kalender_id, status
- `calendars`: id, volk_id, name, umrechnung_zu_master, jahres_zyklus_namen
- `characters`: id, name, volk_id, status (lebt\/tot\/unbekannt), ort, stimme_id
- `locations`: id, name, ebene, entfernung_zu_anderen
- `threads`: id, ebene (makro\/meso\/mikro), ort_id, pov_id, cursor_weltzeit
- `episodes`: id, release_nr, thread_id, welt_start, welt_ende, typ, text, ende_uebergabe
- `events`: id, weltzeit, ort_id, beteiligte, ergebnis, skala, ursache_event_id
- `knowledge`: id, figur_id, inhalt, seit_weltzeit, quelle, status (wahr|geglaubt|geruecht|irrtum)
- `mysteries`: id, beschreibung, wahrheit (verborgen), status (offen|angedeutet|bestaetigt|aufgeloest), saat_folge, max_folgen
- `codes`: id, volk_id, art, bedeutung, erscheinungen (Liste), aufgeloest
- `ripples`: id, quell_event_id, zielstrang_id, fruehestens_weltzeit, wirkung, erledigt
- `world_rules`: id, regel, kategorie

## Ergänzungen Version 2
- Alle Kanontabellen: `created_by` (nutzer|ki|system), `visibility` (offen|backstage)
- `peoples`: + signs, goals, relations, development (vollständiger Steckbrief laut WELT_REGELN.md)
- `characters`: + role, description · `locations`: + kind, parent_id, description · `threads`: + title, premise, status · `events`: + title, description, important
- `languages`: id, name, people_id, description, sound, script
- `impulses`: Eingaben des Nutzers (Grundideen, Informationsstränge, Wünsche) mit Status
- `proposals`: KI-Vorschläge als JSON-Operationen (anlegen | ergaenzen), Status offen|uebernommen|verworfen
- `audit_log`: Änderungsprotokoll (wer, was, backstage-markiert)
- `world_meta`: Name und Beschreibung der Welt

## Ergänzungen Version 3
- `technologies`: id, name, kind, description, rules (Regeln & Grenzen), cost (Preis/Risiko), people_id, location_id, first_world_time
- `episodes`: type zusätzlich `vorausblick`; + title, perspective_of_episode_id (dieselbe Geschichte aus anderem Blickwinkel)
- `world_meta` `setting.auto_uebernehmen`: KI-Vorschläge automatisch übernehmen (Standard: ja)

## Ergänzungen Version 6
- Maßstab Atom … Galaxie (`service.MASSSTAB`, Beschreibung in ZEIT_UND_STRAENGE.md)
- `locations.kind`: räumliche Maßstab-Stufen ab Wohnung + mond, dorf, station, schiff, sonstiges; `level` folgt aus `kind`;
  `parent_id` muss auf einen größeren Ort zeigen (keine Kreise)
- `threads`, `events`: + massstab (Ebene bzw. Skala folgt daraus)
- Migration: Regionen direkt in einem System → `systembereich` (makro), protokolliert im audit_log

## Ergänzungen Version 7
- `organizations` (Firmen & Organisationen): name, kind, location_id (Sitz), people_id, description
- `jobs` (Jobs & Laufbahn): character_id, title, organization_id, location_id, from_world_time, to_world_time, description
- `character_relations` (Familie & Beziehungen): „character_id ist kind von other_id“, since_world_time, description
- `characters`: + location_id (Lebt in) · `peoples`: + home_location_id (Heimat)
- Ansichten: Ort-Dossier (alles im Ort und seinen Unterorten), Figur-Dossier (Laufbahn, Familie, Firmen, Stränge, Erwähnungen, Wissen)

## Ergänzungen Version 8
- `episodes`: + summary, status (fertig|entwurf), word_count, plan (backstage), check_report (backstage), run_id, created_at
- Text im Format `[Sprecher] Text` je Absatz; Segmente werden beim Lesen daraus erzeugt

## Ergänzungen Version 9
- `calendars`: + epoch, year_length, cycles_per_year, year_names (Umrechnung Master-Weltzeit → Jahres-/Zyklusnamen)
- `technologies`: + speed (Entfernungseinheiten je Weltzeit-Einheit), prep_time
- `distances` (pflegbar, ersetzt die alte, weiter vorhandene `location_distances`): from/to, distance, note
- `pronunciations` (Aussprache-Lexikon): term, spoken, note
- `episodes`: + metrics (Kanon-Score, Erzähler-Hinweise, Code-Wiederholungen), audio_path; Status zusätzlich `freigabe`
- `news_sources`, `news_items` (RSS/Atom, Dubletten über guid)

## Ergänzungen Version 10
- `genres`: name, description, rules, tension, taboos, tone, age_rating (Vorlagen: Science-Fiction, Krimi, Horror,
  Grusel für Kinder, Abenteuer, Drama, Komödie, Märchen); `threads.genre_id`, `episodes.genre_id`
- Einstellung `standard_genre`; `world_meta.nutzer_id` = Mensch, der die Welt zuletzt genutzt hat
- Erzählprofile liegen außerhalb der Welten in `story_world.profiles.json` (Interviewantworten, Nachfragen, Profilfelder)

## Ergänzungen Version 11
- `episodes.age_rating`: vom Autor beim Erstellen festgelegte Altersfreigabe
- `episodes.metrics.warnungen` / `warn_arten`: Tabu- und Altersfreigabe-Warnungen des Prüfers (blockieren nichts;
  Details nur mit reveal, sonst nur `warn_anzahl`)

## Texte als Basis (außerhalb der Welten)
- Profil-Eintrag `texte` / `texte_archiv`: id, titel, quelle, zeichen, woerter, erstellt, stil (Stilprobe ja/nein),
  eingelesen [{welt, am, teile}]; der Text selbst liegt in `profile_texte/<profil-id>/<text-id>.txt` (0600)
- Beim Einlesen entsteht je Abschnitt ein Impuls der Art `text` in der Welt

## Hinweise
- Weltzeit immer als Zahl. Darstellung in Volkskalender-Namen nur bei Ausgabe.
- Backstage-Tabellen (mysteries.wahrheit) nicht an den Nutzer ausgeben, außer auf Wunsch.
- Vektor-DB speichert Folgen-Zusammenfassungen und Fakten für Retrieval.
