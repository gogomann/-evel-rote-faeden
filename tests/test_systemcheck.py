"""Systemprüfung beim Start: Erkennen, einmal je Version anbieten, Stand speichern, Start nie blockieren."""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from story_world import __version__, libra, mp3, systemcheck  # noqa: E402


class TestSystemcheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = mock.patch.object(systemcheck, "STATE", Path(self.tmp.name) / "_update" / "systempruefung.json")
        self.state.start()
        self.libra = mock.patch.object(libra, "vorhanden", return_value=False)  # Libra-Punkt nur in eigenen Tests
        self.libra.start()

    def tearDown(self):
        self.libra.stop()
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


    def test_libra_optional_ablehnen_gemerkt(self):
        tty = mock.MagicMock()
        tty.isatty.return_value = True
        with mock.patch.object(mp3, "encoder", return_value=("lame", "/x/lame")), \
                mock.patch.object(libra, "vorhanden", return_value=True), \
                mock.patch.object(libra, "eingerichtet", return_value=False), \
                mock.patch.object(libra, "nachziehen", return_value=None), \
                mock.patch.object(systemcheck.sys, "stdin", tty), \
                mock.patch.object(systemcheck, "_ask", return_value=False) as ask, \
                mock.patch.object(systemcheck, "install") as install:
            items, out = self._run()
            item = next(i for i in items if i["id"] == "libra")
            self.assertTrue(item["optional"] and item["installierbar"] and not item["ok"])
            self.assertEqual(ask.call_count, 1)
            install.assert_not_called()
            with mock.patch.object(systemcheck, "STATE", systemcheck.STATE):
                state = systemcheck._load()
            self.assertEqual(state["abgelehnt"], ["libra"])
            state["version"] = "0.0.1"                              # „Update“: abgelehnt bleibt abgelehnt
            systemcheck._save(state)
            _, out = self._run()
            self.assertEqual(ask.call_count, 1)
            self.assertNotIn("Libra", out.split("Systemprüfung")[0])  # kein Dauer-Hinweis für Optionales
            ask.return_value = True
            self._run(force=True)                                 # „system“ fragt wieder
            self.assertEqual(ask.call_count, 2)
            install.assert_called_once_with("libra")

    def test_libra_nachziehen_bei_jedem_start(self):
        with mock.patch.object(mp3, "encoder", return_value=("lame", "/x/lame")), \
                mock.patch.object(libra, "nachziehen", return_value=True) as pull:
            self._run()
            self._run()
        self.assertEqual(pull.call_count, 2)


if __name__ == "__main__":
    unittest.main()
