"""J7: officer console (mockup "Government dashboard") and Force unlock. Officers only."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import config
from auth import require_officer
from backend import get_backend
from backend.base import lot_number, parse_lot_ref
from templating import templates

router = APIRouter()


def console_data():
    """Everything the console shows, computed from the backend (no stored counters)."""
    b = get_backend()
    spaces = {s["id"]: s for s in b.list_spaces()}
    lots = [lot for sid in spaces for lot in b.list_lots(sid)]
    occupied = sum(1 for lot in lots if lot["status"] != "free")

    def where(lot_id):
        space = spaces.get(lot_id.split("#")[0], {})
        return f"{space.get('address', lot_id.split('#')[0])} · Lot {lot_number(lot_id)}"

    names = {}

    def name_of(user_id):
        if user_id not in names:
            names[user_id] = (b.get_user(user_id) or {}).get("name", user_id)
        return names[user_id]

    parked = sorted(b.list_open_sessions(), key=lambda s: s["start_time"])  # longest first
    for s in parked:
        station = spaces.get(s["lot_id"].split("#")[0], {}).get("address", "")
        s.update(where=where(s["lot_id"]), lot_label=f"Lot {lot_number(s['lot_id'])}", station=station,
                 owner=name_of(s["user_id"]), abandoned="overstay_notified_at" in s, ref=s["lot_id"].replace("#", "_"))

    # Unregistered bikes: bike in a free lot for too long, never used the system (derived, nothing stored)
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=config.UNREGISTERED_LIMIT_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
    unregistered = sorted(
        ({"lot_id": lot["id"], "lot_label": f"Lot {lot_number(lot['id'])}", "since": lot["bike_present_since"],
          "station": spaces.get(lot["space_id"], {}).get("address", "")}
         for lot in lots
         if lot["status"] == "free" and lot.get("bike_present") and lot.get("bike_present_since", "~") < cutoff),
        key=lambda r: r["since"])  # longest first

    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    tamper = b.list_tamper_events()
    for e in tamper:
        session = b.get_session(e["session_id"]) if e.get("session_id") else None
        e.update(where=where(e["lot_id"]), owner=name_of(session["user_id"]) if session else None)

    stations = []
    for sid, space in spaces.items():
        stations.append({
            "id": sid, "lat": space["lat"], "lng": space["lng"], "address": space["address"],
            "abandoned": sum(1 for s in parked if s["abandoned"] and s["lot_id"].startswith(sid + "#")),
            "unregistered": sum(1 for r in unregistered if r["lot_id"].startswith(sid + "#")),
        })

    return {
        "kpi": {
            "stations": len(spaces),
            "lots": len(lots),
            "utilisation": round(100 * occupied / len(lots)) if lots else 0,
            "occupied": occupied,
            "abandoned": sum(1 for s in parked if s["abandoned"]),
            "unregistered": len(unregistered),
            "tamper_week": sum(1 for e in tamper if e["detected_time"] >= week_ago),
            "last_tamper": tamper[0]["detected_time"] if tamper else None,
        },
        "parked": parked,
        "unregistered": unregistered,
        "tamper": tamper[:20],
        "stations": stations,
    }


@router.get("/officer")
def console(request: Request, confirm: str = "", done: str = "", failed: str = ""):
    user = require_officer(request)
    data = console_data()
    pending = next((s for s in data["parked"] if s["ref"] == confirm), None)
    m = config.UNREGISTERED_LIMIT_MINUTES
    limit = f"{m // 1440} day{'' if m // 1440 == 1 else 's'}" if m >= 1440 and m % 1440 == 0 else f"{m} min"
    return templates.TemplateResponse(request, "officer.html", {
        **data, "user": user, "confirm": pending, "done": done, "failed": failed, "unregistered_limit": limit,
    })


@router.get("/officer/data")
def console_refresh(request: Request):
    """Polled every 5 s by HTMX; returns the KPI cards and tables as out-of-band swaps."""
    require_officer(request)
    return templates.TemplateResponse(request, "_officer_data.html", console_data())


@router.get("/officer/stations.json")
def stations_json(request: Request):
    require_officer(request)
    return console_data()["stations"]


@router.post("/officer/force-unlock/{lot_ref}")
def force_unlock(request: Request, lot_ref: str):
    user = require_officer(request)
    keys = parse_lot_ref(lot_ref)
    b = get_backend()
    if keys and b.mark_releasing(*keys, user["id"], is_officer=True):
        b.publish_open(keys[1])
        return RedirectResponse(f"/officer?done={lot_ref}", status_code=303)
    return RedirectResponse(f"/officer?failed={lot_ref}", status_code=303)
