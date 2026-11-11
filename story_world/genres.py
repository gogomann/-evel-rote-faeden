"""Genres: Vorlagen mit Regeln, die Planer, Autor, Lektor und Prüfer kennen.

Ein Genre legt sich über die Welt: Ein Krimi oder ein Grusel für Kinder spielt in derselben Sci-Fi-Welt, folgt aber
eigenen Konventionen. Vorlagen dürfen geändert und ergänzt werden (Welt → Genres).
"""

from __future__ import annotations

import sqlite3

AGE_RATINGS = ("alle", "ab 6", "ab 12", "ab 16", "ab 18")

PRESETS = [
    {"name": "Science-Fiction", "age_rating": "ab 12",
     "description": "Die Grundfarbe der Welt: Technik, fremde Völker, Aufbruch – hoffnungsvoll, an Star Trek angelehnt.",
     "rules": "Technik und Phänomene folgen ihren festgehaltenen Regeln; Staunen und Neugier tragen die Handlung; "
              "Konflikte werden eher durch Verständigung als durch Gewalt gelöst.",
     "tension": "Ruhiger Aufbau, eine Entdeckung oder Frage in der Mitte, versöhnlicher oder offener Ausklang.",
     "taboos": "Zynismus als Grundton; Technik, die ohne Regeln alles löst.",
     "tone": "Neugierig, warm, nachdenklich."},
    {"name": "Krimi", "age_rating": "ab 12",
     "description": "Ein Rätsel um eine Tat, das Schritt für Schritt aufgeklärt wird.",
     "rules": "Faire Hinweise: Alles, was zur Lösung nötig ist, kommt vorher vor. Ermittelnde Figur mit eigener Methode. "
              "Verdächtige mit nachvollziehbaren Motiven. Wissen braucht Quellen.",
     "tension": "Fall – Spuren – falsche Fährte – Wendung – Auflösung oder Cliffhanger zur nächsten Folge.",
     "taboos": "Lösung aus dem Nichts; Gewalt als Selbstzweck; Täter ohne Motiv.",
     "tone": "Aufmerksam, trocken, mit Raum für Atmosphäre."},
    {"name": "Horror", "age_rating": "ab 16",
     "description": "Unheimliches, das in die vertraute Welt einbricht.",
     "rules": "Das Unheimliche wirkt durch Andeutung stärker als durch Zeigen. Regeln des Bedrohlichen bleiben konsistent. "
              "Figuren handeln nachvollziehbar.",
     "tension": "Langsamer Aufbau, wachsendes Unbehagen, Höhepunkt, ein Rest Unsicherheit am Ende.",
     "taboos": "Splatter und ausgewalzte Grausamkeit; Gewalt gegen Kinder; Abwertung von Gruppen.",
     "tone": "Atmosphärisch, leise, beklemmend."},
    {"name": "Grusel für Kinder", "age_rating": "ab 6",
     "description": "Wohliger Grusel, der am Ende sicher auflöst – zum Einschlafen geeignet.",
     "rules": "Die Angst ist spielerisch und wird aufgelöst; das Unheimliche entpuppt sich als harmlos oder wird gemeinsam "
              "überwunden. Kinderfiguren handeln mutig und klug, Erwachsene sind verlässlich. Einfache Sprache, kurze Sätze.",
     "tension": "Neugier – leichtes Kribbeln – Mut – Auflösung – geborgenes Ende.",
     "taboos": "Tod, Verletzungen oder Gewalt im Detail; echte Bedrohung von Kindern oder Tieren; Albträume ohne Auflösung; "
               "Verlassenwerden; Erwachsene, die Kindern schaden.",
     "tone": "Behaglich, verschmitzt, beruhigend am Schluss."},
    {"name": "Abenteuer", "age_rating": "alle",
     "description": "Aufbruch, Reise, Bewährung.",
     "rules": "Klares Ziel, Hindernisse auf dem Weg, Gefährten mit Stärken und Schwächen; Reisezeiten werden eingehalten.",
     "tension": "Aufbruch – Prüfungen – Tiefpunkt – Durchbruch – Heimkehr oder neuer Horizont.",
     "taboos": "Ziellosigkeit; Rettung ohne eigenes Zutun.",
     "tone": "Lebendig, mutig, mit Weite."},
    {"name": "Drama", "age_rating": "ab 12",
     "description": "Menschen (und andere Wesen) in Entscheidungen und Beziehungen.",
     "rules": "Innere Konflikte stehen im Mittelpunkt; keine reinen Bösewichte; Entscheidungen haben Folgen.",
     "tension": "Ausgangslage – Riss – Zuspitzung – Entscheidung – Nachklang.",
     "taboos": "Rührseligkeit ohne Grund; Konflikte, die sich von selbst lösen.",
     "tone": "Ernsthaft, nah, ehrlich."},
    {"name": "Komödie", "age_rating": "alle",
     "description": "Missverständnisse, Eigenheiten, Situationskomik.",
     "rules": "Humor entsteht aus Figuren und Situationen, nicht aus Spott über Gruppen; Running Gags dürfen wiederkehren.",
     "tension": "Kleines Problem – wachsendes Chaos – Höhepunkt – Auflösung mit Pointe.",
     "taboos": "Witze auf Kosten von Schwächeren; Zynismus.",
     "tone": "Leicht, verschmitzt, herzlich."},
    {"name": "Märchen", "age_rating": "alle",
     "description": "Zeitlose Erzählform mit Prüfungen, Wandlungen und klarer Moral – auch im All.",
     "rules": "Wiederholungen und Dreierstrukturen sind erlaubt; Gutes wird belohnt, Klugheit schlägt Stärke; "
              "Magie bzw. Phänomene folgen festen Regeln.",
     "tension": "Mangel – Aufbruch – drei Prüfungen – Wandlung – glückliches Ende.",
     "taboos": "Grausame Strafen im Detail; offenes, beunruhigendes Ende.",
     "tone": "Ruhig, bildhaft, ein wenig feierlich."},
]


def rules_text(conn: sqlite3.Connection, genre_id: int | None) -> str:
    if not genre_id:
        return ""
    row = conn.execute("SELECT * FROM genres WHERE id = ?", (genre_id,)).fetchone()
    if row is None:
        return ""
    parts = [f"GENRE: {row['name']} (Vorgabe Altersfreigabe: {row['age_rating'] or 'nicht festgelegt'})"]
    for key, label in (("description", "Kern"), ("rules", "Regeln"), ("tension", "Spannungsbogen"),
                       ("tone", "Ton"), ("taboos", "Tabus – möglichst vermeiden")):
        if row[key]:
            parts.append(f"- {label}: {row[key]}")
    return "\n".join(parts)


def resolve(conn: sqlite3.Connection, requested: int | None, thread_id: int | None) -> int | None:
    """Folge > Strang > Welt-Standard."""
    thread = conn.execute("SELECT genre_id FROM threads WHERE id = ?", (thread_id,)).fetchone() if thread_id else None
    for candidate in (requested, thread[0] if thread else None):
        if candidate and conn.execute("SELECT 1 FROM genres WHERE id = ?", (candidate,)).fetchone():
            return int(candidate)
    from . import service
    default = service.setting(conn, "standard_genre")
    if default and default.isdigit() and conn.execute("SELECT 1 FROM genres WHERE id = ?", (int(default),)).fetchone():
        return int(default)
    return None
