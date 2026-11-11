"""Startbestand ausschließlich aus WELT_REGELN.md / OFFENE_PUNKTE.md – nichts dazuerfunden.

Bewusst leer gelassene Felder (Kalender-Zyklusnamen, Umrechnung, Ziele …) sind Lücken,
die das System laut OFFENE_PUNKTE.md selbst entwickeln soll.
"""

from __future__ import annotations

import sqlite3

from . import service

RULES = [
    ("Überlichtreise per Warpblase: Raum wird vor dem Schiff gestaucht und dahinter gedehnt. "
     "Jede Reise wird geplant. Reisezeit wird immer berechnet (Entfernung, Antrieb, Vorbereitung).", "Technik"),
    ("Kommunikation über verschränkte Teilchen, ohne Verzögerung. Keine zusätzlichen Einschränkungen erfinden.", "Technik"),
    ("Wer etwas früher weiß, als es normal möglich ist, braucht eine Quelle (Person, Gerücht, Beobachtung). "
     "Technik ist dafür kein Hindernis.", "Wissen"),
    ("Intern gilt ein Master-Kalender als fortlaufende Zahl. Das ist der Fixpunkt.", "Zeit"),
    ("Jedes Volk hat einen eigenen Kalender, der sich eindeutig in den Master umrechnen lässt.", "Zeit"),
    ("Nach außen niemals Tageszahlen nennen, sondern Zyklus- und Jahresnamen "
     "(ähnlich dem chinesischen Tierkreis, aber futuristisch).", "Zeit"),
    ("Welcher Kalender erzählt, verrät Herkunft und Haltung der Figur.", "Zeit"),
    ("Umbenennung oder Flucht eines Volkes kann Kalenderwechsel oder -verlust bedeuten.", "Zeit"),
    ("Pro Volk Steckbrief: Herkunft, Körper, Kultur, Kalender, Zeichen/Codes, Ziele, Beziehungen, "
     "Entwicklungsstatus (Bevölkerung, Technik, Ressourcen).", "Völker"),
    ("Körperliche Merkmale ergeben Folgeregeln (Sehfeld, Haltung, Stimme, Kleidung, Bewegung) "
     "und werden als Regeln gespeichert.", "Völker"),
    ("Wachstum glaubwürdig: maximal 1 bis 2 Statusänderungen pro Folge pro Volk.", "Völker"),
    ("Auch Völker, die gerade in keinem Strang vorkommen, entwickeln sich mit der Weltzeit weiter.", "Völker"),
    ("Langfristig sollen mehrere Dutzend Völker entstehen; Traditionen können unterschiedlich strikt sein "
     "und sich verändern.", "Völker"),
    ("Vergangenheit ist kanon-gesperrt: ergänzen ja, widersprechen nein.", "Zeit"),
    ("Ton: für Erwachsene, grundsätzlich hoffnungsvoll, an Star Trek angelehnt. Menschen stehen meist in gutem "
     "Licht, aber nicht alle handeln gut.", "Ton"),
]


def seed_from_rules(conn: sqlite3.Connection) -> bool:
    """Legt Menschen, Aureas, Aureas-Kalender, Weltregeln und das Aureas-Rätsel an (nur in leerer Welt)."""
    if conn.execute("SELECT 1 FROM peoples LIMIT 1").fetchone():
        return False
    cal = service.create_row(conn, "calendars", {"name": "Aureas-Kalender"})
    service.create_row(conn, "peoples", {
        "name": "Menschen",
        "body_rules": "Klarer Maßstab ohne Besonderheiten.",
    })
    service.create_row(conn, "peoples", {
        "name": "Aureas",
        "origin": "Genetische Quelle vogelartig.",
        "body_rules": (
            "Füße mit nur Zehen, Augen mehrheitlich weiter auseinander, Kopfhaar noch Federn. "
            "Über Hunderttausende Jahre ist dort, wo Kleidung getragen wurde, dauerhaft Haut entstanden; "
            "die Veränderungen werden gerade stärker sichtbar. "
            "Traditionelle: kaum Kleidung, mehr Federn, können noch fliegen. "
            "Raumfahrer: leben im All, tragen Kleidung, mehr nackte Haut, können nicht mehr fliegen."
        ),
        "culture": (
            "Zwei Lebensweisen innerhalb desselben Volkes (Traditionelle und Raumfahrer). Sichtbare Unterschiede "
            "führen zu Spannungen und Rassismus innerhalb des Volkes; beide Seiten haben eigene Perspektiven, "
            "keiner wird zum reinen Bösewicht. Gemeinsamer Kalender: Traditionelle leben ihn mit Jahreszeiten, "
            "Raumfahrer eher als Erinnerung; Streit darüber, wer ihn richtig lebt, ist erlaubt. Die Tradition wird "
            "unterschiedlich streng gelebt und passt sich veränderten Lebensumständen an."
        ),
        "calendar_id": cal,
    })
    for rule, category in RULES:
        service.create_row(conn, "world_rules", {"rule": rule, "category": category})
    service.create_row(conn, "mysteries", {
        "description": "Warum verändert sich der Körper der Aureas gerade jetzt so sichtbar?",
        "status": "offen",
    })
    service.audit(conn, "system", "startbestand", detail="aus WELT_REGELN.md")
    return True
