"""Nachvollzug: Entscheidungsprotokoll je Lauf (run_events) und Rekonstruktion alter Läufe."""

import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_admin  # noqa: E402 – nutzt dessen Schein-KI für die Pipeline


class NachvollzugTests(unittest.TestCase):
    def test_entscheidungen_werden_erfasst(self):
        from story_world import episodes, runs, worlds
        fake = test_admin.FakePipelineLLM
        server = HTTPServer(("127.0.0.1", 0), fake)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as tmp:
            env = {"STORY_WORLDS_DIR": tmp, "STORY_CONFIG": os.path.join(tmp, "c.json"),
                   "STORY_LLM_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}/v1", "STORY_LLM_MODEL": "pipe"}
            old = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
            try:
                slug = worlds.create_world("Nachvollzug")
                with worlds.open_world(slug) as conn:
                    fake.typ, fake.schwere = "gegenwart", "hoch"
                    eid = episodes.produce(conn, words=800)
                    run_id = conn.execute("SELECT run_id FROM episodes WHERE id = ?", (eid,)).fetchone()[0]
                    trace = runs.get_run(conn, run_id)["nachvollzug"]
                    self.assertEqual(trace["modus"], "erfasst")
                    phases = {p["id"]: p for p in trace["phasen"]}
                    for key in ("auftrag", "planer", "vorbereitung", "autor", "pruefer", "lektor", "speichern",
                                "archivar", "bewertung"):
                        self.assertIn(key, phases)
                    weights = phases["auftrag"]["ereignisse"][0]
                    self.assertEqual(weights["art"], "gewichtung")
                    self.assertEqual(weights["eingaben"]["ziel_woerter"], 800)
                    decision = [e for e in phases["bewertung"]["ereignisse"] if e["art"] == "entscheidung"][0]
                    self.assertEqual(decision["ausgang"], "mensch")  # Befund „hoch“ → wartet auf Freigabe
                    finding = [e for e in phases["pruefer"]["ereignisse"] if e["art"] == "pruefung"][0]
                    self.assertTrue(finding["verborgen"])  # Befunde nur mit Backstage
                    self.assertTrue(finding["call_id"])
                    self.assertNotIn("GEHEIME-ANDEUTUNG", json.dumps(trace))
                    shown = runs.get_run(conn, run_id, reveal=True)["nachvollzug"]
                    shown_finding = [e for p in shown["phasen"] if p["id"] == "pruefer" for e in p["ereignisse"]
                                     if e["art"] == "pruefung"][0]
                    self.assertEqual(shown_finding["ergebnis"]["schwere"], "hoch")  # mit Backstage sichtbar
                    self.assertGreater(trace["aenderungen"]["anzahl"], 0)  # Kanon-Änderungen mit Lauf-Bezug
                    self.assertIsNone(runs.current_id())  # Lauf-Stapel ist nach dem Lauf leer
            finally:
                fake.typ, fake.schwere = "gegenwart", "niedrig"
                server.shutdown()
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_alter_lauf_wird_rekonstruiert(self):
        from story_world import runs
        from story_world.migrations import initialize, migrate
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        initialize(conn)
        migrate(conn)
        steps = [{"zeit": "1", "text": "Auftrag angenommen – ohne Erzählprofil", "stufe": "info", "sekunden": 0},
                 {"zeit": "1", "text": "Planer: 1. Wahl: Anfrage an X – warte auf Antwort", "stufe": "info", "sekunden": 0},
                 {"zeit": "1", "text": "Plan: „T“ – 1 Kapitel, Typ gegenwart", "stufe": "ok", "sekunden": 1},
                 {"zeit": "1", "text": "Prüfer übersprungen: kaputt", "stufe": "warnung", "sekunden": 2},
                 {"zeit": "1", "text": "Abgebrochen: Autor streikt", "stufe": "fehler", "sekunden": 3}]
        conn.execute("INSERT INTO ai_runs (id, art, ziel, aufgabe, auftrag, steps, status) VALUES "
                     "(1, 'Folge', 'z', 'planer', 'Neue Folge erzeugen', ?, 'fehler')", (json.dumps(steps),))
        trace = runs.get_run(conn, 1)["nachvollzug"]
        self.assertEqual(trace["modus"], "rekonstruiert")
        outcomes = {p["id"]: p["status"] for p in trace["phasen"]}
        self.assertEqual(outcomes["planer"], "ok")
        self.assertEqual(outcomes["pruefer"], "warnung")
        self.assertEqual(outcomes["abbruch"], "fehler")
        self.assertTrue(trace["fehlt"])


if __name__ == "__main__":
    unittest.main()
