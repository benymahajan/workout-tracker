"""Gym tracker: a Streamlit app for logging workouts, progressive overload and food.

Run locally:  streamlit run app.py
Hosted:       Streamlit Community Cloud, with secrets pointing at a Google Sheet (see README).
"""
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st

from logic import (
    EXERCISE_UNITS,
    UNITS,
    food_totals,
    last_sets_for,
    next_workout,
    sessions_in_last_days,
    suggest_next,
    validate_food,
    validate_program,
    validate_set,
)
from progress import (
    MUSCLES,
    SETS_MAX,
    SETS_MIN,
    bodyweight_trend,
    build_context,
    default_muscle,
    exercise_history,
    is_stalled,
    new_prs_since,
    nutrition_averages,
    recommendations,
    weekly_sets_by_muscle,
    weekly_sets_history,
)
from identity import check_login, resolve_user
from store import LocalStore, open_sheets_store, uses_sheets

LOCAL_FILE = Path(os.environ.get("GYM_DATA_FILE", Path(__file__).parent / "data" / "db.json"))

st.set_page_config(page_title="Gym", page_icon="🏋️", layout="centered")


# ---------- secrets and storage ----------

def _secrets():
    try:
        return st.secrets
    except Exception:
        return {}


def _secret(name):
    try:
        return str(_secrets()[name])
    except Exception:
        return ""


@st.cache_resource(show_spinner=False)
def _sheets_store():
    return open_sheets_store(_secrets())


def is_hosted():
    return uses_sheets(_secrets())


def dev_user():
    return os.environ.get("GYM_DEV_USER", "local@localhost")


def _users_table():
    try:
        return dict(_secrets()["users"])
    except Exception:
        return {}


