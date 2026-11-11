import sqlite3
import unittest

from story_world.database import character_at, connect, eligible_ripples, initialize, presence_conflicts


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")
        initialize(self.db)
        self.db.execute("INSERT INTO characters (id, name) VALUES (1, 'Testfigur')")
        self.db.executemany("INSERT INTO locations (id, name) VALUES (?, ?)", [(1, 'A'), (2, 'B')])

    def tearDown(self):
        self.db.close()

    def test_initialization_is_repeatable_and_foreign_keys_enforced(self):
        initialize(self.db)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO knowledge (character_id, content, since_world_time, source, status) VALUES (99, 'x', 1, 'y', 'wahr')")

    def test_character_snapshot_excludes_future_and_secret_truth(self):
        self.db.execute("INSERT INTO character_status_history (character_id, world_time, status) VALUES (1, 10, 'tot')")
        self.db.execute("INSERT INTO character_presence (character_id, location_id, world_start, world_end) VALUES (1, 1, 0, 10)")
        self.db.execute("INSERT INTO knowledge (character_id, content, since_world_time, source, status) VALUES (1, 'Fakt', 5, 'Beobachtung', 'wahr')")
        self.db.execute("INSERT INTO knowledge (character_id, content, since_world_time, source, status) VALUES (1, 'Zukunft', 9, 'Person', 'geglaubt')")
        self.db.execute("INSERT INTO mysteries (description, truth, status) VALUES ('Rätsel', 'Geheimnis', 'offen')")
        snapshot = character_at(self.db, 1, 6)
        self.assertEqual(snapshot['status'], 'unbekannt')
        self.assertEqual([x['content'] for x in snapshot['knowledge']], ['Fakt'])
        self.assertEqual(snapshot['locations'][0]['name'], 'A')
        self.assertNotIn('Geheimnis', str(snapshot))
        self.assertEqual(character_at(self.db, 1, 10)['status'], 'tot')
        self.assertEqual(character_at(self.db, 1, 10)['locations'], [])

    def test_presence_overlap_and_touching_boundaries(self):
        self.db.executemany("INSERT INTO character_presence (character_id, location_id, world_start, world_end) VALUES (1, ?, ?, ?)", [(1, 0, 10), (2, 10, 20)])
        self.assertEqual(presence_conflicts(self.db), [])
        self.db.execute("INSERT INTO character_presence (character_id, location_id, world_start, world_end) VALUES (1, 2, 9, NULL)")
        self.assertEqual(len(presence_conflicts(self.db)), 1)

    def test_ripples_respect_time_thread_and_completion(self):
        self.db.execute("INSERT INTO threads (id, level, world_time_cursor) VALUES (1, 'mikro', 0)")
        self.db.execute("INSERT INTO events (id, world_time) VALUES (1, 1)")
        self.db.executemany("INSERT INTO ripples (source_event_id, target_thread_id, earliest_world_time, effect, done) VALUES (1, 1, ?, ?, ?)", [(2, 'bereit', 0), (5, 'spaeter', 0), (1, 'erledigt', 1)])
        self.assertEqual([r['effect'] for r in eligible_ripples(self.db, 1, 2)], ['bereit'])

    def test_source_required(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO knowledge (character_id, content, since_world_time, source, status) VALUES (1, 'x', 1, ' ', 'wahr')")


if __name__ == '__main__':
    unittest.main()
