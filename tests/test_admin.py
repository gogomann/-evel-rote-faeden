import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Qualitätsmessungen der Tests landen in einer Wegwerf-Datei, nie im Projektordner
os.environ.setdefault("STORY_QUALITY", os.path.join(tempfile.mkdtemp(prefix="sw-qual-"), "q.sqlite3"))

from story_world import llm, service, status
from story_world.database import connect, initialize
from story_world.migrations import LATEST_VERSION, current_version, migrate
from story_world.seed import seed_from_rules


def fresh():
    conn = connect(":memory:")
    migrate(conn)
    return conn


class MigrationTests(unittest.TestCase):
    def test_legacy_db_keeps_data_and_gets_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "alt.sqlite3"
            conn = connect(path)
            initialize(conn)
            conn.execute("INSERT INTO peoples (name, origin) VALUES ('Altvolk', 'alt')")
            conn.commit()
            self.assertEqual(current_version(conn), 1)
            report = migrate(conn, path)
            self.assertEqual((report["from"], report["to"]), (1, LATEST_VERSION))
            self.assertTrue(Path(report["backup"]).exists())
            row = conn.execute("SELECT name, origin, created_by, visibility FROM peoples").fetchone()
            self.assertEqual(tuple(row), ("Altvolk", "alt", "nutzer", "offen"))
            self.assertEqual(migrate(conn, path)["backup"], None)  # wiederholbar, keine Änderung
            backup = sqlite3.connect(report["backup"])
            self.assertEqual(backup.execute("SELECT name FROM peoples").fetchone()[0], "Altvolk")
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            backup.close()
            conn.close()

    def test_newer_schema_rejected(self):
        conn = fresh()
        conn.execute(f"PRAGMA user_version = {LATEST_VERSION + 1}")
        with self.assertRaises(RuntimeError):
            migrate(conn)
        conn.close()


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = fresh()
        seed_from_rules(self.db)

    def tearDown(self):
        self.db.close()

    def test_seed_only_from_rules_and_gaps_listed(self):
        names = [r[0] for r in self.db.execute("SELECT name FROM peoples ORDER BY id")]
        self.assertEqual(names, ["Menschen", "Aureas"])
        self.assertFalse(seed_from_rules(self.db))
        titles = {i["title"] for i in service.gaps(self.db)["items"]}
        self.assertIn("Aureas-Kalender", titles)

    def test_secret_fields_and_backstage_rows_hidden(self):
        mid = service.create_row(self.db, "mysteries", {"description": "Kanarie-Rätsel", "status": "offen",
                                                        "truth": "KANARIE-WAHRHEIT"}, actor="ki", visibility="offen")
        service.create_row(self.db, "locations", {"name": "KANARIE-ORT"}, actor="ki", visibility="backstage")
        public = json.dumps([service.list_rows(self.db, t) for t in service.ENTITIES], ensure_ascii=False)
        public += json.dumps(service.gaps(self.db), ensure_ascii=False)
        public += json.dumps(service.audit_entries(self.db), ensure_ascii=False)
        self.assertNotIn("KANARIE-WAHRHEIT", public)
        self.assertNotIn("KANARIE-ORT", public)
        self.assertIn("KANARIE-WAHRHEIT", json.dumps(service.get_row(self.db, "mysteries", mid, reveal=True)))
        with self.assertRaises(LookupError):
            service.get_row(self.db, "locations", 1)

    def test_user_edit_without_reveal_preserves_secret(self):
        mid = service.create_row(self.db, "mysteries", {"description": "R", "status": "offen", "truth": "geheim"},
                                 actor="ki", visibility="offen")
        service.update_row(self.db, "mysteries", mid, {"description": "R2", "truth": ""})
        row = self.db.execute("SELECT description, truth FROM mysteries WHERE id=?", (mid,)).fetchone()
        self.assertEqual(tuple(row), ("R2", "geheim"))

    def test_validation_messages(self):
        with self.assertRaises(service.ValidationError):
            service.create_row(self.db, "threads", {"title": "x", "level": "giga", "world_time_cursor": 1})
        with self.assertRaises(service.ValidationError):
            service.create_row(self.db, "characters", {"name": "x", "people_id": 999})
        with self.assertRaises(service.ValidationError):
            service.create_row(self.db, "peoples", {"name": "Menschen"})

    def test_apply_proposal_refs_fill_only_and_hidden(self):
        payload = {
            "zusammenfassung": "Ein Mond und eine Familie.",
            "operationen": [
                {"aktion": "anlegen", "tabelle": "locations", "ref": "kesh", "felder": {"name": "Kesh", "kind": "mond"}},
                {"aktion": "anlegen", "tabelle": "characters", "felder": {"name": "Tavi", "people_id": 2,
                                                                           "description": "Händlerin"}},
                {"aktion": "anlegen", "tabelle": "threads", "felder": {"title": "Federn", "level": "mikro",
                                                                        "location_id": "@kesh", "world_time_cursor": 0}},
                {"aktion": "anlegen", "tabelle": "mysteries",
                 "felder": {"description": "Wer kauft?", "status": "offen", "truth": "Die Flotte"}},
                {"aktion": "ergaenzen", "tabelle": "peoples", "id": 2,
                 "felder": {"origin": "ÜBERSCHRIEBEN", "goals": "Frieden"}},
            ],
        }
        pid = service.store_proposal(self.db, "test", payload, "fake")
        listed = service.list_proposals(self.db)[0]
        self.assertEqual(listed["verborgen"], 1)  # Rätsel der KI ist automatisch backstage
        self.assertNotIn("Die Flotte", json.dumps(listed, ensure_ascii=False))
        report = service.apply_proposal(self.db, pid)
        self.assertEqual(report["angelegt"], 4)
        self.assertEqual(report["uebersprungen"], 1)
        aureas = self.db.execute("SELECT origin, goals FROM peoples WHERE id=2").fetchone()
        self.assertEqual(aureas["origin"], "Genetische Quelle vogelartig.")
        self.assertEqual(aureas["goals"], "Frieden")
        thread = self.db.execute("SELECT t.location_id, l.name FROM threads t JOIN locations l ON l.id=t.location_id").fetchone()
        self.assertEqual(thread["name"], "Kesh")
        self.assertEqual(self.db.execute("SELECT visibility FROM mysteries WHERE description='Wer kauft?'").fetchone()[0], "backstage")
        with self.assertRaises(service.ValidationError):
            service.apply_proposal(self.db, pid)

    def test_failed_operation_does_not_block_others(self):
        payload = {"operationen": [
            {"aktion": "anlegen", "tabelle": "locations", "felder": {"name": "Guter Ort"}},
            {"aktion": "anlegen", "tabelle": "characters", "ref": "x", "felder": {"name": "X", "people_id": 999}},
            {"aktion": "anlegen", "tabelle": "threads", "felder": {"title": "S", "level": "mikro", "pov_id": "@x",
                                                                    "world_time_cursor": 0}},
            {"aktion": "anlegen", "tabelle": "snippets", "felder": {"title": "Plausch in der Kantine", "kind": "Socializing"}},
        ]}
        pid = service.store_proposal(self.db, "test", payload, "fake")
        report = service.apply_proposal(self.db, pid)
        self.assertEqual((report["angelegt"], report["fehlgeschlagen"]), (2, 2))
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM locations WHERE name='Guter Ort'").fetchone())
        self.assertIsNone(self.db.execute("SELECT 1 FROM characters WHERE name='X'").fetchone())
        self.assertEqual(self.db.execute("SELECT status FROM snippets").fetchone()[0], "offen")

    def test_all_operations_failing_keeps_proposal_open(self):
        payload = {"operationen": [{"aktion": "anlegen", "tabelle": "characters", "felder": {"name": "X", "people_id": 999}}]}
        pid = service.store_proposal(self.db, "test", payload, "fake")
        with self.assertRaises(service.ValidationError):
            service.apply_proposal(self.db, pid)
        self.assertEqual(self.db.execute("SELECT status FROM proposals WHERE id=?", (pid,)).fetchone()[0], "offen")

    def test_search_hides_secrets(self):
        service.create_row(self.db, "mysteries", {"description": "R", "status": "offen", "truth": "Zebrafisch"},
                           actor="ki", visibility="offen")
        self.assertEqual(service.search(self.db, "Zebrafisch"), [])
        self.assertEqual(len(service.search(self.db, "Zebrafisch", reveal=True)), 1)
        self.assertEqual(service.search(self.db, "Warpblase")[0]["table"], "world_rules")

    def test_proposal_shows_names_not_ids(self):
        payload = {"operationen": [
            {"aktion": "anlegen", "tabelle": "locations", "ref": "k", "felder": {"name": "Kesh"}},
            {"aktion": "anlegen", "tabelle": "characters", "felder": {"name": "T", "people_id": 2}},
            {"aktion": "anlegen", "tabelle": "threads", "felder": {"title": "S", "level": "mikro", "location_id": "@k", "world_time_cursor": 0}},
            {"aktion": "ergaenzen", "tabelle": "peoples", "id": 2, "felder": {"goals": "x"}}]}
        service.store_proposal(self.db, "t", payload, "m")
        text = json.dumps(service.list_proposals(self.db)[0], ensure_ascii=False)
        self.assertIn("Aureas", text)
        self.assertIn("Kesh (neu)", text)

    def test_validate_payload_rejects_unknown(self):
        self.assertTrue(service.validate_payload({"operationen": [{"aktion": "loeschen", "tabelle": "peoples", "felder": {"x": 1}}]}))
        self.assertTrue(service.validate_payload({"operationen": [{"aktion": "anlegen", "tabelle": "impulses", "felder": {"x": 1}}]}))

    def test_massstab_hierarchy_and_level(self):
        level = lambda t, i: self.db.execute(f"SELECT level FROM {t} WHERE id=?", (i,)).fetchone()[0]
        gal = service.create_row(self.db, "locations", {"name": "G", "kind": "galaxie"})
        sys_ = service.create_row(self.db, "locations", {"name": "S", "kind": "system", "parent_id": gal})
        pl = service.create_row(self.db, "locations", {"name": "P", "kind": "planet", "parent_id": sys_, "level": "makro"})
        self.assertEqual(level("locations", pl), "meso")  # Ebene folgt aus der Art
        mond = service.create_row(self.db, "locations", {"name": "M", "kind": "mond", "parent_id": pl})
        service.create_row(self.db, "locations", {"name": "Stadt", "kind": "stadt", "parent_id": mond})
        service.create_row(self.db, "locations", {"name": "Station", "kind": "station", "parent_id": mond})
        with self.assertRaises(service.ValidationError):
            service.create_row(self.db, "locations", {"name": "X", "kind": "system", "parent_id": pl})
        with self.assertRaises(service.ValidationError):
            service.update_row(self.db, "locations", gal, {"parent_id": pl})  # Kreis
        with self.assertRaises(service.ValidationError):
            service.update_row(self.db, "locations", sys_, {"kind": "haus"})  # enthält einen größeren Planeten
        tid = service.create_row(self.db, "threads", {"title": "Liebe", "level": "makro", "massstab": "liebende",
                                                      "world_time_cursor": 0})
        self.assertEqual(level("threads", tid), "mikro")

    def test_dossiers_place_and_person(self):
        sol = service.create_row(self.db, "locations", {"name": "Sool", "kind": "system"})
        erde = service.create_row(self.db, "locations", {"name": "Erde", "kind": "planet", "parent_id": sol})
        stadt = service.create_row(self.db, "locations", {"name": "Hamburg", "kind": "stadt", "parent_id": erde})
        service.update_row(self.db, "peoples", 1, {"home_location_id": erde})
        mira = service.create_row(self.db, "characters", {"name": "Mira", "people_id": 1, "location_id": stadt})
        tavi = service.create_row(self.db, "characters", {"name": "Tavi", "people_id": 1, "location_id": stadt})
        geheim = service.create_row(self.db, "characters", {"name": "KANARIE-VATER"}, actor="ki", visibility="backstage")
        firma = service.create_row(self.db, "organizations", {"name": "Werft Nord", "location_id": stadt})
        service.create_row(self.db, "jobs", {"character_id": mira, "title": "Schweißerin", "organization_id": firma,
                                             "from_world_time": 10})
        service.create_row(self.db, "character_relations", {"character_id": tavi, "kind": "elternteil", "other_id": mira})
        service.create_row(self.db, "character_relations", {"character_id": geheim, "kind": "elternteil", "other_id": mira},
                           actor="ki", visibility="offen")
        service.create_row(self.db, "threads", {"title": "Funkenflug", "level": "mikro", "pov_id": mira,
                                                "location_id": stadt, "world_time_cursor": 0})
        service.create_row(self.db, "snippets", {"title": "Mira in der Kantine"})
        place = service.location_dossier(self.db, sol)
        self.assertEqual([p["name"] for p in place["voelker"]], ["Menschen"])
        self.assertEqual({c["name"] for c in place["figuren"]}, {"Mira", "Tavi"})
        self.assertEqual((place["unterorte_gesamt"], len(place["jobs"]), len(place["straenge"])), (2, 1, 1))
        self.assertEqual([p["name"] for p in service.location_dossier(self.db, stadt)["pfad"]], ["Sool", "Erde"])
        person = service.character_dossier(self.db, mira)
        self.assertEqual([(f["art"], f["name"]) for f in person["familie"]], [("elternteil", "Tavi")])
        self.assertEqual([f["art"] for f in service.character_dossier(self.db, tavi)["familie"]], ["kind"])
        self.assertEqual(person["jobs"][0]["organization_id__name"], "Werft Nord")
        self.assertEqual(len(person["straenge_pov"]), 1)
        self.assertEqual(len(person["erwaehnt"]["einschuebe"]), 1)
        self.assertNotIn("KANARIE-VATER", json.dumps(person, ensure_ascii=False))
        self.assertEqual(len(service.character_dossier(self.db, mira, reveal=True)["familie"]), 2)
        with self.assertRaises(service.ValidationError):
            service.create_row(self.db, "character_relations", {"character_id": mira, "kind": "partner", "other_id": mira})

    def test_migration_6_turns_belts_into_system_areas(self):
        sid = service.create_row(self.db, "locations", {"name": "Sool", "kind": "system"})
        rid = service.create_row(self.db, "locations", {"name": "Gürtel", "kind": "region", "parent_id": sid})
        self.db.commit()
        self.db.execute("PRAGMA user_version = 5")
        migrate(self.db)
        row = self.db.execute("SELECT kind, level FROM locations WHERE id=?", (rid,)).fetchone()
        self.assertEqual(tuple(row), ("systembereich", "makro"))


