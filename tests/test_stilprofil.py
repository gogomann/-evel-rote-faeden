"""Stil-Fingerabdruck: messen, vergleichen, erkennen – und Einbindung in Stimmen."""

import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from story_world import stilprofil  # noqa: E402

NAMEN = ["Ilka", "Tomas", "Mara", "Jaro"]
ORTE = ["am Fenster", "im Hof", "an der Schleuse", "im Labor", "auf der Brücke"]


def _knapp(seed: int, absaetze: int = 300) -> str:
    """Autor A: kurze Hauptsätze, Präteritum, viel Dialog in »…«."""
    rnd = random.Random(seed)
    out = []
    for _ in range(absaetze):
        n, o = rnd.choice(NAMEN), rnd.choice(ORTE)
        out.append(f"{n} stand {o}. Es war kalt. Sie wartete. Dann kam der Bote. »Hast du es?« fragte {n}. "
                   f"»Ja.« Er nickte. »Gut. Dann los.« Sie gingen. Der Wind war laut. Niemand sprach.")
    return "\n\n".join(out)


def _verschachtelt(seed: int, absaetze: int = 300) -> str:
    """Autor B: lange, verschachtelte Sätze, Präsens, Ich-Erzähler, kaum Dialog."""
    rnd = random.Random(seed)
    out = []
    for _ in range(absaetze):
        n, o = rnd.choice(NAMEN), rnd.choice(ORTE)
        out.append(f"Ich weiß nicht, ob ich {o}, wo das Licht noch immer flackert, wirklich verstehe, was {n} mir sagen "
                   f"will, denn jedes Mal, wenn ich glaube, den Gedanken zu greifen, entgleitet er mir wieder; vielleicht "
                   f"liegt es daran, dass ich müde bin, vielleicht aber auch daran, dass ich es gar nicht wissen will. "
                   f"Ich sehe hinaus und denke, dass alles, was wir uns vorgenommen haben, kleiner ist, als es scheint.")
    return "\n\n".join(out)


def _englisch(seed: int, absaetze: int = 300) -> str:
    """Englisches Vorbild mit gleichem Satzbau wie _knapp."""
    rnd = random.Random(seed)
    out = []
    for _ in range(absaetze):
        n = rnd.choice(NAMEN)
        out.append(f"{n} stood at the window. It was cold. She waited. Then the messenger came. “Do you have it?” asked {n}. "
                   f"“Yes.” He nodded. “Good. Then go.” They went. The wind was loud. Nobody spoke.")
    return "\n\n".join(out)


