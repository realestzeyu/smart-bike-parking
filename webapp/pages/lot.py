"""J2-J5: the lot page opened by the QR sticker, e.g. /lot/space1_lot1.

The page only shows what the logged-in user may do; every POST re-checks on the server
(claim is a conditional write; unlock checks the owner).
"""

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from auth import current_user
from backend import get_backend
from backend.base import parse_lot_ref
from templating import SGT, templates

router = APIRouter()


def load(lot_ref):
    keys = parse_lot_ref(lot_ref)
    lot = get_backend().get_lot(*keys) if keys else None
    if not lot:
        raise HTTPException(status_code=404, detail="Lot not found")
    return keys[0], keys[1], lot


def back_to(lot_ref, step="", sent=False):
    """Back to the lot page. sent=True shows "Open signal sent ... at 14:52:03" so a repeat press visibly works."""
    params = []
    if step:
        params.append(f"step={step}")
    if sent:
        params.append("sent=" + quote(datetime.now(SGT).strftime("%H:%M:%S")))
    return RedirectResponse(f"/lot/{lot_ref}" + ("?" + "&".join(params) if params else ""), status_code=303)


@router.get("/lot/{lot_ref}")
def lot_page(request: Request, lot_ref: str, step: str = "", sent: str = ""):
    space_id, lot_id, lot = load(lot_ref)
    b = get_backend()
    user = current_user(request)
    mine = bool(user) and lot.get("user_id") == user["id"]

    if lot["status"] == "free":
        state = "free"
    elif not mine:
        state = "in_use"
    elif lot["status"] == "releasing":
        state = "released"  # J4.2: unlocked, waiting for the bike to leave
    elif step == "locked":
        state = "locked"  # J2.7: just claimed, cable released for locking
    else:
        state = "mine"  # J4.1: owner came back

    session = b.get_session(lot["session_id"]) if mine and lot.get("session_id") else None
    return templates.TemplateResponse(request, "lot.html", {
        "lot": lot, "lot_ref": lot_ref, "space": b.get_space(space_id), "state": state,
        "user": user, "session": session, "sent": sent if state in ("locked", "released") else "",
    })


@router.post("/lot/{lot_ref}/use")
def use_lot(request: Request, lot_ref: str):
    space_id, lot_id, _ = load(lot_ref)
    user = current_user(request)
    if not user:
        return RedirectResponse(f"/login?next=/lot/{lot_ref}", status_code=303)
    b = get_backend()
    if not b.claim_lot(space_id, lot_id, user["id"]):
        return back_to(lot_ref)  # someone was faster: page now shows "in use"
    b.publish_open(lot_id)
    return back_to(lot_ref, "locked", sent=True)


@router.post("/lot/{lot_ref}/open")
def open_again(request: Request, lot_ref: str):
    """Release again (while locking) / Unlock again (while collecting). Owner only."""
    _, lot_id, lot = load(lot_ref)
    user = current_user(request)
    sent = bool(user) and lot.get("user_id") == user["id"] and lot["status"] in ("taken", "releasing")
    if sent:
        get_backend().publish_open(lot_id)
    return back_to(lot_ref, "locked" if lot["status"] == "taken" else "", sent=sent)


@router.post("/lot/{lot_ref}/unlock")
def unlock(request: Request, lot_ref: str):
    space_id, lot_id, _ = load(lot_ref)
    user = current_user(request)
    b = get_backend()
    if user and b.mark_releasing(space_id, lot_id, user["id"]):
        b.publish_open(lot_id)
        return back_to(lot_ref, sent=True)
    return back_to(lot_ref)
