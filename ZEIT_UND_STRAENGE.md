# Zeit, Stränge und Ebenen

## Zwei Zeitachsen
- `release_nr`: Reihenfolge der Veröffentlichung.
- `welt_start` / `welt_ende`: Zeitraum in der Story-Welt (Master-Kalender, Zahl).
- `typ`: Gegenwart, Rückblende oder Parallel.
- Rückblenden dürfen mehrere Folgen dauern, ohne die Weltzeit zu verwirren.

## Ebenen
- **Makro**: Krieg der Welten, Flotten, Stationen.
- **Meso**: Mond, Station, Stadt.
- **Mikro**: Dorf, Familie, Einzelperson.
- Mikro-Geschichten laufen mehrere Folgen unabhängig, sind aber Teil der Welt.

## Maßstab (Vorgabe des Nutzers, 2026-11-07)
Vom Kleinsten zum Größten – jede Stufe gehört fest zu einer Ebene:

| Ebene | Stufen |
|---|---|
| Mikro | Atom · Wellen & Strahlen · Viren · Bakterien · Tiere · Menschen (Einzelperson) · Liebende · Familie · Gemeinschaft · Wohnung · Etage · Haus · Straße · Umgebung/Bezirk |
| Meso | Stadtteil · Stadt · Gemeinde · Region · Land · Kontinent · Planet |
| Makro | System-Bereich (z. B. innerer Kreis, Gürtel) · System · Spiralarm-Segment · Spiralarm · Galaxie |

- **Orte** nutzen die räumlichen Stufen ab Wohnung aufwärts. Ein Ort liegt immer in einem **größeren** Ort;
  Stufen dürfen übersprungen werden (ein Planet darf direkt im System liegen).
- Sonderarten: **Mond** liegt in einem Planeten (oder größer), **Dorf** auf Stadt-Höhe in einer Gemeinde.
  **Station, Schiff, Sonstiges** sind frei und können überall liegen.
- **Stränge und Ereignisse** können auf jeder Stufe spielen, auch unterhalb des Raums
  (z. B. ein Virus, ein Liebespaar, eine Familie). Die Ebene folgt aus dem Maßstab.

## Stränge
- Jeder Strang hat `strang_id`, Ebene, Ort, POV-Figur und einen **Zeit-Cursor**.
- Parallele Stränge und lineare Entwicklung sind gleichzeitig möglich.
- Reisezeiten (Warp) werden bei jeder Ortsänderung berechnet.

## Ripple-System (Wechselwirkung)
- Ereignis mit Wirkung in einem anderen Strang erzeugt einen Ripple:
  Zielstrang, frühestes Weltdatum, Wirkung.
- Planer prüft offene Ripples bei jeder Folge.
- Makro wirkt auf Mikro (Flüchtlinge, Engpässe, Funkstille) und umgekehrt (Dorfbewohner findet Artefakt mit großer Wirkung).

## Rückblenden-Regeln
- Vergangenheit ist **kanon-gesperrt**: ergänzen ja, widersprechen nein.
- **Time-Travel-Abfrage**: Weltzustand zum Zeitpunkt X abrufen. Das Modell bekommt nur Fakten, die damals galten.

## Automatische Checks
- Figur an zwei Orten gleichzeitig?
- Reisezeit eingehalten?
- Wissens-Leaks: weiß jemand etwas ohne Quelle?
- Tote Figuren in der Gegenwart?

## Konsistenz-Checks (automatisch)
- Zeitüberschneidungen: Ist eine Figur an zwei Orten gleichzeitig?
- Reisezeiten und Entfernungen
- Wissens-Leaks (jemand weiß etwas, das er noch nicht wissen kann)
- Tote Figuren tauchen nicht in der Gegenwart auf.
