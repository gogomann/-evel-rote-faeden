"""Export/Import: Welt, Autor, alles – mit Profil-ID-Prüfung und verborgenen Basistexten."""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KEYS = ("STORY_WORLDS_DIR", "STORY_VOICES", "STORY_PROFILES", "STORY_PROFILE_TEXTS", "STORY_EXPORTS", "STORY_CONFIG")
OWN = ("Mara zählte die Lichter über dem Meer. EIGENER-STIL-SATZ hält inne. " * 80).strip()


class AustauschTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = {k: os.environ.get(k) for k in KEYS}

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def machine(self, name):
        base = Path(self.tmp.name) / name
        for key, sub in zip(KEYS, ("welten", "stimmen.json", "profiles.json", "texte", "exporte", "c.json")):
            os.environ[key] = str(base / sub)
        base.mkdir(parents=True, exist_ok=True)
        return base

    def build_source(self):
        from story_world import profiles, runs, service, stimmen, worlds
        self.machine("A")
        p = profiles.create("Ralf")
        own = profiles.add_text(p["id"], "Eigenes", OWN)
        foreign = profiles.add_text(p["id"], "children of sol", "FREMDTEXT " * 300, fremd=True, autor="u/someone")
        self.assertFalse(foreign["stil"])
        voice = stimmen.create({"art": "mensch", "profil_id": p["id"]})
        self.assertEqual(voice["texte"], [own["id"]])  # fremder Text ist keine Basis
        slug = worlds.create_world("Alpha")
        with worlds.open_world(slug) as conn:
            service.set_setting(conn, "stimme", voice["id"])
            done = service.create_impulse(conn, "Eigenes – Teil 1/2", "GEHEIMTEXT-EINS", "text")
            open_ = service.create_impulse(conn, "Eigenes – Teil 2/2", "GEHEIMTEXT-ZWEI", "text")
            conn.execute("UPDATE impulses SET besitzer = ?, quelle_text = ? WHERE id IN (?, ?)",
                         (p["id"], own["id"], done, open_))
            service.set_impulse_status(conn, done, "eingearbeitet")
            conn.commit()
            run = runs.Run(conn, "Text einlesen", "z", "weltenbau", "AUFTRAG GEHEIMTEXT-EINS", impulse_id=done)
            run.recorder("Weltenbau", "weltenbau")("m", [{"role": "user", "content": "GEHEIMTEXT-EINS"}],
                                                     "Antwort", None, 1.0)
            run.finish("fertig")
        return p, voice, slug

    def test_rundreise_fremder_und_gleicher_mensch(self):
        from story_world import austausch, stimmen, worlds
        p, voice, slug = self.build_source()
        world_zip = austausch.export_dir() / austausch.export_world(slug)["datei"]
        author_zip = austausch.export_dir() / austausch.export_author()["datei"]
        all_zip = austausch.export_dir() / austausch.export_all()["datei"]
        with zipfile.ZipFile(world_zip) as zf:
            names = zf.namelist()
            raw = b"".join(zf.read(n) for n in names if not n.endswith(".sqlite3"))
            self.assertNotIn(b"FREMDTEXT", raw)  # Volltexte gehen nicht in den Welt-Export
            exported = json.loads(zf.read("stimmen.json"))["stimmen"][0]
            self.assertIn("EIGENER-STIL-SATZ", exported["basis"]["anker"])
            db = Path(self.tmp.name) / "check.sqlite3"
            db.write_bytes(zf.read("welt.sqlite3"))
        conn = sqlite3.connect(db)
        contents = [r[0] for r in conn.execute("SELECT content FROM impulses WHERE kind = 'text' ORDER BY id")]
        self.assertNotIn("GEHEIMTEXT-EINS", " ".join(contents))  # eingearbeitet → ohne Inhalt
        self.assertIn("GEHEIMTEXT-ZWEI", " ".join(contents))  # offen → geht mit, damit es weitergeht
        self.assertNotIn("GEHEIMTEXT-EINS", conn.execute("SELECT auftrag FROM ai_runs").fetchone()[0])
        conn.close()

        # Rechner B, anderer Mensch: Basis und offene Text-Impulse verborgen, aber nutzbar
        self.machine("B")
        rep = austausch.import_package(world_zip)
        new_slug = rep["welten"][0]["slug"]
        v = stimmen.get(voice["id"])
        self.assertTrue(v["basis"]["verborgen"])
        self.assertNotIn("anker", stimmen.public(v)["basis"])
        block = stimmen.writer_block(v)
        self.assertIn("EIGENER-STIL-SATZ", block)  # die KI bekommt den Anker weiterhin
        self.assertNotIn("EIGENER-STIL-SATZ", stimmen.redact(block))  # die Anzeige nicht
        self.assertTrue(stimmen.reference_text(v))
        with worlds.open_world(new_slug) as conn:
            row = conn.execute("SELECT content, content_verborgen FROM impulses WHERE title LIKE '%2/2'").fetchone()
            self.assertNotIn("GEHEIMTEXT-ZWEI", row[0])
            self.assertIn("GEHEIMTEXT-ZWEI", row[1])
            self.assertEqual(stimmen.resolve(conn, None, None)[1], "Welt")
        # Derselbe Mensch kommt per Autor-Import dazu → alles wird sichtbar
        rep = austausch.import_package(author_zip)
        self.assertGreaterEqual(rep["autor"]["freigeschaltet"], 2)
        self.assertFalse(stimmen.get(voice["id"])["basis"]["verborgen"])
        with worlds.open_world(new_slug) as conn:
            self.assertIn("GEHEIMTEXT-ZWEI", conn.execute(
                "SELECT content FROM impulses WHERE title LIKE '%2/2'").fetchone()[0])

        # Rechner C: „alles“ → Autor zuerst, daher sofort sichtbar
        self.machine("C")
        rep = austausch.import_package(all_zip)
        self.assertEqual(rep["typ"], "alles")
        self.assertFalse(stimmen.get(voice["id"]).get("basis", {}).get("verborgen", False))
        with worlds.open_world(rep["welten"][0]["slug"]) as conn:
            self.assertIn("GEHEIMTEXT-ZWEI", conn.execute(
                "SELECT content FROM impulses WHERE title LIKE '%2/2'").fetchone()[0])

        # Gleicher Rechner: Import legt eine neue Welt an, überschreibt nichts
        self.machine("A")
        rep = austausch.import_package(world_zip)
        self.assertNotEqual(rep["welten"][0]["slug"], slug)
        self.assertEqual(rep["welten"][0]["stimmen"], {"vorhanden": 1})

    def test_unsichere_datei_wird_abgelehnt(self):
        from story_world import austausch
        self.machine("X")
        bad = Path(self.tmp.name) / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("../evil.txt", "x")
        with self.assertRaises(austausch.ExchangeError):
            austausch.import_package(bad)


if __name__ == "__main__":
    unittest.main()
