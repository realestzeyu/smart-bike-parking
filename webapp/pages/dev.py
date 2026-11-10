"""J8: /dev demo helper. Only registered when BACKEND=fake (see main.py).

Stands in for the ESP32 (bike_arrived / bike_left / tamper) and the check_overstay Lambda.
"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from backend import get_backend
from backend.base import lot_number, parse_lot_ref
from starting_data import SPACES
from templating import templates

router = APIRouter()

EVENTS = ("bike_arrived", "bike_left", "tamper")


@router.get("/dev")
def dev_page(request: Request, msg: str = ""):
    b = get_backend()
    real = {s["id"] for s in SPACES}  # stations with hardware are listed first and open
    stations = sorted(b.list_spaces(), key=lambda s: (s["id"] not in real, s["id"]))
    groups = [(s, s["id"] in real, sorted(b.list_lots(s["id"]), key=lambda l: int(lot_number(l["id"]))))
              for s in stations]
    return templates.TemplateResponse(request, "dev.html", {
        "groups": groups, "events": EVENTS, "msg": msg, "published": list(reversed(b.published[-8:])),
    })


@router.post("/dev/event")
def dev_event(lot_ref: str = Form(...), event: str = Form(...)):
    keys = parse_lot_ref(lot_ref)
    if keys and event in EVENTS:
        get_backend().simulate_event(*keys, event)
    return RedirectResponse(f"/dev?msg={event} sent to {lot_ref}", status_code=303)


@router.post("/dev/overstay")
def dev_overstay(minutes: int = Form(2)):
    flagged = get_backend().flag_overstays(minutes)
    return RedirectResponse(f"/dev?msg=Overstay check ran: {flagged} session(s) flagged", status_code=303)
