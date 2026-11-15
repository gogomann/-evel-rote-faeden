import unittest

from story_world import service
from story_world.database import connect, initialize
from story_world.migrations import LATEST_VERSION, migrate


def fresh():
    conn = connect(":memory:")
    migrate(conn)
    return conn


class FigurenTests(unittest.TestCase):
    def test_migration_teilt_bestehende_namen(self):
        conn = connect(":memory:")
        initialize(conn)
        conn.executemany("INSERT INTO characters (name) VALUES (?)", [("Iva Morell",), ("Kael ven Duur",), ("Wächter",)])
        conn.commit()
        migrate(conn)
        rows = conn.execute("SELECT name, first_name, last_name, gender FROM characters ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("Iva Morell", "Iva", "Morell", None),
                                                     ("Kael ven Duur", "Kael", "ven Duur", None),
                                                     ("Wächter", "Wächter", None, None)])
        cols = {r[1] for r in conn.execute("PRAGMA table_info(character_relations)")}
        self.assertTrue({"reason", "ended_world_time", "break_reason"} <= cols)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], LATEST_VERSION)

    def test_name_aus_vor_und_nachname(self):
        conn = fresh()
        cid = service.create_row(conn, "characters", {"first_name": "Iva", "last_name": "Morell", "gender": "weiblich"})
        self.assertEqual(service.get_row(conn, "characters", cid)["name"], "Iva Morell")
        # Nachname ändern: Name zieht mit, weil er bisher genau „Vorname Nachname“ war
        service.update_row(conn, "characters", cid, {"name": "Iva Morell", "first_name": "Iva", "last_name": "Kessler"})
        self.assertEqual(service.get_row(conn, "characters", cid)["name"], "Iva Kessler")
        # eigener Rufname bleibt stehen
        service.update_row(conn, "characters", cid, {"name": "Captain Iva"})
        service.update_row(conn, "characters", cid, {"name": "Captain Iva", "last_name": "Brandt"})
        self.assertEqual(service.get_row(conn, "characters", cid)["name"], "Captain Iva")
        # Lückenfüllen der KI ändert keinen vorhandenen Namen
        other = service.create_row(conn, "characters", {"name": "Doran"})
        service.update_row(conn, "characters", other, {"last_name": "Vex"}, actor="ki", reveal=True, only_empty=True)
        self.assertEqual(service.get_row(conn, "characters", other)["name"], "Doran")
        with self.assertRaises(service.ValidationError):
            service.create_row(conn, "characters", {"gender": "weiblich"})
        with self.assertRaises(service.ValidationError):
            service.create_row(conn, "characters", {"name": "X", "gender": "irgendwas"})

    def test_beziehung_zeigt_vor_und_nachname_grund_und_bruch(self):
        conn = fresh()
        a = service.create_row(conn, "characters", {"first_name": "Iva", "last_name": "Morell", "name": "Iva"})
        b = service.create_row(conn, "characters", {"first_name": "Kael", "last_name": "Duur"})
        rid = service.create_row(conn, "character_relations", {
            "character_id": a, "kind": "mentor", "other_id": b, "reason": "Flugschule", "since_world_time": 10,
            "ended_world_time": 40, "break_reason": "Verrat"})
        row = service.get_row(conn, "character_relations", rid)
        self.assertEqual(row["character_id__name"], "Iva Morell")
        self.assertEqual(row["__title"], "Iva Morell ist mentor von Kael Duur")
        d = service.character_dossier(conn, b)
        entry = d["beziehungen"][0]
        self.assertEqual((entry["name"], entry["grund"], entry["bruch"], entry["bruch_grund"]),
                         ("Iva Morell", "Flugschule", 40, "Verrat"))


if __name__ == "__main__":
    unittest.main()
