"""Storage with one interface and two backends.

- LocalStore: a JSON file. Used on your PC for testing.
- SheetsStore: a Google Sheet. Used when the app is hosted, because hosted servers
  don't keep files between restarts.

Both implement the same tiny primitives (all / insert / update / delete / program
read+write). Everything else lives on the Store base class.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_PROGRAM_PATH = HERE / "default_program.json"

# table -> {column: type}. Column order is the sheet's column order.
SCHEMA = {
    "sessions": {"id": "int", "date": "str", "workout": "str", "status": "str",
                 "started_at": "str", "finished_at": "str"},
    "sets": {"id": "int", "session_id": "int", "exercise": "str", "weight": "float",
             "reps": "int", "logged_at": "str"},
    "food": {"id": "int", "date": "str", "name": "str", "kcal": "float",
             "protein_g": "float", "carbs_g": "float"},
    "bodyweight": {"id": "int", "date": "str", "weight": "float", "logged_at": "str"},
}


def default_program():
    return json.loads(DEFAULT_PROGRAM_PATH.read_text(encoding="utf-8"))


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_last_id = 0


def next_id(existing_rows):
    """IDs strictly increase, even after deletes, so a stale page can't hit a reused ID.

    Takes the clock in milliseconds, or max+1 if that is higher, and never repeats within a process.
    """
    global _last_id
    _last_id = max(
        _last_id + 1,
        max((r["id"] for r in existing_rows), default=0) + 1,
        time.time_ns() // 1_000_000,
    )
    return _last_id


class Store:
    # ----- primitives, implemented by each backend -----
    def all(self, table): raise NotImplementedError
    def insert(self, table, row): raise NotImplementedError
    def update(self, table, id_, changes): raise NotImplementedError
    def delete(self, table, id_): raise NotImplementedError
    def read_program(self): raise NotImplementedError
    def write_program(self, program): raise NotImplementedError

    # ----- shared API used by the app -----
    def get_program(self):
        return self.read_program() or default_program()

    def save_program(self, program):
        self.write_program(program)
        return program

    def list_sessions(self):
        return sorted(self.all("sessions"), key=lambda s: (s["date"], s["id"]))

    def active_session(self):
        return next((s for s in self.all("sessions") if s["status"] == "active"), None)

    def add_session(self, date, workout, status="active"):
        return self.insert("sessions", {
            "date": date, "workout": workout, "status": status,
            "started_at": now_iso(), "finished_at": "",
        })

    def finish_session(self, id_):
        return self.update("sessions", id_, {"status": "done", "finished_at": now_iso()})

    def delete_session(self, id_):
        for s in self.all("sets"):
            if s["session_id"] == id_:
                self.delete("sets", s["id"])
        return self.delete("sessions", id_)

    def list_sets(self):
        return self.all("sets")

    def add_set(self, session_id, exercise, weight, reps):
        return self.insert("sets", {
            "session_id": session_id, "exercise": exercise, "weight": weight,
            "reps": reps, "logged_at": now_iso(),
        })

    def delete_set(self, id_):
        return self.delete("sets", id_)

    def list_food(self, date=None):
        return [f for f in self.all("food") if date is None or f["date"] == date]

    def add_food(self, date, name, kcal, protein_g, carbs_g):
        return self.insert("food", {
            "date": date, "name": name, "kcal": kcal,
            "protein_g": protein_g, "carbs_g": carbs_g,
        })

    def delete_food(self, id_):
        return self.delete("food", id_)

    def list_bodyweight(self):
        return sorted(self.all("bodyweight"), key=lambda b: (b["date"], b["id"]))

    def add_bodyweight(self, date, weight):
        return self.insert("bodyweight", {"date": date, "weight": weight, "logged_at": now_iso()})

    def delete_bodyweight(self, id_):
        return self.delete("bodyweight", id_)


# ---------- local JSON file ----------

class LocalStore(Store):
    kind = "local file"

    def __init__(self, path):
        self.path = Path(path)

    def _load(self):
        data = (json.loads(self.path.read_text(encoding="utf-8"))
                if self.path.exists() else {"program": None})
        for table in SCHEMA:  # files made before a table existed get it empty
            data.setdefault(table, [])
        return data

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def all(self, table):
        return [dict(r) for r in self._load()[table]]

    def insert(self, table, row):
        data = self._load()
        rows = data[table]
        rec = {"id": next_id(rows), **row}
        rows.append(rec)
        self._save(data)
        return rec

    def update(self, table, id_, changes):
        data = self._load()
        for r in data[table]:
            if r["id"] == id_:
                r.update(changes)
                self._save(data)
                return dict(r)
        return None

    def delete(self, table, id_):
        data = self._load()
        before = len(data[table])
        data[table] = [r for r in data[table] if r["id"] != id_]
        self._save(data)
        return len(data[table]) < before

    def read_program(self):
        return self._load().get("program")

    def write_program(self, program):
        data = self._load()
        data["program"] = program
        self._save(data)


# ---------- Google Sheets ----------

def _cast(value, kind):
    if kind == "str":
        return "" if value is None else str(value)
    if value in (None, ""):
        return 0 if kind == "int" else 0.0
    if kind == "int":
        return int(float(value))
    return float(value)


def _out(value):
    return "" if value is None else value


class SheetsStore(Store):
    kind = "Google Sheets"
    PROGRAM_TAB = "program"

    def __init__(self, spreadsheet):
        self.sheet = spreadsheet
        existing = {ws.title: ws for ws in spreadsheet.worksheets()}
        self._tabs = {}
        for table, cols in SCHEMA.items():
            ws = existing.get(table) or spreadsheet.add_worksheet(
                title=table, rows=500, cols=len(cols))
            if not ws.get_all_values():
                ws.update(range_name="A1", values=[list(cols)])
            self._tabs[table] = ws
        self._program_ws = existing.get(self.PROGRAM_TAB) or spreadsheet.add_worksheet(
            title=self.PROGRAM_TAB, rows=5, cols=1)

    def _rows(self, table):
        """Yields (record, sheet_row_number) for every data row."""
        values = self._tabs[table].get_all_values()
        cols = SCHEMA[table]
        for n, raw in enumerate(values[1:], start=2):
            if not any(raw):
                continue
            rec = {
                col: _cast(raw[i] if i < len(raw) else "", kind)
                for i, (col, kind) in enumerate(cols.items())
            }
            yield rec, n

    def all(self, table):
        return [rec for rec, _ in self._rows(table)]

    def insert(self, table, row):
        cols = SCHEMA[table]
        rec = {"id": next_id(self.all(table)), **row}
        self._tabs[table].append_row(
            [_out(rec.get(c)) for c in cols], value_input_option="RAW")
        return rec

    def update(self, table, id_, changes):
        cols = SCHEMA[table]
        for rec, n in self._rows(table):
            if rec["id"] == id_:
                merged = {**rec, **changes}
                last = chr(ord("A") + len(cols) - 1)
                self._tabs[table].update(
                    range_name=f"A{n}:{last}{n}",
                    values=[[_out(merged[c]) for c in cols]],
                    value_input_option="RAW",
                )
                return merged
        return None

    def delete(self, table, id_):
        for rec, n in self._rows(table):
            if rec["id"] == id_:
                self._tabs[table].delete_rows(n)
                return True
        return False

    def read_program(self):
        raw = self._program_ws.acell("A1").value
        return json.loads(raw) if raw else None

    def write_program(self, program):
        self._program_ws.update(
            range_name="A1", values=[[json.dumps(program)]], value_input_option="RAW")


def uses_sheets(secrets):
    try:
        return "gcp_service_account" in secrets and "sheet_key" in secrets
    except Exception:
        return False


def open_sheets_store(secrets):
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(dict(secrets["gcp_service_account"]), scopes=scopes)
    client = gspread.authorize(creds)
    return SheetsStore(client.open_by_key(secrets["sheet_key"]))
