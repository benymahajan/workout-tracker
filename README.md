# Gym tracker (Streamlit)

Log workouts set-by-set from your phone at the gym, follow progressive overload (A/B/C
rotation), and track daily calories and protein. Hosted free on Streamlit Community Cloud,
with data kept in a Google Sheet you own.

## Run locally (optional, for testing)

```powershell
cd C:\Users\ku9086813\gym-streamlit
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Without secrets it saves to `data/db.json` on your PC. Run the tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

## Host it so your phone can reach it

Hosted apps lose local files on restart, so the data lives in a Google Sheet. Do the steps below
with a **personal** Google account and GitHub account, not work ones. That keeps your health data
off work systems and avoids work policies on service accounts.

### 1. Create the Google Sheet

1. Go to sheets.google.com and create a blank spreadsheet called `gym-data`.
2. Copy its ID from the URL: the long string between `/d/` and `/edit`.
3. You don't need to create tabs. The app creates `sessions`, `sets`, `food` and `program` on first run.

### 2. Create a Google service account (lets the app read and write that sheet)

1. Go to console.cloud.google.com and create a project (any name).
2. **APIs & Services > Library**: enable **Google Sheets API** and **Google Drive API**.
3. **IAM & Admin > Service Accounts > Create service account**. Give it any name. No roles needed.
4. Open the new account, go to **Keys > Add key > Create new key > JSON**. A `.json` file downloads.
5. Copy the account's `client_email` (ends in `iam.gserviceaccount.com`). Open your Sheet,
   click **Share**, and add that email as **Editor**.

### 3. Put the code on GitHub (private)

```powershell
cd C:\Users\ku9086813\gym-streamlit
git add -A
git commit -m "Gym tracker"
```

Create a **private** repository on GitHub under your personal account, then push this folder to it.
`.gitignore` keeps `secrets.toml` and local data out of the repo.

### 4. Deploy on Streamlit Community Cloud

1. Go to share.streamlit.io and sign in with GitHub.
2. **Create app > Deploy from GitHub**. Pick the repo, branch `main`, and main file `app.py`.
3. Open **Advanced settings**, choose Python 3.12 or newer, then paste into **Secrets**. Use
   `.streamlit/secrets.toml.example` as the template. Fill in `sheet_key`, `LEGACY_OWNER`, `ALLOWED_EMAILS`, and the
   fields from the downloaded JSON key under `[gcp_service_account]`.
4. Click **Deploy**.
5. In the app's menu, open **Settings > Sharing** and choose **Anyone with the link**. People then
   reach the app directly, and the name and passcode in Secrets are the lock.

Bookmark the URL on your phone, or use the browser's "Add to Home Screen."

### 5. Set your timezone

Open the **Program** tab, Settings, and set **Timezone** (for example `America/Toronto`). Otherwise
"today" follows UTC, and evening sessions can land on the next day. Save settings.

## Multi-user: inviting friends

Each person signs in with a name and passcode, and sees only their own workouts, food,
bodyweight, and program.

**Before you invite anyone:**
- **You can read every row.** You own the Google Sheet and the app, so you can open the Sheet and
  see everyone's data. Tell friends this before they join. If someone doesn't want that, they
  should run their own copy instead.
- The app's code is public. The data isn't in the repo, but anyone can read the code and see how it works.
- The app URL is open to anyone who has it. Only someone with a name and passcode gets in.

**To add a friend:**
1. In Streamlit's **Secrets**, add a line under `[users]`: `name = "passcode"`. Use a long passcode
   and a different one per person.
2. Send them the app URL, their name, and their passcode over a private channel. They sign in with
   the name and passcode. Nothing else to install.
3. To remove someone, delete their line under `[users]` and reboot the app.

**Secrets to set for multi-user** (replace the old `APP_PASSWORD`, `ALLOWED_EMAILS`):

```toml
LEGACY_OWNER = "you"                    # owns rows saved before accounts existed
[users]
you = "your-long-passcode"
friend = "their-long-passcode"
```

`LEGACY_OWNER` must match one of the names under `[users]`. It gives your existing data to you.
Without it, that data is hidden from everyone.

**What changed in the Sheet:** each tab has an `owner` column at the end holding the person's name.
Rows saved before this change belong to `LEGACY_OWNER`. The `program` tab now has one row per user.
The app creates or updates these columns automatically on the next run.
## Using it

- **Workout:** Tap the workout you're doing (the next one in the rotation is highlighted). Each
  exercise shows the target from your last finished session and what you did last time. Enter
  weight and reps, tap **Add set**, and it's saved straight away. Tap **Finish** when done.
- **Program:** Edit the settings. Under each workout, edit exercises in the table, use the **+**
  row to add one or delete a row to remove one, and tap **Save workout**. Add or remove whole
  workouts (A, B, C, and so on) at the bottom of the page.
- **Food:** Log calories, protein, and carbs per day. Today's totals sit at the top.
- **History:** Review sessions and delete mistakes.
- **Progress:** Pick 4, 8, or 12 weeks. You get the summary numbers (workouts, hard sets, volume,
  new bests, average protein), a per-exercise chart of estimated 1RM and volume, weekly hard sets
  per muscle against the 10–20 band, and recommendations. Recommendations cover missed sessions,
  low or high weekly volume, stalled lifts (with a deload suggestion), protein and calorie intake,
  and what's working. A "Hypertrophy basics" section sums up the guidance.

- **Bodyweight:** log a weigh-in on the Progress tab a few times a week. The app fits a trend line
  and reports change per week as a percent of bodyweight. Recommendations use that trend: about
  0.1–0.5%/week is the lean-gain range. Faster gain means more fat, and flat weight with intake
  below target means eat more.

Progress uses the **Main muscle** column on the Program tab. Set it per exercise so weekly volume
is counted correctly. The app fills in common exercises for you.

Estimated 1RM uses the Epley formula (`weight × (1 + reps / 30)`). It's a trend measure, not a
tested max. Progress and recommendations are general fitness information, not medical advice.

## How progression works

Double progression. Stay at a weight and add reps until every set reaches the top of the rep range
(default 8–12). Then add the increment (default 2.5) and drop back to the bottom of the range.
The suggestion uses your last *finished* session only.

## Files

| File | What it does |
|---|---|
| `app.py` | The Streamlit UI (four sections) |
| `logic.py` | Progression, rotation, totals, validation. No UI or storage. |
| `progress.py` | Progress metrics (e1RM, stalls, weekly sets per muscle) and recommendation rules |
| `store.py` | Storage: `LocalStore` (JSON file) or `SheetsStore` (Google Sheet) |
| `default_program.json` | Starting A/B/C program, used until you edit it in the app |
| `tests/` | Unit tests, a fake-Sheets test, and UI flow tests |
