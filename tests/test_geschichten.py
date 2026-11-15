import json
import unittest

from story_world import episodes, service
from story_world.database import connect
from story_world.migrations import migrate


class GeschichteDetailTests(unittest.TestCase):
    def test_wer_wo_wohin(self):
        conn = connect(":memory:")
        migrate(conn)
        iva = service.create_row(conn, "characters", {"first_name": "Iva", "last_name": "Morell", "role": "Pilotin"})
        kael = service.create_row(conn, "characters", {"first_name": "Kael", "last_name": "Duur"})
        geheim = service.create_row(conn, "characters", {"name": "Schattenmann"}, visibility="backstage")
        service.create_row(conn, "characters", {"first_name": "Ohne", "last_name": "Auftritt"})
        planet = service.create_row(conn, "locations", {"name": "Merid", "kind": "planet"})
        basis = service.create_row(conn, "locations", {"name": "Küstenbasis Merid", "kind": "stadt", "parent_id": planet})
        hafen = service.create_row(conn, "locations", {"name": "Nordhafen", "kind": "stadt", "parent_id": planet})
        tid = service.create_row(conn, "threads", {"title": "Heimkehr", "level": "mikro", "world_time_cursor": 10,
                                                   "premise": "Iva kehrt heim.", "pov_id": iva, "location_id": basis})
        conn.execute("INSERT INTO episodes (release_nr, thread_id, world_start, world_end, type, text, end_handoff, title, "
                     "summary, status, plan) VALUES (1, ?, 0, 5, 'gegenwart', 'x', 'Kael wartet im Nordhafen.', 'Ankunft', "
                     "'Iva trifft Kael Duur.', 'fertig', ?)", (tid, json.dumps({"figuren": [{"id": kael}, {"id": geheim}]})))
        d = episodes.story_detail(conn, tid)
        self.assertEqual([f["anzeige"] for f in d["figuren"]], ["Iva Morell", "Kael Duur"])
        self.assertTrue(d["figuren"][0]["pov"])
        self.assertEqual([(o["name"], o["haupt"]) for o in d["orte"]], [("Küstenbasis Merid", True), ("Nordhafen", False)])
        self.assertEqual(d["orte"][0]["pfad"], "Merid › Küstenbasis Merid")
        self.assertEqual(d["zuletzt"]["uebergabe"], "Kael wartet im Nordhafen.")
        self.assertNotIn("ripples", d)
        self.assertIn("Schattenmann", [f["anzeige"] for f in episodes.story_detail(conn, tid, reveal=True)["figuren"]])
        with self.assertRaises(LookupError):
            episodes.story_detail(conn, 999)


if __name__ == "__main__":
    unittest.main()
