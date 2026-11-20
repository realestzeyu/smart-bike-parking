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
from backend.base import lot_number, parse_lot_ref
from backend.base import lot_ref as lot_ref_of
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
        if user and step == "released":
            state = "done"  # J4.3: bike gone and lock closed again, parking finished
        elif user and step == "gone":
            state = "gone"  # Unlock found the bike already gone: lot freed directly
        else:
            state = "free"
    elif not mine:
        state = "in_use"
    elif lot["status"] == "awaiting_lock":
        state = "awaiting_lock"  # J4.4: bike taken, lock left open; account tied until it closes
    elif lot["status"] == "releasing":
        state = "released"  # J4.2: unlocked, waiting for the bike to leave
    elif step == "locked":
        state = "locked"  # J2.7: just claimed, cable released for locking
    else:
        state = "mine"  # J4.1: owner came back

    # Account tied to another lot whose lock was left open: no new parking until it's closed.
    blocked = None
    if state == "free" and user and user.get("pending_lock_lot_id"):
        pending = user["pending_lock_lot_id"]
        blocked = {"address": (b.get_space(pending.split("#")[0]) or {}).get("address", ""),
                   "n": lot_number(pending), "ref": lot_ref_of(pending)}

    session = b.get_session(lot["session_id"]) if mine and lot.get("session_id") else None
    return templates.TemplateResponse(request, "lot.html", {
        "lot": lot, "lot_ref": lot_ref, "space": b.get_space(space_id), "state": state,
        "user": user, "session": session, "sent": sent if state in ("locked", "released") else "",
        "blocked": blocked,
    })


@router.post("/lot/{lot_ref}/use")
def use_lot(request: Request, lot_ref: str):
    space_id, lot_id, _ = load(lot_ref)
    user = current_user(request)
    if not user:
        return RedirectResponse(f"/login?next=/lot/{lot_ref}", status_code=303)
    if user.get("pending_lock_lot_id"):
        return back_to(lot_ref)  # page shows "Close the lock at ... first"
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
    return back_to(lot_ref, "locked" if lot["status"] == "taken" else "released", sent=sent)


@router.post("/lot/{lot_ref}/unlock")
def unlock(request: Request, lot_ref: str):
    space_id, lot_id, _ = load(lot_ref)
    user = current_user(request)
    b = get_backend()
    result = b.mark_releasing(space_id, lot_id, user["id"]) if user else False
    if result == "releasing":
        b.publish_open(lot_id)
        return back_to(lot_ref, "released", sent=True)
    if result == "freed":
        return back_to(lot_ref, "gone")  # bike already gone: no open command needed
    return back_to(lot_ref)
