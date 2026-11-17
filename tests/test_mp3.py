"""MP3-Export: ID3v2.3-Tags schreiben/lesen, Tags entfernen, Kodieren (nur mit lame/ffmpeg)."""

import sqlite3
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from story_world import mp3  # noqa: E402

TAGS = {"titel": "Folge 3: Ankunft auf Sool", "album": "Sool – Hauptstrang", "album_interpret": "Sool",
        "interpret": "Anna, Markus", "track": 3, "jahr": "2026", "genre": "Hörspiel", "sprache": "deu",
        "kommentar": "Iva, 23, genervt, landet.", "encoder": "Evel • Rote Fäden"}


def _wav(path: Path, seconds: float = 1.0, rate: int = 22050) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00\xf0\xff" * int(rate * seconds / 2))
    return path


class TestID3(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.mp3"
            path.write_bytes(mp3.id3v23(TAGS) + b"\xff\xfb\x90\x00")
            tags = mp3.read_tags(path)
        self.assertEqual(tags["TIT2"], TAGS["titel"])
        self.assertEqual(tags["TALB"], TAGS["album"])
        self.assertEqual(tags["TPE1"], "Anna, Markus")
        self.assertEqual(tags["TRCK"], "3")
        self.assertEqual(tags["TCON"], "Hörspiel")
        self.assertEqual(tags["COMM"], TAGS["kommentar"])

    def test_strip(self):
        audio = b"\xff\xfb\x90\x00" * 10
        self.assertEqual(mp3.strip_tags(mp3.id3v23({"titel": "a"}) + audio + b"TAG" + b"\x00" * 125), audio)

    def test_episode_tags(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE world_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO world_meta VALUES ('name', 'Sool')")
        ep = {"release_nr": 4, "title": "Ankunft", "form": "folge", "strang": "Hauptstrang", "genre": "Sci-Fi",
              "summary": "Kurz."}
        tags = mp3.episode_tags(conn, ep, ["Anna", "Markus", "Anna", ""], "hoerbuch")
        self.assertEqual(tags["titel"], "Folge 4: Ankunft")
        self.assertEqual(tags["album"], "Sool – Hauptstrang")
        self.assertEqual(tags["interpret"], "Anna, Markus")
        self.assertEqual(tags["genre"], "Hörbuch")
        self.assertEqual(mp3.episode_tags(conn, dict(ep, form="geschichte"))["titel"], "Ankunft")


@unittest.skipUnless(mp3.available(), "lame/ffmpeg nicht installiert")
class TestEncode(unittest.TestCase):
    def test_from_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav = _wav(Path(tmp) / "f.wav")
            target = Path(tmp) / "f.mp3"
            mp3.from_wav(wav, target, TAGS)
            data = target.read_bytes()
            self.assertEqual(data[:3], b"ID3")
            self.assertEqual(data.count(b"ID3\x03"), 1)                       # nur unser Tag
            tags = mp3.read_tags(target)
            self.assertEqual(tags["TIT2"], TAGS["titel"])
            self.assertAlmostEqual(int(tags["TLEN"]), 1000, delta=5)
            mp3.from_wav(wav, target, TAGS)                                   # zweites Mal: altes nach _alt
            self.assertEqual(len(list((Path(tmp) / "_alt").glob("*.mp3"))), 1)
            self.assertFalse(list(Path(tmp).glob("*.roh.mp3")) + list(Path(tmp).glob("*.teil.mp3")))


if __name__ == "__main__":
    unittest.main()
