"""End-to-end checks of the Streamlit UI using Streamlit's own test harness (no browser)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

from store import LocalStore  # noqa: E402


class GymAppFlow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.data = Path(self.dir.name) / "db.json"
        os.environ["GYM_DATA_FILE"] = str(self.data)
        self.store = LocalStore(self.data)

    def tearDown(self):
        os.environ.pop("GYM_DATA_FILE", None)
        self.dir.cleanup()

    def run_app(self):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    def test_start_log_finish_workout(self):
        at = self.run_app()
        at.button(key="start-A").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])

        sess = self.store.active_session()
        self.assertIsNotNone(sess)
        self.assertEqual(sess["workout"], "A")

        # First exercise has no history, so reps default to 8. Log 60 kg x 10.
        suffix = f"{sess['id']}-0-0"
        at = self.run_app()
        at.number_input(key=f"w-{suffix}").set_value(60.0)
        at.number_input(key=f"r-{suffix}").set_value(10)
        at.button(key=f"submit-{suffix}").click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])

        logged = [x for x in self.store.list_sets() if x["session_id"] == sess["id"]]
        self.assertEqual(len(logged), 1)
        self.assertEqual((logged[0]["exercise"], logged[0]["weight"], logged[0]["reps"]),
                         ("Back Squat", 60.0, 10))

        at = self.run_app()
        at.button(key=f"finish-{sess['id']}").click().run()
        self.assertIsNone(self.store.active_session())
        self.assertEqual(self.store.list_sessions()[0]["status"], "done")

    def test_progress_page_renders_with_history(self):
        from datetime import date, timedelta

        today = date.today()
        for i, w in enumerate([60, 62.5, 62.5, 65]):
            day = (today - timedelta(days=7 * (3 - i))).isoformat()
            s = self.store.add_session(day, "A", status="done")
            for reps in (8, 8, 7):
                self.store.add_set(s["id"], "Back Squat", w, reps)
        self.store.add_food(today.isoformat(), "Chicken", 500, 45.0, 40.0)

        at = self.run_app()
        at.radio(key="page").set_value("Progress").run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertTrue(any("Recommendations" in m.value for m in at.subheader))

    def test_program_page_renders(self):
        at = self.run_app()
        at.radio(key="page").set_value("Program").run()
        self.assertFalse(at.exception, [e.value for e in at.exception])

    def test_food_entry_appears_and_saves(self):
        at = self.run_app()
        at.radio(key="page").set_value("Food").run()
        at.text_input(key="f_name").set_value("Oats")
        at.number_input[0].set_value(400)  # kcal
        at.button[0].click().run()  # first button on the page is the form submit
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual([f["name"] for f in self.store.list_food()], ["Oats"])


if __name__ == "__main__":
    unittest.main()
