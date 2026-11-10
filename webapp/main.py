"""Smart Bicycle Parking web app (FastAPI + Jinja2 + HTMX).

Run:  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import config
from auth import LoginRequired
from backend import get_backend
from pages import public

app = FastAPI(title="Smart Bicycle Parking")
# Cookie lasts 30 days so repeat QR scans stay logged in.
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET, max_age=30 * 24 * 3600, same_site="lax")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.exception_handler(LoginRequired)
async def login_required(request: Request, exc: LoginRequired):
    return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)


app.include_router(public.router)

get_backend()  # create it at startup so fake-mode accounts are printed once
if config.BACKEND == "fake":
    print("BACKEND=fake. Test accounts: officer / officer, alice / alice")