def current_user():
    """The signed-in user's name. Hosted: name and passcode from [users] in Secrets, kept for the session."""
    if not is_hosted():
        try:
            email = st.user.email
        except Exception:
            email = None
        return resolve_user(email, hosted=False, dev_user=dev_user())

    if st.session_state.get("user"):
        return st.session_state["user"]
    st.title("🏋️ Gym")
    st.subheader("Sign in")
    with st.form("login"):
        name = st.text_input("Name")
        passcode = st.text_input("Passcode", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        try:
            st.session_state["user"] = check_login(name, passcode, _users_table())
        except PermissionError as e:
            st.error(str(e))
        else:
            st.rerun()
    st.stop()


def get_store(user):
    """Every row this store touches belongs to `user`."""
    base = _sheets_store() if is_hosted() else LocalStore(LOCAL_FILE, legacy_owner=dev_user())
    return base.with_owner(user)


# ---------- small helpers ----------

def today_date(program):
    try:
        tz = ZoneInfo(program.get("timezone") or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def fmt_time(iso, program):
    if not iso:
        return ""
    try:
        tz = ZoneInfo(program.get("timezone") or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.fromisoformat(iso).astimezone(tz).strftime("%H:%M")


def fmt_set(x, unit, timed):
    if timed:
        return f"{x['reps']}s"
    return f"{x['weight']:g} {unit} × {x['reps']}"


def timed_names(program):
    return {
        ex["name"].strip().lower()
        for exercises in program["workouts"].values()
        for ex in exercises
        if ex.get("unit") == "seconds"
    }


def rules(program):
    p = program["progression"]
    return {"rep_min": p["repMin"], "rep_max": p["repMax"], "increment": p["increment"]}


# ---------- callbacks (run before the page re-renders) ----------

def cb_start(store, letter, program):
    store.add_session(today_date(program).isoformat(), letter, status="active")


def cb_finish(store, session_id):
    store.finish_session(session_id)


def cb_delete_set(store, set_id):
    store.delete_set(set_id)


def cb_delete_session(store, session_id):
    store.delete_session(session_id)


def cb_delete_food(store, food_id):
    store.delete_food(food_id)


def cb_remove_workout(store, letter):
    program = store.get_program()
    program["workouts"].pop(letter, None)
    store.save_program(program)


# ---------- Workout page ----------

def page_workout(store, program):
    active = store.active_session()
    if active is None:
        _start_screen(store, program)
    else:
        _active_screen(store, program, active)


def _start_screen(store, program):
    letters = list(program["workouts"].keys())
    if not letters:
        st.info("No workouts yet. Add one on the Program tab.")
        return
    sessions = store.list_sessions()
    nxt = next_workout(letters, sessions)
    done = [s for s in sessions if s["status"] == "done"]
    week = len(sessions_in_last_days(done, today_date(program), 7))

    st.subheader("Start today's workout")
    st.caption(f"Up next in your rotation: Workout {nxt} · {week} of {program['workoutsPerWeek']} this week")
    cols = st.columns(min(len(letters), 3))
    for i, letter in enumerate(letters):
        cols[i % len(cols)].button(
            f"Workout {letter}",
            key=f"start-{letter}",
            type="primary" if letter == nxt else "secondary",
            on_click=cb_start,
            args=(store, letter, program),
        )


def _active_screen(store, program, sess):
    unit = program["units"]
    planned = program["workouts"].get(sess["workout"], [])
    all_sets = store.list_sets()
    finished = [s for s in store.list_sessions() if s["status"] == "done"]
    mine = [x for x in all_sets if x["session_id"] == sess["id"]]
    timed = timed_names(program)

    total = sum(ex["sets"] for ex in planned)
    logged_total = sum(
        min(len([x for x in mine if x["exercise"].strip().lower() == ex["name"].strip().lower()]), ex["sets"])
        for ex in planned
    )

    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        c1.subheader(f"Workout {sess['workout']}")
        c1.caption(f"Started {fmt_time(sess['started_at'], program)} · {logged_total}/{total} planned sets")
        c2.button("Finish", type="primary", key=f"finish-{sess['id']}",
                  on_click=cb_finish, args=(store, sess["id"]))

    for i, ex in enumerate(planned):
        name = ex["name"]
        is_timed = name.strip().lower() in timed
        logged = [x for x in mine if x["exercise"].strip().lower() == name.strip().lower()]
        last = last_sets_for(finished, all_sets, name)
        sugg = suggest_next(last, **rules(program))

        with st.container(border=True):
            st.markdown(f"**{name}** · {len(logged)}/{ex['sets']} sets")
            if sugg:
                st.caption(f"Target: {fmt_set(sugg, unit, is_timed)} — {sugg['reason']}")
            else:
                st.caption("No history yet. Pick a weight that leaves 2–3 reps in reserve.")
            if last:
                st.caption("Last time: " + ", ".join(fmt_set(x, unit, is_timed) for x in last))

            for n, x in enumerate(logged, start=1):
                a, b = st.columns([6, 1])
                a.write(f"Set {n}: {fmt_set(x, unit, is_timed)}")
                b.button("✕", key=f"del-set-{x['id']}", on_click=cb_delete_set, args=(store, x["id"]))

            base = logged[-1] if logged else sugg
            w0 = float(base["weight"]) if base and not is_timed else 0.0
            r0 = int(base["reps"]) if base else (30 if is_timed else 8)
            suffix = f"{sess['id']}-{i}-{len(logged)}"

            with st.form(key=f"form-{suffix}", clear_on_submit=False, border=False):
                c1, c2 = st.columns(2)
                weight = c1.number_input(
                    f"Weight ({unit})", min_value=0.0, step=0.5, value=w0,
                    disabled=is_timed, key=f"w-{suffix}")
                reps = c2.number_input(
                    "Seconds" if is_timed else "Reps", min_value=0, step=1, value=r0,
                    key=f"r-{suffix}")
                submitted = st.form_submit_button("Add set", key=f"submit-{suffix}")

            if submitted:
                try:
                    clean = validate_set(name, 0.0 if is_timed else weight, reps)
                except ValueError as e:
                    st.error(str(e))
                else:
                    store.add_set(sess["id"], clean["exercise"], clean["weight"], clean["reps"])
                    st.rerun()


# ---------- Program page ----------

def page_program(store, program):
    st.subheader("Settings")
    nut = program["nutrition"]
    prog = program["progression"]
    with st.form("settings"):
        schedule = st.text_input("Schedule note", value=program.get("schedule", ""))
        c1, c2 = st.columns(2)
        units = c1.selectbox("Units", list(UNITS), index=list(UNITS).index(program["units"]))
        per_week = c2.number_input("Workouts per week", min_value=1, max_value=7,
                                   value=int(program.get("workoutsPerWeek", 3)))
        tz = st.text_input("Timezone (sets what 'today' means)", value=program.get("timezone", "UTC"),
                           help="Example: America/Toronto. Use UTC only if you're fine with evening sessions landing on the next day.")
        c3, c4 = st.columns(2)
        kcal = c3.number_input("Calorie target", min_value=0, max_value=20000, value=int(nut["dailyCalorieTarget"]))
        protein = c4.number_input("Protein target (g)", min_value=0, max_value=1000, value=int(nut["dailyProteinTargetG"]))
        c5, c6, c7 = st.columns(3)
        rep_min = c5.number_input("Rep range min", min_value=1, max_value=50, value=int(prog["repMin"]))
        rep_max = c6.number_input("Rep range max", min_value=1, max_value=100, value=int(prog["repMax"]))
        inc = c7.number_input("Weight increment", min_value=0.1, max_value=1000.0,
                              value=float(prog["increment"]), step=0.5)
        if st.form_submit_button("Save settings", type="primary"):
            try:
                new = validate_program({
                    **program,
                    "schedule": schedule,
                    "units": units,
                    "timezone": tz,
                    "workoutsPerWeek": per_week,
                    "nutrition": {"dailyCalorieTarget": kcal, "dailyProteinTargetG": protein},
                    "progression": {"repMin": rep_min, "repMax": rep_max, "increment": inc},
                })
            except ValueError as e:
                st.error(str(e))
            else:
                store.save_program(new)
                st.success("Settings saved.")
                program = new

    st.subheader("Workouts")
    st.caption("Edit exercises in the table. Add rows with the + at the bottom, or delete them. Save each workout after editing.")

    for letter, exercises in list(program["workouts"].items()):
        with st.expander(f"Workout {letter} · {len(exercises)} exercises"):
            df = pd.DataFrame(
                [{"name": ex["name"], "sets": ex["sets"], "unit": ex.get("unit", "reps"),
                  "muscle": ex.get("muscle") or default_muscle(ex["name"])} for ex in exercises],
                columns=["name", "sets", "unit", "muscle"],
            )
            edited = st.data_editor(
                df,
                key=f"ed-{letter}",
                num_rows="dynamic",
                hide_index=True,
                column_config={
                    "name": st.column_config.TextColumn("Exercise", required=True, max_chars=60),
                    "sets": st.column_config.NumberColumn("Sets", min_value=1, max_value=10, step=1, required=True),
                    "unit": st.column_config.SelectboxColumn("Unit", options=list(EXERCISE_UNITS), required=True),
                    "muscle": st.column_config.SelectboxColumn("Main muscle", options=MUSCLES, required=True),
                },
            )
            c1, c2 = st.columns(2)
            if c1.button("Save workout", key=f"save-{letter}", type="primary"):
                rows = []
                for _, r in edited.iterrows():
                    name = "" if pd.isna(r["name"]) else str(r["name"]).strip()
                    if not name:
                        continue
                    rows.append({
                        "name": name,
                        "sets": 3 if pd.isna(r["sets"]) else int(r["sets"]),
                        "unit": r["unit"] if r["unit"] in EXERCISE_UNITS else "reps",
                        "muscle": r["muscle"] if r["muscle"] in MUSCLES else default_muscle(name),
                    })
                fresh = store.get_program()
                fresh["workouts"][letter] = rows
                try:
                    store.save_program(validate_program(fresh))
                except ValueError as e:
                    st.error(str(e))
                else:
                    st.success(f"Workout {letter} saved.")
            c2.button("Remove workout", key=f"rm-{letter}", on_click=cb_remove_workout, args=(store, letter))

    st.markdown("**Add a workout**")
    c1, c2 = st.columns([1, 2])
    new_letter = c1.text_input("Letter", max_chars=1, key="new_letter").strip().upper()
    if c2.button("Add workout", key="add-workout"):
        fresh = store.get_program()
        if not new_letter or new_letter in fresh["workouts"]:
            st.error("Enter a letter that isn't already used.")
        else:
            fresh["workouts"][new_letter] = []
            try:
                store.save_program(validate_program(fresh))
                st.rerun()
            except ValueError as e:
                st.error(str(e))


# ---------- Food page ----------

def page_food(store, program):
    day = st.date_input("Day", value=today_date(program), key="food_day")
    ds = day.isoformat()
    rows = store.list_food(ds)
    totals = food_totals(rows)
    nut = program["nutrition"]
    done = [s for s in store.list_sessions() if s["status"] == "done"]
    week = len(sessions_in_last_days(done, day, 7))

    c1, c2, c3 = st.columns(3)
    c1.metric("Calories", f"{totals['kcal']:.0f} / {nut['dailyCalorieTarget']}")
    c2.metric("Protein (g)", f"{totals['protein_g']:.0f} / {nut['dailyProteinTargetG']}")
    c3.metric("Workouts (7 days)", f"{week} / {program['workoutsPerWeek']}")

    with st.form("add-food", clear_on_submit=True):
        name = st.text_input("Food", key="f_name", placeholder="e.g. Chicken & rice")
        c1, c2, c3 = st.columns(3)
        kcal = c1.number_input("kcal", min_value=0, max_value=10000, value=0, step=10)
        protein = c2.number_input("Protein g", min_value=0.0, max_value=1000.0, value=0.0, step=1.0)
        carbs = c3.number_input("Carbs g", min_value=0.0, max_value=1000.0, value=0.0, step=1.0)
        if st.form_submit_button("Add food"):
            try:
                f = validate_food(name, kcal, protein, carbs)
            except ValueError as e:
                st.error(str(e))
            else:
                store.add_food(ds, f["name"], f["kcal"], f["protein_g"], f["carbs_g"])
                st.rerun()

    st.subheader("Logged")
    if not rows:
        st.caption("Nothing logged for this day.")
    for f in rows:
        a, b = st.columns([6, 1])
        a.write(f"{f['name']} · {f['kcal']:.0f} kcal · {f['protein_g']:.0f} g protein")
        b.button("✕", key=f"del-food-{f['id']}", on_click=cb_delete_food, args=(store, f["id"]))


# ---------- History page ----------

def page_history(store, program):
    sessions = list(reversed(store.list_sessions()))[:60]
    all_sets = store.list_sets()
    unit = program["units"]
    timed = timed_names(program)
    if not sessions:
        st.info("No workouts logged yet.")
        return
    for s in sessions:
        mine = [x for x in all_sets if x["session_id"] == s["id"]]
        tag = " · in progress" if s["status"] == "active" else ""
        with st.expander(f"{s['date']} · Workout {s['workout']}{tag}"):
            by_ex = {}
            for x in mine:
                by_ex.setdefault(x["exercise"], []).append(x)
            if not by_ex:
                st.caption("No sets logged.")
            for ex_name, xs in by_ex.items():
                is_timed = ex_name.strip().lower() in timed
                st.markdown(f"**{ex_name}**: " + ", ".join(fmt_set(x, unit, is_timed) for x in xs))
            st.button("Delete this workout", key=f"delw-{s['id']}",
                      on_click=cb_delete_session, args=(store, s["id"]))


# ---------- Progress page ----------

def _chart_title(text):
    return alt.Title(text, anchor="start", fontSize=13)


def page_progress(store, program):
    weeks = st.radio("Look back", [4, 8, 12], index=1, horizontal=True,
                     format_func=lambda w: f"{w} weeks", key="prog_weeks")
    ref = today_date(program)
    cutoff = ref - timedelta(days=7 * weeks)
    unit = program["units"]
    timed = timed_names(program)

    sessions = store.list_sessions()
    done = [s for s in sessions if s["status"] == "done"]
    window = [s for s in done if date.fromisoformat(s["date"]) >= cutoff]
    window_ids = {s["id"] for s in window}
    sets = store.list_sets()
    food = store.list_food()

    window_sets = [x for x in sets if x["session_id"] in window_ids]
    lifts = [x for x in window_sets if x["exercise"].strip().lower() not in timed]
    volume = sum(x["weight"] * x["reps"] for x in lifts)
    nut = nutrition_averages(food, ref, 7 * weeks)
    target_sessions = program["workoutsPerWeek"] * weeks

    all_names = sorted({ex["name"] for exs in program["workouts"].values() for ex in exs}, key=str.lower)
    prs = sum(
        len(new_prs_since(exercise_history(done, sets, n, timed=n.strip().lower() in timed), cutoff))
        for n in all_names
    )

    st.subheader("Summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Workouts", f"{len(window)} / {target_sessions}")
    c2.metric("Hard sets", f"{len(window_sets)}")
    c3.metric("New bests (estimated 1RM)", f"{prs}")
    c4, c5 = st.columns(2)
    c4.metric("Volume load", f"{volume:,.0f} {unit}")
    c5.metric("Avg protein", f"{nut['protein_g']:.0f} g" if nut else "No data",
              help=f"Target {program['nutrition']['dailyProteinTargetG']} g/day, averaged over days with food logged")

    # ----- per exercise -----
    st.subheader("Exercise progress")
    if not all_names:
        st.info("Add exercises on the Program tab first.")
    else:
        ex_name = st.selectbox("Exercise", all_names, key="prog_ex")
        is_timed = ex_name.strip().lower() in timed
        hist_all = exercise_history(done, sets, ex_name, timed=is_timed)
        hist = [h for h in hist_all if date.fromisoformat(h["date"]) >= cutoff]
        if not hist:
            st.info("No finished sessions with this exercise in the selected window.")
        else:
            first, last = hist[0]["best"], hist[-1]["best"]
            change = (last - first) / first * 100 if first else 0.0
            best = max(h["best"] for h in hist)
            m_label = "Best hold (s)" if is_timed else f"Best est. 1RM ({unit})"
            c1, c2, c3 = st.columns(3)
            c1.metric(m_label, f"{best:g}")
            c2.metric("Change in window", f"{change:+.1f}%")
            c3.metric("Sessions", f"{len(hist)}")
            if is_stalled(hist_all):
                st.warning("No new best in the last 3 sessions. See recommendations below.")

            df = pd.DataFrame(hist)
            df["date"] = pd.to_datetime(df["date"])
            y_title = "Hold (s)" if is_timed else f"Estimated 1RM ({unit})"
            line = (
                alt.Chart(df, title=_chart_title(f"{ex_name}: {y_title} by session"))
                .mark_line(point=True)
                .encode(
                    x=alt.X("date:T", title=None),
                    y=alt.Y("best:Q", title=y_title, scale=alt.Scale(zero=False)),
                    tooltip=[alt.Tooltip("date:T", title="Date"), alt.Tooltip("best:Q", title=y_title),
                             alt.Tooltip("top_weight:Q", title=f"Top weight ({unit})"),
                             alt.Tooltip("top_reps:Q", title="Top reps"), alt.Tooltip("sets:Q", title="Sets")],
                )
            )
            st.altair_chart(line)

            if not is_timed:
                vol = (
                    alt.Chart(df, title=_chart_title(f"{ex_name}: volume load per session"))
                    .mark_bar()
                    .encode(
                        x=alt.X("date:T", title=None),
                        y=alt.Y("volume:Q", title=f"Weight × reps ({unit})"),
                        tooltip=[alt.Tooltip("date:T", title="Date"), alt.Tooltip("volume:Q", title="Volume"),
                                 alt.Tooltip("sets:Q", title="Sets")],
                    )
                )
                st.altair_chart(vol)

    # ----- muscle volume -----
    st.subheader("Hard sets per muscle")
    counts = weekly_sets_by_muscle(done, sets, program, ref)
    cdf = pd.DataFrame([{"muscle": m, "sets": n} for m, n in counts.items() if n or m != "Other"])
    if not cdf.empty:
        bars = alt.Chart(cdf, title=_chart_title(f"Last 7 days (target band {SETS_MIN}–{SETS_MAX})")).mark_bar().encode(
            x=alt.X("muscle:N", sort=None, title=None),
            y=alt.Y("sets:Q", title="Hard sets"),
            tooltip=["muscle:N", "sets:Q"],
        )
        band = alt.Chart(pd.DataFrame({"y": [SETS_MIN, SETS_MAX]})).mark_rule(strokeDash=[4, 4]).encode(y="y:Q")
        st.altair_chart(bars + band)

    trend = pd.DataFrame(weekly_sets_history(done, sets, program, ref, weeks=weeks))
    if not trend.empty:
        trend["week_ending"] = pd.to_datetime(trend["week_ending"])
        tl = alt.Chart(trend, title=_chart_title("Hard sets per muscle, week by week")).mark_line(point=True).encode(
            x=alt.X("week_ending:T", title=None),
            y=alt.Y("sets:Q", title="Hard sets"),
            color=alt.Color("muscle:N", title=None),
            tooltip=["muscle:N", "sets:Q", alt.Tooltip("week_ending:T", title="Week ending")],
        )
        st.altair_chart(tl)

    # ----- bodyweight -----
    st.subheader("Bodyweight")
    bodyweight = store.list_bodyweight()
    with st.form("add-bw", clear_on_submit=False):
        c1, c2 = st.columns(2)
        bw_day = c1.date_input("Date", value=ref, key="bw_day")
        last_w = float(bodyweight[-1]["weight"]) if bodyweight else 70.0
        bw_weight = c2.number_input(f"Weight ({unit})", min_value=20.0, max_value=1000.0,
                                    value=last_w, step=0.1, key="bw_weight")
        if st.form_submit_button("Log weight"):
            store.add_bodyweight(bw_day.isoformat(), float(bw_weight))
            st.rerun()

    bw_window = [b for b in bodyweight if date.fromisoformat(b["date"]) >= cutoff]
    trend = bodyweight_trend(bodyweight, ref, days=7 * weeks)
    if not bw_window:
        st.caption("No weigh-ins in this window yet.")
    else:
        bdf = pd.DataFrame(bw_window)
        bdf["date"] = pd.to_datetime(bdf["date"])
        bw_chart = alt.Chart(bdf, title=_chart_title(f"Bodyweight ({unit})")).mark_circle(size=60).encode(
            x=alt.X("date:T", title=None),
            y=alt.Y("weight:Q", title=unit, scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("date:T", title="Date"), alt.Tooltip("weight:Q", title=unit)],
        )
        if len(bdf) >= 2:
            bw_chart = bw_chart + alt.Chart(bdf).transform_regression(
                "date", "weight", method="linear").mark_line(color="#6b7280", strokeDash=[4, 4]).encode(
                x="date:T", y="weight:Q")
        st.altair_chart(bw_chart)
    if trend:
        c1, c2 = st.columns(2)
        c1.metric("Trend per week", f"{trend['pct_per_week']:+.2f}%", f"{trend['per_week']:+.2f} {unit}")
        c2.metric("Latest", f"{trend['latest']:.1f} {unit}")
    else:
        st.caption("Log at least 3 weigh-ins spread over 10+ days to see a trend.")

    # ----- recommendations -----
    st.subheader("Recommendations")
    ctx = build_context(sessions, sets, food, program, ref, bodyweight=bodyweight)
    icons = {"action": st.warning, "tip": st.info, "good": st.success}
    for level, text in recommendations(ctx):
        icons[level](text)

    with st.expander("Hypertrophy basics"):
        st.markdown(
            f"""
- **Weekly volume:** aim for about **{SETS_MIN}–{SETS_MAX} hard sets per muscle per week**, spread over 2–3 sessions.
- **Effort:** most working sets should end about **1–3 reps short of failure**.
- **Rep ranges:** muscle grows across a wide range (roughly 6–30 reps) when sets are close to failure. Heavier work for strength, moderate work for volume.
- **Progressive overload:** add reps, then load, over time. Log every set so the trend is real.
- **Rest:** 2–3 minutes between heavy compound sets.
- **Protein:** about **1.6 g per kg of bodyweight per day**, spread over 3–4 meals.
- **Energy:** a small surplus (about 200–300 kcal/day) supports gain. Large surpluses mostly add fat.
- **Sleep:** 7–9 hours. Recovery happens here.
- **Deloads:** when lifts stall for 2–3 weeks, or every 6–8 weeks, take a lighter week.

*General fitness information, not medical advice. If you have an injury or condition, check with a clinician or a qualified coach.*
"""
        )


# ---------- app ----------

user = current_user()

store = get_store(user)
program = store.get_program()

st.title("🏋️ Gym")
st.sidebar.caption(f"Signed in as {user}")
if is_hosted() and st.sidebar.button("Sign out"):
    del st.session_state["user"]
    st.rerun()
st.sidebar.caption(f"Storage: {store.kind}")
if store.kind == "local file":
    st.sidebar.caption("Local file storage is fine on your PC. A hosted app needs Google Sheets secrets (see README), or data can be lost on restart.")

page = st.radio("Section", ["Workout", "Program", "Food", "History", "Progress"],
                horizontal=True, label_visibility="collapsed", key="page")

if page == "Workout":
    page_workout(store, program)
elif page == "Program":
    page_program(store, program)
elif page == "Food":
    page_food(store, program)
elif page == "History":
    page_history(store, program)
else:
    page_progress(store, program)
