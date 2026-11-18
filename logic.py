"""Pure logic for the gym app: progression, rotation, totals, validation.

No storage and no Streamlit imports, so this is easy to test.
"""
from __future__ import annotations

import math
import re
from datetime import date
from zoneinfo import ZoneInfo

UNITS = ("kg", "lb")
EXERCISE_UNITS = ("reps", "seconds")


# ---------- progressive overload ----------

def suggest_next(last_sets, rep_min=8, rep_max=12, increment=2.5):
    """Double progression. Returns the target for next time, or None without history.

    Stay at a weight until every set reaches rep_max, then add `increment` and drop back
    to rep_min.
    """
    if not last_sets:
        return None
    weight = max(s["weight"] for s in last_sets)
    min_reps = min(s["reps"] for s in last_sets)
    if min_reps >= rep_max:
        return {
            "weight": round(weight + increment, 2),
            "reps": rep_min,
            "reason": f"Every set hit {rep_max}. Add {increment} and restart at {rep_min}.",
        }
    if min_reps < rep_min:
        return {
            "weight": weight,
            "reps": rep_min,
            "reason": f"A set fell below {rep_min}. Hold the weight and aim for {rep_min} on every set.",
        }
    return {
        "weight": weight,
        "reps": min(min_reps + 1, rep_max),
        "reason": f"Still in the {rep_min}–{rep_max} range. Hold the weight and aim for one more rep per set.",
    }


def last_sets_for(finished_sessions, all_sets, exercise):
    """Sets for `exercise` from the most recent finished session that contains it, or None."""
    name = exercise.strip().lower()
    for s in sorted(finished_sessions, key=lambda s: (s["date"], s["id"]), reverse=True):
        matches = sorted(
            (x for x in all_sets
             if x["session_id"] == s["id"] and x["exercise"].strip().lower() == name),
            key=lambda x: x["id"],
        )
        if matches:
            return [{"weight": x["weight"], "reps": x["reps"]} for x in matches]
    return None


def next_workout(letters, sessions):
    """Rotation: the letter after the most recent finished workout (A -> B -> C -> A)."""
    if not letters:
        return None
    done = sorted(
        (s for s in sessions if s["status"] == "done" and s["workout"] in letters),
        key=lambda s: (s["date"], s["id"]),
    )
    if not done:
        return letters[0]
    return letters[(letters.index(done[-1]["workout"]) + 1) % len(letters)]


def sessions_in_last_days(sessions, ref: date, days=7):
    out = []
    for s in sessions:
        age = (ref - date.fromisoformat(s["date"])).days
        if 0 <= age < days:
            out.append(s)
    return out


def food_totals(rows):
    return {
        "kcal": sum(float(r.get("kcal") or 0) for r in rows),
        "protein_g": sum(float(r.get("protein_g") or 0) for r in rows),
        "carbs_g": sum(float(r.get("carbs_g") or 0) for r in rows),
    }


# ---------- validation ----------

def _num(v, lo, hi, label):
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number") from None
    if not math.isfinite(n) or n < lo or n > hi:
        raise ValueError(f"{label} must be between {lo:g} and {hi:g}")
    return n


def _int(v, lo, hi, label):
    n = _num(v, lo, hi, label)
    if not n.is_integer():
        raise ValueError(f"{label} must be a whole number")
    return int(n)


def validate_program(p):
    """Returns a cleaned program dict or raises ValueError with a readable message."""
    if not isinstance(p, dict):
        raise ValueError("Program must be an object")
    if p.get("units") not in UNITS:
        raise ValueError("Units must be kg or lb")

    tz = str(p.get("timezone") or "UTC")
    try:
        ZoneInfo(tz)
    except Exception:
        raise ValueError(f"Unknown timezone: {tz}. Try something like America/Toronto or UTC.") from None

    prog = p.get("progression") or {}
    rep_min = _int(prog.get("repMin"), 1, 50, "Rep range min")
    rep_max = _int(prog.get("repMax"), rep_min, 100, "Rep range max")
    increment = _num(prog.get("increment"), 0.1, 1000, "Increment")

    nut = p.get("nutrition") or {}
    kcal = _num(nut.get("dailyCalorieTarget"), 0, 20000, "Calorie target")
    protein = _num(nut.get("dailyProteinTargetG"), 0, 1000, "Protein target")
    per_week = _int(p.get("workoutsPerWeek", 3), 1, 7, "Workouts per week")

    workouts = p.get("workouts")
    if not isinstance(workouts, dict) or not 1 <= len(workouts) <= 10:
        raise ValueError("Use between 1 and 10 workouts")

    clean_workouts = {}
    for letter, exercises in workouts.items():
        if not re.fullmatch(r"[A-Z]", str(letter)):
            raise ValueError("Workout names must be a single capital letter (A–Z)")
        if not isinstance(exercises, list) or len(exercises) > 30:
            raise ValueError(f"Workout {letter} can have up to 30 exercises")
        clean = []
        for ex in exercises:
            if not isinstance(ex, dict):
                raise ValueError(f"Workout {letter} has a malformed exercise")
            name = str(ex.get("name") or "").strip()
            if not name or len(name) > 60:
                raise ValueError("Each exercise needs a name (max 60 characters)")
            clean.append({
                "name": name,
                "sets": _int(ex.get("sets"), 1, 10, f"Sets for {name}"),
                "unit": ex.get("unit") if ex.get("unit") in EXERCISE_UNITS else "reps",
            })
        clean_workouts[letter] = clean

    return {
        "schedule": str(p.get("schedule") or "")[:200],
        "units": p["units"],
        "timezone": tz,
        "workoutsPerWeek": per_week,
        "progression": {"repMin": rep_min, "repMax": rep_max, "increment": increment},
        "nutrition": {"dailyCalorieTarget": kcal, "dailyProteinTargetG": protein},
        "workouts": clean_workouts,
    }


def validate_set(exercise, weight, reps):
    name = str(exercise or "").strip()
    if not name or len(name) > 60:
        raise ValueError("Exercise name is required (max 60 characters)")
    w = _num(weight, 0, 2000, "Weight")
    r = _int(reps, 1, 1000, "Reps")
    return {"exercise": name, "weight": w, "reps": r}


def validate_food(name, kcal, protein_g, carbs_g):
    name = str(name or "").strip()
    if not name or len(name) > 100:
        raise ValueError("Food name is required (max 100 characters)")
    return {
        "name": name,
        "kcal": _num(kcal, 0, 10000, "kcal"),
        "protein_g": _num(protein_g, 0, 1000, "Protein"),
        "carbs_g": _num(carbs_g, 0, 1000, "Carbs"),
    }
