"""Kommandozeile.

  python3 -m story_world                      Oberfläche starten (http://127.0.0.1:8765)
  python3 -m story_world ui --port 8800 --kein-browser
  python3 -m story_world mcp                  MCP-Server (stdio) für KI-Clients
  python3 -m story_world folge <welt> [--woerter N] [--wunsch TEXT]   eine Folge erzeugen
  python3 -m story_world taeglich <welt>      täglicher Lauf (Nachrichten → einarbeiten → Folge), z. B. per cron/launchd
  python3 -m story_world vertonen <welt> <folge-nr> [--modus hoerbuch|hoerspiel]   Folge über TTS-Server vertonen (WAV)
  python3 -m story_world neu "Name der Welt" [--leer]
  python3 -m story_world migrate pfad.sqlite3 Datei auf aktuelles Schema bringen (mit Backup)
  python3 -m story_world update [--nur-pruefen]  Programm von GitHub aktualisieren (Daten bleiben unberührt)
  python3 -m story_world update --zurueck     Notfall: Stand vor dem letzten Update wiederherstellen
  python3 -m story_world system              Systemprüfung (MP3-Encoder, Libra-TTS usw.), Fehlendes installieren
  python3 -m story_world libra [status|einrichten|starten|stoppen]   mitgelieferter TTS-Server (zusatz/libra-tts)
  python3 -m story_world pfad.sqlite3         wie bisher: Basisschema anlegen/ergänzen
"""

import argparse
import json
import sys
import time
from pathlib import Path

from .database import connect, initialize


