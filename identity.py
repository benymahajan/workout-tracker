"""Who is using the app. Pure functions so they can be tested without Streamlit."""
import hmac


def check_login(username, passcode, users):
    """Returns the lowercase username if the name and passcode match an entry in `users`.

    `users` maps each name to its passcode (the [users] table in Secrets). Raises PermissionError
    with the same message for a wrong name and a wrong passcode, so the app doesn't reveal which
    names exist.
    """
    name = str(username or "").strip().lower()
    entries = {str(k).strip().lower(): str(v) for k, v in dict(users or {}).items()}
    if not entries:
        raise PermissionError("No users are set up. Add them under [users] in Secrets.")
    expected = entries.get(name)
    # Compare even when the name is unknown, so timing doesn't reveal valid names.
    ok = hmac.compare_digest(str(passcode or ""), expected or "\x00none")
    if not name or expected is None or not ok:
        raise PermissionError("Wrong name or passcode.")
    return name


def resolve_user(email, hosted, allowed=(), dev_user="local@localhost"):
    """Returns the lowercase email the app should act for.

    - Local (not hosted): uses `email` if Streamlit gave one, else the dev user.
    - Hosted: requires a signed-in email. If `allowed` is non-empty, the email must be on it.
      Streamlit's "only specific people" sharing is the first gate. `allowed` is a second one.
    """
    e = str(email or "").strip().lower()
    if not hosted:
        return e or dev_user.strip().lower()
    if not e:
        raise PermissionError("Sign in with your email to use this app.")
    allowed_set = {str(a).strip().lower() for a in allowed if str(a).strip()}
    if allowed_set and e not in allowed_set:
        raise PermissionError("This email isn't on the invite list for this app.")
    return e
