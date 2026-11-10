"""Login state in the signed session cookie. Passwords are plaintext (PoC only)."""

from fastapi import HTTPException, Request

from backend import get_backend


class LoginRequired(Exception):
    """Raised by require_user; main.py turns it into a redirect to /login?next=..."""


def current_user(request: Request):
    username = request.session.get("username")
    return get_backend().get_user(username) if username else None


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise LoginRequired()
    return user


def require_officer(request: Request):
    user = require_user(request)
    if user.get("role") != "officer":
        raise HTTPException(status_code=403, detail="Officers only")
    return user


def check_password(username, password):
    """Returns the user if the plaintext password matches, else None."""
    user = get_backend().get_user(username.strip().lower())
    return user if user and user.get("password") == password else None


def log_in(request: Request, user):
    request.session["username"] = user["id"]


def log_out(request: Request):
    request.session.clear()
