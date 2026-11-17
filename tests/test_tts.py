"""TTS-Server: Konfiguration, Stimmen laden, Besetzung, Hörspiel/Hörbuch, Zerlegen, Vertonen, JSON-Export."""

import json
import math
import os
import struct
import sys
import tempfile
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from story_world import audio, mp3, service, tts, worlds  # noqa: E402

RATE = 24000


def wav_int16_streaming(seconds: float) -> bytes:
    """Wie Phonon: Längenfelder 0xFFFFFFFF."""
    n = int(RATE * seconds)
    pcm = struct.pack(f"<{n}h", *(int(8000 * math.sin(i / 10)) for i in range(n)))
    fmt = struct.pack("<HHIIHH", 1, 1, RATE, RATE * 2, 2, 16)
    return b"RIFF\xff\xff\xff\xffWAVEfmt " + struct.pack("<I", 16) + fmt + b"data\xff\xff\xff\xff" + pcm


def wav_float32(seconds: float, rate: int = RATE) -> bytes:
    """Wie Pocket TTS: Float32 mit fact-Block."""
    n = int(rate * seconds)
    pcm = struct.pack(f"<{n}f", *(0.25 for _ in range(n)))
    fmt = struct.pack("<HHIIHH", 3, 1, rate, rate * 4, 4, 32)
    body = b"WAVEfmt " + struct.pack("<I", 16) + fmt + b"fact" + struct.pack("<II", 4, n) + b"data" + struct.pack("<I", len(pcm)) + pcm
    return b"RIFF" + struct.pack("<I", len(body)) + body


class FakeTTS(BaseHTTPRequestHandler):
    requests: list = []

    def log_message(self, *a):
        pass

    def _json(self, payload, code=200):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/v1/audio/voices":
            return self._json({"voices": ["Anton", "Jette", "Leon", "default", "Alfie"],
                               "by_language": {"de": ["Anton", "Jette", "Leon", "default"], "en": ["Alfie", "default"]},
                               "details_by_language": {"de": [{"id": "Anton", "language": "de", "gender": "male"},
                                                              {"id": "Jette", "language": "de", "gender": "female"},
                                                              {"id": "Leon", "language": "de", "gender": "male"}],
                                                       "en": [{"id": "Alfie", "language": "en", "gender": "male"}]}})
        if self.path == "/v1/models":
            return self._json({"data": [{"id": "gradium/phonon-40m-multilingual"}]})
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeTTS.requests.append(body)
        if len(body["input"]) > 120:
            return self._json({"error": "zu lang"}, 400)
        data = wav_int16_streaming(0.1) if body["voice"] != "Jette" else wav_float32(0.1)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.end_headers()
        self.wfile.write(data)


class TTSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeTTS)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}/"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = {k: os.environ.get(k) for k in ("STORY_WORLDS_DIR", "STORY_CONFIG")}
        os.environ["STORY_WORLDS_DIR"] = self.tmp.name
        os.environ["STORY_CONFIG"] = os.path.join(self.tmp.name, "c.json")
        FakeTTS.requests.clear()

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _world(self):
        slug = worlds.create_world("TTS")
        with worlds.open_world(slug) as conn:
            conn.execute("INSERT INTO threads (id, level, world_time_cursor, title) VALUES (1, 'mikro', 0, 'S')")
            conn.execute("INSERT INTO episodes (id, release_nr, thread_id, world_start, world_end, type, title, text, status) "
                         "VALUES (1, 1, 1, 0, 1, 'gegenwart', 'Probe', ?, 'fertig')",
                         ("[Erzähler] Die Aureas landen. " + "Es ist ein langer Satz über den Aufzug. " * 5
                          + "\n\n[Tavi] Hallo Aureas.\n\n[Ole] Moin.",))
            service.create_row(conn, "pronunciations", {"term": "Aureas", "spoken": "Ah-u-re-as"})
        return slug

    def test_lexicon_variants_case_language_ipa(self):
        from story_world import audio
        slug = worlds.create_world("Lexikon")
        with worlds.open_world(slug) as conn:
            service.create_row(conn, "pronunciations", {"term": "Warp Blase", "spoken": "Woarp Blaase",
                                                        "variants": "Warp-Blase, Warpblasen", "ignore_case": "on",
                                                        "language": "en", "ipa": ""})
            service.create_row(conn, "pronunciations", {"term": "Aureas", "spoken": "Ah-u-re-as", "ipa": "aʊˈʁeːas"})
            words = audio.lexicon(conn)
        text = "Die warp blase hält. Zwei Warpblasen, eine Warp-Blase & mehr. Aureas! Aureasse bleibt."
        self.assertEqual(audio.apply_lexicon(text, words),
                         "Die Woarp Blaase hält. Zwei Woarp Blaase, eine Woarp Blaase & mehr. Ah-u-re-as! Aureasse bleibt.")
        tokens = audio.apply_lexicon(text, words, ssml=True)
        chunks = tts.chunk_text(tokens, 60)
        self.assertTrue(all(c.count("\uE000") == c.count("\uE001") for c in chunks))   # Platzhalter nie zerteilt
        ssml = " ".join(audio.to_ssml(c) for c in chunks)
        self.assertIn("<lang xml:lang='en-US'>warp blase</lang>", ssml)               # Originalschreibweise bleibt
        self.assertIn("<lang xml:lang='en-US'>Warpblasen</lang>", ssml)
        self.assertIn("<phoneme alphabet='ipa' ph='aʊˈʁeːas'>Aureas</phoneme>", ssml)
        self.assertIn("&amp; mehr", ssml)
        plain = audio.to_ssml(tokens, allow_lang=False)                                  # Stimme ohne Sprachwechsel
        self.assertIn("Woarp Blaase", plain)
        self.assertNotIn("<lang", plain)
        self.assertIn("<phoneme", plain)
        self.assertEqual(audio.locale("en-gb"), "en-GB")
        self.assertIsNone(audio.locale("englisch"))

    def test_decode_formats_and_chunking(self):
        rate, s16 = tts.decode_wav(wav_int16_streaming(0.5))
        self.assertEqual((rate, len(s16)), (RATE, RATE // 2))
        rate, f32 = tts.decode_wav(wav_float32(0.5, 22050))
        self.assertEqual((rate, len(f32)), (22050, 11025))
        self.assertEqual(f32[0], int(32767 * 0.25))
        self.assertEqual(len(tts.resample(f32, 22050, RATE)), RATE // 2)
        text = "Erster Satz ist hier. " * 30 + "Ein " + "sehr " * 80 + "langer Satz, ohne Ende"
        chunks = tts.chunk_text(text, 100)
        self.assertTrue(all(len(c) <= 100 for c in chunks))
        self.assertEqual(" ".join(chunks).split(), text.split())

    def test_server_voices_cast_modes_render_and_export(self):
        sid = tts.add_server({"name": "Phonon", "typ": "openai", "base_url": self.url, "max_zeichen": 120})
        self.assertEqual(tts.get_server(sid)["base_url"], self.url.rstrip("/"))
        result = tts.verify(sid)
        self.assertTrue(result["ok"], result)
        server = tts.get_server(sid)
        self.assertEqual(server["modell"], "gradium/phonon-40m-multilingual")
        self.assertEqual({v["id"]: v["sprache"] for v in server["stimmen"]}["Alfie"], "en")
        slug = self._world()
        with worlds.open_world(slug) as conn:
            p = tts.plan(conn, 1)
            self.assertEqual(p["fehlt"], ["Erzähler", "Tavi", "Ole"])        # ohne Erzähler-Stimme keine Vertonung
            tts.set_cast(conn, {"Erzähler": f"{sid}|Anton", "Ole": f"{sid}|Jette"})
            p = tts.plan(conn, 1)
            self.assertEqual(p["fehlt"], [])
            self.assertEqual(p["sprecher"]["Tavi"]["stimme"], "Leon")         # automatisch: gleiche Sprache, frei
            self.assertEqual(p["sprecher"]["Tavi"]["quelle"], "automatisch")
            self.assertEqual(p["sprecher"]["Ole"]["stimme"], "Jette")
            self.assertEqual(p["sprecher"]["Erzähler"]["sprache"], "de")

            path = tts.render(conn, slug, 1, as_mp3=False)
            self.assertTrue(path.exists())
            with wave.open(str(path), "rb") as w:
                self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (RATE, 1, 2))
                self.assertGreater(w.getnframes(), RATE * 0.5)
            sent = [r for r in FakeTTS.requests]
            self.assertTrue(all(len(r["input"]) <= 120 for r in sent))          # zerlegt
            self.assertTrue(any("Ah-u-re-as" in r["input"] for r in sent))      # Aussprache-Lexikon
            self.assertTrue(all(r["language"] == "de" and r["response_format"] == "wav" for r in sent))
            self.assertTrue(path.with_suffix(".json").exists())

            calls = len(FakeTTS.requests)
            tts.render(conn, slug, 1, as_mp3=False)                              # Zwischenspeicher: keine neuen Aufrufe
            self.assertEqual(len(FakeTTS.requests), calls)
            self.assertEqual(len(list((path.parent / "_alt").glob("*.wav"))), 1)  # altes Ergebnis beiseitegelegt

            if mp3.available():                                                  # MP3 mit ID3-Tags, WAV nach _wav
                out = tts.render(conn, slug, 1)
                self.assertEqual(out.suffix, ".mp3")
                self.assertEqual(tts.output_file(conn, slug, 1), out)
                self.assertTrue((path.parent / "_wav" / path.name).exists())
                tags = mp3.read_tags(out)
                self.assertTrue(tags["TIT2"].startswith("Folge 1"))
                self.assertEqual(tags["TCON"], "Hörspiel")
                self.assertIn("Anton", tags["TPE1"])

            tts.set_episode_settings(conn, 1, {"modus": "hoerbuch", "stimme": f"{sid}|Jette"})
            p = tts.plan(conn, 1)
            self.assertEqual({v["stimme"] for v in p["sprecher"].values()}, {"Jette"})
            data = audio.export_json(conn, 1)
            self.assertEqual(data["quelle"], "tts-server")
            self.assertEqual(data["modus"], "hoerbuch")
            self.assertEqual({s["stimme"] for s in data["segmente"]}, {"Jette"})
            self.assertEqual(data["server"][sid]["url"], self.url.rstrip("/"))
            self.assertNotIn("api_key", json.dumps(data))

        tts.archive_server(sid)
        self.assertEqual(tts.servers(), [])
        tts.restore_server(sid)
        self.assertEqual(len(tts.servers()), 1)

    def test_unreachable_server_is_reported(self):
        sid = tts.add_server({"name": "weg", "base_url": "http://127.0.0.1:9/"})
        result = tts.verify(sid)
        self.assertFalse(result["ok"])
        self.assertEqual(tts.get_server(sid)["status"], "fehler")


class FakeCloud(BaseHTTPRequestHandler):
    """Antwortet wie ElevenLabs (xi-api-key, PCM) und OpenAI (Bearer, feste Stimmen)."""
    requests: list = []

    def log_message(self, *a):
        pass

    def _send(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/v1/voices" and self.headers.get("xi-api-key") == "EL":
            return self._send(200, json.dumps({"voices": [{"voice_id": "v1", "name": "Rachel", "category": "premade",
                                                           "labels": {"gender": "female"}}]}).encode(), "application/json")
        if self.path == "/v1/models" and self.headers.get("xi-api-key") == "EL":
            return self._send(200, json.dumps([{"model_id": "eleven_multilingual_v2", "can_do_text_to_speech": True}]).encode(),
                              "application/json")
        if self.path == "/v1/models" and self.headers.get("Authorization") == "Bearer OA":
            return self._send(200, json.dumps({"data": [{"id": "gpt-4o-mini-tts"}, {"id": "gpt-5"}]}).encode(), "application/json")
        self._send(401, b'{"detail": "invalid key"}', "application/json")

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeCloud.requests.append((self.path, body))
        if self.path.startswith("/v1/text-to-speech/v1?output_format=pcm_24000"):
            return self._send(200, struct.pack("<2400h", *([1000] * 2400)), "audio/pcm")
        if self.path == "/v1/audio/speech":
            return self._send(200, wav_int16_streaming(0.1), "audio/wav")
        self._send(404, b"{}", "application/json")


class PresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeCloud)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("STORY_CONFIG")
        os.environ["STORY_CONFIG"] = os.path.join(self.tmp.name, "c.json")
        FakeCloud.requests.clear()

    def tearDown(self):
        if self.old is None:
            os.environ.pop("STORY_CONFIG", None)
        else:
            os.environ["STORY_CONFIG"] = self.old
        self.tmp.cleanup()

    def test_preset_defaults_and_missing_key(self):
        sid = tts.add_server({"preset": "elevenlabs"})
        s = tts.get_server(sid)
        self.assertEqual((s["typ"], s["base_url"], s["name"], s["modell"]),
                         ("elevenlabs", "https://api.elevenlabs.io", "ElevenLabs", "eleven_multilingual_v2"))
        result = tts.verify(sid)
        self.assertFalse(result["ok"])
        self.assertIn("Schlüssel", result["fehler"])
        self.assertIn("presets", tts.public_settings())

    def test_elevenlabs_voices_and_pcm_to_wav(self):
        sid = tts.add_server({"preset": "elevenlabs", "base_url": self.url, "api_key": "EL"})
        self.assertTrue(tts.verify(sid)["ok"])
        s = tts.get_server(sid)
        self.assertEqual(s["stimmen"][0]["id"], "v1")
        self.assertEqual(s["stimmen"][0]["geschlecht"], "female")
        self.assertEqual(s["modelle"], ["eleven_multilingual_v2"])
        rate, samples = tts.decode_wav(tts.synth(s, "Hallo", "v1", None))
        self.assertEqual((rate, len(samples)), (24000, 2400))
        self.assertEqual(FakeCloud.requests[-1][1], {"text": "Hallo", "model_id": "eleven_multilingual_v2"})
        bad = tts.add_server({"preset": "elevenlabs", "base_url": self.url, "api_key": "falsch"})
        self.assertFalse(tts.verify(bad)["ok"])

    def test_openai_fixed_voices_without_language(self):
        sid = tts.add_server({"preset": "openai", "base_url": self.url, "api_key": "OA"})
        self.assertTrue(tts.verify(sid)["ok"])
        s = tts.get_server(sid)
        self.assertIn("nova", [v["id"] for v in s["stimmen"]])
        self.assertEqual(s["modelle"], ["gpt-4o-mini-tts"])
        tts.synth(s, "Hallo", "nova", "de")
        self.assertNotIn("language", FakeCloud.requests[-1][1])


if __name__ == "__main__":
    unittest.main()


class DramaturgyTests(unittest.TestCase):
    def test_plan_needs_opening_and_author_gets_it(self):
        from story_world import episodes
        plan = {"titel": "T", "strang": {"id": 1}, "typ": "gegenwart", "welt_start": 1, "welt_ende": 2,
                "kapitel": [{"teil": "ganz", "titel": "K", "inhalt": "x", "woerter": 500}], "vorbereitung": []}
        self.assertTrue(any("einstieg" in e for e in episodes._validate_plan(plan)))
        plan["einstieg"] = {"figur": "Iva", "wer": "23, gerade aus der Ausbildung", "gefuehl": "genervt",
                            "lage": "vom Vater vor die Tür gesetzt", "ort": "Küstenbasis"}
        self.assertEqual(episodes._validate_plan(plan), [])
        brief = episodes._opening_brief(plan)
        self.assertIn("Iva", brief)
        self.assertIn("genervt", brief)
        self.assertIn("ANFANG", episodes._style(object()))
