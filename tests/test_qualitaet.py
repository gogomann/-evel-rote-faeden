"""Tests für Qualitätssicherung: Messwerte, Prüfstand, Modellvergleich, Kaskade und Szenarien (mit simulierter KI)."""

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault("STORY_QUALITY", os.path.join(tempfile.mkdtemp(prefix="sw-qual-"), "q.sqlite3"))

from story_world import quality  # noqa: E402

PLAN = {"titel": "Klopfen", "strang": {"ref": "neu"}, "typ": "gegenwart", "welt_start": 200, "welt_ende": 201,
        "figuren": [], "einstieg": {"figur": "Ilka", "gefuehl": "unruhig", "lage": "das Klopfen ist wieder da"}, "kapitel": [{"titel": "Eins", "inhalt": "Etwas passiert.", "woerter": 400}], "einschuebe": [],
        "andeutungen": "", "ende_uebergabe": "Ende.",
        "vorbereitung": [{"aktion": "anlegen", "tabelle": "threads", "ref": "neu",
                          "felder": {"title": "Neuer Strang", "level": "mikro", "world_time_cursor": 200}}]}


class FakeAll(BaseHTTPRequestHandler):
    roles = []
    systems = []
    users = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        system = body["messages"][0]["content"]
        user = body["messages"][-1]["content"]
        FakeAll.systems.append(system)
        FakeAll.users.append(user)
        if "Themenplaner" in system:
            role, content = "thema", {"strang": {"neu": "Das Echo"}, "thema": "Ein Echo im Hafen",
                                      "richtung": "leise, unheimlich", "beteiligte": {"characters": [1], "locations": [1]}}
        elif "Bewerter einer" in system:
            role, content = "bewerter", {"bewertungen": [
                {"nr": 1, "kanonpassung": 9, "ueberraschung": 2, "fair": True, "begruendung": "erwartbar"},
                {"nr": 2, "kanonpassung": 8, "ueberraschung": 7, "fair": True, "begruendung": "überraschend"},
                {"nr": 3, "kanonpassung": 3, "ueberraschung": 9, "fair": False, "widersprueche": ["Doran ist tot"]}]}
        elif "Stammhörer" in system:
            role, content = "erwartung", {"erwartung": "Es bleibt ruhig.", "wahrscheinlich": ["Funk"], "sicher_geglaubt": []}
        elif "Mehrere Modelle" in system:
            role, content = "richter", {"bewertungen": [{"kennung": "A", "wert": 6, "begruendung": "ok"},
                                                        {"kennung": "B", "wert": 8, "begruendung": "besser"}], "bester": "B"}
        elif "Qualitäts-Richter" in system:
            role, content = "richter", {"plan_treue": 8, "genre_treue": 7, "konkretheit": 6, "begruendung": "solide"}
        elif "Kontinuitätsprüfer" in system:
            role = "pruefer"
            if "Doran Vex] Ilka, ich habe" in user:
                content = {"probleme": [
                    {"schwere": "hoch", "kapitel": 1, "beschreibung": "Doran Vex ist seit Weltzeit 50 tot, spricht aber.",
                     "korrektur": "streichen"},
                    {"schwere": "mittel", "kapitel": 1, "beschreibung": "Tageszahl „14. Tag“ statt Kalendernamen.",
                     "korrektur": "Kalender nutzen"},
                    {"schwere": "hoch", "kapitel": 1, "beschreibung": "Juno ist gleichzeitig an zwei Orten.",
                     "korrektur": "einen Ort wählen"},
                    {"schwere": "hoch", "kapitel": 1, "beschreibung": "Das Geheimnis um den Saphirschlüssel wird verraten.",
                     "korrektur": "nur andeuten"}]}
            elif "Das Klopfen ist wieder da" in user:
                content = {"probleme": []}
            else:
                content = {"probleme": [{"schwere": "niedrig", "kapitel": 1, "beschreibung": "x", "korrektur": "y"}]}
        elif "Du bist der Archivar" in system:
            role, content = "archivar", {"folgen_zusammenfassung": "Sefa eröffnet den Nebelkai.", "ende_uebergabe": "Morgen.",
                                         "operationen": [
                                             {"aktion": "anlegen", "tabelle": "characters", "felder": {"name": "Sefa Lorn"}},
                                             {"aktion": "anlegen", "tabelle": "locations", "felder": {"name": "Nebelkai",
                                                                                                      "kind": "sonstiges"}},
                                             {"aktion": "anlegen", "tabelle": "technologies", "felder": {"name": "Gleitsegler"}},
                                             {"aktion": "anlegen", "tabelle": "events",
                                              "felder": {"title": "Eröffnung des Nebelkais", "world_time": 121}},
                                             {"aktion": "anlegen", "tabelle": "locations", "felder": {"name": "Phantomstadt"}}]}
        elif "Planer" in system:
            role = "planer"
            if "SZENARIEN:" in system:
                a = dict(PLAN, titel="Ruhig", abweichung=1, idee="ruhig")
                b = dict(PLAN, titel="Wendung", abweichung=2, idee="Wendung", wendung="Juno lügt")
                content = {"szenarien": [a, b]}
            else:
                content = dict(PLAN)
        elif "Du bist der Weltenbauer" in system:
            role, content = "weltenbau", {"zusammenfassung": "x", "operationen": [
                {"aktion": "anlegen", "tabelle": "events", "sichtbarkeit": "backstage",
                 "felder": {"title": "Hintergrund", "world_time": 10}}]}
        elif "Lektor" in system:
            role, content = "lektor", user.split("\n\nKAPITEL:\n", 1)[1]
        else:
            role = "autor"
            content = "[Erzähler] " + " ".join(["Ilka zog den Handschuh aus, das Metall der Luke war kalt."] * 40) \
                      + "\n[Juno Abe] Ich höre dich."
        FakeAll.roles.append(role)
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        out = json.dumps({"choices": [{"message": {"content": text}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class Env:
    def __init__(self):
        self.server = HTTPServer(("127.0.0.1", 0), FakeAll)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {"STORY_WORLDS_DIR": self.tmp.name, "STORY_CONFIG": os.path.join(self.tmp.name, "c.json"),
                    "STORY_QUALITY": os.path.join(self.tmp.name, "q.sqlite3"),
                    "STORY_LLM_BASE_URL": f"http://127.0.0.1:{self.server.server_address[1]}/v1",
                    "STORY_LLM_MODEL": "fake"}
        self.old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)

    def close(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()


class MetricTests(unittest.TestCase):
    def test_code_metrics(self):
        share, hits = quality.spoiler_share(["Die Boje ist erwacht."], "Ein Saphirschlüssel liegt hier.", ("Saphirschlüssel",))
        self.assertEqual((share, hits), (1.0, ["Saphirschlüssel"]))
        share, _ = quality.spoiler_share(["Das Signal stammt von einer uralten Boje im äußeren Gürtel."],
                                         "[Erzähler] Das Signal stammt von einer uralten Boje im äußeren Gürtel, sagte er.")
        self.assertGreater(share, 0.5)
        self.assertEqual(quality.spoiler_share(["Ganz andere Wahrheit über die Sterne hier."], "Nichts davon.")[0], 0.0)
        self.assertGreater(quality.repetition("a b c d e f g", ["x a b c d e f g y"]), 0.9)
        concrete = quality.concreteness("[Erzähler] Ilka zog den Handschuh aus, das Metall der Luke im Hafen Tharsis war "
                                        "eiskalt; aus dem Funkgerät klopfte es dreimal.", ["Ilka", "Hafen Tharsis"])
        vague = quality.concreteness("[Erzähler] Irgendwie war alles seltsam, eine Art Gefühl lag irgendwie in der Luft, "
                                     "merkwürdig und unbeschreiblich, als ob irgendwas wäre.", ["Ilka"])
        self.assertGreater(concrete["wert"], vague["wert"])
        self.assertEqual(quality.editor_damage("Ilka und Juno reden lange.", "Ilka redet.", ["Ilka", "Juno"]), 0.6)
        values = quality.style_values("[Erzähler] Ein Satz. Noch einer hier.\n[Ilka] Hallo du.")
        self.assertEqual(values["dialoganteil"], 0.5)

    def test_reference_and_drift(self):
        for v in (1.0, 1.0, 1.0):
            quality.record("format", "planer", "Test · drift", v)
        quality.auto_reference()
        model = next(m for m in quality.overview()["modelle"] if m["modell"] == "Test · drift")
        self.assertEqual(model["ampel"], "gruen")
        for v in (0.0,) * 10:
            quality.record("format", "planer", "Test · drift", v)
        model = next(m for m in quality.overview()["modelle"] if m["modell"] == "Test · drift")
        self.assertEqual((model["ampel"], model["tests"][0]["status"]), ("rot", "drift"))
        self.assertEqual(quality.set_reference("Test · drift"), 1)
        model = next(m for m in quality.overview()["modelle"] if m["modell"] == "Test · drift")
        self.assertEqual(model["tests"][0]["status"], "warnung")  # unter der Grenze, aber keine Drift mehr


class BenchAndPipelineTests(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        FakeAll.roles.clear()
        FakeAll.users.clear()
        FakeAll.systems.clear()

    def tearDown(self):
        self.e.close()

    def test_bench_full_with_ballast_and_cascade(self):
        from story_world import pruefstand, worlds
        res = pruefstand.run_bench("schnell")
        werte = res["modelle"]["Umgebungsvariablen · fake"]["werte"]
        self.assertEqual(werte["pruefer_fallen"], 6.7)  # 4 von 6 Fallen gefunden
        self.assertEqual(werte["fehlalarme"], 0.0)
        self.assertEqual(werte["archivar"], 8.0)  # alle 4 Fakten, 1 erfunden
        slug = worlds.create_world("Ballastwelt")
        res = pruefstand.run_bench("voll", ballast=slug, kontext_modus="kaskade")
        werte = res["modelle"]["Umgebungsvariablen · fake"]["werte"]
        self.assertEqual(werte["bewerter_rangfolge"], 10.0)
        self.assertEqual(werte["format"], 1.0)
        self.assertEqual(werte["spoiler"], 0.0)
        self.assertEqual((werte["plan_treue"], werte["genre_treue"]), (8.0, 7.0))
        self.assertIn("thema", FakeAll.roles)  # Kaskade: erste Ebene lief
        series = quality.get_series(res and quality.overview()["serien"][0]["id"])
        self.assertEqual(series["status"], "fertig")
        tests = {t["test"] for m in quality.overview()["modelle"] for t in m["tests"]}
        for t in ("pruefer_fallen", "fehlalarme", "archivar", "bewerter_rangfolge", "spoiler", "konkretheit",
                  "plan_treue", "richter_streuung", "kontext", "format", "laenge", "verweigerung"):
            self.assertIn(t, tests)
        with worlds.open_world(slug) as conn:  # echte Welt bleibt unberührt
            self.assertIsNone(conn.execute("SELECT 1 FROM characters WHERE name = 'Ilka Marren'").fetchone())

    def test_scenarios_calls_and_compare(self):
        from story_world import episodes, runs, service, szenarien, vergleich, worlds
        slug = worlds.create_world("Szenarienwelt")
        with worlds.open_world(slug) as conn:
            eid = episodes.produce(conn, words=400, abweichung=2, szenarien_anzahl=2)
            ep = episodes.get_episode(conn, eid, reveal=True)
            self.assertEqual(ep["plan"]["titel"], "Wendung")  # Überraschung 7 liegt am nächsten am Ziel 6,5
            s = szenarien.get_set(conn, ep["scenario_set_id"], reveal=True)
            self.assertEqual((s["status"], s["gewaehlt"], s["episode_id"]), ("gewaehlt", 2, eid))
            self.assertIn("ABWEICHUNG Stufe 2", " ".join(FakeAll.systems))
            self.assertTrue(any("Täuschung des Erzählers" in u for u in FakeAll.users))  # Prüfer gelockert
            hidden = szenarien.get_set(conn, ep["scenario_set_id"], reveal=False)
            self.assertNotIn("wendung", json.dumps(hidden))
            self.assertIn("qualitaet", json.loads(conn.execute("SELECT metrics FROM episodes WHERE id = ?",
                                                               (eid,)).fetchone()[0]))
            # Erwartung sieht nur, was der Hörer kennt (Spoiler-Kanarie im Backstage)
            service.create_row(conn, "mysteries", {"description": "Offenes Rätsel", "status": "offen",
                                                   "truth": "KANARIE-WAHRHEIT-42"}, actor="ki", visibility="backstage")
            service.create_row(conn, "characters", {"name": "Geheime Figur Kanarie"}, actor="ki", visibility="backstage")
            public = szenarien.public_context(conn, None, "")
            self.assertNotIn("KANARIE", public)
            # Du wählst selbst
            service.set_setting(conn, "szenario_wahl", "ich")
            self.assertIsNone(episodes.produce(conn, words=400, szenarien_anzahl=2))
            waiting = szenarien.open_sets(conn)
            self.assertEqual(len(waiting), 1)
            eid2 = episodes.produce(conn, words=400, scenario_set_id=waiting[0]["id"], scenario_nr=1)
            self.assertEqual(episodes.get_episode(conn, eid2, reveal=True)["plan"]["titel"], "Ruhig")
            self.assertEqual(szenarien.open_sets(conn), [])
            # Jeder Aufruf ist gespeichert, inklusive Prompt
            calls = runs.list_calls(conn, ep["run_id"])
            self.assertEqual({c["task"] for c in calls} >= {"erwartung", "planer", "bewerter", "autor", "pruefer",
                                                            "lektor", "archivar"}, True)
            author = next(c for c in calls if c["task"] == "autor")
            self.assertIn("SCHREIBE JETZT", runs.get_call(conn, author["id"])["messages"][-1]["content"])
            plain = runs.get_run(conn, ep["run_id"])
            self.assertTrue(plain["aufrufe"])  # Metadaten ohne Backstage sichtbar …
            self.assertNotIn("response", plain["aufrufe"][0])  # … Antworten nicht
            self.assertNotIn("messages", plain["aufrufe"][0])
            # Kaskade: Autor bekommt nur die Beteiligten
            service.set_setting(conn, "kontext_modus", "kaskade")
            service.set_setting(conn, "szenario_wahl", "automatisch")
            FakeAll.users.clear()
            eid3 = episodes.produce(conn, words=400)
            weg = " | ".join(st["text"] for st in runs.get_run(conn, episodes.get_episode(conn, eid3)["run_id"])["steps"])
            self.assertIn("Thema:", weg)
            self.assertIn("Kaskade", weg)
            author_prompt = next(u for u in FakeAll.users if "SCHREIBE JETZT" in u)
            self.assertIn("KANON DER BETEILIGTEN", author_prompt)
            self.assertNotIn("AKTUELLER KANON", author_prompt)
        # Modellvergleich mit dem gespeicherten Autor-Aufruf
        res = vergleich.compare(slug, author["id"], [{"provider": "env", "model": "fake"}], richter=True)
        self.assertEqual(len(res["ergebnisse"]), 2)  # Original + 1 Modell
        self.assertTrue(res["ergebnisse"][0]["original"])
        self.assertIn("konkretheit", res["ergebnisse"][1]["werte"])
        self.assertEqual(res["richter"]["bester"], "Umgebungsvariablen · fake")
        self.assertIsNone(vergleich.public(res, reveal=False)["ergebnisse"][1]["text"])


if __name__ == "__main__":
    unittest.main()
