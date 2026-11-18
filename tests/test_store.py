import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import LocalStore, default_program  # noqa: E402


class LocalStoreRoundTrip(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = LocalStore(Path(self.dir.name) / "db.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_program_defaults_then_persists(self):
        self.assertEqual(self.store.get_program()["units"], default_program()["units"])
        p = self.store.get_program()
        p["units"] = "lb"
        self.store.save_program(p)
        self.assertEqual(LocalStore(self.store.path).get_program()["units"], "lb")

    def test_session_sets_and_cascade_delete(self):
        s = self.store.add_session("2026-11-18", "A")
        self.assertEqual(self.store.active_session()["id"], s["id"])
        self.store.add_set(s["id"], "Back Squat", 60, 10)
        self.store.add_set(s["id"], "Back Squat", 60, 9)
        self.assertEqual(len(self.store.list_sets()), 2)

        self.store.finish_session(s["id"])
        self.assertIsNone(self.store.active_session())
        self.assertEqual(self.store.list_sessions()[0]["status"], "done")

        self.store.delete_session(s["id"])
        self.assertEqual(self.store.list_sessions(), [])
        self.assertEqual(self.store.list_sets(), [])

    def test_food_by_day(self):
        self.store.add_food("2026-11-18", "Oats", 400, 15, 60)
        self.store.add_food("2026-11-17", "Eggs", 150, 12, 1)
        self.assertEqual([f["name"] for f in self.store.list_food("2026-11-18")], ["Oats"])
        self.assertEqual(len(self.store.list_food()), 2)


if __name__ == "__main__":
    unittest.main()