class StilprofilTests(unittest.TestCase):
    def test_fremdsprachiges_vorbild_nur_sprachfreie_merkmale(self):
        fp = stilprofil.fingerabdruck(_englisch(1), "Test EN", "Book")
        self.assertEqual(fp["sprache"], "en")
        legacy = {k: v for k, v in fp.items() if k != "sprache"}           # älterer Fingerabdruck ohne Feld
        self.assertEqual(stilprofil.fp_sprache(legacy), "en")
        for ref in (fp, legacy):
            rep = stilprofil.vergleichen(_knapp(2, 60), ref)
            ids = {m["id"] for m in rep["merkmale"]}
            self.assertTrue(ids <= stilprofil.SPRACHFREI)                     # keine Wortlänge, Kommas, kleinen Wörter
            self.assertEqual(rep["auffaellige_woerter"], [])
            self.assertIn("Englisch", rep["satz"])
            self.assertEqual(rep["urteil"], "passt")                         # gleicher Satzbau → passt trotz Sprache
        self.assertNotIn("Buchstaben", stilprofil.ziele(fp))
        self.assertIn("Englisch", stilprofil.ziele(fp))
        same = stilprofil.vergleichen(_knapp(2, 60), stilprofil.fingerabdruck(_knapp(1), "Test A"))
        self.assertEqual(same["nicht_verglichen"], [])                       # gleiche Sprache: alles wie bisher

    def test_gleicher_autor_passt_anderer_nicht(self):
        fp = stilprofil.fingerabdruck(_knapp(1), "Test A", "Buch A")
        self.assertGreaterEqual(fp["abschnitte"], 4)
        self.assertNotIn("Ilka stand", str(fp))  # nur Kennzahlen, kein Text
        same = stilprofil.vergleichen(_knapp(2, 60), fp)
        other = stilprofil.vergleichen(_verschachtelt(3, 60), fp)
        self.assertEqual(same["urteil"], "passt")
        self.assertEqual(other["urteil"], "stark")
        self.assertGreater(same["wert"], other["wert"] + 25)
        ids = {m["id"]: m for m in other["merkmale"]}
        self.assertEqual(ids["praeteritum"]["urteil"], "stark")
        self.assertIn("Gegenwart", ids["praeteritum"]["satz"])
        self.assertIn("Satzlänge", " ".join(m["label"] for m in other["merkmale"] if m["urteil"] != "passt"))
        self.assertTrue(stilprofil.anhalten(other))
        self.assertFalse(stilprofil.anhalten(same))

    def test_hoerbuchformat_wie_buchformat(self):
        buch = "»Komm her«, sagte Mara. Sie lachte.\n\n" * 80
        folge = "[Mara] Komm her.\n\n[Erzähler] Sie lachte.\n\n" * 80
        a, b = stilprofil.messen(buch), stilprofil.messen(folge)
        self.assertAlmostEqual(a["dialoganteil"], b["dialoganteil"], delta=0.2)
        self.assertGreater(b["dialoganteil"], 0.2)

    def test_zu_kurz_und_ohne_massstab(self):
        fp = stilprofil.fingerabdruck(_knapp(1), "A")
        self.assertEqual(stilprofil.vergleichen("Zu kurz.", fp)["urteil"], "zu_kurz")
        self.assertIsNone(stilprofil.vergleichen(_knapp(2), None))
        self.assertIsNone(stilprofil.fingerabdruck("viel zu kurz"))

    def test_erkennen_und_ziele(self):
        fa = stilprofil.fingerabdruck(_knapp(1), "A", "Buch A")
        fb = stilprofil.fingerabdruck(_verschachtelt(1), "B", "Buch B")
        r = stilprofil.erkennen(_verschachtelt(9, 50), [("a", "Knapp", fa), ("b", "Verschachtelt", fb)])
        self.assertEqual(r["rangliste"][0]["id"], "b")
        self.assertIn("Verschachtelt", r["satz"])
        ziele = stilprofil.ziele(fa)
        self.assertIn("Präteritum", ziele)
        self.assertIn("„Buch A“", ziele)
        self.assertIn("dritten Person", ziele)
        self.assertIn("Ich-Erzähler", stilprofil.ziele(fb))

    def test_auffaellige_woerter(self):
        fp = stilprofil.fingerabdruck(_knapp(1, 400), "A")
        text = _knapp(5, 60) + "\n\n" + "\n\n".join(["Das Flimmern kam zurück. Ein leises Summen."] * 15)
        rep = stilprofil.vergleichen(text, fp, ["Mara"])
        woerter = [w["wort"] for w in rep["auffaellige_woerter"]]
        self.assertIn("flimmern", woerter)
        self.assertNotIn("mara", woerter)


