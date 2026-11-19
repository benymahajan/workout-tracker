"""Storage with one interface and two backends. Every row belongs to one owner (a user's email).

- LocalStore: a JSON file. Used on your PC for testing.
- SheetsStore: a Google Sheet. Used when the app is hosted, because hosted servers
  don't keep files between restarts.

A store is bound to one owner with `with_owner(email)`. Reads only see that owner's rows, and
writes only change them. Rows with a blank owner were written before accounts existed; they
belong to the legacy owner (LEGACY_OWNER in secrets, or the dev user locally).
"""
from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
DEFAULT_PROGRAM_PATH = HERE / "default_program.json"

# table -> {column: type}. Column order is the sheet's column order. `owner` comes last so
# sheets created before accounts existed still line up with their first columns.
SCHEMA = {
    "sessions": {"id": "int", "date": "str", "workout": "str", "status": "str",
                 "started_at": "str", "finished_at": "str", "owner": "str"},
    "sets": {"id": "int", "session_id": "int", "exercise": "str", "weight": "float",
             "reps": "int", "logged_at": "str", "owner": "str"},
    "food": {"id": "int", "date": "str", "name": "str", "kcal": "float",
             "protein_g": "float", "carbs_g": "float", "owner": "str"},
    "bodyweight": {"id": "int", "date": "str", "weight": "float", "logged_at": "str",
                   "owner": "str"},
    "program": {"id": "int", "json": "str", "owner": "str"},
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
    owner = ""          # the signed-in user this store acts for
    legacy_owner = ""   # who owns rows that have no owner (written before accounts)

    # ----- primitives, implemented by each backend. They only touch rows this owner can see. -----
    def all(self, table): raise NotImplementedError
    def insert(self, table, row): raise NotImplementedError
    def update(self, table, id_, changes): raise NotImplementedError
    def delete(self, table, id_): raise NotImplementedError

    def with_owner(self, email):
        """A copy of this store acting for `email`. Shares the same underlying data."""
        bound = copy.copy(self)
        bound.owner = str(email or "").strip().lower()
        return bound

    def _mine(self, rec):
        o = rec.get("owner") or ""
        return o == self.owner or (o == "" and self.owner == self.legacy_owner)

    # ----- shared API used by the app -----
    def read_program(self):
        rows = self.all("program")
        return json.loads(rows[0]["json"]) if rows else None

    def get_program(self):
        return self.read_program() or default_program()

    def save_program(self, program):
        raw = json.dumps(program)
        rows = self.all("program")
        if rows:
            self.update("program", rows[0]["id"], {"json": raw})
        else:
            self.insert("program", {"json": raw})
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

    def __init__(self, path, legacy_owner=""):
        self.path = Path(path)
        self.legacy_owner = str(legacy_owner or "").strip().lower()

    def _load(self):
        data = (json.loads(self.path.read_text(encoding="utf-8"))
                if self.path.exists() else {})
        # Old single-program format stored a dict under "program". The new program table is a list
        # under the same key, so only a dict counts as the old format.
        legacy = data.get("program") if isinstance(data.get("program"), dict) else None
        if legacy is not None:
            del data["program"]
        for table in SCHEMA:  # files made before a table existed get it empty
            data.setdefault(table, [])
        if legacy is not None:
            data["program"].append({"id": next_id(data["program"]), "json": json.dumps(legacy),
                                    "owner": ""})
        return data

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def all(self, table):
        return [dict(r) for r in self._load()[table] if self._mine(r)]

    def insert(self, table, row):
        data = self._load()
        rows = data[table]
        rec = {"id": next_id(rows), **row, "owner": self.owner}
        rows.append(rec)
        self._save(data)
        return rec

    def update(self, table, id_, changes):
        data = self._load()
        for r in data[table]:
            if r["id"] == id_ and self._mine(r):
                r.update(changes)
                self._save(data)
                return dict(r)
        return None

    def delete(self, table, id_):
        data = self._load()
        before = len(data[table])
        data[table] = [r for r in data[table] if not (r["id"] == id_ and self._mine(r))]
        self._save(data)
        return len(data[table]) < before


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


def _col_letter(n):
    """1 -> A, 26 -> Z, 27 -> AA."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class SheetsStore(Store):
    kind = "Google Sheets"

    def __init__(self, spreadsheet, legacy_owner=""):
        self.sheet = spreadsheet
        self.legacy_owner = str(legacy_owner or "").strip().lower()
        existing = {ws.title: ws for ws in spreadsheet.worksheets()}
        self._tabs = {}
        for table, cols in SCHEMA.items():
            ws = existing.get(table) or spreadsheet.add_worksheet(
                title=table, rows=500, cols=len(cols))
            self._tabs[table] = ws
            if table == "program":
                self._migrate_program(ws, list(cols))
            else:
                self._ensure_header(ws, list(cols))

    def _ensure_header(self, ws, cols):
        """Writes the header if the tab is empty, or extends an older header with new columns."""
        values = ws.get_all_values()
        header = values[0] if values else []
        if not any(header):
            self._write_row(ws, 1, cols)
        elif header != cols and header == cols[:len(header)]:
            self._write_row(ws, 1, cols)  # older schema: a prefix of the current one

    def _migrate_program(self, ws, cols):
        values = ws.get_all_values()
        if values and values[0] and values[0][0].startswith("{"):
            # Old format: the whole program JSON sits in A1 with no header. Keep it as a legacy row.
            legacy_json = values[0][0]
            self._write_row(ws, 1, cols)
            self._write_row(ws, 2, ["1", legacy_json, ""])
        else:
            self._ensure_header(ws, cols)

    def _write_row(self, ws, row_number, values):
        if ws.col_count < len(values):
            ws.add_cols(len(values) - ws.col_count)
        last = _col_letter(len(values))
        ws.update(range_name=f"A{row_number}:{last}{row_number}",
                  values=[values], value_input_option="RAW")

    def _rows(self, table):
        """Yields (record, sheet_row_number) for every data row, including other owners'."""
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
        return [rec for rec, _ in self._rows(table) if self._mine(rec)]

    def insert(self, table, row):
        cols = SCHEMA[table]
        rec = {"id": next_id([r for r, _ in self._rows(table)]), **row, "owner": self.owner}
        self._tabs[table].append_row(
            [_out(rec.get(c)) for c in cols], value_input_option="RAW")
        return rec

    def update(self, table, id_, changes):
        cols = SCHEMA[table]
        for rec, n in self._rows(table):
            if rec["id"] == id_ and self._mine(rec):
                merged = {**rec, **changes}
                self._write_row(self._tabs[table], n, [_out(merged[c]) for c in cols])
                return merged
        return None

    def delete(self, table, id_):
        for rec, n in self._rows(table):
            if rec["id"] == id_ and self._mine(rec):
                self._tabs[table].delete_rows(n)
                return True
        return False


def uses_sheets(secrets):
    try:
        return "gcp_service_account" in secrets and "sheet_key" in secrets
    except Exception:
        return False


def normalize_service_account(info):
    """Repairs the private key after it's pasted into Streamlit secrets.

    Pastes often turn the key's line breaks into a literal backslash-n, or add stray quotes.
    The key needs real newlines and a trailing newline to parse as PEM.
    """
    info = dict(info)
    key = str(info.get("private_key", "")).strip().strip('"').strip()
    key = key.replace("\\n", "\n").replace("\r\n", "\n")
    info["private_key"] = key.rstrip("\n") + "\n"
    return info


def open_sheets_store(secrets):
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    info = normalize_service_account(secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(creds)
    try:
        legacy = str(secrets["LEGACY_OWNER"])
    except Exception:
        legacy = ""
    return SheetsStore(client.open_by_key(secrets["sheet_key"]), legacy_owner=legacy)
