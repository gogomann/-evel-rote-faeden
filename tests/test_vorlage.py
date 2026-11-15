import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("STORY_QUALITY", os.path.join(tempfile.mkdtemp(prefix="sw-qual-"), "q.sqlite3"))

from story_world import episodes, genres, llm, service, vorlage, worlds  # noqa: E402

BUCH = ("Kapitel 1\n\nMara Lind kam an einem regnerischen Morgen in Hafenstadt an. " * 40
        + "\n\nKapitel 9\n\nAm Ende verlässt Mara die Stadt mit dem Brief ihres Bruders Jonas Lind. " * 40)


class VorlageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = {k: os.environ.get(k) for k in ("STORY_WORLDS_DIR", "STORY_CONFIG")}
        os.environ["STORY_WORLDS_DIR"] = self.tmp.name
        os.environ["STORY_CONFIG"] = os.path.join(self.tmp.name, "c.json")

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _fake_propose(self, conn, task, **kw):
        # Schein-KI: Abschnitt eingearbeitet → Figuren, Ort, Ereignis
        if not conn.execute("SELECT 1 FROM characters").fetchone():
            service.create_row(conn, "characters", {"first_name": "Mara", "last_name": "Lind"}, actor="ki")
            service.create_row(conn, "locations", {"name": "Hafenstadt", "kind": "stadt"}, actor="ki")
            service.create_row(conn, "events", {"title": "Abschied", "world_time": 42}, actor="ki")
        return None

    def _run(self, modus, genre_modus, analyse, genre=None):
        slug = worlds.create_world("Hafenwelt", "", False)
        with worlds.open_world(slug) as conn:
            gid = conn.execute("SELECT id FROM genres WHERE name = ?", (genre,)).fetchone()[0] if genre else None
            vorlage.start(conn, "hafen", modus, genre_modus, "hafen.txt", len(BUCH), gid, titel_vorgabe=False,
                          name_vorgabe=False)
        vorlage.store_text(slug, BUCH)
        with mock.patch.object(llm, "propose", side_effect=self._fake_propose), \
                mock.patch.object(llm, "complete", return_value=(analyse, "schein")):
            message = vorlage.import_job(slug, BUCH, None)
        return slug, message

    def test_fortsetzung_mit_festem_genre(self):
        with worlds.open_world(worlds.create_world("Tmp", "", False)) as conn:
            krimi = conn.execute("SELECT id FROM genres WHERE name = 'Krimi'").fetchone()[0]
        analyse = {"titel": "Hafenstadt", "autor": "R. K.", "genre_id": krimi, "zusammenfassung": "Mara sucht ihren Bruder.",
                   "ton": "ruhig, neblig", "ende": "Mara verlässt die Stadt mit dem Brief.", "offene_faeden": ["Wo ist Jonas?"],
                   "strang": {"id": None, "title": "Maras Suche", "premise": "Mara sucht Jonas.", "level": "mikro"}}
        slug, message = self._run("fortsetzung", "fest", analyse)
        self.assertIn("Vorlage ausgewertet, Genre Krimi", message)
        with worlds.open_world(slug) as conn:
            v = vorlage.get(conn)
            self.assertEqual((v["status"], v["modus"], v["genre_id"]), ("fertig", "fortsetzung", krimi))
            t = dict(conn.execute("SELECT * FROM threads WHERE id = ?", (v["strang_id"],)).fetchone())
            self.assertEqual((t["title"], t["status"], t["genre_id"], t["world_time_cursor"]), ("Maras Suche", "aktiv", krimi, 42))
            self.assertIn("Stand am Ende der Vorlage: Mara verlässt", t["premise"])
            # Genre fest: auch ein ausdrücklich anderes Genre wird überstimmt
            horror = conn.execute("SELECT id FROM genres WHERE name = 'Horror'").fetchone()[0]
            self.assertEqual(genres.resolve(conn, horror, None), krimi)
            head = vorlage.world_header(conn)
            for part in ("MODUS FORTSETZUNG", "STAND AM ENDE DER VORLAGE: Mara verlässt", "GENRE FEST", "Wo ist Jonas?"):
                self.assertIn(part, head)
            self.assertNotIn("===== WELT_REGELN.md", llm._read_context_docs(conn))
            self.assertIn("MODUS FORTSETZUNG", llm.build_messages(conn, "x")[1]["content"])
            self.assertIn("Nach der Vorlage „Hafenstadt“", service.meta(conn)["beschreibung"])
            self.assertEqual(service.meta(conn)["vorlage"]["autor"], "R. K.")
            self.assertEqual(service.meta(conn)["name"], "Hafenstadt")  # Name kam nur aus dem Dateinamen → Titel der Analyse
            self.assertFalse(conn.execute("SELECT 1 FROM peoples WHERE name = 'Aureas'").fetchone())  # kein Beispielbestand
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM impulses WHERE kind = 'text'").fetchone()[0], 1)

    def test_start_genre_frei_mit_neuem_genre(self):
        analyse = {"titel": "Hafenstadt", "genre_id": None, "zusammenfassung": "Eine Stadt am Meer.",
                   "genre_neu": {"name": "Hafenroman", "description": "Leben am Hafen", "age_rating": "ab 12"},
                   "strang": {"id": None, "title": "Hafenjahre", "premise": "…"}}
        slug, _ = self._run("start", "frei", analyse)
        with worlds.open_world(slug) as conn:
            v = vorlage.get(conn)
            gid = conn.execute("SELECT id FROM genres WHERE name = 'Hafenroman'").fetchone()[0]
            self.assertEqual(v["genre_id"], gid)
            self.assertIsNone(vorlage.fixed_genre(conn))
            self.assertEqual(service.setting(conn, "standard_genre"), "")
            krimi = conn.execute("SELECT id FROM genres WHERE name = 'Krimi'").fetchone()[0]
            self.assertEqual(genres.resolve(conn, krimi, None), krimi)
            t = conn.execute("SELECT status FROM threads WHERE id = ?", (v["strang_id"],)).fetchone()
            self.assertEqual(t[0], "beendet")  # bei „Start“ ist die Handlung des Buchs Vorgeschichte
            self.assertIn("MODUS START", vorlage.world_header(conn))
            self.assertIn("GENRE FREI", vorlage.world_header(conn))

    def test_genre_vorgabe_des_nutzers_gewinnt_und_analyse_fehler_bleibt_reparierbar(self):
        slug = worlds.create_world("Fehlerwelt", "", False)
        with worlds.open_world(slug) as conn:
            drama = conn.execute("SELECT id FROM genres WHERE name = 'Drama'").fetchone()[0]
            vorlage.start(conn, "Hafenstadt", "fortsetzung", "fest", "", len(BUCH), drama)
            self.assertEqual(service.setting(conn, "standard_genre"), str(drama))
        vorlage.store_text(slug, BUCH)
        with mock.patch.object(llm, "propose", side_effect=self._fake_propose), \
                mock.patch.object(llm, "complete", side_effect=llm.LLMError("kein Modell")):
            message = vorlage.import_job(slug, BUCH, None)
        self.assertIn("Steckbrief der Vorlage fehlt noch", message)
        with worlds.open_world(slug) as conn:
            self.assertEqual(vorlage.get(conn)["status"], "analyse_fehlt")
        with mock.patch.object(llm, "complete", return_value=({"genre_id": 1, "strang": {}}, "schein")):
            vorlage.analyse_job(slug, None)
        with worlds.open_world(slug) as conn:
            v = vorlage.get(conn)
            self.assertEqual((v["status"], v["genre_id"]), ("fertig", drama))  # Vorgabe schlägt Analyse

    def test_ungueltige_wahl(self):
        slug = worlds.create_world("X", "", False)
        with worlds.open_world(slug) as conn:
            with self.assertRaises(vorlage.VorlageError):
                vorlage.start(conn, "t", "irgendwas", "frei")
            with self.assertRaises(vorlage.VorlageError):
                vorlage.start(conn, "t", "start", "egal")
            self.assertEqual(vorlage.world_header(conn).splitlines()[0], "WELT: X")  # ohne Vorlage unverändert


if __name__ == "__main__":
    unittest.main()