class StimmenFingerabdruckTests(unittest.TestCase):
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

    def test_autor_mit_referenzbuch(self):
        from story_world import profiles, stimmen
        p = profiles.create("Ralf")
        buch = profiles.add_text(p["id"], "Buch A", _knapp(1), fremd=True, autor="Autor A")
        v = stimmen.create({"art": "autor", "vorbild": "Autor A", "profil_id": p["id"], "referenz_texte": [buch["id"]]})
        self.assertEqual(v["fingerabdruck"]["quelle"], "Referenztexte des Vorbilds")
        self.assertEqual(v["messwerte"]["quelle"], "Referenztexte des Vorbilds")
        block = stimmen.writer_block(v)
        self.assertIn("MESSBARE STILZIELE", block)
        self.assertNotIn("Ilka stand", block)  # fremder Text nie als Vorlage für den Autor
        self.assertNotIn("STILANKER", block)
        self.assertIn("MESSBARE STILZIELE", stimmen.checker_block(v))
        pub = stimmen.public(v)
        self.assertNotIn("wortschatz", pub["fingerabdruck"])
        self.assertTrue(pub["fingerabdruck_tabelle"])
        self.assertEqual([x[0] for x in stimmen.with_fingerprint()], [v["id"]])
        # Text archiviert → keine Referenz, kein veralteter Maßstab
        profiles.archive_text(p["id"], buch["id"])
        stimmen.refresh_owner(p["id"])
        v = stimmen.get(v["id"])
        self.assertEqual((v["referenz_texte"], v["fingerabdruck"], v["messwerte"]), ([], None, None))

    def test_probe_und_nachmessen_alter_stimmen(self):
        from story_world import stimmen
        v = stimmen.create({"art": "autor", "vorbild": "Lem"})
        self.assertIsNone(v.get("fingerabdruck"))
        stimmen._update(v["id"], lambda x: (x.update(probe={"text": _knapp(4, 12), "freigegeben": False}),
                                            x.pop("fingerabdruck", None)))
        stimmen.approve_probe(v["id"])
        v = stimmen.get(v["id"])
        self.assertEqual(v["fingerabdruck"]["quelle"], "freigegebene Probe")
        stimmen._update(v["id"], lambda x: x.pop("fingerabdruck"))  # Stimme von vor dem Fingerabdruck
        self.assertEqual(stimmen.get(v["id"])["fingerabdruck"]["quelle"], "freigegebene Probe")
        stimmen.approve_probe(v["id"], False)
        self.assertIsNone(stimmen.get(v["id"])["fingerabdruck"])


if __name__ == "__main__":
    unittest.main()


class PipelineStilTests(StimmenFingerabdruckTests):
    def test_folge_wird_gemessen_und_angehalten(self):
        import json
        import threading
        from http.server import HTTPServer
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import test_admin
        from story_world import episodes, profiles, service, stimmen, worlds
        fake = test_admin.FakePipelineLLM
        server = HTTPServer(("127.0.0.1", 0), fake)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        env = {"STORY_WORLDS_DIR": self.tmp.name, "STORY_CONFIG": os.path.join(self.tmp.name, "c.json"),
               "STORY_QUALITY": os.path.join(self.tmp.name, "q.sqlite3"),
               "STORY_LLM_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}/v1", "STORY_LLM_MODEL": "pipe"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            p = profiles.create("Ralf")
            buch = profiles.add_text(p["id"], "Buch B", _verschachtelt(1), fremd=True)
            v = stimmen.create({"art": "autor", "vorbild": "Autor B", "profil_id": p["id"], "referenz_texte": [buch["id"]]})
            slug = worlds.create_world("Stil")
            with worlds.open_world(slug) as conn:
                service.set_setting(conn, "stimme", v["id"])
                eid = episodes.produce(conn, words=800)
                status, metrics = conn.execute("SELECT status, metrics FROM episodes WHERE id = ?", (eid,)).fetchone()
                m = json.loads(metrics)
                rep = m.get("stilbericht")
                self.assertIsNotNone(rep)
                self.assertEqual(rep["stimme"]["id"], v["id"])
                self.assertEqual((rep["urteil"], status), ("stark", "freigabe"))  # Schein-KI schreibt nicht wie Autor B
                self.assertTrue(any("Stil" in g for g in m["freigabe_gruende"]))
                live = episodes.style_check(conn, eid)
                self.assertEqual(live["stimme"]["id"], v["id"])
                self.assertEqual(live["bericht"]["wert"], rep["wert"])
                service.set_setting(conn, "stil_anhalten", "nie")
                eid2 = episodes.produce(conn, words=800)
                m2 = json.loads(conn.execute("SELECT metrics FROM episodes WHERE id = ?", (eid2,)).fetchone()[0])
                self.assertFalse(any("Stil" in g for g in m2.get("freigabe_gruende", [])))
        finally:
            server.shutdown()
            for k, val in old.items():
                if val is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = val
