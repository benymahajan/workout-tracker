import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from progress import (  # noqa: E402
    bodyweight_trend,
    build_context,
    default_muscle,
    e1rm,
    exercise_history,
    is_stalled,
    new_prs_since,
    nutrition_averages,
    recommendations,
    weekly_sets_by_muscle,
    weekly_sets_history,
)

REF = date(2026, 11, 18)


def program():
    return {
        "units": "kg", "timezone": "UTC", "workoutsPerWeek": 3,
        "progression": {"repMin": 8, "repMax": 12, "increment": 2.5},
        "nutrition": {"dailyCalorieTarget": 2200, "dailyProteinTargetG": 150},
        "workouts": {
            "A": [
                {"name": "Back Squat", "sets": 3, "unit": "reps", "muscle": "Quads"},
                {"name": "Plank", "sets": 3, "unit": "seconds", "muscle": "Core"},
            ],
            "B": [{"name": "Lat Pulldown", "sets": 3, "unit": "reps", "muscle": "Back"}],
        },
    }


class Sessions:
    """Tiny builder: each call adds a finished session with the given sets."""

    def __init__(self):
        self.sessions, self.sets, self._sid, self._setid = [], [], 0, 0

    def add(self, day, exercise, rows, workout="A", status="done"):
        self._sid += 1
        self.sessions.append({"id": self._sid, "date": day, "workout": workout, "status": status})
        for w, r in rows:
            self._setid += 1
            self.sets.append({"id": self._setid, "session_id": self._sid, "exercise": exercise,
                              "weight": w, "reps": r})
        return self._sid


class Metrics(unittest.TestCase):
    def test_epley(self):
        self.assertAlmostEqual(e1rm(100, 10), 133.33, places=2)
        self.assertEqual(e1rm(100, 0), 0.0)

    def test_history_best_and_volume(self):
        b = Sessions()
        b.add("2026-10-01", "Back Squat", [(60, 10), (60, 8)])
        b.add("2026-10-08", "Back Squat", [(62.5, 10)])
        h = exercise_history(b.sessions, b.sets, "back squat")
        self.assertEqual(len(h), 2)
        self.assertEqual(h[0]["volume"], 1080)
        self.assertEqual(h[1]["top_weight"], 62.5)
        self.assertGreater(h[1]["best"], h[0]["best"])

    def test_active_sessions_excluded(self):
        b = Sessions()
        b.add("2026-10-01", "Back Squat", [(60, 10)], status="active")
        self.assertEqual(exercise_history(b.sessions, b.sets, "Back Squat"), [])

    def test_timed_uses_hold_length(self):
        b = Sessions()
        b.add("2026-10-01", "Plank", [(0, 30), (0, 45)])
        h = exercise_history(b.sessions, b.sets, "Plank", timed=True)
        self.assertEqual(h[0]["best"], 45)

    def test_stall_detection(self):
        improving = [{"best": v} for v in (100, 102, 104, 106, 108)]
        stalled = [{"best": v} for v in (100, 110, 105, 108, 107)]
        self.assertFalse(is_stalled(improving))
        self.assertTrue(is_stalled(stalled))
        self.assertFalse(is_stalled(stalled[:3]))  # too short to judge

    def test_prs_in_window(self):
        h = [{"date": "2026-08-01", "best": 100}, {"date": "2026-10-01", "best": 110},
             {"date": "2026-11-01", "best": 105}, {"date": "2026-11-10", "best": 115}]
        prs = new_prs_since(h, date(2026, 10, 15))
        self.assertEqual([p["date"] for p in prs], ["2026-11-10"])


class Volume(unittest.TestCase):
    def test_default_muscles(self):
        self.assertEqual(default_muscle("Back Squat"), "Quads")
        self.assertEqual(default_muscle("Mystery Machine"), "Other")

    def test_weekly_counts_only_recent_done_sessions(self):
        b = Sessions()
        b.add("2026-11-17", "Back Squat", [(60, 8)] * 3)
        b.add("2026-11-10", "Back Squat", [(60, 8)] * 3)  # older than 7 days
        b.add("2026-11-18", "Lat Pulldown", [(40, 10)] * 2, status="active")
        counts = weekly_sets_by_muscle(b.sessions, b.sets, program(), REF)
        self.assertEqual(counts["Quads"], 3)
        self.assertEqual(counts.get("Back", 0), 0)

    def test_weekly_history_buckets(self):
        b = Sessions()
        b.add("2026-11-17", "Back Squat", [(60, 8)] * 2)
        b.add("2026-11-03", "Back Squat", [(60, 8)] * 4)
        rows = weekly_sets_history(b.sessions, b.sets, program(), REF, weeks=4)
        totals = {r["week_ending"]: r["sets"] for r in rows}
        self.assertEqual(totals.get("2026-11-18"), 2)
        self.assertEqual(totals.get("2026-11-04"), 4)


