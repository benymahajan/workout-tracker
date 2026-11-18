"""Progress metrics and hypertrophy recommendations. Pure functions: no UI, no storage.

Guidance is general fitness information, not medical advice. It draws on:
- Dose-response meta-analyses (e.g. Schoenfeld et al. 2017): most growth happens at roughly
  10+ hard sets per muscle per week, with diminishing returns past about 20.
- Effort: most working sets within roughly 1–3 reps of failure.
- Protein (e.g. Morton et al. 2018): about 1.6 g per kg of bodyweight per day is the
  research-supported level for muscle gain.
- Progressive overload: adding reps, sets, or load over time is the main driver of progress.
"""
from __future__ import annotations

from datetime import date, timedelta

MUSCLES = [
    "Quads", "Hamstrings", "Glutes", "Chest", "Back", "Shoulders",
    "Biceps", "Triceps", "Calves", "Core", "Other",
]

# Used when an exercise has no muscle set in the program. Edit it in the Program tab.
DEFAULT_MUSCLE = {
    "back squat": "Quads", "front squat": "Quads", "leg press": "Quads",
    "romanian deadlift": "Hamstrings", "lying leg curl": "Hamstrings",
    "hip thrust": "Glutes",
    "bench press": "Chest", "incline dumbbell press": "Chest",
    "seated cable row": "Back", "lat pulldown": "Back", "chest-supported row": "Back",
    "overhead press": "Shoulders", "lateral raise": "Shoulders",
    "dumbbell curl": "Biceps", "plank": "Core",
}

SETS_MIN = 10   # hard sets per muscle per week
SETS_MAX = 20


def default_muscle(name):
    return DEFAULT_MUSCLE.get(str(name).strip().lower(), "Other")


def muscle_map(program):
    """exercise name (lowercase) -> muscle, from the program."""
    out = {}
    for exercises in program["workouts"].values():
        for ex in exercises:
            out[ex["name"].strip().lower()] = ex.get("muscle") or default_muscle(ex["name"])
    return out


def timed_names(program):
    return {
        ex["name"].strip().lower()
        for exercises in program["workouts"].values()
        for ex in exercises
        if ex.get("unit") == "seconds"
    }


def e1rm(weight, reps):
    """Estimated one-rep max (Epley). Good enough for tracking trends."""
    return weight * (1 + reps / 30) if reps > 0 else 0.0


# ---------- per-exercise history ----------

def exercise_history(sessions, sets, exercise, timed=False):
    """One row per finished session that included the exercise, oldest first.

    `best` is the estimated 1RM for weighted lifts, or the longest hold for timed exercises.
    """
    name = exercise.strip().lower()
    rows = []
    for s in sorted(sessions, key=lambda s: (s["date"], s["id"])):
        if s["status"] != "done":
            continue
        mine = [x for x in sets
                if x["session_id"] == s["id"] and x["exercise"].strip().lower() == name]
        if not mine:
            continue
        if timed:
            best = max(x["reps"] for x in mine)
            volume = 0.0
        else:
            best = max(e1rm(x["weight"], x["reps"]) for x in mine)
            volume = sum(x["weight"] * x["reps"] for x in mine)
        rows.append({
            "session_id": s["id"],
            "date": s["date"],
            "best": round(best, 1),
            "volume": round(volume),
            "sets": len(mine),
            "top_weight": max(x["weight"] for x in mine),
            "top_reps": max(x["reps"] for x in mine),
        })
    return rows


def is_stalled(history, window=3):
    """True if none of the last `window` sessions beat the best from before them."""
    if len(history) < window + 1:
        return False
    prior_best = max(h["best"] for h in history[:-window])
    recent_best = max(h["best"] for h in history[-window:])
    return recent_best <= prior_best


def new_prs_since(history, since: date):
    """Sessions on/after `since` that set a new best (beat everything before them)."""
    prs = []
    best_so_far = None
    for h in history:
        if best_so_far is not None and h["best"] > best_so_far and date.fromisoformat(h["date"]) >= since:
            prs.append(h)
        best_so_far = h["best"] if best_so_far is None else max(best_so_far, h["best"])
    return prs


# ---------- weekly volume per muscle ----------

def _recent_done_ids(sessions, ref, days):
    return {
        s["id"] for s in sessions
        if s["status"] == "done" and 0 <= (ref - date.fromisoformat(s["date"])).days < days
    }


def weekly_sets_by_muscle(sessions, sets, program, ref, days=7):
    """Hard sets per muscle in the last `days` days, including muscles with zero."""
    mmap = muscle_map(program)
    ids = _recent_done_ids(sessions, ref, days)
    counts = {m: 0 for m in MUSCLES if m in set(mmap.values())}
    for x in sets:
        if x["session_id"] in ids:
            m = mmap.get(x["exercise"].strip().lower(), "Other")
            counts[m] = counts.get(m, 0) + 1
    return counts