class NewsAndTechTests(unittest.TestCase):
    def test_news_task_and_technology_gaps(self):
        task = llm.impulse_task({"kind": "nachricht", "title": "T", "content": "C"})
        self.assertIn("Untergrund", task)
        db = fresh()
        tid = service.create_row(db, "technologies", {"name": "Faltantrieb", "kind": "antrieb"})
        gap = [g for g in service.gaps(db)["items"] if g["table"] == "technologies"][0]
        self.assertEqual(gap["id"], tid)
        self.assertIn("Regeln & Grenzen", gap["missing"])
        db.execute("INSERT INTO threads (id, level, world_time_cursor) VALUES (1, 'mikro', 0)")
        db.execute("INSERT INTO episodes (release_nr, thread_id, world_start, world_end, type) VALUES (1, 1, 5, 6, 'vorausblick')")
        db.close()


class McpTests(unittest.TestCase):
    def test_stdio_roundtrip(self):
        import subprocess
        import sys
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, STORY_WORLDS_DIR=tmp, STORY_CONFIG=os.path.join(tmp, "config.json"))
            proc = subprocess.Popen([sys.executable, str(root / "story_world_mcp.py")], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, text=True, env=env, cwd=tmp)
            msg_id = [0]

            def rpc(method, params=None, notify=False):
                msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
                if not notify:
                    msg_id[0] += 1
                    msg["id"] = msg_id[0]
                proc.stdin.write(json.dumps(msg) + "\n")
                proc.stdin.flush()
                return None if notify else json.loads(proc.stdout.readline())

            def tool(tool_name, **args):
                res = rpc("tools/call", {"name": tool_name, "arguments": args})["result"]
                return res["isError"], res["content"][0]["text"]

            try:
                init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "test", "version": "1"}})
                self.assertEqual(init["result"]["serverInfo"]["name"], "story-world")
                rpc("notifications/initialized", notify=True)
                names = {t["name"] for t in rpc("tools/list")["result"]["tools"]}
                self.assertIn("vorschlag_einreichen", names)
                err, text = tool("welt_anlegen", name="MCP Welt")
                self.assertFalse(err, text)
                err, text = tool("vorschlag_einreichen", welt="mcp-welt", vorschlag={"operationen": [
                    {"aktion": "anlegen", "tabelle": "technologies",
                     "felder": {"name": "Spontane Tür", "kind": "tuer", "rules": "Öffnet sich nur bei Stille."}},
                    {"aktion": "anlegen", "tabelle": "mysteries", "felder": {"description": "Wohin?", "status": "offen",
                                                                             "truth": "MCP-GEHEIM"}}]})
                self.assertIn("uebernommen", text)
                err, text = tool("kanon_lesen", welt="mcp-welt")
                self.assertIn("Spontane Tür", text)
                self.assertNotIn("MCP-GEHEIM", text)
                err, text = tool("kanon_lesen", welt="mcp-welt", backstage=True)
                self.assertIn("MCP-GEHEIM", text)
                err, text = tool("vorschlag_einreichen", welt="mcp-welt", vorschlag={"operationen": [
                    {"aktion": "loeschen", "tabelle": "peoples", "felder": {"name": "x"}}]})
                self.assertIn("Nichts gespeichert", text)
                err, text = tool("impuls_anlegen", welt="mcp-welt", titel="News", inhalt="Etwas geschah.", art="nachricht")
                self.assertIn('"neu"', text)
                err, text = tool("anleitung")
                self.assertIn("ERZAEHLREGELN.md", text)
                self.assertTrue(tool("welt_uebersicht", welt="gibts-nicht")[0])
            finally:
                proc.stdin.close()
                proc.wait(timeout=5)
                proc.stdout.close()


