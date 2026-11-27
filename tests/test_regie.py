"""Hörspiel-Regie: Wortlaut-Schutz, Tags, KI-Durchgang, Handbearbeitung, Vertonung mit Stil + Geräuschen, JSON-Export."""

import json
import os
import struct
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from story_world import audio, llm, regie, service, tts, worlds  # noqa: E402

TEXT = ("[Erzähler] Iva, 23, sitzt allein im Hangar. Die Lampen flackern.\n\n"
        "[Iva] Na toll. Schon wieder kaputt.\n\n"
        "[Ole] Ich hab's dir gesagt!")


def wav(seconds=0.05, rate=24000):
    pcm = b"\x00\x00" * int(rate * seconds)
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(pcm)) + pcm


class FakeLibra(BaseHTTPRequestHandler):
    requests: list = []

    def log_message(self, *a):
        pass

    def _send(self, data, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/v1/audio/voices":
            return self._send(json.dumps({"voices": [{"id": "nina", "name": "Nina", "gender": "female"},
                                                     {"id": "jon", "name": "Jon", "gender": "male"},
                                                     {"id": "bob", "name": "Bob", "gender": "male"}],
                                          "styles": regie.STILE, "paces": ["slow", "fast"], "tags": regie.TAGS}).encode(),
                              "application/json")
        if self.path == "/v1/models":
            return self._send(b'{"data": [{"id": "tts-1"}]}', "application/json")
        self._send(b"{}", "application/json", 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLibra.requests.append(body)
        self._send(wav(), "audio/wav")


def fake_ki(payloads):
    """Ersetzt llm.complete: liefert der Reihe nach die vorgegebenen Antworten."""
    calls = []

    def complete(messages, aufgabe, run=None):
        calls.append((messages, aufgabe))
        item = payloads[min(len(calls), len(payloads)) - 1]
        if isinstance(item, Exception):
            raise item
        return item, "Test · regie-modell"
    complete.calls = calls
    return complete


class RegieTextTests(unittest.TestCase):
    def test_bereinigen(self):
        orig = "Na toll. Schon wieder kaputt."
        self.assertEqual(regie.bereinigen("<sigh> Na toll. Schon wieder kaputt.", orig, regie.TAGS, 1),
                         "<sigh> Na toll. Schon wieder kaputt.")
        self.assertIsNone(regie.bereinigen("Na toll. Schon wieder total kaputt.", orig, regie.TAGS, 3))  # Wortlaut!
        self.assertIsNone(regie.bereinigen("<flüstert> Na toll. Schon wieder kaputt.", orig, regie.TAGS, 3))  # unbekannt
        self.assertEqual(regie.bereinigen("<sigh> Na toll <short pause>. <laugh> Schon wieder kaputt.", orig, regie.TAGS, 2),
                         "<sigh> Na toll <short pause>. Schon wieder kaputt.")
        self.assertEqual(regie.bereinigen("<SIGH>Na toll.  Schon wieder kaputt.", orig, regie.TAGS, 1),
                         "<sigh> Na toll. Schon wieder kaputt.")
        self.assertIsNone(regie.bereinigen("", orig, regie.TAGS, 1))

    def test_atmen(self):
        long = ("Iva sitzt allein im Hangar und starrt auf die flackernden Lampen über der Werkbank. Irgendwo tropft Kühlmittel. "
                "Sie zählt die Tropfen, eins, zwei, drei, und verliert den Faden. Der Regler hält keine zwei Tage, hat Ole "
                "gesagt, und Ole hat meistens recht, auch wenn sie das nie zugeben würde. Draußen schlägt eine Tür. "
                "Sie hält den Atem an. Nichts. Dann wieder das Tropfen, gleichmäßig, geduldig, als hätte es alle Zeit der Welt.")
        dezent = regie.atmen(long, "dezent", regie.TAGS)
        self.assertGreaterEqual(dezent.count("<breath>"), 1)
        self.assertFalse(dezent.startswith("<"))                        # dezent: nicht am Absatzbeginn
        self.assertEqual(regie._bare(dezent), regie._bare(long))        # Wortlaut bleibt
        lebendig = regie.atmen(long, "lebendig", regie.TAGS, "frightened")
        self.assertTrue(lebendig.startswith("<heavy breath>"))
        self.assertEqual(lebendig.count("<heavy breath>"), 1)
        self.assertGreater(lebendig.count("<breath>"), dezent.count("<breath>") - 1)
        self.assertEqual(regie.atmen("Kurz. Knapp.", "lebendig", regie.TAGS), "Kurz. Knapp.")
        self.assertEqual(regie.atmen(long, "aus", regie.TAGS), long)
        self.assertEqual(regie.atmen(long, "dezent", ["<laugh>"]), long)  # Server ohne <breath>
        tagged = regie.atmen(long.replace("Draußen", "<gasp> Draußen"), "dezent", regie.TAGS)
        self.assertNotIn("<breath> <gasp>", tagged)                     # nie direkt neben anderem Tag
        # Atem-Tags zählen nicht gegen die Obergrenze für Gefühls-Tags
        self.assertEqual(regie.bereinigen("<breath> <sigh> Na toll. <breath> Schon <laugh> wieder kaputt.", "Na toll. Schon wieder kaputt.",
                                          regie.TAGS, 1), "<breath> <sigh> Na toll. <breath> Schon wieder kaputt.")

    def test_tags_ueberstehen_lexikon_und_zerlegen(self):
        text = "Die Aureas kommen. <short pause> Und dann <heavy breath> ein langer Satz über den Aufzug, " * 3
        protected = regie.schuetzen(text)
        lexed = audio.apply_lexicon(protected, [{"term": "Aureas", "spoken": "Ah-u-re-as", "variants": "",
                                                 "ignore_case": 0, "language": "", "ipa": ""},
                                                {"term": "pause", "spoken": "PAUSE", "variants": "",
                                                 "ignore_case": 1, "language": "", "ipa": ""}])
        chunks = [regie.zurueck(c) for c in tts.chunk_text(lexed, 80)]
        joined = " ".join(chunks)
        self.assertIn("<short pause>", joined)
        self.assertIn("<heavy breath>", joined)
        self.assertIn("Ah-u-re-as", joined)
        self.assertNotIn("PAUSE", joined)
        self.assertTrue(all("" not in c for c in chunks))

    def test_faehig(self):
        self.assertIsNone(regie.faehig({"preset": "custom"}))
        self.assertEqual(regie.faehig({"preset": "libra"})["stile"], regie.STILE)
        caps = regie.faehig({"regie": {"stile": ["warm"], "tags": ["<sigh>"]}})
        self.assertEqual(caps["tempi"], ["slow", "fast"])
        self.assertIsNone(regie.vereinigen([None, None]))


class RegieWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeLibra)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = {k: os.environ.get(k) for k in ("STORY_WORLDS_DIR", "STORY_CONFIG")}
        os.environ["STORY_WORLDS_DIR"] = self.tmp.name
        os.environ["STORY_CONFIG"] = os.path.join(self.tmp.name, "c.json")
        FakeLibra.requests.clear()
        self.slug = worlds.create_world("Regie")
        with worlds.open_world(self.slug) as conn:
            conn.execute("INSERT INTO threads (id, level, world_time_cursor, title) VALUES (1, 'mikro', 0, 'S')")
            conn.execute("INSERT INTO episodes (id, release_nr, thread_id, world_start, world_end, type, title, text, status) "
                         "VALUES (1, 1, 1, 0, 1, 'gegenwart', 'Hangar', ?, 'fertig')", (TEXT,))

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _server(self):
        sid = tts.add_server({"preset": "libra", "base_url": self.url})
        self.assertTrue(tts.verify(sid)["regie"])
        return sid

    KI = {"absaetze": [{"nr": 1, "stil": "calm", "tempo": "slow",                      # Tempo wird ignoriert
                        "text": "Iva, 23, sitzt allein im Hangar. [documentary] Die Lampen flackern."},
                       {"nr": 2, "stil": "sad", "tempo": None, "text": "<sigh> Na toll. Schon wieder kaputt."},
                       {"nr": 3, "stil": "erfunden", "tempo": "fast", "text": "Ich hab's dir NICHT gesagt!"}]}

    def test_erzeugen_pruefen_speichern_veralten(self):
        ki = fake_ki([self.KI])
        with worlds.open_world(self.slug) as conn:
            data = regie.erzeugen(conn, 1, "dezent", complete=ki)
            self.assertEqual(ki.calls[0][1], "regie")
            sent = json.loads(ki.calls[0][0][1]["content"])
            self.assertEqual([a["art"] for a in sent["absaetze"]], ["erzaehler", "figur", "figur"])
            self.assertEqual(data["segmente"][0], {"stil": "calm",
                                                   "text": "Iva, 23, sitzt allein im Hangar. [documentary] Die Lampen flackern."})
            self.assertEqual(data["segmente"][1]["text"], "<sigh> Na toll. Schon wieder kaputt.")
            self.assertEqual(data["segmente"][2], {"stil": None, "text": None})  # Stil unbekannt, Wortlaut geändert
            self.assertIsNotNone(regie.gueltig(conn, 1))
            summary = regie.zusammenfassung(conn, 1)
            self.assertEqual((summary["stile"], summary["geraeusche"], summary["wechsel"]), (2, 1, 1))
            text = conn.execute("SELECT text FROM episodes WHERE id = 1").fetchone()[0]
            self.assertNotIn("<sigh>", text)                    # Folgentext bleibt unberührt
            conn.execute("UPDATE episodes SET text = ? WHERE id = 1", (TEXT + " Wirklich.",))
            self.assertIsNone(regie.gueltig(conn, 1))
            self.assertTrue(regie.zusammenfassung(conn, 1)["veraltet"])

    def test_abschnitt_scheitert_bleibt_neutral(self):
        with mock.patch.object(regie, "BATCH_SEGMENTS", 2):
            ki = fake_ki([RuntimeError("Modell weg"), {"absaetze": [{"nr": 3, "stil": "excited"}]}])
            with worlds.open_world(self.slug) as conn:
                data = regie.erzeugen(conn, 1, "lebendig", complete=ki)
        self.assertEqual(len(ki.calls), 2)
        self.assertEqual([s["stil"] for s in data["segmente"]], [None, None, "excited"])
        self.assertEqual(data["fehler"], 1)
        with worlds.open_world(self.slug) as conn, self.assertRaises(regie.RegieError):
            regie.erzeugen(conn, 1, "dezent", complete=fake_ki([RuntimeError("aus")]))

    def test_atmer_nach_ki(self):
        long = "[Erzähler] " + " ".join(f"Satz Nummer {i} erzählt ruhig etwas über den langen Weg durch den Hangar." for i in range(12))
        with worlds.open_world(self.slug) as conn:
            conn.execute("UPDATE episodes SET text = ? WHERE id = 1", (long + "\n\n[Iva] Na toll.",))
            data = regie.erzeugen(conn, 1, "dezent", complete=fake_ki([{"absaetze": []}]))
            self.assertGreaterEqual(data["segmente"][0]["text"].count("<breath>"), 2)
            self.assertIsNone(data["segmente"][1]["text"])
            self.assertGreaterEqual(regie.zusammenfassung(conn, 1)["atmer"], 2)

    def test_autospeichern_parallel(self):
        def save(nr, stil):
            with worlds.open_world(self.slug) as conn:
                regie.setzen(conn, 1, [{"nr": nr, "stil": stil}])
        threads = [threading.Thread(target=save, args=(n, st)) for n, st in ((1, "calm"), (2, "sad"), (3, "excited"))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        with worlds.open_world(self.slug) as conn:
            self.assertEqual([x["stil"] for x in regie.lesen(conn, 1)["segmente"]], ["calm", "sad", "excited"])

    def test_von_hand(self):
        with worlds.open_world(self.slug) as conn:
            data = regie.setzen(conn, 1, [{"nr": 3, "stil": "excited", "tempo": "fast", "text": "Ich hab's dir <laugh> gesagt!"}])
            self.assertTrue(data["bearbeitet"])
            self.assertEqual(data["segmente"][2]["tempo"], "fast")         # von Hand gesetzt: bleibt
            with self.assertRaises(ValueError):
                regie.setzen(conn, 1, [{"nr": 3, "tempo": "schnell"}])
            data = regie.setzen(conn, 1, [{"nr": 1, "text": "Iva, 23, sitzt allein im Hangar. [documentary] Die Lampen flackern."}])
            self.assertIn("[documentary]", data["segmente"][0]["text"])
            data = regie.setzen(conn, 1, [{"nr": 1, "text": "Iva, 23, sitzt  allein im Hangar. Die Lampen flackern."}])
            self.assertIsNone(data["segmente"][0]["text"])                 # gleich dem Original = keine Regie
            with self.assertRaises(ValueError):
                regie.setzen(conn, 1, [{"nr": 1, "text": "Iva, 23, sitzt allein im Hangar. [wütend] Die Lampen flackern."}])
            self.assertEqual(data["segmente"][2]["text"], "Ich hab's dir <laugh> gesagt!")
            # Von Hand umformulieren ist erlaubt – gilt nur fürs Hörspiel
            data = regie.setzen(conn, 1, [{"nr": 2, "text": "Na super. <sigh> Wieder kaputt."}])
            self.assertEqual(data["segmente"][1]["text"], "Na super. <sigh> Wieder kaputt.")
            self.assertTrue(regie.ansicht(conn, 1, None)["segmente"][1]["umformuliert"])
            self.assertNotIn("super", conn.execute("SELECT text FROM episodes WHERE id = 1").fetchone()[0])
            data = regie.setzen(conn, 1, [{"nr": 2, "text": ""}])                     # leer = wieder Original
            self.assertIsNone(data["segmente"][1]["text"])
            with self.assertRaises(ValueError):
                regie.setzen(conn, 1, [{"nr": 2, "stil": "wütend"}])
            with self.assertRaises(ValueError):
                regie.setzen(conn, 1, [{"nr": 2, "text": "<boom> Na toll. Schon wieder kaputt."}])
            view = regie.ansicht(conn, 1, None)
            self.assertEqual(view["segmente"][2]["sprechtext"], "Ich hab's dir <laugh> gesagt!")
            self.assertEqual(view["segmente"][1]["sprechtext"], "Na toll. Schon wieder kaputt.")  # immer editierbar gefüllt
            # bearbeitete Regie wird beim Vertonen nicht von der KI überschrieben
            ki = fake_ki([self.KI])
            kept = regie.sicherstellen(conn, 1, "lebendig", regie.faehig({"preset": "libra"}), complete=ki)
            self.assertEqual(ki.calls, [])
            self.assertEqual(kept["segmente"][2]["stil"], "excited")

    def test_vertonen_mit_stil_und_geraeuschen(self):
        sid = self._server()
        with worlds.open_world(self.slug) as conn:
            tts.set_cast(conn, {"Erzähler": f"{sid}|nina"})
            conn.commit()
            with mock.patch.object(llm, "complete", fake_ki([self.KI])):
                path = tts.render(conn, self.slug, 1, as_mp3=False)
        self.assertTrue(path.exists())
        by_text = {r["input"]: r for r in FakeLibra.requests}
        self.assertEqual(by_text["<sigh> Na toll. Schon wieder kaputt."]["style"], "sad")
        self.assertTrue(all("pace" not in r for r in FakeLibra.requests))     # nie ein Tempo
        self.assertEqual((by_text["Iva, 23, sitzt allein im Hangar."]["style"], by_text["Die Lampen flackern."]["style"]),
                         ("calm", "documentary"))                             # Stilwechsel im Absatz = zwei Anfragen
        self.assertEqual(by_text["Die Lampen flackern."]["voice"], "nina")
        intro = next(r for r in FakeLibra.requests if r["input"].startswith("Folge 1"))
        self.assertNotIn("style", intro)
        ole = next(r for r in FakeLibra.requests if r["input"].startswith("Ich hab"))
        self.assertNotIn("style", ole)
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(meta["regie"]["geraeusche"], 1)
        self.assertEqual([(g["text"], g["stil"]) for g in meta["segmente"]][1:],
                         [("<sigh> Na toll. Schon wieder kaputt.", "sad"), ("Ich hab's dir gesagt!", None)])
        self.assertEqual(meta["segmente"][0]["teile"], [{"text": "Iva, 23, sitzt allein im Hangar.", "stil": "calm"},
                                                        {"text": "Die Lampen flackern.", "stil": "documentary"}])
        self.assertTrue(all("tempo" not in g for g in meta["segmente"]))

        # Tempo von Hand: geht als pace mit (KI-Tempo „slow“ für Absatz 1 wurde ignoriert)
        FakeLibra.requests.clear()
        with worlds.open_world(self.slug) as conn:
            regie.setzen(conn, 1, [{"nr": 2, "tempo": "slow"}])
            tts.render(conn, self.slug, 1, as_mp3=False)
            regie.setzen(conn, 1, [{"nr": 2, "tempo": ""}])               # zurück auf normal
        self.assertEqual([(r["input"], r.get("pace"), r.get("style")) for r in FakeLibra.requests],
                         [("<sigh> Na toll. Schon wieder kaputt.", "slow", "sad")])

        # Einzelner Absatz: anhören (aus dem Zwischenspeicher), neuer Take, Take tauschen – erst render fügt zusammen
        FakeLibra.requests.clear()
        with worlds.open_world(self.slug) as conn:
            first = tts.segment_take(conn, self.slug, 1, 2)
            self.assertEqual(FakeLibra.requests, [])                           # schon gesprochen
            self.assertTrue(tts.segment_file(self.slug, 1, first["datei"]).is_file())
            new = tts.segment_take(conn, self.slug, 1, 2, neu=True)
            self.assertEqual((new["take"], new["gewaehlt"], new["takes"]), (1, 1, [0, 1]))
            self.assertEqual([(r["input"], r.get("seed")) for r in FakeLibra.requests],
                             [("<sigh> Na toll. Schon wieder kaputt.", 1)])       # nur dieser Absatz, neuer Seed
            self.assertNotEqual(first["datei"], new["datei"])
            self.assertTrue(tts.segment_file(self.slug, 1, first["datei"]).is_file())  # alter Take bleibt
            FakeLibra.requests.clear()
            tts.render(conn, self.slug, 1, as_mp3=False)
            self.assertEqual(FakeLibra.requests, [])                           # Zusammenfügen: alles aus dem Speicher
            back = tts.segment_take(conn, self.slug, 1, 2, take=0, waehlen=True)
            self.assertEqual((back["take"], back["gewaehlt"], back["datei"]), (0, 0, first["datei"]))
            self.assertEqual(regie.ansicht(conn, 1, None)["segmente"][1]["takes"], [0, 1])
            with self.assertRaises(ValueError):
                tts.segment_take(conn, self.slug, 1, 2, take=7, waehlen=True)
            with self.assertRaises(LookupError):
                tts.segment_file(self.slug, 1, "../c.json")

        # Stufe „aus“: neutral, Cache-Treffer für unveränderte Stücke, keine Stil-Felder
        FakeLibra.requests.clear()
        with worlds.open_world(self.slug) as conn:
            tts.set_episode_settings(conn, 1, {"regie": "aus"})
            conn.commit()
            tts.render(conn, self.slug, 1, as_mp3=False)
        self.assertTrue(FakeLibra.requests)
        self.assertTrue(all("style" not in r and "<" not in r["input"] for r in FakeLibra.requests))

        # JSON-Export trägt Stil und Sprechtext je Segment
        with worlds.open_world(self.slug) as conn:
            exp = audio.export_json(conn, 1)
        self.assertEqual(exp["segmente"][1]["stil"], "sad")
        self.assertEqual(exp["segmente"][1]["text"], "<sigh> Na toll. Schon wieder kaputt.")
        self.assertEqual(exp["segmente"][0]["stil"], "calm")
        self.assertEqual(exp["segmente"][0]["text"], "Iva, 23, sitzt allein im Hangar. Die Lampen flackern.")
        self.assertEqual(exp["segmente"][2]["text"], "Ich hab's dir gesagt!")
        with worlds.open_world(self.slug) as conn:            # Anzeige/Kanon: Folgentext ohne Tags
            shown = conn.execute("SELECT text FROM episodes WHERE id = 1").fetchone()[0]
        self.assertNotIn("<", shown)

    def test_alter_eigener_server_wird_nachtraeglich_erkannt(self):
        """Vor der Regie eingetragener „eigener Server“ ohne Feld regie: beim Vertonen einmal nachfragen."""
        sid = tts.add_server({"preset": "custom", "base_url": self.url + "/v1"})
        tts.verify(sid)
        tts._set_state(sid, regie=None)
        cfg = tts._cfg()
        for x in cfg["tts_server"]:
            x.pop("regie", None)
        from story_world import providers
        providers.save(cfg)
        self.assertNotIn("regie", tts.get_server(sid))
        with worlds.open_world(self.slug) as conn:
            tts.set_cast(conn, {"Erzähler": f"{sid}|nina"})
            conn.commit()
            with mock.patch.object(llm, "complete", fake_ki([self.KI])):
                tts.render(conn, self.slug, 1, as_mp3=False)
        self.assertEqual(tts.get_server(sid)["regie"]["stile"], regie.STILE)
        self.assertTrue(any(r.get("style") == "sad" and r["input"].startswith("<sigh>") for r in FakeLibra.requests))

    def test_umformuliert_nur_im_hoerspiel(self):
        sid = self._server()
        with worlds.open_world(self.slug) as conn:
            tts.set_cast(conn, {"Erzähler": f"{sid}|nina"})
            tts.set_episode_settings(conn, 1, {"regie": "dezent"})
            conn.commit()
            regie.setzen(conn, 1, [{"nr": 2, "stil": "sad", "text": "Na super. <sigh> Wieder alles kaputt."}])
            path = tts.render(conn, self.slug, 1, as_mp3=False)
            exp = audio.export_json(conn, 1)
            shown = conn.execute("SELECT text FROM episodes WHERE id = 1").fetchone()[0]
        self.assertTrue(any(r["input"] == "Na super. <sigh> Wieder alles kaputt." and r.get("style") == "sad"
                            for r in FakeLibra.requests))
        self.assertEqual((exp["segmente"][1]["text"], exp["segmente"][1]["originaltext"]),
                         ("Na super. <sigh> Wieder alles kaputt.", "Na toll. Schon wieder kaputt."))
        self.assertNotIn("originaltext", exp["segmente"][0])
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        self.assertEqual(meta["segmente"][1]["originaltext"], "Na toll. Schon wieder kaputt.")
        self.assertIn("Na toll. Schon wieder kaputt.", shown)                    # Anzeige/Kanon unverändert

    def test_ohne_ki_wird_neutral_vertont(self):
        sid = self._server()
        with worlds.open_world(self.slug) as conn:
            tts.set_cast(conn, {"Erzähler": f"{sid}|nina"})
            conn.commit()
            path = tts.render(conn, self.slug, 1, as_mp3=False)    # keine KI eingerichtet
        self.assertTrue(path.exists())
        self.assertTrue(all("style" not in r for r in FakeLibra.requests))

    def test_server_ohne_regie_bekommt_keine_tags(self):
        plain = {"preset": "custom", "typ": "openai"}
        data = {"segmente": [{"stil": "sad", "tempo": "slow", "take": 2, "text": "<sigh> Hallo. [warm] Schön."}]}
        self.assertEqual(regie.teile_fuer_segment(data, 0, plain, "Hallo. Schön."), [("Hallo. Schön.", {})])
        limited = {"regie": {"stile": ["warm"], "tempi": ["slow"], "tags": ["<laugh>"]}}
        self.assertEqual(regie.teile_fuer_segment(data, 0, limited, "Hallo. Schön."),   # Version 1: KI-Tempo ignoriert
                         [("Hallo.", {"seed": 2}), ("Schön.", {"style": "warm", "seed": 2})])
        data["version"] = 2                                                             # von Hand gesetzt: gilt
        self.assertEqual(regie.teile_fuer_segment(data, 0, limited, "Hallo. Schön."),
                         [("Hallo.", {"seed": 2, "pace": "slow"}), ("Schön.", {"style": "warm", "seed": 2, "pace": "slow"})])
        self.assertEqual(regie.teile_fuer_segment(data, 0, limited, "Hallo. Schön.", nur_take=True),
                         [("Hallo. Schön.", {"seed": 2})])


if __name__ == "__main__":
    unittest.main()
