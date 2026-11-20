"""Login state in the signed session cookie. Passwords are checked by the backend (Cognito when BACKEND=aws)."""

from fastapi import Request

from backend import get_backend


class LoginRequired(Exception):
    """Raised by require_user; main.py turns it into a redirect to /login?next=..."""


class OfficerRequired(Exception):
    """Raised by require_officer for a logged-in cyclist; main.py shows the "officers only" page."""

    def __init__(self, user):
        self.user = user


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
        raise OfficerRequired(user)
    return user


def check_password(username, password):
    """Returns the user if the username and password are right, else None."""
    return get_backend().authenticate(username.strip().lower(), password)


def safe_next(value, default="/"):
    """Only allow redirects to our own pages (blocks //evil.com and full URLs)."""
    return value if value and value.startswith("/") and not value.startswith("//") else default


def log_in(request: Request, user):
    request.session["username"] = user["id"]


def log_out(request: Request):
    request.session.clear()
