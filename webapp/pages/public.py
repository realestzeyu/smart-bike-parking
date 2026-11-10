"""J1: map of stations and the station sheet (no login needed)."""

import math

from fastapi import APIRouter, HTTPException, Request

from backend import get_backend
from backend.base import lot_number
from templating import templates

router = APIRouter()

# Browsers only give real location on HTTPS/localhost, so the demo uses a fixed
# "you are here" a short walk from Upper Changi MRT Exit C.
FAKE_POSITION = (1.3405, 103.9605)
NEARBY_METRES = 500
WALK_METRES_PER_MIN = 80


def distance_m(a, b):
    """Great-circle distance in metres between two (lat, lng) points."""
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


def summarise(space):
    """A station with its live counts, as shown on the map and in the sheet."""
    lots = sorted(get_backend().list_lots(space["id"]), key=lambda lot: int(lot_number(lot["id"])))
    total = len(lots)
    free = sum(1 for lot in lots if lot["status"] == "free")
    # Full = none free; few left = under a quarter free (matches "2 free" amber in the mockup).
    level = "full" if free == 0 else "few" if free < total / 4 else "ok"
    metres = distance_m(FAKE_POSITION, (space["lat"], space["lng"]))
    return {
        **space,
        "lots": lots,
        "free": free,
        "total": total,
        "level": level,
        "metres": round(metres / 10) * 10,
        "walk_min": max(1, math.ceil(metres / WALK_METRES_PER_MIN)),
    }


def pins():
    return [
        {k: s[k] for k in ("id", "lat", "lng", "free", "level")}
        for s in map(summarise, get_backend().list_spaces())
    ]


@router.get("/")
def map_page(request: Request):
    stations = pins()
    nearby = sum(1 for s in stations if distance_m(FAKE_POSITION, (s["lat"], s["lng"])) <= NEARBY_METRES)
    return templates.TemplateResponse(request, "map.html", {
        "stations": stations, "you": FAKE_POSITION, "nearby": nearby, "nearby_m": NEARBY_METRES,
    })


@router.get("/spaces.json")
def spaces_json():
    """Pin data, polled by the map every 5 s."""
    return pins()


@router.get("/space/{space_id}/sheet")
def station_sheet(request: Request, space_id: str):
    space = get_backend().get_space(space_id)
    if not space:
        raise HTTPException(status_code=404, detail="Station not found")
    return templates.TemplateResponse(request, "_station_sheet.html", {"s": summarise(space)})
