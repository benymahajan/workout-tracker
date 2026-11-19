"""SheetsStore against an in-memory fake that mimics the gspread calls we use.

This doesn't prove the live Google API behaves identically, but it catches logic and
row-addressing bugs without needing credentials.
"""
import re
import sys
import unittest
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import SheetsStore, default_program  # noqa: E402

Cell = namedtuple("Cell", "value")


def _col_index(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


class FakeWS:
    def __init__(self, title):
        self.title = title
        self.grid = []  # list of rows, each a list of raw values
        self.col_count = 26

    def add_cols(self, n):
        self.col_count += n

    def get_all_values(self):
        return [["" if v is None else str(v) for v in row] for row in self.grid]

    def append_row(self, row, value_input_option=None):
        self.grid.append(list(row))

    def update(self, range_name, values, value_input_option=None):
        m = re.match(r"([A-Z])(\d+)", range_name)
        col0, row0 = _col_index(m.group(1)), int(m.group(2)) - 1
        for i, vals in enumerate(values):
            while len(self.grid) <= row0 + i:
                self.grid.append([])
            row = self.grid[row0 + i]
            for j, v in enumerate(vals):
                while len(row) <= col0 + j:
                    row.append(None)
                row[col0 + j] = v

    def acell(self, address):
        m = re.match(r"([A-Z])(\d+)", address)
        r, c = int(m.group(2)) - 1, _col_index(m.group(1))
        try:
            return Cell(self.grid[r][c])
        except IndexError:
            return Cell(None)

    def delete_rows(self, index):
        del self.grid[index - 1]


class FakeSpreadsheet:
    def __init__(self):
        self.tabs = []

    def worksheets(self):
        return list(self.tabs)

    def add_worksheet(self, title, rows=1, cols=1):
        ws = FakeWS(title)
        self.tabs.append(ws)
        return ws


class SheetsStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = SheetsStore(FakeSpreadsheet())

    def test_creates_tabs_with_headers(self):
        titles = [ws.title for ws in self.store.sheet.tabs]
        self.assertEqual(sorted(titles), ["bodyweight", "food", "program", "sessions", "sets"])
        self.assertEqual(self.store._tabs["sets"].grid[0][0], "id")

    def test_program_defaults_then_round_trips(self):
        self.assertEqual(self.store.get_program()["units"], default_program()["units"])
        p = self.store.get_program()
        p["units"] = "lb"
        self.store.save_program(p)
        self.assertEqual(SheetsStore(self.store.sheet).get_program()["units"], "lb")

    def test_session_set_flow_and_cascade(self):
        s = self.store.add_session("2026-11-18", "A")
        self.assertEqual(self.store.active_session()["id"], s["id"])
        self.assertEqual(self.store.active_session()["workout"], "A")

        self.store.add_set(s["id"], "Back Squat", 60.0, 10)
        self.store.add_set(s["id"], "Back Squat", 62.5, 8)
        sets = self.store.list_sets()
        self.assertEqual([(x["weight"], x["reps"]) for x in sets], [(60.0, 10), (62.5, 8)])

        self.store.delete_set(sets[0]["id"])
        self.assertEqual(len(self.store.list_sets()), 1)

        self.store.finish_session(s["id"])
        self.assertIsNone(self.store.active_session())
        self.assertEqual(self.store.list_sessions()[0]["status"], "done")

        self.store.delete_session(s["id"])
        self.assertEqual(self.store.list_sessions(), [])
        self.assertEqual(self.store.list_sets(), [])

    def test_food_by_day_and_delete(self):
        a = self.store.add_food("2026-11-18", "Oats", 400, 15.0, 60.0)
        self.store.add_food("2026-11-17", "Eggs", 150, 12.0, 1.0)
        self.assertEqual([f["name"] for f in self.store.list_food("2026-11-18")], ["Oats"])
        self.assertTrue(self.store.delete_food(a["id"]))
        self.assertEqual(len(self.store.list_food()), 1)

    def test_ids_keep_increasing_after_deletes(self):
        a = self.store.add_session("2026-11-18", "A")
        self.store.delete_session(a["id"])
        b = self.store.add_session("2026-11-19", "B")
        self.assertGreater(b["id"], a["id"])


ANA, BEN = "ana@example.com", "ben@example.com"


class SheetsOwners(unittest.TestCase):
    def test_rows_are_private_per_owner(self):
        sheet = FakeSpreadsheet()
        base = SheetsStore(sheet)
        ana, ben = base.with_owner(ANA), base.with_owner(BEN)
        s = ana.add_session("2026-11-18", "A")
        ana.add_set(s["id"], "Back Squat", 60, 10)
        ana.add_food("2026-11-18", "Oats", 400, 15, 60)

        self.assertEqual(ben.list_sessions(), [])
        self.assertEqual(ben.list_sets(), [])
        self.assertEqual(ben.list_food(), [])
        self.assertIsNone(ben.finish_session(s["id"]))
        self.assertFalse(ben.delete_session(s["id"]))
        self.assertEqual(ana.active_session()["id"], s["id"])
        self.assertEqual(ana.list_sessions()[0]["owner"], ANA)

    def test_programs_are_per_owner(self):
        base = SheetsStore(FakeSpreadsheet())
        ana, ben = base.with_owner(ANA), base.with_owner(BEN)
        p = ana.get_program()
        p["units"] = "lb"
        ana.save_program(p)
        self.assertEqual(ana.get_program()["units"], "lb")
        self.assertEqual(ben.get_program()["units"], "kg")
        ana.save_program({**ana.get_program(), "units": "kg"})
        self.assertEqual(ana.get_program()["units"], "kg")
        self.assertEqual(len(ana._tabs["program"].get_all_values()), 2)  # header + one row

    def test_legacy_rows_and_program_belong_to_legacy_owner(self):
        sheet = FakeSpreadsheet()
        old = SheetsStore(sheet)
        old.insert("sessions", {"date": "2026-11-18", "workout": "A", "status": "done",
                                "started_at": "", "finished_at": ""})  # owner "" (pre-accounts)
        old_json = '{"units": "lb", "workouts": {}, "timezone": "UTC", "workoutsPerWeek": 3, ' \
                   '"progression": {"repMin": 8, "repMax": 12, "increment": 2.5}, ' \
                   '"nutrition": {"dailyCalorieTarget": 2000, "dailyProteinTargetG": 120}, "schedule": ""}'
        # Simulate the old program layout: JSON in A1 with no header.
        sheet.tabs = [ws for ws in sheet.tabs if ws.title != "program"]
        ws = sheet.add_worksheet(title="program")
        ws.grid = [[old_json]]

        store = SheetsStore(sheet, legacy_owner=ANA)
        self.assertEqual(len(store.with_owner(ANA).list_sessions()), 1)
        self.assertEqual(store.with_owner(BEN).list_sessions(), [])
        self.assertEqual(store.with_owner(ANA).get_program()["units"], "lb")
        self.assertEqual(store.with_owner(BEN).get_program()["units"], "kg")
        self.assertEqual(ws.get_all_values()[0][:2], ["id", "json"])

    def test_older_header_is_extended_with_owner_column(self):
        sheet = FakeSpreadsheet()
        ws = sheet.add_worksheet(title="sessions")
        ws.col_count = 6
        ws.grid = [["id", "date", "workout", "status", "started_at", "finished_at"],
                   ["5", "2026-11-10", "A", "done", "", ""]]
        store = SheetsStore(sheet, legacy_owner=ANA)
        self.assertEqual(ws.get_all_values()[0][-1], "owner")
        self.assertEqual(store.with_owner(ANA).list_sessions()[0]["id"], 5)


if __name__ == "__main__":
    unittest.main()
