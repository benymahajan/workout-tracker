"""Who is using the app. Pure function so it can be tested without Streamlit."""


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
