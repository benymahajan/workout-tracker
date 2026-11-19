"""Multi-user isolation: one user must never see or change another user's rows."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from identity import check_login, resolve_user  # noqa: E402
from store import LocalStore  # noqa: E402

ANA, BEN = "ana@example.com", "ben@example.com"


class OwnerIsolation(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "db.json"
        self.ana = LocalStore(self.path).with_owner(ANA)
        self.ben = LocalStore(self.path).with_owner(BEN)

    def tearDown(self):
        self.dir.cleanup()

    def test_sessions_sets_food_and_bodyweight_are_private(self):
        s = self.ana.add_session("2026-11-18", "A")
        self.ana.add_set(s["id"], "Back Squat", 60, 10)
        self.ana.add_food("2026-11-18", "Oats", 400, 15, 60)
        self.ana.add_bodyweight("2026-11-18", 80.0)

        self.assertEqual(self.ben.list_sessions(), [])
        self.assertEqual(self.ben.list_sets(), [])
        self.assertEqual(self.ben.list_food(), [])
        self.assertEqual(self.ben.list_bodyweight(), [])
        self.assertIsNone(self.ben.active_session())
        self.assertEqual(len(self.ana.list_sessions()), 1)

    def test_cannot_change_or_delete_someone_elses_rows(self):
        s = self.ana.add_session("2026-11-18", "A")
        st_set = self.ana.add_set(s["id"], "Back Squat", 60, 10)

        self.assertIsNone(self.ben.finish_session(s["id"]))
        self.assertFalse(self.ben.delete_session(s["id"]))
        self.assertFalse(self.ben.delete_set(st_set["id"]))
        # Ana's data is untouched.
        self.assertEqual(self.ana.active_session()["id"], s["id"])
        self.assertEqual(len(self.ana.list_sets()), 1)

    def test_programs_are_per_user(self):
        p = self.ana.get_program()
        p["units"] = "lb"
        self.ana.save_program(p)
        self.assertEqual(self.ana.get_program()["units"], "lb")
        self.assertEqual(self.ben.get_program()["units"], "kg")  # Ben still has the default
        self.ben.save_program({**self.ben.get_program(), "units": "kg", "schedule": "Ben's plan"})
        self.assertEqual(self.ana.get_program()["units"], "lb")

    def test_owner_is_case_insensitive(self):
        s = self.ana.add_session("2026-11-18", "A")
        upper = LocalStore(self.path).with_owner("ANA@Example.com")
        self.assertEqual(upper.active_session()["id"], s["id"])


class LegacyData(unittest.TestCase):
    """Data written before accounts existed (blank owner) belongs to the legacy owner only."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "db.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_blank_owner_rows_go_to_legacy_owner(self):
        old = LocalStore(self.path)  # owner "" like pre-accounts code
        old.add_session("2026-11-18", "A")
        owner = LocalStore(self.path, legacy_owner=ANA).with_owner(ANA)
        other = LocalStore(self.path, legacy_owner=ANA).with_owner(BEN)
        self.assertEqual(len(owner.list_sessions()), 1)
        self.assertEqual(other.list_sessions(), [])

    def test_old_single_program_file_is_migrated(self):
        self.path.write_text(json.dumps({"program": {"units": "lb", "workouts": {}, "progression": {
            "repMin": 8, "repMax": 12, "increment": 2.5}, "nutrition": {
            "dailyCalorieTarget": 2000, "dailyProteinTargetG": 120}, "timezone": "UTC",
            "workoutsPerWeek": 3, "schedule": ""}}), encoding="utf-8")
        owner = LocalStore(self.path, legacy_owner=ANA).with_owner(ANA)
        self.assertEqual(owner.get_program()["units"], "lb")
        self.assertEqual(LocalStore(self.path, legacy_owner=ANA).with_owner(BEN).get_program()["units"], "kg")


class PasscodeLogin(unittest.TestCase):
    USERS = {"Ben": "beta-pass", "ana": "alpha-pass"}

    def test_right_name_and_passcode(self):
        self.assertEqual(check_login("Ana", "alpha-pass", self.USERS), "ana")
        self.assertEqual(check_login("  BEN ", "beta-pass", self.USERS), "ben")

    def test_wrong_passcode_or_name_is_refused_with_same_message(self):
        for name, code in [("ana", "wrong"), ("nobody", "alpha-pass"), ("", "alpha-pass")]:
            with self.assertRaises(PermissionError) as cm:
                check_login(name, code, self.USERS)
            self.assertEqual(str(cm.exception), "Wrong name or passcode.")

    def test_no_users_configured(self):
        with self.assertRaises(PermissionError):
            check_login("ana", "alpha-pass", {})


class Identity(unittest.TestCase):
    def test_local_uses_signed_in_email_or_dev_user(self):
        self.assertEqual(resolve_user(None, hosted=False, dev_user="Dev@Test.local"), "dev@test.local")
        self.assertEqual(resolve_user("A@x.com", hosted=False), "a@x.com")

    def test_hosted_requires_sign_in(self):
        with self.assertRaises(PermissionError):
            resolve_user("", hosted=True)

    def test_hosted_checks_allow_list(self):
        self.assertEqual(resolve_user("Ana@x.com", hosted=True, allowed=["ana@x.com"]), "ana@x.com")
        with self.assertRaises(PermissionError):
            resolve_user("eve@x.com", hosted=True, allowed=["ana@x.com", "ben@x.com"])
        self.assertEqual(resolve_user("eve@x.com", hosted=True, allowed=[]), "eve@x.com")


if __name__ == "__main__":
    unittest.main()
