"""Systemprüfung beim Start: Erkennen, einmal je Version anbieten, Stand speichern, Start nie blockieren."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from story_world import __version__, mp3, systemcheck  # noqa: E402


class TestSystemcheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = mock.patch.object(systemcheck, "STATE", Path(self.tmp.name) / "_update" / "systempruefung.json")
        self.state.start()

    def tearDown(self):
        self.state.stop()
        self.tmp.cleanup()

    def _run(self, **kw):
        out = io.StringIO()
        with redirect_stdout(out):
            items = systemcheck.run(**kw)
        return items, out.getvalue()

    def test_vorhanden(self):
        with mock.patch.object(mp3, "encoder", return_value=("lame", "/x/lame")):
            items, out = self._run()
        self.assertTrue(next(i for i in items if i["id"] == "mp3")["ok"])
        self.assertIn("Systemprüfung", out)
        self.assertTrue(systemcheck.STATE.exists())

    def test_fehlt_angebot_einmal_je_version(self):
        cmd = (["brew", "install", "lame"], "Homebrew")
        with mock.patch.object(mp3, "encoder", return_value=None), \
                mock.patch.object(systemcheck, "_install_command", return_value=cmd), \
                mock.patch.object(systemcheck, "_ask", return_value=True) as ask, \
                mock.patch.object(systemcheck, "install", return_value=False) as install:
            items, _ = self._run()
            self.assertFalse(items[0]["ok"])
            self.assertEqual(ask.call_count, 1)
            install.assert_called_once_with("mp3")
            _, out = self._run()                                  # gleiche Version: nur Hinweis, keine Frage
            self.assertEqual(ask.call_count, 1)
            self.assertIn("python3 -m story_world system", out)
            self._run(force=True)                                 # „system“-Befehl fragt erneut
            self.assertEqual(ask.call_count, 2)
        self.assertIn(__version__, systemcheck.STATE.read_text(encoding="utf-8"))

    def test_ohne_installationsweg_nur_hinweis(self):
        with mock.patch.object(mp3, "encoder", return_value=None), \
                mock.patch.object(systemcheck, "_install_command", return_value=(None, "brew.sh")), \
                mock.patch.object(systemcheck, "_ask") as ask:
            items, out = self._run()
        ask.assert_not_called()
        self.assertIn("brew.sh", out)
        self.assertFalse(items[0]["installierbar"])


if __name__ == "__main__":
    unittest.main()
