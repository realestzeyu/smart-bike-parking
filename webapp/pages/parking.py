"""My parking tab: the cyclist's bike(s) parked right now, and their recent parkings. Login required."""

from fastapi import APIRouter, Request

from auth import require_user
from backend import get_backend
from backend.base import lot_number, lot_ref
from templating import templates

router = APIRouter()


@router.get("/my-parking")
def my_parking(request: Request):
    user = require_user(request)
    b = get_backend()
    sessions = b.list_user_sessions(user["id"])
    spaces = {s["id"]: s for s in b.list_spaces()}

    # A parking is "current" while its lot still points at it: taken, releasing or awaiting_lock
    # (awaiting_lock keeps user_id + session_id). One GetItem per distinct lot.
    lots = {}
    for lot_id in {s["lot_id"] for s in sessions} | ({user["pending_lock_lot_id"]} if user.get("pending_lock_lot_id") else set()):
        lots[lot_id] = b.get_lot(lot_id.split("#")[0], lot_id)

    def row(session, lot):
        space = spaces.get(session["lot_id"].split("#")[0], {})
        return {**session, "lot": lot or {}, "address": space.get("address", ""),
                "n": lot_number(session["lot_id"]), "ref": lot_ref(session["lot_id"])}

    current, history = [], []
    for s in sessions:
        lot = lots.get(s["lot_id"])
        if lot and lot.get("session_id") == s["id"] and lot.get("user_id") == user["id"]:
            current.append(row(s, lot))
        elif s.get("end_time"):
            history.append(row(s, lot))

    # Tied to a lot with the lock left open, but its session isn't in the list (index lag / older): show it anyway.
    pending = lots.get(user.get("pending_lock_lot_id"))
    if pending and pending.get("user_id") == user["id"] and not any(c["lot_id"] == pending["id"] for c in current):
        session = b.get_session(pending["session_id"]) if pending.get("session_id") else None
        current.append(row(session or {"id": "", "lot_id": pending["id"], "start_time": ""}, pending))

    return templates.TemplateResponse(request, "parking.html", {
        "user": user, "current": current, "history": history,
    })