class StatusTests(unittest.TestCase):
    def test_parse_checklists(self):
        sections = status.parse("## A\n- [x] fertig\n- [ ] offen\n- [ ] x **Teilweise:** y\n")
        self.assertEqual([i["status"] for i in sections[0]["items"]], ["erledigt", "offen", "teilweise"])


class FakeLLM(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *a):
        pass

    def _json(self, payload, code=200):
        out = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        if self.headers.get("Authorization") == "Bearer falsch":
            return self._json({"error": "bad key"}, 401)
        self._json({"data": [{"id": "fake-b"}, {"id": "fake-a"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLLM.requests.append(body)
        if body.get("model") == "kaputt":
            return self._json({"error": "boom"}, 500)
        if body.get("stream") and body.get("model") == "fake-a":
            content = json.dumps({"zusammenfassung": "Gestreamt.", "operationen": [
                {"aktion": "anlegen", "tabelle": "snippets", "felder": {"title": "Plausch", "kind": "Socializing"}},
                {"aktion": "anlegen", "tabelle": "mysteries", "felder": {"description": "R", "status": "offen",
                                                                         "truth": "STREAM-GEHEIM"}}]})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for i in range(0, len(content), 40):
                chunk = {"choices": [{"delta": {"content": content[i:i + 40]}}]}
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            return
        if "Antworte mit" in body["messages"][-1]["content"]:
            content = '{"ok": true}'
        else:
            content = "```json\n" + json.dumps({
                "zusammenfassung": "Ein neuer Ort.",
                "operationen": [{"aktion": "anlegen", "tabelle": "locations", "felder": {"name": "Neu-Ort", "kind": "station"}}],
                "rueckfragen": [],
            }) + "\n```"
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunk = {"choices": [{"delta": {"content": content}}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode())
            return
        out = json.dumps({"model": "fake-1", "choices": [{"message": {"content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["STORY_WORLDS_DIR"] = cls.tmp.name
        os.environ["STORY_CONFIG"] = os.path.join(cls.tmp.name, "config.json")
        cls.fake = HTTPServer(("127.0.0.1", 0), FakeLLM)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        os.environ["STORY_LLM_BASE_URL"] = f"http://127.0.0.1:{cls.fake.server_address[1]}/v1"
        os.environ["STORY_LLM_MODEL"] = "fake"
        from story_world import web
        cls.web = web
        cls.server = web.make_server(0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.fake.shutdown()
        cls.fake.server_close()
        cls.tmp.cleanup()
        for k in ("STORY_WORLDS_DIR", "STORY_LLM_BASE_URL", "STORY_LLM_MODEL", "STORY_CONFIG"):
            os.environ.pop(k, None)

    def call(self, method, path, body=None, headers=None, host=None):
        h = {"X-Story-World": "1", "Content-Type": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=h,
                                     data=json.dumps(body).encode() if body is not None else None)
        if host:
            req.add_unredirected_header("Host", host)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_person_page_texts_and_world_import(self):
        import base64, io, time, zipfile
        from story_world import profiles, textimport
        os.environ["STORY_PROFILES"] = os.path.join(self.tmp.name, "profiles.json")
        os.environ["STORY_PROFILE_TEXTS"] = os.path.join(self.tmp.name, "texte")
        try:
            slug = self.call("POST", "/api/worlds", {"name": "Textwelt"})[1]["slug"]
            pid = self.call("POST", "/api/profiles", {"name": "Ralf"})[1]["id"]
            code, meta = self.call("POST", f"/api/profiles/{pid}/texte",
                                   {"titel": "Familie Berger", "text": "Die Bergers leben in Sub-Sub.\n\nVater Jon repariert Pumpen.",
                                    "stil": True})
            self.assertEqual((code, meta["woerter"], meta["stil"]), (200, 9, True))
            doc = io.BytesIO()
            with zipfile.ZipFile(doc, "w") as z:
                z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                           '<w:body><w:p><w:r><w:t>Erster Absatz.</w:t></w:r></w:p><w:p><w:r><w:t>Zweiter.</w:t></w:r></w:p>'
                           '</w:body></w:document>')
            code, meta2 = self.call("POST", f"/api/profiles/{pid}/texte",
                                    {"dateiname": "notizen.docx", "daten_b64": base64.b64encode(doc.getvalue()).decode()})
            self.assertEqual((code, meta2["titel"], meta2["quelle"]), (200, "notizen", "notizen.docx"))
            self.assertEqual(self.call("GET", f"/api/profiles/{pid}/texte/{meta2['id']}")[1]["text"], "Erster Absatz.\n\nZweiter.")
            self.assertEqual(self.call("POST", f"/api/profiles/{pid}/texte", {"dateiname": "x.exe", "daten_b64": "AA=="})[0], 400)
            self.assertFalse(self.call("PUT", f"/api/profiles/{pid}/texte/{meta2['id']}", {"stil": False})[1]["texte"][1]["stil"])
            self.assertIn("Familie Berger", profiles.style_samples(profiles.get(pid)))
            self.assertNotIn("Zweiter", profiles.style_samples(profiles.get(pid)))
            # in Welt einlesen → Impuls „text“ → Vorschlag (FakeLLM legt Neu-Ort an)
            code, r = self.call("POST", f"/api/w/{slug}/texte/einlesen", {"profil_id": pid, "text_id": meta["id"]})
            self.assertEqual((code, r["teile"]), (200, 1))
            for _ in range(100):
                job = next(j for j in self.call("GET", "/api/jobs")[1]["jobs"] if j["id"] == r["job"]["id"])
                if job["status"] != "laeuft":
                    break
                time.sleep(0.05)
            self.assertEqual(job["status"], "fertig", job["meldung"])
            imp = self.call("GET", f"/api/w/{slug}/impulses")[1]["impulse"][0]
            self.assertEqual((imp["kind"], imp["title"]), ("text", "Familie Berger"))
            self.assertEqual(profiles.get(pid)["texte"][0]["eingelesen"][0]["welt"], slug)
            # nichts löschen: Archiv und zurück
            p = self.call("POST", f"/api/profiles/{pid}/texte/{meta2['id']}/archivieren", {})[1]
            self.assertEqual((len(p["texte"]), len(p["texte_archiv"])), (1, 1))
            p = self.call("POST", f"/api/profiles/{pid}/texte/{meta2['id']}/wiederherstellen", {})[1]
            self.assertEqual((len(p["texte"]), len(p["texte_archiv"])), (2, 0))
            # Abschnitte und Formate
            parts = profiles.split_text(("Satz eins. " * 300 + "\n\n") * 10, size=5000)
            self.assertTrue(all(len(x) <= 5000 for x in parts) and len(parts) >= 7)
            self.assertEqual(textimport.extract("a.html", b"<p>Hallo</p><script>x</script><p>Welt &amp; mehr</p>"),
                             "Hallo\n\nWelt & mehr")
        finally:
            os.environ.pop("STORY_PROFILES", None)
            os.environ.pop("STORY_PROFILE_TEXTS", None)

    def test_full_flow_and_security(self):
        code, data = self.call("POST", "/api/worlds", {"name": "Testwelt Ä", "startbestand": True})
        self.assertEqual(code, 200)
        slug = data["slug"]
        self.assertEqual(slug, "testwelt-ae")
        # Sicherheit
        self.assertEqual(self.call("POST", "/api/worlds", {"name": "x"}, headers={"X-Story-World": "0"})[0], 403)
        self.assertEqual(self.call("POST", "/api/worlds", {"name": "x"}, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.call("GET", "/api/worlds", host="evil.example")[0], 403)
        # Impuls → KI → automatisch übernommen (Standard laut OFFENE_PUNKTE Nr. 7)
        def run_impulse(title):
            code, data = self.call("POST", f"/api/w/{slug}/impulses", {"title": title, "content": "Eine Station.",
                                                                       "kind": "ort", "ki_sofort": True})
            self.assertEqual(code, 200, data)
            for _ in range(100):
                jobs = self.call("GET", "/api/jobs")[1]["jobs"]
                if jobs and jobs[0]["status"] != "laeuft":
                    break
                threading.Event().wait(0.05)
            self.assertEqual(jobs[0]["status"], "fertig", jobs[0])
            return data["id"]
        run_impulse("Station")
        prompt = FakeLLM.requests[-1]["messages"][1]["content"]
        self.assertIn("Aureas", prompt)
        self.assertIn("Warpblase", prompt)
        proposals = self.call("GET", f"/api/w/{slug}/proposals")[1]["vorschlaege"]
        self.assertEqual((proposals[0]["summary"], proposals[0]["status"]), ("Ein neuer Ort.", "uebernommen"))
        # Mit manueller Freigabe
        self.assertEqual(self.call("POST", f"/api/w/{slug}/settings", {"auto_uebernehmen": False})[1]["auto_uebernehmen"], "0")
        run_impulse("Station 2")
        proposals = self.call("GET", f"/api/w/{slug}/proposals")[1]["vorschlaege"]
        self.assertEqual(proposals[0]["status"], "offen")
        self.assertEqual(self.call("GET", f"/api/w/{slug}/impulses")[1]["impulse"][0]["status"], "vorschlag")
        code, rep = self.call("POST", f"/api/w/{slug}/proposals/{proposals[0]['id']}/uebernehmen", {})
        self.assertEqual((code, rep["angelegt"]), (200, 1))
        rows = self.call("GET", f"/api/w/{slug}/rows/locations")[1]["rows"]
        self.assertEqual([r["name"] for r in rows], ["Neu-Ort", "Neu-Ort"])
        self.assertEqual(rows[0]["created_by"], "ki")
        impulses = self.call("GET", f"/api/w/{slug}/impulses")[1]["impulse"]
        self.assertEqual(impulses[0]["status"], "eingearbeitet")
        # Status und Konfiguration
        self.assertIn("quellen", self.call("GET", "/api/status")[1])
        # Suche und Sicherung
        hits = self.call("GET", f"/api/w/{slug}/search?q=vogel")[1]["treffer"]
        self.assertEqual(hits[0]["title"], "Aureas")
        self.assertEqual(self.call("POST", f"/api/w/{slug}/backup", {})[0], 200)
        # Einstellungen: Anbieter anlegen, prüfen, Modelle laden, Kette mit Ausweich-Modell
        fake_url = os.environ["STORY_LLM_BASE_URL"]
        code, data = self.call("POST", "/api/settings/providers", {"preset": "custom", "base_url": fake_url + "/",
                                                                   "api_key": "geheimer-schluessel-123"})
        self.assertEqual(code, 200, data)
        pid = data["id"]
        settings = self.call("GET", "/api/settings")[1]
        self.assertNotIn("geheimer-schluessel-123", json.dumps(settings))
        self.assertEqual(oct(os.stat(os.environ["STORY_CONFIG"]).st_mode & 0o777), "0o600")
        self.assertTrue(self.call("POST", f"/api/settings/providers/{pid}/pruefen", {})[1]["ok"])
        self.assertEqual(self.call("POST", f"/api/settings/providers/{pid}/modelle", {})[1]["anzahl"], 2)
        self.assertEqual(self.call("GET", f"/api/settings/providers/{pid}/modelle")[1]["modelle"], ["fake-a", "fake-b"])
        self.call("PUT", f"/api/settings/providers/{pid}", {"api_key": "falsch"})
        verify = self.call("POST", f"/api/settings/providers/{pid}/pruefen", {})[1]
        self.assertFalse(verify["ok"])
        self.assertIn("Schlüssel", verify["fehler"])
        self.call("PUT", f"/api/settings/providers/{pid}", {"api_key": "wieder-gut"})
        kette = [{"provider": pid, "model": "kaputt"}, {"provider": pid, "model": "fake-a"}]
        self.assertEqual(len(self.call("PUT", "/api/settings/tasks/weltenbau", {"kette": kette})[1]["kette"]), 2)
        test = self.call("POST", "/api/settings/tasks/weltenbau/test", {})[1]
        self.assertTrue(test["ok"], test)
        self.assertIn("fake-a", test["modell"])  # 1. Wahl kaputt → 2. Wahl springt ein
        # KI-Lauf mit Ausweich-Modell und Streaming wird vollständig protokolliert
        self.call("POST", f"/api/w/{slug}/settings", {"auto_uebernehmen": True})
        run_impulse("Station 3")
        laeufe = self.call("GET", f"/api/w/{slug}/runs")[1]["laeufe"]
        self.assertEqual((laeufe[0]["status"], laeufe[0]["progress"]), ("fertig", 100))
        detail = self.call("GET", f"/api/w/{slug}/runs/{laeufe[0]['id']}")[1]
        weg = " | ".join(st["text"] for st in detail["steps"])
        for teil in ("Kontext fertig", "1. Wahl fehlgeschlagen", "nächste Wahl springt ein", "2. Wahl: Anfrage",
                     "Antwort von", "Vorschlag geprüft", "Automatisch übernommen"):
            self.assertIn(teil, weg)
        self.assertEqual(detail["auftrag"].split("\n")[0], "Arbeite diesen Impuls des Nutzers in die Welt ein (Art: ort).")
        self.assertNotIn("STREAM-GEHEIM", json.dumps(detail))
        self.assertNotIn("response", detail)
        secret = self.call("GET", f"/api/w/{slug}/runs/{laeufe[0]['id']}", headers={"X-Reveal": "1"})[1]
        self.assertIn("STREAM-GEHEIM", secret["response"])
        self.assertEqual(secret["prompt"][0]["role"], "system")
        self.assertEqual(detail["vorschlag"]["status"], "uebernommen")
        self.assertEqual(len(laeufe), 3)  # zwei frühere Impulse + dieser
        self.assertEqual(self.call("POST", f"/api/settings/providers/{pid}/archivieren", {})[0], 200)
        settings = self.call("GET", "/api/settings")[1]
        self.assertEqual(settings["archiv"][0]["id"], pid)
        self.call("POST", f"/api/settings/providers/{pid}/wiederherstellen", {})
        self.assertEqual(self.call("PUT", "/api/settings/theme", {"active": "dunkel"})[1]["active"], "dunkel")
        # Einschübe per KI (Job läuft isoliert)
        self.assertEqual(self.call("POST", f"/api/w/{slug}/einschuebe/ki", {"anzahl": 3})[0], 200)
        # Validierungsfehler sind verständlich
        code, data = self.call("POST", f"/api/w/{slug}/rows/peoples", {"name": ""})
        self.assertEqual(code, 400)
        self.assertIn("Pflichtfeld", data["fehler"])




class FakePipelineLLM(BaseHTTPRequestHandler):
    calls = []
    prompts = []
    systems = []
    schwere = "niedrig"
    typ = "gegenwart"
    beschreibung = "x"
    refuse = 0
    broken_strang = 0  # so viele Planer-Antworten liefern einen Strang, der sich nicht anlegen lässt

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        system = body["messages"][0]["content"]
        user = body["messages"][-1]["content"]
        FakePipelineLLM.prompts.append(user)
        FakePipelineLLM.systems.append(system)
        if "ERZÄHLPROFIL" in system and "Lektorin" in system:
            role = "profil"
            content = json.dumps({"profil": {"zusammenfassung": "Ruhig und genau.", "stimme": "PROFIL-STIMME warm, leise",
                                             "humor": "trocken"}, "nachfragen": ["Magst du offene Enden?"]})
        elif "Du bist der Weltenbauer" in system:
            role = "weltenbau"
            content = json.dumps({"zusammenfassung": "Hintergrund", "operationen": [
                {"aktion": "anlegen", "tabelle": "events", "sichtbarkeit": "backstage",
                 "felder": {"title": "Menschen gründen Kolonie", "world_time": 100.5}}]})
        elif "Planer" in system:
            role = "planer"
            content = json.dumps({
                "titel": "Staub über Kesh", "strang": {"ref": "markt"}, "typ": FakePipelineLLM.typ, "welt_start": 100, "welt_ende": 101,
                "figuren": [{"ref": "tavi"}], "kapitel": [{"titel": "Ankunft", "inhalt": "Tavi kommt an.", "woerter": 800}],
                "einstieg": {"figur": "Tavi", "wer": "junge Händlerin", "gefuehl": "genervt", "lage": "kommt zu spät",
                             "ort": "Markt von Kesh"},
                "einschuebe": [], "andeutungen": "GEHEIME-ANDEUTUNG", "ende_uebergabe": "Tavi blickt zum Himmel.",
                "vorbereitung": [
                    {"aktion": "anlegen", "tabelle": "characters", "ref": "tavi", "felder": {"name": "Tavi", "people_id": 2}},
                    {"aktion": "anlegen", "tabelle": "threads", "ref": "markt",
                     "felder": {"title": "Der Federmarkt", "level": "mikro", "world_time_cursor": 100, "pov_id": "@tavi",
                                "abweichung": 1}}]})
            if FakePipelineLLM.broken_strang > 0:
                FakePipelineLLM.broken_strang -= 1
                content = content.replace('"level": "mikro"', '"level": "ultra"')
        elif "Kontinuitätsprüfer" in system:
            role = "pruefer"
            content = json.dumps({"probleme": [{"schwere": FakePipelineLLM.schwere, "kapitel": 1,
                                                "beschreibung": FakePipelineLLM.beschreibung,
                                                "korrektur": "y"}]})
        elif "Lektor" in system:
            role = "lektor"
            content = user.split("\n\nKAPITEL:\n", 1)[1].replace("Staub", "Sternenstaub", 1)
        elif "Archivar" in system:
            role = "archivar"
            content = json.dumps({"folgen_zusammenfassung": "Tavi erreicht den Markt.", "ende_uebergabe": "Blick zum Himmel.",
                                  "einschuebe_verwendet": [], "raetsel_status": [{"id": 1, "status": "angedeutet"}],
                                  "ripples": [{"quelle_ereignis": "@ankunft", "ziel_strang_id": 1,
                                               "fruehestens_weltzeit": 105, "wirkung": "Gerüchte erreichen die Stadt"}],
                                  "operationen": [{"aktion": "anlegen", "tabelle": "locations",
                                                   "felder": {"name": "Federmarkt von Kesh", "kind": "sonstiges"}},
                                                  {"aktion": "anlegen", "tabelle": "events", "ref": "ankunft",
                                                   "felder": {"title": "Ankunft in Kesh", "world_time": 100.2}}]})
        elif FakePipelineLLM.refuse > 0:
            FakePipelineLLM.refuse -= 1
            role = "autor"
            content = "Es tut mir leid, aber dabei kann ich nicht helfen."
        else:
            role = "autor"
            content = "[Erzähler] " + " ".join(["Staub lag über dem Markt."] * 120) + "\n[Tavi] Wir sind da.\nnoch ein Satz."
        FakePipelineLLM.calls.append((role, body.get("model")))
        out = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class PlanAusfuehrbarTests(unittest.TestCase):
    """Lauf #82: Strang-Operation scheiterte still, Figuren blieben verwaist, kein neuer Versuch."""

    def _run(self, patch_check=False):
        from unittest import mock
        from story_world import episodes, runs, worlds
        server = HTTPServer(("127.0.0.1", 0), FakePipelineLLM)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        tmp = tempfile.TemporaryDirectory()
        env = {"STORY_WORLDS_DIR": tmp.name, "STORY_CONFIG": os.path.join(tmp.name, "c.json"),
               "STORY_LLM_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}/v1", "STORY_LLM_MODEL": "pipe"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            slug = worlds.create_world("Plan")
            with worlds.open_world(slug) as conn:
                FakePipelineLLM.broken_strang = 1
                if patch_check:  # Probelauf ausgeschaltet → Rücknahme + Neuplanung muss greifen
                    with mock.patch.object(episodes, "plan_check", lambda conn, p: episodes._validate_plan(p)):
                        eid = episodes.produce(conn, words=800)
                else:
                    eid = episodes.produce(conn, words=800)
                ep = episodes.get_episode(conn, eid)
                steps = " | ".join(s["text"] for s in runs.get_run(conn, ep["run_id"])["steps"])
                tavis = conn.execute("SELECT COUNT(*) FROM characters WHERE name = 'Tavi'").fetchone()[0]
                thread = conn.execute("SELECT abweichung FROM threads WHERE title = 'Der Federmarkt'").fetchone()
                proposals = [r[0] for r in conn.execute("SELECT status FROM proposals WHERE task LIKE 'Folgenplanung%'")]
                return ep, steps, tavis, thread, proposals
        finally:
            FakePipelineLLM.broken_strang = 0
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            server.shutdown()
            server.server_close()
            tmp.cleanup()

    def test_select_accepts_numbers(self):
        conn = fresh()
        tid = service.create_row(conn, "threads", {"title": "T", "level": "mikro", "world_time_cursor": 1,
                                                  "abweichung": 1}, actor="ki")
        self.assertEqual(str(conn.execute("SELECT abweichung FROM threads WHERE id = ?", (tid,)).fetchone()[0]), "1")

    def test_check_operations_rolls_back(self):
        conn = fresh()
        before = conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0]
        report = service.check_operations(conn, [
            {"aktion": "anlegen", "tabelle": "characters", "ref": "a", "felder": {"name": "Probe"}},
            {"aktion": "anlegen", "tabelle": "threads", "ref": "s", "felder": {"title": "S", "level": "ultra",
                                                                               "world_time_cursor": 1}}])
        self.assertEqual(report["angelegt"], 1)
        self.assertIn("s", report["fehler_refs"])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM characters").fetchone()[0], before)

    def test_planner_corrects_before_saving(self):
        ep, steps, tavis, thread, proposals = self._run()
        self.assertEqual(ep["status"], "fertig")
        self.assertIn("ließe sich nicht anlegen", steps)
        self.assertIn("Korrekturrunde", steps)
        self.assertEqual(tavis, 1)  # Probelauf hat nichts hinterlassen
        self.assertEqual(str(thread[0]), "1")
        self.assertEqual(proposals, ["uebernommen"])

    def test_broken_preparation_rolled_back_and_replanned(self):
        ep, steps, tavis, thread, proposals = self._run(patch_check=True)
        self.assertEqual(ep["status"], "fertig")
        self.assertIn("Vorbereitung zurückgenommen, Planer plant neu", steps)
        self.assertIn("übersprungen", steps)  # Grund steht im Protokoll
        self.assertEqual(tavis, 1)  # erste Vorbereitung komplett zurückgenommen
        self.assertEqual(sorted(proposals), ["uebernommen", "verworfen"])


class EpisodePipelineTests(unittest.TestCase):
    def test_produce_episode_end_to_end(self):
        from story_world import episodes, runs, worlds
        server = HTTPServer(("127.0.0.1", 0), FakePipelineLLM)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as tmp:
            env = {"STORY_WORLDS_DIR": tmp, "STORY_CONFIG": os.path.join(tmp, "c.json"),
                   "STORY_LLM_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}/v1", "STORY_LLM_MODEL": "pipe"}
            old = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
            try:
                slug = worlds.create_world("Pipeline")
                with worlds.open_world(slug) as conn:
                    eid = episodes.produce(conn, "etwas Ruhiges", words=800)
                    ep = episodes.get_episode(conn, eid)
                    self.assertEqual((ep["title"], ep["status"], ep["release_nr"]), ("Staub über Kesh", "fertig", 1))
                    self.assertTrue(ep["text"].startswith("[Erzähler] Sternenstaub"))  # Lektor hat übernommen
                    self.assertEqual(ep["segmente"][-1], {"typ": "character", "sprecher": "Tavi", "text": "Wir sind da. noch ein Satz."})
                    self.assertEqual(ep["summary"], "Tavi erreicht den Markt.")
                    self.assertNotIn("plan", ep)
                    self.assertIn("GEHEIME-ANDEUTUNG", json.dumps(episodes.get_episode(conn, eid, reveal=True)["plan"]))
                    thread = conn.execute("SELECT world_time_cursor, status, pov_id FROM threads").fetchone()
                    self.assertEqual((thread[0], thread[1]), (101.0, "aktiv"))
                    self.assertIsNotNone(conn.execute("SELECT 1 FROM locations WHERE name='Federmarkt von Kesh'").fetchone())
                    run = runs.get_run(conn, ep["run_id"])
                    self.assertEqual((run["status"], run["progress"]), ("fertig", 100))
                    weg = " | ".join(s["text"] for s in run["steps"])
                    for teil in ("Plan: „Staub über Kesh“", "Vorbereitung übernommen", "Autor, Kapitel 1/1",
                                 "Prüfer: 1 Hinweise", "Lektorat abgeschlossen", "Folge #1 gespeichert", "Archivar",
                                 "1 Ripples", "Weltentwicklung", "dasselbe Modell wie der Autor"):
                        self.assertIn(teil, weg)
                    self.assertNotIn("GEHEIME-ANDEUTUNG", json.dumps(run))
                    name, text = episodes.export_text(conn, eid)
                    self.assertTrue(name.startswith("Folge_001_Staub"))
                    self.assertIn("[Tavi] Wir sind da.", text)
                    name, data = episodes.export_pdf(conn, eid)
                    self.assertTrue(name.startswith("Folge_001_Staub") and name.endswith(".pdf"))
                    self.assertTrue(data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF"))
                    self.assertEqual(conn.execute("SELECT effect, done FROM ripples").fetchone()[0], "Gerüchte erreichen die Stadt")
                    self.assertEqual(conn.execute("SELECT status FROM mysteries WHERE id = 1").fetchone()[0], "angedeutet")
                    self.assertEqual(json.loads(conn.execute("SELECT metrics FROM episodes").fetchone()[0])["kanon_score"], 0)
                    self.assertEqual(conn.execute("SELECT visibility FROM events WHERE title='Menschen gründen Kolonie'").fetchone()[0],
                                     "backstage")
                    # Zweite Folge: Rückblende, Prüfer findet Schweres → Freigabe nötig; Übergabe fließt in den Autor
                    FakePipelineLLM.typ, FakePipelineLLM.schwere = "rueckblende", "hoch"
                    FakePipelineLLM.prompts.clear()
                    eid2 = episodes.produce(conn, words=800)
                    ep2 = episodes.get_episode(conn, eid2)
                    self.assertEqual((ep2["release_nr"], ep2["status"], ep2["type"]), (2, "freigabe", "rueckblende"))
                    author_prompt = [p for p in FakePipelineLLM.prompts if "SCHREIBE JETZT" in p][0]
                    self.assertIn("Blick zum Himmel.", author_prompt)  # Ende-Übergabe der ersten Folge
                    self.assertIn("WELTZUSTAND ZU BEGINN DIESER FOLGE", author_prompt)
                    self.assertEqual(episodes._episode_history(conn)[-1]["release_nr"], 1)  # Freigabe-Folge zählt noch nicht
                FakePipelineLLM.typ, FakePipelineLLM.schwere = "gegenwart", "niedrig"
                self.assertEqual([c[0] for c in FakePipelineLLM.calls[:6]],
                                 ["planer", "autor", "pruefer", "lektor", "archivar", "weltenbau"])
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                server.shutdown()
                server.server_close()


class TimelineTests(unittest.TestCase):
    def setUp(self):
        from story_world import timeline
        self.t = timeline
        self.db = fresh()
        seed_from_rules(self.db)
        c = lambda tbl, **kw: service.create_row(self.db, tbl, kw)
        sool = c("locations", name="Sool", kind="system")
        self.erde = c("locations", name="Erde", kind="planet", parent_id=sool)
        self.mars = c("locations", name="Mars", kind="planet", parent_id=sool)
        self.hh = c("locations", name="Hamburg", kind="stadt", parent_id=self.erde)
        c("distances", from_location_id=self.erde, to_location_id=self.mars, distance=200)
        c("technologies", name="Warpblase", kind="antrieb", speed=100, prep_time=1)
        self.tavi = c("characters", name="Tavi")

    def tearDown(self):
        self.db.close()

    def test_calendar_names_never_day_numbers(self):
        service.update_row(self.db, "calendars", 1, {"epoch": 0, "year_length": 360, "cycles_per_year": 4,
                                                     "year_names": "Eisfalke\nSonnenkranich", "cycle_names": ""})
        text = self.t.format_all(self.db, 450)[0]["text"]
        self.assertEqual(text, "Sonnenkranich, zweiter Zyklus")

    def test_travel_inherits_parent_distances_but_not_shared_system(self):
        r = self.t.travel(self.db, self.hh, self.mars)
        self.assertEqual((r["entfernung"], r["reisezeiten"][0]["dauer"]), (200.0, 3.0))
        self.assertEqual(self.t.shortest(self.db, self.erde, self.mars)[0], 200.0)
        self.assertEqual(self.t.shortest(self.db, self.hh, self.erde)[0], 0.0)

    def test_consistency_travel_and_death(self):
        ins = "INSERT INTO character_presence (character_id, location_id, world_start, world_end) VALUES (?, ?, ?, ?)"
        self.db.execute(ins, (self.tavi, self.hh, 0, 10))
        self.db.execute(ins, (self.tavi, self.mars, 11, 20))  # 1 Einheit, nötig sind 3
        self.db.execute("INSERT INTO character_status_history (character_id, world_time, status) VALUES (?, 15, 'tot')",
                        (self.tavi,))
        self.db.execute("INSERT INTO knowledge (character_id, content, since_world_time, source, status) "
                        "VALUES (?, 'x', 18, 'y', 'wahr')", (self.tavi,))
        arts = sorted(i["art"] for i in self.t.check(self.db)["probleme"])
        self.assertEqual(arts, ["Reise", "Status"])
        service.update_row(self.db, "characters", self.tavi, {"name": "Tavi"})
        self.db.execute("UPDATE characters SET visibility = 'backstage' WHERE id = ?", (self.tavi,))
        hidden = self.t.check(self.db)
        self.assertEqual((hidden["probleme"], hidden["verborgen"]), ([], 2))

    def test_world_state_hides_future(self):
        service.create_row(self.db, "events", {"title": "Früh", "world_time": 5})
        service.create_row(self.db, "events", {"title": "Spät", "world_time": 50})
        state = self.t.world_state(self.db, 10)
        self.assertEqual([e["titel"] for e in state["ereignisse"]], ["Früh"])


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>Neue Batterie speichert Sonnenstrom</title><link>https://x.example/1</link><guid>g1</guid>
<description>&lt;p&gt;Forscher zeigen &amp;amp; erkl&#228;ren.&lt;/p&gt;</description></item>
<item><title>Flut in Norddeutschland</title><link>https://x.example/2</link></item></channel></rss>"""
ATOM_FEED = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>a1</id><title>Atom-Meldung</title>
<link href="https://y.example/a"/><summary>Kurz</summary></entry></feed>"""


class NewsAndDailyTests(unittest.TestCase):
    def test_parse_fetch_dedupe_and_impulses(self):
        from story_world import news
        db = fresh()
        self.assertEqual([i["title"] for i in news.parse(ATOM_FEED)], ["Atom-Meldung"])
        news.add_source(db, "Feed", "https://x.example/rss")
        news.add_source(db, "Kaputt", "https://kaputt.example/rss")
        with self.assertRaises(service.ValidationError):
            news.add_source(db, "Doppelt", "https://x.example/rss")

        def downloader(url):
            if "kaputt" in url:
                raise news.NewsError("nicht erreichbar")
            return RSS
        first = news.fetch_all(db, downloader)
        self.assertEqual((first["neu"], len(first["fehler"])), (2, 1))
        self.assertEqual(news.fetch_all(db, downloader)["neu"], 0)  # keine Dubletten
        created = news.to_impulses(db, 1)
        impulse = db.execute("SELECT kind, title, content FROM impulses WHERE id = ?", (created[0],)).fetchone()
        self.assertEqual(impulse["kind"], "nachricht")
        self.assertEqual(len(news.to_impulses(db, 5)), 1)  # nur die noch unbenutzte Meldung
        summary = db.execute("SELECT summary FROM news_items WHERE guid='g1'").fetchone()[0]
        self.assertEqual(summary, "Forscher zeigen & erklären.")
        db.close()

    def test_daily_due_once_per_day(self):
        from datetime import datetime
        from story_world import daily
        db = fresh()
        now = datetime(2026, 11, 8, 20, 30)
        self.assertFalse(daily.due(db, now))
        service.set_setting(db, "auto_folge", True)
        service.set_setting(db, "auto_uhrzeit", "21:00")
        self.assertFalse(daily.due(db, now))
        service.set_setting(db, "auto_uhrzeit", "20:00")
        self.assertTrue(daily.due(db, now))
        service.set_meta(db, "auto_letzter_lauf", "2026-11-08")
        self.assertFalse(daily.due(db, now))
        with self.assertRaises(service.ValidationError):
            service.set_setting(db, "auto_uhrzeit", "25:00")
        db.close()


class AudioTests(unittest.TestCase):
    def test_render_with_voices_lexicon_and_json_export(self):
        import wave as wavemod
        from story_world import audio, runs, worlds
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("STORY_WORLDS_DIR")
            old_config = os.environ.get("STORY_CONFIG")
            os.environ["STORY_WORLDS_DIR"] = tmp
            os.environ["STORY_CONFIG"] = os.path.join(tmp, "c.json")  # ohne TTS-Server → macOS-Stimmen im Export
            try:
                slug = worlds.create_world("Audio")
                with worlds.open_world(slug) as conn:
                    conn.execute("INSERT INTO threads (id, level, world_time_cursor, title) VALUES (1, 'mikro', 0, 'S')")
                    conn.execute("INSERT INTO episodes (release_nr, thread_id, world_start, world_end, type, title, text, status) "
                                 "VALUES (1, 1, 0, 1, 'gegenwart', 'Probe', ?, 'fertig')",
                                 ("[Erzähler] Die Aureas landen.\n\n[Tavi] Hallo Aureas.\n\n[Ole] Moin.",))
                    service.create_row(conn, "pronunciations", {"term": "Aureas", "spoken": "Ah-u-re-as"})
                    service.create_row(conn, "characters", {"name": "Ole", "voice_id": "Markus"})
                    spoken = []

                    def synth(text, voice, rate, path):
                        spoken.append((text, voice))
                        with wavemod.open(str(path), "wb") as w:
                            w.setnchannels(1)
                            w.setsampwidth(2)
                            w.setframerate(22050)
                            w.writeframes(b"\x00\x00" * 2205)
                    path = audio.render(conn, slug, 1, synth=synth, voice_list=["Anna", "Markus", "Petra"])
                    self.assertTrue(path.exists())
                    voices = dict((t, v) for t, v in spoken)
                    self.assertEqual(voices["Die Ah-u-re-as landen."], "Anna")        # Erzähler + Lexikon
                    self.assertEqual(voices["Hallo Ah-u-re-as."], "Markus")           # erste freie Stimme
                    self.assertEqual(voices["Moin."], "Markus")                       # hinterlegte Stimme
                    # Auf macOS wird mit afconvert eine .m4a erzeugt; die WAV liegt dann in _wav (nicht gelöscht)
                    wav = path if path.suffix == ".wav" else path.parent / "_wav" / path.with_suffix(".wav").name
                    with wavemod.open(str(wav), "rb") as w:
                        self.assertGreater(w.getnframes(), 2205 * 4)                  # 4 Teile + Pausen
                    self.assertEqual(audio.audio_file(conn, 1), path.resolve())
                    data = audio.export_json(conn, 1, voice_list=["Anna", "Markus", "Petra"])
                    self.assertEqual([s["sprecher"] for s in data["segmente"]], ["Erzähler", "Tavi", "Ole"])
                    self.assertEqual([s["stimme"] for s in data["segmente"]], ["Anna", "Markus", "Markus"])
                    self.assertEqual(data["erzaehler_stimme"], "Anna")
                    self.assertEqual(data["sprache"], "de-DE")
                    self.assertTrue(all(s["sprache"] == "de-DE" for s in data["segmente"]))
                    data = audio.export_json(conn, 1, voice_list=[{"name": "Anna", "lang": "de_AT"}])
                    self.assertEqual(data["segmente"][0]["sprache"], "de-AT")
                    self.assertEqual(data["sprecher"]["Ole"], {"stimme": "Markus", "sprache": "de-DE"})  # externe Stimme bleibt
                    self.assertEqual(runs.list_runs(conn)[0]["status"], "fertig")
            finally:
                if old is None:
                    os.environ.pop("STORY_WORLDS_DIR", None)
                else:
                    os.environ["STORY_WORLDS_DIR"] = old
                if old_config is None:
                    os.environ.pop("STORY_CONFIG", None)
                else:
                    os.environ["STORY_CONFIG"] = old_config


class RestoreTests(unittest.TestCase):
    def test_backup_restore_as_new_world(self):
        from story_world import migrations, worlds
        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("STORY_WORLDS_DIR")
            os.environ["STORY_WORLDS_DIR"] = tmp
            try:
                slug = worlds.create_world("Original")
                with worlds.open_world(slug) as conn:
                    backup = migrations.backup(conn, worlds.path_for(slug), "manuell")
                    service.create_row(conn, "peoples", {"name": "Nach der Sicherung"})
                self.assertEqual(worlds.list_backups()[0]["datei"], backup.name)
                with self.assertRaises(service.ValidationError):
                    worlds.restore_backup("../" + slug + ".sqlite3")
                restored = worlds.restore_backup(backup.name)
                self.assertNotEqual(restored, slug)
                with worlds.open_world(restored) as conn:
                    names = [r[0] for r in conn.execute("SELECT name FROM peoples ORDER BY id")]
                    self.assertEqual(names, ["Menschen", "Aureas"])
                    self.assertIn("wiederhergestellt", service.meta(conn)["name"])
                with worlds.open_world(slug) as conn:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM peoples").fetchone()[0], 3)
            finally:
                if old is None:
                    os.environ.pop("STORY_WORLDS_DIR", None)
                else:
                    os.environ["STORY_WORLDS_DIR"] = old


class RetrievalTests(unittest.TestCase):
    def test_search_respects_time_and_spoilers(self):
        from story_world import retrieval
        db = fresh()
        db.execute("INSERT INTO threads (id, level, world_time_cursor) VALUES (1, 'mikro', 0)")
        db.execute("INSERT INTO episodes (release_nr, thread_id, world_start, world_end, type, title, summary, status) "
                   "VALUES (1, 1, 10, 11, 'gegenwart', 'Federmarkt', 'Tavi verkauft Federn auf Kesh.', 'fertig')")
        service.create_row(db, "events", {"title": "Federsturm über Kesh", "world_time": 50})
        service.create_row(db, "events", {"title": "Geheimer Federschmuggel", "world_time": 5}, actor="ki", visibility="backstage")
        hits = [h["titel"] for h in retrieval.search(db, "Federn Kesh", until=20)]
        self.assertIn("Folge 1: Federmarkt", hits)
        self.assertNotIn("Federsturm über Kesh", hits)        # liegt nach dem Zeitpunkt
        self.assertNotIn("Geheimer Federschmuggel", hits)     # Backstage
        self.assertIn("Geheimer Federschmuggel", [h["titel"] for h in retrieval.search(db, "Federschmuggel", reveal=True)])
        db.close()


class ProfileAndGenreTests(unittest.TestCase):
    def test_interview_profile_genre_in_pipeline(self):
        from story_world import episodes, profiles, worlds
        server = HTTPServer(("127.0.0.1", 0), FakePipelineLLM)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as tmp:
            env = {"STORY_WORLDS_DIR": tmp, "STORY_CONFIG": os.path.join(tmp, "c.json"),
                   "STORY_PROFILES": os.path.join(tmp, "p.json"),
                   "STORY_LLM_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}/v1", "STORY_LLM_MODEL": "pipe"}
            old = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
            try:
                p = profiles.create("Ralf")
                with self.assertRaises(profiles.ProfileError):
                    profiles.analyze(p["id"])  # zu wenige Antworten
                profiles.save_answers(p["id"], {"fuer_wen": "Kinder, 7", "humor": "trocken", "genres": "Grusel",
                                                "tabus": "Gewalt", "unbekannt": "x"})
                done = profiles.analyze(p["id"])
                self.assertEqual(done["status"], "fertig")
                self.assertEqual(done["nachfragen"], [{"frage": "Magst du offene Enden?", "antwort": ""}])
                self.assertNotIn("unbekannt", done["antworten"])
                self.assertEqual(oct(os.stat(env["STORY_PROFILES"]).st_mode & 0o777), "0o600")
                profiles.save_followups(p["id"], [{"frage": "Magst du offene Enden?", "antwort": "Nein"}])
                profiles.edit_profile(p["id"], {"humor": "sehr trocken"})
                self.assertIn("sehr trocken", profiles.style_block(profiles.get(p["id"])))

                slug = worlds.create_world("Genre")
                with worlds.open_world(slug) as conn:
                    kids = conn.execute("SELECT id FROM genres WHERE name = 'Grusel für Kinder'").fetchone()[0]
                    FakePipelineLLM.systems.clear()
                    FakePipelineLLM.prompts.clear()
                    eid = episodes.produce(conn, words=800, genre_id=kids, profile_id=p["id"])
                    ep = episodes.get_episode(conn, eid)
                    self.assertEqual(ep["genre"], "Grusel für Kinder")
                    author_system = [x for x in FakePipelineLLM.systems if "Autor einer" in x][0]
                    self.assertIn("PROFIL-STIMME", author_system)
                    self.assertIn("Grusel für Kinder", author_system)
                    check_prompt = [x for x in FakePipelineLLM.prompts if "Verstöße gegen Tabus" in x][0]
                    self.assertIn("Tod, Verletzungen oder Gewalt im Detail", check_prompt)
                    service.set_meta(conn, "nutzer_id", p["id"])  # täglicher Lauf nutzt den zuletzt aktiven Menschen
                    FakePipelineLLM.systems.clear()
                    episodes.produce(conn, words=800)
                    self.assertTrue(any("PROFIL-STIMME" in x for x in FakePipelineLLM.systems))
                profiles.archive(p["id"])
                self.assertEqual(profiles.list_profiles()["archiv"][0]["name"], "Ralf")
                profiles.restore(p["id"])
                self.assertEqual(profiles.list_profiles()["profiles"][0]["name"], "Ralf")
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                server.shutdown()
                server.server_close()


class TabooAgeAndStoryPageTests(unittest.TestCase):
    def test_taboo_is_warning_refusal_falls_back_age_by_author(self):
        from story_world import episodes, runs, worlds
        server = HTTPServer(("127.0.0.1", 0), FakePipelineLLM)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as tmp:
            env = {"STORY_WORLDS_DIR": tmp, "STORY_CONFIG": os.path.join(tmp, "c.json"),
                   "STORY_PROFILES": os.path.join(tmp, "p.json"),
                   "STORY_LLM_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}/v1", "STORY_LLM_MODEL": "pipe"}
            old = {k: os.environ.get(k) for k in env}
            os.environ.update(env)
            FakePipelineLLM.schwere, FakePipelineLLM.beschreibung, FakePipelineLLM.refuse = "hoch", "Tabu: Gewalt im Detail", 1
            try:
                slug = worlds.create_world("Tabu")
                with worlds.open_world(slug) as conn:
                    horror = conn.execute("SELECT id FROM genres WHERE name = 'Horror'").fetchone()[0]
                    FakePipelineLLM.systems.clear()
                    eid = episodes.produce(conn, words=800, genre_id=horror, age_rating="ab 16")
                    ep = episodes.get_episode(conn, eid)
                    self.assertEqual(ep["status"], "fertig")  # Tabu blockiert nicht
                    self.assertEqual(ep["age_rating"], "ab 16")
                    self.assertEqual(ep["metrics"]["warn_anzahl"], 1)
                    self.assertNotIn("warnungen", ep["metrics"])  # Details nur mit Backstage
                    self.assertEqual(ep["metrics"]["warn_arten"], ["Tabu"])
                    full = episodes.get_episode(conn, eid, reveal=True)
                    self.assertEqual(full["metrics"]["warnungen"], ["Tabu: Gewalt im Detail"])
                    self.assertEqual(full["check_report"][0]["schwere"], "mittel")
                    author = [x for x in FakePipelineLLM.systems if "Autor einer" in x][0]
                    self.assertIn("ALTERSFREIGABE (vom Autor festgelegt", author)
                    steps = json.dumps(runs.get_run(conn, ep["run_id"]), ensure_ascii=False)
                    self.assertIn("verweigert den Inhalt", steps)
                    # neue Geschichte behält ihr Genre, Seite listet sie
                    story = episodes.stories(conn)[0]
                    self.assertEqual((story["genre"], story["folgen"], story["letzte"]["age_rating"]), ("Horror", 1, "ab 16"))
                    # schwere Kanon-Probleme ohne Tabu bleiben Freigabe-Pflicht
                    FakePipelineLLM.beschreibung = "Figur an zwei Orten"
                    eid2 = episodes.produce(conn, words=800)
                    self.assertEqual(episodes.get_episode(conn, eid2)["status"], "freigabe")
                self.assertTrue(episodes._refusal("I'm sorry, but I can't help with that."))
                self.assertFalse(episodes._refusal("[Erzähler] Es tut mir leid, sagte Tavi leise. " + "Staub. " * 300))
            finally:
                FakePipelineLLM.schwere, FakePipelineLLM.beschreibung, FakePipelineLLM.refuse = "niedrig", "x", 0
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
                server.shutdown()



class PickyModel(BaseHTTPRequestHandler):
    """Simuliert neuere Modelle: lehnt max_tokens ab, denkt ohne Antwort, wenn das Budget klein ist."""
    bodies = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        PickyModel.bodies.append(body)
        if body["model"] == "picky" and "max_tokens" in body:
            out, code = json.dumps({"error": {"message": "Unsupported parameter: 'max_tokens' is not supported with this "
                                              "model. Use 'max_completion_tokens' instead."}}), 400
        elif body["model"] == "thinker" and body.get("max_tokens", 0) < 10000:
            out, code = json.dumps({"choices": [{"message": {"content": "", "reasoning_content": "hmm " * 50},
                                                 "finish_reason": "length"}]}), 200
        elif body["model"] == "cutter" and body.get("max_tokens", 0) < 10000:
            out, code = json.dumps({"choices": [{"message": {"content": '{"titel": "Unter dem Wa'},
                                                 "finish_reason": "length"}]}), 200
        elif body["model"] == "empty":
            out, code = json.dumps({"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}), 200
        else:
            out, code = json.dumps({"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}]}), 200
        out = out.encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class ProviderRobustnessTests(unittest.TestCase):
    def test_params_budget_empty_and_duplicates(self):
        from story_world import providers
        server = HTTPServer(("127.0.0.1", 0), PickyModel)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            prov = {"id": "x", "name": "Fake", "type": "openai", "api_key": "k",
                    "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1"}
            msgs = [{"role": "user", "content": "hi"}]
            logs = []
            text, used = providers.complete(msgs, chain=[(prov, "picky")], log=lambda t, l="info": logs.append(t))
            self.assertEqual((text, used), ('{"ok": true}', "Fake · picky"))
            self.assertIn("max_completion_tokens", PickyModel.bodies[-1])
            PickyModel.bodies.clear()
            providers.complete(msgs, chain=[(prov, "picky")])  # gelernt: direkt richtig
            self.assertEqual(len(PickyModel.bodies), 1)
            text, _ = providers.complete(msgs, chain=[(prov, "thinker")], log=lambda t, l="info": logs.append(t))
            self.assertEqual(text, '{"ok": true}')
            self.assertTrue(any("Token-Budget" in x for x in logs))
            text, _ = providers.complete(msgs, chain=[(prov, "cutter")])  # abgeschnittenes JSON → größeres Budget
            self.assertEqual(text, '{"ok": true}')
            PickyModel.bodies.clear()
            providers.complete(msgs, chain=[(prov, "cutter")])
            self.assertEqual(PickyModel.bodies[0]["max_tokens"], 32000)  # gelernt
            logs.clear()
            text, used = providers.complete(msgs, chain=[(prov, "empty"), (prov, "empty"), (prov, "ok")],
                                            log=lambda t, l="info": logs.append(t))
            self.assertEqual(used, "Fake · ok")
            self.assertEqual(sum("Wahl: Anfrage" in x for x in logs), 2)  # doppeltes Modell nur einmal
            self.assertTrue(any("Leere Antwort" in x for x in logs))
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
