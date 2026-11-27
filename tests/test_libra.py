"""Mitgelieferter Libra-TTS-Server: Update-Schutz, Nachinstallieren, Start/Stopp mit echtem (simuliertem) Server-Prozess,
automatischer Eintrag unter TTS-Server samt Stilen und Geräusch-Tags."""

import json
import os
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from story_world import libra, regie, tts, update  # noqa: E402

FAKE_SERVER = textwrap.dedent('''
    """Simulierter Libra-Server: /health, /v1/audio/voices (Stile, Tags), /v1/audio/speech (kurze WAV)."""
    import json, struct, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    port = int(sys.argv[sys.argv.index("--port") + 1])

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def _send(self, data, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            if self.path == "/health":
                return self._send(json.dumps({"status": "ok", "backend": "onnx", "sample_rate": 24000}).encode(), "application/json")
            if self.path == "/v1/audio/voices":
                return self._send(json.dumps({"voices": [{"id": "nina", "name": "Nina", "gender": "female"},
                                                         {"id": "bob", "name": "Bob", "gender": "male"}],
                                              "styles": ["warm", "sad", "whispering"], "paces": ["slow", "fast"],
                                              "tags": ["<sigh>", "<laugh>", "<short pause>"]}).encode(), "application/json")
            if self.path == "/v1/models":
                return self._send(json.dumps({"data": [{"id": "tts-1"}]}).encode(), "application/json")
            self.send_response(404); self.end_headers()
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            with open("anfragen.jsonl", "ab") as fh:
                fh.write(body + b"\\n")
            pcm = b"\\x00\\x00" * 2400
            fmt = struct.pack("<HHIIHH", 1, 1, 24000, 48000, 2, 16)
            wav = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(pcm)) + pcm
            self._send(wav, "audio/wav")

    HTTPServer(("127.0.0.1", port), H).serve_forever()
''')


class LibraTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.dir = base / "zusatz" / "libra-tts"
        (self.dir / "libra_tts").mkdir(parents=True)
        (self.dir / "web").mkdir()
        (self.dir / "server.py").write_text(FAKE_SERVER, encoding="utf-8")
        for name in ("installer.py", "download_model.py", "requirements.txt"):
            (self.dir / name).write_text(f"# {name}\n", encoding="utf-8")
        (self.dir / "web" / "index.html").write_text("<html></html>", encoding="utf-8")
        self.patches = [mock.patch.object(libra, "DIR", self.dir), mock.patch.object(libra, "STATE_DIR", base / "_update"),
                        mock.patch.object(libra, "PORT_DEFAULT", 8891)]
        for p in self.patches:
            p.start()
        self.old_cfg = os.environ.get("STORY_CONFIG")
        os.environ["STORY_CONFIG"] = str(base / "c.json")

    def tearDown(self):
        try:
            libra.stoppen()
        finally:
            for p in self.patches:
                p.stop()
            if self.old_cfg is None:
                os.environ.pop("STORY_CONFIG", None)
            else:
                os.environ["STORY_CONFIG"] = self.old_cfg
            self.tmp.cleanup()

    def _install(self):
        """Wie nach install: .venv/bin/python (hier das laufende Python) und Modellordner."""
        venv = libra.venv_python()
        venv.parent.mkdir(parents=True)
        os.symlink(sys.executable, venv)
        (self.dir / "models" / "Libra-TTS").mkdir(parents=True)
        (self.dir / "models" / "Libra-TTS" / "config.json").write_text("{}", encoding="utf-8")

    def test_update_schuetzt_umgebung_modell_einstellungen(self):
        self.assertTrue(update.protected("zusatz/libra-tts/models/Libra-TTS/model.safetensors"))
        self.assertTrue(update.protected("zusatz/libra-tts/.venv/bin/python"))
        self.assertTrue(update.protected("zusatz/libra-tts/server.conf"))
        self.assertFalse(update.protected("zusatz/libra-tts/server.py"))
        self.assertFalse(update.protected("zusatz/libra-tts/libra_tts/api.py"))
        self.assertFalse(update.protected("zusatz/libra-tts/server.conf.example"))

    def test_nachziehen_nur_wenn_installationsdateien_neu(self):
        self.assertIsNone(libra.nachziehen())                    # nicht eingerichtet: nichts tun
        self._install()
        self.assertTrue(libra.eingerichtet())
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return mock.Mock(returncode=0)

        with mock.patch.object(libra.subprocess, "run", side_effect=fake_run):
            self.assertTrue(libra.nachziehen(echo=lambda *a: None))   # unbekannter Stand → einmal nachinstallieren
            self.assertEqual(len(calls), 1)
            self.assertTrue(str(calls[0][1]).endswith("installer.py"))
            self.assertIsNone(libra.nachziehen())                     # gleicher Stand: nichts tun
            (self.dir / "requirements.txt").write_text("numpy>=2\n", encoding="utf-8")  # Update bringt neue Pakete
            self.assertTrue(libra.braucht_nachinstallation())
            self.assertTrue(libra.nachziehen(echo=lambda *a: None))
            self.assertEqual(len(calls), 2)
            (self.dir / "server.py").write_text(FAKE_SERVER + "\n# neu\n", encoding="utf-8")  # nur Code: kein pip
            self.assertIsNone(libra.nachziehen())

    def test_einrichten_ohne_python_310(self):
        with mock.patch.object(libra, "python_fuer_libra", return_value=None):
            out = []
            self.assertFalse(libra.einrichten(echo=out.append))
        self.assertIn("3.10", out[-1])

    def test_starten_eintragen_regie_neustart_bei_neuem_code_stoppen(self):
        self._install()
        address = libra.bereit(timeout=30)
        self.assertTrue(address.startswith("http://127.0.0.1:"))
        info = libra.laeuft()
        self.assertTrue(info and info["bereit"])
        self.assertEqual(libra.starten()["pid"], info["pid"])      # läuft schon: weiterbenutzen
        sid = libra.eintragen(address)
        server = tts.get_server(sid)
        self.assertTrue(server["mitgeliefert"])
        self.assertEqual(server["preset"], "libra")
        self.assertEqual(server["status"], "ok")
        self.assertEqual([v["id"] for v in server["stimmen"]], ["nina", "bob"])
        self.assertEqual(server["regie"]["stile"], ["warm", "sad", "whispering"])
        self.assertEqual(regie.faehig(server)["tags"], ["<sigh>", "<laugh>", "<short pause>"])
        self.assertEqual(libra.eintragen(address), sid)             # kein zweiter Eintrag
        self.assertEqual(len(tts.servers()), 1)

        wav = tts.synth(server, "Hallo <sigh> Welt.", "nina", "de", {"style": "sad", "pace": "slow"})
        self.assertEqual(wav[:4], b"RIFF")
        sent = json.loads((self.dir / "anfragen.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual((sent["style"], sent["pace"], sent["language"], sent["input"]), ("sad", "slow", "de", "Hallo <sigh> Welt."))

        (self.dir / "libra_tts" / "api.py").write_text("# neu\n", encoding="utf-8")  # Update ersetzt Server-Code
        new = libra.bereit(timeout=30)
        self.assertNotEqual(libra.laeuft()["pid"], info["pid"])
        self.assertEqual(new, address)

        self.assertTrue(libra.stoppen())
        time.sleep(0.3)
        self.assertIsNone(libra.laeuft())
        self.assertFalse(libra.stoppen())

    def test_archiviert_startet_nicht(self):
        self._install()
        sid = tts.add_server({"preset": "libra", "name": libra.NAME, "base_url": "http://127.0.0.1:8891"})
        tts._set_state(sid, mitgeliefert=True)
        tts.archive_server(sid)
        self.assertTrue(libra.archiviert())
        self.assertIsNone(libra.sicherstellen(echo=lambda *a: None))
        self.assertIsNone(libra.laeuft())


if __name__ == "__main__":
    unittest.main()
