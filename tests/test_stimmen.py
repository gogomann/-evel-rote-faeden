"""Stimmen: virtueller Autor als gemeinsamer Stil-Maßstab für Planer, Autor, Lektor, Prüfer und Messung."""

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_admin  # noqa: E402 – nutzt dessen Schein-KI für die Pipeline


class StimmenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = {k: os.environ.get(k) for k in ("STORY_VOICES", "STORY_PROFILES", "STORY_PROFILE_TEXTS")}
        os.environ["STORY_VOICES"] = os.path.join(self.tmp.name, "stimmen.json")
        os.environ["STORY_PROFILES"] = os.path.join(self.tmp.name, "profiles.json")
        os.environ["STORY_PROFILE_TEXTS"] = os.path.join(self.tmp.name, "texte")

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_bloecke_und_massstab(self):
        from story_world import profiles, stimmen
        lem = stimmen.create({"art": "autor", "vorbild": "Stanisław Lem"})
        self.assertEqual(lem["name"], "Wie Stanisław Lem")
        lem = stimmen.edit(lem["id"], {"steckbrief": {"satzbau": "lange, verschachtelte Sätze"},
                                       "regler": {"humor": 2, "tempo": -1, "naehe": 9}, "hinweise": "keine Kalauer"})
        self.assertEqual(lem["regler"]["naehe"], 2)  # auf -2 … +2 begrenzt
        block = stimmen.writer_block(lem)
        for teil in ("Du schreibst wie Stanisław Lem", "lange, verschachtelte Sätze", "Humor: deutlich humorvoll",
                     "Tempo: ruhiger", "keine Kalauer"):
            self.assertIn(teil, block)
        self.assertNotIn("STILANKER", block)  # fremder Autor: kein Originaltext als Vorlage
        self.assertEqual(stimmen.reference_text(lem), "")  # ohne freigegebene Probe kein Messmaßstab
        with self.assertRaises(stimmen.VoiceError):
            stimmen.approve_probe(lem["id"])

        p = profiles.create("Ralf")
        profiles.add_text(p["id"], "Eigenes", ("Ilka sah zum Fenster hinaus. Draußen fiel Staub. " * 120).strip())
        ralf = stimmen.create({"art": "mensch", "profil_id": p["id"]})
        self.assertEqual(ralf["name"], "Wie Ralf")
        self.assertEqual(ralf["messwerte"]["quelle"], "eigene Texte")
        self.assertIn("STILANKER", stimmen.writer_block(ralf))
        self.assertIn("MESSWERTE DES MASSSTABS", stimmen.checker_block(ralf))
        self.assertIn("Ilka sah", stimmen.reference_text(ralf))
        stimmen.archive(ralf["id"])
        self.assertIsNone(stimmen.get(ralf["id"]))
        stimmen.archive(ralf["id"], back=True)
        self.assertIsNotNone(stimmen.get(ralf["id"]))

    def test_schreibstil_export_import(self):
        from story_world import profiles, stimmen
        p = profiles.create("Ralf")
        profiles.add_text(p["id"], "Eigenes", ("Ilka sah zum Fenster hinaus. Draußen fiel Staub. " * 120).strip())
        lem = stimmen.create({"art": "autor", "vorbild": "Stanisław Lem"})
        stimmen.edit(lem["id"], {"steckbrief": {"satzbau": "lang"}, "hinweise": "trocken"})
        ralf = stimmen.create({"art": "mensch", "profil_id": p["id"]})
        stimmen._update(lem["id"], lambda x: x.update(probe={"text": "Probe", "freigegeben": True, "audio": {"datei": "x"}}))
        datei = stimmen.export_file([lem["id"], ralf["id"]])
        self.assertEqual((datei["format"], len(datei["stimmen"])), ("evel-stimmen", 2))
        exp_ralf = next(v for v in datei["stimmen"] if v["id"] == ralf["id"])
        self.assertIn("Ilka sah", exp_ralf["basis"]["anker"])  # nur Auszüge, keine Texte-Liste nötig
        self.assertNotIn("audio", next(v for v in datei["stimmen"] if v["id"] == lem["id"])["probe"])
        with self.assertRaises(stimmen.VoiceError):
            stimmen.export_file(["v_00000000"])
        with self.assertRaises(stimmen.VoiceError):
            stimmen.import_file({"stimmen": []}, set())
        # gleicher Rechner, unverändert → nichts passiert
        r = stimmen.import_file(json.loads(json.dumps(datei)), {p["id"]})
        self.assertEqual((r["neu"], r["umbenannt"], len(r["vorhanden"])), ([], [], 2))
        # geändert → nicht überschrieben, sondern „Name 2“, dann „Name 3“
        stimmen.edit(lem["id"], {"hinweise": "anders"})
        r = stimmen.import_file(json.loads(json.dumps(datei)), {p["id"]})
        self.assertEqual(r["umbenannt"][0], {"alt": lem["name"], "neu": f"{lem['name']} 2"})
        self.assertEqual(stimmen.get(lem["id"])["hinweise"], "anders")
        self.assertNotEqual(r["ids"][0], lem["id"])
        r = stimmen.import_file(json.loads(json.dumps(datei)), {p["id"]})
        self.assertEqual(r["umbenannt"][0]["neu"], f"{lem['name']} 3")
        # andere Stimme mit gleichem Namen (andere Kennung) → ebenfalls Ziffer
        fremd = dict(datei["stimmen"][0], id="v_abcdef12", hinweise="fremd")
        r = stimmen.import_file({"format": "evel-stimmen", "stimmen": [fremd]}, {p["id"]})
        self.assertEqual(r["umbenannt"][0]["neu"], f"{fremd['name']} 4")
        self.assertIsNotNone(stimmen.get("v_abcdef12"))
        # fremder Rechner: neue Stimmen, Basis verborgen
        os.environ["STORY_VOICES"] = os.path.join(self.tmp.name, "stimmen2.json")
        r = stimmen.import_file(json.loads(json.dumps(datei)), set())
        self.assertEqual((len(r["neu"]), r["verborgen"]), (2, 1))
        self.assertTrue(stimmen.get(ralf["id"])["basis"]["verborgen"])
        self.assertNotIn("anker", stimmen.public(stimmen.get(ralf["id"]))["basis"])

    def test_eigenstaendige_geschichte(self):
        from story_world import episodes, runs, worlds
        fake = test_admin.FakePipelineLLM
        server = HTTPServer(("127.0.0.1", 0), fake)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        env = {"STORY_WORLDS_DIR": self.tmp.name, "STORY_CONFIG": os.path.join(self.tmp.name, "c.json"),
               "STORY_LLM_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}/v1", "STORY_LLM_MODEL": "pipe"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            slug = worlds.create_world("Geschichten")
            with worlds.open_world(slug) as conn:
                episodes.produce(conn, words=800)  # erst eine Folge, damit es eine Übergabe gäbe
                eid = episodes.produce(conn, words=800, form="geschichte")
                row = conn.execute("SELECT form, run_id FROM episodes WHERE id = ?", (eid,)).fetchone()
                self.assertEqual(row[0], "geschichte")

                def prompt(task):
                    cid = conn.execute("SELECT id FROM ai_calls WHERE run_id = ? AND task = ? ORDER BY id LIMIT 1",
                                       (row[1], task)).fetchone()[0]
                    return "\n".join(m["content"] for m in runs.get_call(conn, cid)["messages"])
                self.assertIn("EIGENSTÄNDIGE GESCHICHTE", prompt("planer"))
                author = prompt("autor")
                self.assertIn("ENTRÉE FÜR NEULINGE", author)
                self.assertNotIn("Die letzte Folge endete so", author)
                self.assertIn("Neuling:", prompt("pruefer"))
                self.assertNotIn("ÜBERGABE: Die vorige Folge", prompt("pruefer"))
                name, text = episodes.export_text(conn, eid)
                self.assertFalse(text.split("\n")[0].startswith("[Erzähler] Folge "))
                weights = runs.get_run(conn, row[1])["nachvollzug"]["phasen"][0]["ereignisse"][0]["eingaben"]
                self.assertEqual(weights["form"], "Eigenständige Geschichte")
                self.assertEqual(conn.execute("SELECT form FROM episodes WHERE id <> ?", (eid,)).fetchone()[0], "folge")
        finally:
            server.shutdown()
            for k, val in old.items():
                if val is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = val

    def test_probe_als_hoerbuch(self):
        import io
        import wave
        from story_world import stimmen, tts
        os.environ["STORY_CONFIG"] = os.path.join(self.tmp.name, "c.json")
        os.environ["STORY_WORLDS_DIR"] = os.path.join(self.tmp.name, "welten")
        sid = tts.add_server({"base_url": "http://127.0.0.1:9", "name": "Test-TTS"})
        spoken = []

        def speak(server, text, voice, language):
            spoken.append(text)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes(bytes(3200))
            return buf.getvalue()
        v = stimmen.create({"art": "frei", "name": "Leise", "beschreibung": "ruhig"})
        stimmen._update(v["id"], lambda x: x.update(probe={"text": "[Erzähler] Mara wartet.\n\n[Mara] Hörst du das?",
                                                           "freigegeben": False, "am": "jetzt"}))
        with self.assertRaises(stimmen.VoiceError):
            stimmen.probe_audio(v["id"], "", speak=speak)  # ohne Vorlese-Stimme
        v = stimmen.probe_audio(v["id"], f"{sid}|anna", speak=speak)
        self.assertEqual(spoken, ["Mara wartet.", "Hörst du das?"])  # Sprecher-Marken werden nicht vorgelesen
        self.assertTrue(stimmen.probe_audio_current(v))
        self.assertEqual(v["probe"]["audio"]["stimme"], "anna")
        stimmen.probe_audio(v["id"], f"{sid}|anna", speak=speak)  # alte Datei wandert nach _alt
        self.assertEqual(len(list(stimmen.probe_audio_path(v["id"]).parent.joinpath("_alt").iterdir())), 1)

    def test_stimme_wirkt_in_der_pipeline(self):
        from story_world import episodes, runs, service, stimmen, worlds
        fake = test_admin.FakePipelineLLM
        server = HTTPServer(("127.0.0.1", 0), fake)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        env = {"STORY_WORLDS_DIR": self.tmp.name, "STORY_CONFIG": os.path.join(self.tmp.name, "c.json"),
               "STORY_LLM_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}/v1", "STORY_LLM_MODEL": "pipe"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            v = stimmen.create({"art": "frei", "name": "Trocken", "beschreibung": "knapp und trocken"})
            stimmen.edit(v["id"], {"steckbrief": {"satzbau": "STIL-MARKER kurze Sätze"}})
            slug = worlds.create_world("Stimmen")
            with worlds.open_world(slug) as conn:
                service.set_setting(conn, "stimme", v["id"])
                fake.prompts.clear()
                eid = episodes.produce(conn, words=800)
                row = conn.execute("SELECT stimme_id, run_id, thread_id FROM episodes WHERE id = ?", (eid,)).fetchone()

                def prompt(task):
                    cid = conn.execute("SELECT id FROM ai_calls WHERE run_id = ? AND task = ? ORDER BY id LIMIT 1",
                                       (row[1], task)).fetchone()[0]
                    return "\n".join(m["content"] for m in runs.get_call(conn, cid)["messages"])
                for task in ("planer", "autor", "lektor"):
                    self.assertIn("STIL-MARKER kurze Sätze", prompt(task))
                    self.assertIn("STIMME „Trocken“", prompt(task))
                self.assertIn("STIL-MASSSTAB", prompt("pruefer"))
                self.assertEqual(row[0], v["id"])
                trace = runs.get_run(conn, row[1])["nachvollzug"]
                weights = trace["phasen"][0]["ereignisse"][0]["eingaben"]
                self.assertEqual((weights["stimme"]["name"], weights["stimme"]["quelle"]), ("Trocken", "Welt"))
                # Geschichte bekommt eigene Stimme → hat Vorrang vor der Welt
                other = stimmen.create({"art": "autor", "vorbild": "Ursula K. Le Guin"})
                conn.execute("UPDATE threads SET stimme_id = ? WHERE id = ?", (other["id"], row[2]))
                conn.commit()
                self.assertEqual(stimmen.resolve(conn, None, row[2])[1], "Geschichte")
                self.assertEqual(stimmen.resolve(conn, v["id"], row[2])[1], "Folge")
                with self.assertRaises(service.ValidationError):
                    service.set_setting(conn, "stimme", "v_00000000")
        finally:
            server.shutdown()
            for k, val in old.items():
                if val is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = val


if __name__ == "__main__":
    unittest.main()