def weekly_sets_history(sessions, sets, program, ref, weeks=8):
    """Rows of {week_ending, muscle, sets}, where week 0 is the last 7 days."""
    mmap = muscle_map(program)
    done = {s["id"]: s for s in sessions if s["status"] == "done"}
    buckets = {}
    for x in sets:
        s = done.get(x["session_id"])
        if not s:
            continue
        k = (ref - date.fromisoformat(s["date"])).days // 7
        if 0 <= k < weeks:
            key = (k, mmap.get(x["exercise"].strip().lower(), "Other"))
            buckets[key] = buckets.get(key, 0) + 1
    rows = []
    for k in range(weeks - 1, -1, -1):
        end = ref - timedelta(days=7 * k)
        for m in MUSCLES:
            n = buckets.get((k, m), 0)
            if n and m in set(mmap.values()) | {"Other"}:
                rows.append({"week_ending": end.isoformat(), "muscle": m, "sets": n})
    return rows


# ---------- nutrition ----------

def nutrition_averages(food, ref, days=7):
    """Averages over days that have any food logged in the last `days` days, or None."""
    by_day = {}
    for f in food:
        age = (ref - date.fromisoformat(f["date"])).days
        if 0 <= age < days:
            tot = by_day.setdefault(f["date"], [0.0, 0.0])
            tot[0] += float(f.get("kcal") or 0)
            tot[1] += float(f.get("protein_g") or 0)
    if not by_day:
        return None
    n = len(by_day)
    return {
        "days": n,
        "kcal": sum(v[0] for v in by_day.values()) / n,
        "protein_g": sum(v[1] for v in by_day.values()) / n,
    }


# ---------- recommendations ----------

def build_context(sessions, sets, food, program, ref):
    done = [s for s in sessions if s["status"] == "done"]
    timed = timed_names(program)
    names = sorted({ex["name"] for exs in program["workouts"].values() for ex in exs}, key=str.lower)

    stalled, improving = [], []
    for name in names:
        h = exercise_history(done, sets, name, timed=name.strip().lower() in timed)
        if len(h) < 4:
            continue
        if is_stalled(h):
            stalled.append(name)
        elif h[-1]["best"] > h[-4]["best"]:
            improving.append(name)

    nut = nutrition_averages(food, ref, 7)
    return {
        "sessions_this_week": len(_recent_done_ids(sessions, ref, 7)),
        "sessions_target": int(program.get("workoutsPerWeek", 3)),
        "weekly_sets": weekly_sets_by_muscle(sessions, sets, program, ref),
        "stalled": stalled,
        "improving": improving,
        "avg_kcal": nut["kcal"] if nut else None,
        "avg_protein": nut["protein_g"] if nut else None,
        "kcal_target": program["nutrition"]["dailyCalorieTarget"],
        "protein_target": program["nutrition"]["dailyProteinTargetG"],
    }


def recommendations(ctx):
    """Returns a list of (level, text). Levels: 'action', 'tip', 'good'."""
    out = []

    n, target = ctx["sessions_this_week"], ctx["sessions_target"]
    if n < target:
        out.append(("action", f"You logged {n} of {target} workouts this week. Hitting every session "
                              f"matters more than any single tweak. Aim for all {target}."))

    in_range = []
    for m, count in ctx["weekly_sets"].items():
        if m == "Other":
            continue
        if count < SETS_MIN:
            out.append(("action", f"{m}: {count} hard sets this week. Aim for {SETS_MIN}–{SETS_MAX} "
                                  f"so this muscle gets enough stimulus. Add a set or an exercise for it."))
        elif count > SETS_MAX:
            out.append(("tip", f"{m}: {count} sets this week, above the ~{SETS_MAX} range where extra "
                               f"sets add little. Check recovery before adding more."))
        else:
            in_range.append(f"{m} ({count})")
    if in_range:
        out.append(("good", "Volume in the 10–20 range: " + ", ".join(in_range) + "."))

    for name in ctx["stalled"]:
        out.append(("action", f"{name}: no new best in your last 3 sessions. Try a deload week "
                              f"(same sets, about 10% lighter), or hold the weight and push for the top "
                              f"of the rep range before adding load. Check sleep and food first."))
    for name in ctx["improving"]:
        out.append(("good", f"{name}: still progressing. Keep the plan."))

    pt, ap = ctx["protein_target"], ctx["avg_protein"]
    if ap is None:
        out.append(("tip", "Log food to get protein feedback. Protein is one of the main levers for muscle."))
    elif ap < 0.9 * pt:
        out.append(("action", f"Protein averages {ap:.0f} g/day against your {pt} g target. Close the gap. "
                              f"About 1.6 g per kg of bodyweight a day is the research-supported range for muscle gain."))
    else:
        out.append(("good", f"Protein on target ({ap:.0f} g/day average)."))

    kt, ak = ctx["kcal_target"], ctx["avg_kcal"]
    if ak is not None:
        if ak < 0.9 * kt and ctx["stalled"]:
            out.append(("action", f"Intake averages {ak:.0f} kcal/day, well under target, and lifts are stalling. "
                                  f"Eat closer to target. A small surplus (about 200–300 kcal/day) supports building muscle."))
        elif ak < 0.9 * kt:
            out.append(("tip", f"Intake averages {ak:.0f} kcal/day, well under target. Fine for fat loss, "
                               f"but for muscle gain aim near target."))
        elif ak > 1.15 * kt:
            out.append(("tip", f"Intake averages {ak:.0f} kcal/day, over target. That helps building muscle, "
                               f"but keep the surplus modest to limit fat gain."))

    if not any(level == "action" for level, _ in out):
        out.append(("good", "Nothing urgent. Keep the basics steady: consistent sessions, progressive overload, "
                            "and sleep."))
    return out
