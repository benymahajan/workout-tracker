import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logic import (  # noqa: E402
    food_totals,
    last_sets_for,
    next_workout,
    sessions_in_last_days,
    suggest_next,
    validate_food,
    validate_program,
    validate_set,
)

DEFAULT = {"rep_min": 8, "rep_max": 12, "increment": 2.5}


class Progression(unittest.TestCase):
    def test_no_history(self):
        self.assertIsNone(suggest_next(None, **DEFAULT))
        self.assertIsNone(suggest_next([], **DEFAULT))

    def test_top_of_range_adds_weight(self):
        s = suggest_next([{"weight": 60, "reps": 12}, {"weight": 60, "reps": 12}], **DEFAULT)
        self.assertEqual((s["weight"], s["reps"]), (62.5, 8))

    def test_mid_range_adds_one_rep(self):
        s = suggest_next([{"weight": 60, "reps": 9}, {"weight": 60, "reps": 10}], **DEFAULT)
        self.assertEqual((s["weight"], s["reps"]), (60, 10))

    def test_below_range_holds(self):
        s = suggest_next([{"weight": 60, "reps": 7}, {"weight": 60, "reps": 10}], **DEFAULT)
        self.assertEqual((s["weight"], s["reps"]), (60, 8))

    def test_last_sets_uses_most_recent_session_with_exercise(self):
        sessions = [
            {"id": 1, "date": "2026-11-01", "status": "done"},
            {"id": 2, "date": "2026-11-03", "status": "done"},
            {"id": 3, "date": "2026-11-05", "status": "done"},
        ]
        sets = [
            {"id": 10, "session_id": 1, "exercise": "Back Squat", "weight": 50, "reps": 8},
            {"id": 11, "session_id": 2, "exercise": "Bench Press", "weight": 40, "reps": 8},
            {"id": 12, "session_id": 3, "exercise": "back squat", "weight": 55, "reps": 8},
        ]
        self.assertEqual(last_sets_for(sessions, sets, "Back Squat"), [{"weight": 55, "reps": 8}])
        self.assertIsNone(last_sets_for(sessions, sets, "Deadlift"))


class Rotation(unittest.TestCase):
    def test_rotates_a_b_c(self):
        letters = ["A", "B", "C"]
        self.assertEqual(next_workout(letters, []), "A")
        s = [{"id": 1, "date": "2026-11-16", "workout": "A", "status": "done"}]
        self.assertEqual(next_workout(letters, s), "B")
        s.append({"id": 2, "date": "2026-11-18", "workout": "B", "status": "done"})
        self.assertEqual(next_workout(letters, s), "C")
        s.append({"id": 3, "date": "2026-11-20", "workout": "C", "status": "done"})
        self.assertEqual(next_workout(letters, s), "A")

    def test_active_session_does_not_advance_rotation(self):
        s = [{"id": 1, "date": "2026-11-16", "workout": "A", "status": "active"}]
        self.assertEqual(next_workout(["A", "B"], s), "A")


class Counting(unittest.TestCase):
    def test_last_seven_days(self):
        sessions = [
            {"date": "2026-11-18", "status": "done"},
            {"date": "2026-11-16", "status": "done"},
            {"date": "2026-11-05", "status": "done"},
            {"date": "2026-11-20", "status": "done"},  # future, excluded
        ]
        self.assertEqual(len(sessions_in_last_days(sessions, date(2026, 11, 18), 7)), 2)

    def test_food_totals(self):
        t = food_totals([{"kcal": 400, "protein_g": 15, "carbs_g": 50},
                         {"kcal": 200, "protein_g": 5, "carbs_g": 10}])
        self.assertEqual(t, {"kcal": 600, "protein_g": 20, "carbs_g": 60})


class Validation(unittest.TestCase):
    def good_program(self):
        return {
            "units": "kg", "timezone": "UTC", "workoutsPerWeek": 3,
            "progression": {"repMin": 8, "repMax": 12, "increment": 2.5},
            "nutrition": {"dailyCalorieTarget": 2200, "dailyProteinTargetG": 150},
            "workouts": {"A": [{"name": "Back Squat", "sets": 3, "unit": "reps"}]},
        }

    def test_accepts_good_program_and_strips_extras(self):
        p = self.good_program()
        p["_comment"] = "ignored"
        clean = validate_program(p)
        self.assertNotIn("_comment", clean)
        self.assertEqual(clean["workouts"]["A"][0]["name"], "Back Squat")

    def test_rejects_bad_fields(self):
        cases = [
            ("units", lambda p: p.update(units="stone")),
            ("timezone", lambda p: p.update(timezone="Mars/Olympus")),
            ("rep max below min", lambda p: p["progression"].update(repMax=5)),
            ("workout letter", lambda p: p["workouts"].update(AB=[])),
            ("sets range", lambda p: p["workouts"]["A"][0].update(sets=0)),
            ("empty name", lambda p: p["workouts"]["A"][0].update(name="  ")),
        ]
        for label, mutate in cases:
            with self.subTest(label):
                p = self.good_program()
                mutate(p)
                with self.assertRaises(ValueError):
                    validate_program(p)

    def test_set_and_food_validation(self):
        self.assertEqual(validate_set("Plank", 0, 30)["reps"], 30)
        with self.assertRaises(ValueError):
            validate_set("Squat", 60, 0)
        with self.assertRaises(ValueError):
            validate_set("Squat", 60, 8.5)
        with self.assertRaises(ValueError):
            validate_food("", 100, 0, 0)
        with self.assertRaises(ValueError):
            validate_food("Oats", "lots", 0, 0)


if __name__ == "__main__":
    unittest.main()
