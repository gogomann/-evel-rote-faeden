import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from story_world import __version__, migrations, update


def make_zip(path: Path, files: dict, top: str = "evel-rote-faeden/") -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for rel, content in files.items():
            zf.writestr(top + rel, content)
    return path


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "app"
        files = {
            "story_world/__init__.py": '__version__ = "0.1.0"\n',
            "story_world/gleich.py": "x = 1\n",
            "story_world/aendert.py": "alt = True\n",
            "story_world/entfaellt.py": "weg = True\n",
            "story_world/static/app.js": "// alt\n",
            "README.md": "alt\n",
            "welten/erde.sqlite3": "DATEN",
            "welten/backups/erde-vor-v5.sqlite3": "SICHERUNG",
            "story_world.config.json": '{"geheim": 1}',
            "story_world.profiles.json": '{"p": 1}',
            "story_world.stimmen.json": '{"s": 1}',
            "story_world.qualitaet.sqlite3": "Q",
            "profile_texte/a.txt": "Text",
            "exporte/x.zip": "Z",
            "_old/frueher.txt": "alt",
        }
        for rel, content in files.items():
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.release = {
            "story_world/__init__.py": '__version__ = "0.2.0"\n',
            "story_world/gleich.py": "x = 1\n",
            "story_world/aendert.py": "alt = False\n",
            "story_world/neu.py": "neu = True\n",
            "story_world/static/app.js": "// neu\n",
            "README.md": "neu\n",
            "Story World starten.command": "#!/bin/bash\n",
            # Ein Paket darf Nutzerdaten nie überschreiben – selbst wenn es sie enthielte:
            "welten/erde.sqlite3": "BOESE",
            "story_world.config.json": "{}",
            "AENDERUNGEN.md": "# Änderungen\n\n## 0.2.0 – neu\n- Update-Knopf\n\n## 0.1.0\n- Start\n",
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def test_installiert_programm_und_laesst_daten_in_ruhe(self):
        report = update.install_from_zip(make_zip(self.tmp / "r.zip", self.release), self.root, "Notizen", "v0.2.0")
        self.assertEqual((report["von"], report["nach"]), ("0.1.0", "0.2.0"))
        self.assertEqual(self.read("story_world/__init__.py"), '__version__ = "0.2.0"\n')
        self.assertEqual(self.read("story_world/aendert.py"), "alt = False\n")
        self.assertEqual(self.read("story_world/neu.py"), "neu = True\n")
        self.assertEqual(self.read("story_world/static/app.js"), "// neu\n")
        self.assertTrue(os.access(self.root / "Story World starten.command", os.X_OK))
        # Nutzerdaten unverändert
        self.assertEqual(self.read("welten/erde.sqlite3"), "DATEN")
        self.assertEqual(self.read("welten/backups/erde-vor-v5.sqlite3"), "SICHERUNG")
        self.assertEqual(self.read("story_world.config.json"), '{"geheim": 1}')
        for rel in ("story_world.profiles.json", "story_world.stimmen.json", "story_world.qualitaet.sqlite3",
                    "profile_texte/a.txt", "exporte/x.zip", "_old/frueher.txt"):
            self.assertTrue((self.root / rel).exists(), rel)
        # Alte Fassungen und Entfallenes liegen in _old, nichts gelöscht
        backup = self.root / report["sicherung"]
        self.assertTrue(report["sicherung"].startswith("_old/update-0.1.0-nach-0.2.0-"))
        self.assertEqual((backup / "story_world/aendert.py").read_text(), "alt = True\n")
        self.assertEqual((backup / "story_world/entfaellt.py").read_text(), "weg = True\n")
        self.assertFalse((self.root / "story_world/entfaellt.py").exists())
        self.assertFalse((backup / "story_world/gleich.py").exists())  # unverändert → nicht angefasst
        self.assertEqual(report["entfallen"], 1)
        manifest = json.loads((self.root / "_update/manifest.json").read_text())
        self.assertIn("story_world/neu.py", manifest["dateien"])
        self.assertNotIn("welten/erde.sqlite3", manifest["dateien"])
        self.assertFalse(any(p.name.startswith("entpackt-") for p in (self.root / "_update").iterdir()))

    def test_entwicklerordner_wird_nicht_ueberschrieben(self):
        (self.root / ".git").mkdir()
        with self.assertRaises(update.UpdateError) as ctx:
            update.install_from_zip(make_zip(self.tmp / "r.zip", self.release), self.root)
        self.assertIn("git pull", str(ctx.exception))
        self.assertEqual(self.read("story_world/aendert.py"), "alt = True\n")

    def test_unsichere_pfade_und_falsche_versionen(self):
        bad = make_zip(self.tmp / "bad.zip", {"../../boese.py": "x", **self.release})
        with self.assertRaises(update.UpdateError):
            update.install_from_zip(bad, self.root)
        with self.assertRaises(update.UpdateError):  # Tag passt nicht zum Paket
            update.install_from_zip(make_zip(self.tmp / "r.zip", self.release), self.root, tag="v0.3.0")
        older = dict(self.release, **{"story_world/__init__.py": '__version__ = "0.1.0"\n'})
        with self.assertRaises(update.UpdateError):  # nicht neuer
            update.install_from_zip(make_zip(self.tmp / "o.zip", older), self.root)
        with self.assertRaises(update.UpdateError):  # kein Programm im Paket
            update.install_from_zip(make_zip(self.tmp / "l.zip", {"README.md": "x"}), self.root)
        self.assertEqual(self.read("story_world/aendert.py"), "alt = True\n")

    def test_fehler_unterwegs_stellt_alten_stand_her(self):
        real_replace, calls = os.replace, {"n": 0}

        def flaky(src, dst):
            if str(src).endswith(".update-tmp"):
                calls["n"] += 1
                if calls["n"] == 3:
                    raise OSError("Platte voll")
            return real_replace(src, dst)

        with mock.patch("story_world.update.os.replace", side_effect=flaky):
            with self.assertRaises(update.UpdateError) as ctx:
                update.install_from_zip(make_zip(self.tmp / "r.zip", self.release), self.root)
        self.assertIn("wiederhergestellt", str(ctx.exception))
        self.assertEqual(self.read("story_world/__init__.py"), '__version__ = "0.1.0"\n')
        self.assertEqual(self.read("story_world/aendert.py"), "alt = True\n")
        self.assertEqual(self.read("story_world/entfaellt.py"), "weg = True\n")
        self.assertEqual(self.read("README.md"), "alt\n")
        self.assertFalse((self.root / "story_world/neu.py").exists())
        self.assertFalse((self.root / "_update/installiert.json").exists())

    def test_pruefen_release_und_tags(self):
        release = {"tag_name": "v9.0.0", "name": "Große Fassung", "body": "Alles neu", "published_at": "2026-11-13",
                   "zipball_url": "https://codeberg.org/gogomann/evel-rote-faeden/archive/v9.0.0.zip", "assets": []}
        with mock.patch.object(update, "_get_json", return_value=release):
            info = update.check(self.root)
        self.assertTrue(info["neuer"])
        self.assertEqual((info["neueste"], info["notizen"]), ("9.0.0", "Alles neu"))
        self.assertEqual(update.status(self.root)["verfuegbar"]["neueste"], "9.0.0")

        def no_release(url, timeout=15):
            return None if "releases" in url else [{"name": "v0.0.1"}, {"name": "latest"}, {"name": __version__}]
        with mock.patch.object(update, "_get_json", side_effect=no_release):
            info = update.check(self.root)
        self.assertFalse(info["neuer"])
        self.assertIsNone(update.status(self.root)["verfuegbar"])
        with self.assertRaises(update.UpdateError):
            update.download("https://example.com/x.zip", self.tmp / "x.zip")

    def test_hinweis_nach_update_und_migrationen(self):
        (self.root / "AENDERUNGEN.md").write_text(
            "# Änderungen\n\n## 9.0.0\n- Zukunft\n\n## " + __version__ + " – jetzt\n- Update-Knopf\n\n## 0.0.5\n- Fix\n\n## 0.0.1\n- Alt\n",
            encoding="utf-8")
        first = update.status(self.root)  # erster Start: nur merken, kein Banner
        self.assertIsNone(first["neu"])
        update._save_state(self.root, gesehen_version="0.0.1")
        del migrations.REPORTS[:]  # andere Tests derselben Sitzung migrieren ebenfalls
        migrations.REPORTS.append({"datei": "erde.sqlite3", "von": 14, "nach": 16, "sicherung": "/x/erde-vor-v16.sqlite3"})
        try:
            st = update.status(self.root)
            self.assertEqual([a["version"] for a in st["neu"]["abschnitte"]], [update.version_text(__version__), "0.0.5"])
            self.assertEqual(st["migrationen"][0]["von"], 14)
            update.acknowledge(self.root)
            st = update.status(self.root)
            self.assertIsNone(st["neu"])
            self.assertEqual(st["migrationen"], [])
        finally:
            del migrations.REPORTS[:]

    def test_versionen(self):
        self.assertEqual(update.parse_version("v1.2"), (1, 2, 0))
        self.assertGreater(update.parse_version("0.10.0"), update.parse_version("0.9.9"))
        self.assertTrue(update.protected("welten/erde.sqlite3"))
        self.assertTrue(update.protected("story_world.config.json"))
        self.assertTrue(update.protected("story_world/__pycache__/x.pyc"))
        self.assertFalse(update.protected("story_world/web.py"))
        self.assertFalse(update.protected("Story World starten.bat"))


if __name__ == "__main__":
    unittest.main()