def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else "ui"

    if command == "ui":
        parser = argparse.ArgumentParser(prog="story_world ui")
        parser.add_argument("--port", type=int, default=8765)
        parser.add_argument("--kein-browser", action="store_true")
        opts = parser.parse_args(args[1:])
        from .web import _already_running, serve
        if not _already_running(opts.port):
            try:  # beim ersten Start nach dem Entpacken/Update: Zusatzprogramme prüfen und anbieten
                from . import systemcheck
                systemcheck.run()
            except Exception as exc:  # die Prüfung darf den Start nie verhindern
                print(f"Systemprüfung übersprungen: {exc}")
        serve(opts.port, not opts.kein_browser)
    elif command == "system":
        from . import systemcheck
        items = systemcheck.run(force=True)
        if not all(i["ok"] or i.get("optional") for i in items):
            sys.exit(1)
    elif command == "libra":
        parser = argparse.ArgumentParser(prog="story_world libra")
        parser.add_argument("aktion", nargs="?", default="status", choices=["status", "einrichten", "starten", "stoppen"])
        opts = parser.parse_args(args[1:])
        from . import libra
        if opts.aktion == "einrichten":
            if not libra.einrichten():
                sys.exit(1)
        elif opts.aktion == "stoppen":
            print("Libra-TTS beendet." if libra.stoppen() else "Libra-TTS lief nicht.")
        elif opts.aktion == "starten":  # im Vordergrund, bis Strg+C
            try:
                address = libra.bereit()
                libra.eintragen(address)
            except libra.LibraError as exc:
                sys.exit(str(exc))
            print(f"Libra-TTS läuft: {address}  (Web-Oberfläche dort) – Beenden mit Strg+C")
            try:
                while libra.laeuft():
                    time.sleep(2)
            except KeyboardInterrupt:
                libra.stoppen()
        else:
            print(json.dumps(libra.status(), ensure_ascii=False, indent=1))
    elif command == "folge":
        parser = argparse.ArgumentParser(prog="story_world folge")
        parser.add_argument("welt")
        parser.add_argument("--woerter", type=int)
        parser.add_argument("--wunsch", default="")
        opts = parser.parse_args(args[1:])
        from .episodes import produce
        from .worlds import open_world
        with open_world(opts.welt) as conn:
            episode_id = produce(conn, opts.wunsch, words=opts.woerter)
        print(f"Folge #{episode_id} erzeugt.")
    elif command == "taeglich":
        parser = argparse.ArgumentParser(prog="story_world taeglich")
        parser.add_argument("welt")
        opts = parser.parse_args(args[1:])
        from .daily import run
        print(run(opts.welt))
    elif command == "vertonen":
        parser = argparse.ArgumentParser(prog="story_world vertonen")
        parser.add_argument("welt")
        parser.add_argument("folge", type=int, help="Folgennummer (wie in der Oberfläche)")
        parser.add_argument("--modus", choices=["hoerbuch", "hoerspiel"])
        opts = parser.parse_args(args[1:])
        from .tts import render, set_episode_settings
        from .worlds import open_world
        with open_world(opts.welt) as conn:
            row = conn.execute("SELECT id FROM episodes WHERE release_nr = ? ORDER BY id DESC", (opts.folge,)).fetchone()
            if row is None:
                sys.exit(f"Folge {opts.folge} nicht gefunden.")
            if opts.modus:
                set_episode_settings(conn, row[0], {"modus": opts.modus})
                conn.commit()
            path = render(conn, opts.welt, row[0])
        print(f"Gespeichert: {path}")
    elif command == "mcp":
        from .mcp_server import serve as serve_mcp
        serve_mcp()
    elif command == "neu":
        parser = argparse.ArgumentParser(prog="story_world neu")
        parser.add_argument("name")
        parser.add_argument("--beschreibung", default="")
        parser.add_argument("--leer", action="store_true", help="ohne Startbestand aus WELT_REGELN.md")
        opts = parser.parse_args(args[1:])
        from .worlds import create_world, path_for
        slug = create_world(opts.name, opts.beschreibung, not opts.leer)
        print(f"Welt angelegt: {path_for(slug)}")
    elif command == "update":
        parser = argparse.ArgumentParser(prog="story_world update")
        parser.add_argument("--nur-pruefen", action="store_true")
        parser.add_argument("--zurueck", action="store_true", help="Stand vor dem letzten Update wiederherstellen")
        opts = parser.parse_args(args[1:])
        from . import update
        if opts.zurueck:
            from .web import _already_running
            if _already_running(8765):
                sys.exit("Story World läuft noch – bitte erst beenden (Fenster schließen bzw. „Story World beenden“).")
            try:
                report = update.zurueck()
            except update.UpdateError as exc:
                sys.exit(str(exc))
            print(f"Zurück auf {report['nach']} (von {report['von']}): {report['wiederhergestellt']} Dateien wiederhergestellt, "
                  f"{report['beiseitegelegt']} beiseitegelegt. Der bisherige Stand liegt in {report['sicherung']}.")
            for world in report["welten"]:
                print(f"  ⚠ {world['welt']}: Schema {world['schema']}, Version {report['nach']} kennt nur bis {world['kennt']}. "
                      + (f"Sicherung von vor dem Update: welten/backups/{world['sicherung']} "
                         "(Einstellungen → Sicherung → „Als neue Welt öffnen“)." if world["sicherung"]
                         else "Keine passende Sicherung gefunden – Welt mit der neueren Version weiter nutzen."))
            print("Bitte Story World neu starten. Die automatische Update-Prüfung bietet die neuere Version weiter an.")
            return
        try:
            info = update.check()
            if not info["neuer"]:
                print(f"Aktuell: {info['aktuell']} (neueste auf GitHub: {info['neueste'] or '–'}).")
            elif opts.nur_pruefen:
                print(f"Neue Version {info['neueste']} verfügbar (installiert: {info['aktuell']}).")
            else:
                report = update.install()
                print(f"Aktualisiert {report['von']} → {report['nach']}: {report['geaendert']} geändert, "
                      f"{report['neu']} neu, {report['entfallen']} entfallen"
                      + (f"; alte Fassungen in {report['sicherung']}" if report["sicherung"] else "")
                      + ". Bitte Story World neu starten.")
        except update.UpdateError as exc:
            sys.exit(str(exc))
    elif command == "migrate":
        parser = argparse.ArgumentParser(prog="story_world migrate")
        parser.add_argument("database")
        opts = parser.parse_args(args[1:])
        from .migrations import migrate
        path = Path(opts.database)
        with connect(path) as connection:
            report = migrate(connection, path)
        print(f"Schema {report['from']} → {report['to']}" + (f", Sicherung: {report['backup']}" if report["backup"] else ""))
    else:
        parser = argparse.ArgumentParser(description="Story-Welt-Datenbank initialisieren")
        parser.add_argument("database", help="Pfad zur SQLite-Datenbank")
        opts = parser.parse_args(args)
        with connect(opts.database) as connection:
            initialize(connection)
        print(f"Datenbank initialisiert: {opts.database}")


if __name__ == "__main__":
    main()
