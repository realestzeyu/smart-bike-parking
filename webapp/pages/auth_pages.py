"""J2/J3/J7: log in, sign up (cyclists only), log out, Connect Telegram."""

import re
import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

import config
import telegram_link
from auth import check_password, current_user, log_in, log_out, require_user, safe_next
from backend import get_backend
from templating import templates

router = APIRouter()

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,20}$")


@router.get("/login")
def login_page(request: Request, next: str = "/"):
    # Always show the form: logging in again switches account (e.g. cyclist -> officer).
    return templates.TemplateResponse(request, "login.html", {
        "next": safe_next(next), "error": None, "username": "", "user": current_user(request),
    })


@router.post("/login")
def login_submit(request: Request, username: str = Form(""), password: str = Form(""), next: str = Form("/")):
    user = check_password(username, password)
    if not user:
        return templates.TemplateResponse(request, "login.html", {
            "next": safe_next(next), "username": username, "user": current_user(request),
            "error": "Wrong username or password. Check both and try again.",
        }, status_code=400)
    request.session.clear()  # switching account: drop the old login and any Telegram code
    log_in(request, user)
    default = "/officer" if user.get("role") == "officer" else "/"
    return RedirectResponse(safe_next(next, default) if next != "/" else default, status_code=303)


@router.get("/signup")
def signup_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(request, "signup.html", {"next": safe_next(next), "error": None, "form": {}})


@router.post("/signup")
def signup_submit(request: Request, username: str = Form(""), name: str = Form(""), email: str = Form(""),
                  password: str = Form(""), next: str = Form("/")):
    username, name, email = username.strip().lower(), name.strip(), email.strip()
    if not USERNAME_RE.match(username):
        error = "Username: 3 to 20 lowercase letters, numbers or _."
    elif not name:
        error = "Enter your name."
    elif "@" not in email or "." not in email.split("@")[-1]:
        error = "Enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    else:
        error = get_backend().sign_up(username, name, email, password)
    if error:
        return templates.TemplateResponse(request, "signup.html", {
            "next": safe_next(next), "error": error, "form": {"username": username, "name": name, "email": email},
        }, status_code=400)
    log_in(request, get_backend().get_user(username))
    # J2.5: offer Connect Telegram, then back to where they came from.
    return RedirectResponse(f"/connect-telegram?next={safe_next(next)}", status_code=303)


@router.get("/profile")
def profile(request: Request):
    return templates.TemplateResponse(request, "profile.html", {"user": current_user(request)})


@router.post("/logout")
def logout(request: Request, next: str = Form("/")):
    log_out(request)
    return RedirectResponse(safe_next(next), status_code=303)


@router.get("/connect-telegram")
def telegram_page(request: Request, next: str = "/"):
    user = require_user(request)
    ready = bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_BOT_USERNAME)
    if ready and "tg_code" not in request.session:
        request.session["tg_code"] = secrets.token_hex(6)
    link = f"https://t.me/{config.TELEGRAM_BOT_USERNAME}?start={request.session.get('tg_code')}" if ready else None
    return templates.TemplateResponse(request, "telegram.html", {
        "next": safe_next(next), "link": link, "user": user, "error": None,
    })


@router.post("/connect-telegram")
def telegram_done(request: Request, next: str = Form("/")):
    user = require_user(request)
    code = request.session.get("tg_code")
    chat_id = telegram_link.find_chat_id(code) if code else None
    if chat_id is None:
        link = f"https://t.me/{config.TELEGRAM_BOT_USERNAME}?start={code}" if code else None
        return templates.TemplateResponse(request, "telegram.html", {
            "next": safe_next(next), "link": link, "user": user,
            "error": "We couldn't find your Start message yet. Open Telegram, tap Start, then tap Done again.",
        }, status_code=400)
    get_backend().set_telegram_chat_id(user["id"], chat_id)
    request.session.pop("tg_code", None)
    return RedirectResponse(safe_next(next), status_code=303)