class Nutrition(unittest.TestCase):
    def test_averages_over_logged_days_only(self):
        food = [
            {"date": "2026-11-18", "kcal": 2000, "protein_g": 120},
            {"date": "2026-11-18", "kcal": 300, "protein_g": 30},
            {"date": "2026-11-16", "kcal": 2400, "protein_g": 160},
            {"date": "2026-10-01", "kcal": 9999, "protein_g": 9999},  # outside window
        ]
        n = nutrition_averages(food, REF, 7)
        self.assertEqual(n["days"], 2)
        self.assertEqual(n["kcal"], 2350)  # (2300 on 11-18 + 2400 on 11-16) / 2 days
        self.assertEqual(n["protein_g"], 155)
        self.assertIsNone(nutrition_averages([], REF, 7))


class Bodyweight(unittest.TestCase):
    def test_trend_per_week(self):
        # 0.5 kg a week over 3 weeks, from 80 kg
        entries = [{"date": (date(2026, 10, 28) + __import__("datetime").timedelta(days=d)).isoformat(),
                    "weight": 80 + 0.5 * d / 7} for d in range(0, 22, 3)]
        t = bodyweight_trend(entries, REF, days=28)
        self.assertAlmostEqual(t["per_week"], 0.5, places=1)
        self.assertGreater(t["pct_per_week"], 0)

    def test_needs_enough_points_and_span(self):
        self.assertIsNone(bodyweight_trend([{"date": "2026-11-18", "weight": 80}], REF))
        same_week = [{"date": f"2026-11-1{d}", "weight": 80 + d * 0.01} for d in range(1, 4)]
        self.assertIsNone(bodyweight_trend(same_week, REF))

    def test_rules_use_trend(self):
        def ctx(pct, avg_kcal=2100):
            return {
                "sessions_this_week": 3, "sessions_target": 3, "weekly_sets": {"Quads": 12},
                "stalled": [], "improving": [], "avg_kcal": avg_kcal, "kcal_target": 2200,
                "avg_protein": 160, "protein_target": 150,
                "bodyweight": {"pct_per_week": pct, "per_week": 0, "latest": 80, "points": 4, "span_days": 14},
            }

        def text_of(recs):
            return " ".join(t for _, t in recs)

        self.assertIn("lean-gain range", text_of(recommendations(ctx(0.3))))
        self.assertIn("Trim intake", text_of(recommendations(ctx(0.8))))
        flat_low = recommendations(ctx(0.0, avg_kcal=1900))
        self.assertTrue(any(lvl == "action" and "200–300" in t for lvl, t in flat_low))
        self.assertIn("Log your bodyweight", text_of(recommendations({**ctx(0), "bodyweight": None})))


class Recommendations(unittest.TestCase):
    def ctx(self, **over):
        base = {
            "sessions_this_week": 3, "sessions_target": 3,
            "weekly_sets": {"Quads": 12, "Back": 12},
            "stalled": [], "improving": [],
            "avg_kcal": 2300, "kcal_target": 2200,
            "avg_protein": 160, "protein_target": 150,
        }
        base.update(over)
        return base

    def levels(self, recs):
        return [lvl for lvl, _ in recs]

    def test_happy_path_is_all_good(self):
        recs = recommendations(self.ctx())
        self.assertNotIn("action", self.levels(recs))
        self.assertIn("good", self.levels(recs))

    def test_low_volume_and_missed_sessions_are_actions(self):
        recs = recommendations(self.ctx(sessions_this_week=1, weekly_sets={"Quads": 4, "Back": 12}))
        texts = " ".join(t for lvl, t in recs if lvl == "action")
        self.assertIn("1 of 3 workouts", texts)
        self.assertIn("Quads: 4 hard sets", texts)

    def test_too_much_volume_is_tip_not_action(self):
        recs = recommendations(self.ctx(weekly_sets={"Chest": 26}))
        self.assertTrue(any("Chest: 26" in t and lvl == "tip" for lvl, t in recs))
        self.assertFalse(any("Chest: 26" in t and lvl == "action" for lvl, t in recs))

    def test_stall_suggests_deload(self):
        recs = recommendations(self.ctx(stalled=["Bench Press"]))
        self.assertTrue(any("Bench Press" in t and "deload" in t for lvl, t in recs))

    def test_low_protein_and_low_calories_while_stalled(self):
        recs = recommendations(self.ctx(avg_protein=100, avg_kcal=1700, stalled=["Bench Press"]))
        texts = " ".join(t for _, t in recs)
        self.assertIn("Protein averages 100 g", texts)
        self.assertIn("Eat closer to target", texts)

    def test_no_food_logged_prompts_logging(self):
        recs = recommendations(self.ctx(avg_protein=None, avg_kcal=None))
        self.assertTrue(any("Log food" in t for _, t in recs))

    def test_build_context_detects_stall_from_history(self):
        b = Sessions()
        from datetime import timedelta
        start = date(2026, 10, 1)
        for i, w in enumerate([60, 62.5, 62.5, 62.5, 62.5, 62.5]):
            b.add((start + timedelta(days=7 * i)).isoformat(), "Back Squat", [(w, 8)] * 3)
        ctx = build_context(b.sessions, b.sets, [], program(), REF)
        self.assertIn("Back Squat", ctx["stalled"])


if __name__ == "__main__":
    unittest.main()
